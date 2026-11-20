"""Pruebas funcionales E2E automatizadas con Playwright (Tabla 44, PF-xx).
Se ejecutan con `python manage.py test e2e` si Playwright y su navegador están instalados
(`pip install -r requirements-dev.txt` y `playwright install chromium`); si no, se omiten.
Con AZA_CAPTURAS=<carpeta> además guardan capturas de pantalla para el informe."""
import json
import os
import time
import urllib.request
from pathlib import Path
from unittest import SkipTest

from django.contrib.staticfiles.testing import StaticLiveServerTestCase

os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")   # Playwright sync dentro del test de Django

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:                                            # Playwright no instalado: se omiten
    sync_playwright = None

from cuentas.models import Rol, Usuario
from datetime import time as hora
from trazabilidad.models import EstadoInspeccion, Lote, Receta, TokenApi, Turno
from trazabilidad.tests import CLAVE, mk_user

CAPTURAS = os.getenv("AZA_CAPTURAS")


class E2E(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        if sync_playwright is None:
            raise SkipTest("Playwright no está instalado")
        super().setUpClass()
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception:
            exe = next(Path.home().joinpath("AppData/Local/ms-playwright").glob("chromium-*/chrome-win64/chrome.exe"), None)
            try:
                cls.browser = cls.pw.chromium.launch(executable_path=str(exe)) if exe else cls.pw.chromium.launch(channel="chromium")
            except Exception as e:                              # navegador no descargado
                cls.pw.stop()
                super().tearDownClass()
                raise SkipTest(f"Chromium no disponible: {e}")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        super().tearDownClass()

    def setUp(self):
        for n in ("Operador", "Supervisor", "Administrador"):
            Rol.objects.get_or_create(nombre=n)
        for n in ("Aprobado", "Rechazado", "Sin Receta"):        # LiveServer vacía la BD entre pruebas:
            EstadoInspeccion.objects.get_or_create(nombre=n)      # se reponen los catálogos semilla
        for n, a, b in (("Mañana", 6, 14), ("Tarde", 14, 22), ("Noche", 22, 6)):
            Turno.objects.get_or_create(nombre=n, defaults={"hora_inicio": hora(a), "hora_fin": hora(b)})
        self.op, self.sup, self.adm = mk_user("op", "Operador"), mk_user("sup", "Supervisor"), mk_user("adm", "Administrador")
        self.receta = Receta.objects.create(nombre="TF-6 mm", espesor_mm=6, material="SAE 1008", min_tol=12, max_tol=13)
        self.lote = Lote.objects.create(codigo="LT-E2E-01", receta=self.receta, cantidad=100)
        _, self.tok = TokenApi.crear("Simulador", self.adm)
        self.page = self.browser.new_page(viewport={"width": 1366, "height": 768})

    def tearDown(self):
        self.page.close()

    # -------------------------------------------------- utilidades
    def entrar(self, usuario, page=None):
        p = page or self.page
        p.goto(self.live_server_url + "/login/")
        p.fill("input[name=username]", usuario)
        p.fill("input[name=password]", CLAVE)
        p.click("button:has-text('Ingresar')")
        p.wait_for_load_state()

    def enviar(self, batch, angulo, metricas=None):
        body = {"lote": self.lote.codigo, "id_batch": batch, "angulo": angulo, "carpeta": f"2026-10-19/{batch}"}
        if metricas:
            body["metricas"] = metricas
        req = urllib.request.Request(self.live_server_url + "/api/inspecciones", json.dumps(body).encode(),
                                     {"Content-Type": "application/json", "Authorization": f"Bearer {self.tok}"})
        with urllib.request.urlopen(req) as r:
            return r.status

    def captura(self, nombre, page=None):
        if CAPTURAS:
            Path(CAPTURAS).mkdir(parents=True, exist_ok=True)
            (page or self.page).screenshot(path=str(Path(CAPTURAS) / f"{nombre}.png"), full_page=True)

    # -------------------------------------------------- casos
    def test_PF01_flujo_completo_sin_recargar(self):
        self.enviar("Trigger_0001", 12.4)
        self.entrar("op")
        expect(self.page.locator("#h-batch")).to_have_text("Trigger_0001")
        t0 = time.monotonic()
        self.enviar("Trigger_0002", 12.7)
        expect(self.page.locator("#h-batch")).to_have_text("Trigger_0002", timeout=8000)
        demora = time.monotonic() - t0
        print(f"\n[PR-03] el nuevo resultado apareció en {demora:.1f} s (consulta cada 5 s + carga)")
        self.assertLess(demora, 6.5)
        expect(self.page.locator("#h-estado")).to_contain_text("Aprobado")
        self.captura("01_dashboard_operador")

    def test_PF02_supervisor_consulta_tendencia(self):
        for i, a in enumerate([12.3, 12.6, 13.4, 12.8, 12.1], 1):
            self.enviar(f"Trigger_{i:04d}", a)
        self.entrar("sup")
        self.captura("05_dashboard_supervisor")
        self.page.goto(self.live_server_url + f"/supervisor/tendencias/?lote={self.lote.codigo}")
        self.page.wait_for_function("window.Chart !== undefined && Chart.getChart('ch') !== undefined")
        self.assertEqual(self.page.evaluate("Chart.getChart('ch').data.datasets[0].data.length"), 5)
        self.captura("06_tendencias")

    def test_PF04_cambio_de_contrasena_obligatorio(self):
        u = Usuario.objects.get(username="op")
        u.cambio_obligatorio = True
        u.save()
        self.entrar("op")
        self.assertTrue(self.page.url.endswith("/cambiar-password/"))
        self.page.fill("input[name=temporal]", CLAVE)
        self.page.fill("input[name=nueva]", "corta")
        self.page.fill("input[name=confirmacion]", "corta")
        self.page.click("button:has-text('Guardar')")
        expect(self.page.locator(".err")).to_contain_text("Mínimo 12 caracteres")
        self.page.fill("input[name=temporal]", CLAVE)
        self.page.fill("input[name=nueva]", "Nueva#Clave2026")
        self.page.fill("input[name=confirmacion]", "Nueva#Clave2026")
        self.page.click("button:has-text('Guardar')")
        self.page.wait_for_url("**/operador/")

    def test_PF05_alarma_critica_en_vivo(self):
        self.entrar("op")
        self.page.goto(self.live_server_url + "/operador/alarmas/")
        expect(self.page.locator("#lista")).to_contain_text("Sin alarmas")
        self.enviar("Trigger_0009", 14.2)                      # fuera de 12–13 → rechazo → alarma crítica
        expect(self.page.locator("#lista")).to_contain_text("Crítica", timeout=8000)
        self.captura("03_alarmas")

    def test_PF06_observacion_con_autor_y_fecha(self):
        self.enviar("Trigger_0001", 12.4, {"scene": "oscura", "exit_confidence": "ALTA", "angle_confidence": "ALTA",
                                           "circle_method": "hough", "circle_radius": 311.7, "total_frames": 130})
        self.entrar("op")
        self.page.click("#detalle-link")
        self.page.select_option("select[name=tipo]", "nota")
        self.page.fill("textarea[name=descripcion]", "Se revisó la matriz; sin desgaste visible.")
        self.page.click("button:has-text('Guardar observación')")
        expect(self.page.locator("body")).to_contain_text("Se revisó la matriz")
        expect(self.page.locator("body")).to_contain_text("Op")                  # autor
        expect(self.page.locator("body")).to_contain_text("Métricas del análisis")
        self.captura("02_detalle_metricas")

    def test_PF09_mensaje_de_error_de_login(self):
        self.page.goto(self.live_server_url + "/login/")
        self.page.fill("input[name=username]", "op")
        self.page.fill("input[name=password]", "incorrecta")
        self.page.click("button:has-text('Ingresar')")
        expect(self.page.locator(".err")).to_have_text(
            "Usuario o contraseña incorrectos. Verifica tus datos e intenta nuevamente.")
        self.captura("00_login_error")

    def test_PF10_diseno_adaptable_tablet(self):
        tablet = self.browser.new_page(viewport={"width": 768, "height": 1024})
        try:
            self.enviar("Trigger_0001", 12.4)
            self.entrar("op", tablet)
            nav = tablet.locator("nav#menu")
            expect(nav).to_be_hidden()                          # bajo 1024 px el menú se colapsa
            self.captura("08_tablet_menu_cerrado", tablet)
            tablet.click("#menu-btn")
            expect(nav).to_be_visible()
            self.captura("09_tablet_menu_abierto", tablet)
            ancho = tablet.evaluate("document.documentElement.scrollWidth")
            self.assertLessEqual(ancho, 768)                    # sin desplazamiento horizontal
        finally:
            tablet.close()

    def test_PF12_administrador_gestiona_tokens_y_solicitudes(self):
        self.page.goto(self.live_server_url + "/recuperar/")
        self.page.fill("input[name=username]", "op")
        self.page.click("button:has-text('Enviar solicitud')")
        expect(self.page.locator(".msg")).to_contain_text("Si la cuenta existe")
        self.entrar("adm")
        expect(self.page.locator("body")).to_contain_text("Solicitudes de recuperación")
        self.captura("07_usuarios_solicitud")
        self.page.goto(self.live_server_url + "/administracion/tokens/")
        self.page.fill("input[name=nombre]", "Cámara línea 1 (APP-AZA)")
        self.page.click("button:has-text('Generar token')")
        expect(self.page.locator(".msg.warning")).to_contain_text("se muestra una sola vez")
        self.captura("04_tokens_captura")
        self.page.goto(self.live_server_url + "/administracion/panel/")
        expect(self.page.locator("body")).to_contain_text("Bitácora de auditoría")
        expect(self.page.locator("body")).to_contain_text("Emisión de token")
        self.captura("10_admin_panel_auditoria")
