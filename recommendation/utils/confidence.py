"""Tingkat kepercayaan rekomendasi (aturan dari tim ML, 10 Okt 2026).

`confidence` dari ml_lib = kestabilan skor & peringkat tanaman ketika pH,
curah hujan, dan tekstur digoyang sebesar ketidakpastiannya (0-1). Ini BUKAN
probabilitas tanaman cocok. Kualitas data pH sudah ikut dihitung di sana
(lewat ph_terukur dan ph_q05/ph_q95), jadi tidak ada aturan "uji tanah > API"
terpisah.

  Tinggi : confidence >= 0,75
  Sedang : 0,50 <= confidence < 0,75
  Rendah : confidence < 0,50

Turun satu tingkat kalau data iklim atau elevasi berasal dari data cadangan.

Cadangan untuk ml_lib lama (confidence None): label dari kualitas data saja.
"""

TINGKAT = ["Rendah", "Sedang", "Tinggi"]
SUMBER_CADANGAN = {"cache_kedaluwarsa", "tetangga", "open_meteo_dem"}


def _dari_confidence(c):
    return "Tinggi" if c >= 0.75 else "Sedang" if c >= 0.50 else "Rendah"


def get_confidence(confidence_ml, sumber_data=None, kualitas_skor=None):
    sumber_data = sumber_data or {}
    alasan_turun = [f"data {k} dari sumber cadangan" for k in ("iklim", "elevasi")
                    if sumber_data.get(k) in SUMBER_CADANGAN]

    if confidence_ml is None:  # ml_lib lama / tanaman tanpa confidence
        k = kualitas_skor if kualitas_skor is not None else 0.7
        dasar = "Tinggi" if k >= 0.85 else "Sedang" if k >= 0.65 else "Rendah"
        metode = "kualitas_data"
    else:
        dasar = _dari_confidence(confidence_ml)
        metode = "kestabilan_skor"

    label = dasar
    if alasan_turun and TINGKAT.index(label) > 0:
        label = TINGKAT[TINGKAT.index(label) - 1]

    return label, {
        "metode": metode,
        "confidence_ml": None if confidence_ml is None else round(confidence_ml, 3),
        # dipertahankan untuk FE lama
        "skor": round(confidence_ml if confidence_ml is not None else (kualitas_skor or 0), 3),
        "tingkat_dasar": dasar,
        "diturunkan_karena": alasan_turun,
        "kualitas_data": kualitas_skor,
    }
