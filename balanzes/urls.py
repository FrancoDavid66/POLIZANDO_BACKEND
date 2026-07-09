from rest_framework.routers import DefaultRouter
from django.urls import path, include
# 🚀 IMPORTAMOS NUESTRO NUEVO CategoriaViewSet
from .views import IngresoViewSet, EgresoViewSet, BalanceViewSet, CategoriaViewSet

# 🚀 NUEVO: Vista del Reporte Gerencial MENSUAL (tablas + estilos + gráficos)
from .reporte_mensual import ReporteMensualExcelView

# ------------------------------------------
# ROUTER PARA CRUD OPERATIVO
# ------------------------------------------
router = DefaultRouter()
# GET, POST, PUT, DELETE para Ingresos (/api/balanzes/ingresos/)
router.register(r"ingresos", IngresoViewSet, basename="ingresos")
# GET, POST, PUT, DELETE para Egresos (/api/balanzes/egresos/)
router.register(r"egresos", EgresoViewSet, basename="egresos")
# 🚀 NUEVO: GET, POST, PUT, DELETE para Categorías Oficiales (/api/balanzes/categorias/)
router.register(r"categorias", CategoriaViewSet, basename="categorias")

# ------------------------------------------
# VISTAS PERSONALIZADAS DE BALANCE
# ------------------------------------------
# Mapeamos explícitamente los métodos HTTP a las acciones de nuestro ViewSet de Balance
balance_datos = BalanceViewSet.as_view({"get": "balance_diario"})
balance_enviar = BalanceViewSet.as_view({"post": "enviar_balance"})

# 🚀 NUEVO: Mapeamos la descarga del reporte gerencial
balance_exportar = BalanceViewSet.as_view({"get": "exportar_excel"})

# 🆕 NUEVO: Totales del MES sumados en el backend (JSON, para el home)
balance_mensual = BalanceViewSet.as_view({"get": "balance_mensual"})


urlpatterns = [
    # Incluimos las rutas automáticas del router (Ingresos, Egresos y Categorías)
    path("", include(router.urls)),
    
    # Endpoint para consultar totales, filtrados por fecha y oficina (Escudo de Sucursal activado)
    path("balance-diario/", balance_datos, name="balance-diario"),
    
    # Endpoint para disparar el mensaje de WhatsApp con el resumen de la caja
    path("balance-diario/enviar/", balance_enviar, name="balance-diario-enviar"),
    
    # 🚀 NUEVO: Endpoint para generar y descargar el Excel (DIARIO)
    path("balance-diario/exportar/", balance_exportar, name="balance-exportar"),

    # 🚀 NUEVO: Reporte Gerencial MENSUAL con tablas, estilos y gráficos
    path("balance-mensual/exportar/", ReporteMensualExcelView.as_view(), name="balance-mensual-exportar"),

    # 🆕 NUEVO: Totales del MES (JSON) para que el home no se trunque en 500
    path("balance-mensual/", balance_mensual, name="balance-mensual"),
]