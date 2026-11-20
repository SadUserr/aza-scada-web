from django.contrib import admin
from .models import Alarma, Lote, Observacion, Receta, RegistroInspeccion, TokenApi

for m in (Alarma, Lote, Observacion, Receta, RegistroInspeccion, TokenApi):
    admin.site.register(m)
