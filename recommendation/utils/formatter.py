from ..ml.ml_model import get_profile, skor_efektif
from ..models.crop_models import Crop
from ..services import ekonomi
from .confidence import get_confidence
from .reason import generate_reason


def _item(h, crop, kondisi):
    profil = get_profile(crop.slug)
    alasan, pembatas = generate_reason(
        kondisi, profil, crop.nama, h["rincian"],
        musim_tanam_mm=h.get("musim_tanam_mm"), mulai_tanam=h.get("mulai_tanam"))
    skor = round(skor_efektif(h) / 100, 2)
    label, detail = get_confidence(kondisi["kualitas_data"]["skor"], h.get("peringkat_ml"),
                                   h.get("confidence"))
    return {
        # --- kunci lama ---
        "id": crop.slug,
        "crop_slug": crop.slug,
        "nama": crop.nama,
        "nama_latin": crop.nama_latin,
        "jenis_tanaman": crop.jenis_tanaman,
        "kesuburan_ideal": (crop.syarat_tumbuh or {}).get("kesuburan"),
        "ph_ideal": f'{profil["ph_min"]} - {profil["ph_max"]}',
        "elevasi_ideal": f'{profil.get("elevation_min")} - {profil.get("elevation_max")} mdpl',
        "skor_kesesuaian": skor,
        "tingkat_kepercayaan": label,
        "alasan_rekomendasi": alasan,
        # --- baru ---
        "faktor_pembatas": pembatas,
        "mulai_tanam": h.get("mulai_tanam"),
        "musim_tanam_mm": h.get("musim_tanam_mm"),
        "rincian_skor": h["rincian"],
        # skor jika mulai tanam di bulan Jan..Des (0-1); null untuk tanaman tahunan
        "skor_per_bulan": ([round(x / 100, 2) for x in h["skor_per_bulan"]]
                           if h.get("skor_per_bulan") else None),
        "sumber_skor": "hybrid" if h.get("skor_akhir") is not None else "aturan",
        "detail_kepercayaan": detail,
        "ekonomi": ekonomi.estimasi(crop, kondisi.get("luas_lahan_m2")),
    }


def format_daftar(hasil_model, kondisi):
    crops = {c.slug: c for c in Crop.objects.filter(slug__in=[h["crop_code"] for h in hasil_model])}
    return [_item(h, crops[h["crop_code"]], kondisi) for h in hasil_model if h["crop_code"] in crops]


def format_recommendation(prediksi, kondisi):
    hasil = {
        "kondisi_lahan": kondisi,
        "rekomendasi": format_daftar(prediksi["rekomendasi"], kondisi),
        "rekomendasi_bulan_tanam": None,
    }
    if prediksi.get("rekomendasi_bulan_tanam"):
        hasil["rekomendasi_bulan_tanam"] = {
            "bulan": prediksi["bulan_tanam"],
            "daftar": format_daftar(prediksi["rekomendasi_bulan_tanam"], kondisi),
        }
    return hasil
