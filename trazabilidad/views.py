import csv
import logging
import secrets
from datetime import timedelta
from django.contrib import messages
from django.db.models import Avg, Count, Max, Min, ProtectedError, Q
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from cuentas.decorators import rol_requerido
from cuentas.models import Rol, Usuario
from .auditoria import registrar_auditoria
from .forms import LoteForm, ObservacionForm, RecetaForm, TokenForm, UsuarioForm
from .models import Alarma, EstadoInspeccion, Lote, Receta, RegistroAuditoria, RegistroInspeccion, TokenApi, Turno

log = logging.getLogger("aza.seguridad")

OP, SUP, ADM = Rol.OPERADOR, Rol.SUPERVISOR, Rol.ADMINISTRADOR


def _estados():
    return [(e.nombre, e.nombre) for e in EstadoInspeccion.objects.exclude(nombre=RegistroInspeccion.SIN_RECETA).order_by("id")]


def _filtrar(request, qs, defecto_dias=None):
    """Filtros combinables (fechas, lote, receta, estado, turno, operador). Devuelve (qs, error, valores)."""
    g = request.GET
    desde, hasta = parse_date(g.get("desde", "") or ""), parse_date(g.get("hasta", "") or "")
    if not g and defecto_dias:
        desde = (timezone.localdate() - timedelta(days=defecto_dias))
    if desde and hasta and desde > hasta:                                   # A2: rango inválido -> no consulta
        return qs.none(), "El rango de fechas es inválido (la fecha inicial es posterior a la final).", g
    if desde:
        qs = qs.filter(fecha__date__gte=desde)
    if hasta:
        qs = qs.filter(fecha__date__lte=hasta)
    if g.get("lote"):
        qs = qs.filter(lote__codigo__icontains=g["lote"])
    if g.get("receta", "").isdigit():
        qs = qs.filter(receta_id=int(g["receta"]))
    if g.get("estado") in dict(_estados()):
        qs = qs.filter(estado__nombre=g["estado"])
    if g.get("turno", "").isdigit():
        qs = qs.filter(turno_id=int(g["turno"]))
    if g.get("operador", "").isdigit():
        qs = qs.filter(operador_id=int(g["operador"]))
    if g.get("con_obs") == "1":
        qs = qs.filter(observaciones__isnull=False).distinct()
    return qs, None, {"desde": desde or "", "hasta": hasta or "", "lote": g.get("lote", ""),
                      "receta": g.get("receta", ""), "estado": g.get("estado", ""),
                      "turno": g.get("turno", ""), "operador": g.get("operador", ""),
                      "con_obs": g.get("con_obs", "")}


def _kpis_operador():
    hoy = timezone.localdate()
    qs_hoy = RegistroInspeccion.objects.filter(fecha__date=hoy)
    total = qs_hoy.count()
    ap = qs_hoy.filter(estado__nombre=RegistroInspeccion.APROBADO).count()
    re = qs_hoy.filter(estado__nombre=RegistroInspeccion.RECHAZADO).count()
    return {
        "hoy_total": total,
        "hoy_ap": ap,
        "hoy_re": re,
        "hoy_tasa": round(ap * 100 / total, 1) if total else 0,
        "lotes_abiertos": Lote.objects.filter(fecha_fin__isnull=True).count(),
        "criticas_activas": Alarma.de_proceso().filter(nivel=Alarma.CRITICA, atendida=False).count(),
    }


def _rendimiento_turnos(qs):
    """Devuelve estadísticas comparativas garantizando los 3 turnos de planta."""
    agg = {
        row["turno_id"]: row
        for row in qs.values("turno_id").annotate(
            total=Count("id"),
            aprobados=Count("id", filter=Q(estado__nombre=RegistroInspeccion.APROBADO)),
            rechazados=Count("id", filter=Q(estado__nombre=RegistroInspeccion.RECHAZADO)),
            prom=Avg("angulo"),
        )
    }
    resultado = []
    for t in Turno.objects.order_by("id"):
        d = agg.get(t.pk, {})
        tot = d.get("total", 0)
        ap = d.get("aprobados", 0)
        re = d.get("rechazados", 0)
        prom = d.get("prom")
        resultado.append({
            "nombre": t.nombre,
            "horario": f"{t.hora_inicio:%H:%M}–{t.hora_fin:%H:%M}",
            "total": tot,
            "aprobados": ap,
            "rechazados": re,
            "tasa": round(ap * 100 / tot, 1) if tot else 0,
            "prom": round(prom, 2) if prom is not None else None,
        })
    return resultado


def _rendimiento_operadores(qs):
    """Estadísticas de productividad y calidad por operador (incluye lotes iniciados/terminados)."""
    agg = {
        row["operador_id"]: row
        for row in qs.filter(operador__isnull=False).values("operador_id").annotate(
            total=Count("id"),
            aprobados=Count("id", filter=Q(estado__nombre=RegistroInspeccion.APROBADO)),
            rechazados=Count("id", filter=Q(estado__nombre=RegistroInspeccion.RECHAZADO)),
            prom=Avg("angulo"),
        )
    }
    iniciados = dict(Lote.objects.filter(operador_inicio__isnull=False).values_list("operador_inicio_id").annotate(n=Count("id")))
    finalizados = dict(Lote.objects.filter(operador_fin__isnull=False).values_list("operador_fin_id").annotate(n=Count("id")))
    operadores = Usuario.objects.filter(rol__nombre=OP).order_by("username")
    filas = []
    for u in operadores:
        d = agg.get(u.pk, {})
        tot = d.get("total", 0)
        ap = d.get("aprobados", 0)
        re = d.get("rechazados", 0)
        prom = d.get("prom")
        ini = iniciados.get(u.pk, 0)
        fin = finalizados.get(u.pk, 0)
        if tot or ini or fin or u.is_active:
            filas.append({
                "id": u.pk,
                "username": u.username,
                "nombre": u.nombre_completo or u.username,
                "activo": u.is_active,
                "total": tot,
                "aprobados": ap,
                "rechazados": re,
                "tasa": round(ap * 100 / tot, 1) if tot else 0,
                "prom": round(prom, 2) if prom is not None else None,
                "iniciados": ini,
                "finalizados": fin,
            })
    filas.sort(key=lambda x: (-x["total"], x["username"]))
    return filas


# ---------------------------------------------------------------- Operador
@rol_requerido(OP)
def op_inspeccion(request):                                              # CU03
    ultima = RegistroInspeccion.objects.select_related(
        "lote", "lote__operador_inicio", "lote__operador_activo", "lote__operador_fin", "receta", "estado", "turno", "operador"
    ).first()
    lotes_activos = Lote.objects.filter(fecha_fin__isnull=True).select_related(
        "receta", "operador_inicio", "operador_activo"
    ).order_by("-fecha_inicio")
    ctx = {
        "ultima": ultima,
        "ultima_conf": (ultima.metricas or {}).get("angle_confidence", "ESTÁNDAR") if ultima else "EN ESPERA",
        "alarmas": Alarma.de_proceso()[:5],
        "lotes_activos": lotes_activos,
        **_kpis_operador(),
    }
    return render(request, "operador/inspeccion.html", ctx)


@rol_requerido(OP)
@require_POST
def op_lote_accion(request, pk):
    """Permite al operador iniciar/relevar o finalizar un disco/lote en planta."""
    l = get_object_or_404(Lote, pk=pk)
    accion = request.POST.get("accion")
    if not l.abierto:
        messages.error(request, f"El lote {l.codigo} ya fue finalizado.")
        return redirect("op_inspeccion")
    if accion == "iniciar":
        era_nuevo = l.operador_inicio_id is None
        if era_nuevo:
            l.operador_inicio = request.user
        l.operador_activo = request.user
        l.save(update_fields=["operador_inicio", "operador_activo"])
        verbo = "inició el lote" if era_nuevo else "asumió el turno del lote"
        registrar_auditoria("Operación en Línea", "Inicio / Relevo de lote",
                            f"{request.user.username} {verbo} {l.codigo}", request=request)
        messages.success(request, f"Has asumido la operación en línea del lote {l.codigo}.")
    elif accion == "terminar":
        if l.operador_inicio_id is None:
            l.operador_inicio = request.user
        l.operador_fin = request.user
        l.operador_activo = None
        l.fecha_fin = timezone.now()
        l.save(update_fields=["operador_inicio", "operador_fin", "operador_activo", "fecha_fin"])
        registrar_auditoria("Operación en Línea", "Término de lote / disco",
                            f"{request.user.username} finalizó el lote {l.codigo}", request=request)
        messages.success(request, f"Lote {l.codigo} finalizado y cerrado por {request.user.nombre_completo}.")
    return redirect("op_inspeccion")


@rol_requerido(OP)
def op_ultima_json(request):                                             # actualización sin recargar
    r = RegistroInspeccion.objects.select_related(
        "lote", "lote__operador_inicio", "lote__operador_activo", "receta", "estado", "turno", "operador"
    ).first()
    return JsonResponse({
        "ultima": r and {
            "id": r.pk, "codigo": r.codigo, "estado": r.estado.nombre, "angulo": r.angulo,
            "lote": r.lote.codigo, "batch": r.id_batch, "receta": r.receta.nombre if r.receta else "Sin receta",
            "material": f"{r.receta.material} · Ø{r.receta.espesor_mm} mm" if r.receta else "Sin especificación",
            "turno": r.turno.nombre if r.turno else "—",
            "operador": (r.operador.nombre_completo if r.operador else (r.lote.operador_activo.nombre_completo if r.lote.operador_activo else "—")),
            "op_inicio": r.lote.operador_inicio.nombre_completo if r.lote.operador_inicio else "Pendiente",
            "confianza": (r.metricas or {}).get("angle_confidence", "ESTÁNDAR"),
            "min": r.limite_min, "max": r.limite_max,
            "hora": timezone.localtime(r.fecha).strftime("%d/%m %H:%M:%S"),
        },
        "kpis": _kpis_operador(),
        "alarmas": [{"nivel": a.nivel, "tipo": a.tipo, "texto": a.descripcion,
                     "hora": timezone.localtime(a.fecha).strftime("%d/%m %H:%M:%S")} for a in Alarma.de_proceso()[:5]]})


@rol_requerido(OP)
def op_historial(request):                                               # CU04
    qs, error, f = _filtrar(request, RegistroInspeccion.objects.select_related("lote", "receta", "estado", "turno", "operador"))
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "operador/historial.html", {
        "page": page, "error": error, "f": f, "recetas": Receta.objects.all(), "estados": _estados(),
        "turnos": Turno.objects.order_by("id"), "operadores": Usuario.objects.filter(rol__nombre=OP).order_by("username")})


@rol_requerido(OP)
def op_alarmas(request):                                                 # CU05
    nivel = request.GET.get("nivel")
    base_qs = Alarma.de_proceso().select_related("lote", "registro")
    counts = {
        "todas": base_qs.count(),
        "critica": base_qs.filter(nivel=Alarma.CRITICA).count(),
        "informativa": base_qs.filter(nivel=Alarma.INFORMATIVA).count(),
    }
    qs = base_qs.filter(nivel=nivel) if nivel in (Alarma.CRITICA, Alarma.INFORMATIVA) else base_qs
    return render(request, "operador/alarmas.html", {"alarmas": qs[:100], "nivel": nivel, "counts": counts})


@rol_requerido(OP)
@require_POST
def op_alarma_atender(request, pk):
    a = get_object_or_404(Alarma.de_proceso(), pk=pk)
    if not a.atendida:
        a.atendida = True
        a.save(update_fields=["atendida"])
        registrar_auditoria("Alarmas", "Reconocimiento de alarma", f"Marcó como atendida la alarma #{a.pk} ({a.tipo})", request=request)
        messages.success(request, "Alarma marcada como atendida.")
    nivel = request.POST.get("nivel")
    if nivel in (Alarma.CRITICA, Alarma.INFORMATIVA):
        return redirect(f"{reverse('op_alarmas')}?nivel={nivel}")
    return redirect("op_alarmas")


@rol_requerido(OP, SUP)
def detalle(request, pk):                                                # detalle + CU14
    reg = get_object_or_404(
        RegistroInspeccion.objects.select_related(
            "lote", "lote__operador_inicio", "lote__operador_fin", "receta", "estado", "turno", "operador"
        ), pk=pk
    )
    form = ObservacionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        o = form.save(commit=False)
        o.registro, o.usuario = reg, request.user                        # autor y fecha automáticos
        o.save()
        registrar_auditoria("Inspecciones", "Observación técnica registrada",
                            f"{reg.codigo} [{o.get_tipo_display()}]: {o.descripcion[:100]}", request=request)
        messages.success(request, "Observación guardada.")
        return redirect("detalle", pk=pk)
    raw_m = reg.metricas or {}
    metricas = sorted(raw_m.items())
    desviacion = None
    if reg.limite_min is not None and reg.limite_max is not None:
        nominal = round((reg.limite_min + reg.limite_max) / 2, 2)
        desviacion = {"nominal": nominal, "delta": round(reg.angulo - nominal, 2),
                      "margen_inf": round(reg.angulo - reg.limite_min, 2),
                      "margen_sup": round(reg.limite_max - reg.angulo, 2)}
    resumen_m = {
        "confianza_angulo": raw_m.get("angle_confidence"),
        "confianza_salida": raw_m.get("exit_confidence"),
        "escena": raw_m.get("scene"),
        "metodo_circulo": raw_m.get("circle_method"),
        "radio_circulo": raw_m.get("circle_radius"),
        "frames": raw_m.get("total_frames"),
    }
    return render(request, "detalle.html", {
        "r": reg, "form": form, "metricas": metricas, "resumen_m": resumen_m, "desviacion": desviacion,
        "obs": reg.observaciones.select_related("usuario")})


# ---------------------------------------------------------------- Supervisor
@rol_requerido(SUP)
def sup_dashboard(request):                                              # CU06
    qs, error, f = _filtrar(request, RegistroInspeccion.objects.all(), defecto_dias=7)
    total = qs.count()
    aprobados = qs.filter(estado__nombre=RegistroInspeccion.APROBADO).count()
    rechazados = qs.filter(estado__nombre=RegistroInspeccion.RECHAZADO).count()

    def agrupar(campo, vacio):
        filas = qs.values(campo).annotate(n=Count("id")).order_by(campo)
        return [(x[campo] or vacio, x["n"]) for x in filas]

    return render(request, "supervisor/dashboard.html", {
        "total": total, "aprobados": aprobados, "rechazados": rechazados, "error": error, "f": f,
        "tasa_ap": round(aprobados * 100 / total, 1) if total else 0,
        "tasa_re": round(rechazados * 100 / total, 1) if total else 0,
        "por_turno": agrupar("turno__nombre", "Sin turno"), "por_receta": agrupar("receta__nombre", "Sin receta"),
        # Consulta sobre el dato semiestructurado (metricas.json de cada ráfaga): confianza del ángulo
        "por_confianza": agrupar("metricas__angle_confidence", "Sin métricas"),
        "rendimiento_turnos": _rendimiento_turnos(qs),
        "rendimiento_operadores": _rendimiento_operadores(qs),
        "recetas": Receta.objects.all(), "estados": _estados(),
        "turnos": Turno.objects.order_by("id"), "operadores": Usuario.objects.filter(rol__nombre=OP).order_by("username")})


@rol_requerido(SUP)
def sup_tendencias(request):                                             # CU07
    qs, error, f = _filtrar(request, RegistroInspeccion.objects.select_related("estado"), defecto_dias=7)
    pts = list(qs.order_by("-fecha")[:500])[::-1]                        # A3: máx. 500 puntos
    angulos = [p.angulo for p in pts]
    stats_tend = {
        "n": len(pts),
        "min": round(min(angulos), 2) if angulos else None,
        "prom": round(sum(angulos) / len(angulos), 2) if angulos else None,
        "max": round(max(angulos), 2) if angulos else None,
        "rechazos": sum(1 for p in pts if p.estado.nombre == RegistroInspeccion.RECHAZADO),
    }
    data = {"labels": [timezone.localtime(p.fecha).strftime("%d/%m %H:%M") for p in pts],
            "angulo": angulos, "min": [p.limite_min for p in pts],
            "max": [p.limite_max for p in pts], "estado": [p.estado.nombre for p in pts],
            "batches": [p.id_batch for p in pts], "ids": [p.pk for p in pts]}
    return render(request, "supervisor/tendencias.html", {
        "data": data, "stats_tend": stats_tend, "error": error, "f": f,
        "recetas": Receta.objects.all(), "estados": _estados(),
        "turnos": Turno.objects.order_by("id"), "operadores": Usuario.objects.filter(rol__nombre=OP).order_by("username")})


@rol_requerido(SUP)
def sup_lote(request):                                                   # CU08
    q = request.GET.get("q", "").strip()
    lote, insp, aviso, lote_stats = None, [], None, None
    if q:
        lote = Lote.objects.select_related("receta", "operador_inicio", "operador_activo", "operador_fin").filter(codigo=q).first()
        if not lote:
            aviso = "Lote no encontrado"                                 # A1
        else:
            insp = list(lote.inspecciones.select_related("estado", "turno", "operador").prefetch_related("observaciones", "alarmas"))
            total = len(insp)
            ap = sum(1 for x in insp if x.estado.nombre == RegistroInspeccion.APROBADO)
            re = sum(1 for x in insp if x.estado.nombre == RegistroInspeccion.RECHAZADO)
            lote_stats = {
                "total": total, "aprobados": ap, "rechazados": re,
                "tasa_ap": round(ap * 100 / total, 1) if total else 0,
                "avance": min(100, round(total * 100 / lote.cantidad, 1)) if lote.cantidad else None,
            }
    lotes_recientes = Lote.objects.select_related("receta").order_by("-fecha_inicio")[:8]
    return render(request, "supervisor/lote.html", {
        "q": q, "lote": lote, "insp": insp, "aviso": aviso, "lote_stats": lote_stats, "lotes_recientes": lotes_recientes})


def _celda(v):
    s = str(v)
    return "'" + s if s[:1] in "=+-@" else s                             # evita inyección de fórmulas en Excel


@rol_requerido(SUP, ADM)
def sup_informe_gestion(request):                                        # Informe ejecutivo de gestión (visualización + impresión/PDF)
    qs, error, f = _filtrar(
        request,
        RegistroInspeccion.objects.select_related("lote", "receta", "estado", "turno", "operador"),
        defecto_dias=7,
    )
    if error:
        messages.error(request, error)
    tot = qs.count()
    ap = qs.filter(estado__nombre=RegistroInspeccion.APROBADO).count()
    re_ = qs.filter(estado__nombre=RegistroInspeccion.RECHAZADO).count()
    tasa_ap = round(ap * 100 / tot, 1) if tot else 0
    tasa_re = round(re_ * 100 / tot, 1) if tot else 0
    ang = qs.aggregate(prom=Avg("angulo"), minimo=Min("angulo"), maximo=Max("angulo"))
    turnos = _rendimiento_turnos(qs)
    operadores = _rendimiento_operadores(qs)

    # Desglose de conformidad por receta
    rec_rows = (
        qs.values("receta__codigo_letra", "receta__nombre", "receta__min_tol", "receta__max_tol")
        .annotate(
            total=Count("id"),
            aprobados=Count("id", filter=Q(estado__nombre=RegistroInspeccion.APROBADO)),
            rechazados=Count("id", filter=Q(estado__nombre=RegistroInspeccion.RECHAZADO)),
            prom=Avg("angulo"),
        )
        .order_by("-total")
    )
    por_receta = []
    for r in rec_rows:
        rt = r["total"]
        por_receta.append({
            "letra": r["receta__codigo_letra"] or "—",
            "nombre": r["receta__nombre"] or "Sin receta",
            "min_tol": r["receta__min_tol"],
            "max_tol": r["receta__max_tol"],
            "total": rt,
            "aprobados": r["aprobados"],
            "rechazados": r["rechazados"],
            "prom": round(r["prom"], 2) if r["prom"] is not None else None,
            "tasa": round(r["aprobados"] * 100 / rt, 1) if rt else 0,
        })

    # Lotes involucrados en el período
    lote_ids = list(qs.values_list("lote_id", flat=True).distinct())
    lotes_periodo = (
        Lote.objects.filter(pk__in=lote_ids)
        .select_related("receta", "operador_inicio", "operador_activo", "operador_fin")
        .annotate(
            n_insp=Count("inspecciones", filter=Q(inspecciones__in=qs)),
            n_rech=Count("inspecciones", filter=Q(inspecciones__in=qs, inspecciones__estado__nombre=RegistroInspeccion.RECHAZADO)),
        )
        .order_by("-fecha_inicio")
    )

    alarmas_qs = Alarma.de_proceso().filter(nivel=Alarma.CRITICA).select_related("lote", "registro")
    if f["desde"]:
        alarmas_qs = alarmas_qs.filter(fecha__date__gte=f["desde"])
    if f["hasta"]:
        alarmas_qs = alarmas_qs.filter(fecha__date__lte=f["hasta"])
    if f["lote"]:
        alarmas_qs = alarmas_qs.filter(lote__codigo__icontains=f["lote"])
    alarmas_criticas_total = alarmas_qs.count()
    alarmas_criticas = list(alarmas_qs[:10])

    # Conclusión ejecutiva automática basada en los indicadores del período
    turnos_con_datos = [t for t in turnos if t["total"] > 0]
    mejor_turno = max(turnos_con_datos, key=lambda t: t["tasa"]) if turnos_con_datos else None
    peor_turno = min(turnos_con_datos, key=lambda t: t["tasa"]) if turnos_con_datos else None

    registrar_auditoria(
        "Supervisión",
        "Generación de informe de gestión",
        f"Emitió informe ejecutivo en pantalla ({tot} inspecciones, conformidad {tasa_ap}%)",
        request=request,
    )

    return render(request, "supervisor/informe.html", {
        "emitido_en": timezone.localtime(),
        "total": tot,
        "aprobados": ap,
        "rechazados": re_,
        "tasa_ap": tasa_ap,
        "tasa_re": tasa_re,
        "ang_prom": round(ang["prom"], 2) if ang["prom"] is not None else None,
        "ang_min": round(ang["minimo"], 2) if ang["minimo"] is not None else None,
        "ang_max": round(ang["maximo"], 2) if ang["maximo"] is not None else None,
        "rendimiento_turnos": turnos,
        "rendimiento_operadores": operadores,
        "por_receta": por_receta,
        "lotes_periodo": lotes_periodo,
        "alarmas_criticas_total": alarmas_criticas_total,
        "alarmas_criticas": alarmas_criticas,
        "mejor_turno": mejor_turno,
        "peor_turno": peor_turno,
        "f": f,
        "recetas": Receta.objects.all(),
        "estados": _estados(),
        "turnos": Turno.objects.all(),
        "operadores": Usuario.objects.filter(rol__nombre=OP).order_by("username"),
    })


@rol_requerido(SUP)
def sup_exportar(request):                                               # CU09
    qs, error, _ = _filtrar(request, RegistroInspeccion.objects.select_related("lote", "receta", "estado", "turno", "operador"))
    if error or not qs.exists():                                         # A1
        messages.warning(request, error or "No hay registros para exportar con esos filtros.")
        return redirect("sup_dashboard")
    registrar_auditoria("Supervisión", "Exportación de reporte CSV",
                        f"Descarga de {qs.count()} registros de inspección", request=request)
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="reporte_inspecciones.csv"'
    resp.write("\ufeff")
    w = csv.writer(resp)
    w.writerow(["inspeccion", "fecha", "turno", "operador", "lote", "batch", "receta", "angulo", "limite_min", "limite_max", "estado"])
    for r in qs.iterator():
        w.writerow([r.codigo, timezone.localtime(r.fecha).strftime("%Y-%m-%d %H:%M:%S"),
                    r.turno.nombre if r.turno else "",
                    _celda(r.operador.username if r.operador else ""),
                    _celda(r.lote.codigo),
                    _celda(r.id_batch), _celda(r.receta.nombre if r.receta else ""), r.angulo,
                    r.limite_min if r.limite_min is not None else "", r.limite_max if r.limite_max is not None else "", r.estado.nombre])
    return resp


# ---------------------------------------------------------------- Administrador
def _resumen_admin():
    hoy = timezone.localdate()
    hace_7d = hoy - timedelta(days=7)
    qs_hoy = RegistroInspeccion.objects.filter(fecha__date=hoy)
    qs_7d = RegistroInspeccion.objects.filter(fecha__date__gte=hace_7d)
    tot_hoy, ap_hoy = qs_hoy.count(), qs_hoy.filter(estado__nombre=RegistroInspeccion.APROBADO).count()
    tot_7d, ap_7d = qs_7d.count(), qs_7d.filter(estado__nombre=RegistroInspeccion.APROBADO).count()
    return {
        "insp_hoy": tot_hoy,
        "tasa_hoy": round(ap_hoy * 100 / tot_hoy, 1) if tot_hoy else 0,
        "insp_7d": tot_7d,
        "tasa_7d": round(ap_7d * 100 / tot_7d, 1) if tot_7d else 0,
        "lotes_abiertos": Lote.objects.filter(fecha_fin__isnull=True).count(),
        "recetas_activas": Receta.objects.filter(activo=True).count(),
        "tokens_activos": TokenApi.objects.filter(activo=True).count(),
        "alarmas_criticas": Alarma.de_proceso().filter(nivel=Alarma.CRITICA, fecha__date__gte=hace_7d).count(),
        "cuentas_bloqueadas": sum(1 for u in Usuario.objects.filter(bloqueado_hasta__gt=timezone.now())),
        "solicitudes_pendientes": Alarma.objects.filter(tipo=Alarma.RECUPERACION, atendida=False).count(),
        "acciones_hoy": RegistroAuditoria.objects.filter(fecha__date=hoy).count(),
    }


@rol_requerido(ADM)
def adm_panel(request):
    """Panel ejecutivo del Administrador: data crítica de planta, seguridad y bitácora completa de auditoría."""
    audit_qs = RegistroAuditoria.objects.select_related("usuario").all()
    g = request.GET
    f_usuario = g.get("usuario", "").strip()
    f_modulo = g.get("modulo", "").strip()
    f_desde = parse_date(g.get("desde", "") or "")
    f_hasta = parse_date(g.get("hasta", "") or "")
    if f_usuario:
        audit_qs = audit_qs.filter(usuario_nombre__icontains=f_usuario)
    if f_modulo:
        audit_qs = audit_qs.filter(modulo=f_modulo)
    if f_desde:
        audit_qs = audit_qs.filter(fecha__date__gte=f_desde)
    if f_hasta:
        audit_qs = audit_qs.filter(fecha__date__lte=f_hasta)

    page = Paginator(audit_qs, 35).get_page(g.get("page"))
    modulos = list(RegistroAuditoria.objects.values_list("modulo", flat=True).distinct().order_by("modulo"))
    qs_7d = RegistroInspeccion.objects.filter(fecha__date__gte=timezone.localdate() - timedelta(days=7))
    lotes_en_curso = Lote.objects.filter(fecha_fin__isnull=True).select_related(
        "receta", "operador_inicio", "operador_activo"
    ).annotate(n_insp=Count("inspecciones")).order_by("-fecha_inicio")

    return render(request, "admin/panel.html", {
        "resumen": _resumen_admin(),
        "lotes_en_curso": lotes_en_curso,
        "rendimiento_turnos": _rendimiento_turnos(qs_7d),
        "rendimiento_operadores": _rendimiento_operadores(qs_7d)[:6],
        "alarmas_recientes": Alarma.objects.select_related("lote", "registro", "usuario")[:8],
        "page": page,
        "modulos": modulos,
        "f": {"usuario": f_usuario, "modulo": f_modulo, "desde": f_desde or "", "hasta": f_hasta or ""},
    })


@rol_requerido(ADM)
def adm_usuarios(request):                                               # CU10
    form, temporal = UsuarioForm(request.POST or None), None
    if request.method == "POST" and request.POST.get("accion") == "crear" and form.is_valid():
        temporal = "Tmp" + secrets.token_urlsafe(8) + "9a"
        u = Usuario(username=form.cleaned_data["username"], nombre_completo=form.cleaned_data["nombre_completo"],
                    rol=form.cleaned_data["rol"], cambio_obligatorio=True)
        u.set_password(temporal)
        u.save()
        log.info("admin %s creó el usuario %s (rol %s)", request.user.username, u.username, u.rol_nombre)
        registrar_auditoria("Usuarios", "Creación de usuario",
                            f"Creó cuenta '{u.username}' ({u.nombre_completo}) con rol {u.rol_nombre}", request=request)
        form = UsuarioForm()                                             # contraseña temporal se muestra una sola vez
    return render(request, "admin/usuarios.html", {
        "form": form, "temporal": temporal, "usuarios": Usuario.objects.select_related("rol").order_by("username"),
        "roles": Rol.objects.all(), "resumen": _resumen_admin(),
        "solicitudes": Alarma.objects.filter(tipo=Alarma.RECUPERACION, atendida=False).select_related("usuario")})


@rol_requerido(ADM)
@require_POST
def adm_usuario_accion(request, pk):
    u = get_object_or_404(Usuario, pk=pk)
    accion = request.POST.get("accion")
    if u.pk == request.user.pk and accion in ("toggle", "rol"):          # A2: no puede quitarse acceso a sí mismo
        messages.error(request, "No puedes desactivarte ni cambiar tu propio rol.")
        log.warning("admin %s intentó desactivarse o cambiar su propio rol", request.user.username)
        registrar_auditoria("Usuarios", "Intento bloqueado de auto-modificación",
                            f"Intentó ejecutar '{accion}' sobre su propia cuenta", request=request)
    elif accion == "toggle":
        u.is_active = not u.is_active                                    # A3: la sesión deja de ser válida
        u.save(update_fields=["is_active"])
        estado_txt = "activó" if u.is_active else "desactivó"
        log.info("admin %s %s al usuario %s", request.user.username, estado_txt, u.username)
        registrar_auditoria("Usuarios", f"Usuario {'activado' if u.is_active else 'desactivado'}",
                            f"{estado_txt.capitalize()} la cuenta '{u.username}'", request=request)
    elif accion == "rol":
        rol_ant = u.rol_nombre
        u.rol = get_object_or_404(Rol, pk=request.POST.get("rol"))
        u.save(update_fields=["rol"])
        log.info("admin %s cambió el rol de %s a %s", request.user.username, u.username, u.rol_nombre)
        registrar_auditoria("Usuarios", "Cambio de rol",
                            f"Cambió rol de '{u.username}': {rol_ant} → {u.rol_nombre}", request=request)
    elif accion == "reset":                                              # CU17: atiende también la solicitud CU16
        temporal = "Tmp" + secrets.token_urlsafe(8) + "9a"
        u.set_password(temporal)
        u.cambio_obligatorio, u.intentos_fallidos, u.bloqueado_hasta = True, 0, None
        u.save()
        Alarma.objects.filter(tipo=Alarma.RECUPERACION, usuario=u, atendida=False).update(atendida=True)
        log.info("admin %s restableció la contraseña de %s", request.user.username, u.username)
        registrar_auditoria("Usuarios", "Restablecimiento de contraseña",
                            f"Emitió clave temporal para '{u.username}'", request=request)
        messages.success(request, f"Contraseña temporal de {u.username} (se muestra una sola vez): {temporal}")
    return redirect("adm_usuarios")


@rol_requerido(ADM)
def adm_recetas(request, pk=None):                                       # CU11
    inst = get_object_or_404(Receta, pk=pk) if pk else None
    form = RecetaForm(request.POST or None, instance=inst)
    if request.method == "POST" and form.is_valid():
        r = form.save()
        registrar_auditoria("Recetas", "Edición de receta" if inst else "Creación de receta",
                            f"[{r.codigo_letra}] {r.nombre} ({r.min_tol}°–{r.max_tol}°, Ø{r.espesor_mm} mm {r.material})",
                            request=request)
        messages.success(request, "Receta guardada. El cambio solo afecta a inspecciones futuras.")
        return redirect("adm_recetas")
    return render(request, "admin/recetas.html", {"form": form, "editando": inst, "recetas": Receta.objects.annotate(n=Count("lotes"))})


@rol_requerido(ADM)
@require_POST
def adm_receta_toggle(request, pk):                                      # Desactivación lógica para recetas con historial
    r = get_object_or_404(Receta, pk=pk)
    r.activo = not r.activo
    r.save(update_fields=["activo"])
    log.info("admin %s %s la receta %s", request.user.username, "activó" if r.activo else "desactivó", r.nombre)
    registrar_auditoria("Recetas", f"Receta {'activada' if r.activo else 'desactivada'}",
                        f"[{r.codigo_letra}] {r.nombre}", request=request)
    return redirect("adm_recetas")


@rol_requerido(ADM)
@require_POST
def adm_receta_eliminar(request, pk):                                    # Eliminación segura (solo sin historial, respeta PROTECT)
    r = get_object_or_404(Receta, pk=pk)
    etiqueta = f"[{r.codigo_letra}] {r.nombre}"
    try:
        r.delete()
    except ProtectedError:
        messages.error(request, f"No se puede eliminar la receta {etiqueta} porque tiene lotes o inspecciones asociadas. Usa Desactivar.")
        registrar_auditoria("Recetas", "Eliminación bloqueada por integridad",
                            f"Intento de eliminar receta {etiqueta} con registros asociados", request=request)
    else:
        log.info("admin %s eliminó la receta %s", request.user.username, etiqueta)
        registrar_auditoria("Recetas", "Eliminación de receta", f"Eliminó receta sin historial {etiqueta}", request=request)
        messages.success(request, f"Receta {etiqueta} eliminada correctamente.")
    return redirect("adm_recetas")


@rol_requerido(ADM)
def adm_lotes(request):                                                  # CU12
    form = LoteForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        l = form.save()
        op_txt = f" · op. inicial: {l.operador_inicio.username}" if l.operador_inicio else ""
        registrar_auditoria("Lotes", "Apertura de lote",
                            f"Lote {l.codigo} con receta [{l.receta.codigo_letra}] {l.receta.nombre} (cant. {l.cantidad}){op_txt}",
                            request=request)
        messages.success(request, f"Lote {l.codigo} creado.")
        return redirect("adm_lotes")
    recetas_activas = Receta.objects.filter(activo=True).order_by("codigo_letra", "nombre")
    sugerencias = {str(r.pk): Lote.generar_codigo(r) for r in recetas_activas}
    return render(request, "admin/lotes.html", {
        "form": form,
        "lotes": Lote.objects.select_related("receta", "operador_inicio", "operador_activo", "operador_fin")
                     .annotate(n_insp=Count("inspecciones")).order_by("-fecha_inicio"),
        "recetas": recetas_activas,
        "sugerencias": sugerencias})


@rol_requerido(ADM)
@require_POST
def adm_lote_cerrar(request, pk):
    l = get_object_or_404(Lote, pk=pk)
    if not l.abierto:                                                    # A3
        messages.error(request, "El lote ya está cerrado.")
    else:
        l.fecha_fin = timezone.now()
        if not l.operador_fin_id:
            l.operador_fin = l.operador_activo or l.operador_inicio or request.user
        l.operador_activo = None
        l.save(update_fields=["fecha_fin", "operador_fin", "operador_activo"])
        registrar_auditoria("Lotes", "Cierre administrativo de lote",
                            f"Cerró lote {l.codigo} (op. fin: {l.operador_fin.username if l.operador_fin else '—'})",
                            request=request)
    return redirect("adm_lotes")


@rol_requerido(ADM)
@require_POST
def adm_lote_eliminar(request, pk):                                      # Eliminación segura (solo sin inspecciones, respeta PROTECT)
    l = get_object_or_404(Lote, pk=pk)
    codigo = l.codigo
    try:
        l.delete()
    except ProtectedError:
        messages.error(request, f"No se puede eliminar el lote {codigo} porque tiene inspecciones o alarmas registradas. Usa Cerrar lote.")
        registrar_auditoria("Lotes", "Eliminación bloqueada por integridad",
                            f"Intento de eliminar lote {codigo} con registros asociados", request=request)
    else:
        log.info("admin %s eliminó el lote %s", request.user.username, codigo)
        registrar_auditoria("Lotes", "Eliminación de lote", f"Eliminó lote sin inspecciones {codigo}", request=request)
        messages.success(request, f"Lote {codigo} eliminado correctamente.")
    return redirect("adm_lotes")


@rol_requerido(ADM)
def adm_tokens(request):                                                 # emisión de tokens de captura
    form, nuevo = TokenForm(request.POST or None), None
    if request.method == "POST" and request.POST.get("accion") == "crear" and form.is_valid():
        t, nuevo = TokenApi.crear(form.cleaned_data["nombre"], request.user)
        log.info("admin %s creó el token de captura #%s (%s)", request.user.username, t.pk, t.nombre)
        registrar_auditoria("Tokens API", "Emisión de token", f"Token #{t.pk} para estación '{t.nombre}'", request=request)
        form = TokenForm()
    return render(request, "admin/tokens.html", {"form": form, "nuevo": nuevo, "tokens": TokenApi.objects.all().order_by("-fecha_creacion")})


@rol_requerido(ADM)
@require_POST
def adm_token_revocar(request, pk):
    t = get_object_or_404(TokenApi, pk=pk)
    t.activo = False
    t.save(update_fields=["activo"])
    log.info("admin %s revocó el token de captura #%s (%s)", request.user.username, t.pk, t.nombre)
    registrar_auditoria("Tokens API", "Revocación de token", f"Revocó token #{t.pk} ('{t.nombre}')", request=request)
    return redirect("adm_tokens")
