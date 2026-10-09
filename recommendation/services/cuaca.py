"""Prakiraan cuaca 14 hari + saran sederhana untuk petani.

Ambang hujan mengikuti kategori BMKG (hujan lebat 50-100 mm/hari,
sangat lebat 100-150, ekstrem > 150).
"""
from . import cache
from .apis import openmeteo


def _saran(harian):
    saran = []
    lebat = [h for h in harian if (h.get("hujan_mm") or 0) >= 50]
    if lebat:
        tgl = ", ".join(h["tanggal"] for h in lebat[:3])
        saran.append({"jenis": "hujan_lebat", "tingkat": "waspada",
                      "pesan": f"Potensi hujan lebat pada {tgl}. Pastikan saluran drainase "
                               "lahan tidak tersumbat dan tunda pemupukan agar tidak tercuci."})

    run = terpanjang = 0
    for h in harian:
        run = run + 1 if (h.get("hujan_mm") or 0) < 1 else 0
        terpanjang = max(terpanjang, run)
    if terpanjang >= 7:
        saran.append({"jenis": "kering", "tingkat": "info",
                      "pesan": f"Diperkirakan {terpanjang} hari berturut-turut tanpa hujan berarti. "
                               "Siapkan pengairan, terutama untuk tanaman yang baru ditanam."})

    panas = [h for h in harian if (h.get("suhu_maks") or 0) >= 35]
    if panas:
        saran.append({"jenis": "panas", "tingkat": "info",
                      "pesan": "Suhu siang hari diperkirakan mencapai 35°C atau lebih. "
                               "Siram pada pagi atau sore hari."})
    return saran


def get_prakiraan(lat, lon):
    data, asal, _ = cache.ambil_atau_fetch("prakiraan", float(lat), float(lon), openmeteo.fetch_prakiraan)
    harian = [dict(h) for h in data.get("harian", [])]
    for h in harian:   # nama field yang dipakai FE
        h["peluang_hujan"] = h.get("peluang_hujan", h.get("peluang_hujan_persen"))
    return {"harian": harian, "saran": _saran(harian), "sumber": "Open-Meteo", "asal": asal}
