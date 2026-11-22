from django.urls import path
from . import api, views as v

urlpatterns = [
    path("api/inspecciones", api.inspecciones_api, name="api_inspecciones"),
    # Operador
    path("operador/", v.op_inspeccion, name="op_inspeccion"),
    path("operador/lote/<int:pk>/", v.op_lote_accion, name="op_lote_accion"),
    path("operador/ultima.json", v.op_ultima_json, name="op_ultima_json"),
    path("operador/historial/", v.op_historial, name="op_historial"),
    path("operador/alarmas/", v.op_alarmas, name="op_alarmas"),
    path("operador/alarmas/<int:pk>/atender/", v.op_alarma_atender, name="op_alarma_atender"),
    path("inspeccion/<int:pk>/", v.detalle, name="detalle"),
    # Supervisor
    path("supervisor/", v.sup_dashboard, name="sup_dashboard"),
    path("supervisor/informe/", v.sup_informe_gestion, name="sup_informe_gestion"),
    path("supervisor/tendencias/", v.sup_tendencias, name="sup_tendencias"),
    path("supervisor/lote/", v.sup_lote, name="sup_lote"),
    path("supervisor/exportar/", v.sup_exportar, name="sup_exportar"),
    # Administrador
    path("administracion/panel/", v.adm_panel, name="adm_panel"),
    path("administracion/usuarios/", v.adm_usuarios, name="adm_usuarios"),
    path("administracion/usuarios/<int:pk>/", v.adm_usuario_accion, name="adm_usuario_accion"),
    path("administracion/recetas/", v.adm_recetas, name="adm_recetas"),
    path("administracion/recetas/<int:pk>/", v.adm_recetas, name="adm_receta_editar"),
    path("administracion/recetas/<int:pk>/toggle/", v.adm_receta_toggle, name="adm_receta_toggle"),
    path("administracion/recetas/<int:pk>/eliminar/", v.adm_receta_eliminar, name="adm_receta_eliminar"),
    path("administracion/lotes/", v.adm_lotes, name="adm_lotes"),
    path("administracion/lotes/<int:pk>/cerrar/", v.adm_lote_cerrar, name="adm_lote_cerrar"),
    path("administracion/lotes/<int:pk>/eliminar/", v.adm_lote_eliminar, name="adm_lote_eliminar"),
    path("administracion/tokens/", v.adm_tokens, name="adm_tokens"),
    path("administracion/tokens/<int:pk>/revocar/", v.adm_token_revocar, name="adm_token_revocar"),
]
