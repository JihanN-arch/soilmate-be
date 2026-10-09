"""Pembungkus NusaCropModel untuk backend.

KONTRAK DENGAN TIM ML (ringkas; lengkapnya di dokumen permintaan ke ML)
----------------------------------------------------------------------
Input wajib ke recommend(): ph, temp_c, elevation_m, soil_texture,
monthly_rain (12), top_k, mulai.

Input tambahan (FITUR_TAMBAHAN) hanya dikirim kalau recommend() punya
parameter dengan nama itu (atau **kwargs) DAN nilainya tersedia. Jadi tim
ML bisa menambah fitur kapan saja tanpa BE diubah.

Output per tanaman yang dipakai BE:
  wajib   : crop_code, skor_aturan (0-100), rincian, mulai_tanam, musim_tanam_mm,
            confidence (0-1 atau None)
  opsional: skor_akhir (0-100)    -> kalau ada, dipakai untuk urutan & skor
            skor_per_bulan (12)   -> kalau tidak ada, BE menghitungnya sendiri
                                     dengan memanggil recommend(mulai=0..11)

NDVI sengaja TIDAK dikirim ke parameter `ndvi` (di training masih sintetik).
NDVI asli tersedia sebagai `ndvi_aktual` kalau model menerimanya.
"""
import inspect

from ml_lib import NusaCropModel

from ..services.errors import PrediksiGagal

_model = NusaCropModel()
_profil = {p["crop_code"]: p for p in _model.profiles}


def _parameter_model():
    sig = inspect.signature(_model.recommend)
    terima_semua = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    return set(sig.parameters), terima_semua


_PARAMS, _TERIMA_KWARGS = _parameter_model()

# nama parameter -> cara mengambil nilainya dari kondisi_lahan
FITUR_TAMBAHAN = {
    "ndvi_aktual": lambda k: k.get("ndvi"),
    "kemiringan_derajat": lambda k: k.get("kemiringan"),
    "nitrogen_gkg": lambda k: k.get("nitrogen"),
    "organic_carbon_gkg": lambda k: k.get("organic_carbon"),
    "sand_persen": lambda k: (k.get("tekstur_tanah") or {}).get("sand"),
    "silt_persen": lambda k: (k.get("tekstur_tanah") or {}).get("silt"),
    "clay_persen": lambda k: (k.get("tekstur_tanah") or {}).get("clay"),
    "et0_tahunan_mm": lambda k: k.get("et0"),
    "ph_q05": lambda k: (k.get("ph_rentang") or [None, None])[0],
    "ph_q95": lambda k: (k.get("ph_rentang") or [None, None])[1],
    "ph_terukur": lambda k: (k.get("sumber_data") or {}).get("ph") == "uji_tanah",
}


def get_profile(slug):
    return _profil.get(slug)


def kelas_model():
    return set(_model.kelas_model)


def tahunan(slug):
    return (_profil.get(slug) or {}).get("cycle_months", 0) >= 12


def skor_efektif(h):
    """Skor yang dipakai untuk urutan & tampilan (0-100)."""
    return h["skor_akhir"] if h.get("skor_akhir") is not None else h["skor_aturan"]


def _fitur_tambahan(kondisi):
    hasil = {}
    for nama, ambil in FITUR_TAMBAHAN.items():
        if nama in _PARAMS or _TERIMA_KWARGS:
            nilai = ambil(kondisi)
            if nilai is not None:
                hasil[nama] = nilai
    return hasil


def _peringkat_ml(hasil):
    """{crop_code: peringkat_ML (1 = tertinggi)} untuk tanaman yang dikenal model."""
    dikenal = [h for h in hasil if h.get("confidence") is not None]
    dikenal.sort(key=lambda h: h["confidence"], reverse=True)
    return {h["crop_code"]: i for i, h in enumerate(dikenal, start=1)}


def predict(kondisi_lahan, bulan_tanam=None, top_k=5):
    """bulan_tanam: 1-12 atau None.

    Mengembalikan:
      {"rekomendasi": [...top_k...], "rekomendasi_bulan_tanam": [...] | None,
       "bulan_tanam": "Okt" | None}
    Setiap item punya `skor_per_bulan` (12 nilai 0-100, indeks 0 = Jan) atau
    None untuk tanaman tahunan.
    """
    argumen = dict(
        ph=kondisi_lahan["ph_tanah"],
        temp_c=kondisi_lahan["suhu"],
        elevation_m=kondisi_lahan["elevasi"],
        soil_texture=kondisi_lahan["tekstur_kelas"],
        monthly_rain=kondisi_lahan["curah_hujan_bulanan"],
        **_fitur_tambahan(kondisi_lahan),
    )
    try:
        semua = _model.recommend(**argumen, top_k=None)
        perlu_kalender = any(h.get("skor_per_bulan") is None for h in semua)
        per_bulan = ([_model.recommend(**argumen, top_k=None, mulai=i) for i in range(12)]
                     if perlu_kalender or bulan_tanam else None)
    except ValueError as e:
        raise PrediksiGagal(f"Model gagal memproses data: {e}") from e

    if per_bulan and perlu_kalender:
        skor_bulan = {}
        for daftar in per_bulan:
            for h in daftar:
                skor_bulan.setdefault(h["crop_code"], []).append(round(skor_efektif(h), 2))
        for h in semua:
            if h.get("skor_per_bulan") is None:
                h["skor_per_bulan"] = skor_bulan.get(h["crop_code"])

    semua.sort(key=skor_efektif, reverse=True)
    peringkat = _peringkat_ml(semua)
    kalender = {h["crop_code"]: h.get("skor_per_bulan") for h in semua}

    daftar_bulan, bulan = None, None
    if bulan_tanam:
        daftar_bulan = sorted(per_bulan[int(bulan_tanam) - 1], key=skor_efektif, reverse=True)[:top_k]
        bulan = daftar_bulan[0]["mulai_tanam"] if daftar_bulan else None

    for daftar in (semua, daftar_bulan or []):
        for h in daftar:
            h["peringkat_ml"] = peringkat.get(h["crop_code"])
            h["skor_per_bulan"] = kalender.get(h["crop_code"])
            # Tanaman tahunan (kemiri): semua jendela hujan sama, jadi bulan tanam
            # terbaik & kalender dari scorer tidak bermakna.
            if tahunan(h["crop_code"]):
                h["mulai_tanam"] = None
                h["skor_per_bulan"] = None

    return {
        "rekomendasi": semua[:top_k] if top_k else semua,
        "rekomendasi_bulan_tanam": daftar_bulan,
        "bulan_tanam": bulan,
    }
