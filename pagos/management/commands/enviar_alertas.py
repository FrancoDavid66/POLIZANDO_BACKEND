from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from collections import defaultdict
from decimal import Decimal

from pagos.models import Cuota
from polizas.utils.ultramsg import enviar_mensaje
from pagos.utils.medios import obtener_medio_cobro  # NUEVO: rotación de medio de cobro


# -------------------- Formatos / textos --------------------

TITULOS = {
    "3_antes": "📌 Recordatorio: tenés cuotas que vencen pronto",
    "hoy": "⚠️ Hoy vencen tus cuotas",
    "3_despues": "🔔 Tenés cuotas vencidas hace 3 días",
    "7_despues": "❗ Atraso importante: cuotas vencidas hace 1 semana",
    "30_despues": "🚨 Último aviso para recuperar cobertura: cuotas vencidas hace 30 días o más",
}


def fmt_money(value) -> str:
    """
    Formatea números como moneda argentina: $ 1.234,56
    Evita depender de locale del sistema.
    """
    try:
        d = Decimal(str(value or "0"))
        s = f"{d:,.2f}"  # 1,234,567.89
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
        return f"$ {s}"
    except Exception:
        return f"$ {value}"


def armar_rangos(hoy):
    """
    Devuelve los rangos de fechas (inclusive) para buscar cuotas no pagadas.
    Claves pensadas para lectura y reporting.
    """
    return {
        "3_antes": (hoy + timedelta(days=1), hoy + timedelta(days=3)),
        "hoy": (hoy, hoy),
        "3_despues": (hoy - timedelta(days=3), hoy - timedelta(days=1)),
        "7_despues": (hoy - timedelta(days=7), hoy - timedelta(days=4)),
        # 🆕 "30 días o más": ahora agarra de 30 a 60 días vencida (antes agarraba desde 8).
        "30_despues": (hoy - timedelta(days=60), hoy - timedelta(days=30)),
    }


def armar_mensaje_cliente(cliente, alertas_por_tipo, medio_cobro):
    """
    Construye un único mensaje por cliente incluyendo todas las cuotas agrupadas por tipo de alerta.
    El cierre muestra el medio de cobro rotado (proveedor + titular + valor).
    """
    encabezado = (
        f"📣 ¡Hola {cliente.nombre} {cliente.apellido}! "
        f"Estas son tus cuotas pendientes de diferentes pólizas:\n"
    )

    partes = [encabezado]

    for tipo, cuotas in alertas_por_tipo.items():
        titulo = TITULOS.get(tipo, "🔔 Recordatorio de vencimiento")
        partes.append(f"\n{titulo}:\n")

        for cuota in cuotas:
            p = cuota.poliza
            partes.append(
                "— "
                + f"Cuota #{cuota.cuota_nro} — {p.marca} {p.modelo} ({p.patente})\n"
                + f"   🏢 Compañía: {p.compania}\n"
                + f"   📅 Vencimiento: {cuota.fecha_vencimiento.strftime('%d/%m/%Y')}\n"
                + f"   💸 Monto: {fmt_money(cuota.monto)}\n"
            )

    partes.append(
        "\n💬 Podés abonar:\n"
        "• 💵 En efectivo en nuestra oficina\n"
        f"• 💳 Por {medio_cobro.resumen_para_mensaje}\n\n"
        "Si ya pagaste, ignorá este mensaje. ¡Gracias por confiar en nosotros! 💙"
    )

    return "".join(partes)


def ejecutar_alertas(simulate=False, cliente_id=None, telefono_contiene=None, force_medio_valor=None):
    """
    Ejecuta el barrido de cuotas y envía (o simula) los mensajes por WhatsApp agrupados por cliente.
    Usa medio de cobro rotatorio; si se pasa force_medio_valor, lo usa fijo.
    Retorna un resumen con contadores.
    """
    hoy = timezone.localdate()
    rangos = armar_rangos(hoy)

    print(f"\n📅 Fecha actual: {hoy}")
    print("🔎 Buscando cuotas para enviar alertas...\n")

    # Estructuras de agregación
    clientes_alertas = defaultdict(lambda: defaultdict(list))
    contadores_por_tipo = defaultdict(int)

    # Recolecta cuotas por rango/tipo
    for tipo, (desde, hasta) in rangos.items():
        qs = (
            Cuota.objects.filter(
                pagado=False,
                fecha_vencimiento__range=(desde, hasta),
                poliza__estado__in=["activa", "vencida"],  # 🆕 no alertar canceladas/finalizadas
            )
            .select_related("poliza", "poliza__cliente")
            .order_by("fecha_vencimiento", "poliza__id", "cuota_nro")
        )

        # Filtros de testing/debug opcionales
        if cliente_id:
            qs = qs.filter(poliza__cliente_id=cliente_id)
        if telefono_contiene:
            qs = qs.filter(poliza__cliente__telefono__icontains=telefono_contiene)

        cuotas = list(qs)
        contadores_por_tipo[tipo] += len(cuotas)

        for cuota in cuotas:
            cliente = cuota.poliza.cliente
            clientes_alertas[cliente][tipo].append(cuota)

    # Envío / simulación por cliente
    total_clientes = 0
    total_cuotas = 0
    total_ok = 0
    total_error = 0

    for cliente, alertas in clientes_alertas.items():
        if not getattr(cliente, "telefono", None):
            print(f"⚠️ Cliente {cliente.id} sin teléfono. Omitido.")
            continue

        # Medio de cobro por cliente (rotado)
        medio = obtener_medio_cobro(force_valor=force_medio_valor)

        # Ordena las listas por tipo para una salida consistente
        for tipo in list(alertas.keys()):
            alertas[tipo].sort(key=lambda c: (c.fecha_vencimiento, c.poliza_id, c.cuota_nro))

        mensaje = armar_mensaje_cliente(cliente, alertas, medio)
        cuotas_count = sum(len(lst) for lst in alertas.values())

        try:
            if simulate:
                print(f"🧪 [SIMULADO] WhatsApp a {cliente.telefono} ({cuotas_count} cuotas) – medio: {medio.resumen_para_mensaje}")
                total_ok += 1
            else:
                enviar_mensaje(cliente.telefono, mensaje)
                print(f"✅ WhatsApp enviado a {cliente.telefono} ({cuotas_count} cuotas) – medio: {medio.resumen_para_mensaje}")
                total_ok += 1

            total_clientes += 1
            total_cuotas += cuotas_count

        except Exception as e:
            print(f"❌ Error al enviar a {cliente.telefono}: {e}")
            total_error += 1

    # Resumen
    print("\n— Resumen por tipo —")
    for tipo in ["3_antes", "hoy", "3_despues", "7_despues", "30_despues"]:
        print(f"  {TITULOS.get(tipo, tipo)}: {contadores_por_tipo.get(tipo, 0)} cuotas")

    print(
        f"\n📤 Clientes notificados: {total_clientes} | "
        f"Cuotas incluidas: {total_cuotas} | "
        f"OK: {total_ok} | Errores: {total_error}"
    )

    return {
        "fecha": str(hoy),
        "clientes_notificados": total_clientes,
        "cuotas_incluidas": total_cuotas,
        "ok": total_ok,
        "errores": total_error,
        "por_tipo": dict(contadores_por_tipo),
        "simulate": simulate,
    }


# 🎯 Comando: python manage.py enviar_alertas [--simulate] [--cliente-id 123] [--tel 1166] [--medio alias_o_cbu_o_link]
class Command(BaseCommand):
    help = "Envía alertas por WhatsApp para cuotas próximas a vencer (agrupado por cliente) usando medio de cobro rotatorio."

    def add_arguments(self, parser):
        parser.add_argument("--simulate", action="store_true", help="No envía WhatsApp; solo simula el proceso.")
        parser.add_argument("--cliente-id", type=int, help="Filtra por ID de cliente (para pruebas).")
        parser.add_argument("--tel", type=str, help="Filtra por teléfono que contenga el texto (para pruebas).")
        parser.add_argument("--medio", type=str, help="Forzar un valor específico (alias/CBU/CVU/link) y omitir rotación.")

    def handle(self, *args, **kwargs):
        simulate = bool(kwargs.get("simulate"))
        cliente_id = kwargs.get("cliente_id")
        telefono_contiene = kwargs.get("tel")
        force_medio_valor = kwargs.get("medio")  # alias/CBU/CVU/link puntual
        ejecutar_alertas(
            simulate=simulate,
            cliente_id=cliente_id,
            telefono_contiene=telefono_contiene,
            force_medio_valor=force_medio_valor,
        )