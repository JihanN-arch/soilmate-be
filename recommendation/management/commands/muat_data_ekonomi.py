"""Muat data harga produsen dan biaya produksi dari folder data/ ke database.

    python manage.py muat_data_ekonomi

Aman dijalankan berulang (upsert). Cocok ditaruh di Pre-deploy Command Railway:
    python manage.py migrate && python manage.py seed_crop && python manage.py muat_data_ekonomi
"""
import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from recommendation.models.crop_models import Crop
from recommendation.models.ekonomi_models import HargaKomoditas

DATA = Path(settings.BASE_DIR) / "data"


class Command(BaseCommand):
    help = "Muat harga produsen & biaya produksi (data/*.csv) ke database."

    def add_arguments(self, p):
        p.add_argument("--harga", default=str(DATA / "harga_produsen_bps.csv"))
        p.add_argument("--biaya", default=str(DATA / "biaya_produksi_bps.csv"))
        p.add_argument("--acuan", default=str(DATA / "harga_acuan.csv"),
                       help="harga dari sumber lain; ganti_data_bps=ya membuang data BPS tanaman itu")

    @transaction.atomic
    def handle(self, *args, harga, biaya, acuan, **kw):
        crops = {c.slug: c for c in Crop.objects.all()}
        if not crops:
            self.stderr.write("Tabel Crop kosong; jalankan seed_crop dulu.")
            return

        baris_acuan = []
        if Path(acuan).exists():
            with open(acuan, newline="", encoding="utf-8") as f:
                baris_acuan = list(csv.DictReader(f))
        ganti_bps = {r["crop_slug"] for r in baris_acuan
                     if (r.get("ganti_data_bps") or "").strip().lower() in ("ya", "yes", "true", "1")}
        if ganti_bps:
            # buang data BPS lama tanaman itu (mis. dari deploy sebelumnya)
            HargaKomoditas.objects.filter(crop_id__in=ganti_bps, sumber__startswith="BPS").delete()

        objek, lewat = [], 0
        with open(harga, newline="", encoding="utf-8") as f:
            for r in list(csv.DictReader(f)) + baris_acuan:
                crop = crops.get(r["crop_slug"])
                dari_bps = r not in baris_acuan
                if crop is None or not r["harga_per_kg"] or (dari_bps and crop.slug in ganti_bps):
                    lewat += 1
                    continue
                objek.append(HargaKomoditas(
                    crop=crop, tanggal=r["tanggal"], harga_per_kg=int(float(r["harga_per_kg"])),
                    tingkat=r.get("tingkat") or "produsen", wilayah_kode=r.get("wilayah_kode") or None,
                    wilayah_nama=r.get("wilayah_nama") or None, sumber=(r.get("sumber") or "")[:100] or None))
        HargaKomoditas.objects.bulk_create(
            objek, batch_size=1000, update_conflicts=True,
            unique_fields=["crop", "tanggal", "tingkat", "wilayah_kode"],
            update_fields=["harga_per_kg", "wilayah_nama", "sumber"])

        n_biaya = 0
        with open(biaya, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                crop = crops.get(r["crop_slug"])
                if crop is None or not r["biaya_produksi_per_ha"]:
                    continue
                crop.biaya_produksi_per_ha = int(float(r["biaya_produksi_per_ha"]))
                crop.tahun_biaya = int(r["tahun"]) if r.get("tahun") else None
                crop.sumber_biaya = (r.get("sumber") or "")[:200] or None
                crop.save(update_fields=["biaya_produksi_per_ha", "tahun_biaya", "sumber_biaya"])
                n_biaya += 1

        self.stdout.write(self.style.SUCCESS(
            f"Data ekonomi dimuat: {len(objek)} baris harga ({lewat} dilewati; "
            f"data BPS diganti untuk: {', '.join(sorted(ganti_bps)) or '-'}), "
            f"biaya produksi {n_biaya} tanaman."))
