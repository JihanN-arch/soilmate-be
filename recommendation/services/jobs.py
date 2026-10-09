"""Antrian job untuk pekerjaan lambat (GEE, SoilGrids, monitoring).

Dua mode, dipilih otomatis:
- CELERY_BROKER_URL / REDIS_URL di-set  -> Celery + Redis (tahan restart,
  bisa diskalakan; butuh service worker terpisah di Railway).
- tidak di-set                          -> thread pool di dalam proses web.
  Cukup untuk demo/prototype, tetapi job yang sedang jalan hilang kalau
  proses di-restart (job seperti itu ditandai gagal saat dicek, lihat
  tandai_job_macet).
- NUSACROP_JOB_SINKRON=True (tes)        -> dijalankan langsung.
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections, connection
from django.utils import timezone

from ..models.job_models import AnalisisJob
from .errors import DataTidakLengkap, PrediksiGagal, SumberDataGagal

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="nusacrop-job")
BATAS_MACET = timedelta(minutes=5)


def _pakai_celery():
    return bool(getattr(settings, "CELERY_BROKER_URL", None))


def kirim(nama_tugas, *args):
    """nama_tugas: 'analisis' | 'pantau_lahan'."""
    if getattr(settings, "NUSACROP_JOB_SINKRON", False):
        return TUGAS[nama_tugas](*args)
    if _pakai_celery():
        from .. import tasks
        return getattr(tasks, f"tugas_{nama_tugas}").delay(*args)
    return _executor.submit(_di_thread, TUGAS[nama_tugas], *args)


def _di_thread(fn, *args):
    close_old_connections()
    try:
        return fn(*args)
    except Exception:
        logger.exception("Job %s gagal", fn.__name__)
    finally:
        connection.close()


def jalankan_analisis(job_id):
    from .recommendation_services import get_recommendation

    job = AnalisisJob.objects.get(pk=job_id)
    job.status = "berjalan"
    job.progres = {"tanah": "menunggu", "iklim": "menunggu", "elevasi": "menunggu",
                   "satelit": "menunggu", "model": "menunggu"}
    job.save(update_fields=["status", "progres", "diperbarui_pada"])

    kunci = threading.Lock()
    progres = dict(job.progres)

    def lapor(sumber, status):
        with kunci:
            progres[sumber] = status
            # elevasi diambil bersama citra satelit; kalau satelit gagal,
            # environment_service melaporkan elevasi cadangan/gagal sendiri
            if sumber == "satelit" and status != "gagal":
                progres["elevasi"] = status
            AnalisisJob.objects.filter(pk=job_id).update(progres=dict(progres), diperbarui_pada=timezone.now())

    try:
        hasil = get_recommendation(job.input, job.anonymous_id, progres=lapor)
        AnalisisJob.objects.filter(pk=job_id).update(status="selesai", hasil=hasil, diperbarui_pada=timezone.now())
    except DataTidakLengkap as e:
        AnalisisJob.objects.filter(pk=job_id).update(
            status="perlu_input", diperbarui_pada=timezone.now(),
            error={"pesan": e.pesan, "butuh_input": e.butuh_input})
    except (SumberDataGagal, PrediksiGagal) as e:
        AnalisisJob.objects.filter(pk=job_id).update(
            status="gagal", error={"pesan": str(e)}, diperbarui_pada=timezone.now())
    except Exception:
        logger.exception("Analisis %s error tak terduga", job_id)
        AnalisisJob.objects.filter(pk=job_id).update(
            status="gagal", error={"pesan": "Terjadi kesalahan di server. Silakan coba lagi."},
            diperbarui_pada=timezone.now())


def tandai_job_macet(job):
    if job.status in ("antri", "berjalan") and timezone.now() - job.diperbarui_pada > BATAS_MACET:
        job.status = "gagal"
        job.error = {"pesan": "Analisis terhenti (server mungkin di-restart). Silakan coba lagi."}
        job.save(update_fields=["status", "error", "diperbarui_pada"])
    return job


def _pantau_lahan(lahan_id):
    from .monitoring import perbarui_lahan
    perbarui_lahan(lahan_id)


TUGAS = {"analisis": jalankan_analisis, "pantau_lahan": _pantau_lahan}
