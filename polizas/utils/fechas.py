# polizas/utils/fechas.py
"""Helpers de fecha compartidos por Solicitudes, Renovaciones y Tareas.

Antes cada módulo tenía su propia copia de `add_months` / `to_date`
(idénticas salvo detalles). Ahora viven acá y cada archivo los importa con
el alias que ya usaba, así ningún call-site cambia.
"""
from datetime import date, datetime
from calendar import monthrange


def add_months(d: date, months: int) -> date:
    """Suma `months` meses a `d` preservando el día cuando existe; si el mes
    destino no tiene ese día (ej. 31 en febrero), usa el último día del mes."""
    m = (d.month - 1) + months
    y = d.year + (m // 12)
    mm = (m % 12) + 1
    dd = min(d.day, monthrange(y, mm)[1])
    return date(y, mm, dd)


def to_date(v):
    """Convierte 'YYYY-MM-DD' (o date/datetime) a date. None si no se puede."""
    if not v:
        return None
    if isinstance(v, date):
        return v
    try:
        return datetime.fromisoformat(str(v)[:10]).date()
    except Exception:
        return None