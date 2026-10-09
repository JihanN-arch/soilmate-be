import re

from django.core.management.base import BaseCommand

from recommendation.models.crop_models import Crop
from recommendation.models.data import TANAMAN_DATA


def parse_produktivitas(teks):
    """'1,5-2 ton/ha' -> (1.5, 2.0). None kalau tidak bisa dibaca."""
    if not teks or "ton" not in teks.lower():
        return None, None
    angka = [float(a.replace(",", ".")) for a in re.findall(r"\d+(?:[.,]\d+)?", teks)]
    if not angka:
        return None, None
    return min(angka), max(angka)


class Command(BaseCommand):
    help = "Isi/perbarui tabel Crop dari models/data.py (field ekonomi yang sudah diisi tidak ditimpa)."

    def handle(self, *args, **options):
        for slug, crop in TANAMAN_DATA.items():
            obj, _ = Crop.objects.update_or_create(
                slug=slug,
                defaults={k: crop[k] for k in (
                    "nama", "nama_latin", "deskripsi", "jenis_tanaman", "umur_panen",
                    "produktivitas_tanaman", "cara_budidaya", "manfaat", "syarat_tumbuh")},
            )
            if obj.produktivitas_min_ton_ha is None:
                pmin, pmax = parse_produktivitas(crop["produktivitas_tanaman"])
                obj.produktivitas_min_ton_ha, obj.produktivitas_max_ton_ha = pmin, pmax
                obj.save(update_fields=["produktivitas_min_ton_ha", "produktivitas_max_ton_ha"])
        self.stdout.write(self.style.SUCCESS(f"Seed selesai ({len(TANAMAN_DATA)} tanaman)."))
