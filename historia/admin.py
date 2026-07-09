from django.contrib import admin
from historia.models import PolizaEvento

@admin.register(PolizaEvento)
class PolizaEventoAdmin(admin.ModelAdmin):
    list_display = ("id", "poliza", "categoria", "tipo", "severidad", "mensaje", "actor_name", "created_at")
    list_filter = ("categoria", "tipo", "severidad", "created_at")
    search_fields = ("mensaje", "actor_name")
    ordering = ("-created_at",)
