"""Datos de demostración: 3 operadores por turno, recetas con letra, lotes con receta obligatoria, 40 inspecciones y auditoría."""
import random
import secrets
from datetime import time, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

from cuentas.models import Rol, Usuario
from trazabilidad.models import EstadoInspeccion, Lote, Receta, RegistroAuditoria, RegistroInspeccion, TokenApi, Turno


def metricas_demo(i, angulo):
    """Mismo formato que el metricas.json que escribe APP-AZA (SequenceAnalysisResult)."""
    return {
        "total_frames": 130,
        "scene": "oscura",
        "mean_background": round(random.uniform(18, 26), 2),
        "first_exit_frame": random.randint(30, 60),
        "exit_confidence": "ALTA",
        "circle_cx": round(random.uniform(610, 640), 1),
        "circle_cy": round(random.uniform(500, 520), 1),
        "circle_radius": round(random.uniform(300, 320), 1),
        "circle_method": "hough",
        "circle_support_frames": random.randint(8, 20),
        "angle_frame": random.randint(60, 90),
        "exit_angle_deg": angulo,
        "angle_confidence": "ALTA" if i % 7 else "MEDIA",
        "diagnostic_path": f"Trigger_{i:04d}/resultado_analisis.png",
    }


class Command(BaseCommand):
    help = "Carga datos de ejemplo realistas de los 3 turnos y operadores (solo desarrollo)."

    def handle(self, *a, **kw):
        for n in (Rol.OPERADOR, Rol.SUPERVISOR, Rol.ADMINISTRADOR):
            Rol.objects.get_or_create(nombre=n)
        r6, _ = Receta.objects.get_or_create(
            nombre="TF-6 mm",
            defaults={"codigo_letra": "A", "min_tol": 12.0, "max_tol": 13.0, "espesor_mm": 6.0, "material": "SAE 1008"},
        )
        if r6.codigo_letra != "A":
            r6.codigo_letra = "A"
            r6.save(update_fields=["codigo_letra"])
        r10, _ = Receta.objects.get_or_create(
            nombre="TF-10 mm",
            defaults={"codigo_letra": "B", "min_tol": 16.0, "max_tol": 17.0, "espesor_mm": 10.0, "material": "SAE 1010"},
        )
        if r10.codigo_letra != "B":
            r10.codigo_letra = "B"
            r10.save(update_fields=["codigo_letra"])

        admin = Usuario.objects.filter(rol__nombre=Rol.ADMINISTRADOR).first()
        if admin is None:
            self.stderr.write("Primero ejecuta init_aza (necesita un administrador).")
            return

        ops = {}
        op_specs = (
            ("operador1", "Operador Turno Mañana"),
            ("operador2", "Operador Turno Tarde"),
            ("operador3", "Operador Turno Noche"),
        )
        for username, nombre in op_specs:
            u = Usuario.objects.filter(username=username).first()
            if not u:
                pwd = "Tmp" + secrets.token_urlsafe(6) + "9a"
                u = Usuario(username=username, nombre_completo=nombre, rol=Rol.objects.get(nombre=Rol.OPERADOR), cambio_obligatorio=True)
                u.set_password(pwd)
                u.save()
            ops[username] = u

        if not Usuario.objects.filter(username="supervisor1").exists():
            u = Usuario(username="supervisor1", nombre_completo="Supervisor de Calidad",
                        rol=Rol.objects.get(nombre=Rol.SUPERVISOR), cambio_obligatorio=True)
            u.set_password("Tmp" + secrets.token_urlsafe(6) + "9a")
            u.save()

        ahora = timezone.now()
        l1, _ = Lote.objects.get_or_create(
            codigo="LT-DEMO-01",
            defaults={
                "receta": r6,
                "operador_inicio": ops["operador1"],
                "operador_activo": ops["operador1"],
                "cantidad": 2400,
                "fecha_inicio": ahora - timedelta(hours=20),
            },
        )
        Lote.objects.get_or_create(
            codigo="LT-DEMO-00",
            defaults={
                "receta": r10,
                "operador_inicio": ops["operador2"],
                "operador_fin": ops["operador3"],
                "cantidad": 1800,
                "fecha_inicio": ahora - timedelta(days=1, hours=10),
                "fecha_fin": ahora - timedelta(hours=18),
            },
        )

        _, token = TokenApi.crear("Nodo Jetson · Línea 1", admin)
        self.stdout.write(self.style.SUCCESS(f"Token de captura: {token}"))

        for est in (RegistroInspeccion.APROBADO, RegistroInspeccion.RECHAZADO):
            EstadoInspeccion.objects.get_or_create(nombre=est)
        for t_nom, t_ini, t_fin in (("Mañana", time(6), time(14)), ("Tarde", time(14), time(22)), ("Noche", time(22), time(6))):
            Turno.objects.get_or_create(nombre=t_nom, defaults={"hora_inicio": t_ini, "hora_fin": t_fin})

        estados = {e.nombre: e for e in EstadoInspeccion.objects.all()}
        turnos = list(Turno.objects.all())
        turno_op = {"Mañana": ops["operador1"], "Tarde": ops["operador2"], "Noche": ops["operador3"]}

        random.seed(7)
        for i in range(1, 41):
            # Repartir a lo largo de las últimas 24 horas para poblar los 3 turnos y 3 operadores
            dt = ahora - timedelta(minutes=(41 - i) * 35)
            h = timezone.localtime(dt).time()
            turno = next((t for t in turnos if t.incluye(h)), None)
            op = turno_op.get(turno.nombre, ops["operador1"]) if turno else ops["operador1"]
            lote_obj = l1 if i > 10 else Lote.objects.get(codigo="LT-DEMO-00")
            rec = lote_obj.receta
            ang = round(random.gauss((rec.min_tol + rec.max_tol) / 2, 0.45), 2)
            ang = max(0.0, min(180.0, ang))
            est_name = RegistroInspeccion.APROBADO if (rec.min_tol <= ang <= rec.max_tol) else RegistroInspeccion.RECHAZADO
            batch_id = f"{lote_obj.codigo}-B{i:03d}"
            RegistroInspeccion.objects.get_or_create(
                lote=lote_obj,
                id_batch=batch_id,
                defaults={
                    "fecha": dt,
                    "angulo": ang,
                    "receta": rec,
                    "limite_min": rec.min_tol,
                    "limite_max": rec.max_tol,
                    "estado": estados[est_name],
                    "turno": turno,
                    "operador": op,
                    "carpeta": f"RESULTADOS/{dt:%Y-%m-%d}/{batch_id}",
                    "metricas": metricas_demo(i, ang),
                },
            )

        if not RegistroAuditoria.objects.exists():
            RegistroAuditoria.objects.create(
                usuario=admin, usuario_nombre=admin.username, rol_nombre="Administrador",
                modulo="Lotes", accion="Apertura de lote",
                detalle=f"Lote {l1.codigo} abierto con receta [{r6.codigo_letra}] {r6.nombre}",
                ip="127.0.0.1",
            )
            RegistroAuditoria.objects.create(
                usuario=ops["operador1"], usuario_nombre=ops["operador1"].username, rol_nombre="Operador",
                modulo="Operación en Línea", accion="Inicio / Relevo de lote",
                detalle=f"Operador {ops['operador1'].username} inició turno en lote {l1.codigo}",
                ip="127.0.0.1",
            )

        self.stdout.write("Listo: 40 inspecciones distribuidas en los 3 turnos y 3 operadores.")
