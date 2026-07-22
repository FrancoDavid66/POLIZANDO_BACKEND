from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# 🚀 IMPORTAMOS LAS VISTAS DE SIMPLE JWT
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

# 🔧 Único endpoint que sobrevive de la ex-app "tareas": subir papeles/cuponera
#    de la póliza renovada al sistema. Se mudó a polizas/papeles_sistema.py.
from polizas.papeles_sistema import SubirPapelesSistemaView

urlpatterns = [
    path('admin/', admin.site.urls),

    path('api/', include('clientes.urls')),
    path('api/', include('polizas.urls')),

    # 🔧 Ex-app Tareas: solo queda "Subir póliza a sistema" (mudado a polizas).
    #    Mantenemos la MISMA URL para no tocar el frontend.
    path(
        'api/tareas/subir-papeles-sistema/',
        SubirPapelesSistemaView.as_view(),
        name='subir-papeles-sistema',
    ),

    path('api/', include('pagos.urls')),
    path('api/', include('siniestros.urls')),
    path('api/', include('balanzes.urls')),

    path('api/', include('solicitudes.urls')),
    path('public/solicitudes/', include('solicitudes.public_urls')),
    path('public/portal/', include('clientes.public_urls')),  # 🆕 Portal del asegurado

    path('api/notificaciones/', include('notificaciones.urls')),
    path('api/estadisticas/', include('estadisticas.urls')),
    path('api/bajas/', include('bajas.urls')),

    # 💸 RECAUDACIÓN / CAJA
    path('api/recaudacion/', include('recaudacion.urls')),

    # 🚀 COTIZACIONES
    path('api/cotizaciones/', include('cotizaciones.urls')),

    # 🚀 SERVICIOS Y GASTOS FIJOS
    path('api/servicios/', include('servicios.urls')),

    # 🔐 RUTAS DE AUTENTICACIÓN (LOGIN)
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # 🚀 RUTA PARA USUARIOS, PERFILES Y OFICINAS
    path('api/usuarios/', include('usuarios.urls')),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)