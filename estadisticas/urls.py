from django.urls import path

from .views import (
    PolizasPorOficinaAPIView,
    VehiculosResumenAPIView,
    VehiculosExportAPIView,
    VehiculosListAPIView,
    SolicitudesSeriePorOficinaAPIView,
    EmisionesSeriePorOficinaAPIView,
    AgrosaltaKpisAPIView,
    ClientesDuplicadosAPIView,
    PolizasDuplicadasAPIView,
    ContabilidadResumenAPIView,
    BajasRetenciónAPIView,
    EmisionesExportExcelAPIView,  # 🆕 NUEVO: Export Excel de emisiones
)

app_name = "estadisticas"

urlpatterns = [
    path(
        "polizas/por-oficina/",
        PolizasPorOficinaAPIView.as_view(),
        name="polizas-por-oficina",
    ),

    # ✅ Emisiones por fecha_emision (serie)
    path(
        "polizas/emisiones/serie/",
        EmisionesSeriePorOficinaAPIView.as_view(),
        name="polizas-emisiones-serie",
    ),

    # ✅ Aliases defensivos (por si algún entorno quedó con otra variante o sin APPEND_SLASH)
    path(
        "polizas/emisiones/serie",
        EmisionesSeriePorOficinaAPIView.as_view(),
        name="polizas-emisiones-serie-noslash",
    ),
    path(
        "polizas/emisiones-serie/",
        EmisionesSeriePorOficinaAPIView.as_view(),
        name="polizas-emisiones-serie-alias",
    ),
    path(
        "polizas/emisiones-serie",
        EmisionesSeriePorOficinaAPIView.as_view(),
        name="polizas-emisiones-serie-alias-noslash",
    ),

    # 🆕 NUEVO: Export Excel detallado de emisiones (altas + renovaciones)
    path(
        "polizas/emisiones/export-excel/",
        EmisionesExportExcelAPIView.as_view(),
        name="polizas-emisiones-export-excel",
    ),

    # ✅ KPIs Agrosalta (Autos con Robo + Camiones)
    path(
        "agrosalta/kpis/",
        AgrosaltaKpisAPIView.as_view(),
        name="agrosalta-kpis",
    ),

    path(
        "vehiculos/resumen/",
        VehiculosResumenAPIView.as_view(),
        name="vehiculos-resumen",
    ),
    path(
        "vehiculos/list/",
        VehiculosListAPIView.as_view(),
        name="vehiculos-list",
    ),
    path(
        "vehiculos/export/",
        VehiculosExportAPIView.as_view(),
        name="vehiculos-export",
    ),

    path(
        "solicitudes/serie/",
        SolicitudesSeriePorOficinaAPIView.as_view(),
        name="solicitudes-serie",
    ),

    # ✅ Duplicados
    path(
        "duplicados/clientes/",
        ClientesDuplicadosAPIView.as_view(),
        name="duplicados-clientes",
    ),
    path(
        "duplicados/polizas/",
        PolizasDuplicadasAPIView.as_view(),
        name="duplicados-polizas",
    ),
    
    # 🚀 NUEVO: Contabilidad y Caja
    path(
        "contabilidad/resumen/",
        ContabilidadResumenAPIView.as_view(),
        name="contabilidad-resumen",
    ),

    # 🚀 NUEVO: Bajas del mes + Tasa de retención
    path(
        "polizas/bajas-retencion/",
        BajasRetenciónAPIView.as_view(),
        name="polizas-bajas-retencion",
    ),
]