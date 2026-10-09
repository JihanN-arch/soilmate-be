"""SoilGrids v2.0.

Kedaluwarsa: versi lama memakai kedalaman 0-5cm, padahal model dilatih
dengan 5-15cm (lihat docstring ml_lib/predict.py). Sekarang mengikuti
kedalaman training.
"""
from ml_lib.soilgrids_adapter import usda_texture_class

from .http import get_json

SOILGRIDS_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"
KEDALAMAN = "5-15cm"
PROPERTI = ["phh2o", "sand", "silt", "clay", "nitrogen", "soc"]
NAMA_FIELD = {"phh2o": "ph", "soc": "organic_carbon"}
WAJIB = ["ph", "sand", "silt", "clay"]


def fetch_tanah(lat, lon, cepat=False):
    """Ambil data tanah satu titik. Field yang tidak ada datanya bernilai None.

    Mengembalikan dict:
      ph, sand, silt, clay (%), nitrogen, organic_carbon (g/kg),
      ph_q05, ph_q95 (rentang ketidakpastian pH), tekstur_kelas
    """
    params = [("lon", lon), ("lat", lat), ("depth", KEDALAMAN),
              ("value", "mean"), ("value", "Q0.05"), ("value", "Q0.95")]
    params += [("property", p) for p in PROPERTI]

    # cepat=True untuk titik sekitar: satu percobaan saja supaya total waktu terkendali
    raw = get_json(SOILGRIDS_URL, params, "SoilGrids", timeout=10 if cepat else 15,
                   percobaan=1 if cepat else 2)
    return parse(raw)


def parse(raw):
    hasil = {f: None for f in WAJIB + ["nitrogen", "organic_carbon", "ph_q05", "ph_q95"]}
    for layer in (raw.get("properties") or {}).get("layers", []):
        nama = NAMA_FIELD.get(layer.get("name"), layer.get("name"))
        faktor = (layer.get("unit_measure") or {}).get("d_factor") or None
        depth = next((d for d in layer.get("depths", []) if d.get("label") == KEDALAMAN), None)
        if depth is None or not faktor:
            continue
        nilai = depth.get("values", {})
        if nilai.get("mean") is not None:
            hasil[nama] = round(nilai["mean"] / faktor, 3)
        if nama == "ph":
            for q, kunci in (("Q0.05", "ph_q05"), ("Q0.95", "ph_q95")):
                if nilai.get(q) is not None:
                    hasil[kunci] = round(nilai[q] / faktor, 2)

    hasil["tekstur_kelas"] = tekstur_dari_fraksi(hasil)
    return hasil


def tekstur_dari_fraksi(d):
    if all(d.get(k) is not None for k in ("sand", "silt", "clay")):
        return usda_texture_class(d["sand"], d["silt"], d["clay"])
    return None
