"""Alinea el modelo con el informe EV2:
- RECETA: espesor_mm, material y `activo` (antes `activa`), con CHECK de tolerancias.
- Catálogos ESTADO_INSPECCION y TURNO (3FN) con sus datos semilla; REGISTRO_INSPECCION pasa a usar FK.
- REGISTRO_INSPECCION.metricas: JSON (JSONB en PostgreSQL) con el metricas.json de cada ráfaga.
- ALARMA: usuario_id y atendida para las solicitudes de recuperación de contraseña (CU16/CU17)."""
from datetime import time

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import F, Q
from django.utils import timezone

ESTADOS = ("Aprobado", "Rechazado", "Sin Receta")
TURNOS = (("Mañana", time(6), time(14)), ("Tarde", time(14), time(22)), ("Noche", time(22), time(6)))


def semillas_y_datos(apps, schema_editor):
    Estado = apps.get_model("trazabilidad", "EstadoInspeccion")
    Turno = apps.get_model("trazabilidad", "Turno")
    Registro = apps.get_model("trazabilidad", "RegistroInspeccion")
    for n in ESTADOS:
        Estado.objects.get_or_create(nombre=n)
    for n, ini, fin in TURNOS:
        Turno.objects.get_or_create(nombre=n, defaults={"hora_inicio": ini, "hora_fin": fin})
    estados = {e.nombre: e for e in Estado.objects.all()}
    turnos = list(Turno.objects.all())

    def turno_de(dt):
        h = timezone.localtime(dt).time()
        for t in turnos:
            dentro = (t.hora_inicio <= h < t.hora_fin) if t.hora_inicio < t.hora_fin else (h >= t.hora_inicio or h < t.hora_fin)
            if dentro:
                return t
        return None

    for r in Registro.objects.all():
        r.estado_ref = estados.get(r.estado) or estados["Sin Receta"]
        r.turno = turno_de(r.fecha)
        r.save(update_fields=["estado_ref", "turno"])


class Migration(migrations.Migration):
    dependencies = [
        ("trazabilidad", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # RECETA
        migrations.RenameField("receta", "activa", "activo"),
        migrations.AddField("receta", "espesor_mm", models.FloatField(default=6.0, verbose_name="espesor (mm)"),
                            preserve_default=False),
        migrations.AddField("receta", "material", models.CharField(default="Por definir", max_length=50),
                            preserve_default=False),
        migrations.AddConstraint("receta", models.CheckConstraint(condition=Q(espesor_mm__gt=0), name="ck_receta_espesor")),
        migrations.AddConstraint("receta", models.CheckConstraint(
            condition=Q(min_tol__gte=0, max_tol__lte=180, min_tol__lt=F("max_tol")), name="ck_receta_tolerancias")),
        migrations.AddConstraint("lote", models.CheckConstraint(
            condition=Q(fecha_fin__isnull=True) | Q(fecha_fin__gte=F("fecha_inicio")), name="ck_lote_fechas")),
        # Catálogos
        migrations.CreateModel("EstadoInspeccion", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("nombre", models.CharField(max_length=20, unique=True))]),
        migrations.CreateModel("Turno", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("nombre", models.CharField(max_length=20, unique=True)),
            ("hora_inicio", models.TimeField()), ("hora_fin", models.TimeField())]),
        migrations.AddField("registroinspeccion", "estado_ref", models.ForeignKey(
            null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="trazabilidad.estadoinspeccion")),
        migrations.AddField("registroinspeccion", "turno", models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="inspecciones",
            to="trazabilidad.turno")),
        migrations.AddField("registroinspeccion", "metricas", models.JSONField(blank=True, null=True)),
        migrations.RunPython(semillas_y_datos, migrations.RunPython.noop),
        migrations.RemoveIndex("registroinspeccion", "idx_inspeccion_estado"),
        migrations.RemoveField("registroinspeccion", "estado"),
        migrations.RenameField("registroinspeccion", "estado_ref", "estado"),
        migrations.AlterField("registroinspeccion", "estado", models.ForeignKey(
            on_delete=django.db.models.deletion.PROTECT, related_name="inspecciones", to="trazabilidad.estadoinspeccion")),
        migrations.AddIndex("registroinspeccion", models.Index(fields=["estado"], name="idx_inspeccion_estado")),
        migrations.AlterField("registroinspeccion", "operador", models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
        # ALARMA
        migrations.AddField("alarma", "usuario", models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="solicitudes",
            to=settings.AUTH_USER_MODEL)),
        migrations.AddField("alarma", "atendida", models.BooleanField(default=False)),
        migrations.AlterField("alarma", "tipo", models.CharField(max_length=40, choices=[
            ("rechazado", "rechazado"), ("sin_receta", "sin_receta"), ("dato_invalido", "dato_invalido"),
            ("token_invalido", "token_invalido"), ("solicitud_recuperacion", "solicitud_recuperacion")])),
    ]
