# bajas/admin.py
from django.contrib import admin
from django.utils.html import format_html

from .models import BajaPoliza, CorreoCompaniaBaja, HistorialBajaPoliza


# ─── CorreoCompaniaBaja ───────────────────────────────────────────────────────

@admin.register(CorreoCompaniaBaja)
class CorreoCompaniaBajaAdmin(admin.ModelAdmin):
    list_display  = ["compania", "email", "dias_gracia"]
    search_fields = ["compania", "email"]
    ordering      = ["compania"]


# ─── BajaPoliza ───────────────────────────────────────────────────────────────

@admin.register(BajaPoliza)
class BajaPolizaAdmin(admin.ModelAdmin):
    list_display   = ["poliza_numero", "poliza_compania", "estado", "email_destino", "email_ok", "enviada_en", "realizada_en", "created_at"]
    list_filter    = ["estado", "email_ok"]
    search_fields  = ["poliza__numero_poliza", "poliza__patente", "email_destino"]
    ordering       = ["-created_at"]
    readonly_fields = ["email_asunto", "email_cuerpo", "email_ok", "email_error", "enviada_en", "realizada_en", "created_at", "updated_at"]

    def poliza_numero(self, obj):
        return obj.poliza.numero_poliza or f"Póliza #{obj.poliza_id}"
    poliza_numero.short_description = "Póliza"

    def poliza_compania(self, obj):
        return obj.poliza.compania or "—"
    poliza_compania.short_description = "Compañía"


# ─── HistorialBajaPoliza ──────────────────────────────────────────────────────

@admin.register(HistorialBajaPoliza)
class HistorialBajaPolizaAdmin(admin.ModelAdmin):
    list_display  = ["poliza_numero", "estado_anterior", "estado_nuevo", "fecha"]
    list_filter   = ["estado_nuevo"]
    search_fields = ["baja_poliza__poliza__numero_poliza", "baja_poliza__poliza__patente"]
    ordering      = ["-fecha"]
    readonly_fields = ["baja_poliza", "estado_anterior", "estado_nuevo", "fecha"]

    def poliza_numero(self, obj):
        try:
            return obj.baja_poliza.poliza.numero_poliza or f"Póliza #{obj.baja_poliza.poliza_id}"
        except Exception:
            return "—"
    poliza_numero.short_description = "Póliza"