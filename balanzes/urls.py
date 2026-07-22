from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import IngresoViewSet, EgresoViewSet, BalanceViewSet, CategoriaViewSet

# 🚀 Reporte COMPLETO (todo en un Excel: Resumen + Ingresos + Egresos)
from .reporte_completo import ReporteCompletoExcelView

# ------------------------------------------
# ROUTER PARA CRUD OPERATIVO
# ------------------------------------------
router = DefaultRouter()
router.register(r"ingresos", IngresoViewSet, basename="ingresos")
router.register(r"egresos", EgresoViewSet, basename="egresos")
router.register(r"categorias", CategoriaViewSet, basename="categorias")

# ------------------------------------------
# VISTAS PERSONALIZADAS DE BALANCE
# ------------------------------------------
balance_datos = BalanceViewSet.as_view({"get": "balance_diario"})
balance_enviar = BalanceViewSet.as_view({"post": "enviar_balance"})

# 🆕 Totales del MES sumados en el backend (JSON, para el home)
balance_mensual = BalanceViewSet.as_view({"get": "balance_mensual"})


urlpatterns = [
    # CRUD del router (Ingresos, Egresos, Categorías)
    path("", include(router.urls)),

    # Totales del día (filtrados por fecha y oficina)
    path("balance-diario/", balance_datos, name="balance-diario"),

    # Disparar el WhatsApp con el resumen de caja
    path("balance-diario/enviar/", balance_enviar, name="balance-diario-enviar"),

    # Totales del MES (JSON) para el home
    path("balance-mensual/", balance_mensual, name="balance-mensual"),

    # 🚀 TODO en un Excel (Resumen + Ingresos + Egresos), rango de fechas
    path("reporte-completo/", ReporteCompletoExcelView.as_view(), name="reporte-completo"),
]