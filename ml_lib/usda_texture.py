"""
Klasifikasi kelas tekstur tanah USDA (12 kelas) — implementasi mandiri.

KENAPA TIDAK PAKAI LIBRARY `soiltexture`:
Library PyPI `soiltexture` berlisensi GPLv3 (lisensi copyleft kuat). Kalau
NUSA-CROP mendistribusikan kode yang meng-import library itu, seluruh proyek
ikut wajib GPLv3 dan LICENSE MIT kita jadi tidak sah. Modul ini menggantikannya
sehingga proyek tetap bisa MIT. Bonus: menghapus dependensi matplotlib yang
ditarik diam-diam oleh `soiltexture` (dipakai hanya untuk point-in-polygon).

DASAR ATURAN:
Batas ke-12 kelas di bawah ini adalah definisi resmi segitiga tekstur USDA
(Soil Survey Division Staff, 1993, *Soil Survey Manual*, USDA Handbook 18) —
terbitan pemerintah AS, domain publik. Aturannya ditulis sebagai pertidaksamaan
persen pasir/debu/liat, bentuk yang sama dipakai USDA-NRCS Soil Texture
Calculator, bukan sebagai poligon lalu uji point-in-polygon.

Bentuk pertidaksamaan ini justru lebih rapat daripada pendekatan poligon: titik
yang jatuh PERSIS di garis batas antar-kelas selalu dapat satu kelas pasti,
sedangkan uji poligon bisa menolaknya dan mengembalikan None. Untuk NUSA-CROP
itu penting, karena nilai tekstur dari SoilGrids sering mendarat di angka bulat
yang kebetulan tepat di garis batas (mis. liat = 27.0%).
"""

# Nama kelas ditulis huruf kecil tanpa spasi berlebih dan HARUS tetap sama
# persis: string ini dicocokkan dengan profil di seed.json dan tabel tekstur di
# rule_based_scorer/pengapuran, yang mengenali "sandy clay loam" tapi tidak
# "Sandy Clay Loam".
_CLASSES = (
    "sand", "loamy sand", "sandy loam", "loam", "silt loam", "silt",
    "sandy clay loam", "clay loam", "silty clay loam", "sandy clay",
    "silty clay", "clay",
)


def usda_texture_class(sand, silt, clay):
    """
    Kembalikan kelas tekstur USDA dari persen pasir, debu, dan liat.

    Ketiga nilai dinormalisasi dulu ke total 100% supaya input yang jumlahnya
    meleset sedikit (mis. 99.7 karena pembulatan SoilGrids) tetap terklasifikasi
    di titik yang benar, bukan tergeser ke kelas tetangga.

    Parameters
    ----------
    sand, silt, clay : float
        Persentase fraksi tanah. Skala relatif juga boleh (mis. g/kg), karena
        dinormalisasi.

    Returns
    -------
    str
        Satu dari 12 kelas USDA, mis. "sandy clay loam".
    """
    total = sand + silt + clay
    if total <= 0:
        raise ValueError(
            f"sand+silt+clay={total}; ketiga fraksi tidak boleh nol/negatif "
            f"semua (sand={sand}, silt={silt}, clay={clay})."
        )
    sand = sand / total * 100.0
    silt = silt / total * 100.0
    clay = clay / total * 100.0

    # Urutan cabang mengikuti urutan uji baku USDA: kelas berpasir diperiksa
    # lebih dulu lewat kombinasi (silt + k*clay), lalu kelas menengah, baru
    # kelas berliat. Urutan ini tidak boleh diacak — beberapa cabang di bawah
    # sengaja mengandalkan cabang di atasnya sudah menyaring lebih dulu.
    if silt + 1.5 * clay < 15:
        return "sand"
    if silt + 2 * clay < 30:
        return "loamy sand"
    # Mulai sini silt + 2*clay >= 30 dijamin, jadi tidak perlu diulang.
    if (7 <= clay < 20 and sand > 52) or (clay < 7 and silt < 50):
        return "sandy loam"
    if 7 <= clay < 27 and 28 <= silt < 50 and sand <= 52:
        return "loam"
    if (silt >= 50 and 12 <= clay < 27) or (50 <= silt < 80 and clay < 12):
        return "silt loam"
    if silt >= 80 and clay < 12:
        return "silt"
    if 20 <= clay < 35 and silt < 28 and sand > 45:
        return "sandy clay loam"
    if 27 <= clay < 40 and 20 < sand <= 45:
        return "clay loam"
    if 27 <= clay < 40 and sand <= 20:
        return "silty clay loam"
    if clay >= 35 and sand > 45:
        return "sandy clay"
    if clay >= 40 and silt >= 40:
        return "silty clay"
    if clay >= 40 and sand <= 45:
        return "clay"

    # Tidak boleh tercapai: setelah normalisasi, ke-12 cabang di atas menutupi
    # seluruh segitiga. Kalau tetap sampai sini berarti ada input aneh (NaN),
    # dan lebih baik gagal keras daripada mengembalikan None yang lalu jadi
    # kategori "unknown" diam-diam di OneHotEncoder.
    raise ValueError(
        f"tekstur tidak terklasifikasi untuk sand={sand:.2f} silt={silt:.2f} "
        f"clay={clay:.2f} (ada NaN?)"
    )
