# AZA – Sistema SCADA Web de Monitoreo y Trazabilidad del Trefilado (Django)

Sistema web industrial desarrollado para **Aceros AZA S.A.** (contraparte técnica: **Robotic Systems Chile**), alineado con el modelo de datos (apartado 6), casos de uso **CU01–CU18**, arquitectura de seguridad (apartado 7), plan de pruebas (apartado 9) y requerimientos de evaluación **EV2 / ES3**.

La captura óptica de alta velocidad y el cálculo geométrico por visión artificial permanecen desacoplados en **APP-AZA** (nodo industrial NVIDIA Jetson en línea de trefilado), que transmite cada ráfaga procesada mediante `POST /api/inspecciones` con autenticación Bearer por token revocable. Cuando no se dispone de la cámara en sala, `simulador.py` (y su lanzador interactivo `simular_captura.bat`) emula exactamente el mismo contrato JSON.

```text
APP-AZA (Jetson + cámara)   ──HTTPS + Bearer Token──►  aza_web (Django SCADA)  ──►  PostgreSQL / SQLite (metricas JSONB)
simular_captura.bat / CLI   ────────────────────────►            ▲
                                                      Navegador Web en Planta (100% Offline-Ready)
                                                   (Operador · Supervisor de Calidad · Administrador)
```

---

## 1. Inicio rápido con un clic (Windows `.bat` — Recomendado para defensa y cliente)

Para levantar y demostrar todo el proyecto sin escribir comandos en PowerShell ni copiar tokens manualmente:

### Paso 1: Encender el servidor web
Haz doble clic en **`INICIAR_AZA.bat`** (en la carpeta raíz) o en **`iniciar_aza.bat`** (dentro de `aza_web\aza_web`) y presiona **Enter**:

- Verifica `.venv` (si abres el proyecto en otro PC, recrea el entorno virtual automáticamente) e instala `requirements.txt` únicamente si faltan paquetes (arranca en **~2–3 segundos sin conexión a internet** si ya fue instalado).
- Ejecuta las migraciones (`migrate --noinput`) y muestra 4 modos de arranque:

| Opción | Modo | Qué ejecuta automáticamente | Cuándo elegirla |
| :---: | :--- | :--- | :--- |
| **`[1]`** *(Enter)* | **Demo lista para presentar** | Carga las 40 inspecciones históricas si la base está vacía, desbloquea `operador1`, `supervisor1` y `admin` con clave **`Clave#AZA2026`**, reabre el lote `LT-DEMO-01`, sincroniza tokens locales y abre `http://127.0.0.1:8000`. | **Opción recomendada frente al profesor o cliente.** |
| **`[2]`** | **Reiniciar demo limpia de cero** | Respalda y recrea `db.sqlite3` desde cero con las 40 inspecciones originales limpias (elimina alarmas u observaciones de ensayo). | Justo **antes de presentar** tras haber practicado. |
| **`[3]`** | **Primer acceso estricto (`CU02`)** | Igual que `[1]`, pero configura a `admin` con contraseña inicial **`Cambia#Esto2026`** y cambio obligatorio al iniciar sesión. | Si te piden demostrar el bloqueo de primer acceso (`CU02`). |
| **`[4]`** | **Solo encender servidor** | Abre el navegador y levanta `runserver` conservando intactos los usuarios, tokens y registros actuales. | Para retomar una sesión previa sin cambios. |

> **Importante:** Mantén abierta la ventana de `iniciar_aza.bat` mientras uses el navegador (`Ctrl + C` para apagar el servidor).

### Paso 2: Simular capturas de cámara / Jetson en tiempo real
Con el servidor encendido, haz doble clic en **`SIMULAR_CAPTURA.bat`** (raíz) o **`simular_captura.bat`**. El script lee automáticamente los tokens sincronizados en archivos locales ignorados por Git (`.demo_token*.txt`) y ofrece un menú interactivo de una sola tecla:

| Opción | Escenario en vivo | Resultado esperado en la interfaz web |
| :---: | :--- | :--- |
| **`[1]`** | **5 ráfagas Aprobadas** (`~12.5°`) | Lecturas dentro de tolerancia (`12.0°–13.0°`, receta `TF-6 mm`), estado verde **CONFORME / APROBADO**. |
| **`[2]`** | **3 Rechazos + Alarma Crítica** (`~14.2°`) | En ~5 s la pantalla del Operador cambia sola a rojo **FUERA DE TOLERANCIA** y levanta **Alarma Crítica** (`CU03`, `CU05`). |
| **`[3]`** | **Probar Token Revocado (`CU18`)** | Usa la credencial secundaria (*«Cámara Auxiliar · Línea 2»*): tras revocarla en *Administración → Tokens*, devuelve `401 No autorizado` y genera alarma de seguridad. |
| **`[4]`** | **2 ráfagas a lote Sin Receta** | Envía al lote `LT-DEMO-SINRECETA`, registrando estado **Sin Receta** (`limite_min/max = null`) y alerta operativa. |
| **`[5]`** | **Simulación continua de planta** | Envía 25 ráfagas cada 4 s para recorrer gráficos y KPIs en tiempo real. |

---

## 2. Puesta en marcha manual (Windows / PowerShell) y Despliegue

Si prefieres ejecutar cada etapa manualmente desde consola en `aza_web\aza_web`:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate

# Opción A: Inicialización estricta de producción/informe (CU02: exige cambio de clave al primer login)
$env:ADMIN_USER="admin"; $env:ADMIN_INITIAL_PASSWORD="Cambia#Esto2026"
python manage.py init_aza
python manage.py seed_demo         # opcional: recetas, lotes, usuarios demo y 40 inspecciones con métricas JSON

# Opción B: Preparación rápida de demostración (solo disponible con DJANGO_DEBUG=1)
python manage.py preparar_demo --con-datos --guardar-tokens

python manage.py runserver 127.0.0.1:8000
```

Banderas soportadas por `preparar_demo`:
- `--clave "OtraClave#2026"`: define la contraseña asignada a `admin`, `operador1` y `supervisor1` (por defecto `Clave#AZA2026`).
- `--con-datos`: ejecuta `seed_demo` automáticamente si aún no existen inspecciones en la base de datos.
- `--guardar-tokens`: guarda los dos tokens recién emitidos en `.demo_token.txt` y `.demo_token_revocar.txt` (excluidos en `.gitignore`) para `simular_captura.bat`.
- `--forzar-cambio-admin`: activa `cambio_obligatorio=True` en `admin` para demostrar `CU02`.

**Base de datos y despliegue en la nube:**
- **PostgreSQL (arquitectura del informe):** define `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` y ejecuta `migrate`. Si `DB_NAME` no está definida, usa **SQLite** local para desarrollo rápido (un escritor simultáneo; documentado en prueba `PR-02`).
- **Producción (Render + Supabase PostgreSQL):** define `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS` y variables de BD con `DB_SSLMODE=require`. Comando de inicio:
  ```bash
  python manage.py collectstatic --noinput && gunicorn aza.wsgi
  ```

---

## 3. Interfaz SCADA Industrial y Capacidades Implementadas (ES3)

La interfaz web fue diseñada bajo lineamientos de **HMI / SCADA industrial para planta siderúrgica** (paleta de alto contraste acero/carbón para reducir fatiga visual en turnos nocturnos, acento corporativo verde Aceros AZA `#008752` / `#10b981`, cifras tabulares monoespaciadas y operación **100% offline** sin depender de CDNs externos):

- **Operador de Línea (`operador1` — `CU03`, `CU04`, `CU05`, `CU14`):**
  - Panel de monitoreo en vivo con auto-actualización cada 5 s (`meta refresh`), indicador luminoso de estado, alerta destacada si existen alarmas críticas sin atender y **medidor lineal/SVG de tolerancia angular** con banda verde nominal y aguja dinámica posicionada según el ángulo medido.
  - Historial operativo paginado con filtros combinables por lote, turno, estado, rango de fechas y check de auditoría **«Con observaciones»**.
  - Ficha técnica de inspección (`detalle.html`) con tarjetas estructuradas de **telemetría de visión artificial** provenientes del Jetson (`exit_angle_deg`, `angle_confidence`, `exit_confidence`, `scene`, `circle_method`, `circle_radius`, `total_frames`), visor desplegable del payload `metricas` crudo (`JSONB`) y bitácora inmutable de observaciones (`Nota`, `Alerta`, `Corrección`).
- **Supervisor de Calidad (`supervisor1` — `CU06`, `CU07`, `CU08`, `CU09`):**
  - Dashboard gerencial con KPIs de tasa de aprobación/rechazo, distribución por nivel de confianza óptica (`ALTA`, `MEDIA`, `BAJA`) y **Control Estadístico de Procesos (SPC)** en vivo: media angular (`μ`), desviación estándar (`σ`) e índices de capacidad de proceso **`Cp`** y **`Cpk`** calculados sobre las lecturas con tolerancia activa.
  - Gráfico interactivo de tendencias angulares (`Chart.js` empacado localmente en `static/vendor/`) con trazado continuo de límites superior (`USL`) e inferior (`LSL`), puntos coloreados por conformidad y tabla de trazabilidad por lote.
  - Exportación directa a **CSV con BOM UTF-8** lista para abrir en Microsoft Excel respetando todos los filtros aplicados (`CU09`).
- **Administrador de Sistema (`admin` — `CU01`, `CU02`, `CU10`–`CU12`, `CU16`–`CU18`):**
  - Gestión de cuentas y roles (`Operador`, `Supervisor`, `Administrador`), desactivación sin borrado físico (integridad referencial `PROTECT`), atención de solicitudes de recuperación de contraseña con clave temporal de un uso (`CU16`/`CU17`).
  - Catálogo de recetas metalúrgicas (espesor en mm, acero SAE y rango angular `0°–180°`), apertura/cierre de lotes de producción y emisión/revocación inmediata de tokens API individuales almacenados únicamente como hash `SHA-256`.

---

## 4. Integración API con APP-AZA (Jetson) y Simulador (`CU13`, `CU15`)

- **Con cámara en planta (APP-AZA en NVIDIA Jetson):** define las variables de entorno `AZA_API_URL=https://<servidor>`, `AZA_API_TOKEN=<TOKEN>` y `AZA_API_LOTE=<codigo_lote>` (o escribe el lote activo en `data/lote_actual.txt`; ver `src/integracion/cliente_api.py` en APP-AZA).
- **Sin cámara (consola manual):**
  ```powershell
  python simulador.py --token <TOKEN> --lote LT-DEMO-01 --n 10 --cada 3 --centro 12.5
  ```
  *(Usa `--centro 14.2` para forzar rechazos fuera de la banda `12.0°–13.0°`).*

**Contrato JSON recibido en `POST /api/inspecciones`:**
```json
{
  "lote": "LT-DEMO-01",
  "id_batch": "Trigger_0123_20261019_181900",
  "angulo": 12.61,
  "fecha": "2026-10-19T21:19:00+00:00",
  "carpeta": "RESULTADOS/2026-10-19/Trigger_0123_20261019_181900",
  "metricas": {
    "total_frames": 130,
    "scene": "oscura",
    "exit_confidence": "ALTA",
    "angle_confidence": "ALTA",
    "circle_method": "hough",
    "circle_radius": 312.8
  }
}
```
**Códigos de respuesta HTTP:** `201` inspección registrada · `401` token ausente, inválido o revocado · `404` lote inexistente · `409` `id_batch` duplicado en el lote o lote cerrado · `413` payload mayor a 10 KB · `422` validación fallida (`{"error": "campo: motivo"}`) · `429` límite de 120 peticiones/min por IP excedido.

---

## 5. Guion sugerido para la defensa / demostración (paso a paso)

1. **Arranque limpio (10 s):** ejecuta `INICIAR_AZA.bat` y elige **`[2]`** (si estuviste ensayando antes) o **`[1]`**. Se abrirá `http://127.0.0.1:8000` con la contraseña `Clave#AZA2026` activa para los tres perfiles.
2. **Monitoreo en planta (`operador1`):** ingresa como `operador1` → muestra el estado actual del lote `LT-DEMO-01`, el medidor angular y las últimas lecturas del turno.
3. **Disparo de rechazo y alarma en vivo (`CU03`, `CU05`, `CU13`):** abre `SIMULAR_CAPTURA.bat` y presiona **`[2]`**. Sin tocar el navegador, en ~5 s el panel cambia a **RECHAZADO** en rojo y aparece el banner de **Alarma Crítica**.
4. **Telemetría óptica y bitácora (`CU14`):** haz clic en **Detalle** sobre el rechazo recién creado → muestra los parámetros del círculo de Hough enviados por visión artificial y registra una observación tipo *Alerta* o *Corrección* → pasa a *Alarmas* y márcala como **Atendida**.
5. **Analítica SPC y exportación (`supervisor1`, `CU06`–`CU09`):** cierra sesión e ingresa como `supervisor1` → explica los KPIs de calidad, la capacidad de proceso (`Cp` / `Cpk`), la curva de **Tendencias** frente a los límites de tolerancia y descarga el reporte con **Exportar CSV**.
6. **Seguridad y revocación de credenciales de captura (`admin`, `CU18`):** ingresa como `admin` → ve a *Tokens de captura* → pulsa **Revocar** en *«Cámara Auxiliar · Línea 2»*. En la ventana de `SIMULAR_CAPTURA.bat` presiona **`[3]`**: verás la respuesta `401 {"error": "No autorizado"}` y el registro automático de intento con token inválido.
7. **Recuperación auditada de clave (`CU16` / `CU17`, opcional):** en la pantalla de login entra a *¿Olvidaste tu contraseña?* con `operador1` → como `admin` verás el aviso pendiente en *Usuarios* para emitir una clave temporal con cambio obligatorio.

> **Frase clave de arquitectura:** *«En planta, el Jetson con APP-AZA publica cada ráfaga analizada a este mismo endpoint REST mediante un token SHA-256 revocable; en sala, `simular_captura.bat` inyecta exactamente ese mismo JSON para validar toda la cadena de trazabilidad y alarmas en tiempo real.»*

### Solución rápida de problemas
| Síntoma | Solución con `.bat` | Equivalente por consola |
| :--- | :--- | :--- |
| «Usuario o contraseña incorrectos» o cuenta bloqueada 15 min | Ejecuta `INICIAR_AZA.bat` → opción **`[1]`** | `python manage.py preparar_demo` |
| Quieres limpiar alarmas/observaciones de pruebas previas | Ejecuta `INICIAR_AZA.bat` → opción **`[2]`** | Borrar `db.sqlite3`, `migrate` y `preparar_demo --con-datos` |
| El simulador responde `401` sin haber revocado el token | Ejecuta `INICIAR_AZA.bat` → **`[1]`** (resincroniza `.demo_token.txt`) | `python manage.py preparar_demo --guardar-tokens` |
| El simulador responde `404` o `409` «lote cerrado» | `INICIAR_AZA.bat` → **`[1]`** reabre `LT-DEMO-01` automáticamente | `--lote LT-DEMO-01` o reabrir en *Administración → Lotes* |
| El simulador responde `429` | Superaste 120 envíos/min: espera 60 s o usa opciones `[1]`/`[2]` | Subir `--cada` en `simulador.py` |
| El navegador no carga `127.0.0.1:8000` | Verifica que la ventana de `INICIAR_AZA.bat` siga abierta | `python manage.py runserver` |
| `Activate.ps1 no se puede cargar` en PowerShell | Usa directamente `INICIAR_AZA.bat` (no requiere `Activate.ps1`) | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |

---

## 6. Pruebas Automatizadas, Rendimiento y Seguridad (Apartado 9)

```powershell
# 68 pruebas unitarias (PU), integración (PI), seguridad (PS) y funcionales sin navegador (PF)
.venv\Scripts\python.exe manage.py test trazabilidad cuentas -v 2

# 8 pruebas End-to-End (PF) en navegador Chromium real + generación de las 10 capturas en capturas/
.venv\Scripts\python.exe manage.py test e2e -v 2

# Auditoría estática SAST y vulnerabilidades de dependencias
bandit -r aza cuentas trazabilidad -x "*/tests.py,*/migrations/*" -ll
pip-audit -r requirements.txt
```
- **Total automatizado:** **76 pruebas** (`68` backend + `8` E2E Playwright), cada una identificada con el código del protocolo de pruebas del informe. `e2e/test_navegador.py` incluye detección automática de Chromium local cuando la red bloquea descargas adicionales.
- **Pruebas de carga y estrés (Locust):** `python pruebas/preparar_carga.py` seguido de los escenarios definidos en `pruebas/locustfile.py`.
- **CI/CD y hooks:** `.github/workflows/ci.yml` ejecuta toda la batería contra PostgreSQL real en cada push; `.pre-commit-config.yaml` valida `gitleaks`, `Bandit` y `flake8` antes de cada commit.

---

## 7. Qué se corrigió respecto de APP-AZA (código legacy)

| Limitación en APP-AZA (Legacy) | Solución implementada en `aza_web` |
| :--- | :--- |
| Flag binario `is_admin` (`0`/`1`) | Tabla `Rol` (`Operador`, `Supervisor`, `Administrador`) y control RBAC `403` en servidor por vista |
| Credencial fija `admin` / `1234` en código fuente | Cero credenciales por defecto en producción: variables `ADMIN_USER`/`ADMIN_INITIAL_PASSWORD` + `CU02` |
| `PBKDF2` 100.000 it. con fallback `SHA-256` sin sal | `PBKDF2-HMAC-SHA256` de **600.000 iteraciones** con sal aleatoria; sin fallback inseguro |
| Tabla plana `registros` con receta en texto libre | Modelo relacional 3FN (`Receta`, `Lote`, `RegistroInspeccion`) con `PROTECT` e historial inmutable de límites |
| Estado como string libre | Catálogos normalizados `EstadoInspeccion` y `Turno` (migración semilla `0002`) |
| SQLite aislado dentro del Jetson | PostgreSQL centralizado (o SQLite en desarrollo) accesible desde cualquier estación de planta |
| `metricas.json` aislado en carpetas locales | Persistido en columna `metricas` (`JSONB`) y visualizado como telemetría estructurada en la web |
| Sin bitácora de observaciones ni auditoría | Entidades `Observacion` (autor + estampa temporal), `Alarma` y bitácora rotativa `logs/seguridad.log` |
| Monitor LAN puerto `8080` abierto sin login | Sesiones autenticadas con expiración por inactividad (30 min), `HttpOnly`, `CSRF` y `SameSite=Lax` |
| Sin API autenticada ni revocación | Endpoint REST con tokens individuales revocables almacenados como hash `SHA-256` (`CU13`/`CU15`/`CU18`) |
| Consultas SQL concatenadas manualmente | ORM de Django con consultas 100% parametrizadas |
| Borrado físico de cuentas de usuario | Solo desactivación lógica; protección contra auto-desactivación o auto-degradación del Administrador |

---

## 8. Mapa informe → código fuente

- **Lanzadores automáticos Windows:** `iniciar_aza.bat` y `simular_captura.bat` (más accesos directos `INICIAR_AZA.bat` y `SIMULAR_CAPTURA.bat` en la carpeta superior).
- **Modelo de datos (apartado 6.2):** `cuentas/models.py` (`Rol`, `Usuario`), `cuentas/hashers.py` (`PBKDF2600k`) y `trazabilidad/models.py` (`Receta`, `Lote`, `RegistroInspeccion`, `EstadoInspeccion`, `Turno`, `Observacion`, `Alarma`, `TokenApi`).
- **Lógica de dominio e ingesta API (`CU13`, `CU15`):** `trazabilidad/services.py`, `trazabilidad/api.py` y `simulador.py`.
- **Autenticación y autorización (`CU01`, `CU02`, `CU16`):** `cuentas/views.py`, `cuentas/middleware.py` y `cuentas/decorators.py`.
- **Vistas SCADA, cálculo SPC (`Cp`/`Cpk`) y plantillas (`CU03`–`CU18`):** `trazabilidad/views.py`, `templates/` (18 plantillas HTML) y `static/` (`aza.css` + `vendor/chart.umd.min.js` local).
- **Comandos de administración:** `trazabilidad/management/commands/init_aza.py`, `seed_demo.py` y `preparar_demo.py`.
- **Protocolo de pruebas (apartado 9):** `trazabilidad/tests.py` (68 pruebas backend), `e2e/test_navegador.py` (8 pruebas E2E Chromium) y `pruebas/` (Locust).

## 9. Parámetros operativos a validar en planta (Anexo B del informe)
Rangos horarios de turnos (`06:00–14:00`, `14:00–22:00`, `22:00–06:00`), frecuencia de refresco en sala (`5 s`), severidad por tipo de alarma, política de contraseñas (`12` caracteres mínimos, bloqueo de `15 min` tras `5` intentos fallidos) y umbral de rate-limiting en la API (`120` peticiones/minuto por IP).
