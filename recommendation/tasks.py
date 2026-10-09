"""Tugas Celery (hanya dipakai kalau CELERY_BROKER_URL / REDIS_URL di-set)."""
from celery import shared_task

from .services import jobs


@shared_task
def tugas_analisis(job_id):
    jobs.jalankan_analisis(job_id)


@shared_task
def tugas_pantau_lahan(lahan_id):
    jobs.TUGAS["pantau_lahan"](lahan_id)
