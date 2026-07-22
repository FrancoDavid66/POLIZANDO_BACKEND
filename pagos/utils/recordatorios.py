# pagos/utils/recordatorios.py
#
# Lógica compartida para armar recordatorios de cuotas por WhatsApp: los
# rangos de días (buckets), los títulos de cada rango, el formato de plata
# y el armado del mensaje final.
#
# Antes esto estaba reimplementado casi igual en 2 lugares (pagos/admin.py,
# para el envío manual desde el panel de admin; y el sistema de recordatorios
# automáticos en notificaciones/). Se centraliza acá para que un cambio de
# umbral o de texto no haya que acordarse de tocarlo en 2 lugares.
from decimal import Decimal


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
    """
    Devuelve la key del bucket ("3_antes", "hoy", "3_despues", "7_despues",
    "30_despues") según cuántos días faltan/pasaron desde el vencimiento de
    la cuota, o None si está fuera de esos rangos.
    """
    from datetime import timedelta

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
    return None  # fuera de los rangos "visibles"


def armar_mensaje(cliente, cuotas_por_tipo, medio_cobro):
    """
    Arma el texto del WhatsApp para un cliente, agrupando sus cuotas por
    tipo de rango (bucket). `cuotas_por_tipo` es un dict {tipo: [cuotas]}.
    """
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