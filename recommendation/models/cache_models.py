from django.db import models


class DataCache(models.Model):
    """Cache data lingkungan per sel grid.

    Dipakai untuk:
    - mempercepat request (data statis tidak perlu ditarik ulang),
    - cadangan saat API eksternal down (data kedaluwarsa / sel tetangga),
    - hasil precompute (`manage.py precompute_statis`).
    """

    sumber = models.CharField(max_length=20)       # tanah | iklim | satelit | prakiraan
    kunci_sel = models.CharField(max_length=40)     # mis. "-6.2500_106.8000"
    lat = models.FloatField()
    lon = models.FloatField()
    payload = models.JSONField()
    diambil_pada = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["sumber", "kunci_sel"], name="unique_cache_sel")
        ]
        indexes = [models.Index(fields=["sumber", "lat", "lon"])]

    def __str__(self):
        return f"{self.sumber} {self.kunci_sel}"
