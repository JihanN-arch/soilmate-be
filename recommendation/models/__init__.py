# Semua model didaftarkan di sini supaya Django selalu menemukannya
# (sebelumnya folder ini tidak punya __init__.py dan model hanya
# terdaftar kebetulan lewat import di views).
from .crop_models import Crop  # noqa: F401
from .riwayat_models import RiwayatPencarian, RiwayatRekomendasi  # noqa: F401
from .ekonomi_models import HargaKomoditas  # noqa: F401
from .cache_models import DataCache  # noqa: F401
from .job_models import AnalisisJob  # noqa: F401
from .monitoring_models import (  # noqa: F401
    LahanTanam, ObservasiNdvi, FeedbackPengguna, UsabilityEvent)
