from django.db import models

from .crop_models import Crop
from .riwayat_models import RiwayatRekomendasi


class LahanTanam(models.Model):
    """Lahan yang sedang ditanami petani ("Saya menanam ini")."""

    STATUS_CHOICES = [
        ("aktif", "Aktif"),
        ("panen", "Sudah panen"),
        ("gagal", "Gagal"),
        ("dihentikan", "Dihentikan"),
    ]

    anonymous_id = models.CharField(max_length=100, db_index=True)
    nama = models.CharField(max_length=100, null=True, blank=True)
    rekomendasi = models.ForeignKey(
        RiwayatRekomendasi, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="lahan_tanam")
    crop = models.ForeignKey(Crop, on_delete=models.PROTECT)
    lat = models.FloatField()
    lon = models.FloatField()
    radius_m = models.PositiveIntegerField(default=50)
    luas_lahan_m2 = models.FloatField(null=True, blank=True)
    tanggal_tanam = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="aktif")

    kesehatan = models.CharField(max_length=30, default="belum_cukup_data")
    peringatan = models.JSONField(default=list)
    terakhir_dipantau = models.DateTimeField(null=True, blank=True)
    dibuat_pada = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-dibuat_pada"]


class ObservasiNdvi(models.Model):
    lahan = models.ForeignKey(LahanTanam, on_delete=models.CASCADE, related_name="observasi")
    tanggal = models.DateField()
    ndvi = models.FloatField()
    piksel_valid = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["tanggal"]
        constraints = [
            models.UniqueConstraint(fields=["lahan", "tanggal"], name="unique_observasi_harian")
        ]


class FeedbackPengguna(models.Model):
    JENIS_CHOICES = [
        ("rekomendasi", "Tanggapan atas rekomendasi"),
        ("hasil_panen", "Hasil panen"),
        ("aplikasi", "Masukan aplikasi"),
    ]
    HASIL_CHOICES = [("baik", "Baik"), ("sedang", "Sedang"), ("buruk", "Buruk"), ("gagal", "Gagal")]

    anonymous_id = models.CharField(max_length=100, db_index=True)
    jenis = models.CharField(max_length=20, choices=JENIS_CHOICES)
    rekomendasi = models.ForeignKey(
        RiwayatRekomendasi, null=True, blank=True, on_delete=models.SET_NULL)
    lahan = models.ForeignKey(LahanTanam, null=True, blank=True, on_delete=models.SET_NULL)
    ditanam = models.BooleanField(null=True, blank=True)
    hasil = models.CharField(max_length=10, choices=HASIL_CHOICES, null=True, blank=True)
    hasil_panen_kg = models.FloatField(null=True, blank=True)
    luas_lahan_m2 = models.FloatField(null=True, blank=True)
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    komentar = models.TextField(blank=True, default="")
    dibuat_pada = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-dibuat_pada"]


class UsabilityEvent(models.Model):
    """Log anonim untuk mengukur task success rate, waktu tugas, dan SUS.

    Format dari FE: {anonymous_id, sesi_id, event, tugas, peserta, mode_tes,
    halaman, waktu, data}. `berhasil` dan `durasi_ms` disalin dari `data`
    supaya mudah di-query.
    """

    anonymous_id = models.CharField(max_length=100, db_index=True, blank=True, default="")
    sesi_id = models.CharField(max_length=100, db_index=True)
    event = models.CharField(max_length=50, db_index=True)   # tugas_mulai, tugas_selesai, sus, ...
    tugas = models.CharField(max_length=50, null=True, blank=True)
    peserta = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    mode_tes = models.BooleanField(default=False)
    halaman = models.CharField(max_length=200, null=True, blank=True)
    data = models.JSONField(default=dict, blank=True)
    berhasil = models.BooleanField(null=True, blank=True)
    durasi_ms = models.PositiveIntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)      # format lama
    waktu_klien = models.DateTimeField(null=True, blank=True)
    dibuat_pada = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["dibuat_pada"]
