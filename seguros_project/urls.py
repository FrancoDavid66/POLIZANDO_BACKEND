from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# 🚀 IMPORTAMOS LAS VISTAS DE SIMPLE JWT
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

urlpatterns = [
    path('admin/', admin.site.urls),

    path('api/', include('clientes.urls')),
    path('api/', include('polizas.urls')),

    # 🆕 NUEVA APP DE TAREAS (panel "Tareas del día")
    path('api/', include('tareas.urls')),

    # 🏆 NUEVA APP DE RANKING (monedero central de puntos)
    path('api/', include('ranking.urls')),

    path('api/', include('pagos.urls')),
    path('api/', include('siniestros.urls')),
    path('api/', include('geo.urls')),
    path('api/', include('inmuebles.urls')),
    path('api/', include('alquileres.urls')),
    path('api/', include('balanzes.urls')),

    path('api/', include('gruas.urls')),  # ✅ ESTA ES

    path('api/', include('solicitudes.urls')),
    path('public/solicitudes/', include('solicitudes.public_urls')),
    path('public/portal/', include('clientes.public_urls')),  # 🆕 Portal del asegurado

    path('api/notificaciones/', include('notificaciones.urls')),
    path('api/competencia/', include('competencia.urls')),
    path('api/estadisticas/', include('estadisticas.urls')),
    path('api/marketing/', include('marketing.urls')),
    path('api/bajas/', include('bajas.urls')),
    
    # 💸 NUEVA APP DE RECAUDACIÓN / CAJA
    path('api/recaudacion/', include('recaudacion.urls')),

    # 🚀 NUEVA APP DE COTIZACIONES (¡LA QUE FALTABA!)
    path('api/cotizaciones/', include('cotizaciones.urls')),

    # 🚀 NUEVA APP DE SERVICIOS Y GASTOS FIJOS
    path('api/servicios/', include('servicios.urls')),
    
    # 🔐 RUTAS DE AUTENTICACIÓN (LOGIN)
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # 🚀 RUTA PARA USUARIOS, PERFILES Y OFICINAS
    path('api/usuarios/', include('usuarios.urls')),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)