from functools import wraps
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden
from django.shortcuts import render


def rol_requerido(*roles):
    """Verificación de rol en el servidor en cada vista (7.1): sin sesión -> login, rol incorrecto -> 403."""
    def deco(view):
        @wraps(view)
        def wrapper(request, *a, **kw):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if request.user.rol_nombre not in roles:
                return render(request, "403.html", status=403)
            return view(request, *a, **kw)
        return wrapper
    return deco
