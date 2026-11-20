import logging
from datetime import timedelta
from django.conf import settings
from django.core.cache import cache
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import Usuario
from .politica import validar_politica
from trazabilidad.auditoria import registrar_auditoria

log = logging.getLogger("aza.seguridad")
MSG_RECUPERACION = ("Si la cuenta existe y está activa, el administrador recibirá tu solicitud y te entregará "
                    "una contraseña temporal.")


def _ip(request):
    return request.META.get("REMOTE_ADDR", "?")

MSG_GENERICO = "Usuario o contraseña incorrectos. Verifica tus datos e intenta nuevamente."
HOME = {"Operador": "op_inspeccion", "Supervisor": "sup_dashboard", "Administrador": "adm_usuarios"}


def home(request):
    if not request.user.is_authenticated:
        return redirect("login")
    return redirect(HOME.get(request.user.rol_nombre, "login"))


@require_http_methods(["GET", "POST"])
def login_view(request):
    """CU01 – Autenticarse (flujo normal y alternativos A1–A4)."""
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        if not username or not password:                                   # paso 3
            return render(request, "login.html", {"error": "Completa usuario y contraseña."})
        user = Usuario.objects.filter(username=username).first()
        if user and user.bloqueado:                                        # A4
            log.warning("login rechazado: cuenta bloqueada (%s) desde %s", username, _ip(request))
            registrar_auditoria("Autenticación", "Login bloqueado",
                                f"Intento rechazado: cuenta '{username}' bloqueada temporalmente",
                                request=request, usuario=user, usuario_nombre=user.username)
            return render(request, "login.html", {"error": "Acceso bloqueado temporalmente. Intenta más tarde."})
        ok = bool(user and user.check_password(password))                  # paso 4 (hash con sal)
        if not user:
            Usuario().set_password(password)                               # iguala tiempos (anti-enumeración)
        if not ok:                                                         # A1: mensaje genérico
            if user:
                user.intentos_fallidos += 1
                if user.intentos_fallidos >= settings.MAX_INTENTOS_FALLIDOS:
                    user.bloqueado_hasta = timezone.now() + timedelta(minutes=settings.MINUTOS_BLOQUEO)
                    user.intentos_fallidos = 0
                    log.warning("cuenta %s bloqueada %s min por intentos fallidos", username, settings.MINUTOS_BLOQUEO)
                    registrar_auditoria("Autenticación", "Bloqueo por intentos fallidos",
                                        f"Cuenta '{username}' bloqueada {settings.MINUTOS_BLOQUEO} min",
                                        request=request, usuario=user, usuario_nombre=user.username)
                user.save(update_fields=["intentos_fallidos", "bloqueado_hasta"])
            log.warning("login fallido para '%s' desde %s", username[:100], _ip(request))   # nunca la contraseña
            registrar_auditoria("Autenticación", "Intento de ingreso fallido",
                                f"Credenciales inválidas para usuario '{username[:100]}'",
                                request=request, usuario=user,
                                usuario_nombre=user.username if user else username[:100])
            return render(request, "login.html", {"error": MSG_GENERICO})
        if not user.is_active:                                             # A2 (paso 5)
            registrar_auditoria("Autenticación", "Ingreso denegado (cuenta inactiva)",
                                f"Cuenta '{user.username}' desactivada",
                                request=request, usuario=user, usuario_nombre=user.username)
            return render(request, "login.html", {"error": "Cuenta desactivada. Contacta al administrador."})
        user.intentos_fallidos, user.bloqueado_hasta, user.ultimo_acceso = 0, None, timezone.now()
        user.save(update_fields=["intentos_fallidos", "bloqueado_hasta", "ultimo_acceso"])
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")   # paso 6
        log.info("login correcto: %s (%s) desde %s", user.username, user.rol_nombre, _ip(request))
        registrar_auditoria("Autenticación", "Inicio de sesión",
                            f"Acceso exitoso como {user.rol_nombre}",
                            request=request, usuario=user)
        if user.cambio_obligatorio:                                        # A3 -> CU02
            return redirect("cambiar_password")
        return redirect("home")                                            # paso 7: según rol
    return render(request, "login.html")


@require_http_methods(["GET", "POST"])
def recuperar(request):
    """CU16 – Recuperar contraseña. Mensaje siempre igual (no revela qué cuentas existen); la solicitud queda
    registrada como alarma visible solo para el Administrador, que asigna una contraseña temporal (CU17)."""
    from trazabilidad.models import Alarma                                 # import local: evita ciclo entre apps
    ctx = {}
    if request.method == "POST":
        username = request.POST.get("username", "").strip()[:150]
        clave = f"recuperar-{_ip(request)}"
        cache.add(clave, 0, 3600)
        if cache.incr(clave) <= 5 and username:                            # máx. 5 solicitudes por hora y origen
            u = Usuario.objects.filter(username=username, is_active=True).first()
            if u and not Alarma.objects.filter(tipo=Alarma.RECUPERACION, usuario=u, atendida=False).exists():
                Alarma.objects.create(nivel=Alarma.INFORMATIVA, tipo=Alarma.RECUPERACION, usuario=u,
                                      descripcion=f"Solicitud de recuperación de contraseña de {u.username}")
                log.info("solicitud de recuperación registrada para %s", u.username)
                registrar_auditoria("Autenticación", "Solicitud de recuperación",
                                    f"Usuario '{u.username}' solicitó contraseña temporal",
                                    request=request, usuario=u)
        ctx["enviado"] = MSG_RECUPERACION
    return render(request, "recuperar.html", ctx)


@require_http_methods(["POST", "GET"])
def logout_view(request):
    if request.user.is_authenticated:
        registrar_auditoria("Autenticación", "Cierre de sesión", "Salida del sistema", request=request, usuario=request.user)
    logout(request)
    return redirect("login")


@login_required
@require_http_methods(["GET", "POST"])
def cambiar_password(request):
    """CU02 – Cambiar contraseña inicial."""
    ctx = {}
    if request.method == "POST":
        temporal, nueva, conf = (request.POST.get(k, "") for k in ("temporal", "nueva", "confirmacion"))
        u = request.user
        if not u.check_password(temporal):                                 # A3
            ctx["error"] = "La contraseña temporal es incorrecta."
        elif nueva != conf:                                                # A2
            ctx["error"] = "La confirmación no coincide con la nueva contraseña."
        else:
            fallos = validar_politica(nueva, temporal)
            if fallos:                                                     # A1
                ctx["fallos"] = fallos
            else:
                u.set_password(nueva)
                u.cambio_obligatorio = False
                u.save(update_fields=["password", "cambio_obligatorio"])
                update_session_auth_hash(request, u)
                registrar_auditoria("Autenticación", "Cambio de contraseña",
                                    "Actualización obligatoria de contraseña inicial completada",
                                    request=request, usuario=u)
                messages.success(request, "Contraseña actualizada.")
                return redirect("home")
    return render(request, "cambiar_password.html", ctx)
