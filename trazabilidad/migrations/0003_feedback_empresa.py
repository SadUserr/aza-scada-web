"""Feedback empresarial Aceros AZA:
- Receta.codigo_letra para nomenclatura de lotes por receta + fecha.
- Lote.receta obligatorio (no existen lotes sin receta).
- Lote.operador_inicio, operador_activo y operador_fin.
- RegistroAuditoria para trazabilidad completa de acciones por usuario."""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


def limpiar_lotes_sin_receta(apps, schema_editor):
    Receta = apps.get_model("trazabilidad", "Receta")
    Lote = apps.get_model("trazabilidad", "Lote")
    Registro = apps.get_model("trazabilidad", "RegistroInspeccion")
    Alarma = apps.get_model("trazabilidad", "Alarma")
    Observacion = apps.get_model("trazabilidad", "Observacion")

    sin_receta_demo = Lote.objects.filter(codigo="LT-DEMO-SINRECETA")
    if sin_receta_demo.exists():
        regs = Registro.objects.filter(lote__in=sin_receta_demo)
        Alarma.objects.filter(registro__in=regs).delete()
        Observacion.objects.filter(registro__in=regs).delete()
        Alarma.objects.filter(lote__in=sin_receta_demo).delete()
        regs.delete()
        sin_receta_demo.delete()

    pendientes = Lote.objects.filter(receta__isnull=True)
    if pendientes.exists():
        rec = Receta.objects.first() or Receta.objects.create(
            codigo_letra="A", nombre="TF-6 mm", espesor_mm=6.0, material="SAE 1008", min_tol=12.0, max_tol=13.0
        )
        pendientes.update(receta=rec)


class Migration(migrations.Migration):
    dependencies = [
        ("trazabilidad", "0002_alinear_informe"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="receta",
            name="codigo_letra",
            field=models.CharField(default="A", max_length=6, verbose_name="código / letra"),
        ),
        migrations.AddField(
            model_name="lote",
            name="operador_inicio",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="lotes_iniciados", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="lote",
            name="operador_activo",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="lotes_activos", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="lote",
            name="operador_fin",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="lotes_finalizados", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(limpiar_lotes_sin_receta, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="lote",
            name="receta",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="lotes", to="trazabilidad.receta",
            ),
        ),
        migrations.CreateModel(
            name="RegistroAuditoria",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("fecha", models.DateTimeField(db_index=True, default=timezone.now)),
                ("usuario_nombre", models.CharField(max_length=150)),
                ("rol_nombre", models.CharField(blank=True, default="", max_length=50)),
                ("modulo", models.CharField(db_index=True, max_length=40)),
                ("accion", models.CharField(max_length=80)),
                ("detalle", models.TextField(blank=True, default="")),
                ("ip", models.CharField(blank=True, default="", max_length=45)),
                (
                    "usuario",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                        related_name="auditorias", to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-fecha", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="registroauditoria",
            index=models.Index(fields=["modulo", "fecha"], name="idx_audit_modulo_fecha"),
        ),
        migrations.AddIndex(
            model_name="registroauditoria",
            index=models.Index(fields=["usuario", "fecha"], name="idx_audit_usuario_fecha"),
        ),
    ]
