import soiltexture


def usda_texture_class(sand, silt, clay):
    """
    Klasifikasi kelas tekstur USDA dari persentase pasir (sand), debu (silt),
    dan liat (clay). Mengembalikan salah satu dari 12 kelas USDA.

    Menggunakan library `soiltexture` (batas segitiga USDA tervalidasi) alih-alih
    implementasi batas manual, agar akurat termasuk pada titik-titik dekat batas
    antar-kelas yang rawan salah. Library hanya perlu sand% dan clay% (silt
    dihitung sebagai sisanya).
    """
    total = sand + silt + clay
    if total > 0:
        sand = sand / total * 100
        clay = clay / total * 100
    return soiltexture.getTexture(sand, clay, classification="USDA")


def parse_soilgrids_response(raw_json, depth="5-15cm"):
    """
    Baca respons MENTAH SoilGrids v2.0 (endpoint /properties/query) dan
    kembalikan nilai dlm satuan konvensional.

    PENTING: SoilGrids menyimpan nilai sbg INTEGER utk hemat ruang, jadi harus
    dibagi faktor konversi dulu. pH datang sbg 61 (bukan 6.1) dan sand/silt/clay
    sbg g/kg x10 (543, bukan 54.3%). Faktornya TIDAK di-hardcode di sini
    melainkan dibaca dari unit_measure.d_factor pada respons, supaya tetap benar
    kalau ISRIC mengubahnya.

    Input : dict hasil json.loads() dari
            rest.isric.org/soilgrids/v2.0/properties/query?...
    Output: {'ph': float, 'sand': %, 'silt': %, 'clay': %} (nilai None kalau
            piksel tsb tidak punya data, mis. di badan air)
    """
    out = {}
    for layer in raw_json["properties"]["layers"]:
        target = next((d for d in layer["depths"] if d["label"] == depth), None)
        if target is None:
            continue
        raw = target["values"]["mean"]
        factor = layer["unit_measure"]["d_factor"]
        key = "ph" if layer["name"] == "phh2o" else layer["name"]
        out[key] = None if raw is None else raw / factor
    return out


def adapt_soilgrids(soilgrids_json):
    """
    Ubah dict tanah yang SUDAH dikonversi ke satuan konvensional menjadi fitur
    siap-pakai untuk scorer/model NUSA-CROP.

    Input : {'soil': {'ph_tanah': 6.1, 'sand': {'value': 54.3}, ...}}
            CATATAN: ini BUKAN respons mentah SoilGrids. Kalau kamu memegang
            respons mentah dari API, lewatkan dulu ke parse_soilgrids_response().
    Output: {'ph': float, 'soil_texture': str, 'sand': %, 'silt': %, 'clay': %}
    """
    soil = soilgrids_json["soil"]
    sand = soil["sand"]["value"]
    silt = soil["silt"]["value"]
    clay = soil["clay"]["value"]
    ph = soil["ph_tanah"]

    # Gagal keras kalau nilainya kelihatan belum dikonversi. Tanpa penjagaan ini
    # pH 61 lolos diam-diam: semua tanaman kena skor pH 0 -> hard_fail -> semua
    # rekomendasi salah, tanpa satu pun pesan error.
    if ph is not None and not (2.0 <= ph <= 12.0):
        raise ValueError(
            f"ph={ph} di luar rentang pH yang mungkin (2-12). Nilai SoilGrids "
            f"tampaknya belum dibagi d_factor (pH disimpan sbg pH*10, mis. 61 "
            f"artinya 6.1). Pakai parse_soilgrids_response() lebih dulu."
        )
    total = sum(v for v in (sand, silt, clay) if v is not None)
    if total > 200:
        raise ValueError(
            f"sand+silt+clay={total:.0f}, jauh di atas 100%. Nilai tekstur "
            f"tampaknya masih dlm g/kg x10 dan belum dibagi d_factor. "
            f"Pakai parse_soilgrids_response() lebih dulu."
        )

    return {
        "ph": ph,
        "soil_texture": usda_texture_class(sand, silt, clay),
        "sand": sand, "silt": silt, "clay": clay,
    }


if __name__ == "__main__":
    sample = {'location': {'latitude': 50, 'longitude': 90}, 'depth': '0-5cm',
              'soil': {'ph_tanah': 7.4, 'nitrogen': {'value': 6.9, 'unit': 'g/kg'},
                       'soc': {'value': 38.3, 'unit': 'g/kg'},
                       'sand': {'value': 42.8, 'unit': '%'},
                       'silt': {'value': 32.7, 'unit': '%'},
                       'clay': {'value': 24.5, 'unit': '%'}}}
    result = adapt_soilgrids(sample)
    print("Input  : sand=42.8%, silt=32.7%, clay=24.5%, ph=7.4")
    print("Output :", result)
    print("\nUji klasifikasi USDA:")
    cases = [
        (42.8, 32.7, 24.5, "loam / clay loam?"),
        (80, 15, 5, "loamy sand / sand"),
        (60, 30, 10, "sandy loam"),
        (20, 60, 20, "silt loam"),
        (30, 30, 40, "clay"),
    ]
    for s, si, c, exp in cases:
        print(f"  sand={s} silt={si} clay={c} -> {usda_texture_class(s,si,c):18} (harusnya ~{exp})")