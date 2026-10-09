from django.contrib import admin

from .models import (AnalisisJob, Crop, DataCache, FeedbackPengguna, HargaKomoditas, LahanTanam,
                     ObservasiNdvi, RiwayatPencarian, RiwayatRekomendasi, UsabilityEvent)


@admin.register(Crop)
class CropAdmin(admin.ModelAdmin):
    list_display = ["slug", "nama", "jenis_tanaman", "produktivitas_min_ton_ha",
                    "produktivitas_max_ton_ha", "biaya_produksi_per_ha"]


@admin.register(HargaKomoditas)
class HargaAdmin(admin.ModelAdmin):
    list_display = ["crop", "tanggal", "tingkat", "harga_per_kg", "wilayah_nama", "sumber"]
    list_filter = ["crop", "tingkat"]


@admin.register(DataCache)
class DataCacheAdmin(admin.ModelAdmin):
    list_display = ["sumber", "kunci_sel", "diambil_pada"]
    list_filter = ["sumber"]


@admin.register(AnalisisJob)
class JobAdmin(admin.ModelAdmin):
    list_display = ["id", "status", "dibuat_pada", "diperbarui_pada"]
    list_filter = ["status"]


@admin.register(LahanTanam)
class LahanAdmin(admin.ModelAdmin):
    list_display = ["id", "crop", "tanggal_tanam", "status", "kesehatan", "terakhir_dipantau"]
    list_filter = ["status", "kesehatan"]


@admin.register(FeedbackPengguna)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ["id", "jenis", "ditanam", "hasil", "rating", "dibuat_pada"]
    list_filter = ["jenis", "hasil"]


admin.site.register([RiwayatPencarian, RiwayatRekomendasi, ObservasiNdvi, UsabilityEvent])
