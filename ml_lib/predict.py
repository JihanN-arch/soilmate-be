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
    # hasil = [{"crop_code": "jagung", "confidence": 0.93, "skor_aturan": 78.4,
    #           "mulai_tanam": "Nov", "musim_tanam_mm": 1065, "rincian": {...}}, ...]

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

Keterbatasan yang harus ditampilkan/dicatat
-------------------------------------------
- Model hanya mengenali 8 dari 10 tanaman. `kacang_hijau` dan `terong` tidak
  ada di kelas keluaran ML. Keduanya TETAP dinilai oleh skor aturan, jadi
  `skor_aturan` bisa dipakai backend sebagai cadangan bila ingin menampilkan
  kesepuluh tanaman.
- ndvi masih fitur sintetik (turunan curah hujan), pengaruhnya ~0.
  Biarkan pada nilai bawaan sampai NDVI sungguhan tersedia.
"""

import os

import joblib
import pandas as pd
from xgboost import XGBClassifier

from ml_lib.climate_features import derive
from ml_lib.preprocess import NUMERIC_FEATURES, CATEGORICAL_FEATURES
from ml_lib.rule_based_scorer import load_profiles, score_all_crops, BULAN

HERE = os.path.dirname(os.path.abspath(__file__))
FEATURE_ORDER = NUMERIC_FEATURES + CATEGORICAL_FEATURES
NDVI_DEFAULT = 0.50


class NusaCropModel:
    def __init__(self, base_dir=HERE):
        self.preprocessor = joblib.load(os.path.join(base_dir, "preprocessor.joblib"))
        self.model = XGBClassifier()
        self.model.load_model(os.path.join(base_dir, "model_xgb.json"))
        # n_jobs tidak ikut tersimpan di JSON; set eksplisit supaya tiap worker
        # API tidak berebut seluruh core.
        self.model.set_params(n_jobs=1)
        self.classes = joblib.load(os.path.join(base_dir, "label_encoder.joblib")).classes_
        self.profiles = load_profiles(os.path.join(base_dir, "seed.json"))

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
                      bulan_sekarang, ndvi=NDVI_DEFAULT, top_k=None):
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
        """
        if isinstance(bulan_sekarang, str):
            bulan_sekarang = BULAN.index(bulan_sekarang)
        return {
            "kondisi_lahan": self.recommend(
                ph, temp_c, elevation_m, soil_texture, monthly_rain,
                ndvi=ndvi, top_k=top_k),
            "tanam_sekarang": self.recommend(
                ph, temp_c, elevation_m, soil_texture, monthly_rain,
                ndvi=ndvi, top_k=top_k, mulai=bulan_sekarang),
            "bulan_sekarang": BULAN[bulan_sekarang],
        }

    def recommend(self, ph, temp_c, elevation_m, soil_texture, monthly_rain,
                  ndvi=NDVI_DEFAULT, top_k=None, sort_by="aturan", mulai=None):
        """Rekomendasi tanaman terurut, digabung dgn penjelasan aturan.

        mulai=None  -> cari waktu tanam terbaik sepanjang tahun.
        mulai=0..11 -> kunci waktu tanam pada bulan itu.
        """
        if isinstance(mulai, str):
            mulai = BULAN.index(mulai)
        land = self.build_land(ph, temp_c, elevation_m, soil_texture,
                               monthly_rain, ndvi)

        X = pd.DataFrame([land])[FEATURE_ORDER]
        proba = self.model.predict_proba(self.preprocessor.transform(X))[0]
        conf = {c: float(p) for c, p in zip(self.classes, proba)}

        aturan = {r["crop_code"]: r
                  for r in score_all_crops(land, self.profiles, mulai)}

        hasil = []
        for code, r in aturan.items():
            b = r["breakdown"]
            hasil.append({
                "crop_code": code,
                # None = tanaman ini tidak ada di kelas model (lihat docstring)
                "confidence": conf.get(code),
                "skor_aturan": r["score"],
                "mulai_tanam": b.get("mulai_tanam"),
                "musim_tanam_mm": b.get("musim_tanam_mm"),
                "rincian": {k: b[k] for k in
                            ("ph", "rainfall", "temp", "elevation", "texture")},
            })
        # Urutan bawaan memakai SKOR ATURAN, bukan confidence ML. Alasannya:
        #
        # 1. Confidence ML nyaris biner. Karena label training dihasilkan
        #    rule_based_scorer yang deterministik, model belajar memetakan
        #    lahan -> satu pemenang dgn sangat yakin. Contoh nyata di Grobogan:
        #    kemiri 99.9%, sembilan tanaman lain 0.0%. Untuk tampilan Top-3
        #    itu tidak memberi informasi apa pun di peringkat 2 dan 3.
        #    Skor aturan di lahan yang sama: 92.4 / 90.1 / 83.8 / 82.3 / 80.5.
        # 2. kacang_hijau dan terong tidak ada di kelas model. Mengurutkan
        #    dengan confidence akan selalu melempar keduanya ke dasar daftar
        #    tanpa memandang kecocokan sebenarnya.
        #
        # confidence tetap disertakan supaya backend bisa menampilkan atau
        # memakainya; pakai sort_by="ml" bila memang diinginkan.
        if sort_by == "ml":
            hasil.sort(key=lambda h: (h["confidence"] if h["confidence"] is not None
                                      else -1, h["skor_aturan"]), reverse=True)
        else:
            hasil.sort(key=lambda h: h["skor_aturan"], reverse=True)
        return hasil[:top_k] if top_k else hasil

    @property
    def kelas_model(self):
        """Tanaman yang dikenali model ML (8 dari 10)."""
        return list(self.classes)


if __name__ == "__main__":
    m = NusaCropModel()
    print("kelas model:", m.kelas_model)
    grobogan = [287, 266, 311, 218, 118, 98, 45, 31, 76, 152, 311, 285]
    print("\nGrobogan, Jawa Tengah (sentra kacang hijau):")
    for h in m.recommend(ph=5.5, temp_c=27.3, elevation_m=31,
                         soil_texture="clay loam", monthly_rain=grobogan, top_k=5):
        c = "-" if h["confidence"] is None else f"{h['confidence']*100:5.1f}%"
        print(f"  {h['crop_code']:16} ML {c}  aturan {h['skor_aturan']:5.1f}  "
              f"tanam {h['mulai_tanam']} ({h['musim_tanam_mm']} mm)")
