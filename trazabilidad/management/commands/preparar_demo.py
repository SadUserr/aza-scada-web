"""Deja el sistema listo para operación o demostración (solo en desarrollo, DJANGO_DEBUG=1).
- Asigna la contraseña de demo a admin, operador1, operador2, operador3 y supervisor1.
- Opcionalmente (--con-datos) carga las 40 inspecciones históricas de seed_demo si la base está vacía.
- Se asegura de que existan recetas con código letra ([A] TF-6 mm, [B] TF-10 mm) y lote abierto LT-DEMO-01 con operador asignado.
- Genera dos tokens limpios y elimina cualquier lote sin receta heredado."""
from pathlib import Path
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from cuentas.models import Rol, Usuario
from trazabilidad.models import Lote, Receta, RegistroInspeccion, TokenApi


class Command(BaseCommand):
    help = "Prepara usuarios, lotes con receta obligatoria y tokens para demostración (solo desarrollo)."

    def add_arguments(self, parser):
        parser.add_argument("--clave", default="Clave#AZA2026")
        parser.add_argument("--con-datos", action="store_true",
                            help="Ejecuta seed_demo automáticamente si aún no hay inspecciones registradas.")
        parser.add_argument("--guardar-tokens", action="store_true",
                            help="Guarda los tokens generados en archivos locales ignorados por Git para simular_captura.bat")
        parser.add_argument("--forzar-cambio-admin", action="store_true",
                            help="Deja a admin con cambio obligatorio de contraseña para demostrar primer ingreso.")

    def handle(self, *a, clave, con_datos=False, guardar_tokens=False, forzar_cambio_admin=False, **kw):
        if not settings.DEBUG:
            raise CommandError("preparar_demo solo se puede usar en desarrollo (DJANGO_DEBUG=1).")
        roles = {n: Rol.objects.get_or_create(nombre=n)[0] for n in (Rol.OPERADOR, Rol.SUPERVISOR, Rol.ADMINISTRADOR)}

        admin_defaults = {"nombre_completo": "Administrador Planta", "rol": roles[Rol.ADMINISTRADOR],
                          "is_staff": True, "is_superuser": True}
        admin_user, _ = Usuario.objects.get_or_create(username="admin", defaults=admin_defaults)
        if not admin_user.is_staff or not admin_user.is_superuser:
            admin_user.is_staff, admin_user.is_superuser = True, True
            admin_user.save(update_fields=["is_staff", "is_superuser"])

        if con_datos and not RegistroInspeccion.objects.exists():
            self.stdout.write("Base sin inspecciones previas: cargando historial inicial (seed_demo)...")
            call_command("seed_demo")

        usuarios_demo = (
            ("admin", Rol.ADMINISTRADOR, "Administrador Planta"),
            ("operador1", Rol.OPERADOR, "Operador Turno Mañana"),
            ("operador2", Rol.OPERADOR, "Operador Turno Tarde"),
            ("operador3", Rol.OPERADOR, "Operador Turno Noche"),
            ("supervisor1", Rol.SUPERVISOR, "Supervisor de Calidad"),
        )
        ops = {}
        for username, rol, nombre in usuarios_demo:
            u, _ = Usuario.objects.get_or_create(username=username, defaults={"nombre_completo": nombre, "rol": roles[rol]})
            u.rol = roles[rol]
            u.nombre_completo = nombre
            u.set_password(clave)
            u.is_active = True
            u.cambio_obligatorio = (forzar_cambio_admin and username == "admin")
            u.intentos_fallidos = 0
            u.bloqueado_hasta = None
            u.save()
            ops[username] = u

        receta, _ = Receta.objects.get_or_create(
            nombre="TF-6 mm",
            defaults={"codigo_letra": "A", "espesor_mm": 6.0, "material": "SAE 1008", "min_tol": 12.0, "max_tol": 13.0},
        )
        Receta.objects.get_or_create(
            nombre="TF-10 mm",
            defaults={"codigo_letra": "B", "espesor_mm": 10.0, "material": "SAE 1010", "min_tol": 16.0, "max_tol": 17.0},
        )

        lote, _ = Lote.objects.get_or_create(
            codigo="LT-DEMO-01",
            defaults={"receta": receta, "operador_inicio": ops["operador1"], "operador_activo": ops["operador1"], "cantidad": 2400},
        )
        cambios_lote = []
        if lote.fecha_fin:
            lote.fecha_fin = None
            lote.operador_fin = None
            cambios_lote.extend(["fecha_fin", "operador_fin"])
        if lote.receta_id != receta.id:
            lote.receta = receta
            cambios_lote.append("receta")
        if not lote.operador_inicio_id:
            lote.operador_inicio = ops["operador1"]
            cambios_lote.append("operador_inicio")
        if not lote.operador_activo_id:
            lote.operador_activo = ops["operador1"]
            cambios_lote.append("operador_activo")
        if cambios_lote:
            lote.save(update_fields=cambios_lote)

        nombres_demo = [
            "Simulador demo",
            "Token para revocar en la demo",
            "Nodo Jetson · Línea 1",
            "Cámara Auxiliar · Línea 2",
        ]
        TokenApi.objects.filter(nombre__in=nombres_demo).delete()
        admin = Usuario.objects.get(username="admin")
        _, t1 = TokenApi.crear("Nodo Jetson · Línea 1", admin)
        _, t2 = TokenApi.crear("Cámara Auxiliar · Línea 2", admin)

        self.stdout.write(self.style.SUCCESS("Listo para operación / presentación."))
        self.stdout.write(f"  Usuarios: admin, operador1, operador2, operador3, supervisor1 · contraseña: {clave}")
        if forzar_cambio_admin:
            self.stdout.write("  Nota: 'admin' deberá cambiar su contraseña en el primer ingreso.")
        self.stdout.write(f"  Lote abierto: LT-DEMO-01 (receta [{receta.codigo_letra}] {receta.nombre}: {receta.min_tol}°–{receta.max_tol}°)")
        self.stdout.write(f"  Token Línea 1 (activo):     {t1}")
        self.stdout.write(f"  Token Línea 2 (secundario): {t2}")
        if guardar_tokens:
            Path(settings.BASE_DIR / ".demo_token.txt").write_text(t1, encoding="utf-8")
            Path(settings.BASE_DIR / ".demo_token_revocar.txt").write_text(t2, encoding="utf-8")
            self.stdout.write("  (Tokens sincronizados automáticamente con simular_captura.bat)")
        else:
            self.stdout.write("  (Los tokens se muestran solo ahora; cópialos.)")
