"""
NUSA-CROP : Titik masuk inference untuk backend.
=================================================

Dipakai backend seperti ini (root repo harus ada di sys.path):

    from ml_lib import NusaCropModel

    model = NusaCropModel()          # muat sekali saat startup, JANGAN per request
    hasil = model.recommend(
        ph=5.5, temp_c=27.3, elevation_m=31, soil_texture="clay loam",
        monthly_rain=[287, 266, 311, 218, 118, 98, 45, 31, 76, 152, 311, 285],
    )
    # hasil = [{"crop_code": "jagung", "confidence": 0.71, "skor_aturan": 78.4,
    #           "mulai_tanam": "Nov", "musim_tanam_mm": 1065, "rincian": {...},
    #           "skor_akhir": 78.4, "skor_per_bulan": [...12 angka...]}, ...]

Contoh di blok __main__ bawah dijalankan dgn `python -m ml_lib.predict` dari
root repo, BUKAN `python ml_lib/predict.py` (cara itu tidak menaruh root repo
di sys.path sehingga `import ml_lib` gagal).

`monthly_rain` adalah 12 angka mm/bulan (Januari..Desember). Ini WAJIB dan
tidak bisa diganti total setahun: seluruh perbaikan sistem bertumpu pada
mengetahui KAPAN hujannya turun, bukan hanya berapa banyak. Lihat
climate_features.py.

Dari mana backend mengambil datanya
-----------------------------------
  monthly_rain, temp_c : Open-Meteo Archive (ERA5)
      https://archive-api.open-meteo.com/v1/archive
        ?latitude={lat}&longitude={lon}
        &start_date=2022-01-01&end_date=2024-12-31
        &daily=precipitation_sum,temperature_2m_mean&timezone=auto
      Jumlahkan per bulan kalender, lalu rata-ratakan antar tahun
      (climate_features.monthly_from_daily sudah melakukannya).

  elevation_m : https://api.open-meteo.com/v1/elevation?latitude=..&longitude=..

  ph, soil_texture : SoilGrids v2.0
      https://rest.isric.org/soilgrids/v2.0/properties/query
        ?lon=..&lat=..&property=phh2o&property=sand&property=silt
        &property=clay&depth=5-15cm&value=mean
      WAJIB lewat soilgrids_adapter.parse_soilgrids_response() -- SoilGrids
      mengirim nilai sbg integer (pH 61 berarti 6.1). Lihat catatan di sana.

PENTING: pakai sumber yang SAMA dengan saat training. ERA5 dan NASA POWER
berselisih median 27% utk curah hujan dan sampai 5.9 C utk suhu pada 24
wilayah uji, jadi menukarnya akan menggeser semua rekomendasi diam-diam.

Skor dan confidence
-------------------
- `skor_aturan`, `rincian`, `mulai_tanam`, `musim_tanam_mm` selalu dari aturan
  (rule_based_scorer), untuk kesepuluh tanaman.
- `skor_akhir` dan `skor_per_bulan` hanya ada kalau PAKAI_SKOR_ML = True dan
  model_kecocokan.joblib berhasil dimuat. Lihat latih_kecocokan.py dan
  LAPORAN_ML.md untuk cara menghitungnya.
- `confidence` = kestabilan skor dan peringkat tiap tanaman kalau input
  digoyang sebesar ketidakpastiannya (Monte Carlo). Terisi untuk kesepuluh
  tanaman dan BUKAN probabilitas kecocokan.
- XGBoost lama (dilatih dari label aturan) tidak dipakai lagi; berkasnya
  dipindah ke arsip_model_lama/ di root repo.
"""

import os

import numpy as np

from ml_lib.climate_features import derive
from ml_lib.rule_based_scorer import (load_profiles, score_all_crops, score_crop,
                                      BULAN, _USDA_CENTROIDS, _texture_distance)

HERE = os.path.dirname(os.path.abspath(__file__))
NDVI_DEFAULT = 0.50

# Saklar skor ML. False (atau model gagal dimuat) -> recommend() tidak mengirim
# skor_akhir/skor_per_bulan, sehingga BE otomatis memakai skor_aturan.
PAKAI_SKOR_ML = True
MODEL_KECOCOKAN = "model_kecocokan.joblib"
# ML hanya boleh menggeser skor aturan paling banyak 30% ke bawah atau ke atas.
# ponytail: batas ini ditetapkan, bukan di-fit; sempitkan/lebarkan kalau label
# panen sudah ada untuk lebih dari satu tanaman.
KOREKSI_ML_MIN, KOREKSI_ML_MAKS = 0.7, 1.3

# --- Monte Carlo untuk confidence ---------------------------------------------
N_MC = 100
# pH terukur (uji tanah pengguna): galat alat/pengambilan contoh, +-0,2 (brief T3).
PH_GALAT_TERUKUR = 0.2
# Simpangan baku pH kalau BE tidak mengirim ph_q05/ph_q95: median
# (Q95 - Q05) / 3,29 SoilGrids 5-15 cm di titik kabupaten (tarik_fitur.py).
PH_SD_DEFAULT = 0.88
# Variasi antartahun curah hujan tahunan: median koefisien variasi 2022-2024
# di titik kabupaten (Open-Meteo ERA5).
CV_HUJAN = 0.14
# Peluang kelas tekstur sebenarnya adalah salah satu dari 2 kelas tetangga.
P_TEKSTUR_GESER = 0.3
# Batas "stabil": skor bergeser paling banyak 10 poin, peringkat paling banyak 1.
TOLERANSI_SKOR = 10.0
TOLERANSI_PERINGKAT = 1
# Pengali confidence tanaman ber-skor ML kalau input di luar rentang data latih.
FAKTOR_LUAR_RENTANG = 0.7


def koreksi_ml(p, p_acuan):
    """Pengali skor aturan dari probabilitas model: 1 kalau p = p_acuan
    (rata-rata data latih), dibatasi KOREKSI_ML_MIN..KOREKSI_ML_MAKS."""
    return np.clip(p / p_acuan, KOREKSI_ML_MIN, KOREKSI_ML_MAKS)


def _tetangga_tekstur(tekstur):
    lain = [t for t in _USDA_CENTROIDS if t != tekstur]
    return sorted(lain, key=lambda t: _texture_distance(tekstur, t))[:2]


class NusaCropModel:
    def __init__(self, base_dir=HERE):
        self.profiles = load_profiles(os.path.join(base_dir, "seed.json"))
        self.ml = None
        if PAKAI_SKOR_ML:
            try:
                import joblib
                self.ml = joblib.load(os.path.join(base_dir, MODEL_KECOCOKAN))
            except Exception:
                # Model tidak ada / versi pustaka tidak cocok: jatuh ke aturan.
                self.ml = None

    def build_land(self, ph, temp_c, elevation_m, soil_texture, monthly_rain,
                   ndvi=NDVI_DEFAULT):
        """Susun dict lahan lengkap dgn fitur musim."""
        if monthly_rain is None or len(monthly_rain) != 12:
            raise ValueError(
                "monthly_rain harus 12 angka mm/bulan (Jan..Des). "
                "Total setahun saja tidak cukup: sistem perlu tahu KAPAN hujan "
                "turun untuk menentukan waktu tanam."
            )
        musim = derive(list(monthly_rain))
        if musim is None:
            raise ValueError("monthly_rain berisi nilai kosong/tidak sah.")
        land = {"ph": ph, "temp_c": temp_c, "elevation_m": elevation_m,
                "soil_texture": soil_texture, "ndvi": ndvi,
                "monthly_rain": list(monthly_rain)}
        land.update(musim)
        return land

    def recommend_dua(self, ph, temp_c, elevation_m, soil_texture, monthly_rain,
                      bulan_sekarang, ndvi=NDVI_DEFAULT, top_k=None, **tambahan):
        """Dua daftar rekomendasi yang menjawab dua pertanyaan berbeda.

        {
          "kondisi_lahan": [...],   # apa yang paling cocok utk lahan ini,
                                    # bebas kapan pun ditanam
          "tanam_sekarang": [...],  # apa yang paling cocok kalau ditanam
                                    # mulai `bulan_sekarang`
          "bulan_sekarang": "Agu",
        }

        Keduanya perlu ditampilkan terpisah karena sering berbeda, tanaman
        terbaik untuk sebuah lahan bisa jadi baru layak ditanam empat bulan
        lagi. Daftar pertama menjawab "lahan saya cocoknya untuk apa",
        daftar kedua menjawab "saya mau tanam bulan ini, ambil yang mana".

        bulan_sekarang: 0-11 (0=Januari) atau nama singkat spt "Agu".
        `tambahan` diteruskan ke recommend() (sand_persen, ph_q05, dst.).
        """
        if isinstance(bulan_sekarang, str):
            bulan_sekarang = BULAN.index(bulan_sekarang)
        return {
            "kondisi_lahan": self.recommend(
                ph, temp_c, elevation_m, soil_texture, monthly_rain,
                ndvi=ndvi, top_k=top_k, **tambahan),
            "tanam_sekarang": self.recommend(
                ph, temp_c, elevation_m, soil_texture, monthly_rain,
                ndvi=ndvi, top_k=top_k, mulai=bulan_sekarang, **tambahan),
            "bulan_sekarang": BULAN[bulan_sekarang],
        }

    # ------------------------------------------------------------------ skor ML

    def _fitur_ml(self, lands):
        """Matriks fitur model kecocokan; urutan kolom = self.ml["fitur"]."""
        baris = []
        for land in lands:
            # Fraksi pasir/liat: dari BE kalau dikirim, kalau tidak dari titik
            # tengah kelas tekstur USDA.
            pasir, liat = _USDA_CENTROIDS.get(land["soil_texture"], (None, None))
            nilai = dict(land, sand_persen=land.get("sand_persen", pasir),
                         clay_persen=land.get("clay_persen", liat))
            baris.append([np.nan if nilai.get(f) is None else nilai[f]
                          for f in self.ml["fitur"]])
        return np.array(baris, dtype=float)

    def _p_ml(self, lands):
        X = self._fitur_ml(lands)
        return {kode: m.predict_proba(X)[:, 1] for kode, m in self.ml["model"].items()}

    def _skor_peringkat(self, lands, mulai):
        """Skor yang dipakai mengurutkan, bentuk (n_lahan, n_tanaman).

        Tanpa ML: skor_aturan. Dengan ML (hibrida):
            skor_akhir = skor_aturan x koreksi_ml(p)
        untuk tanaman yang punya model; tanaman lain skor_akhir = skor_aturan.
        Musim tanam (`mulai`) dan batas keras pH/hujan/suhu tetap dari aturan.
        """
        out = np.empty((len(lands), len(self.profiles)))
        p_ml = {} if self.ml is None else self._p_ml(lands)
        for i, land in enumerate(lands):
            for j, p in enumerate(self.profiles):
                skor = score_crop(land, p, mulai)[0]
                if p["crop_code"] in p_ml:
                    skor = min(100.0, skor * koreksi_ml(p_ml[p["crop_code"]][i],
                                                        self.ml["p_acuan"]))
                out[i, j] = skor
        return out

    def _di_luar_rentang(self, land):
        x = self._fitur_ml([land])[0]
        return any(not np.isnan(v) and not (lo <= v <= hi)
                   for v, (lo, hi) in zip(x, self.ml["rentang"]))

    # --------------------------------------------------------------- confidence

    def _goyang(self, land, ph_q05, ph_q95, ph_terukur, rng):
        """Satu lahan tiruan: input digeser sebesar ketidakpastiannya."""
        ph = land["ph"]
        if ph_terukur:
            ph_baru = ph + rng.uniform(-PH_GALAT_TERUKUR, PH_GALAT_TERUKUR)
        elif ph_q05 is not None and ph_q95 is not None and ph_q95 > ph_q05:
            # rentang 5-95% sebaran normal = 3,29 simpangan baku
            ph_baru = float(np.clip(rng.normal(ph, (ph_q95 - ph_q05) / 3.29), ph_q05, ph_q95))
        else:
            ph_baru = float(np.clip(rng.normal(ph, PH_SD_DEFAULT),
                                    ph - 2 * PH_SD_DEFAULT, ph + 2 * PH_SD_DEFAULT))
        faktor_hujan = float(np.exp(rng.normal(0.0, CV_HUJAN)))
        tekstur = land["soil_texture"]
        if rng.random() < P_TEKSTUR_GESER and tekstur in _USDA_CENTROIDS:
            tekstur = _tetangga_tekstur(tekstur)[int(rng.integers(2))]
        baru = self.build_land(ph_baru, land["temp_c"], land["elevation_m"], tekstur,
                               [m * faktor_hujan for m in land["monthly_rain"]],
                               land["ndvi"])
        if tekstur == land["soil_texture"]:
            for k in ("sand_persen", "clay_persen"):
                if k in land:
                    baru[k] = land[k]
        return baru

    def _confidence(self, land, mulai, ph_q05, ph_q95, ph_terukur):
        """Bagian simulasi yang skor dan peringkat tiap tanamannya tetap stabil."""
        rng = np.random.default_rng(0)      # tetap: input sama -> confidence sama
        lands = [land] + [self._goyang(land, ph_q05, ph_q95, ph_terukur, rng)
                          for _ in range(N_MC)]
        S = self._skor_peringkat(lands, mulai)
        peringkat = (-S).argsort(axis=1).argsort(axis=1)
        skor_stabil = (np.abs(S[1:] - S[0]) <= TOLERANSI_SKOR).mean(axis=0)
        peringkat_stabil = (np.abs(peringkat[1:] - peringkat[0])
                            <= TOLERANSI_PERINGKAT).mean(axis=0)
        return S[0], 0.5 * skor_stabil + 0.5 * peringkat_stabil

    # ---------------------------------------------------------------- recommend

    def recommend(self, ph, temp_c, elevation_m, soil_texture, monthly_rain,
                  ndvi=NDVI_DEFAULT, top_k=None, sort_by="akhir", mulai=None,
                  sand_persen=None, clay_persen=None,
                  ph_q05=None, ph_q95=None, ph_terukur=False):
        """Rekomendasi tanaman terurut, digabung dgn penjelasan aturan.

        mulai=None  -> cari waktu tanam terbaik sepanjang tahun.
        mulai=0..11 -> kunci waktu tanam pada bulan itu.

        sort_by="akhir"  -> urut skor_akhir kalau ada, kalau tidak skor_aturan.
        sort_by="aturan" -> selalu urut skor_aturan.

        Parameter tambahan dari BE (semua boleh tidak dikirim):
          sand_persen, clay_persen : fraksi tanah, fitur model kecocokan
          ph_q05, ph_q95, ph_terukur : ketidakpastian pH, untuk confidence
        """
        if isinstance(mulai, str):
            mulai = BULAN.index(mulai)
        land = self.build_land(ph, temp_c, elevation_m, soil_texture,
                               monthly_rain, ndvi)
        if sand_persen is not None and clay_persen is not None:
            land["sand_persen"], land["clay_persen"] = sand_persen, clay_persen

        aturan = {r["crop_code"]: r
                  for r in score_all_crops(land, self.profiles, mulai)}
        skor, conf = self._confidence(land, mulai, ph_q05, ph_q95, ph_terukur)
        luar = self.ml is not None and self._di_luar_rentang(land)
        per_bulan = (None if self.ml is None else
                     np.column_stack([self._skor_peringkat([land], m)[0] for m in range(12)]))

        hasil = []
        for j, p in enumerate(self.profiles):
            code = p["crop_code"]
            r = aturan[code]
            b = r["breakdown"]
            h = {
                "crop_code": code,
                "confidence": round(float(conf[j]), 3),
                "skor_aturan": r["score"],
                "mulai_tanam": b.get("mulai_tanam"),
                "musim_tanam_mm": b.get("musim_tanam_mm"),
                "rincian": {k: b[k] for k in
                            ("ph", "rainfall", "temp", "elevation", "texture")},
            }
            if self.ml is not None:
                dari_ml = code in self.ml["model"]
                h["skor_akhir"] = round(float(skor[j]), 2)
                h["skor_per_bulan"] = [round(float(v), 2) for v in per_bulan[j]]
                h["sumber_skor_tanaman"] = "ml" if dari_ml else "aturan"
                if dari_ml and luar:
                    h["di_luar_rentang_latih"] = True
                    h["confidence"] = round(h["confidence"] * FAKTOR_LUAR_RENTANG, 3)
            hasil.append(h)

        kunci = ("skor_akhir" if self.ml is not None and sort_by != "aturan"
                 else "skor_aturan")
        hasil.sort(key=lambda h: h[kunci], reverse=True)
        return hasil[:top_k] if top_k else hasil

    @property
    def tanaman_ml(self):
        """Tanaman yang skor aturannya dikoreksi model ML (sisanya aturan murni)."""
        return [] if self.ml is None else list(self.ml["model"])


if __name__ == "__main__":
    m = NusaCropModel()
    print("skor ML aktif:", m.ml is not None, "| tanaman ML:", m.tanaman_ml)
    grobogan = [287, 266, 311, 218, 118, 98, 45, 31, 76, 152, 311, 285]
    print("\nGrobogan, Jawa Tengah (sentra kacang hijau):")
    for h in m.recommend(ph=5.5, temp_c=27.3, elevation_m=31,
                         soil_texture="clay loam", monthly_rain=grobogan, top_k=5):
        akhir = h.get("skor_akhir", "-")
        print(f"  {h['crop_code']:16} akhir {akhir}  aturan {h['skor_aturan']:5.1f}  "
              f"confidence {h['confidence']:.2f}  tanam {h['mulai_tanam']} "
              f"({h['musim_tanam_mm']} mm)")
