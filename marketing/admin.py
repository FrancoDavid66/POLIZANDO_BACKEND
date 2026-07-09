from django.contrib import admin
from .models import HistorialMensajeMarketing, HistorialMensajeMarketingLog

class LogInline(admin.TabularInline):
    model = HistorialMensajeMarketingLog
    extra = 0
    readonly_fields = ('numero', 'estado', 'mensaje_renderizado', 'error', 'created_at')
    can_delete = False

@admin.register(HistorialMensajeMarketing)
class HistorialMarketingAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_at', 'oficina', 'total_enviados', 'total_errores', 'dry_run')
    list_filter = ('oficina', 'dry_run', 'created_at')
    inlines = [LogInline]

@admin.register(HistorialMensajeMarketingLog)
class LogMarketingAdmin(admin.ModelAdmin):
    list_display = ('id', 'historial', 'numero', 'estado', 'created_at')
    list_filter = ('estado', 'created_at')
    search_fields = ('numero', 'mensaje_renderizado')