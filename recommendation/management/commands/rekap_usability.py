"""Rekap hasil usability test dari UsabilityEvent.

    python manage.py rekap_usability                    # semua event mode_tes=true
    python manage.py rekap_usability --sejak 2026-10-08 --csv rekap.csv
    python manage.py rekap_usability --semua            # termasuk pemakaian biasa

Format event dari FE (lib/usability.ts):
    {"sesi_id", "event", "tugas", "peserta", "mode_tes", "halaman", "waktu",
     "data": {...}}
- tugas_selesai : data = {berhasil: true/false/null, durasi_detik, dilewati}
- sus           : data = {jawaban: [10 angka 1-5], skor}

Aturan hitung:
- Task success rate = berhasil / (total yang berhasil-nya tercatat). Tugas yang
  dilewati dihitung GAGAL. berhasil=null dan tidak dilewati -> tidak dihitung
  (dilaporkan terpisah sebagai "tak tercatat").
- Kalau satu peserta mengulang tugas yang sama, yang dipakai event TERAKHIR.
- SUS dihitung ulang dari `jawaban`; `skor` dari FE hanya dipakai kalau
  jawaban tidak lengkap. Satu peserta = satu skor (event SUS terakhir).
"""
import csv
from statistics import mean, median

from django.core.management.base import BaseCommand

from recommendation.models.monitoring_models import UsabilityEvent


def skor_sus(jawaban):
    """Butir ganjil: x-1, butir genap: 5-x, total x 2,5 -> 0..100."""
    try:
        nilai = [int(x) for x in jawaban]
    except (TypeError, ValueError):
        return None
    if len(nilai) != 10 or any(not 1 <= x <= 5 for x in nilai):
        return None
    return sum((x - 1) if i % 2 == 0 else (5 - x) for i, x in enumerate(nilai)) * 2.5


def _kunci_peserta(e):
    return e.peserta or f"sesi:{e.sesi_id}"


def _data(e):
    return e.data or e.metadata or {}


def _status(e):
    d = _data(e)
    if d.get("dilewati"):
        return False
    b = d.get("berhasil", e.berhasil)
    return b if isinstance(b, bool) else None


def _durasi(e):
    d = _data(e).get("durasi_detik")
    if isinstance(d, (int, float)):
        return float(d)
    return e.durasi_ms / 1000 if e.durasi_ms is not None else None


def hitung(qs):
    # event terakhir per (peserta, tugas)
    terakhir = {}
    for e in qs.filter(event="tugas_selesai").order_by("waktu_klien", "dibuat_pada"):
        terakhir[(_kunci_peserta(e), e.tugas or "-")] = e

    per_tugas, per_peserta = {}, {}
    for (peserta, tugas), e in terakhir.items():
        st, dur = _status(e), _durasi(e)
        for wadah, kunci in ((per_tugas, tugas), (per_peserta, peserta)):
            r = wadah.setdefault(kunci, {"berhasil": 0, "dihitung": 0, "tak_tercatat": 0, "durasi": []})
            if st is None:
                r["tak_tercatat"] += 1
            else:
                r["dihitung"] += 1
                r["berhasil"] += int(st)
            if dur is not None and st is True:   # waktu hanya untuk tugas yang berhasil
                r["durasi"].append(dur)

    sus = {}
    for e in qs.filter(event="sus").order_by("waktu_klien", "dibuat_pada"):
        d = _data(e)
        s = skor_sus(d.get("jawaban"))
        if s is None and isinstance(d.get("skor"), (int, float)):
            s = float(d["skor"])
        if s is not None:
            sus[_kunci_peserta(e)] = s
    return per_tugas, per_peserta, sus


def _fmt(x, f="{:.1f}"):
    return f.format(x) if x is not None else "-"


class Command(BaseCommand):
    help = "Hitung task success rate, waktu pengerjaan, dan skor SUS (per tugas & per peserta)."

    def add_arguments(self, p):
        p.add_argument("--sejak", default=None, help="YYYY-MM-DD")
        p.add_argument("--semua", action="store_true", help="ikutkan event di luar mode tes")
        p.add_argument("--csv", dest="csv_path", default=None, help="simpan rekap per peserta ke file CSV")

    def handle(self, *args, sejak, semua, csv_path=None, **kw):
        qs = UsabilityEvent.objects.all()
        if not semua:
            qs = qs.filter(mode_tes=True)
        if sejak:
            qs = qs.filter(dibuat_pada__date__gte=sejak)
        per_tugas, per_peserta, sus = hitung(qs)

        out = self.stdout.write
        out("PER TUGAS")
        out(f"{'tugas':12} {'berhasil':>9} {'sukses':>7} {'median s':>9} {'rata s':>7} {'tak tercatat':>13}")
        for t, r in sorted(per_tugas.items()):
            rate = r["berhasil"] / r["dihitung"] * 100 if r["dihitung"] else None
            out(f"{t:12} {r['berhasil']:>4}/{r['dihitung']:<4} {_fmt(rate, '{:.0f}%'):>7} "
                f"{_fmt(median(r['durasi']) if r['durasi'] else None):>9} "
                f"{_fmt(mean(r['durasi']) if r['durasi'] else None):>7} {r['tak_tercatat']:>13}")

        out("\nPER PESERTA")
        out(f"{'peserta':16} {'berhasil':>9} {'sukses':>7} {'SUS':>6}")
        baris_csv = []
        for p in sorted(set(per_peserta) | set(sus)):
            r = per_peserta.get(p, {"berhasil": 0, "dihitung": 0, "durasi": []})
            rate = r["berhasil"] / r["dihitung"] * 100 if r["dihitung"] else None
            out(f"{p:16} {r['berhasil']:>4}/{r['dihitung']:<4} {_fmt(rate, '{:.0f}%'):>7} {_fmt(sus.get(p)):>6}")
            baris_csv.append({"peserta": p, "tugas_berhasil": r["berhasil"], "tugas_dihitung": r["dihitung"],
                              "success_rate_persen": None if rate is None else round(rate, 1),
                              "sus": sus.get(p)})

        total_b = sum(r["berhasil"] for r in per_tugas.values())
        total_d = sum(r["dihitung"] for r in per_tugas.values())
        out(f"\nTOTAL: task success {total_b}/{total_d}"
            + (f" ({total_b / total_d * 100:.0f}%)" if total_d else ""))
        out(f"SUS: n={len(sus)}" + (f", rata-rata {mean(sus.values()):.1f}, min {min(sus.values()):.1f}, "
                                    f"maks {max(sus.values()):.1f}" if sus else ", belum ada data"))

        if csv_path:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["peserta", "tugas_berhasil", "tugas_dihitung",
                                                  "success_rate_persen", "sus"])
                w.writeheader()
                w.writerows(baris_csv)
            out(f"CSV disimpan ke {csv_path}")
