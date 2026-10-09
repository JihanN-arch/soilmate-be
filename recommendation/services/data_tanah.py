"""Penentuan data tanah: uji tanah pengguna > SoilGrids > cache > tetangga.

Penanganan saat SoilGrids down / datanya tidak lengkap:
- API down          -> cache kedaluwarsa di sel yang sama, lalu sel tetangga
                       dalam radius 1 km (lihat services/cache.py).
- piksel kosong     -> SoilGrids mengembalikan null untuk area permukiman,
  (null)               badan air, dsb. Dicoba 4 titik di sekitarnya (~280 m),
                       lalu tiap field yang masih kosong diisi dari sel cache
                       tetangga, per field.
- tetap tidak ada   -> DataTidakLengkap(butuh_input=[...]) sehingga FE bisa
                       meminta pengguna mengisi hasil uji tanah. TIDAK ada
                       lagi data palsu (mock) yang diam-diam dipakai.
"""
import logging

from ml_lib.rule_based_scorer import _USDA_CENTROIDS

from . import cache
from .apis import soilgrids
from .errors import DataTidakLengkap, SumberDataGagal

logger = logging.getLogger(__name__)

# nama kelas tekstur yang biasa dipakai di Indonesia -> USDA
TEKSTUR_ID_KE_USDA = {
    "pasir": "sand",
    "pasir berlempung": "loamy sand",
    "lempung berpasir": "sandy loam",
    "lempung": "loam",
    "lempung berdebu": "silt loam",
    "debu": "silt",
    "lempung liat berpasir": "sandy clay loam",
    "lempung berliat": "clay loam",
    "lempung liat berdebu": "silty clay loam",
    "liat berpasir": "sandy clay",
    "liat berdebu": "silty clay",
    "liat": "clay",
}
USDA_KE_ID = {v: k for k, v in TEKSTUR_ID_KE_USDA.items()}
KELAS_USDA = set(_USDA_CENTROIDS)

FIELD_TANAH = ["ph", "sand", "silt", "clay", "nitrogen", "organic_carbon"]
OFFSET = 0.0025  # derajat, ~280 m


def normalisasi_tekstur(nilai):
    if not nilai:
        return None
    n = str(nilai).strip().lower()
    if n in KELAS_USDA:
        return n
    return TEKSTUR_ID_KE_USDA.get(n)


def normalisasi_uji_tanah(uji):
    """Dict uji tanah (sudah divalidasi serializer) -> nilai dalam satuan sistem."""
    if not uji:
        return {}
    hasil = {}
    if uji.get("ph") is not None:
        hasil["ph"] = float(uji["ph"])
    fraksi = [uji.get(k) for k in ("sand", "silt", "clay")]
    if all(v is not None for v in fraksi):
        hasil.update(sand=float(fraksi[0]), silt=float(fraksi[1]), clay=float(fraksi[2]))
        hasil["tekstur_kelas"] = soilgrids.tekstur_dari_fraksi(hasil)
    elif uji.get("tekstur_kelas"):
        hasil["tekstur_kelas"] = normalisasi_tekstur(uji["tekstur_kelas"])
    if uji.get("c_organik_persen") is not None:
        hasil["organic_carbon"] = float(uji["c_organik_persen"]) * 10  # % -> g/kg
    if uji.get("nitrogen_persen") is not None:
        hasil["nitrogen"] = float(uji["nitrogen_persen"]) * 10
    return hasil


def _lengkap(p):
    return bool(p) and p.get("ph") is not None and p.get("tekstur_kelas") is not None


def _fetch_dengan_sekitar(lat, lon):
    data = soilgrids.fetch_tanah(lat, lon)
    if _lengkap(data):
        return data
    terisi = []
    for dlat, dlon in ((OFFSET, 0), (-OFFSET, 0), (0, OFFSET), (0, -OFFSET)):
        try:
            alt = soilgrids.fetch_tanah(lat + dlat, lon + dlon, cepat=True)
        except SumberDataGagal:
            continue
        for f in FIELD_TANAH + ["ph_q05", "ph_q95"]:
            if data.get(f) is None and alt.get(f) is not None:
                data[f] = alt[f]
                terisi.append(f)
        data["tekstur_kelas"] = data.get("tekstur_kelas") or soilgrids.tekstur_dari_fraksi(data)
        if _lengkap(data):
            break
    if terisi:
        data["_terisi_dari_sekitar"] = sorted(set(terisi))
    return data


def resolve_tanah(lat, lon, uji_tanah=None):
    """Mengembalikan (data, asal_per_field, catatan)."""
    uji = normalisasi_uji_tanah(uji_tanah)
    data, asal, catatan = {}, {}, []

    for f, v in uji.items():
        if v is not None:
            data[f] = v
            asal["tekstur" if f == "tekstur_kelas" else f] = "uji_tanah"

    payload, asal_api = None, None
    if not _lengkap(data):
        try:
            payload, asal_api, info = cache.ambil_atau_fetch(
                "tanah", lat, lon, _fetch_dengan_sekitar, syarat_tetangga=_lengkap)
            if asal_api != "api" and asal_api != "cache":
                catatan.append("SoilGrids sedang tidak dapat diakses; data tanah memakai "
                               + ("cache lama." if asal_api == "cache_kedaluwarsa"
                                  else f"lokasi terdekat ({info.get('jarak_km')} km)."))
        except SumberDataGagal as e:
            logger.warning("Data tanah tidak tersedia: %s", e)
    else:
        ada = cache.ambil("tanah", lat, lon)  # info tambahan (N, C) kalau kebetulan ada
        if ada:
            payload, asal_api = ada[0], "cache"

    if payload:
        dari_sekitar = set(payload.get("_terisi_dari_sekitar", []))
        for f in FIELD_TANAH + ["ph_q05", "ph_q95"]:
            if data.get(f) is None and payload.get(f) is not None:
                data[f] = payload[f]
                if f in FIELD_TANAH:
                    asal[f] = "api_sekitar" if f in dari_sekitar else asal_api
        if data.get("tekstur_kelas") is None and payload.get("tekstur_kelas"):
            data["tekstur_kelas"] = payload["tekstur_kelas"]
            asal["tekstur"] = "api_sekitar" if dari_sekitar & {"sand", "silt", "clay"} else asal_api

    # isi field wajib yang masih kosong dari sel tetangga, per field
    for f, cek in (("ph", lambda p: p.get("ph") is not None),
                   ("tekstur_kelas", lambda p: p.get("tekstur_kelas") is not None)):
        if data.get(f) is None:
            dekat = cache.tetangga("tanah", lat, lon, syarat=cek)
            if dekat:
                data[f] = dekat[0][f]
                if f == "tekstur_kelas":
                    for k in ("sand", "silt", "clay"):
                        data.setdefault(k, dekat[0].get(k))
                asal["tekstur" if f == "tekstur_kelas" else f] = "tetangga"
                catatan.append(f"{'pH' if f == 'ph' else 'Tekstur'} tanah diambil dari "
                               f"lokasi terdekat ({dekat[1]:.1f} km).")

    kurang = [n for f, n in (("ph", "ph"), ("tekstur_kelas", "tekstur_kelas")) if data.get(f) is None]
    if kurang:
        raise DataTidakLengkap(
            "Data tanah untuk lokasi ini belum tersedia. Isi hasil uji tanah "
            "(pH dan tekstur) supaya analisis tetap bisa dilakukan.",
            butuh_input=kurang)

    if any(asal.get(k) not in (None, "uji_tanah") for k in ("ph", "tekstur")):
        catatan.append("pH/tekstur tanah adalah estimasi SoilGrids (resolusi ~250 m). "
                       "Hasil uji tanah akan membuat rekomendasi lebih akurat.")
    return data, asal, catatan
