"""Diagnosis sumber data eksternal: berhasil/gagal dan berapa lama.

    python manage.py cek_sumber                     # titik default (Grobogan)
    python manage.py cek_sumber --lat -4.85 --lon 105.25

Tidak memakai cache, jadi benar-benar memanggil API. Jalankan di server
(Railway: `railway ssh`, lalu perintah ini) untuk melihat kondisi di sana.
"""
import os
import time

from django.core.management.base import BaseCommand

from recommendation.services.apis import gee, openmeteo, soilgrids
from recommendation.services.errors import SumberDataGagal


class Command(BaseCommand):
    help = "Uji koneksi ke GEE, SoilGrids, dan Open-Meteo beserta waktunya."

    def add_arguments(self, p):
        p.add_argument("--lat", type=float, default=-7.05)
        p.add_argument("--lon", type=float, default=110.92)

    def handle(self, *args, lat, lon, **kw):
        out = self.stdout.write
        out(f"Titik uji: {lat}, {lon}\n")
        key = os.getenv("GEE_SERVICE_ACCOUNT_KEY_JSON")
        out(f"GEE_SERVICE_ACCOUNT_KEY_JSON: "
            f"{'terisi (' + str(len(key)) + ' karakter)' if key else 'KOSONG'}")
        out(f"Kredensial GEE tersedia: {gee.kredensial_tersedia()}\n")

        uji = [
            ("SoilGrids", lambda: soilgrids.fetch_tanah(lat, lon)),
            ("Open-Meteo iklim", lambda: openmeteo.fetch_iklim(lat, lon)),
            ("Open-Meteo prakiraan", lambda: openmeteo.fetch_prakiraan(lat, lon)),
            ("GEE satelit", lambda: gee.fetch_satelit(lat, lon)),
        ]
        for nama, fn in uji:
            mulai = time.monotonic()
            try:
                hasil = fn()
                ringkas = {k: hasil.get(k) for k in list(hasil)[:4]} if isinstance(hasil, dict) else hasil
                out(self.style.SUCCESS(f"[OK]    {nama:22} {time.monotonic() - mulai:5.1f} s  {ringkas}"))
            except SumberDataGagal as e:
                out(self.style.ERROR(f"[GAGAL] {nama:22} {time.monotonic() - mulai:5.1f} s  {e}"))
            except Exception as e:
                out(self.style.ERROR(f"[ERROR] {nama:22} {time.monotonic() - mulai:5.1f} s  "
                                     f"{type(e).__name__}: {e}"))
