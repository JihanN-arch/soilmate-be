from django.db import models


class Crop(models.Model):
    slug = models.SlugField(primary_key=True)

    nama = models.CharField(max_length=100)
    nama_latin = models.CharField(max_length=150)
    deskripsi = models.TextField()
    jenis_tanaman = models.CharField(max_length=100)
    umur_panen = models.CharField(max_length=100)
    # teks tampilan, mis. "20-25 ton/ha" (dipertahankan untuk FE lama)
    produktivitas_tanaman = models.CharField(max_length=100)
    manfaat = models.TextField()
    cara_budidaya = models.TextField()
    # hanya dipakai untuk info tampilan (mis. "kesuburan").
    # Syarat tumbuh untuk PENILAIAN selalu dibaca dari ml_lib/seed.json
    # supaya alasan dan skor memakai angka yang sama.
    syarat_tumbuh = models.JSONField()

    # ---- Lapisan ekonomi (boleh kosong dulu) ----
    produktivitas_min_ton_ha = models.FloatField(null=True, blank=True)
    produktivitas_max_ton_ha = models.FloatField(null=True, blank=True)
    biaya_produksi_per_ha = models.PositiveBigIntegerField(
        null=True, blank=True, help_text="Rupiah per hektar per musim tanam")
    sumber_biaya = models.CharField(max_length=200, null=True, blank=True)
    tahun_biaya = models.PositiveSmallIntegerField(null=True, blank=True)

    def __str__(self):
        return self.nama
