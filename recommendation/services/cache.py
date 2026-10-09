"""Cache data lingkungan per sel grid + rantai cadangan.

Urutan saat data diminta (ambil_atau_fetch):
  1. cache segar di sel yang sama          -> asal "cache"
  2. tarik dari API, lalu simpan            -> asal "api"
  3. API gagal: cache kedaluwarsa sel sama  -> asal "cache_kedaluwarsa"
  4. API gagal: sel tetangga terdekat       -> asal "tetangga"
  5. semuanya gagal                         -> SumberDataGagal

Ukuran sel mengikuti resolusi asli datanya, jadi menyimpan per sel tidak
membuang informasi: SoilGrids 250 m, Sentinel-2/SRTM jauh lebih halus,
iklim Open-Meteo sudah dikoreksi elevasi per titik sehingga sel 0,01 deg.
"""
import logging
import math
from datetime import timedelta

from django.utils import timezone

from ..models.cache_models import DataCache
from .errors import SumberDataGagal

logger = logging.getLogger(__name__)

# derajat per sel (0,0025 deg ~ 280 m; 0,01 deg ~ 1,1 km)
GRID = {"tanah": 0.0025, "iklim": 0.01, "satelit": 0.001, "prakiraan": 0.05}
# umur cache segar; None = permanen (data statis)
TTL = {
    "tanah": timedelta(days=180),
    "iklim": None,                 # periode iklim tetap 2022-2024
    "satelit": timedelta(days=30),
    "prakiraan": timedelta(hours=3),
}
# radius maksimal sel tetangga sebagai cadangan
RADIUS_TETANGGA_KM = {"tanah": 1.0, "iklim": 15.0, "satelit": 0.3, "prakiraan": 10.0}


def kunci_sel(sumber, lat, lon):
    step = GRID[sumber]
    clat = round(math.floor(lat / step) * step + step / 2, 6)
    clon = round(math.floor(lon / step) * step + step / 2, 6)
    return f"{clat:.6f}_{clon:.6f}"


def _segar(obj, sumber):
    ttl = TTL[sumber]
    return ttl is None or timezone.now() - obj.diambil_pada <= ttl


def ambil(sumber, lat, lon):
    """(payload, segar) atau None."""
    obj = DataCache.objects.filter(sumber=sumber, kunci_sel=kunci_sel(sumber, lat, lon)).first()
    if obj is None:
        return None
    return obj.payload, _segar(obj, sumber)


def simpan(sumber, lat, lon, payload):
    DataCache.objects.update_or_create(
        sumber=sumber, kunci_sel=kunci_sel(sumber, lat, lon),
        defaults={"lat": lat, "lon": lon, "payload": payload})


def jarak_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def tetangga(sumber, lat, lon, radius_km=None, syarat=None):
    """Sel cache terdekat dalam radius. Tanpa PostGIS: saring kotak lalu haversine.

    syarat: fungsi payload -> bool untuk melewati sel yang datanya tidak berguna
    (mis. piksel SoilGrids kosong).
    Mengembalikan (payload, jarak_km) atau None.
    """
    radius_km = radius_km if radius_km is not None else RADIUS_TETANGGA_KM[sumber]
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.01))
    kandidat = DataCache.objects.filter(
        sumber=sumber, lat__range=(lat - dlat, lat + dlat), lon__range=(lon - dlon, lon + dlon))
    terbaik = None
    for obj in kandidat:
        if syarat and not syarat(obj.payload):
            continue
        d = jarak_km(lat, lon, obj.lat, obj.lon)
        if d <= radius_km and (terbaik is None or d < terbaik[1]):
            terbaik = (obj.payload, d)
    return terbaik


def ambil_atau_fetch(sumber, lat, lon, fetch_fn, syarat_tetangga=None):
    """Lihat docstring modul. Mengembalikan (payload, asal, info)."""
    ada = ambil(sumber, lat, lon)
    if ada and ada[1]:
        return ada[0], "cache", {}

    try:
        payload = fetch_fn(lat, lon)
        simpan(sumber, lat, lon, payload)
        return payload, "api", {}
    except SumberDataGagal as e:
        logger.warning("%s: %s -> mencoba cache", sumber, e)
        if ada:
            return ada[0], "cache_kedaluwarsa", {"error_api": str(e)}
        dekat = tetangga(sumber, lat, lon, syarat=syarat_tetangga)
        if dekat:
            return dekat[0], "tetangga", {"error_api": str(e), "jarak_km": round(dekat[1], 2)}
        raise
