"""Google Earth Engine: NDVI, elevasi, kemiringan, dan deret NDVI monitoring.

Perbaikan dari versi lama:
- komposit median 12 bulan terakhir + masker awan (SCL), bukan satu citra
  dengan awan paling sedikit (yang di titik itu bisa saja tetap berawan);
- rata-rata dalam radius (default 100 m), bukan satu piksel;
- kemiringan lahan dari SRTM;
- semua nilai diambil dalam SATU getInfo() (dulu dua round-trip);
- rentang tanggal dinamis, bukan hardcode 2025.
"""
import json
import logging
import math
import os
import time
from datetime import date, timedelta

from ..errors import SumberDataGagal

logger = logging.getLogger(__name__)

S2 = "COPERNICUS/S2_SR_HARMONIZED"
DEM = "USGS/SRTMGL1_003"
PERCOBAAN = 2
BATAS_WAKTU_MS = 20_000
_siap = False


class KredensialGeeBermasalah(SumberDataGagal):
    """Tidak perlu dicoba ulang: masalahnya konfigurasi, bukan jaringan."""


def kredensial_tersedia():
    return bool(os.getenv("GEE_SERVICE_ACCOUNT_KEY_JSON")) or bool(
        os.getenv("GEE_SERVICE_ACC_EMAIL") and os.getenv("GEE_SERVICE_ACC_KEY_PATH"))


def _ee():
    global _siap
    import ee
    if _siap:
        return ee
    if not kredensial_tersedia():
        raise KredensialGeeBermasalah(
            "Kredensial GEE belum diatur (env GEE_SERVICE_ACCOUNT_KEY_JSON kosong).")
    try:
        key_json = os.getenv("GEE_SERVICE_ACCOUNT_KEY_JSON")
        if key_json:
            email = json.loads(key_json)["client_email"]
            cred = ee.ServiceAccountCredentials(email, key_data=key_json)
        else:
            cred = ee.ServiceAccountCredentials(
                os.getenv("GEE_SERVICE_ACC_EMAIL"), os.getenv("GEE_SERVICE_ACC_KEY_PATH"))
        ee.Initialize(cred)
    except (ValueError, KeyError) as e:
        raise KredensialGeeBermasalah(
            f"Isi GEE_SERVICE_ACCOUNT_KEY_JSON tidak valid (bukan JSON kunci service account): {e}") from e
    except Exception as e:
        raise KredensialGeeBermasalah(f"Login ke Google Earth Engine gagal: {e}") from e
    try:
        ee.data.setDeadline(BATAS_WAKTU_MS)
    except Exception:  # versi lama earthengine-api
        pass
    _siap = True
    return ee


def _mask_awan(img):
    scl = img.select("SCL")  # 3 bayangan awan, 8-9 awan, 10 cirrus
    bersih = scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10))
    return img.updateMask(bersih)


def _dengan_retry(nama, fn):
    terakhir = None
    for i in range(PERCOBAAN):
        try:
            return fn()
        except KredensialGeeBermasalah:
            raise
        except Exception as e:  # earthengine melempar berbagai jenis exception
            terakhir = e
            if i < PERCOBAAN - 1:
                jeda = 2 ** i
                logger.warning("%s gagal (%s), ulang dalam %d s", nama, e, jeda)
                time.sleep(jeda)
    raise SumberDataGagal(f"{nama} gagal setelah {PERCOBAAN} percobaan: {terakhir}")


def fetch_satelit(lat, lon, radius_m=100):
    def jalan():
        ee = _ee()
        area = ee.Geometry.Point([lon, lat]).buffer(radius_m)
        akhir = ee.Date(date.today().isoformat())
        awal = akhir.advance(-12, "month")
        koleksi = (ee.ImageCollection(S2).filterBounds(area)
                   .filterDate(awal, akhir).map(_mask_awan))
        dem = ee.Image(DEM)
        terrain = (dem.select("elevation").rename("elevasi")
                   .addBands(ee.Terrain.slope(dem).rename("kemiringan"))
                   .reduceRegion(ee.Reducer.mean(), area, 30))
        # If() dievaluasi malas di server: kalau tidak ada citra sama sekali,
        # NDVI dikosongkan tanpa membuat seluruh request gagal.
        ndvi = ee.Dictionary(ee.Algorithms.If(
            koleksi.size().gt(0),
            koleksi.median().normalizedDifference(["B8", "B4"]).rename("ndvi")
            .reduceRegion(ee.Reducer.mean(), area, 10),
            ee.Dictionary({})))
        return ee.Dictionary(terrain).combine(ndvi).getInfo()

    hasil = _dengan_retry("GEE", jalan) or {}
    if hasil.get("elevasi") is None:
        raise SumberDataGagal("GEE tidak mengembalikan elevasi")
    return {
        "ndvi": None if hasil.get("ndvi") is None else round(hasil["ndvi"], 4),
        "elevasi_m": round(hasil["elevasi"]),
        "kemiringan_derajat": None if hasil.get("kemiringan") is None
        else round(hasil["kemiringan"], 1),
        "radius_m": radius_m,
    }


# SoilGrids 2.0 di katalog komunitas Earth Engine (ISRIC). Data dan satuannya
# sama dengan REST API SoilGrids (nilai integer yang harus dibagi faktor).
SOILGRIDS_GEE = {
    # nama di ISRIC: (nama field kita, faktor pembagi)
    "phh2o": ("ph", 10),
    "sand": ("sand", 10),            # g/kg -> %
    "silt": ("silt", 10),
    "clay": ("clay", 10),
    "soc": ("organic_carbon", 10),   # dg/kg -> g/kg
    "nitrogen": ("nitrogen", 100),   # cg/kg -> g/kg
}
KEDALAMAN_TANAH = "5-15cm"           # sama dengan data training model


def fetch_tanah(lat, lon):
    """Data tanah SoilGrids lewat GEE. Jauh lebih cepat dan stabil dari REST.

    Rata-rata dalam radius 150 m; kalau titiknya tidak punya data (permukiman,
    badan air), radius diperluas ke 600 m. Bentuk keluaran sama dengan
    apis.soilgrids.fetch_tanah (kecuali ph_q05/ph_q95 tidak tersedia).
    """
    def jalan(radius):
        ee = _ee()
        img = ee.Image.cat([
            ee.Image(f"projects/soilgrids-isric/{nama}_mean")
            .select(f"{nama}_{KEDALAMAN_TANAH}_mean").rename(nama)
            for nama in SOILGRIDS_GEE])
        area = ee.Geometry.Point([lon, lat]).buffer(radius)
        return img.reduceRegion(ee.Reducer.mean(), area, 250).getInfo() or {}

    hasil = {}
    for radius in (150, 600):
        mentah = _dengan_retry("GEE (SoilGrids)", lambda: jalan(radius))
        hasil = {field: None if mentah.get(nama) is None else round(mentah[nama] / faktor, 3)
                 for nama, (field, faktor) in SOILGRIDS_GEE.items()}
        if hasil["ph"] is not None and hasil["clay"] is not None:
            break
    hasil.update(ph_q05=None, ph_q95=None, _sumber="soilgrids_gee")
    return hasil


def fetch_deret_ndvi(lat, lon, mulai, selesai=None, radius_m=50, min_fraksi_valid=0.3):
    """Deret NDVI per tanggal citra Sentinel-2 (untuk monitoring pasca-tanam).

    Citra yang sebagian besar tertutup awan di area lahan dibuang
    (piksel valid < min_fraksi_valid dari perkiraan jumlah piksel).
    """
    selesai = selesai or date.today() + timedelta(days=1)
    perkiraan_piksel = max(1, round(math.pi * radius_m ** 2 / 100))

    def jalan():
        ee = _ee()
        area = ee.Geometry.Point([lon, lat]).buffer(radius_m)
        koleksi = (ee.ImageCollection(S2).filterBounds(area)
                   .filterDate(mulai.isoformat(), selesai.isoformat()).map(_mask_awan))

        def per_citra(img):
            ndvi = img.normalizedDifference(["B8", "B4"]).rename("ndvi")
            stat = ndvi.reduceRegion(
                ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True), area, 10)
            return ee.Feature(None, {"tanggal": img.date().format("YYYY-MM-dd"),
                                     "ndvi": stat.get("ndvi_mean"),
                                     "n": stat.get("ndvi_count")})

        fc = ee.FeatureCollection(koleksi.map(per_citra)).filter(ee.Filter.notNull(["ndvi"]))
        return fc.reduceColumns(ee.Reducer.toList(3), ["tanggal", "ndvi", "n"]).get("list").getInfo()

    baris = _dengan_retry("GEE (deret NDVI)", jalan) or []

    per_tanggal = {}
    for tgl, ndvi, n in baris:
        if ndvi is None or (n or 0) < perkiraan_piksel * min_fraksi_valid:
            continue
        per_tanggal.setdefault(tgl, []).append((ndvi, n))   # tile yang tumpang tindih
    return [{"tanggal": tgl,
             "ndvi": round(sum(v for v, _ in xs) / len(xs), 4),
             "piksel_valid": max(n for _, n in xs)}
            for tgl, xs in sorted(per_tanggal.items())]
