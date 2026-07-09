# recaudacion/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CierreCajaViewSet, HorariosCierreView, MiHorarioCierreView

router = DefaultRouter()
router.register(r'', CierreCajaViewSet, basename='recaudacion')

urlpatterns = [
    path('horarios-cierre/', HorariosCierreView.as_view(), name='horarios-cierre'),
    path('mi-horario-cierre/', MiHorarioCierreView.as_view(), name='mi-horario-cierre'),
    path('', include(router.urls)),
]