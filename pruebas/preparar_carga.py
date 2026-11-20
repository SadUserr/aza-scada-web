"""Prepara la base para las pruebas de rendimiento: 50.000 inspecciones simuladas repartidas en 10 lotes
y 2 recetas, un usuario Operador de carga y un token de captura. Uso: python pruebas/preparar_carga.py"""
import os
import random
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "aza.settings")
import django  # noqa: E402

django.setup()
from django.utils import timezone  # noqa: E402

from cuentas.models import Rol, Usuario  # noqa: E402
from trazabilidad.models import EstadoInspeccion, Lote, Receta, RegistroInspeccion, TokenApi, Turno  # noqa: E402
from trazabilidad.services import evaluar_estado  # noqa: E402

TOTAL = int(os.getenv("AZA_CARGA_TOTAL", "50000"))
random.seed(42)
op_rol, _ = Rol.objects.get_or_create(nombre="Operador")
adm_rol, _ = Rol.objects.get_or_create(nombre="Administrador")
usuario, _ = Usuario.objects.get_or_create(username="carga_op", defaults={"nombre_completo": "Usuario de carga", "rol": op_rol})
usuario.set_password("Carga#Rendimiento2026")
usuario.cambio_obligatorio = False
usuario.save()
admin, _ = Usuario.objects.get_or_create(username="carga_admin", defaults={"nombre_completo": "Admin de carga", "rol": adm_rol})
recetas = [Receta.objects.get_or_create(nombre=f"CARGA-{e} mm", defaults={"espesor_mm": e, "material": "SAE 1008",
                                                                        "min_tol": lo, "max_tol": lo + 1})[0]
           for e, lo in ((6, 12.0), (10, 16.0))]
estados = {e.nombre: e for e in EstadoInspeccion.objects.all()}
turnos = list(Turno.objects.all())
ahora = timezone.now()
lotes = []
for i in range(10):
    lote, _ = Lote.objects.get_or_create(codigo=f"LT-CARGA-{i + 1:02d}",
                                         defaults={"receta": recetas[i % 2], "fecha_inicio": ahora - timedelta(days=30)})
    lotes.append(lote)
if RegistroInspeccion.objects.filter(lote__codigo__startswith="LT-CARGA-").count() < TOTAL:
    filas = []
    for n in range(TOTAL):
        lote = lotes[n % 10]
        ang = round(random.gauss(lote.receta.min_tol + 0.5, 0.4), 2)
        est, lo, hi = evaluar_estado(ang, lote.receta)
        fecha = ahora - timedelta(seconds=(TOTAL - n) * 50)
        filas.append(RegistroInspeccion(lote=lote, id_batch=f"C-{n:06d}", fecha=fecha, angulo=ang, receta=lote.receta,
                                        limite_min=lo, limite_max=hi, estado=estados[est],
                                        turno=next((t for t in turnos if t.incluye(timezone.localtime(fecha).time())), None),
                                        metricas={"scene": "oscura", "angle_confidence": random.choice(["ALTA", "MEDIA"])}))
    RegistroInspeccion.objects.bulk_create(filas, batch_size=2000, ignore_conflicts=True)
_, token = TokenApi.crear("Carga Locust", admin)
print(f"Inspecciones de carga: {RegistroInspeccion.objects.filter(lote__codigo__startswith='LT-CARGA-').count()}")
print(f"AZA_CARGA_USUARIO=carga_op  AZA_CARGA_CLAVE=Carga#Rendimiento2026  AZA_CARGA_LOTE=LT-CARGA-01")
print(f"AZA_CARGA_TOKEN={token}")
