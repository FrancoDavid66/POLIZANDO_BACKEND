# usuarios/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import Oficina, Perfil


class PerfilInline(admin.StackedInline):
    """Rol y oficina, embebidos en la misma pantalla del User — no una tabla aparte."""
    model = Perfil
    can_delete = False
    verbose_name_plural = "Perfil"


class CustomUserAdmin(UserAdmin):
    inlines = (PerfilInline,)
    list_display = UserAdmin.list_display + ("get_rol", "get_oficina")

    def get_rol(self, obj):
        return getattr(obj.perfil, "rol", "—") if hasattr(obj, "perfil") else "—"
    get_rol.short_description = "Rol"

    def get_oficina(self, obj):
        return getattr(obj.perfil, "oficina", "—") if hasattr(obj, "perfil") else "—"
    get_oficina.short_description = "Oficina"


admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)


@admin.register(Oficina)
class OficinaAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'activa', 'creado_en')
    search_fields = ('codigo', 'nombre')
    list_filter = ('activa',)