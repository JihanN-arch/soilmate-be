"""Impor harga komoditas dari CSV (mis. unduhan Panel Harga Bapanas yang sudah dirapikan).

Kolom wajib : crop_slug, tanggal (YYYY-MM-DD), harga_per_kg
Kolom opsi  : tingkat (produsen|konsumen, default produsen), wilayah_kode, wilayah_nama, sumber

    python manage.py import_harga harga.csv --sumber "Panel Harga Bapanas"
"""
import csv

from django.core.management.base import BaseCommand, CommandError

from recommendation.models.crop_models import Crop
from recommendation.models.ekonomi_models import HargaKomoditas


class Command(BaseCommand):
    help = "Impor deret harga komoditas dari CSV."

    def add_arguments(self, p):
        p.add_argument("path")
        p.add_argument("--sumber", default=None, help="isi kolom sumber kalau CSV tidak punya")

    def handle(self, *args, path, sumber, **kw):
        crops = {c.slug: c for c in Crop.objects.all()}
        baru = diperbarui = dilewati = 0
        try:
            f = open(path, newline="", encoding="utf-8-sig")
        except OSError as e:
            raise CommandError(e)
        with f:
            for i, row in enumerate(csv.DictReader(f), start=2):
                crop = crops.get((row.get("crop_slug") or "").strip())
                if crop is None or not row.get("harga_per_kg") or not row.get("tanggal"):
                    dilewati += 1
                    self.stderr.write(f"baris {i} dilewati: {row}")
                    continue
                _, dibuat = HargaKomoditas.objects.update_or_create(
                    crop=crop, tanggal=row["tanggal"].strip(),
                    tingkat=(row.get("tingkat") or "produsen").strip(),
                    wilayah_kode=(row.get("wilayah_kode") or "").strip() or None,
                    defaults={
                        "harga_per_kg": int(float(row["harga_per_kg"])),
                        "wilayah_nama": (row.get("wilayah_nama") or "").strip() or None,
                        "sumber": (row.get("sumber") or "").strip() or sumber,
                    })
                baru += dibuat
                diperbarui += not dibuat
        self.stdout.write(self.style.SUCCESS(
            f"Impor selesai: {baru} baru, {diperbarui} diperbarui, {dilewati} dilewati"))
