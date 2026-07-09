# gruas/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    PlanGruaViewSet,
    AdhesionGruaViewSet,
    ProveedorGruaViewSet,
    PolizasBuscarAPIView,
    PolizasAdheridasBuscarAPIView,
    SolicitudGruaViewSet,
)

router = DefaultRouter()
router.register(r"planes", PlanGruaViewSet, basename="gruas-planes")
router.register(r"adhesiones", AdhesionGruaViewSet, basename="gruas-adhesiones")
router.register(r"proveedores", ProveedorGruaViewSet, basename="gruas-proveedores")
router.register(r"solicitudes", SolicitudGruaViewSet, basename="gruas-solicitudes")

urlpatterns = [
    path("gruas/", include(router.urls)),
    path("gruas/polizas/buscar/", PolizasBuscarAPIView.as_view(), name="gruas-polizas-buscar"),
    path(
        "gruas/polizas/adheridas/buscar/",
        PolizasAdheridasBuscarAPIView.as_view(),
        name="gruas-polizas-adheridas-buscar",
    ),
]
