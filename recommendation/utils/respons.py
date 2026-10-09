"""Format error yang seragam: {"status": ..., "pesan": "..."} di semua endpoint.

`pesan` selalu satu kalimat bahasa Indonesia yang bisa langsung ditampilkan.
Untuk error validasi, rincian per field tetap ada di `detail`.
"""
from django.http import Http404
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

LABEL = {
    "lat": "Lintang", "lon": "Bujur", "nama_lokasi": "Nama lokasi", "bulan_tanam": "Bulan tanam",
    "luas_lahan_m2": "Luas lahan", "uji_tanah": "Uji tanah", "ph": "pH", "tekstur_kelas": "Tekstur",
    "tanggal_tanam": "Tanggal tanam", "rekomendasi_id": "Rekomendasi", "riwayat_id": "Riwayat",
    "dosis_ton_ha": "Dosis kapur", "target_ph": "Target pH", "rating": "Rating",
    "anonymous_id": "ID pengguna", "sesi_id": "ID sesi", "event": "Event",
}


def galat(pesan, kode, status="error", **extra):
    return Response({"status": status, "pesan": pesan, **extra}, status=kode)


def _pesan_pertama(data, jalur=()):
    if isinstance(data, dict):
        for k, v in data.items():
            hasil = _pesan_pertama(v, jalur + (k,))
            if hasil:
                return hasil
    elif isinstance(data, list):
        for i, v in enumerate(data):
            hasil = _pesan_pertama(v, jalur if not isinstance(v, (dict, list)) else jalur + (i,))
            if hasil:
                return hasil
    elif data:
        kunci = [k for k in jalur if isinstance(k, str) and k != "non_field_errors"]
        label = LABEL.get(kunci[-1], kunci[-1]) if kunci else None
        return f"{label}: {data}" if label else str(data)
    return None


def exception_handler(exc, context):
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    resp = drf_exception_handler(exc, context)
    if resp is None:
        return None
    if isinstance(exc, exceptions.ValidationError):
        resp.data = {"status": "error", "pesan": _pesan_pertama(resp.data) or "Data tidak valid.",
                     "detail": resp.data}
    elif isinstance(exc, exceptions.Throttled):
        tunggu = f" Coba lagi dalam {int(exc.wait) + 1} detik." if exc.wait else ""
        resp.data = {"status": "error", "pesan": "Terlalu banyak permintaan." + tunggu}
    elif isinstance(exc, exceptions.NotFound):
        resp.data = {"status": "error", "pesan": "Data tidak ditemukan."}
    else:
        detail = resp.data.get("detail") if isinstance(resp.data, dict) else resp.data
        resp.data = {"status": "error", "pesan": str(detail)}
    return resp
