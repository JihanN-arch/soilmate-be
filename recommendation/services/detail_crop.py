from ..ml.ml_model import get_profile
from ..models.riwayat_models import RiwayatRekomendasi
from . import ekonomi


def get_crop_detail(rekomendasi_id, anonymous_id=None):
    qs = RiwayatRekomendasi.objects.select_related("crop", "riwayat")
    if anonymous_id:
        qs = qs.filter(riwayat__anonymous_id=anonymous_id)
    rekomendasi = qs.filter(id=rekomendasi_id).first()
    if rekomendasi is None:
        return None

    tanaman = rekomendasi.crop
    profil = get_profile(tanaman.slug) or {}
    est = ekonomi.estimasi(tanaman, rekomendasi.riwayat.luas_lahan_m2)
    tren = ekonomi.tren_harga(tanaman)
    return {
        "slug": tanaman.slug,
        "crop_slug": tanaman.slug,
        "rekomendasi_id": rekomendasi.id,
        "riwayat_id": rekomendasi.riwayat_id,
        "nama": tanaman.nama,
        "nama_latin": tanaman.nama_latin,
        "deskripsi": tanaman.deskripsi,
        "jenis_tanaman": tanaman.jenis_tanaman,
        "umur_panen": tanaman.umur_panen,
        "produktivitas_tanaman": tanaman.produktivitas_tanaman,
        "cara_budidaya": tanaman.cara_budidaya,
        "manfaat": tanaman.manfaat,
        "syarat_tumbuh": tanaman.syarat_tumbuh,
        # syarat yang benar-benar dipakai penilaian (seed.json)
        "profil_penilaian": {k: profil.get(k) for k in (
            "ph_min", "ph_max", "ph_optimal_min", "ph_optimal_max",
            "rainfall_min", "rainfall_max", "rainfall_optimal_min", "rainfall_optimal_max",
            "temp_min", "temp_max", "temp_optimal_min", "temp_optimal_max",
            "elevation_min", "elevation_max", "optimal_soil_texture",
            "tolerable_soil_texture", "cycle_months", "drought_tolerance")},
        "ringkasan_rekomendasi": {
            "skor_kesesuaian": rekomendasi.skor_kesesuaian,
            "tingkat_kepercayaan": rekomendasi.tingkat_kepercayaan,
            "alasan_rekomendasi": rekomendasi.alasan_rekomendasi,
            "faktor_pembatas": rekomendasi.faktor_pembatas,
            "mulai_tanam": rekomendasi.mulai_tanam,
            "musim_tanam_mm": rekomendasi.musim_tanam_mm,
            "rincian_skor": rekomendasi.rincian_skor,
            "detail_kepercayaan": rekomendasi.detail_kepercayaan,
        },
        "ekonomi": {**est, "tren_harga": tren},   # tren juga di dalam (kompatibilitas)
        "tren_harga": tren,
    }
