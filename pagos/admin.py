# pagos/admin.py
from django.contrib import admin, messages
from django.utils import timezone
from collections import defaultdict

from .models import Pago, Cuota, AlertaEnviada, MedioCobro
from pagos.utils.medios import obtener_medio_cobro
from pagos.utils.recordatorios import clasificar_por_rango, armar_mensaje

# ✅ Centralizamos el envío en polizas
from polizas.utils.mensajeria import enviar_whatsapp


# -------------------- Admins --------------------

@admin.register(MedioCobro)
class MedioCobroAdmin(admin.ModelAdmin):
    list_display = (
        "oficina", 
        "proveedor_label", 
        "tipo", 
        "valor", 
        "titular_nombre",
        "activo", 
        "ultimo_uso", 
        "usos_totales",
    )
    
    # 🚀 FIX ERROR E124: Definimos qué campos son los links para entrar al detalle
    # (No puede ser un campo que esté en list_editable)
    list_display_links = ("proveedor_label", "valor")
    
    # 🚀 Te permite cambiar la sucursal y el estado activo directamente en la grilla
    list_editable = ("oficina", "activo")
    
    list_filter = ("oficina", "activo", "proveedor", "tipo")
    search_fields = ("valor", "titular_nombre", "etiqueta", "oficina")
    ordering = ("oficina", "-activo", "ultimo_uso")
    
    readonly_fields = ("usos_totales", "ultimo_uso", "creado", "actualizado")

    actions = ("activar", "desactivar",)

    def proveedor_label(self, obj):
        if obj.proveedor == "mercado_pago":
            return "Mercado Pago"
        if obj.proveedor == "billetera_virtual":
            return "Billetera Virtual"
        return str(obj.proveedor).replace("_", " ").capitalize()
    
    proveedor_label.short_description = "Proveedor"

    @admin.action(description="Activar seleccionados")
    def activar(self, request, queryset):
        updated = queryset.update(activo=True)
        self.message_user(request, f"Activados {updated} medios.", level=messages.SUCCESS)

    @admin.action(description="Desactivar seleccionados")
    def desactivar(self, request, queryset):
        updated = queryset.update(activo=False)
        self.message_user(request, f"Desactivados {updated} medios.", level=messages.SUCCESS)


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ('poliza', 'cuota_nro', 'fecha', 'monto', 'metodo', 'registrado_en_balance')
    list_filter = ('metodo', 'fecha', 'registrado_en_balance')
    search_fields = ('poliza__numero_poliza', 'poliza__cliente__apellido')


@admin.register(Cuota)
class CuotaAdmin(admin.ModelAdmin):
    list_display = ('poliza', 'cuota_nro', 'fecha_vencimiento', 'monto', 'pagado', 'forma_pago')
    list_filter = ('pagado', 'fecha_vencimiento', 'forma_pago')
    search_fields = ('poliza__numero_poliza', 'poliza__cliente__apellido')

    actions = ("accion_enviar_recordatorio", "accion_simular_recordatorio")

    @admin.action(description="Enviar recordatorio por WhatsApp (usando medio rotatorio)")
    def accion_enviar_recordatorio(self, request, queryset):
        self._procesar_recordatorio(request, queryset, simulate=False)

    @admin.action(description="Simular recordatorio (no envía)")
    def accion_simular_recordatorio(self, request, queryset):
        self._procesar_recordatorio(request, queryset, simulate=True)

    def _procesar_recordatorio(self, request, queryset, simulate: bool):
        hoy = timezone.localdate()

        qs = queryset.select_related("poliza", "poliza__cliente").filter(pagado=False)
        if not qs.exists():
            self.message_user(request, "No hay cuotas impagas en la selección.", level=messages.WARNING)
            return

        por_cliente = defaultdict(lambda: defaultdict(list))
        tot_cuotas = 0

        for c in qs:
            cli = c.poliza.cliente
            tipo = clasificar_por_rango(c, hoy)
            if not tipo:
                continue
            por_cliente[cli][tipo].append(c)
            tot_cuotas += 1

        if not por_cliente:
            self.message_user(
                request,
                "Las cuotas seleccionadas están fuera de los rangos de aviso.",
                level=messages.INFO,
            )
            return

        enviados = 0
        omitidos_sin_tel = 0
        fallidos = 0

        for cli, buckets in por_cliente.items():
            tel = (getattr(cli, "telefono", "") or "").strip()
            if not tel:
                omitidos_sin_tel += 1
                continue

            medio = obtener_medio_cobro()

            for t in list(buckets.keys()):
                buckets[t].sort(key=lambda x: (x.fecha_vencimiento, x.poliza_id, x.cuota_nro))

            mensaje = armar_mensaje(cli, buckets, medio)

            try:
                if simulate:
                    print(f"🧪 [SIMULADO] WhatsApp a {tel} — medio: {medio.resumen_para_mensaje}")
                    enviados += 1
                else:
                    ok, info = enviar_whatsapp(tel, mensaje)
                    if ok:
                        enviados += 1
                    else:
                        fallidos += 1
            except Exception:
                fallidos += 1

        resumen = (
            f"Clientes notificados: {enviados} | "
            f"Cuotas incluidas: {tot_cuotas} | "
            f"Sin teléfono: {omitidos_sin_tel} | "
            f"Fallidos: {fallidos}"
        )
        self.message_user(request, resumen, level=messages.SUCCESS if fallidos == 0 else messages.WARNING)


@admin.register(AlertaEnviada)
class AlertaEnviadaAdmin(admin.ModelAdmin):
    list_display = ("cuota", "tipo", "enviada", "fecha")
    list_filter = ("tipo", "enviada", "fecha")
    search_fields = ("cuota__poliza__numero_poliza", "cuota__poliza__patente")