from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("recuperar/", views.recuperar, name="recuperar"),
    path("cambiar-password/", views.cambiar_password, name="cambiar_password"),
]
