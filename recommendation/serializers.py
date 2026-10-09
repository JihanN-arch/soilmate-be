from rest_framework import serializers

from .ml.ml_model import get_profile
from .models.crop_models import Crop
from .models.monitoring_models import FeedbackPengguna, LahanTanam, ObservasiNdvi, UsabilityEvent
from .models.riwayat_models import RiwayatPencarian, RiwayatRekomendasi
from .services.data_tanah import normalisasi_tekstur


# ---------------------------------------------------------------- input
class UjiTanahSerializer(serializers.Serializer):
    """Hasil uji tanah dari pH meter, PUTK, atau laboratorium. Semua opsional,
    tapi minimal salah satu dari pH / tekstur harus ada."""

    ph = serializers.FloatField(min_value=3.0, max_value=10.0, required=False, allow_null=True)
    tekstur_kelas = serializers.CharField(required=False, allow_null=True, allow_blank=True,
                                          help_text="Kelas USDA ('clay loam') atau Indonesia ('lempung berliat')")
    sand = serializers.FloatField(min_value=0, max_value=100, required=False, allow_null=True)
    silt = serializers.FloatField(min_value=0, max_value=100, required=False, allow_null=True)
    clay = serializers.FloatField(min_value=0, max_value=100, required=False, allow_null=True)
    c_organik_persen = serializers.FloatField(min_value=0, max_value=60, required=False, allow_null=True)
    nitrogen_persen = serializers.FloatField(min_value=0, max_value=5, required=False, allow_null=True)
    metode = serializers.ChoiceField(choices=["ph_meter", "putk", "lab", "lainnya"],
                                     required=False, allow_null=True)
    tanggal_uji = serializers.DateField(required=False, allow_null=True)

    def validate_tekstur_kelas(self, nilai):
        if not nilai:
            return None
        if normalisasi_tekstur(nilai) is None:
            raise serializers.ValidationError("Kelas tekstur tidak dikenal.")
        return nilai

    def validate(self, d):
        fraksi = [d.get(k) for k in ("sand", "silt", "clay")]
        if any(v is not None for v in fraksi):
            if any(v is None for v in fraksi):
                raise serializers.ValidationError("sand, silt, dan clay harus diisi ketiganya.")
            if not 95 <= sum(fraksi) <= 105:
                raise serializers.ValidationError("Jumlah sand + silt + clay harus sekitar 100%.")
        if d.get("ph") is None and not d.get("tekstur_kelas") and fraksi[0] is None:
            raise serializers.ValidationError("Isi minimal pH atau tekstur tanah.")
        if d.get("tanggal_uji"):
            d["tanggal_uji"] = d["tanggal_uji"].isoformat()  # agar aman disimpan di JSONField
        return d


class RecommendRequestSerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-11, max_value=6)
    lon = serializers.FloatField(min_value=95, max_value=141)
    nama_lokasi = serializers.CharField(max_length=100, min_length=1)
    bulan_tanam = serializers.IntegerField(min_value=1, max_value=12, required=False, allow_null=True)
    # lama, dipertahankan agar FE lama tetap jalan (dipetakan ke bulan_tanam)
    musim_target = serializers.ChoiceField(choices=["hujan", "kemarau"], required=False, allow_null=True)
    uji_tanah = UjiTanahSerializer(required=False, allow_null=True)
    # luas dalam m2 (FE yang mengonversi dari ha / are / bata / tumbak)
    luas_lahan_m2 = serializers.FloatField(min_value=1, max_value=10_000_000,
                                           required=False, allow_null=True)


class LahanTanamCreateSerializer(serializers.Serializer):
    anonymous_id = serializers.CharField(max_length=100)
    rekomendasi_id = serializers.IntegerField(required=False, allow_null=True)
    crop = serializers.SlugRelatedField(slug_field="slug", queryset=Crop.objects.all(), required=False)
    lat = serializers.FloatField(min_value=-11, max_value=6, required=False)
    lon = serializers.FloatField(min_value=95, max_value=141, required=False)
    radius_m = serializers.IntegerField(min_value=10, max_value=500, required=False, default=50)
    tanggal_tanam = serializers.DateField()
    nama = serializers.CharField(max_length=100, required=False, allow_blank=True)
    luas_lahan_m2 = serializers.FloatField(min_value=1, max_value=10_000_000,
                                           required=False, allow_null=True)

    def validate(self, d):
        rek_id = d.get("rekomendasi_id")
        if rek_id:
            rek = (RiwayatRekomendasi.objects.select_related("riwayat", "crop")
                   .filter(id=rek_id, riwayat__anonymous_id=d["anonymous_id"]).first())
            if rek is None:
                raise serializers.ValidationError({"rekomendasi_id": "Rekomendasi tidak ditemukan."})
            d["rekomendasi"] = rek
            d.setdefault("crop", rek.crop)
            d.setdefault("lat", rek.riwayat.lat)
            d.setdefault("lon", rek.riwayat.lon)
            d.setdefault("nama", rek.riwayat.nama_lokasi)
            if d.get("luas_lahan_m2") is None:
                d["luas_lahan_m2"] = rek.riwayat.luas_lahan_m2
        missing = [k for k in ("crop", "lat", "lon") if d.get(k) is None]
        if missing:
            raise serializers.ValidationError(
                f"Isi rekomendasi_id, atau isi langsung: {', '.join(missing)}.")
        d.pop("rekomendasi_id", None)
        return d


class SimulasiKapurSerializer(serializers.Serializer):
    """Mode 1: riwayat_id. Mode 2: uji_tanah (minimal ph), lat/lon opsional."""

    anonymous_id = serializers.CharField(max_length=100)
    riwayat_id = serializers.IntegerField(required=False, allow_null=True)
    uji_tanah = UjiTanahSerializer(required=False, allow_null=True)
    lat = serializers.FloatField(min_value=-11, max_value=6, required=False, allow_null=True)
    lon = serializers.FloatField(min_value=95, max_value=141, required=False, allow_null=True)
    dosis_ton_ha = serializers.FloatField(min_value=0, max_value=20, required=False, allow_null=True)
    target_ph = serializers.FloatField(min_value=4.0, max_value=7.5, required=False, allow_null=True)
    jenis_kapur = serializers.ChoiceField(choices=["dolomit", "kalsit", "kapur_tohor"], default="dolomit")
    luas_lahan_m2 = serializers.FloatField(min_value=1, max_value=10_000_000, required=False, allow_null=True)

    def validate(self, d):
        if (d.get("dosis_ton_ha") is None) == (d.get("target_ph") is None):
            raise serializers.ValidationError("Isi salah satu: dosis kapur atau target pH.")
        if not d.get("riwayat_id") and (d.get("uji_tanah") or {}).get("ph") is None:
            raise serializers.ValidationError(
                "Pilih lahan yang sudah dianalisis, atau isi pH tanah sendiri.")
        if (d.get("lat") is None) != (d.get("lon") is None):
            raise serializers.ValidationError("Lintang dan bujur harus diisi keduanya.")
        return d


class FeedbackSerializer(serializers.ModelSerializer):
    rekomendasi_id = serializers.PrimaryKeyRelatedField(
        source="rekomendasi", queryset=RiwayatRekomendasi.objects.all(), required=False, allow_null=True)
    lahan_id = serializers.PrimaryKeyRelatedField(
        source="lahan", queryset=LahanTanam.objects.all(), required=False, allow_null=True)
    rating = serializers.IntegerField(min_value=1, max_value=5, required=False, allow_null=True)

    class Meta:
        model = FeedbackPengguna
        fields = ["id", "anonymous_id", "jenis", "rekomendasi_id", "lahan_id", "ditanam", "hasil",
                  "hasil_panen_kg", "luas_lahan_m2", "rating", "komentar", "dibuat_pada"]
        read_only_fields = ["id", "dibuat_pada"]

    def validate(self, d):
        aid = d["anonymous_id"]
        if d.get("rekomendasi") and d["rekomendasi"].riwayat.anonymous_id != aid:
            raise serializers.ValidationError({"rekomendasi_id": "Tidak ditemukan."})
        if d.get("lahan") and d["lahan"].anonymous_id != aid:
            raise serializers.ValidationError({"lahan_id": "Tidak ditemukan."})
        return d


class UsabilityEventSerializer(serializers.ModelSerializer):
    """Format FE: {anonymous_id, sesi_id, event, tugas, peserta, mode_tes, halaman, waktu, data}."""

    waktu = serializers.DateTimeField(source="waktu_klien", required=False, allow_null=True)
    data = serializers.JSONField(required=False, default=dict)
    anonymous_id = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")

    class Meta:
        model = UsabilityEvent
        fields = ["anonymous_id", "sesi_id", "event", "tugas", "peserta", "mode_tes",
                  "halaman", "waktu", "data"]
        extra_kwargs = {"tugas": {"required": False, "allow_null": True, "allow_blank": True},
                        "peserta": {"required": False, "allow_null": True, "allow_blank": True},
                        "halaman": {"required": False, "allow_null": True, "allow_blank": True},
                        "mode_tes": {"required": False}}

    def validate_data(self, d):
        if d is None:
            return {}
        if not isinstance(d, dict):
            raise serializers.ValidationError("data harus berupa objek.")
        return d

    def validate(self, v):
        data = v.get("data") or {}
        if isinstance(data.get("berhasil"), bool):
            v["berhasil"] = data["berhasil"]
        durasi = data.get("durasi_detik")
        if isinstance(durasi, (int, float)) and durasi >= 0:
            v["durasi_ms"] = round(durasi * 1000)
        return v


# ---------------------------------------------------------------- output
class RiwayatRekomendasiSerializer(serializers.ModelSerializer):
    rekomendasi_id = serializers.IntegerField(source="id", read_only=True)
    nama = serializers.CharField(source="crop.nama")
    crop_slug = serializers.CharField(source="crop_id")
    nama_latin = serializers.CharField(source="crop.nama_latin")
    nama_tanaman = serializers.CharField(source="crop.nama")      # lama, pakai `nama`
    kesuburan_ideal = serializers.SerializerMethodField()
    ph_ideal = serializers.SerializerMethodField()
    elevasi_ideal = serializers.SerializerMethodField()

    class Meta:
        model = RiwayatRekomendasi
        fields = [
            'rekomendasi_id', 'id', 'crop_slug', 'nama', 'nama_tanaman', 'nama_latin',
            'jenis_tanaman', 'kesuburan_ideal', 'ph_ideal', 'elevasi_ideal',
            'skor_kesesuaian', 'ranking', 'tingkat_kepercayaan', 'mulai_tanam',
        ]

    def get_kesuburan_ideal(self, obj):
        return (obj.crop.syarat_tumbuh or {}).get('kesuburan')

    def get_ph_ideal(self, obj):
        p = get_profile(obj.crop_id) or {}
        return f"{p.get('ph_min')} - {p.get('ph_max')}"

    def get_elevasi_ideal(self, obj):
        p = get_profile(obj.crop_id) or {}
        return f"{p.get('elevation_min')} - {p.get('elevation_max')} mdpl"


class RiwayatPencarianSerializer(serializers.ModelSerializer):
    riwayat_id = serializers.IntegerField(source="id", read_only=True)
    rekomendasi = serializers.SerializerMethodField()
    nama_tampilan = serializers.SerializerMethodField()
    kualitas_data = serializers.SerializerMethodField()
    lahan_aktif = serializers.SerializerMethodField()

    class Meta:
        model = RiwayatPencarian
        fields = [
            'riwayat_id', 'id', 'nama_lokasi', 'nama_tampilan', 'lat', 'lon',
            'bulan_tanam', 'luas_lahan_m2', 'curah_hujan', 'ph_tanah', 'elevasi', 'ndvi',
            'suhu', 'et0', 'nitrogen', 'organic_carbon', 'tekstur_tanah', 'tekstur_kelas',
            'kesuburan_tanah', 'kemiringan', 'sumber_data', 'kualitas_data', 'dibuat_pada',
            'rekomendasi', 'lahan_aktif',
        ]

    def get_rekomendasi(self, obj):
        items = [r for r in obj.rekomendasi.all() if r.daftar == "utama"]
        return RiwayatRekomendasiSerializer(items, many=True).data

    def get_nama_tampilan(self, obj):
        if obj.nama_lokasi:
            return obj.nama_lokasi
        return f"Lokasi {obj.lat:.4f}, {obj.lon:.4f}"

    def get_kualitas_data(self, obj):
        s = obj.kualitas_data
        if s is None:
            return None
        return {"skor": s, "label": "Tinggi" if s >= 0.85 else "Sedang" if s >= 0.7 else "Rendah"}

    def get_lahan_aktif(self, obj):
        """Lahan yang sedang ditanam dari riwayat ini (untuk tab "Sedang ditanam")."""
        return [{"lahan_id": l.id, "crop_slug": l.crop_id, "rekomendasi_id": r.id}
                for r in obj.rekomendasi.all() for l in r.lahan_tanam.all() if l.status == "aktif"]


class ObservasiNdviSerializer(serializers.ModelSerializer):
    class Meta:
        model = ObservasiNdvi
        fields = ["tanggal", "ndvi", "piksel_valid"]


class LahanTanamSerializer(serializers.ModelSerializer):
    crop_nama = serializers.CharField(source="crop.nama", read_only=True)       # lama
    nama_tanaman = serializers.CharField(source="crop.nama", read_only=True)
    crop_slug = serializers.CharField(source="crop_id", read_only=True)
    nama_lokasi = serializers.CharField(source="nama", read_only=True)
    rekomendasi_id = serializers.IntegerField(read_only=True)
    riwayat_id = serializers.SerializerMethodField()
    hari_setelah_tanam = serializers.SerializerMethodField()
    ndvi_terbaru = serializers.SerializerMethodField()

    class Meta:
        model = LahanTanam
        fields = ["id", "nama", "nama_lokasi", "crop", "crop_slug", "crop_nama", "nama_tanaman",
                  "rekomendasi", "rekomendasi_id", "riwayat_id", "lat", "lon", "radius_m",
                  "tanggal_tanam", "hari_setelah_tanam", "luas_lahan_m2", "status", "kesehatan", "peringatan",
                  "ndvi_terbaru", "terakhir_dipantau", "dibuat_pada"]
        # yang boleh diubah lewat PATCH: nama, tanggal_tanam, luas_lahan_m2, status
        read_only_fields = ["crop", "rekomendasi", "lat", "lon", "radius_m", "kesehatan",
                            "peringatan", "terakhir_dipantau", "dibuat_pada"]

    def get_riwayat_id(self, obj):
        return obj.rekomendasi.riwayat_id if obj.rekomendasi_id else None

    def get_hari_setelah_tanam(self, obj):
        from django.utils import timezone
        return (timezone.localdate() - obj.tanggal_tanam).days

    def get_ndvi_terbaru(self, obj):
        o = obj.observasi.order_by("-tanggal").first()
        return {"tanggal": o.tanggal, "ndvi": o.ndvi} if o else None
