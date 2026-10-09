"""
NUSA-CROP : Fitur iklim berbasis MUSIM TANAM, bukan total tahunan.
===================================================================

Masalah yang diperbaiki
-----------------------
Versi sebelumnya membandingkan rentang kebutuhan air tiap tanaman terhadap
curah hujan SETAHUN. Itu keliru: angka di DataTanaman.md (mis. sorgum
350-1500 mm) adalah kebutuhan air selama SATU MUSIM TANAM (~3-4 bulan),
bukan batas iklim tahunan.

Akibatnya terukur. Pada 300 lahan pertanian Indonesia (median 2920 mm/th),
hanya tanaman yang siklusnya mendekati setahun yang lolos:

    singkong  (8-12 bln)  -> menang di 55.8% lahan
    kemiri    (tahunan)   -> menang di 42.5% lahan
    jagung    (3-4 bln)   -> menang di  0.1% lahan
    sorgum, kacang_tanah, kacang_hijau -> TIDAK PERNAH menang

Padahal sorgum, kacang hijau, kacang tanah, dan jagung justru ditanam luas
di Indonesia sebagai PALAWIJA di musim kemarau, setelah padi. Grobogan
menerima ~2000 mm/th dan merupakan sentra kacang hijau terbesar Jawa Tengah,
tetapi sistem lama menyatakan kacang hijau mustahil di sana.

Pendekatan
----------
Fitur lahan harus BEBAS-TANAMAN (satu vektor dipakai utk menilai 10 tanaman
sekaligus), jadi tidak bisa memakai "hujan selama musim tanam tanaman X".
Yang dipakai: penciri REZIM hujan setahun, lalu scorer memilih jendela yang
sesuai siklus tiap tanaman.

Fitur bebas-tanaman yang dihasilkan:
  rainfall_mm    - total setahun (tetap relevan utk tanaman tahunan spt kemiri)
  rain_wet3      - hujan pada 3 bulan berurutan TERBASAH
  rain_dry3      - hujan pada 3 bulan berurutan TERKERING
  bulan_basah    - jumlah bulan dgn hujan > 200 mm
  bulan_kering   - jumlah bulan dgn hujan < 100 mm

Ambang 200 mm dan 100 mm mengikuti klasifikasi agroklimat OLDEMAN, yang
memang disusun untuk Indonesia: bulan basah >200 mm, bulan lembab 100-200 mm,
bulan kering <100 mm.

Untuk scorer: best_window_rain(bulanan, n_bulan) memberi total hujan pada
jendela n bulan berurutan paling basah (melingkar melewati Desember-Januari),
yaitu perkiraan air yang diterima tanaman bila ditanam pada waktu terbaik.
"""

BULAN_BASAH_MM = 200      # ambang Oldeman
BULAN_KERING_MM = 100


def rain_windows(monthly, n_months):
    """Total hujan utk SETIAP kemungkinan waktu tanam.

    Mengembalikan 12 nilai: total hujan bila tanam dimulai pada Jan, Feb, ...,
    Des, masing-masing selama n_months bulan berurutan (melingkar Des->Jan).

    Ini inti perbaikannya. Petani memilih WAKTU TANAM, jadi pertanyaan yang
    benar bukan "berapa hujan setahun di sini" melainkan "adakah waktu tanam
    dalam setahun yang pasokan airnya cocok utk tanaman ini". Kacang hijau
    justru ditanam pada musim kemarau -- kelebihan air memicu penyakit -- jadi
    memakai jendela terbasah pun keliru. Yang benar: cari jendela yang paling
    COCOK dengan syarat tanamannya (lihat rule_based_scorer.score_crop).
    """
    if not monthly or n_months <= 0:
        return []
    n = min(n_months, 12)
    ext = list(monthly) + list(monthly)      # melingkar
    return [sum(ext[i:i + n]) for i in range(12)]


def best_window_rain(monthly, n_months):
    """Total hujan pada n_months berurutan paling basah (melingkar Des->Jan)."""
    w = rain_windows(monthly, n_months)
    return max(w) if w else None


def worst_window_rain(monthly, n_months):
    """Total hujan pada n_months berurutan paling kering (melingkar)."""
    if not monthly or n_months <= 0:
        return None
    n = min(n_months, 12)
    ext = list(monthly) + list(monthly)
    return min(sum(ext[i:i + n]) for i in range(12))


def derive(monthly):
    """Ubah 12 nilai hujan bulanan (mm/bulan) menjadi fitur lahan."""
    if monthly is None or len(monthly) != 12 or any(m is None for m in monthly):
        return None
    return {
        "rainfall_mm": round(sum(monthly)),
        "rain_wet3": round(best_window_rain(monthly, 3)),
        "rain_dry3": round(worst_window_rain(monthly, 3)),
        "bulan_basah": sum(1 for m in monthly if m > BULAN_BASAH_MM),
        "bulan_kering": sum(1 for m in monthly if m < BULAN_KERING_MM),
    }


def monthly_from_daily(dates, values):
    """Rerata hujan per bulan kalender dari deret harian multi-tahun.

    dates : list 'YYYY-MM-DD'
    values: list mm/hari (None diabaikan)
    Keluaran: 12 angka, mm/bulan, dirata-ratakan antar tahun.
    """
    total = [0.0] * 12
    tahun = [set() for _ in range(12)]
    for d, v in zip(dates, values):
        if v is None:
            continue
        bln = int(d[5:7]) - 1
        total[bln] += v
        tahun[bln].add(d[:4])
    out = []
    for i in range(12):
        n = len(tahun[i])
        out.append(total[i] / n if n else None)
    return None if any(x is None for x in out) else out
