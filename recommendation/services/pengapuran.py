"""Simulasi pengapuran (BE): "kalau lahan ini dikapur, rekomendasinya jadi apa?"

PEMBAGIAN TUGAS
---------------
- Tim ML  : membuat `ml_lib/pengapuran.py` dengan fungsi `simulasi(...)`
            (kontrak di bawah). Isinya: perhitungan perubahan pH dari dosis
            kapur, atau dosis yang dibutuhkan untuk mencapai target pH.
- BE (ini): memanggil fungsi itu, menilai ulang SEMUA tanaman dengan pH baru
            memakai model yang sama, lalu menghitung kebutuhan kapur total
            untuk luas lahan petani dan biayanya.

Dua mode input:
  1. dari riwayat analisis (riwayat_id): kondisi lahan lengkap -> skor ulang.
  2. data tanah sendiri (uji_tanah, lat/lon opsional):
       - ada lat/lon  -> iklim & elevasi dari cache/API (dengan cadangan),
                         tekstur dari SoilGrids kalau tidak diisi -> skor ulang.
       - tanpa lat/lon -> hanya dosis & pH baru; perubahan_skor dan
                         rekomendasi_baru berupa list kosong.

Selama `ml_lib/pengapuran.py` belum ada, endpoint membalas 501 dan FE bisa
menampilkan "fitur segera hadir". Tidak ada angka karangan.

KONTRAK FUNGSI ML
-----------------
    def simulasi(ph_awal, tekstur_kelas, organic_carbon=None, al_dd=None,
                 dosis_ton_ha=None, target_ph=None, jenis_kapur="dolomit") -> dict

    Input:
      ph_awal        float, pH tanah saat ini
      tekstur_kelas  str | None, kelas USDA ("clay loam", ...). Bisa None kalau
                     pengguna mengisi data tanah sendiri tanpa tekstur.
      organic_carbon float | None, g/kg
      al_dd          float | None, cmol(+)/kg. Saat ini BE belum punya data
                     Al-dd, jadi selalu None; boleh diestimasi di dalam fungsi.
      dosis_ton_ha   float | None  } tepat SATU yang diisi
      target_ph      float | None  }
      jenis_kapur    "dolomit" | "kalsit" | "kapur_tohor"

    Output (dict):
      ph_baru        float, perkiraan pH setelah pengapuran   (wajib)
      dosis_ton_ha   float, dosis per hektar                  (wajib)
      catatan        list[str], penjelasan/batasan            (opsional)
      ...field lain boleh ditambahkan; diteruskan apa adanya ke FE di "detail_ml".

    Lempar ValueError untuk input yang tidak masuk akal (mis. target_ph < ph_awal).
"""
from django.conf import settings

from ..ml.ml_model import predict, skor_efektif
from ..models.crop_models import Crop
from ..utils.formatter import format_daftar
from .data_tanah import normalisasi_uji_tanah
from .errors import DataTidakLengkap, PrediksiGagal, SumberDataGagal


def _muat_harga_kapur():
    """{jenis: {min, maks, tanggal, kemasan, sumber}} dari data/harga_kapur.csv."""
    import csv
    from pathlib import Path
    path = Path(settings.BASE_DIR) / "data" / "harga_kapur.csv"
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r["jenis_kapur"]: {"min": int(r["harga_min_per_kg"]), "maks": int(r["harga_maks_per_kg"]),
                                   "tanggal": r.get("tanggal"), "kemasan": r.get("kemasan"),
                                   "sumber": r.get("sumber")}
                for r in csv.DictReader(f)}


HARGA_KAPUR = _muat_harga_kapur()


def _harga_kapur(jenis):
    """Env HARGA_KAPUR_PER_KG (satu angka, semua jenis) mengalahkan data CSV."""
    tetap = getattr(settings, "HARGA_KAPUR_PER_KG", None)
    if tetap:
        return {"min": tetap, "maks": tetap, "tanggal": None, "kemasan": None,
                "sumber": "env HARGA_KAPUR_PER_KG"}
    return HARGA_KAPUR.get(jenis)


class PengapuranBelumTersedia(Exception):
    pass


class RiwayatTidakLengkap(Exception):
    pass


def _fungsi_ml():
    """(fungsi, mode_contoh). Modul asli tim ML selalu diutamakan."""
    try:
        from ml_lib.pengapuran import simulasi
        return simulasi, False
    except ImportError as e:
        if getattr(settings, "NUSACROP_PENGAPURAN_CONTOH", False):
            from .pengapuran_contoh import simulasi as contoh
            return contoh, True
        raise PengapuranBelumTersedia("Modul pengapuran dari tim ML belum tersedia.") from e


def _kondisi_dari_riwayat(r, ph=None):
    if not r.curah_hujan_bulanan or not r.tekstur_kelas:
        raise RiwayatTidakLengkap(
            "Riwayat ini dibuat sebelum fitur simulasi ada. Lakukan analisis ulang untuk lokasi ini.")
    return {
        "ph_tanah": r.ph_tanah if ph is None else ph,
        "suhu": r.suhu, "elevasi": r.elevasi, "tekstur_kelas": r.tekstur_kelas,
        "curah_hujan_bulanan": r.curah_hujan_bulanan,
        "kualitas_data": {"skor": r.kualitas_data or 0.8},
        "luas_lahan_m2": r.luas_lahan_m2,
    }


def _kondisi_dari_lokasi(lat, lon, uji_tanah, ph_awal, tekstur):
    """Kondisi lahan untuk mode 'isi data tanah sendiri' + lokasi.
    Mengembalikan (kondisi | None, tekstur, catatan)."""
    from .data_tanah import resolve_tanah
    from .environment_service import _hitung_kualitas, resolve_iklim, resolve_satelit

    catatan = []
    asal = {"ph": "uji_tanah", "tekstur": "uji_tanah" if tekstur else None}
    try:
        iklim, asal["iklim"], cat = resolve_iklim(lat, lon)
        catatan += cat
    except SumberDataGagal:
        return None, tekstur, ["Data iklim lokasi tidak tersedia; hanya dosis kapur yang dihitung."]

    try:
        sat, asal["elevasi"], cat = resolve_satelit(lat, lon)
        elevasi = sat["elevasi_m"]
        catatan += cat
    except SumberDataGagal:
        if iklim.get("elevasi_m") is None:
            return None, tekstur, ["Data elevasi tidak tersedia; hanya dosis kapur yang dihitung."]
        elevasi, asal["elevasi"] = round(iklim["elevasi_m"]), "open_meteo_dem"

    if not tekstur:
        try:
            tanah, asal_tanah, cat = resolve_tanah(lat, lon, uji_tanah)
            tekstur, asal["tekstur"] = tanah["tekstur_kelas"], asal_tanah.get("tekstur")
            catatan += [c for c in cat if "uji tanah" not in c.lower()]
        except (DataTidakLengkap, SumberDataGagal):
            return None, None, ["Tekstur tanah tidak diisi dan tidak tersedia untuk lokasi ini; "
                                "hanya dosis kapur yang dihitung."]

    skor, _ = _hitung_kualitas(asal)
    return {
        "ph_tanah": ph_awal, "suhu": iklim["suhu_rata_rata"], "elevasi": elevasi,
        "tekstur_kelas": tekstur, "curah_hujan_bulanan": iklim["curah_hujan_bulanan"],
        "kualitas_data": {"skor": skor},
    }, tekstur, catatan


def simulasi_kapur(riwayat=None, uji_tanah=None, lat=None, lon=None, dosis_ton_ha=None,
                   target_ph=None, jenis_kapur="dolomit", luas_lahan_m2=None):
    simulasi, mode_contoh = _fungsi_ml()   # 501 lebih dulu, sebelum memanggil API apa pun
    catatan_data = []

    if riwayat is not None:
        kondisi_awal = _kondisi_dari_riwayat(riwayat)
        ph_awal, tekstur = riwayat.ph_tanah, riwayat.tekstur_kelas
        # C-organik hanya dikirim kalau dari uji tanah (permintaan tim ML: nilai
        # SoilGrids terlalu tinggi untuk rumus kapur dan menggandakan dosis).
        oc = (riwayat.organic_carbon
              if (riwayat.sumber_data or {}).get("organic_carbon") == "uji_tanah" else None)
        luas = luas_lahan_m2 or riwayat.luas_lahan_m2
    else:
        uji = normalisasi_uji_tanah(uji_tanah)
        ph_awal, tekstur, oc = uji["ph"], uji.get("tekstur_kelas"), uji.get("organic_carbon")
        luas = luas_lahan_m2
        kondisi_awal = None
        if lat is not None and lon is not None:
            kondisi_awal, tekstur, catatan_data = _kondisi_dari_lokasi(lat, lon, uji_tanah, ph_awal, tekstur)
        else:
            catatan_data = ["Tanpa lokasi, perubahan kecocokan tanaman tidak dihitung."]

    try:
        hasil_ml = simulasi(
            ph_awal=ph_awal, tekstur_kelas=tekstur, organic_carbon=oc, al_dd=None,
            dosis_ton_ha=dosis_ton_ha, target_ph=target_ph, jenis_kapur=jenis_kapur)
        ph_baru = float(hasil_ml["ph_baru"])
        dosis = float(hasil_ml["dosis_ton_ha"])
    except (KeyError, TypeError, ValueError) as e:
        raise PrediksiGagal(f"Simulasi pengapuran gagal: {e}") from e

    perubahan, rekomendasi_baru = [], []
    if kondisi_awal is not None:
        kondisi_awal["luas_lahan_m2"] = luas
        kondisi_baru = {**kondisi_awal, "ph_tanah": ph_baru}
        sebelum = {h["crop_code"]: skor_efektif(h)
                   for h in predict(kondisi_awal, top_k=None)["rekomendasi"]}
        baru = predict(kondisi_baru, top_k=None)["rekomendasi"]
        nama = dict(Crop.objects.values_list("slug", "nama"))
        perubahan = sorted(
            ({"id": h["crop_code"], "crop_slug": h["crop_code"],
              "nama": nama.get(h["crop_code"], h["crop_code"]),
              "sebelum": round(sebelum.get(h["crop_code"], 0) / 100, 2),
              "sesudah": round(skor_efektif(h) / 100, 2),
              "selisih": round((skor_efektif(h) - sebelum.get(h["crop_code"], 0)) / 100, 2)}
             for h in baru),
            key=lambda x: x["sesudah"], reverse=True)
        rekomendasi_baru = format_daftar(baru[:5], kondisi_baru)

    total_kg = round(dosis * 1000 * luas / 10_000) if luas else None
    harga = _harga_kapur(jenis_kapur)
    biaya_rentang = ({"min": round(total_kg * harga["min"]), "max": round(total_kg * harga["maks"])}
                     if harga and total_kg else None)
    biaya_ha = ({"min": round(dosis * 1000 * harga["min"]), "max": round(dosis * 1000 * harga["maks"])}
                if harga else None)

    return {
        # True = angka dari modul CONTOH, bukan model; FE wajib menampilkan label
        "mode_contoh": mode_contoh,
        "ph_awal": ph_awal,
        "ph_baru": round(ph_baru, 2),
        "jenis_kapur": jenis_kapur,
        "kebutuhan_kapur": {
            "dosis_ton_ha": round(dosis, 2),
            "luas_lahan_m2": luas,
            "total_kg": total_kg,
            # rentang harga & biaya (pakai ini); None kalau harga jenis kapur ini belum ada
            "harga_per_kg_rentang": {"min": harga["min"], "max": harga["maks"]} if harga else None,
            "perkiraan_biaya_rentang": biaya_rentang,          # untuk luas lahan
            "perkiraan_biaya_per_ha_rentang": biaya_ha,
            "sumber_harga": harga["sumber"] if harga else None,
            "tanggal_harga": harga["tanggal"] if harga else None,
            "kemasan": harga["kemasan"] if harga else None,
            # lama (satu angka = nilai tengah rentang), dipertahankan untuk FE lama
            "harga_per_kg": round((harga["min"] + harga["maks"]) / 2) if harga else None,
            "perkiraan_biaya": (round((biaya_rentang["min"] + biaya_rentang["max"]) / 2)
                                if biaya_rentang else None),
        },
        "perubahan_skor": perubahan,
        "rekomendasi_baru": rekomendasi_baru,
        "detail_ml": {k: v for k, v in hasil_ml.items()
                      if k not in ("ph_baru", "dosis_ton_ha", "catatan")},
        # catatan dari modul ML sudah ditulis untuk petani; tampilkan di depan
        "catatan": catatan_data + list(hasil_ml.get("catatan") or []) + (
            [f"Harga {jenis_kapur.replace('_', ' ')} belum tersedia, jadi perkiraan biaya tidak dihitung."]
            if not harga else
            [f"Harga kapur dari {harga['sumber']} ({harga['kemasan'] or 'per kg'}), bisa berbeda "
             "menurut lokasi dan ongkos kirim."]) + [
            "Efek kapur butuh beberapa minggu dan perlu diulang berkala."],
    }
