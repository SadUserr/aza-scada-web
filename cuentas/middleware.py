from django.shortcuts import redirect

LIBRES = ("/cambiar-password/", "/logout/", "/login/", "/recuperar/", "/static/")


class CambioObligatorioMiddleware:
    """CU02: mientras la cuenta tenga contraseña temporal no puede usar otras funciones."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        u = request.user
        if u.is_authenticated and getattr(u, "cambio_obligatorio", False) \
                and not request.path.startswith(LIBRES):
            return redirect("cambiar_password")
        return self.get_response(request)
