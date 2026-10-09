"""Pipeline rekomendasi: kondisi lahan -> model -> format -> riwayat.

Dipakai oleh endpoint sinkron (/api/recommend/) dan job asinkron
(/api/analisis/), jadi keduanya selalu memberi hasil yang sama.
"""
from django.db import transaction
from django.utils import timezone

from ..ml.ml_model import predict
from ..models.riwayat_models import RiwayatPencarian, RiwayatRekomendasi
from ..utils.formatter import format_recommendation
from .environment_service import get_environment

# musim_target lama dipetakan ke bulan awal musimnya (1-12)
MUSIM_KE_BULAN = {"hujan": 11, "kemarau": 5}


def get_recommendation(data, anonymous_id, progres=None):
    """Melempar DataTidakLengkap / SumberDataGagal / PrediksiGagal kalau gagal."""
    # Sama dengan recommend_dua() di ml_lib: daftar kedua ("tanam_sekarang")
    # selalu ada. Kalau pengguna tidak memilih bulan, pakai bulan berjalan.
    bulan_tanam = (data.get("bulan_tanam") or MUSIM_KE_BULAN.get(data.get("musim_target"))
                   or timezone.localdate().month)

    kondisi = get_environment(data["lat"], data["lon"], data.get("uji_tanah"), progres)
    kondisi["luas_lahan_m2"] = data.get("luas_lahan_m2")
    if progres:
        progres("model", "berjalan")
    prediksi = predict(kondisi, bulan_tanam=bulan_tanam)
    hasil = format_recommendation(prediksi, kondisi)

    with transaction.atomic():
        riwayat = RiwayatPencarian.objects.create(
            anonymous_id=anonymous_id,
            nama_lokasi=data.get("nama_lokasi"),
            lat=data["lat"], lon=data["lon"],
            musim_target=data.get("musim_target"),
            bulan_tanam=bulan_tanam,
            curah_hujan=kondisi["curah_hujan"],
            ph_tanah=kondisi["ph_tanah"],
            elevasi=kondisi["elevasi"],
            ndvi=kondisi.get("ndvi"),
            suhu=kondisi["suhu"],
            et0=kondisi.get("et0"),
            nitrogen=kondisi.get("nitrogen"),
            organic_carbon=kondisi.get("organic_carbon"),
            tekstur_tanah=kondisi.get("tekstur_tanah") or {},
            kesuburan_tanah=kondisi.get("kesuburan_tanah"),
            kemiringan=kondisi.get("kemiringan"),
            uji_tanah=data.get("uji_tanah"),
            sumber_data=kondisi["sumber_data"],
            kualitas_data=kondisi["kualitas_data"]["skor"],
            luas_lahan_m2=data.get("luas_lahan_m2"),
            curah_hujan_bulanan=kondisi["curah_hujan_bulanan"],
            tekstur_kelas=kondisi["tekstur_kelas"],
        )

        def simpan_item(item, ranking, daftar):
            rek = RiwayatRekomendasi.objects.create(
                riwayat=riwayat,
                crop_id=item["id"],
                jenis_tanaman=item["jenis_tanaman"],
                skor_kesesuaian=item["skor_kesesuaian"],
                ranking=ranking,
                tingkat_kepercayaan=item["tingkat_kepercayaan"],
                alasan_rekomendasi=item["alasan_rekomendasi"],
                mulai_tanam=item["mulai_tanam"],
                musim_tanam_mm=item["musim_tanam_mm"],
                rincian_skor=item["rincian_skor"],
                faktor_pembatas=item["faktor_pembatas"],
                detail_kepercayaan=item["detail_kepercayaan"],
                daftar=daftar,
            )
            return rek.id

        id_per_crop = {}
        for i, item in enumerate(hasil["rekomendasi"], start=1):
            item["rekomendasi_id"] = id_per_crop[item["id"]] = simpan_item(item, i, "utama")

        # tab "cocok ditanam bulan X": pakai id yang sama kalau tanamannya sudah
        # ada di daftar utama, kalau belum disimpan terpisah agar detail bisa dibuka
        if hasil["rekomendasi_bulan_tanam"]:
            for i, item in enumerate(hasil["rekomendasi_bulan_tanam"]["daftar"], start=1):
                item["rekomendasi_id"] = id_per_crop.get(item["id"]) or simpan_item(item, i, "bulan_tanam")

        hasil["riwayat_id"] = riwayat.id
        riwayat.hasil_snapshot = hasil
        riwayat.save(update_fields=["hasil_snapshot"])

    if progres:
        progres("model", "selesai")
    return {"status": "success", "recommendation": hasil}
