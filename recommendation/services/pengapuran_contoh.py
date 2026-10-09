"""Simulasi pengapuran CONTOH (mock) untuk pengembangan FE.

BUKAN hasil model. Hanya dipakai kalau:
  - ml_lib/pengapuran.py dari tim ML belum ada, DAN
  - env NUSACROP_PENGAPURAN_CONTOH=True.
Begitu ml_lib/pengapuran.py ada, modul asli selalu dipakai dan file ini
diabaikan, tanpa perubahan kode.

Kontraknya sama persis dengan ml_lib/pengapuran.py (lihat services/pengapuran.py).
Rumusnya sengaja sederhana supaya angkanya masuk akal untuk tampilan:
  dosis (ton/ha) = (target_pH - pH_awal) x faktor_tekstur x faktor_C-organik x faktor_jenis_kapur
"""

# ton kalsit per hektar untuk menaikkan pH 1 satuan (tanah makin liat makin besar)
FAKTOR_TEKSTUR = {
    "sand": 0.8, "loamy sand": 1.0, "sandy loam": 1.2, "loam": 1.5, "silt loam": 1.6,
    "silt": 1.6, "sandy clay loam": 1.7, "clay loam": 1.9, "silty clay loam": 2.0,
    "sandy clay": 2.0, "silty clay": 2.2, "clay": 2.3,
}
FAKTOR_TEKSTUR_DEFAULT = 1.6
# relatif terhadap kalsit (daya netralisasi lebih tinggi -> butuh lebih sedikit)
FAKTOR_JENIS = {"kalsit": 1.0, "dolomit": 0.92, "kapur_tohor": 0.56}
PH_MAKS = 7.0


def _faktor(tekstur_kelas, organic_carbon, jenis_kapur):
    f = FAKTOR_TEKSTUR.get(tekstur_kelas or "", FAKTOR_TEKSTUR_DEFAULT)
    if organic_carbon:  # bahan organik menahan perubahan pH
        f *= 1 + min(max(organic_carbon - 10, 0), 40) / 100
    return f * FAKTOR_JENIS.get(jenis_kapur, 1.0)


def simulasi(ph_awal, tekstur_kelas, organic_carbon=None, al_dd=None,
             dosis_ton_ha=None, target_ph=None, jenis_kapur="dolomit"):
    if (dosis_ton_ha is None) == (target_ph is None):
        raise ValueError("Isi salah satu: dosis kapur atau target pH.")
    if target_ph is not None and target_ph <= ph_awal:
        raise ValueError("Target pH harus lebih tinggi dari pH tanah saat ini.")
    if ph_awal >= PH_MAKS:
        raise ValueError("pH tanah sudah netral; pengapuran tidak diperlukan.")

    f = _faktor(tekstur_kelas, organic_carbon, jenis_kapur)
    catatan = ["ANGKA CONTOH untuk pengembangan tampilan, bukan hasil model."]
    if target_ph is not None:
        target = min(target_ph, PH_MAKS)
        dosis = (target - ph_awal) * f
        ph_baru = target
    else:
        dosis = dosis_ton_ha
        ph_baru = min(ph_awal + dosis_ton_ha / f, PH_MAKS)
    if tekstur_kelas is None:
        catatan.append("Tekstur tidak diisi; dipakai asumsi tanah lempung.")

    return {
        "ph_baru": round(ph_baru, 2),
        "dosis_ton_ha": round(dosis, 2),
        "catatan": catatan,
        "metode": "contoh",
    }
