# Celery opsional: kalau paketnya tidak terpasang, backend tetap jalan
# dengan antrian thread (lihat recommendation/services/jobs.py).
try:
    from .celery import app as celery_app  # noqa: F401
except ImportError:  # pragma: no cover
    celery_app = None
