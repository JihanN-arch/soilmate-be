import json
import os

from ml_lib.climate_features import rain_windows

# seed.json ikut di dalam paket, jadi profil tanaman selalu ketemu tanpa
# bergantung pada direktori kerja pemanggil.
SEED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed.json")

WEIGHTS = {
    "ph": 0.25,
    "rainfall": 0.28,
    "temp": 0.25,
    "elevation": 0.10,
    "texture": 0.12,
}


def _range_score(value, lo, hi, opt_lo, opt_hi):
    if value is None or lo is None or hi is None:
        return 0.5
    if value < lo or value > hi:
        return 0.0
    if opt_lo is None or opt_hi is None:
        # Literatur tidak menyebut rentang optimal utk parameter ini. Itu berarti
        # sumbernya tidak mempersempit, BUKAN bahwa tanamannya biasa-biasa saja
        # di seluruh rentang toleransinya.
        #
        # Versi lama mengembalikan 0.65 mati di sini. Akibatnya sistematis:
        # 5 dari 10 tanaman (singkong, kemiri, kacang tanah, kacang hijau,
        # kacang panjang) tidak punya elevasi optimal di seed.json, jadi skor
        # elevasinya MENTOK 0.65, sementara 5 lainnya bisa mencapai 1.00.
        # Pada 496.079 lahan uji, kacang tanah dan kacang hijau akibatnya
        # TIDAK PERNAH menang sekali pun -- kalah bukan karena tidak cocok,
        # melainkan karena data literaturnya tidak selengkap tanaman lain.
        #
        # Perlakuan yang benar: literatur menyatakan tanaman MENOLERIR seluruh
        # rentang ini, jadi jangan menghukum posisi di dalamnya. Beri skor
        # tinggi merata.
        #
        # (Percobaan sebelumnya menganggap 50% bagian tengah rentang sebagai
        # setara-optimal. Itu justru lebih buruk: rentang elevasi kacang hijau
        # 0-1800 m membuat "optimal" jadi 450-1350 m, padahal lahan pertanian
        # Indonesia bermedian 124 mdpl -- jadi hampir semua lahan malah kena
        # penalti. Ketiadaan data optimal tidak boleh ditafsirkan sebagai
        # "optimalnya di tengah".)
        #
        # Sedikit di bawah 1.0 supaya tanaman yang PUNYA rentang optimal dan
        # sedang berada di dalamnya tetap unggul tipis -- itu informasi nyata.
        return 0.90

    if opt_lo <= value <= opt_hi:
        mid = (opt_lo + opt_hi) / 2
        half = (opt_hi - opt_lo) / 2
        if half <= 0:
            return 1.0
        dist = abs(value - mid) / half        
        return 1.0 - 0.15 * (dist ** 2)       

    if value < opt_lo:
        frac = (value - lo) / (opt_lo - lo) if opt_lo > lo else 1.0
    else:
        frac = (hi - value) / (hi - opt_hi) if hi > opt_hi else 1.0
    return 0.15 + 0.70 * frac

_USDA_CENTROIDS = {
    "sand":            (92, 4),
    "loamy sand":      (82, 7),
    "sandy loam":      (63, 11),
    "loam":            (42, 18),
    "silt loam":       (21, 14),
    "silt":            (7, 6),
    "sandy clay loam": (58, 28),
    "clay loam":       (33, 34),
    "silty clay loam": (10, 34),
    "sandy clay":      (52, 42),
    "silty clay":      (7, 47),
    "clay":            (22, 58),
}
_MAX_TEX_DIST = 111.0


def _texture_distance(a, b):
    if a == b:
        return 0.0
    ca, cb = _USDA_CENTROIDS.get(a), _USDA_CENTROIDS.get(b)
    if ca is None or cb is None:
        return _MAX_TEX_DIST  # tak dikenal -> anggap jauh
    return ((ca[0]-cb[0])**2 + (ca[1]-cb[1])**2) ** 0.5


def _texture_score(texture, optimal_list, tolerable_list):
    opt = optimal_list or []
    tol = tolerable_list or []

    if opt:
        d_opt = min(_texture_distance(texture, t) for t in opt)
    else:
        d_opt = _MAX_TEX_DIST
    score_opt = max(0.0, 1.0 - d_opt / 40.0)
    if tol:
        d_tol = min(_texture_distance(texture, t) for t in tol)
        score_tol = max(0.0, 0.6 - d_tol / 80.0)
    else:
        score_tol = 0.0
    return max(score_opt, score_tol, 0.15)


def _drought_adjustment(land, profile):
    """Penalti utk tanaman tak tahan kering di lahan bermusim kemarau panjang.

    Dulu dipicu oleh curah hujan tahunan < 700 mm. Setelah land_pool memakai
    lahan pertanian nyata (median 2920 mm/th), ambang itu praktis tidak pernah
    tercapai sehingga drought_tolerance jadi tidak terpakai sama sekali.
    Sekarang dipicu oleh jumlah BULAN KERING (< 100 mm, ambang Oldeman), yang
    memang ukuran cekaman kekeringan yang relevan di iklim monsun: Indonesia
    bisa basah setahun penuh totalnya tetapi punya kemarau 5 bulan.
    """
    bulan_kering = land.get("bulan_kering")
    if bulan_kering is None:
        annual = land.get("rainfall_mm")
        if annual is None or annual >= 700:
            return 1.0
    elif bulan_kering < 5:            # Oldeman: kemarau panjang mulai ~5 bulan
        return 1.0
    drought = (profile.get("drought_tolerance") or "").lower()
    return {"tinggi": 1.0, "sedang": 0.80, "rendah": 0.55}.get(drought, 0.75)


BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
         "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


def rain_for_crop(land, profile, mulai=None):
    """Pilih WAKTU TANAM terbaik, lalu kembalikan (hujan_musim, skor, bulan_mulai).

    rainfall_min/max di seed.json adalah kebutuhan air satu musim tanam
    (mis. sorgum 350-1500 mm utk siklus ~4 bulan). Membandingkannya dengan
    curah hujan setahun (median lahan Indonesia 2920 mm) menolak hampir semua
    palawija secara keliru -- padahal justru itu yang ditanam petani, sebagai
    palawija musim kemarau setelah padi.

    Pertanyaan yang benar: "adakah waktu tanam dalam setahun yang pasokan
    airnya cocok untuk tanaman ini?" Jadi semua 12 kemungkinan bulan mulai
    dievaluasi, lalu diambil yang skornya tertinggi. Ini juga menangani
    tanaman yang justru menghindari hujan berlebih (kacang hijau) -- memakai
    jendela terbasah akan salah untuk mereka.

    Untuk tanaman tahunan (kemiri, cycle_months=12) semua jendela sama dengan
    total setahun, jadi perilakunya tidak berubah.
    """
    cycle = profile.get("cycle_months") or 12
    lo, hi = profile["rainfall_min"], profile["rainfall_max"]
    opt_lo = profile.get("rainfall_optimal_min")
    opt_hi = profile.get("rainfall_optimal_max")

    monthly = land.get("monthly_rain")
    if monthly:
        w = rain_windows(monthly, cycle)
        if mulai is not None:
            # Waktu tanam dikunci (petani mau tanam bulan ini), jadi jangan
            # cari jendela terbaik -- pakai jendela bulan itu apa adanya.
            total = w[mulai % 12]
            return (total, _range_score(total, lo, hi, opt_lo, opt_hi), mulai % 12)
        best = None
        for start, total in enumerate(w):
            s = _range_score(total, lo, hi, opt_lo, opt_hi)
            if best is None or s > best[1]:
                best = (total, s, start)
        return best

    # Cadangan kalau hujan bulanan tidak tersedia. Kurang akurat, jadi
    # sedapat mungkin sediakan monthly_rain (12 nilai mm/bulan).
    annual = land.get("rainfall_mm")
    if annual is None:
        return (None, 0.5, None)
    if cycle >= 12:
        approx = annual
    else:
        wet3 = land.get("rain_wet3")
        approx = (wet3 * (cycle / 3.0) ** 0.75 if wet3 is not None
                  else annual * cycle / 12.0)
    return (approx, _range_score(approx, lo, hi, opt_lo, opt_hi), None)


def score_crop(land, profile, mulai=None):
    s_ph = _range_score(land.get("ph"),
                        profile["ph_min"], profile["ph_max"],
                        profile.get("ph_optimal_min"), profile.get("ph_optimal_max"))
    musim_mm, s_rain, bulan_mulai = rain_for_crop(land, profile, mulai)
    s_temp = _range_score(land.get("temp_c"),
                        profile["temp_min"], profile["temp_max"],
                        profile.get("temp_optimal_min"), profile.get("temp_optimal_max"))
    s_elev = _range_score(land.get("elevation_m"),
                        profile.get("elevation_min"), profile.get("elevation_max"),
                        profile.get("elevation_optimal_min"), profile.get("elevation_optimal_max"))
    s_tex = _texture_score(land.get("soil_texture"),
                        profile.get("optimal_soil_texture"), profile.get("tolerable_soil_texture"))

    key_scores = [s_ph, s_rain, s_temp]
    hard_fail = any(s == 0.0 for s in key_scores)

    total = (WEIGHTS["ph"] * s_ph +
             WEIGHTS["rainfall"] * s_rain +
             WEIGHTS["temp"] * s_temp +
             WEIGHTS["elevation"] * s_elev +
             WEIGHTS["texture"] * s_tex)

    score = total * 100
    if hard_fail:
        score *= 0.3
    score *= _drought_adjustment(land, profile)

    return round(min(score, 100.0), 2), {
        "ph": round(s_ph, 2), "rainfall": round(s_rain, 2),
        "temp": round(s_temp, 2), "elevation": round(s_elev, 2),
        "texture": round(s_tex, 2),
        # utk penjelasan ke pengguna: kapan sebaiknya tanam dan berapa air
        # yang diterima selama musim tanam itu
        "musim_tanam_mm": None if musim_mm is None else round(musim_mm),
        "mulai_tanam": None if bulan_mulai is None else BULAN[bulan_mulai],
    }


def score_all_crops(land, profiles, mulai=None):
    """Nilai semua tanaman utk satu lahan.

    mulai=None  -> cari waktu tanam terbaik sepanjang tahun (rekomendasi
                   berdasarkan kondisi lahan saja, tanpa batasan waktu).
    mulai=0..11 -> kunci waktu tanam pada bulan itu (rekomendasi "kalau
                   ditanam sekarang"). Indeks 0 = Januari.
    """
    results = []
    for p in profiles:
        score, breakdown = score_crop(land, p, mulai)
        results.append({"crop_code": p["crop_code"], "score": score, "breakdown": breakdown})
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def load_profiles(path=SEED_PATH):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [d["fields"] for d in data if d["model"] == "crops.cropprofile"]


if __name__ == "__main__":
    # contoh cara pakai
    profiles = load_profiles()
    land = {"ph": 4.8, "rainfall_mm": 2200, "temp_c": 27.0,
            "elevation_m": 80, "ndvi": 0.55, "soil_texture": "clay loam"}
    print("Uji Lampung (harusnya singkong/ubi_jalar tinggi):")
    for r in score_all_crops(land, profiles)[:5]:
        print(f"  {r['crop_code']:16} skor={r['score']:.1f}  {r['breakdown']}")