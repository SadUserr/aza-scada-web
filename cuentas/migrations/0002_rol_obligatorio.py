"""Alinea USUARIO con el informe (6.2.2): rol NOT NULL y nombre_completo VARCHAR(150) NOT NULL."""
import django.db.models.deletion
from django.db import migrations, models


def completar(apps, schema_editor):
    Rol = apps.get_model("cuentas", "Rol")
    Usuario = apps.get_model("cuentas", "Usuario")
    for n in ("Operador", "Supervisor", "Administrador"):
        Rol.objects.get_or_create(nombre=n)
    operador = Rol.objects.get(nombre="Operador")
    Usuario.objects.filter(rol__isnull=True).update(rol=operador)           # cuentas antiguas sin rol
    for u in Usuario.objects.filter(nombre_completo=""):
        u.nombre_completo = u.username
        u.save(update_fields=["nombre_completo"])


class Migration(migrations.Migration):
    dependencies = [("cuentas", "0001_initial")]

    operations = [
        migrations.RunPython(completar, migrations.RunPython.noop),
        migrations.AlterField("usuario", "rol", models.ForeignKey(
            on_delete=django.db.models.deletion.PROTECT, related_name="usuarios", to="cuentas.rol")),
        migrations.AlterField("usuario", "nombre_completo", models.CharField(max_length=150)),
    ]
