# Data ekonomi

Dimuat ke database dengan `python manage.py muat_data_ekonomi` (aman diulang).

## harga_produsen_bps.csv
Harga produsen (harga yang diterima petani) bulanan, Rp/kg, nasional (`wilayah_kode` 00) dan 34 provinsi,
tahun 2020, 2021, dan 2024, untuk 9 tanaman (tanpa sorgum).

- Sumber: BPS, *Statistik Harga Produsen Pertanian Subsektor Tanaman Pangan, Hortikultura, dan Tanaman
  Perkebunan Rakyat* (edisi 2020, 2021, 2024). Angka sumber dalam Rp/100 kg, dibagi 100.
- Disusun tim dari publikasi BPS (akses 6 Okt 2026). Baris `DIKOREKSI` = salah cetak di sumber yang
  diperbaiki (lihat kolom `catatan`). Tanda "-" di sumber tidak dibuat barisnya.
- Bulanan 2022–2023 belum ada. Rata-rata nasional 2020–2021 sama dengan tabel tahunan Kementan
  (Statistik Harga Komoditas Pertanian 2024), jadi konsisten.
- Bentuk produk tidak selalu dinyatakan di judul tabel BPS (kecuali jagung: pipilan). Pastikan
  produktivitas di tabel Crop memakai bentuk yang sama.

## biaya_produksi_bps.csv
Total biaya produksi per hektar per musim tanam, rata-rata nasional.

- Sumber: BPS, *Hasil Survei Struktur Ongkos Usaha Tanaman Palawija 2017 (SOUT2017-PW)*, Tabel 23.
- Tersedia: jagung, kacang tanah, kacang hijau, singkong (ubi kayu), ubi jalar (angka termasuk Papua).
- Belum ada: cabai rawit, terong, kacang panjang, sorgum, kemiri.
- Data tahun 2017, sedangkan harga terbaru 2024, sehingga keuntungan cenderung terlalu tinggi
  (biaya sekarang kemungkinan lebih besar). BE menampilkan peringatan ini di `catatan`.

## harga_acuan.csv
Harga dari sumber selain BPS. Kalau `ganti_data_bps` = `ya`, seluruh data BPS tanaman itu tidak dipakai.

- **Singkong**: Rp1.350/kg, harga pembelian singkong oleh industri tepung yang ditetapkan Mentan
  (berlaku 31 Jan 2025). Harga BPS "ketela pohon" (~Rp4.900/kg pada 2024) kemungkinan untuk singkong
  konsumsi di pasar perdesaan, sehingga keuntungan singkong menjadi tidak realistis (84–109 juta/ha).
  Laporan yang sama menyebut harga di tingkat petani bisa di bawah Rp1.000/kg.
