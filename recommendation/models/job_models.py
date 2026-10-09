import uuid

from django.db import models


class AnalisisJob(models.Model):
    STATUS_CHOICES = [
        ("antri", "Antri"),
        ("berjalan", "Berjalan"),
        ("selesai", "Selesai"),
        ("perlu_input", "Perlu input tambahan"),
        ("gagal", "Gagal"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    anonymous_id = models.CharField(max_length=100, db_index=True)
    input = models.JSONField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="antri")
    # status per sumber data: {"tanah": "selesai", "iklim": "berjalan", ...}
    progres = models.JSONField(default=dict)
    hasil = models.JSONField(null=True, blank=True)
    error = models.JSONField(null=True, blank=True)
    dibuat_pada = models.DateTimeField(auto_now_add=True)
    diperbarui_pada = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-dibuat_pada"]
