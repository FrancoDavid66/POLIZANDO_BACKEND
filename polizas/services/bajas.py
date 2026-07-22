# polizas/services/bajas.py
from datetime import timedelta, date

from django.db.models import F, DateField
from django.db.models.functions import Coalesce, Cast
from django.utils import timezone


def _parse_int(v, default):
    try:
        return int(str(v).strip())
    except Exception:
        return default


def annotate_bajas(qs):
    """
    🎯 REGLA UNIFICADA (frontend + backend):
       días_vencida = hoy − fecha_vencimiento_cuota_IMPAGA_MÁS_ANTIGUA

    La fecha de referencia es la cuota IMPAGA más antigua que ya venció,
    NO la última cuota de la póliza ni la fecha genérica de vencimiento.

    Ejemplo: póliza con cuotas 3 y 4 impagas (cuota 3 venció hace 34 días,
    cuota 4 hace 4 días) → días_vencida = 34 (desde cuota 3).

    El campo `proxima_vencimiento_impaga` del backend es justamente eso:
    la cuota impaga con menor fecha_vencimiento (= más antigua, porque
    las cuotas se pagan en orden, no podés pagar la 4 antes que la 3).

    Fallbacks SOLO si la póliza no tiene cuotas cargadas todavía:
      1. proxima_vencimiento_impaga  ← cuota impaga más antigua (preferido)
      2. ultima_cuota_vencimiento    ← última cuota (legacy)
      3. fecha_vencimiento           ← vto genérico de la póliza
    """
    vto_ref = Coalesce(
        F("proxima_vencimiento_impaga"),
        F("ultima_cuota_vencimiento"),
        F("fecha_vencimiento"),
    )
    return qs.annotate(vto_referencia_date=Cast(vto_ref, DateField()))


def build_bajas_queryset(qs, params):
    """
    GET /api/polizas/bajas/?dias=30&fecha=YYYY-MM-DD
    Regla: vto_referencia_date <= base - dias
    """
    base = timezone.localdate()
    raw_fecha = (params.get("fecha") or "").strip()
    if raw_fecha:
        try:
            base = date.fromisoformat(raw_fecha)
        except Exception:
            pass

    dias = _parse_int(params.get("dias") or 30, 30)
    dias = max(1, min(3650, dias))

    cutoff = base - timedelta(days=dias)

    qs = annotate_bajas(qs)
    qs = qs.exclude(vto_referencia_date__isnull=True)
    qs = qs.filter(vto_referencia_date__lte=cutoff)
    return qs


def build_bajas_resumen(qs, params):
    base = timezone.localdate()
    raw_fecha = (params.get("fecha") or "").strip()
    if raw_fecha:
        try:
            base = date.fromisoformat(raw_fecha)
        except Exception:
            pass

    dias = _parse_int(params.get("dias") or 30, 30)
    dias = max(1, min(3650, dias))

    cutoff = base - timedelta(days=dias)

    qs = annotate_bajas(qs)
    total = qs.exclude(vto_referencia_date__isnull=True).filter(vto_referencia_date__lte=cutoff).count()

    return {
        "fecha_base": base.isoformat(),
        "dias": dias,
        "total": int(total),
    }