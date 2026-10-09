from django.db import models
from .crop_models import Crop

class RiwayatPencarian(models.Model):

    anonymous_id = models.CharField(max_length=100,db_index=True)

    nama_lokasi = models.CharField(max_length=100, null=True, blank=True)
    
    lat = models.FloatField()
    lon = models.FloatField()

    musim_target = models.CharField(max_length=50,null=True,blank=True)

    curah_hujan = models.FloatField(null=True,blank=True)

    ph_tanah = models.FloatField(null=True, blank=True)

    elevasi = models.FloatField(null = True,blank=True)
    
    ndvi = models.FloatField(null=True, blank=True)
    
    suhu = models.FloatField(null=True,blank=True)
    et0 = models.FloatField(null=True,blank=True)


    nitrogen = models.FloatField(null=True,blank=True)
    organic_carbon = models.FloatField(null=True,blank=True)
    tekstur_tanah = models.JSONField(default=dict)
    kesuburan_tanah = models.FloatField(null=True,blank=True)

    # tambahan
    bulan_tanam = models.PositiveSmallIntegerField(null=True, blank=True)  # 1-12
    kemiringan = models.FloatField(null=True, blank=True)                  # derajat
    uji_tanah = models.JSONField(null=True, blank=True)
    sumber_data = models.JSONField(default=dict, blank=True)
    kualitas_data = models.FloatField(null=True, blank=True)               # 0-1
    luas_lahan_m2 = models.FloatField(null=True, blank=True)
    # disimpan agar simulasi (mis. pengapuran) bisa dihitung ulang tanpa API
    curah_hujan_bulanan = models.JSONField(null=True, blank=True)
    tekstur_kelas = models.CharField(max_length=30, null=True, blank=True)
    # salinan lengkap objek `recommendation` saat analisis, agar riwayat bisa
    # ditampilkan persis seperti hasil analisis (ekonomi dihitung ulang saat dibaca)
    hasil_snapshot = models.JSONField(null=True, blank=True)

    dibuat_pada = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ["-dibuat_pada"]
        
    def __str__(self):
        return f"Riwayat {self.id} ({self.lat},{self.lon})"

class RiwayatRekomendasi(models.Model):

    riwayat = models.ForeignKey(
        RiwayatPencarian,
        related_name="rekomendasi",
        on_delete=models.CASCADE
    )

    crop = models.ForeignKey(
        Crop,
        on_delete=models.PROTECT
    )
    
    jenis_tanaman = models.CharField(max_length=100, null=True, blank=True)

    skor_kesesuaian = models.FloatField()

    ranking = models.PositiveSmallIntegerField()

    tingkat_kepercayaan = models.CharField(
        max_length=50,
        default="Sedang"
    )

    alasan_rekomendasi = models.JSONField(
        default=list
    )

    # tambahan
    mulai_tanam = models.CharField(max_length=5, null=True, blank=True)
    musim_tanam_mm = models.FloatField(null=True, blank=True)
    rincian_skor = models.JSONField(default=dict, blank=True)
    faktor_pembatas = models.JSONField(default=list, blank=True)
    detail_kepercayaan = models.JSONField(null=True, blank=True)
    # "utama" = daftar rekomendasi utama; "bulan_tanam" = hanya muncul di tab
    # "cocok ditanam bulan X" (disimpan agar detailnya tetap bisa dibuka)
    daftar = models.CharField(max_length=20, default="utama")


    class Meta:
        ordering = ["ranking"]

        constraints = [
            models.UniqueConstraint(
                fields=["riwayat", "crop"],
                name="unique_crop_history"
            )
        ]