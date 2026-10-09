class SumberDataGagal(Exception):
    """API eksternal tidak bisa diakses / mengembalikan error."""


class DataTidakLengkap(Exception):
    """Data wajib tidak tersedia dari sumber mana pun.

    `butuh_input` memberi tahu FE field apa yang bisa diisi pengguna
    (mis. lewat form hasil uji tanah) supaya analisis tetap bisa jalan.
    """

    def __init__(self, pesan, butuh_input=None):
        super().__init__(pesan)
        self.pesan = pesan
        self.butuh_input = butuh_input or []


class PrediksiGagal(Exception):
    pass
