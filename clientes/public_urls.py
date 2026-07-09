# clientes/public_urls.py
# Rutas PÚBLICAS del Portal del Asegurado (montadas en /public/portal/ del urls principal).
from django.urls import path

from .public_views import PortalDataView, PortalReportarPagoCuponView

urlpatterns = [
    path("<str:token>/", PortalDataView.as_view(), name="portal-data"),
    path(
        "<str:token>/cupon/<int:cupon_id>/reportar-pago/",
        PortalReportarPagoCuponView.as_view(),
        name="portal-reportar-pago-cupon",
    ),
]