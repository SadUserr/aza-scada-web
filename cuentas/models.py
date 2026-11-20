from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class Rol(models.Model):
    """Tabla ROL (6.2.1): Operador, Supervisor, Administrador."""
    OPERADOR, SUPERVISOR, ADMINISTRADOR = "Operador", "Supervisor", "Administrador"
    nombre = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.nombre


class Usuario(AbstractUser):
    """Tabla USUARIO (6.2.2). `is_active` cumple el rol del campo `activo`.
    La contraseña queda en `password` como hash PBKDF2 con sal (nunca en claro)."""
    first_name = None
    last_name = None
    nombre_completo = models.CharField(max_length=150)
    rol = models.ForeignKey(Rol, on_delete=models.PROTECT, related_name="usuarios")
    cambio_obligatorio = models.BooleanField(default=True)
    intentos_fallidos = models.PositiveIntegerField(default=0)
    bloqueado_hasta = models.DateTimeField(null=True, blank=True)
    ultimo_acceso = models.DateTimeField(null=True, blank=True)

    @property
    def rol_nombre(self):
        return self.rol.nombre if self.rol_id else ""

    @property
    def bloqueado(self):
        return bool(self.bloqueado_hasta and self.bloqueado_hasta > timezone.now())

    def __str__(self):
        return self.nombre_completo or self.username
