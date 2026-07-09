# polizas/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from polizas.views import (
    PolizaViewSet,
    FotoVehiculoViewSet,
    PolizaDocumentoViewSet,
    CuponRoboViewSet,
)
# 🆕 Endpoints públicos del portal de cupones (sin login)
from polizas.views.portal_cupon import PortalCuponView, PortalCuponReportarView
# 🆕 Lector de PDF (alta de póliza)
from polizas.views.lector_pdf import LectorPdfView

# Historia es opcional
try:
    from historia.views import PolizaEventoViewSet
    _HISTORIA_INSTALADA = True
except Exception:
    PolizaEventoViewSet = None
    _HISTORIA_INSTALADA = False

app_name = "polizas"

router = DefaultRouter()

# Sub-recursos
router.register(r"polizas/documentos", PolizaDocumentoViewSet, basename="poliza-documentos")
router.register(r"polizas/fotos", FotoVehiculoViewSet, basename="poliza-fotos")
router.register(r"polizas/cupones-robo", CuponRoboViewSet, basename="poliza-cupones-robo")
router.register(r"polizas", PolizaViewSet, basename="poliza")

if _HISTORIA_INSTALADA and PolizaEventoViewSet is not None:
    router.register(r"polizas/historia", PolizaEventoViewSet, basename="poliza-historia")

urlpatterns = [
    # 🆕 Rutas públicas del cliente (van ANTES del router)
    path("polizas/portal/cupon/<uuid:token>/", PortalCuponView.as_view(), name="portal-cupon"),
    path("polizas/portal/cupon/<uuid:token>/reportar/", PortalCuponReportarView.as_view(), name="portal-cupon-reportar"),

    # 🆕 Lector de PDF (autenticado) — autocompleta el alta
    path("polizas/lector-pdf/", LectorPdfView.as_view(), name="lector-pdf"),

    path("", include(router.urls)),
]