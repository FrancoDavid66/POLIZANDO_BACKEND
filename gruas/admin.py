# gruas/admin.py
from django.contrib import admin
from .models import PlanGrua, AdhesionGrua


@admin.register(PlanGrua)
class PlanGruaAdmin(admin.ModelAdmin):
    list_display = ("id", "nombre", "km_incluidos", "precio_mensual", "activo", "creado_en")
    list_filter = ("activo",)
    search_fields = ("nombre",)


@admin.register(AdhesionGrua)
class AdhesionGruaAdmin(admin.ModelAdmin):
    list_display = ("id", "poliza", "plan", "estado", "fecha_activacion", "carencia_dias", "creado_en")
    list_filter = ("estado", "plan")
    search_fields = ("poliza__patente", "poliza__numero_poliza", "poliza__cliente__apellido", "poliza__cliente__nombre")
    raw_id_fields = ("poliza",)
