# polizas/admin.py
from django.contrib import admin
from .models import Poliza, CuponRobo, FotoVehiculo, PolizaDocumento

@admin.register(Poliza)
class PolizaAdmin(admin.ModelAdmin):
    list_display = ('numero_poliza', 'patente', 'cliente', 'compania', 'estado')
    search_fields = ('numero_poliza', 'patente', 'cliente__nombre', 'cliente__apellido')
    list_filter = ('estado', 'fase')

@admin.register(CuponRobo)
class CuponRoboAdmin(admin.ModelAdmin):
    list_display = ('poliza', 'periodo_desde', 'periodo_hasta', 'estado')
    list_filter = ('estado',)

@admin.register(FotoVehiculo)
class FotoVehiculoAdmin(admin.ModelAdmin):
    list_display = ('poliza', 'tipo', 'origen', 'subido_en')

@admin.register(PolizaDocumento)
class PolizaDocumentoAdmin(admin.ModelAdmin):
    list_display = ('poliza', 'tipo', 'nombre', 'created_at')