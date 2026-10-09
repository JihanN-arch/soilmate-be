"""Lapisan ekonomi: estimasi pendapatan & keuntungan per hektar.

Semua field boleh kosong. Selama data belum diisi, estimasi bernilai None
dan `tersedia` = False, jadi FE bisa menampilkan "data ekonomi belum
tersedia" tanpa error.

Estimasi memakai HARGA TERKINI, bukan harga saat panen. Selalu tampilkan
`catatan` agar petani tahu ini perkiraan kasar.
"""
from datetime import timedelta

from ..models.ekonomi_models import HargaKomoditas

CATATAN = ("Perkiraan kasar berdasarkan harga terkini dan rata-rata produktivitas/biaya "
           "nasional. Harga saat panen bisa berbeda.")


def _harga_terakhir(crop, tingkat="produsen"):
    return (HargaKomoditas.objects.filter(crop=crop, tingkat=tingkat)
            .order_by("-tanggal").first())


def _perubahan_persen(crop, terbaru, hari=30):
    if terbaru is None:
        return None
    lama = (HargaKomoditas.objects
            .filter(crop=crop, tingkat=terbaru.tingkat,
                    tanggal__lte=terbaru.tanggal - timedelta(days=hari))
            .order_by("-tanggal").first())
    if lama is None or not lama.harga_per_kg:
        return None
    return round((terbaru.harga_per_kg - lama.harga_per_kg) / lama.harga_per_kg * 100, 1)


def _skala(rentang, luas_m2):
    if rentang is None or not luas_m2:
        return None
    f = luas_m2 / 10_000
    return {"min": round(rentang["min"] * f), "max": round(rentang["max"] * f)}


def estimasi(crop, luas_m2=None):
    harga = _harga_terakhir(crop)
    pmin, pmax = crop.produktivitas_min_ton_ha, crop.produktivitas_max_ton_ha
    biaya = crop.biaya_produksi_per_ha

    pendapatan = keuntungan = None
    if harga and pmin is not None and pmax is not None:
        pendapatan = {"min": round(pmin * 1000 * harga.harga_per_kg),
                      "max": round(pmax * 1000 * harga.harga_per_kg)}
        if biaya is not None:
            keuntungan = {"min": pendapatan["min"] - biaya, "max": pendapatan["max"] - biaya}

    produktivitas_kg = ({"min": round(pmin * 1000), "max": round(pmax * 1000)}
                        if pmin is not None and pmax is not None else None)
    return {
        "tersedia": keuntungan is not None,
        # nama field yang dipakai FE
        "harga_per_kg": harga.harga_per_kg if harga else None,
        "produktivitas_kg_ha": produktivitas_kg,
        "estimasi_biaya_per_ha": biaya,
        "estimasi_biaya_lahan": round(biaya * luas_m2 / 10_000) if biaya is not None and luas_m2 else None,
        "produktivitas_ton_ha": ({"min": pmin, "max": pmax}
                                 if pmin is not None and pmax is not None else None),
        "harga_produsen_per_kg": harga.harga_per_kg if harga else None,
        "tanggal_harga": harga.tanggal.isoformat() if harga else None,
        "sumber_harga": harga.sumber if harga else None,
        "perubahan_harga_30_hari_persen": _perubahan_persen(crop, harga),
        "biaya_produksi_per_ha": biaya,
        "sumber_biaya": crop.sumber_biaya,
        "estimasi_pendapatan_per_ha": pendapatan,
        "estimasi_keuntungan_per_ha": keuntungan,
        # sama, tetapi untuk luas lahan petani (null kalau luas tidak diisi)
        "luas_lahan_m2": luas_m2,
        "estimasi_pendapatan_lahan": _skala(pendapatan, luas_m2),
        "estimasi_keuntungan_lahan": _skala(keuntungan, luas_m2),
        "catatan": CATATAN,
    }


def tren_harga(crop, hari=180, tingkat="produsen"):
    terbaru = _harga_terakhir(crop, tingkat)
    if terbaru is None:
        return []
    qs = (HargaKomoditas.objects
          .filter(crop=crop, tingkat=tingkat, tanggal__gte=terbaru.tanggal - timedelta(days=hari))
          .order_by("tanggal").values("tanggal", "harga_per_kg", "wilayah_nama"))
    return [{"tanggal": r["tanggal"].isoformat(), "harga_per_kg": r["harga_per_kg"],
             "wilayah": r["wilayah_nama"]} for r in qs]
