# usuarios/admin.py
from django.contrib import admin
from .models import Oficina, Perfil

@admin.register(Oficina)
class OficinaAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'activa', 'creado_en')
    search_fields = ('codigo', 'nombre')
    list_filter = ('activa',)

@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = ('user', 'rol', 'oficina')
    list_filter = ('rol', 'oficina')
    search_fields = ('user__username', 'user__email', 'user__first_name', 'user__last_name')