# notificaciones/utils/balanzes/messages.py
import re
from decimal import Decimal
from typing import Optional


def _to_decimal(value):
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def format_money(value):
    """
    Formatea números decimales como $ 12.345,67 (simple).
    """
    d = _to_decimal(value)
    s = f"{d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"$ {s}"


def format_phone_ar(raw: Optional[str]) -> Optional[str]:
    """
    Normaliza teléfonos AR a algo razonable para UltraMsg:
    - 11XXXXXXXX (10 dígitos) → 54911XXXXXXXX
    - 54... sin 9 → 549...
    - 549... o 54... → se respeta
    """
    if not raw:
        return None

    digits = re.sub(r"\D+", "", raw)
    if not digits:
        return None

    if digits.startswith("11") and len(digits) == 10:
        return "549" + digits

    if digits.startswith("54") and not digits.startswith("549"):
        return "549" + digits[2:]

    if digits.startswith("549") or digits.startswith("54"):
        return digits

    if len(digits) >= 10:
        return "54" + digits

    return None


def _render_block(title: str, payload: dict) -> list:
    tot = payload.get("totales") or {}
    t_ing = format_money(tot.get("ingresos", "0"))
    t_egr = format_money(tot.get("egresos", "0"))
    t_bal = format_money(tot.get("balance", "0"))

    lineas = []
    lineas.append(f"🏢 *{title}*")
    lineas.append(f"➡️ Ingresos: {t_ing}")
    lineas.append(f"⬅️ Egresos: {t_egr}")
    lineas.append(f"🟰 Balance: {t_bal}")

    pagadores = tot.get("pagadores_distintos", None)
    if pagadores is not None:
        lineas.append(f"👤 Pagadores: {pagadores}")

    movs_ing = tot.get("ingresos_cantidad", None)
    movs_egr = tot.get("egresos_cantidad", None)
    if movs_ing is not None or movs_egr is not None:
        lineas.append(f"📌 Movs: +{movs_ing or 0} / -{movs_egr or 0}")

    return lineas


def build_balance_message(fecha, data: dict) -> str:
    """
    Construye el texto del mensaje WhatsApp para balance diario.
    Si viene data["por_oficina"], imprime por oficina y al final total general.
    """
    fecha_hum = data.get("fecha_hum") or fecha.strftime("%d/%m/%Y")

    lineas = []
    lineas.append(f"📊 *Balance del día {fecha_hum}*")
    lineas.append("")

    por_oficina = data.get("por_oficina") or []
    if por_oficina:
        for block in por_oficina:
            scope = block.get("scope") or {}
            title = scope.get("oficina_nombre") or f"Oficina {scope.get('oficina') or '—'}"
            lineas.extend(_render_block(title, block))
            lineas.append("")

        sin_oficina = data.get("sin_oficina")
        if sin_oficina:
            scope = (sin_oficina.get("scope") or {})
            title = scope.get("oficina_nombre") or "SIN OFICINA"
            lineas.extend(_render_block(title, sin_oficina))
            lineas.append("")

        lineas.append("📌 *TOTAL GENERAL*")
        lineas.extend(_render_block("Total", data))
        lineas.append("— Enviado automáticamente desde el sistema.")
        return "\n".join(lineas)

    lineas.extend(_render_block("Total", data))
    lineas.append("— Enviado automáticamente desde el sistema.")
    return "\n".join(lineas)
