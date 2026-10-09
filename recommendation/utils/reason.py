"""Alasan rekomendasi dari rincian skor rule-based.

Dulu alasan dibuat dari syarat di models/data.py dan membandingkan curah
hujan TAHUNAN dengan kebutuhan per MUSIM TANAM, sehingga tidak sinkron
dengan skor. Sekarang alasan dibaca dari `rincian` hasil scorer yang sama
dan profil di ml_lib/seed.json (satu sumber kebenaran).
"""
from ..services.data_tanah import USDA_KE_ID


def _angka(x, desimal=1):
    if x is None:
        return "-"
    if float(x).is_integer():
        return f"{int(x):,}".replace(",", ".")
    return f"{x:.{desimal}f}".replace(".", ",")


def _rentang(lo, hi, satuan=""):
    return f"{_angka(lo)}–{_angka(hi)}{satuan}"


def _kalimat(label, nilai_teks, s, nama, opt, tol):
    if s >= 0.85:
        if opt is None:  # literatur tidak menyebut rentang optimal
            return True, f"{label} {nilai_teks} berada dalam rentang toleransi {nama} ({tol})."
        return True, f"{label} {nilai_teks} berada dalam rentang ideal {nama} ({opt})."
    if s >= 0.6:
        return True, f"{label} {nilai_teks} masih dalam toleransi {nama} ({tol})."
    if s > 0:
        return False, f"{label} {nilai_teks} mendekati batas toleransi {nama} ({tol})."
    return False, f"{label} {nilai_teks} di luar toleransi {nama} ({tol})."


def generate_reason(kondisi, profil, nama, rincian, musim_tanam_mm=None, mulai_tanam=None):
    """Mengembalikan (alasan, faktor_pembatas): dua list kalimat."""
    alasan, pembatas = [], []
    p = profil

    def opt(lo_k, hi_k, satuan=""):
        lo, hi = p.get(lo_k), p.get(hi_k)
        return _rentang(lo, hi, satuan) if lo is not None and hi is not None else None

    params = [
        ("ph", "pH tanah", _angka(kondisi.get("ph_tanah")),
         opt("ph_optimal_min", "ph_optimal_max"), _rentang(p["ph_min"], p["ph_max"])),
        ("rainfall", "Air hujan selama musim tanam", f"(~{_angka(musim_tanam_mm)} mm)",
         opt("rainfall_optimal_min", "rainfall_optimal_max", " mm"),
         _rentang(p["rainfall_min"], p["rainfall_max"], " mm")),
        ("temp", "Suhu rata-rata", f"{_angka(kondisi.get('suhu'))}°C",
         opt("temp_optimal_min", "temp_optimal_max", "°C"),
         _rentang(p["temp_min"], p["temp_max"], "°C")),
        ("elevation", "Ketinggian", f"{_angka(kondisi.get('elevasi'))} mdpl",
         opt("elevation_optimal_min", "elevation_optimal_max", " mdpl"),
         _rentang(p.get("elevation_min"), p.get("elevation_max"), " mdpl")),
    ]
    for kunci, label, nilai, o, t in params:
        s = rincian.get(kunci)
        if s is None:
            continue
        positif, teks = _kalimat(label, nilai, s, nama, o, t)
        (alasan if positif else pembatas).append(teks)

    s_tex = rincian.get("texture")
    tekstur = kondisi.get("tekstur_kelas")
    if s_tex is not None and tekstur:
        t_id = USDA_KE_ID.get(tekstur, tekstur)
        if s_tex >= 0.85:
            alasan.append(f"Tekstur tanah {t_id} termasuk ideal untuk {nama}.")
        elif s_tex >= 0.5:
            alasan.append(f"Tekstur tanah {t_id} masih dapat ditoleransi {nama}.")
        else:
            pembatas.append(f"Tekstur tanah {t_id} kurang sesuai untuk {nama}.")

    if mulai_tanam:
        alasan.append(f"Waktu tanam terbaik mulai bulan {mulai_tanam}.")

    if not alasan:
        alasan.append("Rekomendasi berdasarkan kesesuaian keseluruhan kondisi lingkungan.")
    return alasan, pembatas
