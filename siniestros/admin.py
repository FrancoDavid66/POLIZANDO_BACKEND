# siniestros/admin.py
from django.contrib import admin
from django.utils.html import format_html
from .models import Siniestro, SiniestroEvento, SiniestroFoto


class SiniestroEventoInline(admin.TabularInline):
    """Permite ver y editar la línea de tiempo dentro del mismo Siniestro"""
    model = SiniestroEvento
    extra = 1
    fields = ['fecha_evento', 'descripcion_evento']


class SiniestroFotoInline(admin.TabularInline):
    """Galería de fotos del siniestro como inline."""
    model = SiniestroFoto
    extra = 0
    fields = ['miniatura', 'nombre', 'descripcion', 'subida_por', 'fecha_creacion']
    readonly_fields = ['miniatura', 'subida_por', 'fecha_creacion']

    def miniatura(self, obj):
        if obj.url:
            return format_html(
                '<a href="{0}" target="_blank"><img src="{0}" style="max-height:80px; max-width:120px; border-radius:4px;" /></a>',
                obj.url,
            )
        return "—"
    miniatura.short_description = "Vista previa"


@admin.register(Siniestro)
class SiniestroAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'get_estado_color', 'cliente', 'poliza',
        'fecha_siniestro', 'responsabilidad', 'nro_reclamo_cia',
    ]
    list_filter = ['estado', 'responsabilidad', 'poliza__oficina']
    search_fields = ['cliente__nombre', 'patente', 'tercero_patente', 'nro_reclamo_cia']

    fieldsets = (
        ('Información Básica', {
            'fields': ('estado', 'cliente', 'poliza', 'nro_reclamo_cia'),
        }),
        ('Detalles del Accidente', {
            'fields': ('fecha_siniestro', 'responsabilidad', 'descripcion'),
        }),
        ('Vehículo Asegurado', {
            'fields': ('marca_auto', 'modelo_auto', 'ano_auto', 'patente'),
        }),
        ('Datos del Tercero Involucrado', {
            'fields': ('tercero_nombre', 'tercero_telefono', 'tercero_patente', 'tercero_compania', 'tercero_poliza'),
            'classes': ('collapse',),
        }),
    )

    inlines = [SiniestroEventoInline, SiniestroFotoInline]

    @admin.display(description='Estado')
    def get_estado_color(self, obj):
        colors = {
            'PENDIENTE': '#f59e0b',
            'DENUNCIADO': '#3b82f6',
            'CERRADO': '#10b981',
        }
        color = colors.get(obj.estado, '#64748b')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, obj.get_estado_display(),
        )


@admin.register(SiniestroFoto)
class SiniestroFotoAdmin(admin.ModelAdmin):
    list_display = ['id', 'siniestro', 'miniatura', 'nombre', 'subida_por', 'fecha_creacion']
    list_filter = ['fecha_creacion']
    search_fields = ['siniestro__id', 'nombre', 'descripcion']
    readonly_fields = ['miniatura_grande', 'fecha_creacion']

    def miniatura(self, obj):
        if obj.url:
            return format_html(
                '<img src="{}" style="max-height:50px; max-width:80px; border-radius:4px;" />',
                obj.url,
            )
        return "—"
    miniatura.short_description = "Foto"

    def miniatura_grande(self, obj):
        if obj.url:
            return format_html(
                '<a href="{0}" target="_blank"><img src="{0}" style="max-height:300px; max-width:500px; border-radius:8px;" /></a>',
                obj.url,
            )
        return "—"
    miniatura_grande.short_description = "Vista previa"