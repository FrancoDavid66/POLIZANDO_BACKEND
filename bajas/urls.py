# bajas/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

# ✅ IMPORTAMOS EL NUEVO VIEWSET DEL HISTORIAL
from bajas.views import BajaPolizaViewSet, CorreoCompaniaBajaViewSet, HistorialBajaPolizaViewSet

router = DefaultRouter()

# 1. Endpoint para administrar correos: /api/bajas/correos/
# Esta ruta debe ir primero por ser más específica.
router.register(r"correos", CorreoCompaniaBajaViewSet, basename="bajas-correos")

# 2. Endpoint para el listado operativo: /api/bajas/operativo/
# Al usar "operativo" evitamos que el router capture todas las peticiones con una ruta vacía.
router.register(r"operativo", BajaPolizaViewSet, basename="bajas")

# 3. ✅ NUEVO: Endpoint para el historial de movimientos: /api/bajas/historial/
router.register(r"historial", HistorialBajaPolizaViewSet, basename="bajas-historial")

urlpatterns = [
    path("", include(router.urls)),
]