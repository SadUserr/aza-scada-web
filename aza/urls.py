from django.urls import path, include
from django.contrib import admin

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", include("cuentas.urls")),
    path("", include("trazabilidad.urls")),
]
