# polizas/services/vencimientos.py
from datetime import date, timedelta

from django.db.models import DateField, F
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone


def _hoy_localdate() -> date:
    return timezone.localdate()


def _base_date(params) -> date:
    """
    Permite simular una fecha base:
      ?fecha=YYYY-MM-DD  (alias: ?base_date=YYYY-MM-DD)
    Si no viene o es inválida => hoy local.
    """
    if not hasattr(params, "get"):
        return _hoy_localdate()

    raw = (params.get("fecha") or params.get("base_date") or "").strip()
    if not raw:
        return _hoy_localdate()

    try:
        return date.fromisoformat(raw)
    except Exception:
        return _hoy_localdate()


def annotate_vencimientos(qs):
    """
    Agrega:
      - vto_referencia: usa la PROXIMA CUOTA IMPAGA si existe.
        (fallbacks: ultima_cuota_vencimiento, fecha_vencimiento)
      - vto_referencia_date: vto_referencia normalizado a DATE (sin hora)

    Importante:
      - proxima_vencimiento_impaga e impagas_count se anotan en PolizaViewSet.get_queryset()
        para las actions vencimientos/vencimientos_resumen.
    """
    # ✅ CLAVE: vencimientos por CUOTAS => próxima cuota IMPAGA
    vto_ref = Coalesce(
        F("proxima_vencimiento_impaga"),
        F("ultima_cuota_vencimiento"),
        F("fecha_vencimiento"),
    )

    qs = qs.annotate(vto_referencia=vto_ref)

    # ✅ CLAVE: trabajar en DATE, evita bugs por timezone al castear Date->DateTime
    qs = qs.annotate(
        vto_referencia_date=Cast(F("vto_referencia"), output_field=DateField()),
    )

    return qs


def build_vencimientos_queryset(queryset, params_or_past_days=30, future_days=3):
    """
    Acepta:
      - build_vencimientos_queryset(qs, request.query_params)
      - build_vencimientos_queryset(qs, past_days=30, future_days=3)

    Params soportados:
      - past_days (default 30)
      - future_days (default 3)
      - modo: all | vencidas | hoy | por_vencer
        * vencidas   => [hoy-past_days .. ayer]
        * hoy        => [hoy]
        * por_vencer => [mañana .. hoy+future_days]
        * all        => [hoy-past_days .. hoy+future_days]
      - ✅ fecha=YYYY-MM-DD (opcional): simula fecha base

    Regla:
      - Solo consideramos pólizas con cuotas IMPAGAS (si no hay impagas, no debe aparecer).
    """
    # --- Parse params ---
    if hasattr(params_or_past_days, "get"):
        params = params_or_past_days
        past_days = int(params.get("past_days", 30) or 30)
        future_days = int(params.get("future_days", 3) or 3)
        modo = (params.get("modo") or "all").strip().lower()
        hoy = _base_date(params)  # ✅ NUEVO
    else:
        past_days = int(params_or_past_days or 30)
        future_days = int(future_days or 3)
        modo = "all"
        hoy = _hoy_localdate()

    # --- Annotate base ---
    qs = annotate_vencimientos(queryset)

    # ✅ CLAVE: excluir pólizas sin cuotas impagas (evita “todas pagas” en vencidas)
    qs = qs.filter(proxima_vencimiento_impaga__isnull=False)

    # --- Window base (DATE) ---
    desde = hoy - timedelta(days=past_days)
    hasta = hoy + timedelta(days=future_days)

    qs = qs.filter(vto_referencia_date__range=(desde, hasta))

    # --- Modo específico ---
    if modo == "vencidas":
        ayer = hoy - timedelta(days=1)
        qs = qs.filter(vto_referencia_date__range=(desde, ayer))

    elif modo == "hoy":
        qs = qs.filter(vto_referencia_date=hoy)

    elif modo == "por_vencer":
        manana = hoy + timedelta(days=1)
        qs = qs.filter(vto_referencia_date__range=(manana, hasta))

    return qs


def build_vencimientos_resumen(queryset, params_or_past_days=30, future_days=3):
    """
    Devuelve conteos acumulados:
      vencidas_3, vencidas_7, vencidas_14, vencidas_30, vence_hoy, por_vencer_3

    Regla:
      - Solo cuenta pólizas con cuotas IMPAGAS.
      - ✅ soporta fecha=YYYY-MM-DD para simular
    """
    if hasattr(params_or_past_days, "get"):
        params = params_or_past_days
        past_days = int(params.get("past_days", 30) or 30)
        future_days = int(params.get("future_days", 3) or 3)
        hoy = _base_date(params)  # ✅ NUEVO
    else:
        past_days = int(params_or_past_days or 30)
        future_days = int(future_days or 3)
        hoy = _hoy_localdate()

    qs = annotate_vencimientos(queryset)

    # ✅ CLAVE: excluir pólizas sin impagas también en el resumen
    qs = qs.filter(proxima_vencimiento_impaga__isnull=False)

    def count_between(delta_from: int, delta_to: int) -> int:
        """
        Cuenta vto_referencia_date dentro de [hoy+delta_from, hoy+delta_to] inclusive.
        Ej:
          (-7,-1) => vencidas en últimos 7 días (sin hoy)
          (0,0)   => hoy
          (1,3)   => por vencer en 3 días
        """
        d1 = hoy + timedelta(days=delta_from)
        d2 = hoy + timedelta(days=delta_to)
        return qs.filter(vto_referencia_date__range=(d1, d2)).count()

    return {
        "hoy": hoy.isoformat(),
        "past_days": past_days,
        "future_days": future_days,
        "vencidas_3": count_between(-3, -1),
        "vencidas_7": count_between(-7, -1),
        "vencidas_14": count_between(-14, -1),
        "vencidas_30": count_between(-30, -1),
        "vence_hoy": count_between(0, 0),
        "por_vencer_3": count_between(1, 3),
    }
