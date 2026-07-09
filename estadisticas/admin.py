# estadisticas/admin.py
from django.contrib import admin

from .models import (
    PolizaOficinaSnapshot,
    KpiDiarioOficina,
    AlertaKpi,
    ExportLog,
)


@admin.register(PolizaOficinaSnapshot)
class PolizaOficinaSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "oficina",
        "anio",
        "mes",
        "total_polizas",
        "total_activas",
        "nuevas_mes",
        "bajas_mes",
        "creado_el",
    )
    list_filter = ("anio", "mes", "oficina")
    search_fields = ("oficina",)
    readonly_fields = ("creado_el",)


@admin.register(KpiDiarioOficina)
class KpiDiarioOficinaAdmin(admin.ModelAdmin):
    list_display = (
        "fecha",
        "oficina",
        "polizas_activas",
        "polizas_morosas",
        "cobranzas_del_dia",
        "creado_el",
    )
    list_filter = ("fecha", "oficina")
    search_fields = ("oficina",)
    readonly_fields = ("creado_el",)


@admin.register(AlertaKpi)
class AlertaKpiAdmin(admin.ModelAdmin):
    list_display = (
        "descripcion",
        "oficina",
        "tipo",
        "umbral",
        "activo",
        "creado_el",
        "ultimo_disparo",
    )
    list_filter = ("activo", "tipo", "oficina")
    search_fields = ("descripcion", "oficina")


@admin.register(ExportLog)
class ExportLogAdmin(admin.ModelAdmin):
    list_display = ("tipo", "usuario", "creado_el")
    list_filter = ("tipo", "creado_el")
    search_fields = ("tipo", "usuario__username", "usuario__email")
    readonly_fields = ("creado_el",)
