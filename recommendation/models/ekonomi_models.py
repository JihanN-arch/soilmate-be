from django.db import models

from .crop_models import Crop


class HargaKomoditas(models.Model):
    """Deret harga per komoditas (mis. dari Panel Harga Bapanas / PIHPS)."""

    TINGKAT_CHOICES = [("produsen", "Produsen"), ("konsumen", "Konsumen")]

    crop = models.ForeignKey(Crop, on_delete=models.CASCADE, related_name="harga")
    tanggal = models.DateField()
    tingkat = models.CharField(max_length=10, choices=TINGKAT_CHOICES, default="produsen")
    harga_per_kg = models.PositiveIntegerField(help_text="Rupiah per kg")
    wilayah_kode = models.CharField(max_length=20, null=True, blank=True)
    wilayah_nama = models.CharField(max_length=100, null=True, blank=True)
    sumber = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        ordering = ["-tanggal"]
        indexes = [models.Index(fields=["crop", "tingkat", "-tanggal"])]
        constraints = [
            models.UniqueConstraint(
                fields=["crop", "tanggal", "tingkat", "wilayah_kode"],
                name="unique_harga_per_hari",
            )
        ]

    def __str__(self):
        return f"{self.crop_id} {self.tingkat} {self.tanggal}: Rp{self.harga_per_kg}/kg"
