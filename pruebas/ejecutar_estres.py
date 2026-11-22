"""Pruebas reproducibles de carga y estrés para aza_web (PR-01, PR-02, PR-04).

Uso (desde la carpeta aza_web):
    .\\.venv\\Scripts\\python.exe pruebas\\ejecutar_estres.py

Qué hace:
  1. Respalda db.sqlite3 en memoria temporal y al terminar lo restaura intacto.
  2. Levanta un servidor Django temporal aislado (puertos 8771 y 8772).
  3. Ejecuta los 3 escenarios:
     - PR-01: 20 sesiones autenticadas concurrentes (300 lecturas a historial y /ultima.json).
     - PR-02: 120 envíos sostenidos a POST /api/inspecciones con métricas JSON (límite 1000/min).
     - PR-04: 150 envíos en ráfaga contra el límite real de 120/min (verifica 120x201 y 30x429).
"""
import concurrent.futures
import http.cookiejar
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
PY = Path(sys.executable)


def esperar_servidor(base_url: str):
    for _ in range(50):
        try:
            urllib.request.urlopen(f"{base_url}/login/", timeout=1)
            return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f"El servidor temporal en {base_url} no respondió a tiempo.")


def crear_sesion_operador(base_url: str, usuario: str, clave: str):
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    html = opener.open(f"{base_url}/login/", timeout=5).read().decode("utf-8")
    csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html).group(1)
    datos = urllib.parse.urlencode(
        {"username": usuario, "password": clave, "csrfmiddlewaretoken": csrf}
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/login/",
        data=datos,
        headers={"Referer": f"{base_url}/login/"},
        method="POST",
    )
    opener.open(req, timeout=10).read()
    return opener


def percentil(valores_ordenados: list[float], pct: float) -> float:
    if not valores_ordenados:
        return 0.0
    idx = min(len(valores_ordenados) - 1, max(0, int(round((pct / 100.0) * (len(valores_ordenados) - 1)))))
    return valores_ordenados[idx]


def main():
    token_path = PROJ / ".demo_token.txt"
    if not token_path.exists():
        print("No se encontró .demo_token.txt. Ejecuta primero iniciar_aza.bat (opción 1).")
        sys.exit(1)
    token = token_path.read_text(encoding="utf-8").strip()

    orig_db = PROJ / "db.sqlite3"
    bak_db = Path(tempfile.gettempdir()) / f"aza_db_bak_{os.getpid()}.sqlite3"
    shutil.copy2(orig_db, bak_db)

    print("=" * 74)
    print(" PROTOCOLO DE PRUEBAS DE CARGA Y ESTRÉS — ACEROS AZA SCADA (aza_web)")
    print("=" * 74)

    try:
        # ---- FASE 1: PR-01 + PR-02 con límite elevado ----
        port1 = 8771
        base1 = f"http://127.0.0.1:{port1}"
        env1 = os.environ.copy()
        env1["DJANGO_DEBUG"] = "1"
        env1["API_LIMITE_POR_MINUTO"] = "1000"
        proc1 = subprocess.Popen(
            [str(PY), "manage.py", "runserver", f"127.0.0.1:{port1}", "--noreload"],
            cwd=str(PROJ),
            env=env1,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            esperar_servidor(base1)

            # PR-01
            print("\n[PR-01] Autenticando 20 sesiones de operador y ejecutando 300 lecturas concurrentes...")
            sesiones = [crear_sesion_operador(base1, "operador1", "Clave#AZA2026") for _ in range(20)]

            def tarea_pr01(opener):
                lats, codes = [], {}
                urls = [
                    f"{base1}/operador/historial/?lote=LT-DEMO-01",
                    f"{base1}/operador/ultima.json",
                    f"{base1}/operador/historial/?page=2",
                ]
                for i in range(15):
                    t0 = time.perf_counter()
                    try:
                        r = opener.open(urls[i % len(urls)], timeout=15)
                        r.read()
                        code = r.status
                    except urllib.error.HTTPError as e:
                        code = e.code
                    except Exception:
                        code = 0
                    lats.append((time.perf_counter() - t0) * 1000.0)
                    codes[code] = codes.get(code, 0) + 1
                return lats, codes

            t0 = time.perf_counter()
            lats1, codes1 = [], {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
                for lats, codes in ex.map(tarea_pr01, sesiones):
                    lats1.extend(lats)
                    for k, v in codes.items():
                        codes1[k] = codes1.get(k, 0) + v
            dur1 = time.perf_counter() - t0
            lats1.sort()
            print(f"  Peticiones : {len(lats1)} en {dur1:.2f} s ({len(lats1)/dur1:.1f} req/s)")
            print(f"  Latencia   : p50={percentil(lats1,50):.1f} ms | p95={percentil(lats1,95):.1f} ms | máx={max(lats1):.1f} ms")
            print(f"  Códigos    : {codes1}  -> {'APROBADA' if codes1.get(200)==300 else 'REVISAR'}")

            # PR-02
            print("\n[PR-02] Enviando ráfaga sostenida de 120 POST /api/inspecciones (métricas JSON)...")
            t0 = time.perf_counter()
            lats2, codes2 = [], {}
            for idx in range(1, 121):
                payload = json.dumps({
                    "lote": "LT-DEMO-01",
                    "id_batch": f"LT-DEMO-01-STRESS-{idx:04d}",
                    "angulo": round(random.gauss(12.5, 0.35), 2),
                    "metricas": {"scene": "oscura", "angle_confidence": "ALTA", "circle_method": "hough", "total_frames": 120},
                }).encode("utf-8")
                req = urllib.request.Request(
                    f"{base1}/api/inspecciones",
                    data=payload,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    method="POST",
                )
                ti = time.perf_counter()
                try:
                    with urllib.request.urlopen(req, timeout=10) as r:
                        r.read()
                        code = r.status
                except urllib.error.HTTPError as e:
                    e.read()
                    code = e.code
                except Exception:
                    code = 0
                lats2.append((time.perf_counter() - ti) * 1000.0)
                codes2[code] = codes2.get(code, 0) + 1
            dur2 = time.perf_counter() - t0
            lats2.sort()
            print(f"  Peticiones : {len(lats2)} en {dur2:.2f} s ({len(lats2)/dur2:.1f} ingestas/s)")
            print(f"  Latencia   : p50={percentil(lats2,50):.1f} ms | p95={percentil(lats2,95):.1f} ms | máx={max(lats2):.1f} ms")
            print(f"  Códigos    : {codes2}  -> {'APROBADA' if codes2.get(201)==120 else 'REVISAR'}")
        finally:
            proc1.terminate()
            try:
                proc1.wait(timeout=5)
            except Exception:
                proc1.kill()

        # ---- FASE 2: PR-04 límite de tasa 120/min ----
        port2 = 8772
        base2 = f"http://127.0.0.1:{port2}"
        env2 = os.environ.copy()
        env2["DJANGO_DEBUG"] = "1"
        env2["API_LIMITE_POR_MINUTO"] = "120"
        proc2 = subprocess.Popen(
            [str(PY), "manage.py", "runserver", f"127.0.0.1:{port2}", "--noreload"],
            cwd=str(PROJ),
            env=env2,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            esperar_servidor(base2)
            print("\n[PR-04] Enviando sobrecarga de 150 POST contra límite de 120 req/min...")
            t0 = time.perf_counter()
            lats4, codes4 = [], {}
            for idx in range(1, 151):
                payload = json.dumps({
                    "lote": "LT-DEMO-01",
                    "id_batch": f"LT-DEMO-01-RL-{idx:04d}",
                    "angulo": 12.5,
                }).encode("utf-8")
                req = urllib.request.Request(
                    f"{base2}/api/inspecciones",
                    data=payload,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    method="POST",
                )
                ti = time.perf_counter()
                try:
                    with urllib.request.urlopen(req, timeout=10) as r:
                        r.read()
                        code = r.status
                except urllib.error.HTTPError as e:
                    e.read()
                    code = e.code
                except Exception:
                    code = 0
                lats4.append((time.perf_counter() - ti) * 1000.0)
                codes4[code] = codes4.get(code, 0) + 1
            dur4 = time.perf_counter() - t0
            lats4.sort()
            print(f"  Peticiones : {len(lats4)} en {dur4:.2f} s ({len(lats4)/dur4:.1f} req/s)")
            print(f"  Latencia   : p50={percentil(lats4,50):.1f} ms | p95={percentil(lats4,95):.1f} ms")
            print(f"  Códigos    : {codes4}  -> {'APROBADA' if codes4.get(201)==120 and codes4.get(429)==30 else 'REVISAR'}")
        finally:
            proc2.terminate()
            try:
                proc2.wait(timeout=5)
            except Exception:
                proc2.kill()
    finally:
        shutil.copy2(bak_db, orig_db)
        try:
            bak_db.unlink()
        except Exception:
            pass
        print("\nBase de datos db.sqlite3 restaurada a su estado original.")
        print("=" * 74)


if __name__ == "__main__":
    main()
