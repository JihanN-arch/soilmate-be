"""
Bangun preprocessor & pecah data latih/uji.

Jalankan dari ROOT repo sebagai modul:  `python -m ml_lib.preprocess`
BUKAN `python ml_lib/preprocess.py` -- cara itu tidak menaruh root repo di
sys.path, jadi `from ml_lib import ...` gagal.

Membaca `synthetic_training_dataset.csv` dari direktori kerja (root repo).
Menulis `preprocessor.joblib` + `feature_names.txt` ke ml_lib/ (artefak
inference) dan `X_*.npy` / `y_*.npy` ke direktori kerja (berkas antara).
"""

import os

import numpy as np
import pandas as pd
import joblib

from ml_lib import ARTIFACT_DIR

from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.model_selection import train_test_split

RANDOM_STATE = 42
TEST_SIZE = 0.2
MIN_SAMPLES_PER_CLASS = 20   # di bawah ini kelas dibuang (lihat catatan di main)

# Fitur musim (rain_wet3, rain_dry3, bulan_basah, bulan_kering) diturunkan dari
# hujan bulanan oleh climate_features.derive(). Tanpa ini model hanya melihat
# total hujan setahun, yang keliru untuk palawija: kebutuhan air di seed.json
# adalah per-musim-tanam, bukan per-tahun. Lihat climate_features.py.
NUMERIC_FEATURES = ["ph", "rainfall_mm", "rain_wet3", "rain_dry3",
                    "bulan_basah", "bulan_kering", "temp_c", "elevation_m", "ndvi"]
CATEGORICAL_FEATURES = ["soil_texture"]
LABEL_COL = "crop_code"


def build_preprocessor() -> ColumnTransformer:
    """Bangun ColumnTransformer: numerik -> imputasi+scaling, kategorikal -> imputasi+one-hot."""
    numeric_pipeline = Pipeline(steps=[
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
    ])

    categorical_pipeline = Pipeline(steps=[
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("onehot", OneHotEncoder(handle_unknown="ignore")),
    ])

    preprocessor = ColumnTransformer(transformers=[
        ("num", numeric_pipeline, NUMERIC_FEATURES),
        ("cat", categorical_pipeline, CATEGORICAL_FEATURES),
    ])
    return preprocessor


def main():
    df = pd.read_csv("synthetic_training_dataset.csv")

    # Buang kelas yang sampelnya terlalu sedikit utk dilatih/di-split.
    # Ini BUKAN pembersihan kosmetik: kelas yang tersisih di sini adalah
    # tanaman yang hampir tidak pernah menjadi pemenang rule_based_scorer pada
    # lahan Indonesia yang realistis. Model hasilnya TIDAK BISA
    # merekomendasikan tanaman tsb sama sekali -- keterbatasan yang harus
    # disebut, bukan disembunyikan. Lihat catatan di README/laporan.
    n_kelas = df[LABEL_COL].value_counts()
    kurang = n_kelas[n_kelas < MIN_SAMPLES_PER_CLASS]
    if len(kurang):
        print(f"PERINGATAN: {len(kurang)} kelas dibuang krn sampel < {MIN_SAMPLES_PER_CLASS}:")
        for c, n in kurang.items():
            print(f"  - {c}: {n} sampel")
        print(f"  Model TIDAK akan pernah merekomendasikan tanaman di atas.\n")
        df = df[~df[LABEL_COL].isin(kurang.index)].reset_index(drop=True)

    X = df[NUMERIC_FEATURES + CATEGORICAL_FEATURES]
    y = df[LABEL_COL]

    # Split SEBELUM fit preprocessor -> mencegah data leakage.
    # stratify=y menjaga proporsi tiap kelas tanaman tetap seimbang di train & test.
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
    )

    preprocessor = build_preprocessor()

    # fit HANYA di data train
    X_train_proc = preprocessor.fit_transform(X_train)
    # transform (bukan fit) di data test -> pakai statistik dari train
    X_test_proc = preprocessor.transform(X_test)

    feature_names = preprocessor.get_feature_names_out()

    # Preprocessor terlatih adalah ARTEFAK INFERENCE: NusaCropModel memuatnya
    # dari ml_lib/, jadi simpan ke ARTIFACT_DIR dan bukan ke CWD. Kalau ditulis
    # ke CWD, latihan ulang tampak berhasil tetapi backend tetap memakai
    # preprocessor lama tanpa satu pun peringatan.
    joblib.dump(preprocessor, os.path.join(ARTIFACT_DIR, "preprocessor.joblib"))
    with open(os.path.join(ARTIFACT_DIR, "feature_names.txt"), "w") as f:
        f.write("\n".join(feature_names))

    # Matriks hasil transform hanya dipakai train_model.py, bukan saat
    # inference -> tetap di CWD (root repo) sebagai berkas antara.
    np.save("X_train.npy", X_train_proc)
    np.save("X_test.npy", X_test_proc)
    np.save("y_train.npy", y_train.to_numpy())
    np.save("y_test.npy", y_test.to_numpy())

    print(f"Data train : {X_train_proc.shape[0]} baris x {X_train_proc.shape[1]} fitur")
    print(f"Data test  : {X_test_proc.shape[0]} baris x {X_test_proc.shape[1]} fitur")
    print(f"\nFitur setelah encoding ({len(feature_names)}):")
    for fn in feature_names:
        print(f"  - {fn}")

    print(f"\nDistribusi kelas train:\n{y_train.value_counts().sort_index()}")
    print(f"\nDistribusi kelas test:\n{y_test.value_counts().sort_index()}")


if __name__ == "__main__":
    main()