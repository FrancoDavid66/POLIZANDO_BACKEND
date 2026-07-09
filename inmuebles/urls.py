# inmuebles/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    PropiedadViewSet,
    AlquilerViewSet,
    CuotaAlquilerViewSet,
    InquilinoViewSet,
    PropietarioViewSet,
)

router = DefaultRouter()
router.register(r'propiedades', PropiedadViewSet)
router.register(r'alquileres', AlquilerViewSet)
router.register(r'cuotas-alquiler', CuotaAlquilerViewSet)
router.register(r'inquilinos', InquilinoViewSet)
router.register(r'propietarios', PropietarioViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
