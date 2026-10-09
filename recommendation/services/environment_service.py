"""Kumpulkan kondisi lahan dari tiga sumber secara paralel.

Setiap sumber punya rantai cadangan sendiri (lihat cache.py & data_tanah.py),
dan asal setiap nilai dicatat di `sumber_data` supaya FE bisa menampilkan
badge "terukur / estimasi / cadangan" dan peringatan kalau perlu.
"""
import logging
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.db import connection

from ..utils.fertility import calculate_fertility
from . import cache
from .apis import gee, openmeteo
from .data_tanah import resolve_tanah
from .errors import DataTidakLengkap, SumberDataGagal

logger = logging.getLogger(__name__)

NILAI_ASAL = {
    "uji_tanah": 1.0, "api": 0.8, "cache": 0.8, "cache_kedaluwarsa": 0.7,
    "api_sekitar": 0.65, "open_meteo_dem": 0.7, "tetangga": 0.55,
}
BOBOT_KUALITAS = {"ph": 0.30, "tekstur": 0.20, "iklim": 0.35, "elevasi": 0.15}


def _iklim_valid(lat, lon):
    data = openmeteo.fetch_iklim(lat, lon)
    bulanan = data.get("curah_hujan_bulanan")
    if not bulanan or len(bulanan) != 12 or data.get("suhu_rata_rata") is None:
        # jangan di-cache, perlakukan sebagai gagal supaya cadangan dipakai
        raise SumberDataGagal("Open-Meteo mengembalikan data iklim tidak lengkap")
    return data


def resolve_iklim(lat, lon):
    data, asal, info = cache.ambil_atau_fetch(
        "iklim", lat, lon, _iklim_valid,
        syarat_tetangga=lambda p: bool(p.get("curah_hujan_bulanan")))
    catatan = []
    if asal == "cache_kedaluwarsa":
        catatan.append("Layanan iklim sedang tidak dapat diakses; memakai data tersimpan.")
    elif asal == "tetangga":
        catatan.append(f"Data iklim diambil dari lokasi terdekat ({info['jarak_km']} km).")
    return data, asal, catatan


def resolve_satelit(lat, lon):
    data, asal, info = cache.ambil_atau_fetch(
        "satelit", lat, lon, gee.fetch_satelit,
        syarat_tetangga=lambda p: p.get("elevasi_m") is not None)
    catatan = []
    if asal in ("cache_kedaluwarsa", "tetangga"):
        catatan.append("Layanan citra satelit sedang tidak dapat diakses; memakai data tersimpan.")
    return data, asal, catatan


def _jalankan(nama, fn, progres, *args):
    if progres:
        progres(nama, "berjalan")
    try:
        hasil = fn(*args)
        if progres:
            progres(nama, "selesai" if hasil[1] in ("api", "cache", "uji_tanah") else "cadangan")
        return hasil, None
    except (SumberDataGagal, DataTidakLengkap) as e:
        if progres:
            progres(nama, "gagal")
        return None, e
    finally:
        if getattr(settings, "NUSACROP_PARALEL", True):
            connection.close()  # koneksi DB milik thread ini


def _hitung_kualitas(asal):
    skor = sum(BOBOT_KUALITAS[k] * NILAI_ASAL.get(asal.get(k), 0.5) for k in BOBOT_KUALITAS)
    label = "Tinggi" if skor >= 0.85 else "Sedang" if skor >= 0.7 else "Rendah"
    return round(skor, 2), label


def get_environment(lat, lon, uji_tanah=None, progres=None):
    lat, lon = float(lat), float(lon)

    def tanah_fn(la, lo):
        data, asal, cat = resolve_tanah(la, lo, uji_tanah)
        utama = asal.get("ph", "api")
        return (data, asal, cat), utama

    tugas = {"tanah": tanah_fn, "iklim": lambda la, lo: _bungkus(resolve_iklim(la, lo)),
             "satelit": lambda la, lo: _bungkus(resolve_satelit(la, lo))}

    if getattr(settings, "NUSACROP_PARALEL", True):
        with ThreadPoolExecutor(max_workers=3) as ex:
            futures = {n: ex.submit(_jalankan, n, fn, progres, lat, lon) for n, fn in tugas.items()}
            hasil = {n: f.result() for n, f in futures.items()}
    else:
        hasil = {n: _jalankan(n, fn, progres, lat, lon) for n, fn in tugas.items()}

    # --- tanah (wajib) ---
    (r_tanah, e_tanah) = hasil["tanah"]
    if e_tanah:
        raise e_tanah
    tanah, asal_tanah, catatan = r_tanah[0]
    catatan = list(catatan)

    # --- iklim (wajib) ---
    (r_iklim, e_iklim) = hasil["iklim"]
    if e_iklim:
        raise SumberDataGagal(f"Data iklim tidak tersedia: {e_iklim}")
    iklim, asal_iklim, cat = r_iklim[0]
    catatan += cat

    # --- satelit (elevasi wajib, NDVI & kemiringan opsional) ---
    (r_sat, e_sat) = hasil["satelit"]
    if r_sat:
        satelit, asal_sat, cat = r_sat[0]
        catatan += cat
    elif iklim.get("elevasi_m") is not None:
        satelit = {"ndvi": None, "elevasi_m": round(iklim["elevasi_m"]), "kemiringan_derajat": None}
        asal_sat = "open_meteo_dem"
        catatan.append("Citra satelit tidak tersedia; elevasi memakai DEM Open-Meteo, "
                       "NDVI dan kemiringan tidak ditampilkan.")
        if progres:
            progres("elevasi", "cadangan")   # satelit tetap "gagal"
    else:
        if progres:
            progres("elevasi", "gagal")
        raise SumberDataGagal(f"Data elevasi tidak tersedia: {e_sat}")

    asal = {
        "ph": asal_tanah.get("ph"), "tekstur": asal_tanah.get("tekstur"),
        "nitrogen": asal_tanah.get("nitrogen"), "organic_carbon": asal_tanah.get("organic_carbon"),
        "iklim": asal_iklim, "elevasi": asal_sat,
        "ndvi": asal_sat if satelit.get("ndvi") is not None else None,
        "kemiringan": asal_sat if satelit.get("kemiringan_derajat") is not None else None,
    }
    skor_kualitas, label_kualitas = _hitung_kualitas(asal)

    kemiringan = satelit.get("kemiringan_derajat")
    if kemiringan is not None and kemiringan > 15:
        catatan.append(f"Lahan cukup miring (~{kemiringan:.0f} derajat); pertimbangkan "
                       "terasering atau tanaman penutup tanah untuk mencegah erosi.")

    return {
        # --- kunci lama (dipertahankan untuk FE) ---
        "curah_hujan": iklim["curah_hujan_tahunan"],
        "curah_hujan_bulanan": iklim["curah_hujan_bulanan"],
        "suhu": iklim["suhu_rata_rata"],
        "et0": iklim.get("et0_tahunan"),
        "ph_tanah": tanah["ph"],
        "nitrogen": tanah.get("nitrogen"),
        "organic_carbon": tanah.get("organic_carbon"),
        "tekstur_kelas": tanah["tekstur_kelas"],
        "tekstur_tanah": {k: tanah.get(k) for k in ("sand", "silt", "clay")},
        "ndvi": satelit.get("ndvi"),
        "elevasi": satelit["elevasi_m"],
        "kesuburan_tanah": calculate_fertility(tanah),
        # --- baru ---
        "kemiringan": kemiringan,
        "ph_rentang": ([tanah["ph_q05"], tanah["ph_q95"]]
                       if tanah.get("ph_q05") is not None and asal["ph"] != "uji_tanah" else None),
        "sumber_data": asal,
        "kualitas_data": {"skor": skor_kualitas, "label": label_kualitas},
        "catatan_data": catatan,
    }


def _bungkus(hasil):
    """(data, asal, catatan) -> ((data, asal, catatan), asal) agar seragam di _jalankan."""
    return hasil, hasil[1]
