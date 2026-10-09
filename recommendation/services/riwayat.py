"""Riwayat dalam bentuk yang sama dengan hasil analisis (objek `recommendation`).

Riwayat baru menyimpan salinan lengkap (`hasil_snapshot`); ekonominya dihitung
ulang saat dibaca karena harga bisa berubah. Riwayat lama (sebelum fitur ini)
disusun dari kolom yang ada; field yang tidak tersimpan dikirim null.
"""
import copy

from ..ml.ml_model import get_profile
from ..models.crop_models import Crop
from . import ekonomi


def _segarkan_ekonomi(items, luas, crops):
    for it in items or []:
        slug = it.get("crop_slug") or it.get("id")
        it["crop_slug"] = slug
        if slug in crops:
            it["ekonomi"] = ekonomi.estimasi(crops[slug], luas)


def _item_lama(rek):
    crop = rek.crop
    p = get_profile(crop.slug) or {}
    return {
        "id": crop.slug, "crop_slug": crop.slug, "rekomendasi_id": rek.id,
        "nama": crop.nama, "nama_latin": crop.nama_latin, "jenis_tanaman": crop.jenis_tanaman,
        "kesuburan_ideal": (crop.syarat_tumbuh or {}).get("kesuburan"),
        "ph_ideal": f"{p.get('ph_min')} - {p.get('ph_max')}",
        "elevasi_ideal": f"{p.get('elevation_min')} - {p.get('elevation_max')} mdpl",
        "skor_kesesuaian": rek.skor_kesesuaian,
        "tingkat_kepercayaan": rek.tingkat_kepercayaan,
        "alasan_rekomendasi": rek.alasan_rekomendasi,
        "faktor_pembatas": rek.faktor_pembatas or None,
        "mulai_tanam": rek.mulai_tanam,
        "musim_tanam_mm": rek.musim_tanam_mm,
        "rincian_skor": rek.rincian_skor or None,
        "detail_kepercayaan": rek.detail_kepercayaan,
        "ekonomi": None,
    }


def _label_kualitas(skor):
    if skor is None:
        return None
    return {"skor": skor, "label": "Tinggi" if skor >= 0.85 else "Sedang" if skor >= 0.7 else "Rendah"}


def _hasil_lama(r):
    return {
        "kondisi_lahan": {
            "curah_hujan": r.curah_hujan, "curah_hujan_bulanan": r.curah_hujan_bulanan,
            "suhu": r.suhu, "et0": r.et0, "ph_tanah": r.ph_tanah, "nitrogen": r.nitrogen,
            "organic_carbon": r.organic_carbon, "tekstur_kelas": r.tekstur_kelas,
            "tekstur_tanah": r.tekstur_tanah or None, "ndvi": r.ndvi, "elevasi": r.elevasi,
            "kesuburan_tanah": r.kesuburan_tanah, "kemiringan": r.kemiringan, "ph_rentang": None,
            "sumber_data": r.sumber_data or None, "kualitas_data": _label_kualitas(r.kualitas_data),
            "catatan_data": None, "luas_lahan_m2": r.luas_lahan_m2,
        },
        "rekomendasi": [_item_lama(x) for x in
                        r.rekomendasi.filter(daftar="utama").select_related("crop")],
        "rekomendasi_bulan_tanam": None,
    }


def riwayat_sebagai_hasil(r):
    hasil = copy.deepcopy(r.hasil_snapshot) if r.hasil_snapshot else _hasil_lama(r)
    if r.hasil_snapshot:
        crops = {c.slug: c for c in Crop.objects.all()}
        _segarkan_ekonomi(hasil.get("rekomendasi"), r.luas_lahan_m2, crops)
        _segarkan_ekonomi((hasil.get("rekomendasi_bulan_tanam") or {}).get("daftar"), r.luas_lahan_m2, crops)
    hasil.update({
        "riwayat_id": r.id, "nama_lokasi": r.nama_lokasi, "lat": r.lat, "lon": r.lon,
        "bulan_tanam": r.bulan_tanam, "luas_lahan_m2": r.luas_lahan_m2,
        "dibuat_pada": r.dibuat_pada.isoformat(),
    })
    return hasil
