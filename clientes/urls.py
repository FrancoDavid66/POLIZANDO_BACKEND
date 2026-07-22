# clientes/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import ClienteViewSet
from .views_verificar import VerificarGlobalAPIView  # 🚀 NUEVO: endpoint de verificación global
from .fusion import FusionarClientesView, FusionMasivaDNIView  # 🚀 Fusión de duplicados
from .portal_link import PortalLinkView  # 🚀 Link del Portal del Asegurado (uso interno staff)

router = DefaultRouter()
router.register(r"clientes", ClienteViewSet, basename="clientes")

urlpatterns = [
    # 🚀 Verificación GLOBAL (DNI / Patente en TODAS las oficinas)
    # ⚠️ IMPORTANTE: va ANTES del router. Si se pone después, el router interpreta
    #    "verificar-global" como si fuera el ID de un cliente y devuelve 404.
    path(
        "clientes/verificar-global/",
        VerificarGlobalAPIView.as_view(),
        name="verificar-global",
    ),

    # 🚀 FUSIÓN DE CLIENTES DUPLICADOS
    # ⚠️ También van ANTES del router (mismo motivo): si no, "fusionar" / "fusionar-dni"
    #    se interpretan como ID de cliente y el POST devuelve 405 Method Not Allowed.
    path(
        "clientes/fusionar/",
        FusionarClientesView.as_view(),
        name="clientes-fusionar",
    ),
    path(
        "clientes/fusionar-dni/",
        FusionMasivaDNIView.as_view(),
        name="clientes-fusionar-dni",
    ),

    # 🚀 LINK DEL PORTAL DEL ASEGURADO (uso interno).
    # ⚠️ ANTES del router: si no, "<pk>/portal-link" se confunde con un detail del ViewSet.
    #   GET  → devuelve/crea el token   ·   POST → regenera el token (invalida el link viejo)
    path(
        "clientes/<int:pk>/portal-link/",
        PortalLinkView.as_view(),
        name="cliente-portal-link",
    ),

    path("", include(router.urls)),
]