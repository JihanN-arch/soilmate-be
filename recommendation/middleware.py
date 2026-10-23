def tanpa_cache_api(get_response):
    """Respons /api/ tidak boleh disimpan browser/CDN: data lahan berubah dan berbeda per lahan."""
    def middleware(request):
        r = get_response(request)
        if request.path.startswith("/api/"):
            r.setdefault("Cache-Control", "no-store")
        return r
    return middleware
