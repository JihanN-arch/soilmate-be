"""
NUSA-CROP : paket inference yang berdiri sendiri.
==================================================

Semua yang dibutuhkan backend ada di dalam folder ini -- kode penilaian,
artefak model, dan `seed.json` -- jadi paket ini bisa disalin/di-install utuh
tanpa menyeret skrip pipeline training di root repo.

Pemakaian di backend:

    from ml_lib import NusaCropModel

    model = NusaCropModel()      # muat sekali saat startup, JANGAN per request
    hasil = model.recommend(...)

Lihat docstring `predict.py` untuk daftar parameter, sumber data yang wajib
dipakai (ERA5, bukan NASA POWER), dan keterbatasan yang harus ditampilkan.

ARTIFACT_DIR menunjuk ke folder ini. Skrip training di root memakainya supaya
`preprocessor.joblib`, `model_xgb.json`, dan `label_encoder.joblib` hasil
latihan ulang mendarat di tempat yang dibaca `NusaCropModel`, bukan di CWD.
Tanpa itu, latihan ulang tampak berhasil tetapi backend diam-diam tetap
memakai model lama.
"""

import os

ARTIFACT_DIR = os.path.dirname(os.path.abspath(__file__))

__all__ = ["ARTIFACT_DIR", "NusaCropModel"]


def __getattr__(name):
    # Sengaja lazy. `import ml_lib` yang hanya butuh ARTIFACT_DIR (skrip
    # training) jadi tidak ikut menarik xgboost/pandas, dan preprocess.py bisa
    # `from ml_lib import ARTIFACT_DIR` tanpa impor melingkar lewat predict.py
    # (predict.py mengimpor preprocess.py).
    if name == "NusaCropModel":
        from ml_lib.predict import NusaCropModel
        return NusaCropModel
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
