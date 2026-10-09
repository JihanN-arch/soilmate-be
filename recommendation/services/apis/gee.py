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
PERCOBAAN = 3
_siap = False


def _ee():
    global _siap
    import ee
    if _siap:
        return ee
    key_json = os.getenv("GEE_SERVICE_ACCOUNT_KEY_JSON")
    if key_json:
        email = json.loads(key_json)["client_email"]
        cred = ee.ServiceAccountCredentials(email, key_data=key_json)
    else:
        cred = ee.ServiceAccountCredentials(
            os.getenv("GEE_SERVICE_ACC_EMAIL"), os.getenv("GEE_SERVICE_ACC_KEY_PATH"))
    ee.Initialize(cred)
    try:
        ee.data.setDeadline(30_000)  # ms
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
