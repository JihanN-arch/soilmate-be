"""Lapisan ekonomi: estimasi pendapatan & keuntungan per hektar dan per lahan.

Harga yang dipakai: harga PRODUSEN terbaru tingkat NASIONAL (wilayah_kode "00").
Kalau data nasional tidak ada, dipakai data terbaru apa pun.

Semua field boleh kosong; `status` memberi tahu FE apa yang bisa ditampilkan.
Estimasi memakai harga terbaru yang tersedia, bukan harga saat panen.
"""
from datetime import timedelta

from ..models.ekonomi_models import HargaKomoditas

KODE_NASIONAL = "00"
CATATAN = ("Perkiraan kasar berdasarkan harga produsen terbaru yang tersedia dan rata-rata "
           "produktivitas/biaya nasional. Harga saat panen bisa berbeda.")


def _qs(crop, tingkat="produsen"):
    qs = HargaKomoditas.objects.filter(crop=crop, tingkat=tingkat)
    nasional = qs.filter(wilayah_kode=KODE_NASIONAL)
    return nasional if nasional.exists() else qs


def _harga_terakhir(crop, tingkat="produsen"):
    return _qs(crop, tingkat).order_by("-tanggal").first()


def _perubahan_persen(crop, terbaru, hari=30):
    if terbaru is None:
        return None
    lama = (_qs(crop, terbaru.tingkat)
            .filter(tanggal__lte=terbaru.tanggal - timedelta(days=hari))
            .order_by("-tanggal").first())
    if lama is None or not lama.harga_per_kg:
        return None
    return round((terbaru.harga_per_kg - lama.harga_per_kg) / lama.harga_per_kg * 100, 1)


def _skala(rentang, luas_m2):
    if rentang is None or not luas_m2:
        return None
    f = luas_m2 / 10_000
    return {"min": round(rentang["min"] * f), "max": round(rentang["max"] * f)}


def _catatan(crop, harga):
    teks = [CATATAN]
    if harga:
        teks.append(f"Harga: {harga.sumber or 'tidak diketahui'}, {harga.tanggal:%m/%Y}"
                    f" ({harga.wilayah_nama or 'nasional'}).")
    if crop.biaya_produksi_per_ha is not None and crop.tahun_biaya and harga \
            and harga.tanggal.year - crop.tahun_biaya >= 3:
        teks.append(f"Biaya produksi memakai data tahun {crop.tahun_biaya}; biaya sekarang "
                    f"kemungkinan lebih tinggi, jadi keuntungan sebenarnya bisa lebih kecil.")
    return " ".join(teks)


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
        # tersedia = keuntungan bersih bisa dihitung (perilaku lama, dipakai FE)
        "tersedia": keuntungan is not None,
        # lengkap | pendapatan_saja (biaya belum ada) | belum_tersedia (harga belum ada)
        "status": ("lengkap" if keuntungan is not None
                   else "pendapatan_saja" if pendapatan is not None else "belum_tersedia"),
        "harga_per_kg": harga.harga_per_kg if harga else None,
        "produktivitas_kg_ha": produktivitas_kg,
        "estimasi_biaya_per_ha": biaya,
        "estimasi_biaya_lahan": round(biaya * luas_m2 / 10_000) if biaya is not None and luas_m2 else None,
        "produktivitas_ton_ha": ({"min": pmin, "max": pmax}
                                 if pmin is not None and pmax is not None else None),
        "harga_produsen_per_kg": harga.harga_per_kg if harga else None,
        "tanggal_harga": harga.tanggal.isoformat() if harga else None,
        "wilayah_harga": (harga.wilayah_nama if harga else None),
        "sumber_harga": harga.sumber if harga else None,
        "perubahan_harga_30_hari_persen": _perubahan_persen(crop, harga),
        "biaya_produksi_per_ha": biaya,
        "tahun_biaya": crop.tahun_biaya,
        "sumber_biaya": crop.sumber_biaya,
        "estimasi_pendapatan_per_ha": pendapatan,
        "estimasi_keuntungan_per_ha": keuntungan,
        "luas_lahan_m2": luas_m2,
        "estimasi_pendapatan_lahan": _skala(pendapatan, luas_m2),
        "estimasi_keuntungan_lahan": _skala(keuntungan, luas_m2),
        "catatan": _catatan(crop, harga),
    }


def tren_harga(crop, hari=365, tingkat="produsen"):
    """Deret harga nasional (bulanan) selama `hari` terakhir dari data terbaru."""
    terbaru = _harga_terakhir(crop, tingkat)
    if terbaru is None:
        return []
    qs = (_qs(crop, tingkat)
          .filter(tanggal__gte=terbaru.tanggal - timedelta(days=hari))
          .order_by("tanggal").values("tanggal", "harga_per_kg", "wilayah_nama"))
    return [{"tanggal": r["tanggal"].isoformat(), "harga_per_kg": r["harga_per_kg"],
             "wilayah": r["wilayah_nama"]} for r in qs]
