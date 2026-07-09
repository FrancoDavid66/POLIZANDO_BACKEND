# servicios/admin.py
from django.contrib import admin
from .models import ServicioFijo, PagoServicio


@admin.register(ServicioFijo)
class ServicioFijoAdmin(admin.ModelAdmin):
    list_display = (
        'nombre',
        'proveedor',
        'categoria',
        'oficina',
        'dia_vencimiento',
        'monto_estimado',
        'activo',
    )
    list_filter = ('activo', 'oficina', 'categoria', 'forma_pago_default')
    search_fields = ('nombre', 'proveedor', 'categoria')
    list_editable = ('activo',)
    readonly_fields = ('creado_en', 'actualizado_en', 'creado_por')

    fieldsets = (
        ('Identificación', {
            'fields': ('nombre', 'proveedor', 'categoria')
        }),
        ('Sucursal y monto', {
            'fields': ('oficina', 'monto_estimado', 'dia_vencimiento')
        }),
        ('Defaults de pago', {
            'fields': ('forma_pago_default',)
        }),
        ('Estado', {
            'fields': ('activo', 'notas')
        }),
        ('Auditoría', {
            'fields': ('creado_en', 'actualizado_en', 'creado_por'),
            'classes': ('collapse',),
        }),
    )


@admin.register(PagoServicio)
class PagoServicioAdmin(admin.ModelAdmin):
    list_display = (
        'servicio',
        'periodo',
        'fecha_vencimiento',
        'estado',
        'monto_real',
        'fecha_pago',
        'pagado_por',
    )
    list_filter = ('estado', 'periodo', 'forma_pago', 'servicio__oficina')
    search_fields = (
        'servicio__nombre',
        'servicio__proveedor',
        'pagado_por__username',
        'observaciones',
    )
    readonly_fields = (
        'creado_en',
        'actualizado_en',
        'hora_pago',
        'egreso',
    )
    autocomplete_fields = ('servicio',)

    fieldsets = (
        ('Servicio y período', {
            'fields': ('servicio', 'periodo', 'fecha_vencimiento', 'estado')
        }),
        ('Datos del pago', {
            'fields': (
                'monto_real',
                'fecha_pago',
                'hora_pago',
                'pagado_por',
                'forma_pago',
                'medio_cobro',
            )
        }),
        ('Comprobante y enlaces', {
            'fields': ('comprobante_url', 'egreso', 'observaciones')
        }),
        ('Auditoría', {
            'fields': ('creado_en', 'actualizado_en'),
            'classes': ('collapse',),
        }),
    )