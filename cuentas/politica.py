import re
from django.conf import settings


def validar_politica(nueva, temporal=""):
    """Política de contraseñas (7.1): largo mínimo, mayúsculas, minúsculas, números y carácter especial,
    distinta de la temporal. Devuelve la lista de requisitos incumplidos (vacía si cumple)."""
    fallos = []
    if len(nueva) < settings.LARGO_MIN_PASSWORD:
        fallos.append(f"Mínimo {settings.LARGO_MIN_PASSWORD} caracteres")
    if not re.search(r"[A-Z]", nueva) or not re.search(r"[a-z]", nueva) or not re.search(r"\d", nueva):
        fallos.append("Debe combinar mayúsculas, minúsculas y números")
    if not re.search(r"[^A-Za-z0-9]", nueva):
        fallos.append("Debe incluir al menos un carácter especial (por ejemplo # $ % & *)")
    if temporal and nueva == temporal:
        fallos.append("Debe ser distinta de la contraseña temporal")
    return fallos
