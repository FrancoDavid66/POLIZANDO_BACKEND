from django.contrib import admin
from .models import Ingreso, Egreso

@admin.register(Ingreso)
class IngresoAdmin(admin.ModelAdmin):
    list_display = ('descripcion', 'monto', 'fecha', 'categoria')
    search_fields = ('descripcion', 'categoria')

@admin.register(Egreso)
class EgresoAdmin(admin.ModelAdmin):
    list_display = ('descripcion', 'monto', 'fecha', 'categoria')
    search_fields = ('descripcion', 'categoria')
