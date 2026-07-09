from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CotizacionViewSet, CompaniaSeguroViewSet, TipoCoberturaViewSet, ConfiguracionGlobalView

router = DefaultRouter()

router.register(r'companias', CompaniaSeguroViewSet, basename='companias')
router.register(r'coberturas', TipoCoberturaViewSet, basename='coberturas')
router.register(r'', CotizacionViewSet, basename='cotizaciones')

urlpatterns = [
    # 🚀 RUTA DE CONFIGURACIÓN (Va antes de router.urls para evitar conflictos)
    path('configuracion/', ConfiguracionGlobalView.as_view(), name='configuracion-global'),
    path('', include(router.urls)),
]