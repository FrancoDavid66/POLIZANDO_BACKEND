from django.contrib import admin
from .models import SolicitudSeguro, SolicitudDocumento

@admin.register(SolicitudSeguro)
class SolicitudSeguroAdmin(admin.ModelAdmin):
    list_display = ("codigo", "cliente_nombre", "cliente_dni", "vehiculo_patente", "estado", "inicio", "fin", "creado_en")
    list_filter = ("estado", "creado_en")
    search_fields = ("codigo", "cliente_nombre", "cliente_dni", "vehiculo_patente", "vehiculo_modelo", "vehiculo_marca")

@admin.register(SolicitudDocumento)
class SolicitudDocumentoAdmin(admin.ModelAdmin):
    list_display = ("solicitud", "tipo", "nombre", "vencimiento", "creado_en")
    list_filter = ("tipo",)
    search_fields = ("nombre", "public_id")
