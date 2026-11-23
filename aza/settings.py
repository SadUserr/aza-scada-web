"""Configuración del Sistema Web de Monitoreo y Trazabilidad del Trefilado (AZA)."""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
_TESTING = "test" in sys.argv
DEBUG = os.getenv("DJANGO_DEBUG", "0") == "1"

# Secretos solo por variables de entorno (informe 7.3). En desarrollo se usa una clave local.
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY") or ("dev-insegura-no-usar-en-produccion" if (DEBUG or _TESTING) else None)
if not SECRET_KEY:
    raise RuntimeError("Define DJANGO_SECRET_KEY cuando DJANGO_DEBUG=0")
ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
_render_host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
if _render_host and _render_host not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_render_host)

_csrf_env = os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "")
if _csrf_env:
    CSRF_TRUSTED_ORIGINS = [u.strip() for u in _csrf_env.split(",") if u.strip()]
elif not DEBUG:
    CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in ALLOWED_HOSTS if h not in ("localhost", "127.0.0.1", "*")]

INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "cuentas", "trazabilidad",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "cuentas.middleware.CambioObligatorioMiddleware",   # CU02
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
if not DEBUG and not _TESTING:                        # sirve /static en el despliegue (Render)
    try:
        import whitenoise  # noqa: F401
        MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
    except ImportError:
        pass
ROOT_URLCONF = "aza.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "aza.wsgi.application"

# Base de datos: PostgreSQL si hay DB_NAME o DATABASE_URL (informe 6.1); SQLite para desarrollo rápido.
if os.getenv("DB_NAME"):
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["DB_NAME"], "USER": os.getenv("DB_USER", ""),
        "PASSWORD": os.getenv("DB_PASSWORD", ""), "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"sslmode": os.getenv("DB_SSLMODE", "prefer")},
    }}
elif os.getenv("DATABASE_URL"):
    from urllib.parse import unquote, urlparse
    _u = urlparse(os.environ["DATABASE_URL"])
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _u.path.lstrip("/"),
        "USER": unquote(_u.username or ""),
        "PASSWORD": unquote(_u.password or ""),
        "HOST": _u.hostname or "localhost",
        "PORT": str(_u.port or 5432),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"sslmode": os.getenv("DB_SSLMODE", "require")},
    }}
else:
    # SQLite solo para desarrollo: un único escritor a la vez. La prueba PR-02 mostró bloqueos con varios
    # procesos; por eso producción usa PostgreSQL. timeout + IMMEDIATE reducen esos bloqueos en desarrollo.
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3",
                             "OPTIONS": {"timeout": 20, "transaction_mode": "IMMEDIATE"}}}

AUTH_USER_MODEL = "cuentas.Usuario"
PASSWORD_HASHERS = ["cuentas.hashers.PBKDF2600k"]            # PBKDF2-HMAC-SHA256, 600.000 it. (6.4)
LOGIN_URL = "/login/"

LANGUAGE_CODE = "es-cl"
TIME_ZONE = "America/Santiago"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"                  # collectstatic (despliegue)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Sesión con expiración por inactividad (CU01 A5): 30 min sin actividad.
SESSION_COOKIE_AGE = int(os.getenv("SESSION_MINUTES", "30")) * 60
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

# Políticas definidas en el informe (7.1)
MAX_INTENTOS_FALLIDOS = 5
MINUTOS_BLOQUEO = 15
LARGO_MIN_PASSWORD = 12
API_LIMITE_POR_MINUTO = int(os.getenv("API_LIMITE_POR_MINUTO", "120"))   # límite por IP a la API (7.2)
API_MAX_BYTES = 10_000
TRUSTED_PROXY_HOPS = int(os.getenv("TRUSTED_PROXY_HOPS", "1" if _render_host else "0"))

# Registro de eventos de seguridad (7.2, OWASP A09): logins, bloqueos, tokens inválidos y acciones
# del Administrador. Nunca se registran contraseñas ni tokens en claro.
LOG_DIR = Path(os.getenv("AZA_LOG_DIR", BASE_DIR / "logs"))
LOG_DIR.mkdir(exist_ok=True)
LOGGING = {
    "version": 1, "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {
        "consola": {"class": "logging.StreamHandler", "formatter": "std"},
        "archivo": {"class": "logging.handlers.RotatingFileHandler", "formatter": "std",
                    "filename": LOG_DIR / "seguridad.log", "maxBytes": 1_000_000, "backupCount": 5,
                    "encoding": "utf-8"},
    },
    "loggers": {
        "aza.seguridad": {"handlers": ["consola", "archivo"], "level": "INFO", "propagate": False},
        "django.security": {"handlers": ["consola", "archivo"], "level": "WARNING", "propagate": False},
    },
}

if not DEBUG and not _TESTING:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
