# ranking/admin.py
from django.contrib import admin

from .models import MovimientoPuntos


@admin.register(MovimientoPuntos)
class MovimientoPuntosAdmin(admin.ModelAdmin):
    list_display = ("usuario", "puntos", "categoria", "oficina", "fecha", "detalle")
    list_filter = ("categoria", "fecha", "oficina")
    search_fields = ("usuario__username", "detalle", "ref")
    date_hierarchy = "fecha"