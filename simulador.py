"""Simulador del sistema de captura: envía batches a la API (informe: actor externo, CU13).
Reemplaza a APP-AZA cuando no hay cámara; envía el mismo formato (incluido «metricas», como el metricas.json).
Uso: python simulador.py --token <TOKEN> --lote LT-DEMO-01 [--url http://127.0.0.1:8000] [--n 10] [--cada 3]"""
import argparse
import json
import random
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

p = argparse.ArgumentParser()
p.add_argument("--token", required=True)
p.add_argument("--lote", required=True)
p.add_argument("--url", default="http://127.0.0.1:8000")
p.add_argument("--n", type=int, default=10)
p.add_argument("--cada", type=float, default=3.0)
p.add_argument("--centro", type=float, default=12.5)
a = p.parse_args()

for i in range(1, a.n + 1):
    ahora = datetime.now(timezone.utc)
    angulo = round(random.gauss(a.centro, 0.5), 2)
    trigger = f"{a.lote}-B{i:03d}_{ahora:%H%M%S}"
    body = {"lote": a.lote, "id_batch": trigger[:50], "angulo": angulo, "fecha": ahora.isoformat(),
            "carpeta": f"RESULTADOS/{ahora:%Y-%m-%d}/{trigger}",
            "metricas": {"total_frames": 130, "scene": "oscura", "exit_confidence": "ALTA",
                         "circle_method": "hough", "circle_radius": round(random.uniform(300, 320), 1),
                         "exit_angle_deg": angulo, "angle_confidence": random.choice(["ALTA", "ALTA", "MEDIA"]),
                         "origen": "simulador"}}
    req = urllib.request.Request(a.url + "/api/inspecciones", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Authorization": f"Bearer {a.token}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            print(r.status, r.read().decode())
    except urllib.error.HTTPError as e:
        print(e.code, e.read().decode())
    except urllib.error.URLError as e:
        print(f"ERROR: No se pudo conectar a {a.url} ({e.reason}). Verifica que iniciar_aza.bat este encendido.")
        raise SystemExit(1)
    if i < a.n:
        time.sleep(a.cada)
