from django.contrib import admin
from .models import Cliente

@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ['apellido', 'nombre', 'dni_cuit_cuil', 'telefono', 'email', 'localidad', 'estado']
    search_fields = ['apellido', 'nombre', 'dni_cuit_cuil', 'localidad']
    list_filter = ['estado']
