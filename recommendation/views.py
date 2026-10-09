from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.generics import DestroyAPIView
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from .models.crop_models import Crop
from .models.job_models import AnalisisJob
from .models.monitoring_models import LahanTanam
from .models.riwayat_models import RiwayatPencarian
from .serializers import (FeedbackSerializer, LahanTanamCreateSerializer, LahanTanamSerializer,
                          ObservasiNdviSerializer, RecommendRequestSerializer,
                          RiwayatPencarianSerializer, SimulasiKapurSerializer,
                          UsabilityEventSerializer)
from .services import cuaca, ekonomi, jobs
from .services.detail_crop import get_crop_detail
from .services.errors import DataTidakLengkap, PrediksiGagal, SumberDataGagal
from .services.pengapuran import PengapuranBelumTersedia, RiwayatTidakLengkap, simulasi_kapur
from .services.recommendation_services import get_recommendation
from .services.riwayat import riwayat_sebagai_hasil
from .utils.pagination import RiwayatPagination
from .utils.respons import galat


class AnalisisThrottle(ScopedRateThrottle):
    scope = "analisis"


class UsabilityThrottle(ScopedRateThrottle):
    scope = "usability"


def _anonymous_id(request):
    data = request.data if isinstance(request.data, dict) else {}
    return data.get("anonymous_id") or request.query_params.get("anonymous_id")


def _wajib_anonymous_id(request):
    aid = _anonymous_id(request)
    if not aid:
        return None, galat("anonymous_id wajib dikirim.", 400)
    return aid, None


def _validasi_rekomendasi(request):
    serializer = RecommendRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    aid, err = _wajib_anonymous_id(request)
    return serializer.validated_data, aid, err


# ------------------------------------------------------------ rekomendasi
@api_view(["POST"])
@throttle_classes([AnalisisThrottle])
def recommend(request):
    """Sinkron (kompatibel dengan FE lama). Untuk progres per sumber, pakai /api/analisis/."""
    data, aid, err = _validasi_rekomendasi(request)
    if err:
        return err
    try:
        return Response(get_recommendation(data, aid))
    except DataTidakLengkap as e:
        return galat(e.pesan, 422, status="perlu_input", butuh_input=e.butuh_input)
    except (SumberDataGagal, PrediksiGagal):
        return galat("Data lingkungan untuk lokasi ini sedang tidak dapat diambil. "
                     "Coba lagi beberapa saat lagi.", 503)


@api_view(["POST"])
@throttle_classes([AnalisisThrottle])
def analisis_mulai(request):
    data, aid, err = _validasi_rekomendasi(request)
    if err:
        return err
    job = AnalisisJob.objects.create(anonymous_id=aid, input=data)
    jobs.kirim("analisis", str(job.id))
    return Response({"job_id": str(job.id), "status": job.status}, status=status.HTTP_202_ACCEPTED)


@api_view(["GET"])
def analisis_status(request, job_id):
    aid, err = _wajib_anonymous_id(request)
    if err:
        return err
    job = jobs.tandai_job_macet(get_object_or_404(AnalisisJob, pk=job_id, anonymous_id=aid))
    body = {"job_id": str(job.id), "status": job.status, "progres": job.progres}
    if job.status == "selesai":
        body["hasil"] = job.hasil
    elif job.status in ("gagal", "perlu_input"):
        body["error"] = job.error
        body["pesan"] = (job.error or {}).get("pesan")
        if job.status == "perlu_input":
            body["butuh_input"] = (job.error or {}).get("butuh_input", [])
    return Response(body)


@api_view(['GET'])
def detail_tanaman(request, rekomendasi_id):
    # anonymous_id belum diwajibkan agar FE lama tetap jalan; segera kirim dari FE
    result = get_crop_detail(rekomendasi_id, _anonymous_id(request))
    if result is None:
        return galat("Tanaman tidak ditemukan.", 404)
    return Response(result)


@api_view(["POST"])
def simulasi_pengapuran(request):
    s = SimulasiKapurSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    d = s.validated_data
    riwayat = None
    if d.get("riwayat_id"):
        riwayat = get_object_or_404(RiwayatPencarian, pk=d["riwayat_id"], anonymous_id=d["anonymous_id"])
    try:
        return Response(simulasi_kapur(
            riwayat=riwayat, uji_tanah=d.get("uji_tanah"), lat=d.get("lat"), lon=d.get("lon"),
            dosis_ton_ha=d.get("dosis_ton_ha"), target_ph=d.get("target_ph"),
            jenis_kapur=d["jenis_kapur"], luas_lahan_m2=d.get("luas_lahan_m2")))
    except PengapuranBelumTersedia:
        return galat("Fitur simulasi kapur segera hadir.", 501, status="belum_tersedia")
    except RiwayatTidakLengkap as e:
        return galat(str(e), 409)
    except PrediksiGagal as e:
        return galat(str(e), 400)


# ------------------------------------------------------------ cuaca & ekonomi
@api_view(["GET"])
def prakiraan_cuaca(request):
    try:
        lat, lon = float(request.query_params["lat"]), float(request.query_params["lon"])
    except (KeyError, ValueError):
        return galat("Lintang dan bujur wajib berupa angka.", 400)
    try:
        return Response(cuaca.get_prakiraan(lat, lon))
    except SumberDataGagal:
        return galat("Prakiraan cuaca sedang tidak dapat diambil.", 503)


@api_view(["GET"])
def ekonomi_tanaman(request, slug):
    crop = get_object_or_404(Crop, slug=slug)
    luas = request.query_params.get("luas_lahan_m2")
    try:
        luas = float(luas) if luas else None
    except ValueError:
        luas = None
    return Response({"crop": slug, "crop_slug": slug, **ekonomi.estimasi(crop, luas),
                     "tren_harga": ekonomi.tren_harga(crop)})


# ------------------------------------------------------------ riwayat
class RiwayatListView(generics.ListAPIView):
    serializer_class = RiwayatPencarianSerializer
    pagination_class = RiwayatPagination

    def get_queryset(self):
        anonymous_id = self.request.query_params.get('anonymous_id')
        if not anonymous_id:
            return RiwayatPencarian.objects.none()
        return (RiwayatPencarian.objects.filter(anonymous_id=anonymous_id)
                .prefetch_related("rekomendasi__crop", "rekomendasi__lahan_tanam"))


class RiwayatDeleteView(DestroyAPIView):
    serializer_class = RiwayatPencarianSerializer

    def get_queryset(self):
        return RiwayatPencarian.objects.filter(anonymous_id=self.request.query_params.get('anonymous_id'))


@api_view(["GET"])
def riwayat_detail(request, pk):
    """Bentuk sama dengan objek `recommendation` pada hasil analisis."""
    aid, err = _wajib_anonymous_id(request)
    if err:
        return err
    r = get_object_or_404(RiwayatPencarian, pk=pk, anonymous_id=aid)
    return Response(riwayat_sebagai_hasil(r))


# ------------------------------------------------------------ monitoring
JEDA_PANTAU_MANUAL = timedelta(hours=6)


@api_view(["GET", "POST"])
def lahan_list(request):
    if request.method == "POST":
        s = LahanTanamCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        rek = s.validated_data.get("rekomendasi")
        if rek:
            ada = LahanTanam.objects.filter(rekomendasi=rek, status="aktif").first()
            if ada:
                return galat("Tanaman ini sudah tercatat sedang ditanam.", 409, lahan_id=ada.id)
        lahan = LahanTanam.objects.create(**s.validated_data)
        jobs.kirim("pantau_lahan", lahan.id)
        return Response(LahanTanamSerializer(lahan).data, status=201)

    aid, err = _wajib_anonymous_id(request)
    if err:
        return err
    qs = LahanTanam.objects.filter(anonymous_id=aid).select_related("crop", "rekomendasi")
    if request.query_params.get("status"):
        qs = qs.filter(status=request.query_params["status"])
    return Response(LahanTanamSerializer(qs, many=True).data)


@api_view(["GET", "PATCH", "DELETE"])
def lahan_detail(request, pk):
    aid, err = _wajib_anonymous_id(request)
    if err:
        return err
    lahan = get_object_or_404(LahanTanam, pk=pk, anonymous_id=aid)

    if request.method == "DELETE":
        lahan.delete()
        return Response(status=204)
    if request.method == "PATCH":
        s = LahanTanamSerializer(lahan, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()

    body = LahanTanamSerializer(lahan).data
    body["observasi"] = ObservasiNdviSerializer(lahan.observasi.all(), many=True).data
    try:
        body["cuaca"] = cuaca.get_prakiraan(lahan.lat, lahan.lon)
    except SumberDataGagal:
        body["cuaca"] = None
    return Response(body)


@api_view(["POST"])
def lahan_pantau(request, pk):
    aid, err = _wajib_anonymous_id(request)
    if err:
        return err
    lahan = get_object_or_404(LahanTanam, pk=pk, anonymous_id=aid)
    if lahan.terakhir_dipantau and timezone.now() - lahan.terakhir_dipantau < JEDA_PANTAU_MANUAL:
        bisa = timezone.localtime(lahan.terakhir_dipantau + JEDA_PANTAU_MANUAL)
        return galat(f"Data lahan baru saja diperbarui. Bisa diperbarui lagi pukul {bisa:%H.%M}.",
                     429, bisa_lagi_pada=bisa.isoformat())
    jobs.kirim("pantau_lahan", lahan.id)
    return Response({"status": "diproses"}, status=202)


# ------------------------------------------------------------ feedback & usability
@api_view(["POST"])
def feedback(request):
    s = FeedbackSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    s.save()
    return Response(s.data, status=201)


@api_view(["POST"])
@throttle_classes([UsabilityThrottle])
def log_usability(request):
    """Menerima satu event atau list event (batch)."""
    many = isinstance(request.data, list)
    s = UsabilityEventSerializer(data=request.data, many=many)
    s.is_valid(raise_exception=True)
    s.save()
    return Response({"diterima": len(request.data) if many else 1}, status=201)
