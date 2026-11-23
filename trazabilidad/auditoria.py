"""Registro centralizado de auditoría de acciones de usuario en todo el sistema."""
from typing import Optional


def client_ip(request) -> str:
    """Devuelve la IP del cliente resistente a suplantación de X-Forwarded-For.

    - TRUSTED_PROXY_HOPS == 0: ignora X-Forwarded-For y usa REMOTE_ADDR.
    - TRUSTED_PROXY_HOPS >= 1: toma parts[-hops] desde la derecha (valor agregado por el proxy confiable).
    """
    if request is None:
        return ""
    from django.conf import settings
    hops = int(getattr(settings, "TRUSTED_PROXY_HOPS", 0) or 0)
    if hops > 0:
        xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops][:45]
    return str(request.META.get("REMOTE_ADDR", ""))[:45]


_client_ip = client_ip


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
