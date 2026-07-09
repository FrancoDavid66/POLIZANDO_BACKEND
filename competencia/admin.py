# competencia/admin.py
from django.contrib import admin
from .models import (
    Competidor,
    CompetidorCanal,
    CompetidorUbicacion,
    OficinaMapa,
    OportunidadCompetencia,
)


@admin.register(Competidor)
class CompetidorAdmin(admin.ModelAdmin):
    list_display = ("nombre", "tipo", "nicho_fuerte", "activo", "created_at")
    list_filter = ("tipo", "activo")
    search_fields = ("nombre", "nicho_fuerte", "descripcion")
    ordering = ("nombre",)


@admin.register(CompetidorCanal)
class CompetidorCanalAdmin(admin.ModelAdmin):
    list_display = ("competidor", "tipo_canal", "url_o_user", "activo", "created_at")
    list_filter = ("tipo_canal", "activo")
    search_fields = ("competidor__nombre", "url_o_user", "notas")
    autocomplete_fields = ("competidor",)


@admin.register(CompetidorUbicacion)
class CompetidorUbicacionAdmin(admin.ModelAdmin):
    list_display = (
        "competidor",
        "direccion",
        "ciudad",
        "compania",
        "cobertura",
        "precio",
        "horario_desde",
        "horario_hasta",
    )
    list_filter = ("ciudad", "compania")
    search_fields = (
        "competidor__nombre",
        "direccion",
        "ciudad",
        "compania",
        "cobertura",
    )
    autocomplete_fields = ("competidor",)


@admin.register(OficinaMapa)
class OficinaMapaAdmin(admin.ModelAdmin):
    list_display = (
        "nombre",
        "codigo",
        "direccion",
        "ciudad",
        "horario_desde",
        "horario_hasta",
        "activo",
    )
    list_filter = ("activo", "ciudad")
    search_fields = ("nombre", "codigo", "direccion", "ciudad")


@admin.register(OportunidadCompetencia)
class OportunidadCompetenciaAdmin(admin.ModelAdmin):
    list_display = ("fecha", "ramo", "competidor", "resultado", "motivo")
    list_filter = ("resultado", "motivo", "ramo")
    search_fields = ("competidor__nombre", "cliente__nombre", "cliente__apellido")
    autocomplete_fields = ("competidor", "cliente")
    date_hierarchy = "fecha"
