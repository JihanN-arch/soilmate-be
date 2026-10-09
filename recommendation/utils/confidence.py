"""Tingkat kepercayaan rekomendasi.

Dulu label ini diturunkan dari skor rule-based (skor_aturan / 100), padahal
skor itu sudah ditampilkan sebagai skor kesesuaian, jadi labelnya tidak
menambah informasi dan keliru disebut "keyakinan model".

Sekarang kepercayaan = seberapa bisa diandalkan DATA-nya, dikoreksi oleh
kesepakatan model ML:
  - basis: kualitas data (uji tanah > API > cache > lokasi tetangga)
  - turun 0,10 kalau model ML tidak menaruh tanaman ini di 3 besarnya
  - tanaman di luar kelas model (kacang_hijau, terong): tanpa koreksi

USULAN: aturan ini perlu disepakati dengan tim ML.
"""

TOP_ML = 3


def get_confidence(kualitas_skor, peringkat_ml, confidence_ml=None):
    skor = kualitas_skor
    ml_setuju = None if peringkat_ml is None else peringkat_ml <= TOP_ML
    if ml_setuju is False:
        skor -= 0.10
    label = "Tinggi" if skor >= 0.85 else "Sedang" if skor >= 0.65 else "Rendah"
    return label, {
        "skor": round(max(skor, 0), 2),
        "kualitas_data": kualitas_skor,
        "ml_setuju": ml_setuju,
        "peringkat_ml": peringkat_ml,
        "confidence_ml": None if confidence_ml is None else round(confidence_ml, 4),
    }
