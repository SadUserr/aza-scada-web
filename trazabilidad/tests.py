"""Plan de pruebas del informe (apartado 9). Cada prueba lleva el ID del caso de prueba (PU, PI, PS, PF)
para que el resultado de `python manage.py test -v 2` se pueda trasladar directo a las tablas 42 a 45."""
import json
from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.test import Client, TestCase
from django.utils import timezone

from cuentas.models import Rol, Usuario
from cuentas.politica import validar_politica
from .forms import LoteForm, UsuarioForm
from .models import Alarma, EstadoInspeccion, Lote, Observacion, Receta, RegistroAuditoria, RegistroInspeccion, TokenApi, Turno
from .services import evaluar_estado, validar_datos

CLAVE = "Clave#Segura2026"


def mk_user(username, rol, pwd=CLAVE, cambio=False):
    r, _ = Rol.objects.get_or_create(nombre=rol)
    u = Usuario(username=username, nombre_completo=username.title(), rol=r, cambio_obligatorio=cambio)
    u.set_password(pwd)
    u.save()
    return u


def mk_receta(nombre="TF-6", lo=12.0, hi=13.0, letra="A"):
    return Receta.objects.create(codigo_letra=letra, nombre=nombre, espesor_mm=6.0, material="SAE 1008", min_tol=lo, max_tol=hi)


def mk_registro(lote, batch, angulo, estado="Aprobado", **kw):
    return RegistroInspeccion.objects.create(
        lote=lote, id_batch=batch, angulo=angulo, receta=lote.receta, estado=EstadoInspeccion.objects.get(nombre=estado),
        limite_min=lote.receta.min_tol if lote.receta else None, limite_max=lote.receta.max_tol if lote.receta else None, **kw)


def login(username, pwd=CLAVE):
    c = Client()
    c.post("/login/", {"username": username, "password": pwd})
    return c


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.op, self.sup, self.adm = mk_user("op", "Operador"), mk_user("sup", "Supervisor"), mk_user("adm", "Administrador")
        self.receta = mk_receta()
        self.lote = Lote.objects.create(codigo="L1", receta=self.receta)
        _, self.tok = TokenApi.crear("Simulador", self.adm)

    def api(self, body, tok=None, raw=None):
        h = {} if tok == "" else {"HTTP_AUTHORIZATION": f"Bearer {self.tok if tok is None else tok}"}
        return Client().post("/api/inspecciones", raw if raw is not None else json.dumps(body),
                             content_type="application/json", **h)


# ============================================================ Pruebas unitarias (Tabla 42)
class PruebasUnitarias(Base):
    def test_PU01_angulo_dentro_de_tolerancia(self):
        self.assertEqual(evaluar_estado(12.5, self.receta)[0], "Aprobado")

    def test_PU02_angulo_sobre_limite_superior(self):
        self.assertEqual(evaluar_estado(13.4, self.receta)[0], "Rechazado")

    def test_PU03_angulo_bajo_limite_inferior(self):
        self.assertEqual(evaluar_estado(11.6, self.receta)[0], "Rechazado")

    def test_PU04_lote_requiere_receta(self):
        self.assertFalse(LoteForm({"codigo": "L-SIN", "cantidad": 10}).is_valid())
        with self.assertRaises(IntegrityError):
            Lote.objects.create(codigo="L-SIN")

    def test_PU05_angulo_igual_al_minimo(self):
        self.assertEqual(evaluar_estado(12.0, self.receta)[0], "Aprobado")

    def test_PU06_angulo_igual_al_maximo(self):
        self.assertEqual(evaluar_estado(13.0, self.receta)[0], "Aprobado")

    def test_PU07_angulo_fuera_de_rango_fisico(self):
        for ang in (-0.1, 180.1, float("nan")):
            datos, error = validar_datos({"lote": "L1", "id_batch": "B", "angulo": ang})
            self.assertIsNone(datos)
            self.assertTrue(error.startswith("angulo"))

    def test_PU08_hash_genera_sal_unica(self):
        u2 = mk_user("op2", "Operador")
        self.assertNotEqual(self.op.password, u2.password)
        self.assertTrue(self.op.password.startswith("pbkdf2_sha256$600000$"))

    def test_PU09_verificacion_contrasena_correcta(self):
        self.assertTrue(self.op.check_password(CLAVE))

    def test_PU10_verificacion_contrasena_incorrecta(self):
        self.assertFalse(self.op.check_password("otra"))

    def test_PU11_contrasena_incumple_politica(self):
        fallos = validar_politica("abc123")
        self.assertEqual(len(fallos), 3)                       # largo, combinación y carácter especial
        self.assertIn("Debe ser distinta de la contraseña temporal", validar_politica("Temporal#2026x", "Temporal#2026x"))
        self.assertEqual(validar_politica("Nueva#Clave2026", "Temporal1"), [])

    def test_PU12_bloqueo_tras_intentos_fallidos(self):
        c = Client()
        for _ in range(settings.MAX_INTENTOS_FALLIDOS):
            c.post("/login/", {"username": "op", "password": "mala"})
        self.op.refresh_from_db()
        self.assertTrue(self.op.bloqueado)

    def test_PU13_receta_con_nombre_duplicado(self):
        with self.assertRaises(IntegrityError):
            mk_receta("TF-6")

    def test_PU14_receta_con_tolerancias_invertidas(self):
        with self.assertRaises(Exception):
            Receta(nombre="X", espesor_mm=6, material="A", min_tol=60, max_tol=30).full_clean()
        with self.assertRaises(IntegrityError):                # CHECK en la base de datos
            Receta.objects.create(nombre="Y", espesor_mm=6, material="A", min_tol=60, max_tol=30)

    def test_PU15_usuario_con_username_vacio(self):
        f = UsuarioForm({"nombre_completo": "Ana", "username": "", "rol": Rol.objects.get(nombre="Operador").pk})
        self.assertFalse(f.is_valid())
        self.assertIn("username", f.errors)

    def test_PU16_usuario_sin_rol(self):
        self.assertFalse(UsuarioForm({"nombre_completo": "Ana", "username": "ana"}).is_valid())
        with self.assertRaises(IntegrityError):
            Usuario.objects.create(username="sinrol", nombre_completo="Sin rol")

    def test_PU17_tasa_de_aprobacion(self):
        for i, (ang, est) in enumerate([(12.5, "Aprobado")] * 4 + [(14.0, "Rechazado")]):
            mk_registro(self.lote, f"B{i}", ang, est)
        r = login("sup").get("/supervisor/")
        self.assertEqual(r.context["tasa_ap"], 80.0)

    def test_PU18_restablecer_contrasena_reinicia_bloqueo(self):
        self.op.intentos_fallidos, self.op.bloqueado_hasta = 3, timezone.now() + timedelta(minutes=10)
        self.op.save()
        login("adm").post(f"/administracion/usuarios/{self.op.pk}/", {"accion": "reset"})
        self.op.refresh_from_db()
        self.assertEqual((self.op.intentos_fallidos, self.op.bloqueado, self.op.cambio_obligatorio), (0, False, True))

    def test_PU19_turno_segun_hora(self):
        tz = timezone.get_current_timezone()
        self.assertEqual(Turno.para(timezone.make_aware(datetime(2026, 10, 19, 7, 0), tz)).nombre, "Mañana")
        self.assertEqual(Turno.para(timezone.make_aware(datetime(2026, 10, 19, 14, 0), tz)).nombre, "Tarde")
        self.assertEqual(Turno.para(timezone.make_aware(datetime(2026, 10, 19, 23, 30), tz)).nombre, "Noche")
        self.assertEqual(Turno.para(timezone.make_aware(datetime(2026, 10, 19, 5, 59), tz)).nombre, "Noche")

    def test_PU20_metricas_invalidas(self):
        for m in ("texto", [1, 2], {f"k{i}": i for i in range(60)}, {"x": "a" * 5000}):
            datos, error = validar_datos({"lote": "L1", "id_batch": "B", "angulo": 12, "metricas": m})
            self.assertIsNone(datos)
            self.assertTrue(error.startswith("metricas"))


# ============================================================ Integración y seguridad (Tabla 43)
class PruebasIntegracion(Base):
    def test_PI01_login_valido_redirige_segun_rol(self):
        c = Client()
        self.assertRedirects(c.post("/login/", {"username": "op", "password": CLAVE}), "/", fetch_redirect_response=False)
        self.assertRedirects(c.get("/"), "/operador/")

    def test_PI02_login_invalido_mensaje_generico(self):
        r = Client().post("/login/", {"username": "op", "password": "mala"})
        r2 = Client().post("/login/", {"username": "noexiste", "password": "mala"})
        self.assertContains(r, "Usuario o contraseña incorrectos")
        self.assertContains(r2, "Usuario o contraseña incorrectos")

    def test_PI03_ruta_protegida_sin_sesion(self):
        r = Client().get("/administracion/recetas/")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/login/"))

    def test_PI04_operador_intenta_crear_receta(self):
        r = login("op").post("/administracion/recetas/", {"nombre": "Z", "espesor_mm": 6, "material": "A", "min_tol": 1, "max_tol": 2})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Receta.objects.filter(nombre="Z").exists())

    def test_PI05_operador_intenta_gestionar_lotes(self):
        self.assertEqual(login("op").post("/administracion/lotes/", {"codigo": "LX", "cantidad": 1}).status_code, 403)

    def test_PI06_administrador_crea_receta(self):
        r = login("adm").post("/administracion/recetas/", {"nombre": "TF-8", "espesor_mm": 8, "material": "SAE 1008",
                                                          "min_tol": 14, "max_tol": 15})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Receta.objects.filter(nombre="TF-8", activo=True).exists())

    def test_PI07_registrar_inspeccion_completa(self):
        r = self.api({"lote": "L1", "id_batch": "B1", "angulo": 12.5})
        self.assertEqual((r.status_code, r.json()["estado"]), (201, "Aprobado"))
        self.assertIsNotNone(RegistroInspeccion.objects.get().turno)

    def test_PI08_token_de_captura_invalido(self):
        self.assertEqual(self.api({"lote": "L1", "id_batch": "B1", "angulo": 12}, tok="falso").status_code, 401)
        self.assertEqual(self.api({"lote": "L1", "id_batch": "B1", "angulo": 12}, tok="").status_code, 401)
        self.assertTrue(Alarma.objects.filter(tipo="token_invalido", nivel="informativa").exists())
        self.assertEqual(RegistroInspeccion.objects.count(), 0)

    def test_PI09_angulo_fuera_de_rango(self):
        r = self.api({"lote": "L1", "id_batch": "B1", "angulo": 200})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(RegistroInspeccion.objects.count(), 0)

    def test_PI10_lote_inexistente(self):
        self.assertEqual(self.api({"lote": "X", "id_batch": "B1", "angulo": 12}).status_code, 404)
        self.assertTrue(Alarma.objects.filter(tipo="dato_invalido").exists())

    def test_PI11_batch_repetido(self):
        self.assertEqual(self.api({"lote": "L1", "id_batch": "B1", "angulo": 12}).status_code, 201)
        self.assertEqual(self.api({"lote": "L1", "id_batch": "B1", "angulo": 12}).status_code, 409)
        self.assertEqual(RegistroInspeccion.objects.count(), 1)

    def test_PI12_no_existen_lotes_sin_receta(self):
        r = login("adm").post("/administracion/lotes/", {"codigo": "L2", "cantidad": 100})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Lote.objects.filter(codigo="L2").exists())

    def test_PI13_inspeccion_rechazada_genera_alarma_critica(self):
        r = self.api({"lote": "L1", "id_batch": "B1", "angulo": 13.4})
        self.assertEqual((r.status_code, r.json()["estado"]), (201, "Rechazado"))
        self.assertTrue(Alarma.objects.filter(tipo="rechazado", nivel="critica").exists())
        self.assertEqual((RegistroInspeccion.objects.get().limite_min, RegistroInspeccion.objects.get().limite_max), (12, 13))

    def test_PI14_consultar_alarmas_por_nivel(self):
        self.api({"lote": "L1", "id_batch": "B1", "angulo": 14})
        self.api({"lote": "NO", "id_batch": "B2", "angulo": 12})
        r = login("op").get("/operador/alarmas/?nivel=critica")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(all(a.nivel == "critica" for a in r.context["alarmas"]))
        self.assertEqual(len(r.context["alarmas"]), 1)

    def test_PI15_trazar_por_lote(self):
        mk_registro(self.lote, "B1", 12.5)
        r = login("sup").get("/supervisor/lote/?q=L1")
        self.assertEqual((r.status_code, len(r.context["insp"])), (200, 1))

    def test_PI16_consultar_por_rango_de_fechas(self):
        mk_registro(self.lote, "B1", 12.5, fecha=timezone.now() - timedelta(days=10))
        mk_registro(self.lote, "B2", 12.5)
        hoy = timezone.localdate()
        r = login("op").get(f"/operador/historial/?desde={hoy - timedelta(days=1)}&hasta={hoy}")
        self.assertEqual(r.context["page"].paginator.count, 1)

    def test_PI17_rango_de_fechas_invertido(self):
        mk_registro(self.lote, "B1", 12.5)
        r = login("op").get("/operador/historial/?desde=2026-12-31&hasta=2026-01-01")
        self.assertContains(r, "rango de fechas es inválido")
        self.assertEqual(r.context["page"].paginator.count, 0)

    def test_PI18_operador_registra_observacion(self):
        reg = mk_registro(self.lote, "B1", 12.5)
        login("op").post(f"/inspeccion/{reg.pk}/", {"tipo": "nota", "descripcion": "Revisar matriz"})
        o = Observacion.objects.get()
        self.assertEqual((o.usuario, o.registro), (self.op, reg))

    def test_PI19_exportar_reporte_csv(self):
        mk_registro(self.lote, "B1", 12.5)
        r = login("sup").get("/supervisor/exportar/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("INS-", r.content.decode())

    def test_PI20_operador_intenta_exportar(self):
        self.assertEqual(login("op").get("/supervisor/exportar/").status_code, 403)

    def test_PI21_crear_lote_con_receta(self):
        login("adm").post("/administracion/lotes/", {"codigo": "L9", "receta": self.receta.pk, "cantidad": 100})
        self.assertEqual(Lote.objects.get(codigo="L9").receta, self.receta)

    def test_PI22_crear_lote_con_codigo_duplicado(self):
        r = login("adm").post("/administracion/lotes/", {"codigo": "L1", "receta": self.receta.pk, "cantidad": 1})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Lote.objects.filter(codigo="L1").count(), 1)

    def test_PI23_cerrar_lote_ya_cerrado(self):
        fin = timezone.now()
        self.lote.fecha_fin = fin
        self.lote.save()
        login("adm").post(f"/administracion/lotes/{self.lote.pk}/cerrar/")
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.fecha_fin, fin)

    def test_PI24_eliminar_lote_con_inspecciones(self):
        mk_registro(self.lote, "B1", 12.5)
        with self.assertRaises(ProtectedError):
            self.lote.delete()
        self.assertTrue(Lote.objects.filter(pk=self.lote.pk).exists())

    def test_PI25_mensaje_de_error_comprensible(self):
        r = self.api({"lote": "L1", "id_batch": "B1"})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json(), {"error": "angulo: campo obligatorio"})

    def test_PI26_recuperacion_usuario_inexistente(self):
        r = Client().post("/recuperar/", {"username": "noexiste"})
        self.assertContains(r, "Si la cuenta existe")
        self.assertFalse(Alarma.objects.filter(tipo=Alarma.RECUPERACION).exists())

    def test_PI27_recuperacion_usuario_valido(self):
        r = Client().post("/recuperar/", {"username": "op"})
        self.assertContains(r, "Si la cuenta existe")
        self.assertTrue(Alarma.objects.filter(tipo=Alarma.RECUPERACION, usuario=self.op, atendida=False).exists())
        self.assertContains(login("adm").get("/administracion/usuarios/"), "Solicitudes de recuperación")
        r_op = login("op").get("/operador/alarmas/")                     # el Operador no ve estas solicitudes
        self.assertFalse(any(a.tipo == Alarma.RECUPERACION for a in r_op.context["alarmas"]))

    def test_PI28_administrador_cambia_rol(self):
        sup = Rol.objects.get(nombre="Supervisor")
        login("adm").post(f"/administracion/usuarios/{self.op.pk}/", {"accion": "rol", "rol": sup.pk})
        self.op.refresh_from_db()
        self.assertEqual(self.op.rol, sup)

    def test_PI29_operador_intenta_modificar_usuario(self):
        self.assertEqual(login("op").post(f"/administracion/usuarios/{self.sup.pk}/", {"accion": "toggle"}).status_code, 403)

    def test_PI30_administrador_intenta_desactivarse(self):
        login("adm").post(f"/administracion/usuarios/{self.adm.pk}/", {"accion": "toggle"})
        self.adm.refresh_from_db()
        self.assertTrue(self.adm.is_active)

    def test_PI31_administrador_crea_token(self):
        r = login("adm").post("/administracion/tokens/", {"accion": "crear", "nombre": "Cámara línea 1"})
        claro = r.context["nuevo"]
        t = TokenApi.objects.get(nombre="Cámara línea 1")
        self.assertEqual(t.token_hash, TokenApi.hash(claro))
        self.assertNotEqual(t.token_hash, claro)

    def test_PI32_operador_intenta_crear_token(self):
        self.assertEqual(login("op").post("/administracion/tokens/", {"accion": "crear", "nombre": "x"}).status_code, 403)

    def test_PI33_administrador_revoca_token(self):
        t = TokenApi.objects.get(nombre="Simulador")
        login("adm").post(f"/administracion/tokens/{t.pk}/revocar/")
        self.assertEqual(self.api({"lote": "L1", "id_batch": "B1", "angulo": 12}).status_code, 401)

    def test_PI34_ingesta_con_metricas_json(self):
        m = {"scene": "oscura", "exit_confidence": "ALTA", "angle_confidence": "MEDIA", "circle_radius": 312.4}
        r = self.api({"lote": "L1", "id_batch": "Trigger_0001", "angulo": 12.4, "carpeta": "2026-10-19/Trigger_0001",
                      "metricas": m})
        self.assertEqual(r.status_code, 201)
        reg = RegistroInspeccion.objects.get()
        self.assertEqual(reg.metricas["circle_radius"], 312.4)
        self.assertEqual(RegistroInspeccion.objects.filter(metricas__angle_confidence="MEDIA").count(), 1)
        self.assertContains(login("op").get(f"/inspeccion/{reg.pk}/"), "Métricas del análisis")
        conf = dict(login("sup").get("/supervisor/").context["por_confianza"])
        self.assertEqual(conf.get("MEDIA"), 1)

    def test_PI35_codigo_lote_con_letra_receta_y_fecha(self):
        rec_b = mk_receta("TF-10", 16.0, 17.0, letra="B")
        login("adm").post("/administracion/lotes/", {"codigo": "", "receta": rec_b.pk, "cantidad": 500})
        hoy = timezone.localdate().strftime("%Y%m%d")
        self.assertTrue(Lote.objects.filter(codigo=f"B-{hoy}-01", receta=rec_b).exists())

    def test_PI36_operador_inicia_releva_y_termina_lote(self):
        op2 = mk_user("op2", "Operador")
        login("op").post(f"/operador/lote/{self.lote.pk}/", {"accion": "iniciar"})
        self.lote.refresh_from_db()
        self.assertEqual((self.lote.operador_inicio, self.lote.operador_activo), (self.op, self.op))
        self.assertEqual(self.api({"lote": "L1", "id_batch": "L1-B01", "angulo": 12.5}).status_code, 201)
        self.assertEqual(RegistroInspeccion.objects.get(id_batch="L1-B01").operador, self.op)

        login("op2").post(f"/operador/lote/{self.lote.pk}/", {"accion": "iniciar"})
        login("op2").post(f"/operador/lote/{self.lote.pk}/", {"accion": "terminar"})
        self.lote.refresh_from_db()
        self.assertEqual((self.lote.operador_inicio, self.lote.operador_fin), (self.op, op2))
        self.assertFalse(self.lote.abierto)

    def test_PI37_estadisticas_3_turnos_y_rendimiento_operadores(self):
        mk_registro(self.lote, "B-OP1-1", 12.4, "Aprobado", operador=self.op)
        mk_registro(self.lote, "B-OP1-2", 14.0, "Rechazado", operador=self.op)
        r = login("sup").get("/supervisor/")
        self.assertEqual(len(r.context["rendimiento_turnos"]), 3)
        ops = {x["username"]: x for x in r.context["rendimiento_operadores"]}
        self.assertEqual(ops["op"]["total"], 2)
        self.assertEqual(ops["op"]["tasa"], 50.0)

    def test_PI38_auditoria_registra_usuario_y_panel_admin(self):
        c = login("adm")
        c.post("/administracion/recetas/", {"codigo_letra": "Z", "nombre": "TF-Z", "espesor_mm": 5, "material": "SAE 1010",
                                             "min_tol": 10, "max_tol": 11})
        self.assertTrue(RegistroAuditoria.objects.filter(usuario=self.adm, modulo="Recetas", accion="Creación de receta").exists())
        r = c.get("/administracion/panel/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "TF-Z")

    def test_PI39_operador_no_accede_panel_auditoria(self):
        self.assertEqual(login("op").get("/administracion/panel/").status_code, 403)


class PruebasSeguridad(Base):
    def test_PS01_inyeccion_sql_en_filtro(self):
        mk_registro(self.lote, "B1", 12.5)
        r = login("op").get("/operador/historial/", {"lote": "1' OR '1'='1", "receta": "1 OR 1=1"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["page"].paginator.count, 0)

    def test_PS02_sesion_expirada(self):
        c = login("op")
        s = c.session
        s.set_expiry(-1)
        s.save()
        r = c.get("/operador/")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/login/"))

    def test_PS03_token_de_captura_revocado(self):
        TokenApi.objects.update(activo=False)
        self.assertEqual(self.api({"lote": "L1", "id_batch": "B1", "angulo": 12}).status_code, 401)
        self.assertEqual(RegistroInspeccion.objects.count(), 0)

    def test_PS04_bloqueo_rechaza_tambien_login_valido(self):
        c = Client()
        for _ in range(5):
            c.post("/login/", {"username": "op", "password": "mala"})
        self.assertContains(c.post("/login/", {"username": "op", "password": CLAVE}), "bloqueado")

    def test_PS05_token_de_captura_no_abre_pantallas(self):
        r = Client().get("/operador/", HTTP_AUTHORIZATION=f"Bearer {self.tok}")
        self.assertEqual(r.status_code, 302)

    def test_PS06_csrf_en_formularios(self):
        c = Client(enforce_csrf_checks=True)
        self.assertEqual(c.post("/login/", {"username": "op", "password": CLAVE}).status_code, 403)

    def test_PS07_xss_en_observaciones(self):
        reg = mk_registro(self.lote, "B1", 12.5)
        c = login("op")
        c.post(f"/inspeccion/{reg.pk}/", {"tipo": "nota", "descripcion": "<script>alert(1)</script>"})
        html = c.get(f"/inspeccion/{reg.pk}/").content.decode()
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_PS08_inyeccion_de_formulas_en_csv(self):
        l2 = Lote.objects.create(codigo="=HYPERLINK(1)", receta=self.receta)
        mk_registro(l2, "B1", 12.5)
        self.assertIn("'=HYPERLINK(1)", login("sup").get("/supervisor/exportar/").content.decode())

    def test_PS09_cabeceras_de_seguridad(self):
        r = Client().get("/login/")
        self.assertEqual(r["X-Frame-Options"], "DENY")
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")

    def test_PS10_registro_de_eventos_sin_contrasenas(self):
        with self.assertLogs("aza.seguridad", level="WARNING") as cm:
            Client().post("/login/", {"username": "op", "password": "MiClaveSecreta#1"})
        self.assertTrue(any("login fallido" in m for m in cm.output))
        self.assertFalse(any("MiClaveSecreta" in m for m in cm.output))

    def test_PS11_limite_de_peticiones_api(self):
        with self.settings(API_LIMITE_POR_MINUTO=3):
            codigos = [self.api({"lote": "L1", "id_batch": f"B{i}", "angulo": 12}).status_code for i in range(4)]
        self.assertEqual(codigos[-1], 429)


# ============================================================ Funcionales sin navegador (Tabla 44)
class PruebasFuncionales(Base):
    def test_PF03_gestion_de_receta_conserva_historico(self):
        self.api({"lote": "L1", "id_batch": "B1", "angulo": 12.9})
        login("adm").post(f"/administracion/recetas/{self.receta.pk}/", {
            "nombre": "TF-6", "espesor_mm": 6, "material": "SAE 1008", "min_tol": 12.0, "max_tol": 12.5})
        self.receta.refresh_from_db()
        self.assertEqual(self.receta.max_tol, 12.5)
        self.assertEqual(RegistroInspeccion.objects.get().limite_max, 13.0)   # el histórico no cambia

    def test_PF04_cambio_de_contrasena_obligatorio(self):
        mk_user("nuevo", "Operador", "Temporal#2026x", cambio=True)
        c = login("nuevo", "Temporal#2026x")
        self.assertRedirects(c.get("/operador/"), "/cambiar-password/", fetch_redirect_response=False)
        c.post("/cambiar-password/", {"temporal": "Temporal#2026x", "nueva": "Nueva#Clave2026", "confirmacion": "Nueva#Clave2026"})
        self.assertEqual(c.get("/operador/").status_code, 200)

    def test_PF07_cierre_de_sesion_por_inactividad(self):
        self.assertEqual(settings.SESSION_COOKIE_AGE, 30 * 60)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)    # el plazo se renueva con cada actividad
