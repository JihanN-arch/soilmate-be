"""Monitoring pasca-tanam berbasis deret NDVI Sentinel-2.

Aturan peringatan (sengaja sederhana dan bisa dijelaskan ke petani):
- penurunan_tajam   : NDVI terbaru turun > 0,15 dari nilai tertinggi
                      3 observasi sebelumnya (tanaman stres/rusak/dipanen).
- pertumbuhan_lambat: > 45 hari setelah tanam tetapi NDVI masih < 0,25
                      (masih menyerupai tanah terbuka).
- data_tertunda     : tidak ada citra bebas awan dalam 20 hari terakhir.
"""
import logging
from datetime import timedelta

from django.utils import timezone

from ..models.monitoring_models import LahanTanam, ObservasiNdvi
from .apis import gee
from .errors import SumberDataGagal

logger = logging.getLogger(__name__)

AMBANG_TURUN = 0.15
AMBANG_LAMBAT = 0.25
HARI_LAMBAT = 45
HARI_TERTUNDA = 20


def analisis_tren(observasi, tanggal_tanam, hari_ini=None):
    """observasi: list (tanggal: date, ndvi: float) terurut. -> (kesehatan, peringatan)"""
    hari_ini = hari_ini or timezone.localdate()
    peringatan = []
    if hari_ini < tanggal_tanam:          # jadwal tanam di masa depan
        return "dijadwalkan", peringatan

    if observasi and (hari_ini - observasi[-1][0]).days > HARI_TERTUNDA:
        peringatan.append({"jenis": "data_tertunda", "tingkat": "info",
                           "pesan": "Belum ada citra satelit bebas awan dalam 20 hari terakhir; "
                                    "status mungkin belum terbaru."})

    if len(observasi) >= 2:
        terbaru = observasi[-1][1]
        sebelumnya = max(v for _, v in observasi[-4:-1])
        if sebelumnya - terbaru > AMBANG_TURUN:
            peringatan.append({"jenis": "penurunan_tajam", "tingkat": "waspada",
                               "pesan": "Kehijauan tanaman turun cukup tajam dibanding pengamatan "
                                        "sebelumnya. Periksa kemungkinan kekeringan, hama, atau penyakit."})

    if observasi and (hari_ini - tanggal_tanam).days > HARI_LAMBAT and observasi[-1][1] < AMBANG_LAMBAT:
        peringatan.append({"jenis": "pertumbuhan_lambat", "tingkat": "waspada",
                           "pesan": "Lebih dari 45 hari setelah tanam, kehijauan lahan masih rendah. "
                                    "Periksa apakah tanaman tumbuh dengan baik."})

    if len(observasi) < 2:
        kesehatan = "belum_cukup_data"
    elif any(p["tingkat"] == "waspada" for p in peringatan):
        kesehatan = "perlu_dicek"
    else:
        kesehatan = "baik"
    return kesehatan, peringatan


def perbarui_lahan(lahan_id):
    lahan = LahanTanam.objects.get(pk=lahan_id)
    mulai = lahan.tanggal_tanam - timedelta(days=30)   # baseline sebelum tanam
    try:
        deret = gee.fetch_deret_ndvi(lahan.lat, lahan.lon, mulai, radius_m=lahan.radius_m)
    except SumberDataGagal as e:
        logger.warning("Monitoring lahan %s gagal: %s", lahan_id, e)
        return False

    for d in deret:
        ObservasiNdvi.objects.update_or_create(
            lahan=lahan, tanggal=d["tanggal"],
            defaults={"ndvi": d["ndvi"], "piksel_valid": d["piksel_valid"]})

    obs = list(lahan.observasi.filter(tanggal__gte=lahan.tanggal_tanam).values_list("tanggal", "ndvi"))
    lahan.kesehatan, lahan.peringatan = analisis_tren(obs, lahan.tanggal_tanam)
    lahan.terakhir_dipantau = timezone.now()
    lahan.save(update_fields=["kesehatan", "peringatan", "terakhir_dipantau"])
    return True


BULAN_ID = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus",
            "September", "Oktober", "November", "Desember"]
MIN_CITRA_GRAFIK = 2


def _tgl(d):
    return f"{d.day} {BULAN_ID[d.month - 1]} {d.year}"


def status_tampilan(lahan, hari_ini=None):
    """Status pemantauan siap tampil untuk FE (dihitung saat dibaca, jadi tidak basi).

    Mengembalikan dict: kesehatan, pesan_status, hari_menuju_tanam,
    jumlah_citra_setelah_tanam, grafik_siap.
    """
    hari_ini = hari_ini or timezone.localdate()
    n = lahan.observasi.filter(tanggal__gte=lahan.tanggal_tanam).count()
    hasil = {"jumlah_citra_setelah_tanam": n, "grafik_siap": n >= MIN_CITRA_GRAFIK,
             "hari_menuju_tanam": None}

    if hari_ini < lahan.tanggal_tanam:
        hasil.update(
            kesehatan="dijadwalkan",
            hari_menuju_tanam=(lahan.tanggal_tanam - hari_ini).days,
            pesan_status=(f"Dijadwalkan tanam {_tgl(lahan.tanggal_tanam)}. Pemantauan lewat satelit "
                          "dimulai setelah tanggal tanam."))
        return hasil

    kesehatan = lahan.kesehatan
    if kesehatan == "dijadwalkan":       # tersimpan sebelum tanggal tanam lewat
        kesehatan = "belum_cukup_data"
    if kesehatan == "belum_cukup_data" or n < MIN_CITRA_GRAFIK:
        kesehatan = "belum_cukup_data" if kesehatan in ("belum_cukup_data", "baik") else kesehatan
        pesan = ("Menunggu foto satelit pertama setelah tanam. " if n == 0 else
                 "Sudah ada 1 foto satelit setelah tanam; grafik kehijauan muncul setelah ada 1 foto lagi. ")
        pesan += ("Satelit memotret lahan kira-kira tiap 5 hari, tetapi foto yang tertutup awan tidak "
                  "dipakai, jadi biasanya butuh 1-3 minggu.")
    elif kesehatan == "perlu_dicek":
        pesan = "Ada tanda yang perlu dicek langsung di lahan. Lihat peringatan di bawah."
    else:
        pesan = "Kehijauan tanaman berkembang normal menurut foto satelit."
    hasil.update(kesehatan=kesehatan, pesan_status=pesan)
    return hasil


def hitung_ulang(lahan):
    """Hitung ulang status dari observasi yang sudah tersimpan (tanpa memanggil GEE)."""
    obs = list(lahan.observasi.filter(tanggal__gte=lahan.tanggal_tanam).values_list("tanggal", "ndvi"))
    lahan.kesehatan, lahan.peringatan = analisis_tren(obs, lahan.tanggal_tanam)
    lahan.save(update_fields=["kesehatan", "peringatan"])
