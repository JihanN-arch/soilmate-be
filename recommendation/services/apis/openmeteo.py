"""Open-Meteo: iklim historis (ERA5) dan prakiraan cuaca.

Iklim memakai periode TETAP 2022-2024, sama dengan data training model
(lihat docstring ml_lib/predict.py). Versi lama memakai 365 hari terakhir,
sehingga satu tahun yang kebetulan sangat basah/kering menggeser semua
rekomendasi tanpa error. Karena periodenya tetap, hasilnya statis dan
aman di-cache permanen.

Catatan: suhu dari Open-Meteo sudah dikoreksi elevasi (downscaling dengan
DEM 90 m) untuk koordinat yang diminta, jadi tidak perlu koreksi lapse rate
manual.
"""
from ml_lib.climate_features import monthly_from_daily

from .http import get_json

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
PERIODE_IKLIM = ("2022-01-01", "2024-12-31")


def fetch_iklim(lat, lon):
    data = get_json(ARCHIVE_URL, {
        "latitude": lat, "longitude": lon,
        "start_date": PERIODE_IKLIM[0], "end_date": PERIODE_IKLIM[1],
        "daily": "precipitation_sum,temperature_2m_mean,et0_fao_evapotranspiration",
        "timezone": "Asia/Jakarta",
    }, "Open-Meteo (iklim)", timeout=30)

    harian = data.get("daily") or {}
    tanggal = harian.get("time") or []
    hujan_bulanan = monthly_from_daily(tanggal, harian.get("precipitation_sum") or [])

    suhu = [v for v in harian.get("temperature_2m_mean") or [] if v is not None]
    et0 = [v for v in harian.get("et0_fao_evapotranspiration") or [] if v is not None]
    n_tahun = len({t[:4] for t in tanggal}) or 1

    return {
        "curah_hujan_bulanan": [round(v, 1) for v in hujan_bulanan] if hujan_bulanan else None,
        "curah_hujan_tahunan": round(sum(hujan_bulanan), 1) if hujan_bulanan else None,
        "suhu_rata_rata": round(sum(suhu) / len(suhu), 1) if suhu else None,
        "et0_tahunan": round(sum(et0) / n_tahun, 1) if et0 else None,
        # elevasi titik dari DEM Open-Meteo: cadangan kalau GEE gagal
        "elevasi_m": data.get("elevation"),
        "periode": f"{PERIODE_IKLIM[0]}..{PERIODE_IKLIM[1]}",
    }


def fetch_prakiraan(lat, lon, hari=14):
    data = get_json(FORECAST_URL, {
        "latitude": lat, "longitude": lon,
        "daily": "precipitation_sum,precipitation_probability_max,"
                 "temperature_2m_max,temperature_2m_min",
        "forecast_days": hari,
        "timezone": "Asia/Jakarta",
    }, "Open-Meteo (prakiraan)")

    d = data.get("daily") or {}
    kolom = ["precipitation_sum", "precipitation_probability_max",
             "temperature_2m_max", "temperature_2m_min"]
    nama = ["hujan_mm", "peluang_hujan", "suhu_maks", "suhu_min"]
    harian = []
    for i, tgl in enumerate(d.get("time") or []):
        baris = {"tanggal": tgl}
        for k, n in zip(kolom, nama):
            vals = d.get(k) or []
            baris[n] = vals[i] if i < len(vals) else None
        harian.append(baris)
    return {"harian": harian}
