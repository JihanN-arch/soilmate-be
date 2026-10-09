import logging
import time

import requests
from django.conf import settings

from ..errors import SumberDataGagal

logger = logging.getLogger(__name__)

STATUS_LAYAK_ULANG = {429, 500, 502, 503, 504}
USER_AGENT = f"NUSA-CROP/1.1 ({getattr(settings, 'NUSACROP_SITE_URL', '')})"


def get_json(url, params, nama, timeout=15, percobaan=3, jeda_awal=1.0):
    """GET JSON dengan retry + exponential backoff (1 s, 2 s, ...).

    Melempar SumberDataGagal kalau semua percobaan gagal. TIDAK pernah
    mengembalikan data palsu.
    """
    terakhir = None
    for i in range(percobaan):
        try:
            resp = requests.get(url, params=params, timeout=timeout,
                                headers={"User-Agent": USER_AGENT})
            if resp.status_code in STATUS_LAYAK_ULANG:
                terakhir = f"HTTP {resp.status_code}"
            elif resp.status_code >= 400:
                # 4xx selain 429 tidak akan sembuh dengan retry
                raise SumberDataGagal(f"{nama}: HTTP {resp.status_code}")
            else:
                return resp.json()
        except SumberDataGagal:
            raise
        except (requests.Timeout, requests.ConnectionError) as e:
            terakhir = type(e).__name__
        except (requests.RequestException, ValueError) as e:
            raise SumberDataGagal(f"{nama}: {e}") from e

        if i < percobaan - 1:
            jeda = jeda_awal * (2 ** i)
            logger.warning("%s gagal (%s), percobaan %d/%d, ulang dalam %.0f s",
                           nama, terakhir, i + 1, percobaan, jeda)
            time.sleep(jeda)

    raise SumberDataGagal(f"{nama} tidak dapat diakses setelah {percobaan} percobaan ({terakhir})")
