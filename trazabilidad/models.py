"""Entidades del modelo de datos del informe (apartado 6.2) – ROL y USUARIO viven en `cuentas`."""
import hashlib
import secrets
from datetime import time

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Receta(models.Model):
    """Tabla RECETA (6.2.3): producto (código letra, espesor y material) y tolerancias angulares."""
    codigo_letra = models.CharField("código / letra", max_length=6, default="A")
    nombre = models.CharField(max_length=100, unique=True)
    espesor_mm = models.FloatField("espesor (mm)")
    material = models.CharField(max_length=50)
    min_tol = models.FloatField("tolerancia mínima (°)")
    max_tol = models.FloatField("tolerancia máxima (°)")
    activo = models.BooleanField(default=True)      # se desactiva, nunca se borra (CU11 A2)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(espesor_mm__gt=0), name="ck_receta_espesor"),
            models.CheckConstraint(condition=Q(min_tol__gte=0, max_tol__lte=180, min_tol__lt=models.F("max_tol")),
                                   name="ck_receta_tolerancias"),
        ]

    def clean(self):
        self.codigo_letra = (self.codigo_letra or "").strip().upper()
        if not self.codigo_letra:
            raise ValidationError("El código/letra de receta es obligatorio (ej. A, B, TF6).")
        if self.espesor_mm is not None and self.espesor_mm <= 0:
            raise ValidationError("El espesor debe ser mayor que 0 mm.")
        if self.min_tol is None or self.max_tol is None:
            return
        if not (0 <= self.min_tol <= 180 and 0 <= self.max_tol <= 180):
            raise ValidationError("Las tolerancias deben estar entre 0° y 180°.")
        if self.min_tol >= self.max_tol:
            raise ValidationError("La tolerancia mínima debe ser menor que la máxima.")

    def save(self, *args, **kwargs):
        self.codigo_letra = (self.codigo_letra or "A").strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"[{self.codigo_letra}] {self.nombre} ({self.min_tol}°–{self.max_tol}°)"


class Lote(models.Model):
    """Tabla LOTE (6.2.4): todo lote requiere receta asociada y registra operador de inicio y término."""
    codigo = models.CharField(max_length=50, unique=True)
    receta = models.ForeignKey(Receta, on_delete=models.PROTECT, related_name="lotes")
    operador_inicio = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="lotes_iniciados"
    )
    operador_activo = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="lotes_activos"
    )
    operador_fin = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="lotes_finalizados"
    )
    fecha_inicio = models.DateTimeField(default=timezone.now)
    fecha_fin = models.DateTimeField(null=True, blank=True)
    cantidad = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(fecha_fin__isnull=True) | Q(fecha_fin__gte=models.F("fecha_inicio")),
                                              name="ck_lote_fechas")]

    @classmethod
    def generar_codigo(cls, receta, fecha=None) -> str:
        """Genera código único con letra de receta, fecha AAAAMMDD y correlativo: ej. A-20261116-01."""
        letra = (getattr(receta, "codigo_letra", "") or "A").strip().upper()
        dia = timezone.localdate(fecha) if fecha else timezone.localdate()
        prefijo = f"{letra}-{dia:%Y%m%d}-"
        n = cls.objects.filter(codigo__startswith=prefijo).count() + 1
        while cls.objects.filter(codigo=f"{prefijo}{n:02d}").exists():
            n += 1
        return f"{prefijo}{n:02d}"

    @property
    def abierto(self):
        return self.fecha_fin is None

    def __str__(self):
        return self.codigo


class EstadoInspeccion(models.Model):
    """Catálogo ESTADO_INSPECCION (6.2.9): Aprobado, Rechazado, Sin Receta (datos semilla en la migración 0002)."""
    nombre = models.CharField(max_length=20, unique=True)

    def __str__(self):
        return self.nombre


class Turno(models.Model):
    """Catálogo TURNO (6.2.10). Los rangos horarios son un supuesto a validar con la contraparte."""
    nombre = models.CharField(max_length=20, unique=True)
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()

    def incluye(self, h: time) -> bool:
        if self.hora_inicio < self.hora_fin:
            return self.hora_inicio <= h < self.hora_fin
        return h >= self.hora_inicio or h < self.hora_fin      # turno que cruza medianoche

    @classmethod
    def para(cls, dt):
        h = timezone.localtime(dt).time()
        return next((t for t in cls.objects.all() if t.incluye(h)), None)

    def __str__(self):
        return f"{self.nombre} ({self.hora_inicio:%H:%M}–{self.hora_fin:%H:%M})"


class RegistroInspeccion(models.Model):
    """Tabla REGISTRO_INSPECCION (6.2.5). `metricas` guarda el metricas.json de la ráfaga (JSONB en PostgreSQL)."""
    APROBADO, RECHAZADO, SIN_RECETA = "Aprobado", "Rechazado", "Sin Receta"
    lote = models.ForeignKey(Lote, on_delete=models.PROTECT, related_name="inspecciones")
    id_batch = models.CharField(max_length=50)
    fecha = models.DateTimeField(default=timezone.now)
    angulo = models.FloatField()
    receta = models.ForeignKey(Receta, null=True, blank=True, on_delete=models.PROTECT, related_name="inspecciones")
    limite_min = models.FloatField(null=True, blank=True)    # copia de los límites usados al evaluar
    limite_max = models.FloatField(null=True, blank=True)
    estado = models.ForeignKey(EstadoInspeccion, on_delete=models.PROTECT, related_name="inspecciones")
    turno = models.ForeignKey(Turno, null=True, blank=True, on_delete=models.PROTECT, related_name="inspecciones")
    operador = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    carpeta = models.CharField(max_length=255, blank=True, default="")   # ruta a las imágenes de la ráfaga
    metricas = models.JSONField(null=True, blank=True)                   # dato semiestructurado (5.6)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["lote", "id_batch"], name="uq_inspeccion_lote_batch"),
            models.CheckConstraint(condition=Q(angulo__gte=0, angulo__lte=180), name="ck_angulo_0_180"),
        ]
        indexes = [
            models.Index(fields=["fecha"], name="idx_inspeccion_fecha"),
            models.Index(fields=["lote", "fecha"], name="idx_inspeccion_lote"),
            models.Index(fields=["estado"], name="idx_inspeccion_estado"),
        ]
        ordering = ["-fecha", "-id"]

    @property
    def codigo(self):
        return f"INS-{self.pk:04d}"

    @property
    def estado_nombre(self):
        return self.estado.nombre if self.estado_id else ""


class Observacion(models.Model):
    """Tabla OBSERVACION (6.2.6)."""
    TIPOS = [("nota", "Nota"), ("alerta", "Alerta"), ("correccion", "Corrección")]
    registro = models.ForeignKey(RegistroInspeccion, on_delete=models.PROTECT, related_name="observaciones")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(auto_now_add=True)
    tipo = models.CharField(max_length=30, choices=TIPOS)
    descripcion = models.TextField(max_length=500)

    class Meta:
        ordering = ["fecha"]


class Alarma(models.Model):
    """Tabla ALARMA (6.2.7). `solicitud_recuperacion` (CU16) solo la ve el Administrador."""
    CRITICA, INFORMATIVA = "critica", "informativa"
    RECUPERACION = "solicitud_recuperacion"
    TIPOS = ["rechazado", "sin_receta", "dato_invalido", "token_invalido", RECUPERACION]
    fecha = models.DateTimeField(default=timezone.now)
    nivel = models.CharField(max_length=15, choices=[(CRITICA, "Crítica"), (INFORMATIVA, "Informativa")])
    tipo = models.CharField(max_length=40, choices=[(t, t) for t in TIPOS])
    descripcion = models.TextField()
    registro = models.ForeignKey(RegistroInspeccion, null=True, blank=True, on_delete=models.PROTECT, related_name="alarmas")
    lote = models.ForeignKey(Lote, null=True, blank=True, on_delete=models.PROTECT, related_name="alarmas")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                related_name="solicitudes")
    atendida = models.BooleanField(default=False)

    class Meta:
        ordering = ["-fecha", "-id"]

    @classmethod
    def de_proceso(cls):
        """Alarmas que ve el Operador (excluye solicitudes de recuperación de contraseña)."""
        return cls.objects.exclude(tipo=cls.RECUPERACION)


class TokenApi(models.Model):
    """Tabla TOKEN_API (6.2.8)."""
    nombre = models.CharField(max_length=100)
    token_hash = models.CharField(max_length=255, unique=True)   # el token en claro se muestra una sola vez
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    @staticmethod
    def hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()   # token aleatorio de 256 bits: SHA-256 basta

    @classmethod
    def crear(cls, nombre, creado_por):
        token = secrets.token_urlsafe(32)
        obj = cls.objects.create(nombre=nombre, token_hash=cls.hash(token), creado_por=creado_por)
        return obj, token


class RegistroAuditoria(models.Model):
    """Bitácora inmutable de acciones realizadas por cada usuario en el sistema."""
    fecha = models.DateTimeField(default=timezone.now, db_index=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="auditorias"
    )
    usuario_nombre = models.CharField(max_length=150)
    rol_nombre = models.CharField(max_length=50, blank=True, default="")
    modulo = models.CharField(max_length=40, db_index=True)
    accion = models.CharField(max_length=80)
    detalle = models.TextField(blank=True, default="")
    ip = models.CharField(max_length=45, blank=True, default="")

    class Meta:
        ordering = ["-fecha", "-id"]
        indexes = [
            models.Index(fields=["modulo", "fecha"], name="idx_audit_modulo_fecha"),
            models.Index(fields=["usuario", "fecha"], name="idx_audit_usuario_fecha"),
        ]

    def __str__(self):
        return f"{self.fecha:%Y-%m-%d %H:%M} · {self.usuario_nombre} · {self.accion}"
