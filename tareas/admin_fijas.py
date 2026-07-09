# tareas/admin_fijas.py
#
# Para activarlo, agregá al final de tareas/admin.py:
#     from . import admin_fijas  # noqa

from django.contrib import admin

from .models_fijas import TareaFija, CumplimientoTareaFija, Feriado


@admin.register(TareaFija)
class TareaFijaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "oficina", "responsable", "frecuencia", "hora_esperada", "activa", "orden")
    list_filter = ("frecuencia", "activa", "oficina")
    search_fields = ("nombre",)
    list_editable = ("activa", "orden")
    fieldsets = (
        (None, {"fields": ("nombre", "oficina", "responsable", "orden", "activa")}),
        ("Cuándo", {"fields": ("frecuencia", "dias_semana", "hora_esperada")}),
        ("Verificación", {"fields": ("requiere_foto",)}),
    )


@admin.register(CumplimientoTareaFija)
class CumplimientoTareaFijaAdmin(admin.ModelAdmin):
    list_display = ("tarea", "oficina", "fecha", "usuario", "cumplido_en")
    list_filter = ("fecha", "oficina")
    search_fields = ("tarea__nombre",)
    date_hierarchy = "fecha"


@admin.register(Feriado)
class FeriadoAdmin(admin.ModelAdmin):
    list_display = ("fecha", "nombre", "nacional")
    list_filter = ("nacional",)
    ordering = ("fecha",)