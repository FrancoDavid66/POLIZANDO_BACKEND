# pagos/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PagoViewSet, CuotaViewSet, MedioCobroViewSet

app_name = "pagos"

router = DefaultRouter()
router.register(r"pagos", PagoViewSet, basename="pago")
router.register(r"cuotas", CuotaViewSet, basename="cuota")
router.register(r"medios-cobro", MedioCobroViewSet, basename="medio-cobro")  # ← NUEVO

urlpatterns = [
    # ✅ Alias PRO: /pagos/buscar/ (sin depender del router /pagos/pagos/buscar/)
    path(
        "buscar/",
        PagoViewSet.as_view({"get": "buscar"}),
        name="pagos-buscar",
    ),
    # ✅ Alias RÁPIDO: /pagos/buscar-cliente/ (DNI -> cliente + pólizas, sin cuotas)
    path(
        "buscar-cliente/",
        PagoViewSet.as_view({"get": "buscar_cliente"}),
        name="pagos-buscar-cliente",
    ),
    path("", include(router.urls)),
]
