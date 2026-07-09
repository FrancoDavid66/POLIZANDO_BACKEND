from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import (
    PropietarioViewSet,
    InquilinoViewSet,
    GaranteViewSet,
    AlquilerViewSet,
    CuotaAlquilerViewSet,
)

router = DefaultRouter()
router.register(r'propietarios', PropietarioViewSet)
router.register(r'inquilinos', InquilinoViewSet)
router.register(r'garantes', GaranteViewSet)  # 👈 agregado
router.register(r'alquileres', AlquilerViewSet)
router.register(r'cuotas-alquiler', CuotaAlquilerViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
