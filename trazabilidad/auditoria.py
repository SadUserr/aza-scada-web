"""Registro centralizado de auditoría de acciones de usuario en todo el sistema."""
from typing import Optional


def _client_ip(request) -> str:
    if request is None:
        return ""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()[:45]
    return str(request.META.get("REMOTE_ADDR", ""))[:45]


def registrar_auditoria(
    modulo: str,
    accion: str,
    detalle: str = "",
    *,
    request=None,
    usuario=None,
    usuario_nombre: Optional[str] = None,
    rol_nombre: Optional[str] = None,
) -> None:
    """Persiste un evento de auditoría indicando exactamente qué usuario ejecutó la acción."""
    from .models import RegistroAuditoria

    u = usuario
    if u is None and request is not None and getattr(request, "user", None) is not None:
        if request.user.is_authenticated:
            u = request.user

    nombre = usuario_nombre or (u.username if u is not None else "Sistema / Anónimo")
    rol = rol_nombre if rol_nombre is not None else (getattr(u, "rol_nombre", "") if u is not None else "")
    ip = _client_ip(request)

    RegistroAuditoria.objects.create(
        usuario=u,
        usuario_nombre=str(nombre)[:150],
        rol_nombre=str(rol)[:50],
        modulo=modulo[:40],
        accion=accion[:80],
        detalle=detalle,
        ip=ip,
    )
