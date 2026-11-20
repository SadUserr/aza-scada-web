"""Crea los 3 roles semilla y el administrador inicial desde variables de entorno (6.2.2).
No existe credencial por defecto: ADMIN_USER y ADMIN_INITIAL_PASSWORD son obligatorias."""
import os
from django.core.management.base import BaseCommand, CommandError
from cuentas.models import Rol, Usuario


class Command(BaseCommand):
    help = "Crea roles y administrador inicial (cambio obligatorio en el primer ingreso)."

    def handle(self, *a, **kw):
        for n in (Rol.OPERADOR, Rol.SUPERVISOR, Rol.ADMINISTRADOR):
            Rol.objects.get_or_create(nombre=n)
        user, pwd = os.getenv("ADMIN_USER"), os.getenv("ADMIN_INITIAL_PASSWORD")
        if not user or not pwd:
            raise CommandError("Define ADMIN_USER y ADMIN_INITIAL_PASSWORD en el entorno.")
        if Usuario.objects.filter(username=user).exists():
            self.stdout.write("El administrador ya existe; no se modifica.")
            return
        u = Usuario(username=user, nombre_completo="Administrador inicial",
                    rol=Rol.objects.get(nombre=Rol.ADMINISTRADOR), cambio_obligatorio=True, is_staff=True, is_superuser=True)
        u.set_password(pwd)
        u.save()
        self.stdout.write(self.style.SUCCESS(f"Administrador '{user}' creado (debe cambiar la contraseña al ingresar)."))
