# siniestros/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SiniestroViewSet, SiniestroEventoViewSet, SiniestroFotoViewSet

router = DefaultRouter()
router.register(r'siniestros', SiniestroViewSet, basename='siniestro')
router.register(r'siniestro-eventos', SiniestroEventoViewSet, basename='siniestro-evento')
# 📸 Galería de fotos del siniestro
router.register(r'siniestro-fotos', SiniestroFotoViewSet, basename='siniestro-foto')

urlpatterns = [
    path('', include(router.urls)),
]