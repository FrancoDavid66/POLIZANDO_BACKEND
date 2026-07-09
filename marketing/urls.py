# marketing/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import MarketingViewSet

router = DefaultRouter()

# Registramos el ViewSet en la raíz del módulo de marketing. 
# Basado en los url_path definidos en las acciones del ViewSet, esto habilita:
# - api/marketing/audiencia/resumen/ (para conteo y preview)
# - api/marketing/enviar/ (para lanzar la campaña)
# - api/marketing/historial/ (para el listado de campañas anteriores)
router.register(r'', MarketingViewSet, basename='marketing')

urlpatterns = [
    # Agregamos este mapeo manual para que la ruta de los logs incluya el prefijo 'historial/'
    # Esto es indispensable para que coincida exactamente con lo que pide tu frontend en 'marketing.js':
    # URL esperada: api/marketing/historial/{id}/logs/
    path('historial/<int:pk>/logs/', MarketingViewSet.as_view({'get': 'ver_logs'}), name='marketing-historial-logs'),
    
    path('', include(router.urls)),
]