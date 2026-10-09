"""Precompute data statis (tanah, iklim, satelit) untuk satu wilayah ke DataCache.

Contoh (Kabupaten Bogor kira-kira):
    python manage.py precompute_statis --bbox 106.4 -6.8 107.2 -6.3 --step 0.02

Setelah ini, request di wilayah tsb tidak perlu menunggu API eksternal, dan
kalau API down, sel tetangga dipakai sebagai cadangan (radius tanah 1 km,
iklim 15 km). Jadi step 0,01-0,02 deg sudah cukup; tidak perlu sehalus
resolusi asli.

PERHATIAN kuota:
- SoilGrids punya kebijakan fair use (sekitar 5 request/menit); default
  --jeda-tanah 12 detik. Satu titik bisa memicu sampai 5 request kalau
  pikselnya kosong. Cek kebijakan terbaru ISRIC sebelum menjalankan besar.
- Open-Meteo gratis untuk non-komersial dengan batas harian; request iklim
  3 tahun dihitung lebih berat dari request biasa.
Jalankan untuk wilayah pilot dulu, bukan seluruh Indonesia.
"""
import time

from django.core.management.base import BaseCommand

from recommendation.services import cache
from recommendation.services.apis import gee
from recommendation.services.data_tanah import _fetch_dengan_sekitar
from recommendation.services.environment_service import _iklim_valid
from recommendation.services.errors import SumberDataGagal

FETCH = {"tanah": _fetch_dengan_sekitar, "iklim": _iklim_valid, "satelit": gee.fetch_satelit}


class Command(BaseCommand):
    help = "Precompute data lingkungan statis untuk wilayah (bbox) ke cache."

    def add_arguments(self, p):
        p.add_argument("--bbox", nargs=4, type=float, required=True,
                       metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"))
        p.add_argument("--step", type=float, default=0.02, help="jarak titik dalam derajat")
        p.add_argument("--sumber", nargs="+", default=["tanah", "iklim"], choices=list(FETCH))
        p.add_argument("--jeda-tanah", type=float, default=12.0)
        p.add_argument("--jeda-lain", type=float, default=1.0)
        p.add_argument("--timpa", action="store_true", help="tarik ulang walau cache masih segar")
        p.add_argument("--dry-run", action="store_true", help="hanya hitung jumlah titik")

    def handle(self, *args, bbox, step, sumber, jeda_tanah, jeda_lain, timpa, dry_run, **kw):
        min_lon, min_lat, max_lon, max_lat = bbox
        titik = []
        lat = min_lat
        while lat <= max_lat + 1e-9:
            lon = min_lon
            while lon <= max_lon + 1e-9:
                titik.append((round(lat, 6), round(lon, 6)))
                lon += step
            lat += step

        detik = len(titik) * sum(jeda_tanah if s == "tanah" else jeda_lain for s in sumber)
        self.stdout.write(f"{len(titik)} titik x {len(sumber)} sumber, perkiraan >= {detik / 60:.0f} menit")
        if dry_run:
            return

        stat = {s: {"baru": 0, "lewati": 0, "gagal": 0} for s in sumber}
        for i, (la, lo) in enumerate(titik, start=1):
            for s in sumber:
                ada = cache.ambil(s, la, lo)
                if ada and ada[1] and not timpa:
                    stat[s]["lewati"] += 1
                    continue
                try:
                    cache.simpan(s, la, lo, FETCH[s](la, lo))
                    stat[s]["baru"] += 1
                except SumberDataGagal as e:
                    stat[s]["gagal"] += 1
                    self.stderr.write(f"  {s} ({la}, {lo}) gagal: {e}")
                time.sleep(jeda_tanah if s == "tanah" else jeda_lain)
            if i % 10 == 0 or i == len(titik):
                self.stdout.write(f"[{i}/{len(titik)}] {stat}")
        self.stdout.write(self.style.SUCCESS(f"Selesai: {stat}"))
