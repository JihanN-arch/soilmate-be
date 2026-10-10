"""Simulasi pengapuran untuk NUSA-CROP.

Menjawab dua pertanyaan:
  1. Kalau tanah dikapur X ton/ha, pH-nya jadi berapa?
  2. Kalau ingin pH mencapai Y, butuh kapur berapa ton/ha?

    from ml_lib.pengapuran import simulasi
    simulasi(ph_awal=4.8, tekstur_kelas="clay loam", organic_carbon=14.0, target_ph=6.0)

Model: kurva jenuh
    BC      = K_BC x (BC_TEKSTUR[tekstur] + BC_PER_OC x C_organik_gkg)
    R       = PH_PLAFON - ph_awal
    ph_baru = ph_awal + R x (1 - exp(-D / (BC x R)))      D = dosis setara CaCO3 (t/ha)
Bentuknya monoton, tidak pernah melewati PH_PLAFON, dan punya invers tertutup
sehingga mode dosis dan mode target selalu konsisten.

Parameter dilatih oleh latih_pengapuran.py (leave-one-study-out pada sheet
`1c Pengapuran`); lihat LAPORAN_ML.md. Modul ini sengaja tidak membaca berkas
apa pun dan hanya memakai pustaka standar.
"""

import math

# --- Parameter model pH -------------------------------------------------------

# Daya sangga dasar per kelas tekstur, t CaCO3/ha per unit pH. Nilai awal dari
# brief (Baseline B). Data latih hanya punya tekstur di 1 studi, jadi urutan
# antarkelas TIDAK bisa di-fit dan tetap dari tabel ini; yang dilatih hanya K_BC.
BC_TEKSTUR = {
    "sand": 0.6, "loamy sand": 0.8, "sandy loam": 1.0, "loam": 1.4,
    "silt loam": 1.4, "silt": 1.3, "sandy clay loam": 1.6, "clay loam": 1.8,
    "silty clay loam": 1.8, "sandy clay": 1.9, "silty clay": 2.0, "clay": 2.2,
}
BC_PER_OC = 0.04          # tambahan daya sangga per g/kg C-organik (brief, Baseline B)
PH_PLAFON_AWAL = 7.8      # plafon Baseline B (pH tanah jenuh CaCO3 kira-kira 7,8-8,2)
PH_PLAFON = 7.8

# Pengali daya sangga hasil fit pada data 1c (latih_pengapuran.py, model C3:
# median dari k tiap studi, 30 baris dari 8 studi). Tanah di data itu kira-kira
# 2,6 kali lebih sulit dinaikkan pH-nya daripada tabel BC_TEKSTUR; antarstudi
# nilainya 0,6-9,4, jadi dosis hasil hitung bisa meleset jauh untuk satu lahan.
K_BC = 2.56

# C-organik di data latih 6-21 g/kg (uji laboratorium). SoilGrids 5-15 cm di
# titik kabupaten bermedian 53 g/kg, dan di Lamandau 189 g/kg padahal terukur
# 2-9 g/kg. Nilai di atas batas ini dipotong supaya C-organik dari SoilGrids
# tidak menggandakan dosis.
OC_MAKS_GKG = 25.0
TEKSTUR_DEFAULT = "loam"  # dipakai kalau tekstur tidak diisi (keputusan 1b.3 brief)
OC_DEFAULT_GKG = 11.6     # median C-organik studi di data latih, g/kg
# Dosis setara CaCO3 tertinggi di data latih yang bertanaman (t/ha). Hanya
# inkubasi laboratorium S09 yang lebih tinggi (3,8-7,7 t/ha hasil konversi).
DOSIS_LATIH_MAKS = 3.0

# --- Jenis kapur --------------------------------------------------------------

# Setara CaCO3 (CCE) per berat produk.
CCE = {
    # 4 sampel dolomit lokal, rata-rata 29,5% CaO dan 16,3% MgO (Santi & Goenadi
    # 2012, Menara Perkebunan 80(1), Tabel 1; sheet 3_Param Ekonomi Kapur P30-P31):
    # 29,5 x 1,785 + 16,3 x 2,483 = 93%. Teoretis murni 109%.
    "dolomit": 0.93,
    # Syarat kalsit pertanian CaCO3+MgCO3 minimal 85% (Dariah dkk. 2015, P34) dan
    # kapur program pengapuran Indonesia 85% CaCO3 (Amien 1991). NP terukur produk
    # belum ada di paket data, jadi dipakai batas bawah syarat mutu.
    "kalsit": 0.85,
    # Nilai awal brief; CaO murni 1,79. Tidak ada data mutu di paket data.
    "kapur_tohor": 1.70,
}

# --- Al-dd --------------------------------------------------------------------

# Al-dd (cmol(+)/kg) = FAKTOR_AL_TEKSTUR x AL_A x (AL_PH_NOL - pH)^AL_B, nol di
# atas AL_PH_NOL. Nilai awal dari brief; lihat LAPORAN_ML.md untuk hasil uji
# terhadap pasangan pH-Al-dd di sheet 1c dan 2a.
AL_A = 2.0
AL_B = 1.3
AL_PH_NOL = 5.5
# 0,4 (sand) sampai 1,5 (clay), mengikuti urutan BC_TEKSTUR (brief 1c).
FAKTOR_AL_TEKSTUR = {t: round(0.4 + 1.1 * (bc - 0.6) / 1.6, 2)
                     for t, bc in BC_TEKSTUR.items()}

# Aturan 1 x Al-dd (Maulana dkk. 2020): 1 cmol(+)/kg Al dinetralkan 0,5 g CaCO3
# per kg tanah. Dengan lapisan olah 20 cm dan bobot isi 1,2 g/cm3 (asumsi sheet
# Rumus_Bantu, 2,4 juta kg tanah/ha) = 1,2 t CaCO3/ha per cmol(+)/kg.
T_CACO3_PER_CMOL_AL = 1.2

# --- Lama efek ----------------------------------------------------------------

# (dosis setara CaCO3 t/ha, tahun). 0,5 t/ha bertahan sekitar 2 tahun dan
# 2 t/ha 5 tahun atau lebih (studi Ultisol kaolinitik, sheet 3_Param Ekonomi
# Kapur P20-P21). Sitiung (Amien 1991, sheet 3i): 0,32 t CaCO3/ha kembali ke
# Al awal dalam sekitar 3 tahun; 1,9 dan 5,5 t/ha masih menahan Al di 66% dan
# 49% nilai awal pada bulan ke-42. Tidak ada pengamatan di atas 5 tahun, jadi
# dibatasi 5.
_LAMA_EFEK = ((0.0, 0.0), (0.5, 2.0), (2.0, 5.0))

DOSIS_MAKS = 20.0


def _ph_dari_dosis(ph_awal, dosis_caco3, bc, plafon=None):
    plafon = PH_PLAFON if plafon is None else plafon
    r = plafon - ph_awal
    if r <= 0 or dosis_caco3 <= 0:
        return ph_awal
    return ph_awal + r * (1.0 - math.exp(-dosis_caco3 / (bc * r)))


def _dosis_dari_ph(ph_awal, target_ph, bc):
    r = PH_PLAFON - ph_awal
    if target_ph >= PH_PLAFON:
        return math.inf
    return -bc * r * math.log(1.0 - (target_ph - ph_awal) / r)


def _al_dari_ph(ph, tekstur):
    if ph >= AL_PH_NOL:
        return 0.0
    return FAKTOR_AL_TEKSTUR[tekstur] * AL_A * (AL_PH_NOL - ph) ** AL_B


def _lama_efek(dosis_caco3):
    for (d0, t0), (d1, t1) in zip(_LAMA_EFEK, _LAMA_EFEK[1:]):
        if dosis_caco3 <= d1:
            return t0 + (t1 - t0) * (dosis_caco3 - d0) / (d1 - d0)
    return _LAMA_EFEK[-1][1]


def _angka(nilai, nama, lo, hi):
    if isinstance(nilai, bool) or not isinstance(nilai, (int, float)):
        raise ValueError(f"{nama} harus berupa angka.")
    nilai = float(nilai)
    if math.isnan(nilai) or not (lo <= nilai <= hi):
        raise ValueError(f"{nama} harus di antara {lo:g} dan {hi:g}.")
    return nilai


def _slug(teks, nama):
    if not isinstance(teks, str):
        raise ValueError(f"{nama} tidak dikenali.")
    return " ".join(teks.strip().lower().replace("_", " ").split())


def _ton(x):
    return f"{x:.1f}".replace(".", ",")


def simulasi(ph_awal, tekstur_kelas, organic_carbon=None, al_dd=None,
             dosis_ton_ha=None, target_ph=None, jenis_kapur="dolomit"):
    if (dosis_ton_ha is None) == (target_ph is None):
        raise ValueError("Isi salah satu: dosis kapur atau target pH.")

    ph_awal = _angka(ph_awal, "pH tanah", 3.0, 10.0)
    if target_ph is not None:
        target_ph = _angka(target_ph, "Target pH", 4.0, 7.5)
        if target_ph <= ph_awal:
            raise ValueError("Target pH harus lebih tinggi dari pH tanah saat ini.")
    else:
        dosis_ton_ha = _angka(dosis_ton_ha, "Dosis kapur", 0.0, DOSIS_MAKS)

    tekstur_diasumsikan = tekstur_kelas is None
    tekstur = TEKSTUR_DEFAULT if tekstur_diasumsikan else _slug(tekstur_kelas, "Tekstur tanah")
    if tekstur not in BC_TEKSTUR:
        raise ValueError(f"Tekstur tanah '{tekstur_kelas}' tidak dikenali.")

    oc_diasumsikan = organic_carbon is None
    oc = OC_DEFAULT_GKG if oc_diasumsikan else _angka(organic_carbon, "C-organik", 0.0, 600.0)
    oc_dibatasi = oc > OC_MAKS_GKG
    oc = min(oc, OC_MAKS_GKG)

    jenis = _slug(jenis_kapur, "Jenis kapur").replace(" ", "_")
    if jenis not in CCE:
        raise ValueError(f"Jenis kapur '{jenis_kapur}' tidak dikenali. "
                         "Pilih dolomit, kalsit, atau kapur_tohor.")
    cce = CCE[jenis]

    al_terukur = al_dd is not None
    al_awal = (_angka(al_dd, "Al-dd", 0.0, 50.0) if al_terukur
               else _al_dari_ph(ph_awal, tekstur))

    bc = K_BC * (BC_TEKSTUR[tekstur] + BC_PER_OC * oc)

    if target_ph is not None:
        mode = "target_ph"
        dosis_caco3 = _dosis_dari_ph(ph_awal, target_ph, bc)
        if dosis_caco3 / cce > DOSIS_MAKS:
            raise ValueError(
                f"Target pH {target_ph:g} terlalu tinggi untuk tanah ini: butuh lebih "
                f"dari {DOSIS_MAKS:g} ton kapur per hektare. Pilih target yang lebih rendah.")
        ph_baru = target_ph
    else:
        mode = "dosis"
        dosis_caco3 = dosis_ton_ha * cce
        ph_baru = _ph_dari_dosis(ph_awal, dosis_caco3, bc)
    dosis_produk = dosis_caco3 / cce

    # Al-dd pada pH baru. Kalau Al-dd terukur, pertahankan nilainya sebagai
    # titik awal dan turunkan sebanding dengan kurva estimasi.
    al_est_awal = _al_dari_ph(ph_awal, tekstur)
    al_est_baru = _al_dari_ph(ph_baru, tekstur)
    if not al_terukur:
        al_baru = al_est_baru
    elif al_est_awal > 0:
        al_baru = al_awal * al_est_baru / al_est_awal
    else:
        al_baru = al_awal      # pH awal sudah di atas ambang Al; kurva tidak memberi arah
    penetral_al = al_awal * T_CACO3_PER_CMOL_AL / cce

    catatan = []
    if tekstur_diasumsikan:
        catatan.append("Jenis tanah (tekstur) tidak diisi, jadi dihitung untuk tanah "
                       "lempung. Tanah liat butuh kapur lebih banyak, tanah berpasir "
                       "lebih sedikit.")
    if oc_diasumsikan:
        catatan.append("Kandungan bahan organik tanah tidak diisi, jadi dipakai nilai "
                       "rata-rata.")
    if oc_dibatasi:
        catatan.append("Kandungan bahan organik yang diisi sangat tinggi, di luar tanah "
                       "yang ada di data percobaan kami, jadi dihitung dengan nilai batas. "
                       "Untuk tanah gambut, perkiraan ini tidak berlaku.")
    if mode == "dosis" and ph_awal >= 6.5:
        catatan.append("Tanah ini sudah tidak masam, jadi pengapuran kemungkinan tidak "
                       "diperlukan.")
    if ph_baru > 6.5:
        catatan.append("Di tanah masam Indonesia, pengapuran umumnya cukup sampai pH "
                       "5,5-6,5 untuk menetralkan aluminium. Lebih tinggi dari itu "
                       "menambah biaya dan jarang menambah hasil panen.")
    if dosis_produk > 3:
        catatan.append("Dosis di atas 3 ton per hektare sebaiknya dibagi menjadi beberapa "
                       "kali pemberian, dan cek dulu apakah biayanya sepadan.")
    if dosis_caco3 > DOSIS_LATIH_MAKS:
        catatan.append("Dosis ini lebih besar daripada yang ada di data percobaan kami, "
                       "jadi hasil perkiraannya kurang pasti.")
    if al_awal > 0:
        catatan.append("Untuk menetralkan aluminium saja, perkiraan kebutuhannya sekitar "
                       f"{_ton(penetral_al)} ton per hektare.")
    if not al_terukur:
        catatan.append("Kadar aluminium tanah diperkirakan dari pH, bukan hasil uji "
                       "laboratorium.")
    if jenis == "kapur_tohor":
        catatan.append("Kapur tohor bersifat panas dan bisa melukai kulit. Pakai sarung "
                       "tangan dan masker saat menebar.")
    if tekstur_diasumsikan or oc_diasumsikan or oc_dibatasi or not al_terukur:
        catatan.append("Ini perkiraan. Pastikan dengan uji tanah atau tanyakan ke "
                       "penyuluh sebelum membeli kapur.")

    return {
        "ph_baru": round(float(ph_baru), 2),
        "dosis_ton_ha": round(float(dosis_produk), 2),   # berat PRODUK, bukan setara CaCO3
        "catatan": catatan,
        "mode": mode,
        "metode": "kurva jenuh daya sangga (parametrik, dilatih dari uji pengapuran)",
        "jenis_kapur": jenis,
        "dosis_setara_caco3_ton_ha": round(float(dosis_caco3), 2),
        "al_dd_awal": round(float(al_awal), 2),
        "al_dd_baru": round(float(al_baru), 2),
        "al_dd_sumber": "terukur" if al_terukur else "estimasi dari pH",
        "dosis_penetral_al_ton_ha": round(float(penetral_al), 2),
        "estimasi_lama_efek_tahun": round(_lama_efek(dosis_caco3) * 2) / 2,
        "tekstur_dipakai": tekstur,
        "tekstur_diasumsikan": tekstur_diasumsikan,
        "organic_carbon_dipakai": round(float(oc), 1),
        "organic_carbon_diasumsikan": oc_diasumsikan,
        "organic_carbon_dibatasi": oc_dibatasi,
    }
