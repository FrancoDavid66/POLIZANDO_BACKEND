from rest_framework.routers import DefaultRouter
from .views import (
    CompetidorViewSet,
    CompetidorCanalViewSet,
    CompetidorUbicacionViewSet,
    MiPrecioReferenciaViewSet,
    OficinaMapaViewSet,
    OportunidadCompetenciaViewSet,
)

router = DefaultRouter()
router.register(r"competidores", CompetidorViewSet, basename="competidor")
router.register(
    r"competidores-canales", CompetidorCanalViewSet, basename="competidor-canal"
)
router.register(
    r"competidores-ubicaciones",
    CompetidorUbicacionViewSet,
    basename="competidor-ubicacion",
)
router.register(
    r"mis-precios",
    MiPrecioReferenciaViewSet,
    basename="mi-precio-referencia",
)
router.register(
    r"oficinas-mapa",
    OficinaMapaViewSet,
    basename="oficina-mapa",
)
router.register(
    r"oportunidades-competencia",
    OportunidadCompetenciaViewSet,
    basename="oportunidad-competencia",
)

urlpatterns = router.urls
