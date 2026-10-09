"""Perbarui NDVI semua lahan aktif. Jadwalkan harian (mis. Railway Cron):
    python manage.py update_monitoring
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from recommendation.models.monitoring_models import LahanTanam
from recommendation.services.monitoring import perbarui_lahan


class Command(BaseCommand):
    help = "Tarik deret NDVI terbaru untuk lahan yang sedang ditanami."

    def add_arguments(self, p):
        p.add_argument("--min-jam", type=int, default=20,
                       help="lewati lahan yang dipantau kurang dari N jam lalu")

    def handle(self, *args, min_jam, **kw):
        batas = timezone.now() - timedelta(hours=min_jam)
        qs = LahanTanam.objects.filter(status="aktif").filter(
            Q(terakhir_dipantau__isnull=True) | Q(terakhir_dipantau__lt=batas))
        ok = gagal = 0
        for lahan in qs.iterator():
            if perbarui_lahan(lahan.id):
                ok += 1
            else:
                gagal += 1
        self.stdout.write(self.style.SUCCESS(f"Monitoring selesai: {ok} diperbarui, {gagal} gagal"))
