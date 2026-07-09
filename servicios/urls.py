# servicios/urls.py
from rest_framework.routers import DefaultRouter
from django.urls import path, include

from .views import (
    ServicioFijoViewSet,
    PagoServicioViewSet,
    CategoriaServicioViewSet,
)

router = DefaultRouter()
router.register(r'servicios', ServicioFijoViewSet, basename='servicios')
router.register(r'pagos', PagoServicioViewSet, basename='pagos-servicios')
router.register(r'categorias', CategoriaServicioViewSet, basename='categorias-servicios')

urlpatterns = [
    path('', include(router.urls)),
]