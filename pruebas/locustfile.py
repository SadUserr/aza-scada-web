"""Pruebas de rendimiento con Locust (Tabla 45).
Preparación:  python pruebas/preparar_carga.py   (50.000 inspecciones simuladas + usuario y token de carga)
PR-01:  locust -f pruebas/locustfile.py ConsultaHistorial --headless -u 100 -r 20 -t 60s --host http://127.0.0.1:8000
PR-02:  locust -f pruebas/locustfile.py IngestaApi --headless -u 10 -r 10 -t 60s --host http://127.0.0.1:8000
Variables: AZA_CARGA_USUARIO, AZA_CARGA_CLAVE, AZA_CARGA_TOKEN, AZA_CARGA_LOTE (las imprime preparar_carga.py).
Para PR-02 el servidor debe iniciarse con API_LIMITE_POR_MINUTO alto (el límite normal es 120 por minuto y origen)."""
import itertools
import os
import random
import re
import uuid

from locust import HttpUser, between, constant_pacing, task

USUARIO = os.getenv("AZA_CARGA_USUARIO", "carga_op")
CLAVE = os.getenv("AZA_CARGA_CLAVE", "Carga#Rendimiento2026")
TOKEN = os.getenv("AZA_CARGA_TOKEN", "")
LOTE = os.getenv("AZA_CARGA_LOTE", "LT-CARGA-01")
_contador = itertools.count(1)


class ConsultaHistorial(HttpUser):
    """PR-01: operadores consultando el historial filtrado y la última inspección."""
    wait_time = between(0.5, 1.5)

    def on_start(self):
        r = self.client.get("/login/")
        csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', r.text).group(1)
        self.client.post("/login/", {"username": USUARIO, "password": CLAVE, "csrfmiddlewaretoken": csrf},
                         headers={"Referer": self.host + "/login/"})

    @task(3)
    def historial(self):
        self.client.get(f"/operador/historial/?lote={LOTE}&page={random.randint(1, 50)}", name="/operador/historial/")

    @task(1)
    def ultima(self):
        self.client.get("/operador/ultima.json")


class IngestaApi(HttpUser):
    """PR-02: el sistema de captura envía ~500 resultados en 60 s (10 equipos x ~0,85 por segundo)."""
    wait_time = constant_pacing(1.2)

    @task
    def enviar(self):
        n = next(_contador)
        self.client.post("/api/inspecciones", name="/api/inspecciones",
                         json={"lote": LOTE, "id_batch": f"PR02-{uuid.uuid4().hex[:12]}-{n}",
                               "angulo": round(random.gauss(12.5, 0.4), 2),
                               "metricas": {"scene": "oscura", "angle_confidence": "ALTA", "origen": "locust"}},
                         headers={"Authorization": f"Bearer {TOKEN}"})
