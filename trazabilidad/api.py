import json
from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .services import ingestar


def _ip(request):
    return request.META.get("REMOTE_ADDR", "?")


@csrf_exempt
@require_POST
def inspecciones_api(request):
    """POST /api/inspecciones  – Authorization: Bearer <token>  – CU13 + CU15."""
    clave = f"api-rate-{_ip(request)}"                                      # límite de peticiones por origen
    cache.add(clave, 0, 60)
    if cache.incr(clave) > settings.API_LIMITE_POR_MINUTO:
        return JsonResponse({"error": "Demasiadas peticiones"}, status=429)
    if len(request.body) > settings.API_MAX_BYTES:
        return JsonResponse({"error": "Cuerpo demasiado grande"}, status=413)
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    try:
        payload = json.loads(request.body or b"null")
    except json.JSONDecodeError:
        payload = None
    status, body = ingestar(token, payload)
    return JsonResponse(body, status=status)
