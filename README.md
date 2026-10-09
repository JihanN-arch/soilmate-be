# NUSA-CROP Backend

Django + DRF. Dikembangkan oleh Burhan Lovers. Lisensi MIT (lihat `LICENSE`).

## Menjalankan lokal

```bash
pip install -r requirements.txt
export DATABASE_URL=sqlite:///db.sqlite3 DJANGO_SECRET_KEY=dev DJANGO_DEBUG=True DJANGO_ALLOWED_HOSTS=*
python manage.py migrate
python manage.py seed_crop
python manage.py test recommendation      # 45 tes, semua API eksternal di-mock
python manage.py runserver
```

## Deploy (Railway)

1. `python manage.py migrate` lalu `python manage.py seed_crop` (mengisi produktivitas numerik untuk lapisan ekonomi; field ekonomi yang sudah diisi tidak ditimpa).
2. **Antrian job**
   - Tanpa Redis: tidak perlu apa-apa, job jalan di thread proses web. Cukup untuk demo, tapi job yang sedang jalan hilang kalau server restart (akan ditandai gagal).
   - Dengan Redis: tambah plugin Redis, set `REDIS_URL`, lalu buat service kedua dari repo yang sama dengan start command `celery -A nusacrop_backend worker -l info --concurrency 2`.
3. **Cron** (Railway Cron, harian): `python manage.py update_monitoring`.
4. **Precompute wilayah pilot** (opsional, jalankan sekali): lihat bagian Perintah.

**Domain .id:** set `DJANGO_ALLOWED_HOSTS` (tambah `api.<domain>.id`), `CORS_EXTRA_ORIGINS` (domain FE .id), `CSRF_TRUSTED_ORIGINS` (`https://api.<domain>.id`, untuk login admin), dan `NUSACROP_SITE_URL`.

Env baru (opsional): `REDIS_URL`, `HARGA_KAPUR_PER_KG`, `CORS_EXTRA_ORIGINS`, `CORS_ORIGIN_REGEX`, `THROTTLE_USABILITY` (default `600/min`), `THROTTLE_ANON` (default `120/min`), `THROTTLE_ANALISIS` (default `10/min`).

## Endpoint

Semua di bawah `/api/`. `anonymous_id` dikirim di body (POST) atau query (GET/PATCH/DELETE).

### Rekomendasi

| Method | Path | Keterangan |
|---|---|---|
| POST | `recommend/` | Sinkron, kompatibel dengan FE lama |
| POST | `analisis/` | Asinkron, balas `202 {job_id}` |
| GET | `analisis/<job_id>/?anonymous_id=` | Status + progres per sumber + hasil |
| GET | `rekomendasi/<id>/detail/?anonymous_id=` | Detail tanaman + ekonomi + tren harga |
| POST | `simulasi/kapur/` | Simulasi pengapuran (lihat bawah) |

Body `recommend/` dan `analisis/`:

```json
{
  "anonymous_id": "abc", "lat": -6.95, "lon": 110.9, "nama_lokasi": "Sawah Pak Budi",
  "bulan_tanam": 10,
  "luas_lahan_m2": 2500,
  "uji_tanah": {
    "ph": 5.8,
    "tekstur_kelas": "lempung berliat",
    "sand": null, "silt": null, "clay": null,
    "c_organik_persen": 1.4, "nitrogen_persen": null,
    "metode": "putk", "tanggal_uji": "2026-10-01"
  }
}
```

- `bulan_tanam` (1-12, opsional) menggantikan `musim_target`. Kalau kosong, dipakai bulan berjalan, jadi `rekomendasi_bulan_tanam` selalu terisi (sama dengan `tanam_sekarang` di `recommend_dua()`). `musim_target` lama masih diterima (hujan = Nov, kemarau = Mei).
- `luas_lahan_m2` opsional. FE yang mengonversi dari ha/are/bata/tumbak. Dipakai untuk `ekonomi.estimasi_*_lahan` dan kebutuhan kapur total.
- `uji_tanah` opsional. Isi minimal pH **atau** tekstur. Tekstur boleh kelas USDA (`clay loam`) atau Indonesia (`lempung berliat`), atau sand/silt/clay (%) ketiganya. Kalau pH dan tekstur diisi, SoilGrids tidak dipanggil.

Status `analisis/<job_id>/`: `antri` → `berjalan` → `selesai` | `perlu_input` | `gagal`.
`progres` per sumber: `menunggu`, `berjalan`, `selesai`, `cadangan` (pakai cache/tetangga), `gagal`.

Respons sukses (field baru ditandai ★, field lama tetap ada):

```jsonc
{
  "status": "success",
  "recommendation": {
    "riwayat_id": 12,                                   // ★
    "kondisi_lahan": {
      "ph_tanah": 5.5, "tekstur_kelas": "clay loam", "curah_hujan": 2198, "suhu": 27.3,
      "elevasi": 31, "ndvi": 0.61, "...": "...",
      "kemiringan": 2.1,                                // ★ derajat
      "ph_rentang": [5.0, 6.1],                         // ★ Q5-Q95 SoilGrids (null kalau uji tanah)
      "sumber_data": {"ph": "uji_tanah", "tekstur": "api", "iklim": "cache", "elevasi": "api", "...": "..."}, // ★
      "kualitas_data": {"skor": 0.86, "label": "Tinggi"},  // ★
      "catatan_data": ["..."]                           // ★ tampilkan sebagai info/peringatan
    },
    "rekomendasi": [{
      "id": "kemiri", "nama": "Kemiri", "skor_kesesuaian": 0.92,
      "tingkat_kepercayaan": "Sedang", "alasan_rekomendasi": ["..."], "rekomendasi_id": 55,
      "faktor_pembatas": ["..."],                       // ★ kalimat negatif
      "mulai_tanam": "Jan",                             // ★ null untuk tanaman tahunan
      "musim_tanam_mm": 2198,                           // ★
      "rincian_skor": {"ph": 0.85, "rainfall": 0.98, "temp": 0.91, "elevation": 0.9, "texture": 1.0}, // ★
      "skor_per_bulan": [0.82, 0.8, "...", 0.83],       // ★ skor kalau mulai tanam Jan..Des (null untuk tanaman tahunan)
      "sumber_skor": "aturan",                          // ★ "hybrid" kalau model ML mengirim skor_akhir
      "detail_kepercayaan": {"skor": 0.8, "kualitas_data": 0.8, "ml_setuju": true, "peringkat_ml": 1}, // ★
      "ekonomi": {"tersedia": false, "estimasi_keuntungan_per_ha": null, "...": "..."} // ★
    }],
    "rekomendasi_bulan_tanam": {"bulan": "Okt", "daftar": ["...format sama..."]} // ★ bulan pilihan pengguna, atau bulan berjalan
  }
}
```

Nilai `sumber_data`: `uji_tanah`, `api`, `cache`, `cache_kedaluwarsa`, `api_sekitar` (titik ~280 m di sekitar), `tetangga` (sel cache terdekat), `open_meteo_dem`, `null` (tidak tersedia).

Error (semua endpoint): `{"status": "...", "pesan": "kalimat bahasa Indonesia"}`. Validasi menambah `detail` per field.
- `400` validasi input.
- `422 {"status": "perlu_input", "butuh_input": ["ph", "tekstur_kelas"]}` data tanah tidak tersedia dari sumber mana pun. FE sebaiknya membuka form uji tanah.
- `503 {"status": "error"}` iklim/elevasi tidak tersedia sama sekali.
- `429` terlalu banyak request.

### Simulasi pengapuran

Dua bentuk body (isi salah satu dari `dosis_ton_ha` atau `target_ph`):
1. Dari analisis: `{anonymous_id, riwayat_id, target_ph, jenis_kapur?, luas_lahan_m2?}`. Kondisi lahan diambil dari riwayat.
2. Isi sendiri: `{anonymous_id, uji_tanah: {ph, tekstur_kelas?, c_organik_persen?}, lat?, lon?, luas_lahan_m2?, target_ph, jenis_kapur?}`. Dengan lat/lon: iklim & elevasi dari cache/API lalu skor ulang. Tanpa lat/lon: hanya dosis & pH baru (`perubahan_skor` dan `rekomendasi_baru` kosong).

Respons: `ph_awal`, `ph_baru`, `kebutuhan_kapur {dosis_ton_ha, luas_lahan_m2, total_kg, harga_per_kg, perkiraan_biaya}`, `perubahan_skor` `[{id, crop_slug, nama, sebelum, sesudah, selisih}]`, `rekomendasi_baru` (format sama dengan rekomendasi), `detail_ml`, `catatan`.

- `501 belum_tersedia` selama tim ML belum membuat `ml_lib/pengapuran.py` (template: `ml_lib/pengapuran.py.contoh`, kontrak: `recommendation/services/pengapuran.py`).
- **Mode contoh (mock):** set env `NUSACROP_PENGAPURAN_CONTOH=True` untuk memakai angka contoh selama modul ML belum ada. Respons membawa `mode_contoh: true` dan catatan "ANGKA CONTOH"; FE wajib menampilkan labelnya. Begitu `ml_lib/pengapuran.py` ada, modul asli otomatis dipakai (`mode_contoh: false`) tanpa ubah kode. **Matikan sebelum demo ke juri** kalau modul asli belum ada.
- `409` riwayat lama (dibuat sebelum fitur ini) tidak menyimpan hujan bulanan/tekstur; minta pengguna analisis ulang.
- `perkiraan_biaya` hanya terisi kalau env `HARGA_KAPUR_PER_KG` di-set.

### Cuaca & ekonomi

| Method | Path | Keterangan |
|---|---|---|
| GET | `cuaca/prakiraan/?lat=&lon=` | 14 hari + `saran` (hujan lebat, kering, panas). Cache 3 jam |
| GET | `ekonomi/<slug>/` | Estimasi + `tren_harga` 180 hari |

### Monitoring pasca-tanam

| Method | Path | Keterangan |
|---|---|---|
| POST | `lahan/` | "Saya menanam ini": `{anonymous_id, rekomendasi_id, tanggal_tanam, luas_lahan_m2?}` (atau `crop`, `lat`, `lon`). Langsung memicu penarikan NDVI. 409 `{lahan_id}` kalau rekomendasi itu sudah punya lahan aktif |
| GET | `lahan/?anonymous_id=&status=aktif` | Daftar lahan |
| GET/PATCH/DELETE | `lahan/<id>/?anonymous_id=` | Detail + `observasi` NDVI + `cuaca`. PATCH misalnya `{"status": "panen"}` |
| POST | `lahan/<id>/pantau/` | Paksa perbarui. < 6 jam: 429 dengan `pesan` jam berikutnya |

`kesehatan`: `belum_cukup_data`, `baik`, `perlu_dicek`. `peringatan`: list `{jenis, tingkat, pesan}` dengan jenis `penurunan_tajam`, `pertumbuhan_lambat`, `data_tertunda`.

### Feedback & usability

| Method | Path | Keterangan |
|---|---|---|
| POST | `feedback/` | `{anonymous_id, jenis: rekomendasi/hasil_panen/aplikasi, rekomendasi_id?, lahan_id?, ditanam?, hasil?: baik/sedang/buruk/gagal, hasil_panen_kg?, luas_lahan_m2?, rating?: 1-5, komentar?}` |
| POST | `usability/log/` | Satu event atau list: `{anonymous_id, sesi_id, event, tugas, peserta, mode_tes, halaman, waktu, data}`. Throttle sendiri 600/menit |

### Riwayat

| Method | Path | Keterangan |
|---|---|---|
| GET | `riwayat/?anonymous_id=` | List (paginasi). Item: `riwayat_id, nama_lokasi, bulan_tanam, luas_lahan_m2, kualitas_data, rekomendasi[{rekomendasi_id, crop_slug, nama, ...}], lahan_aktif[{lahan_id, crop_slug, rekomendasi_id}]` |
| GET | `riwayat/<id>/detail/?anonymous_id=` | Bentuk sama dengan objek `recommendation` hasil analisis (+ meta lokasi). Riwayat lama: field baru null |
| DELETE | `riwayat/<id>/?anonymous_id=` | Hapus |

## Perintah

```bash
python manage.py precompute_statis --bbox MIN_LON MIN_LAT MAX_LON MAX_LAT --step 0.02 [--sumber tanah iklim satelit] [--dry-run]
python manage.py cek_sumber [--lat -7.05 --lon 110.92]   # diagnosis: tiap API berhasil/gagal + berapa detik
python manage.py update_monitoring          # cron harian
python manage.py muat_data_ekonomi            # muat data/harga_produsen_bps.csv & data/biaya_produksi_bps.csv (aman diulang)
python manage.py import_harga harga.csv --sumber "Panel Harga Bapanas"
python manage.py rekap_usability --sejak 2026-10-08 --csv rekap.csv   # per tugas & per peserta, hanya mode_tes
```

Format CSV harga: `crop_slug,tanggal,harga_per_kg,tingkat,wilayah_kode,wilayah_nama,sumber`.
Biaya produksi dan produktivitas diisi lewat Django admin (`/admin/`, model Crop).

## Catatan desain

- **Data tanah:** SoilGrids 2.0 diambil lewat Google Earth Engine (katalog ISRIC, cepat), dengan REST SoilGrids sebagai cadangan. Lewat GEE, `ph_rentang` bernilai null.
- **Tidak ada lagi mock data.** Kalau API gagal: cache kedaluwarsa → sel tetangga → error yang jelas. Asal setiap nilai ada di `sumber_data`.
- **Input model mengikuti training** (`ml_lib/predict.py`): SoilGrids 5-15 cm, iklim rata-rata 2022-2024.
- **Satu sumber syarat tumbuh:** skor dan alasan sama-sama membaca `ml_lib/seed.json`. `syarat_tumbuh` di tabel Crop hanya untuk tampilan.
- **Tingkat kepercayaan** = kualitas data, dikoreksi kesepakatan model ML (lihat `utils/confidence.py`). Aturan ini usulan dan perlu disepakati tim ML.
- **NDVI belum dikirim ke model** karena NDVI di data training masih sintetik.
