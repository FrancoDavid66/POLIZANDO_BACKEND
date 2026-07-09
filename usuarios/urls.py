# usuarios/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import OficinaViewSet, UserViewSet
from .precios_views import PreciosNREView

router = DefaultRouter()
router.register(r'oficinas', OficinaViewSet, basename='oficinas')
router.register(r'users', UserViewSet, basename='users')

urlpatterns = [
    # Lista de precios NRE para el modal del header (precios de hoy según oficina).
    path('precios-nre/', PreciosNREView.as_view(), name='precios-nre'),
    path('', include(router.urls)),
]