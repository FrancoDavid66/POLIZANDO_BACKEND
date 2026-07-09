from django.contrib import admin
from .models import Propietario, Inquilino, Alquiler, CuotaAlquiler

@admin.register(Propietario)
class PropietarioAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'telefono', 'email')

@admin.register(Inquilino)
class InquilinoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'telefono', 'email')

class CuotaInline(admin.TabularInline):
    model = CuotaAlquiler
    extra = 0

@admin.register(Alquiler)
class AlquilerAdmin(admin.ModelAdmin):
    list_display = ('direccion', 'localidad', 'partido', 'fecha_inicio', 'fecha_fin', 'precio_alquiler')
    inlines = [CuotaInline]
    filter_horizontal = ('inquilinos', 'propietarios')

@admin.register(CuotaAlquiler)
class CuotaAlquilerAdmin(admin.ModelAdmin):
    list_display = ('alquiler', 'nro_cuota', 'monto', 'fecha_vencimiento', 'pagado')
    list_filter = ('pagado',)
