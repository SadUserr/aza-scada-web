"""Reglas de negocio: evaluación de tolerancia (6.4), CU15 (validar) y CU13 (ingesta)."""
import json
import logging
import math
from datetime import datetime, timedelta
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .auditoria import registrar_auditoria
from .models import Alarma, EstadoInspeccion, Lote, RegistroInspeccion, TokenApi, Turno

log = logging.getLogger("aza.seguridad")
METRICAS_MAX_BYTES = 4000          # tamaño máximo del metricas.json aceptado (5.6)
METRICAS_MAX_CLAVES = 50


def evaluar_estado(angulo, receta):
    """min_tol <= angulo <= max_tol -> Aprobado (bordes incluidos); fuera -> Rechazado; sin receta -> Sin Receta."""
    if receta is None:
        return RegistroInspeccion.SIN_RECETA, None, None
    ok = receta.min_tol <= angulo <= receta.max_tol
    return (RegistroInspeccion.APROBADO if ok else RegistroInspeccion.RECHAZADO), receta.min_tol, receta.max_tol


def _alarma(nivel, tipo, desc, lote=None, registro=None):
    """Agrupa alarmas repetidas iguales en 60 s para que no se use para saturar la tabla (7.2)."""
    if nivel == Alarma.INFORMATIVA and tipo in ("token_invalido", "dato_invalido"):
        desde = timezone.now() - timedelta(seconds=60)
        if Alarma.objects.filter(tipo=tipo, descripcion=desc, fecha__gte=desde).exists():
            return None
    return Alarma.objects.create(nivel=nivel, tipo=tipo, descripcion=desc, lote=lote, registro=registro)


def validar_token(token):
    """CU15 pasos 1–2: calcula el hash y lo compara con los tokens activos."""
    if not token:
        return None
    return TokenApi.objects.filter(token_hash=TokenApi.hash(token), activo=True).first()


def validar_datos(d):
    """CU15 paso 3. Devuelve (datos_limpios, error 'campo: motivo')."""
    if not isinstance(d, dict):
        return None, "cuerpo: debe ser un objeto JSON"
    for campo in ("lote", "id_batch", "angulo"):
        if d.get(campo) in (None, ""):
            return None, f"{campo}: campo obligatorio"
    lote, id_batch, ang = d["lote"], d["id_batch"], d["angulo"]
    if not isinstance(lote, str) or not 0 < len(lote) <= 50:
        return None, "lote: texto de 1 a 50 caracteres"
    if not isinstance(id_batch, (str, int)) or isinstance(id_batch, bool) or not 0 < len(str(id_batch)) <= 50:
        return None, "id_batch: texto de 1 a 50 caracteres"
    if isinstance(ang, bool) or not isinstance(ang, (int, float)) or not math.isfinite(ang):
        return None, "angulo: debe ser numérico"
    if not 0 <= ang <= 180:
        return None, "angulo: debe estar entre 0 y 180"
    fecha = timezone.now()
    if d.get("fecha"):
        try:
            fecha = parse_datetime(str(d["fecha"]))
        except ValueError:
            fecha = None
        if fecha is None:
            return None, "fecha: formato ISO 8601 inválido"
        if timezone.is_naive(fecha):
            fecha = timezone.make_aware(fecha)
        if fecha > timezone.now() + timedelta(seconds=5):                  # A3: fecha futura
            return None, "fecha: no puede ser futura"
    carpeta = str(d.get("carpeta", ""))[:255]
    metricas = d.get("metricas")
    if metricas is not None:                                               # dato semiestructurado opcional
        if not isinstance(metricas, dict):
            return None, "metricas: debe ser un objeto JSON"
        if len(metricas) > METRICAS_MAX_CLAVES or len(json.dumps(metricas)) > METRICAS_MAX_BYTES:
            return None, f"metricas: máximo {METRICAS_MAX_CLAVES} claves y {METRICAS_MAX_BYTES} bytes"
    return {"lote": lote, "id_batch": str(id_batch), "angulo": float(ang), "fecha": fecha, "carpeta": carpeta,
            "metricas": metricas}, None


def ingestar(token, payload):
    """CU13. Devuelve (http_status, cuerpo_json)."""
    tok = validar_token(token)
    if tok is None:                                                        # CU15 A1
        log.warning("api: token de captura ausente, inválido o revocado")
        _alarma(Alarma.INFORMATIVA, "token_invalido", "Intento de ingesta con token ausente, inválido o revocado")
        registrar_auditoria("API Ingesta", "Token rechazado (401)", "Intento con token ausente, inválido o revocado",
                            usuario_nombre="Estación no autorizada")
        return 401, {"error": "No autorizado"}
    datos, error = validar_datos(payload)
    if error:                                                              # CU15 A2/A3
        _alarma(Alarma.INFORMATIVA, "dato_invalido", f"Ingesta rechazada ({tok.nombre}): {error}")
        return 422, {"error": error}
    lote = Lote.objects.select_related("receta", "operador_activo", "operador_inicio").filter(codigo=datos["lote"]).first()
    if lote is None:                                                       # A4
        _alarma(Alarma.INFORMATIVA, "dato_invalido", f"Lote inexistente: {datos['lote']}")
        return 404, {"error": "Lote no encontrado"}
    if not lote.abierto:
        _alarma(Alarma.INFORMATIVA, "dato_invalido", f"Lote cerrado: {lote.codigo}", lote=lote)
        return 409, {"error": "El lote está cerrado"}
    if lote.receta is None:
        _alarma(Alarma.INFORMATIVA, "dato_invalido", f"Lote sin receta asignada: {lote.codigo}", lote=lote)
        return 422, {"error": "lote: todo lote debe tener una receta asignada"}
    estado, lmin, lmax = evaluar_estado(datos["angulo"], lote.receta)      # pasos 3–4
    operador_turno = lote.operador_activo or lote.operador_inicio
    try:
        with transaction.atomic():
            reg = RegistroInspeccion.objects.create(                       # paso 5 (guarda límites usados)
                lote=lote, id_batch=datos["id_batch"], fecha=datos["fecha"], angulo=datos["angulo"],
                receta=lote.receta, limite_min=lmin, limite_max=lmax,
                estado=EstadoInspeccion.objects.get_or_create(nombre=estado)[0], turno=Turno.para(datos["fecha"]),
                operador=operador_turno, carpeta=datos["carpeta"], metricas=datos["metricas"])
            if estado == RegistroInspeccion.RECHAZADO:                     # paso 6
                _alarma(Alarma.CRITICA, "rechazado",
                        f"{reg.codigo}: {reg.angulo}° fuera de {lmin}°–{lmax}° (lote {lote.codigo})", lote, reg)
                registrar_auditoria(
                    "Inspecciones", "Rechazo angular detectado",
                    f"{reg.codigo} ({reg.id_batch}) · {reg.angulo}° fuera de {lmin}°–{lmax}° en lote {lote.codigo}",
                    usuario=operador_turno,
                    usuario_nombre=operador_turno.username if operador_turno else f"Estación:{tok.nombre}",
                    rol_nombre=operador_turno.rol_nombre if operador_turno else "Visión Artificial",
                )
    except IntegrityError:                                                 # A3: id_batch repetido
        return 409, {"error": "id_batch ya registrado en este lote"}
    return 201, {"id": reg.pk, "codigo": reg.codigo, "estado": estado, "limite_min": lmin, "limite_max": lmax}
