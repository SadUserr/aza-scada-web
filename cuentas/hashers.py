from django.contrib.auth.hashers import PBKDF2PasswordHasher


class PBKDF2600k(PBKDF2PasswordHasher):
    """PBKDF2-HMAC-SHA256 con sal aleatoria y 600.000 iteraciones (informe 6.4)."""
    iterations = 600_000
