from django.urls import path

from . import views

urlpatterns = [
    # rekomendasi
    path('recommend/', views.recommend),
    path('analisis/', views.analisis_mulai),
    path('analisis/<uuid:job_id>/', views.analisis_status),
    path('rekomendasi/<int:rekomendasi_id>/detail/', views.detail_tanaman),
    path('simulasi/kapur/', views.simulasi_pengapuran),

    # cuaca & ekonomi
    path('cuaca/prakiraan/', views.prakiraan_cuaca),
    path('ekonomi/<slug:slug>/', views.ekonomi_tanaman),

    # riwayat
    path('riwayat/', views.RiwayatListView.as_view()),
    path('riwayat/<int:pk>/', views.RiwayatDeleteView.as_view()),
    path('riwayat/<int:pk>/detail/', views.riwayat_detail),

    # monitoring pasca-tanam
    path('lahan/', views.lahan_list),
    path('lahan/<int:pk>/', views.lahan_detail),
    path('lahan/<int:pk>/pantau/', views.lahan_pantau),

    # feedback & usability
    path('feedback/', views.feedback),
    path('usability/log/', views.log_usability),
]
