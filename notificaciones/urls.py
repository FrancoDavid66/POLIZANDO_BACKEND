# notificaciones/urls.py
from django.urls import path

from .views import (
    EnviarRecordatoriosCuotasView,
    EnviarRecorditoriosCuotasView,
    CuotasRecordatoriosView,
    CuotasAlertasView,
    CuotasHistorialView,
    SidebarBadgesView,
    EnviarTodasOficinasView,
    ReporteContactosView,   # ← NUEVO
)

urlpatterns = [
    path(
        "sidebar-badges/",
        SidebarBadgesView.as_view(),
        name="notificaciones-sidebar-badges",
    ),
    path(
        "cuotas/recordatorios/",
        CuotasRecordatoriosView.as_view(),
        name="notificaciones-cuotas-recordatorios",
    ),
    path(
        "cuotas/alertas/",
        CuotasAlertasView.as_view(),
        name="notificaciones-cuotas-alertas",
    ),
    path(
        "cuotas/historial/",
        CuotasHistorialView.as_view(),
        name="notificaciones-cuotas-historial",
    ),
    path(
        "cuotas/enviar-recordatorios/",
        EnviarRecordatoriosCuotasView.as_view(),
        name="notificaciones-cuotas-enviar-recordatorios",
    ),
    path(
        "cuotas/enviar-recorditorios/",
        EnviarRecorditoriosCuotasView.as_view(),
        name="notificaciones-cuotas-enviar-recorditorios",
    ),
    path(
        "cuotas/enviar-todas-oficinas/",
        EnviarTodasOficinasView.as_view(),
        name="notificaciones-cuotas-enviar-todas-oficinas",
    ),
    # ← NUEVO: reporte de contactos pendientes (PDF / Excel)
    path(
        "cuotas/reporte-contactos/",
        ReporteContactosView.as_view(),
        name="notificaciones-cuotas-reporte-contactos",
    ),
]