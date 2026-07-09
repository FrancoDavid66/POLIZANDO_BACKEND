# inmuebles/admin.py
from django.contrib import admin
from .models import Propiedad
from .models import Inquilino, Propietario

@admin.register(Propiedad)
class PropiedadAdmin(admin.ModelAdmin):
    list_display = ('direccion', 'localidad', 'partido', 'tipo', 'estado', 'precio', 'fecha_publicacion')
    list_filter = ('tipo', 'estado', 'partido', 'localidad')
    search_fields = ('direccion', 'localidad', 'partido', 'descripcion')




@admin.register(Inquilino)
class InquilinoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'apellido', 'telefono', 'dni')
    search_fields = ('nombre', 'apellido', 'dni')

@admin.register(Propietario)
class PropietarioAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'apellido', 'telefono', 'dni')
    search_fields = ('nombre', 'apellido', 'dni')
