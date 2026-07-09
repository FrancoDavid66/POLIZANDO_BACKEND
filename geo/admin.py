# geo/admin.py
from django.contrib import admin
from .models import GeoItem


@admin.register(GeoItem)
class GeoItemAdmin(admin.ModelAdmin):
    list_display = ("id", "nombre", "lat", "lng", "activo", "creado_en")
    list_filter = ("tipo", "activo")
    search_fields = ("nombre", "direccion", "nota")
    list_editable = ("activo",)
    ordering = ("-creado_en",)
