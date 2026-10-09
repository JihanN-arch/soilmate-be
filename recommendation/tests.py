"""Tes backend. Semua API eksternal di-mock; tidak ada request jaringan.

    python manage.py test recommendation
"""
from datetime import date, timedelta
from unittest.mock import patch

from django.core.cache import cache as django_cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .management.commands.rekap_usability import skor_sus
from .management.commands.seed_crop import parse_produktivitas
from .models import Crop, DataCache, HargaKomoditas, ObservasiNdvi, RiwayatPencarian, RiwayatRekomendasi
from .services import cache, ekonomi
from .services.errors import SumberDataGagal
from .services.monitoring import analisis_tren

LAT, LON = -6.95, 110.9   # sekitar Grobogan

TANAH = {"ph": 5.5, "sand": 30.0, "silt": 35.0, "clay": 35.0, "nitrogen": 1.5,
         "organic_carbon": 14.0, "ph_q05": 5.0, "ph_q95": 6.1, "tekstur_kelas": "clay loam"}
IKLIM = {"curah_hujan_bulanan": [287, 266, 311, 218, 118, 98, 45, 31, 76, 152, 311, 285],
         "curah_hujan_tahunan": 2198, "suhu_rata_rata": 27.3, "et0_tahunan": 1500,
         "elevasi_m": 35, "periode": "2022-01-01..2024-12-31"}
SATELIT = {"ndvi": 0.61, "elevasi_m": 31, "kemiringan_derajat": 2.1, "radius_m": 100}

P_TANAH = "recommendation.services.apis.soilgrids.fetch_tanah"
P_IKLIM = "recommendation.services.apis.openmeteo.fetch_iklim"
P_SAT = "recommendation.services.apis.gee.fetch_satelit"
GAGAL = SumberDataGagal("down")


@override_settings(NUSACROP_PARALEL=False, NUSACROP_JOB_SINKRON=True)
class DasarTes(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_crop", stdout=open("/dev/null", "w"))

    def setUp(self):
        django_cache.clear()  # reset throttle
        self.api = APIClient()

    def body(self, **extra):
        return {"lat": LAT, "lon": LON, "nama_lokasi": "Lahan Uji", "anonymous_id": "anon-1", **extra}


class RekomendasiTes(DasarTes):
    @patch(P_SAT, return_value=SATELIT)
    @patch(P_IKLIM, return_value=IKLIM)
    @patch(P_TANAH, return_value=dict(TANAH))
    def test_alur_normal(self, *_):
        r = self.api.post("/api/recommend/", self.body(bulan_tanam=10), format="json")
        self.assertEqual(r.status_code, 200, r.content)
        rek = r.json()["recommendation"]
        item = rek["rekomendasi"][0]
        for k in ("id", "skor_kesesuaian", "tingkat_kepercayaan", "alasan_rekomendasi",
                  "mulai_tanam", "faktor_pembatas", "rincian_skor", "ekonomi", "rekomendasi_id"):
            self.assertIn(k, item)
        self.assertEqual(rek["rekomendasi_bulan_tanam"]["bulan"], "Okt")
        self.assertEqual(rek["kondisi_lahan"]["sumber_data"]["ph"], "api")
        self.assertEqual(rek["kondisi_lahan"]["kualitas_data"]["label"], "Sedang")
        self.assertEqual(RiwayatRekomendasi.objects.filter(daftar="utama").count(), 5)
        self.assertEqual(DataCache.objects.count(), 3)

    @patch(P_SAT, return_value=SATELIT)
    @patch(P_IKLIM, return_value=IKLIM)
    @patch(P_TANAH, side_effect=AssertionError("SoilGrids tidak boleh dipanggil"))
    def test_uji_tanah_lengkap_tidak_panggil_soilgrids(self, *_):
        uji = {"ph": 6.2, "tekstur_kelas": "lempung berliat", "metode": "putk",
               "tanggal_uji": "2026-10-01"}
        r = self.api.post("/api/recommend/", self.body(uji_tanah=uji), format="json")
        self.assertEqual(r.status_code, 200, r.content)
        kl = r.json()["recommendation"]["kondisi_lahan"]
        self.assertEqual(kl["ph_tanah"], 6.2)
        self.assertEqual(kl["tekstur_kelas"], "clay loam")
        self.assertEqual(kl["sumber_data"]["ph"], "uji_tanah")
        self.assertEqual(kl["kualitas_data"]["label"], "Tinggi")
        # tanpa bulan_tanam: daftar kedua tetap ada untuk bulan berjalan (seperti recommend_dua)
        self.assertIsNotNone(r.json()["recommendation"]["rekomendasi_bulan_tanam"])

    @patch(P_SAT, return_value=SATELIT)
    @patch(P_IKLIM, return_value=IKLIM)
    @patch(P_TANAH, side_effect=GAGAL)
    def test_soilgrids_down_pakai_tetangga(self, *_):
        cache.simpan("tanah", LAT + 0.004, LON, dict(TANAH))   # ~450 m dari titik
        r = self.api.post("/api/recommend/", self.body(), format="json")
        self.assertEqual(r.status_code, 200, r.content)
        kl = r.json()["recommendation"]["kondisi_lahan"]
        self.assertEqual(kl["sumber_data"]["ph"], "tetangga")
        self.assertTrue(any("terdekat" in c for c in kl["catatan_data"]))

    @patch(P_SAT, return_value=SATELIT)
    @patch(P_IKLIM, return_value=IKLIM)
    @patch(P_TANAH, side_effect=GAGAL)
    def test_soilgrids_down_tanpa_cache_minta_uji_tanah(self, *_):
        r = self.api.post("/api/recommend/", self.body(), format="json")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["status"], "perlu_input")
        self.assertEqual(set(r.json()["butuh_input"]), {"ph", "tekstur_kelas"})

    @patch(P_SAT, return_value=SATELIT)
    @patch(P_IKLIM, return_value=IKLIM)
    def test_piksel_kosong_diisi_dari_titik_sekitar(self, *_):
        kosong = {k: None for k in TANAH}
        with patch(P_TANAH, side_effect=[kosong, dict(TANAH)]):
            r = self.api.post("/api/recommend/", self.body(), format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["recommendation"]["kondisi_lahan"]["sumber_data"]["ph"], "api_sekitar")

    @patch(P_SAT, side_effect=GAGAL)
    @patch(P_IKLIM, return_value=IKLIM)
    @patch(P_TANAH, return_value=dict(TANAH))
    def test_gee_down_elevasi_dari_open_meteo(self, *_):
        r = self.api.post("/api/recommend/", self.body(), format="json")
        self.assertEqual(r.status_code, 200, r.content)
        kl = r.json()["recommendation"]["kondisi_lahan"]
        self.assertEqual(kl["elevasi"], 35)
        self.assertIsNone(kl["ndvi"])
        self.assertEqual(kl["sumber_data"]["elevasi"], "open_meteo_dem")

    @patch(P_SAT, return_value=SATELIT)
    @patch(P_IKLIM, side_effect=GAGAL)
    @patch(P_TANAH, return_value=dict(TANAH))
    def test_iklim_down_tanpa_cache_503(self, *_):
        r = self.api.post("/api/recommend/", self.body(), format="json")
        self.assertEqual(r.status_code, 503)

    def test_validasi_uji_tanah(self):
        r = self.api.post("/api/recommend/", self.body(uji_tanah={"sand": 50, "silt": 10}), format="json")
        self.assertEqual(r.status_code, 400)
        r = self.api.post("/api/recommend/", self.body(uji_tanah={"tekstur_kelas": "lumpur ajaib"}),
                          format="json")
        self.assertEqual(r.status_code, 400)


class JobTes(DasarTes):
    @patch(P_SAT, return_value=SATELIT)
    @patch(P_IKLIM, return_value=IKLIM)
    @patch(P_TANAH, return_value=dict(TANAH))
    def test_job_analisis(self, *_):
        r = self.api.post("/api/analisis/", self.body(), format="json")
        self.assertEqual(r.status_code, 202, r.content)
        job_id = r.json()["job_id"]
        r = self.api.get(f"/api/analisis/{job_id}/?anonymous_id=anon-1")
        self.assertEqual(r.json()["status"], "selesai")
        self.assertEqual(r.json()["progres"]["tanah"], "selesai")
        self.assertIn("rekomendasi", r.json()["hasil"]["recommendation"])
        # anonymous_id lain tidak boleh melihat
        self.assertEqual(self.api.get(f"/api/analisis/{job_id}/?anonymous_id=x").status_code, 404)

    @patch(P_SAT, return_value=SATELIT)
    @patch(P_IKLIM, return_value=IKLIM)
    @patch(P_TANAH, side_effect=GAGAL)
    def test_job_perlu_input(self, *_):
        job_id = self.api.post("/api/analisis/", self.body(), format="json").json()["job_id"]
        body = self.api.get(f"/api/analisis/{job_id}/?anonymous_id=anon-1").json()
        self.assertEqual(body["status"], "perlu_input")
        self.assertIn("butuh_input", body["error"])


class CacheTes(DasarTes):
    def test_ambil_atau_fetch_cache_kedaluwarsa(self):
        cache.simpan("prakiraan", LAT, LON, {"harian": [1]})
        DataCache.objects.update(diambil_pada=timezone.now() - timedelta(days=1))
        def gagal(*a):
            raise GAGAL
        payload, asal, _ = cache.ambil_atau_fetch("prakiraan", LAT, LON, gagal)
        self.assertEqual(asal, "cache_kedaluwarsa")

    def test_tetangga_di_luar_radius_diabaikan(self):
        cache.simpan("tanah", LAT + 0.05, LON, dict(TANAH))   # ~5,5 km
        self.assertIsNone(cache.tetangga("tanah", LAT, LON))


class EkonomiTes(DasarTes):
    def test_parse_produktivitas(self):
        self.assertEqual(parse_produktivitas("1,5-2 ton/ha"), (1.5, 2.0))
        self.assertEqual(parse_produktivitas("-"), (None, None))

    def test_estimasi_kosong_lalu_lengkap(self):
        jagung = Crop.objects.get(slug="jagung")
        self.assertEqual(ekonomi.estimasi(jagung)["status"], "belum_tersedia")
        HargaKomoditas.objects.create(crop=jagung, tanggal=date(2026, 9, 1), harga_per_kg=5000)
        HargaKomoditas.objects.create(crop=jagung, tanggal=date(2026, 10, 1), harga_per_kg=5500)
        e = ekonomi.estimasi(jagung)
        self.assertEqual((e["status"], e["tersedia"]), ("pendapatan_saja", False))
        self.assertIsNotNone(e["estimasi_pendapatan_per_ha"])
        jagung.biaya_produksi_per_ha = 15_000_000
        jagung.save()
        e = ekonomi.estimasi(jagung)
        self.assertTrue(e["tersedia"])
        self.assertEqual(e["status"], "lengkap")
        self.assertEqual(e["estimasi_pendapatan_per_ha"], {"min": 27_500_000, "max": 38_500_000})
        self.assertEqual(e["estimasi_keuntungan_per_ha"]["min"], 12_500_000)
        self.assertEqual(e["perubahan_harga_30_hari_persen"], 10.0)


class MonitoringTes(DasarTes):
    def test_analisis_tren(self):
        tanam = date(2026, 7, 1)
        hari_ini = date(2026, 9, 1)
        obs = [(date(2026, 8, 1), 0.55), (date(2026, 8, 15), 0.62), (date(2026, 8, 28), 0.40)]
        kesehatan, peringatan = analisis_tren(obs, tanam, hari_ini)
        self.assertEqual(kesehatan, "perlu_dicek")
        self.assertIn("penurunan_tajam", [p["jenis"] for p in peringatan])
        kesehatan, _ = analisis_tren([(date(2026, 8, 1), 0.5), (date(2026, 8, 20), 0.55)], tanam, hari_ini)
        self.assertEqual(kesehatan, "baik")

    @patch("recommendation.services.cuaca.openmeteo.fetch_prakiraan", return_value={"harian": []})
    @patch("recommendation.services.apis.gee.fetch_deret_ndvi")
    @patch(P_SAT, return_value=SATELIT)
    @patch(P_IKLIM, return_value=IKLIM)
    @patch(P_TANAH, return_value=dict(TANAH))
    def test_alur_lahan_dan_feedback(self, _t, _i, _s, deret, _c):
        tanam = date.today() - timedelta(days=30)
        deret.return_value = [{"tanggal": (tanam + timedelta(days=d)).isoformat(),
                               "ndvi": n, "piksel_valid": 70}
                              for d, n in ((5, 0.2), (15, 0.35), (25, 0.5))]
        rek = self.api.post("/api/recommend/", self.body(), format="json").json()
        rek_id = rek["recommendation"]["rekomendasi"][0]["rekomendasi_id"]

        r = self.api.post("/api/lahan/", {"anonymous_id": "anon-1", "rekomendasi_id": rek_id,
                                         "tanggal_tanam": tanam.isoformat()}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        lahan_id = r.json()["id"]
        self.assertEqual(ObservasiNdvi.objects.filter(lahan_id=lahan_id).count(), 3)

        d = self.api.get(f"/api/lahan/{lahan_id}/?anonymous_id=anon-1").json()
        self.assertEqual(d["kesehatan"], "baik")
        self.assertEqual(len(d["observasi"]), 3)
        self.assertEqual(self.api.get(f"/api/lahan/{lahan_id}/?anonymous_id=x").status_code, 404)

        r = self.api.post("/api/feedback/", {"anonymous_id": "anon-1", "jenis": "hasil_panen",
                                            "lahan_id": lahan_id, "ditanam": True, "hasil": "baik",
                                            "rating": 5}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        r = self.api.post("/api/feedback/", {"anonymous_id": "orang-lain", "jenis": "hasil_panen",
                                            "lahan_id": lahan_id}, format="json")
        self.assertEqual(r.status_code, 400)


class UsabilityTes(DasarTes):
    def _ev(self, peserta, event, tugas=None, **data):
        return {"anonymous_id": "a", "sesi_id": "s-" + peserta, "event": event, "tugas": tugas,
                "peserta": peserta, "mode_tes": True, "halaman": "/analisis",
                "waktu": "2026-10-08T09:12:00Z", "data": data}

    def test_format_fe_dan_rekap(self):
        from .management.commands.rekap_usability import hitung
        from .models import UsabilityEvent
        events = [
            self._ev("P01", "tugas_mulai", "T1"),
            self._ev("P01", "tugas_selesai", "T1", berhasil=True, durasi_detik=40, dilewati=False),
            self._ev("P01", "tugas_selesai", "T2", berhasil=None, durasi_detik=90, dilewati=True),
            self._ev("P02", "tugas_selesai", "T1", berhasil=True, durasi_detik=60, dilewati=False),
            self._ev("P02", "tugas_selesai", "T2", berhasil=True, durasi_detik=74, dilewati=False),
            self._ev("P01", "sus", jawaban=[5, 1, 5, 1, 5, 1, 5, 1, 5, 1], skor=100),
            self._ev("P02", "sus", jawaban=[3] * 10, skor=50),
            self._ev("P02", "halaman_dibuka", path="/riwayat"),
        ]
        r = self.api.post("/api/usability/log/", events, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        r = self.api.post("/api/usability/log/", self._ev("P03", "cari_lokasi", jumlah=3), format="json")
        self.assertEqual(r.status_code, 201, r.content)

        e = UsabilityEvent.objects.get(peserta="P02", tugas="T2")
        self.assertEqual((e.berhasil, e.durasi_ms, e.mode_tes), (True, 74000, True))

        per_tugas, per_peserta, sus = hitung(UsabilityEvent.objects.filter(mode_tes=True))
        self.assertEqual((per_tugas["T1"]["berhasil"], per_tugas["T1"]["dihitung"]), (2, 2))
        self.assertEqual((per_tugas["T2"]["berhasil"], per_tugas["T2"]["dihitung"]), (1, 2))  # dilewati = gagal
        self.assertEqual(per_peserta["P01"]["berhasil"], 1)
        self.assertEqual(sus, {"P01": 100.0, "P02": 50.0})
        self.assertEqual(skor_sus([3] * 10), 50.0)
        call_command("rekap_usability", stdout=open("/dev/null", "w"))

    def test_throttle_usability_terpisah(self):
        from .views import UsabilityThrottle, log_usability
        self.assertEqual(log_usability.cls.throttle_classes, [UsabilityThrottle])


class KontrakFeTes(DasarTes):
    """Bentuk respons yang diminta dokumen 'Perubahan Backend untuk Mendukung FE Baru'."""

    def _analisis(self, **extra):
        with patch(P_TANAH, return_value=dict(TANAH)), \
                patch(P_IKLIM, return_value=IKLIM), patch(P_SAT, return_value=SATELIT):
            r = self.api.post("/api/recommend/", self.body(**extra), format="json")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()["recommendation"]

    def test_riwayat_detail_sama_dengan_hasil(self):
        rek = self._analisis(bulan_tanam=3, luas_lahan_m2=2500)
        r = self.api.get(f"/api/riwayat/{rek['riwayat_id']}/detail/?anonymous_id=anon-1")
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        for k in ("sumber_data", "kualitas_data", "catatan_data", "tekstur_kelas", "ph_rentang", "kemiringan"):
            self.assertIn(k, d["kondisi_lahan"])
        item = d["rekomendasi"][0]
        for k in ("rincian_skor", "faktor_pembatas", "mulai_tanam", "detail_kepercayaan",
                  "ekonomi", "rekomendasi_id", "crop_slug"):
            self.assertIn(k, item)
        self.assertEqual(d["rekomendasi_bulan_tanam"]["bulan"], "Mar")
        self.assertTrue(all(x["rekomendasi_id"] for x in d["rekomendasi_bulan_tanam"]["daftar"]))
        self.assertEqual(d["luas_lahan_m2"], 2500)

    def test_riwayat_lama_tanpa_snapshot(self):
        r = RiwayatPencarian.objects.create(anonymous_id="anon-1", lat=LAT, lon=LON, ph_tanah=5.5,
                                            tekstur_tanah={})
        RiwayatRekomendasi.objects.create(riwayat=r, crop_id="jagung", skor_kesesuaian=0.8,
                                          ranking=1, tingkat_kepercayaan="Tinggi", alasan_rekomendasi=["x"])
        d = self.api.get(f"/api/riwayat/{r.id}/detail/?anonymous_id=anon-1").json()
        self.assertIsNone(d["kondisi_lahan"]["kualitas_data"])
        self.assertIsNone(d["rekomendasi"][0]["rincian_skor"])
        self.assertIsNone(d["rekomendasi_bulan_tanam"])

    def test_riwayat_list(self):
        self._analisis(bulan_tanam=3, luas_lahan_m2=2500)
        d = self.api.get("/api/riwayat/?anonymous_id=anon-1").json()
        item = d["results"][0] if isinstance(d, dict) and "results" in d else d[0]
        self.assertEqual((item["bulan_tanam"], item["luas_lahan_m2"]), (3, 2500))
        self.assertNotIn("musim_target", item)
        self.assertNotIn("hasil_snapshot", item)
        self.assertEqual(len(item["rekomendasi"]), 5)   # hanya daftar utama
        for k in ("nama", "rekomendasi_id", "crop_slug"):
            self.assertIn(k, item["rekomendasi"][0])

    def test_detail_tanaman_field_baru(self):
        rek = self._analisis()
        d = self.api.get(f"/api/rekomendasi/{rek['rekomendasi'][0]['rekomendasi_id']}/detail/"
                         "?anonymous_id=anon-1").json()
        for k in ("rincian_skor", "faktor_pembatas", "mulai_tanam", "musim_tanam_mm", "detail_kepercayaan"):
            self.assertIn(k, d["ringkasan_rekomendasi"])
        for k in ("ekonomi", "tren_harga", "slug"):
            self.assertIn(k, d)

    def test_error_pakai_pesan(self):
        r = self.api.post("/api/recommend/", {"anonymous_id": "a"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("pesan", r.json())
        self.assertNotIn("message", r.json())
        self.assertEqual(self.api.get("/api/lahan/999/?anonymous_id=a").json()["pesan"], "Data tidak ditemukan.")

    @patch("recommendation.services.cuaca.openmeteo.fetch_prakiraan", return_value={"harian": []})
    @patch("recommendation.services.apis.gee.fetch_deret_ndvi", return_value=[])
    def test_lahan_dobel_409_dan_pantau_429(self, *_):
        rek = self._analisis()
        body = {"anonymous_id": "anon-1", "rekomendasi_id": rek["rekomendasi"][0]["rekomendasi_id"],
                "tanggal_tanam": "2026-09-01"}
        r1 = self.api.post("/api/lahan/", body, format="json")
        self.assertEqual(r1.status_code, 201)
        for k in ("nama_tanaman", "crop_slug", "nama_lokasi", "rekomendasi_id", "riwayat_id"):
            self.assertIn(k, r1.json())
        r2 = self.api.post("/api/lahan/", body, format="json")
        self.assertEqual(r2.status_code, 409)
        self.assertEqual(r2.json()["lahan_id"], r1.json()["id"])
        r3 = self.api.post(f"/api/lahan/{r1.json()['id']}/pantau/", {"anonymous_id": "anon-1"}, format="json")
        self.assertEqual(r3.status_code, 429)
        self.assertIn("pukul", r3.json()["pesan"])
        riw = self.api.get("/api/riwayat/?anonymous_id=anon-1").json()
        item = riw["results"][0] if isinstance(riw, dict) and "results" in riw else riw[0]
        self.assertEqual(item["lahan_aktif"][0]["lahan_id"], r1.json()["id"])

    @patch(P_SAT, return_value=SATELIT)
    @patch(P_IKLIM, return_value=IKLIM)
    @patch(P_TANAH, return_value=dict(TANAH))
    def test_job_progres_ada_elevasi(self, *_):
        job_id = self.api.post("/api/analisis/", self.body(), format="json").json()["job_id"]
        p = self.api.get(f"/api/analisis/{job_id}/?anonymous_id=anon-1").json()["progres"]
        self.assertEqual(set(p), {"tanah", "iklim", "elevasi", "satelit", "model"})
        self.assertEqual(p["elevasi"], "selesai")


class LuasDanPengapuranTes(DasarTes):
    def _analisis(self, **extra):
        with patch(P_TANAH, return_value=dict(TANAH, ph=4.7)), \
                patch(P_IKLIM, return_value=IKLIM), patch(P_SAT, return_value=SATELIT):
            r = self.api.post("/api/recommend/", self.body(**extra), format="json")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()["recommendation"]

    def test_luas_lahan_tersimpan_dan_ekonomi_per_lahan(self):
        jagung = Crop.objects.get(slug="jagung")
        jagung.biaya_produksi_per_ha = 15_000_000
        jagung.save()
        HargaKomoditas.objects.create(crop=jagung, tanggal=date(2026, 10, 1), harga_per_kg=5000)
        rek = self._analisis(luas_lahan_m2=2500)
        self.assertEqual(RiwayatPencarian.objects.get(pk=rek["riwayat_id"]).luas_lahan_m2, 2500)
        e = ekonomi.estimasi(jagung, 2500)
        self.assertEqual(e["estimasi_keuntungan_lahan"],
                         {"min": e["estimasi_keuntungan_per_ha"]["min"] // 4,
                          "max": e["estimasi_keuntungan_per_ha"]["max"] // 4})

    def test_pengapuran_belum_tersedia_501(self):
        rek = self._analisis()
        r = self.api.post("/api/simulasi/kapur/", {"anonymous_id": "anon-1", "riwayat_id": rek["riwayat_id"],
                                                   "dosis_ton_ha": 2}, format="json")
        self.assertEqual(r.status_code, 501)

    def test_pengapuran_dengan_modul_ml_palsu(self):
        import sys
        import types
        palsu = types.ModuleType("ml_lib.pengapuran")
        palsu.simulasi = lambda ph_awal, dosis_ton_ha=None, **kw: {
            "ph_baru": ph_awal + 0.5 * dosis_ton_ha, "dosis_ton_ha": dosis_ton_ha, "metode": "uji"}
        rek = self._analisis(luas_lahan_m2=5000)
        with patch.dict(sys.modules, {"ml_lib.pengapuran": palsu}):
            r = self.api.post("/api/simulasi/kapur/", {"anonymous_id": "anon-1",
                                                       "riwayat_id": rek["riwayat_id"],
                                                       "dosis_ton_ha": 2}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        b = r.json()
        self.assertEqual(b["ph_baru"], 5.7)
        self.assertEqual(b["kebutuhan_kapur"]["total_kg"], 1000)
        self.assertEqual(b["detail_ml"], {"metode": "uji"})
        self.assertEqual(len(b["rekomendasi_baru"]), 5)
        self.assertTrue(any(x["selisih"] > 0 for x in b["perubahan_skor"]))
        self.assertIn("sebelum", b["perubahan_skor"][0])

    def _ml_palsu(self):
        import types
        palsu = types.ModuleType("ml_lib.pengapuran")
        palsu.simulasi = lambda ph_awal, target_ph=None, **kw: {
            "ph_baru": target_ph, "dosis_ton_ha": round((target_ph - ph_awal) * 2, 2)}
        return palsu

    def test_pengapuran_isi_sendiri_tanpa_lokasi(self):
        import sys
        with patch.dict(sys.modules, {"ml_lib.pengapuran": self._ml_palsu()}):
            r = self.api.post("/api/simulasi/kapur/", {"anonymous_id": "anon-1",
                                                       "uji_tanah": {"ph": 5.2}, "luas_lahan_m2": 2500,
                                                       "target_ph": 6.5}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        b = r.json()
        self.assertEqual((b["perubahan_skor"], b["rekomendasi_baru"]), ([], []))
        self.assertEqual(b["kebutuhan_kapur"]["total_kg"], 650)

    @patch(P_SAT, return_value=SATELIT)
    @patch(P_IKLIM, return_value=IKLIM)
    @patch(P_TANAH, side_effect=AssertionError("tekstur sudah diisi, SoilGrids tak perlu"))
    def test_pengapuran_isi_sendiri_dengan_lokasi(self, *_):
        import sys
        with patch.dict(sys.modules, {"ml_lib.pengapuran": self._ml_palsu()}):
            r = self.api.post("/api/simulasi/kapur/", {
                "anonymous_id": "anon-1", "lat": LAT, "lon": LON, "target_ph": 6.5,
                "uji_tanah": {"ph": 4.6, "tekstur_kelas": "clay loam", "c_organik_persen": 1.4}},
                format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(r.json()["perubahan_skor"]), 10)
        self.assertEqual(len(r.json()["rekomendasi_baru"]), 5)

    def test_pengapuran_tanpa_riwayat_dan_ph_400(self):
        r = self.api.post("/api/simulasi/kapur/", {"anonymous_id": "a", "target_ph": 6}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("pH", r.json()["pesan"])

    def test_validasi_dosis_atau_target(self):
        r = self.api.post("/api/simulasi/kapur/", {"anonymous_id": "a", "riwayat_id": 1,
                                                   "dosis_ton_ha": 1, "target_ph": 6}, format="json")
        self.assertEqual(r.status_code, 400)


class KontrakMlTes(TestCase):
    KONDISI = {"ph_tanah": 5.5, "suhu": 27.3, "elevasi": 31, "tekstur_kelas": "clay loam",
               "curah_hujan_bulanan": IKLIM["curah_hujan_bulanan"], "ndvi": 0.6, "kemiringan": 3.0,
               "tekstur_tanah": {"sand": 30, "silt": 35, "clay": 35}, "ph_rentang": [5.0, 6.1],
               "sumber_data": {"ph": "api"}}

    def test_skor_per_bulan_dan_tanaman_tahunan(self):
        from .ml.ml_model import predict
        hasil = predict(self.KONDISI, top_k=None)["rekomendasi"]
        per = {h["crop_code"]: h for h in hasil}
        self.assertEqual(len(per["jagung"]["skor_per_bulan"]), 12)
        self.assertIsNone(per["kemiri"]["skor_per_bulan"])
        self.assertIsNone(per["kemiri"]["mulai_tanam"])

    def test_fitur_tambahan_hanya_dikirim_kalau_diterima_model(self):
        from .ml import ml_model
        diterima = {}
        asli = ml_model._model.recommend

        def palsu(*a, **kw):
            diterima.update(kw)
            kw = {k: v for k, v in kw.items() if k not in ml_model.FITUR_TAMBAHAN}
            return asli(*a, **kw)

        with patch.object(ml_model._model, "recommend", side_effect=palsu):
            ml_model.predict(self.KONDISI)
            self.assertNotIn("kemiringan_derajat", diterima)          # model asli tidak menerima
            with patch.object(ml_model, "_PARAMS", ml_model._PARAMS | {"kemiringan_derajat", "ph_q95"}):
                ml_model.predict(self.KONDISI)
        self.assertEqual((diterima["kemiringan_derajat"], diterima["ph_q95"]), (3.0, 6.1))
        self.assertNotIn("ndvi", diterima)                            # NDVI asli tidak ke param sintetik

    def test_skor_akhir_dipakai_untuk_urutan(self):
        from .ml import ml_model
        from .utils.formatter import format_daftar
        asli = ml_model._model.recommend

        def dengan_skor_akhir(*a, **kw):
            hasil = asli(*a, **kw)
            for h in hasil:
                h["skor_akhir"] = 99.0 if h["crop_code"] == "sorgum" else 10.0
            return hasil

        with patch.object(ml_model._model, "recommend", side_effect=dengan_skor_akhir):
            hasil = ml_model.predict(self.KONDISI)["rekomendasi"]
        self.assertEqual(hasil[0]["crop_code"], "sorgum")
        call_command("seed_crop", stdout=open("/dev/null", "w"))
        item = format_daftar(hasil[:1], {**self.KONDISI, "kualitas_data": {"skor": 0.8}})[0]
        self.assertEqual((item["skor_kesesuaian"], item["sumber_skor"]), (0.99, "hybrid"))


class PengapuranContohTes(DasarTes):
    def test_mati_secara_default(self):
        r = self.api.post("/api/simulasi/kapur/", {"anonymous_id": "a", "uji_tanah": {"ph": 5.0},
                                                   "target_ph": 6.0}, format="json")
        self.assertEqual(r.status_code, 501)

    @override_settings(NUSACROP_PENGAPURAN_CONTOH=True)
    def test_mode_contoh(self):
        r = self.api.post("/api/simulasi/kapur/", {"anonymous_id": "a",
                                                   "uji_tanah": {"ph": 5.0, "tekstur_kelas": "clay loam"},
                                                   "target_ph": 6.0, "luas_lahan_m2": 2500}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        b = r.json()
        self.assertTrue(b["mode_contoh"])
        self.assertEqual(b["detail_ml"]["metode"], "contoh")
        self.assertGreater(b["kebutuhan_kapur"]["dosis_ton_ha"], 0)
        from .services.pengapuran_contoh import simulasi
        self.assertLess(simulasi(5.0, "loam", dosis_ton_ha=1)["ph_baru"],
                        simulasi(5.0, "loam", dosis_ton_ha=2)["ph_baru"])
        self.assertEqual(simulasi(5.0, "sand", dosis_ton_ha=50)["ph_baru"], 7.0)

    @override_settings(NUSACROP_PENGAPURAN_CONTOH=True)
    def test_modul_asli_diutamakan(self):
        import sys
        import types
        asli = types.ModuleType("ml_lib.pengapuran")
        asli.simulasi = lambda ph_awal, target_ph=None, **kw: {"ph_baru": target_ph, "dosis_ton_ha": 1.0}
        with patch.dict(sys.modules, {"ml_lib.pengapuran": asli}):
            r = self.api.post("/api/simulasi/kapur/", {"anonymous_id": "a", "uji_tanah": {"ph": 5.0},
                                                       "target_ph": 6.0}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(r.json()["mode_contoh"])


class GeeKredensialTes(TestCase):
    def test_tanpa_kredensial_gagal_cepat_tanpa_retry(self):
        import time as _t
        from .services.apis import gee
        with patch.dict("os.environ", {"GEE_SERVICE_ACCOUNT_KEY_JSON": "", "GEE_SERVICE_ACC_EMAIL": "",
                                       "GEE_SERVICE_ACC_KEY_PATH": ""}), \
                patch.object(gee, "_siap", False):
            mulai = _t.monotonic()
            with self.assertRaises(gee.KredensialGeeBermasalah):
                gee.fetch_satelit(LAT, LON)
        self.assertLess(_t.monotonic() - mulai, 0.5)

    def test_json_rusak_pesan_jelas(self):
        from .services.apis import gee
        with patch.dict("os.environ", {"GEE_SERVICE_ACCOUNT_KEY_JSON": "{"}), patch.object(gee, "_siap", False):
            with self.assertRaisesRegex(gee.KredensialGeeBermasalah, "tidak valid"):
                gee.fetch_satelit(LAT, LON)


class TanahViaGeeTes(DasarTes):
    GEE_TANAH = {"ph": 5.4, "sand": 30.0, "silt": 35.0, "clay": 35.0, "organic_carbon": 14.0,
                 "nitrogen": 1.5, "ph_q05": None, "ph_q95": None, "_sumber": "soilgrids_gee"}

    @patch(P_SAT, return_value=SATELIT)
    @patch(P_IKLIM, return_value=IKLIM)
    @patch(P_TANAH, side_effect=AssertionError("REST tidak boleh dipanggil kalau GEE berhasil"))
    def test_gee_utama(self, *_):
        with patch("recommendation.services.apis.gee.kredensial_tersedia", return_value=True), \
                patch("recommendation.services.apis.gee.fetch_tanah", return_value=dict(self.GEE_TANAH)):
            r = self.api.post("/api/recommend/", self.body(), format="json")
        self.assertEqual(r.status_code, 200, r.content)
        kl = r.json()["recommendation"]["kondisi_lahan"]
        self.assertEqual((kl["ph_tanah"], kl["tekstur_kelas"]), (5.4, "clay loam"))
        self.assertIsNone(kl["ph_rentang"])

    @patch(P_SAT, return_value=SATELIT)
    @patch(P_IKLIM, return_value=IKLIM)
    @patch(P_TANAH, return_value=dict(TANAH))
    def test_gee_gagal_pakai_rest(self, rest, *_):
        with patch("recommendation.services.apis.gee.kredensial_tersedia", return_value=True), \
                patch("recommendation.services.apis.gee.fetch_tanah", side_effect=SumberDataGagal("down")):
            r = self.api.post("/api/recommend/", self.body(), format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(rest.called)
        self.assertEqual(r.json()["recommendation"]["kondisi_lahan"]["ph_tanah"], 5.5)

    def test_konversi_satuan_gee(self):
        from .services.apis import gee
        mentah = {"phh2o": 54, "sand": 300, "silt": 350, "clay": 350, "soc": 140, "nitrogen": 150}
        with patch.object(gee, "_dengan_retry", return_value=mentah):
            d = gee.fetch_tanah(LAT, LON)
        self.assertEqual((d["ph"], d["clay"], d["organic_carbon"], d["nitrogen"]), (5.4, 35.0, 14.0, 1.5))


class GarisMiringTes(DasarTes):
    def test_tanpa_garis_miring(self):
        r = self.api.post("/api/usability/log", {"sesi_id": "s", "event": "halaman_dibuka"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.api.get("/api/riwayat?anonymous_id=a").status_code, 200)
        self.assertEqual(self.api.get("/api/lahan?anonymous_id=a&status=aktif").status_code, 200)
        self.assertEqual(self.api.get("/api/ekonomi/jagung").status_code, 200)
        self.assertEqual(self.api.get("/api/ekonomi/jagung/").status_code, 200)


class DataEkonomiTes(DasarTes):
    def test_muat_data_ekonomi(self):
        call_command("muat_data_ekonomi", stdout=open("/dev/null", "w"))
        call_command("muat_data_ekonomi", stdout=open("/dev/null", "w"))  # aman diulang
        self.assertGreater(HargaKomoditas.objects.count(), 9_000)
        self.assertEqual(HargaKomoditas.objects.filter(crop_id="jagung", wilayah_kode="00").count(), 36)

        jagung = Crop.objects.get(slug="jagung")
        self.assertEqual((jagung.biaya_produksi_per_ha, jagung.tahun_biaya), (10_197_140, 2017))
        e = ekonomi.estimasi(jagung, 2500)
        self.assertEqual(e["status"], "lengkap")
        self.assertEqual(e["wilayah_harga"], "Indonesia")
        self.assertEqual(e["tanggal_harga"], "2024-12-01")
        self.assertIn("tahun 2017", e["catatan"])
        self.assertEqual(len(ekonomi.tren_harga(jagung)), 12)

        self.assertEqual(ekonomi.estimasi(Crop.objects.get(slug="cabai_rawit"))["status"], "pendapatan_saja")
        singkong = ekonomi.estimasi(Crop.objects.get(slug="singkong"))
        self.assertEqual((singkong["harga_per_kg"], singkong["tanggal_harga"]), (1350, "2025-01-31"))
        self.assertFalse(HargaKomoditas.objects.filter(crop_id="singkong", sumber__startswith="BPS").exists())
        self.assertEqual(ekonomi.estimasi(Crop.objects.get(slug="sorgum"))["status"], "belum_tersedia")
