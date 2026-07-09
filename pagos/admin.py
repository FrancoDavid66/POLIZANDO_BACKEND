# pagos/admin.py — Reemplaza TODO el archivo con esta versión
from django.contrib import admin, messages
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from collections import defaultdict

from .models import Pago, Cuota, AlertaEnviada, MedioCobro
from pagos.utils.medios import obtener_medio_cobro

# ✅ Centralizamos el envío en polizas
from polizas.utils.mensajeria import enviar_whatsapp


# -------------------- Helpers de armado de mensaje --------------------

TITULOS = {
    "3_antes": "📌 Recordatorio: tenés cuotas que vencen pronto",
    "hoy": "⚠️ Hoy vencen tus cuotas",
    "3_despues": "🔔 Tenés cuotas vencidas hace 3 días",
    "7_despues": "❗ Atraso importante: cuotas vencidas hace 1 semana",
    "30_despues": "🚨 Último aviso para recuperar cobertura: cuotas vencidas hace 30 días",
}

def fmt_money(value) -> str:
    try:
        d = Decimal(str(value or "0"))
        s = f"{d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"$ {s}"
    except Exception:
        return f"$ {value}"

def clasificar_por_rango(cuota, hoy):
    vto = cuota.fecha_vencimiento
    if not vto:
        return None
    if hoy + timedelta(days=1) <= vto <= hoy + timedelta(days=3):
        return "3_antes"
    if vto == hoy:
        return "hoy"
    if hoy - timedelta(days=3) <= vto <= hoy - timedelta(days=1):
        return "3_despues"
    if hoy - timedelta(days=7) <= vto <= hoy - timedelta(days=4):
        return "7_despues"
    if hoy - timedelta(days=30) <= vto <= hoy - timedelta(days=8):
        return "30_despues"
    return None  # fuera de los rangos “visibles”; igual lo podemos listar si querés

def armar_mensaje(cliente, cuotas_por_tipo, medio_cobro):
    encabezado = (
        f"📣 ¡Hola {cliente.nombre} {cliente.apellido}! "
        f"Estas son tus cuotas pendientes de diferentes pólizas:\n"
    )
    partes = [encabezado]
    for tipo, cuotas in cuotas_por_tipo.items():
        if not cuotas:
            continue
        titulo = TITULOS.get(tipo, "🔔 Recordatorio de vencimiento")
        partes.append(f"\n{titulo}:\n")
        for c in cuotas:
            p = c.poliza
            partes.append(
                "— "
                + f"Cuota #{c.cuota_nro} — {p.marca} {p.modelo} ({p.patente})\n"
                + f"   🏢 Compañía: {p.compania}\n"
                + f"   📅 Vencimiento: {c.fecha_vencimiento.strftime('%d/%m/%Y')}\n"
                + f"   💸 Monto: {fmt_money(c.monto)}\n"
            )
    partes.append(
        "\n💬 Podés abonar:\n"
        "• 💵 En efectivo en nuestra oficina\n"
        f"• 💳 Por {medio_cobro.resumen_para_mensaje}\n\n"
        "Si ya pagaste, ignorá este mensaje. ¡Gracias por confiar en nosotros! 💙"
    )
    return "".join(partes)


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