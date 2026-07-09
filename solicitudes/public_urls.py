from django.urls import path
from .public_views import verificar

urlpatterns = [
    path("<int:id>/verificar/", verificar, name="solicitud-verificar"),
]
