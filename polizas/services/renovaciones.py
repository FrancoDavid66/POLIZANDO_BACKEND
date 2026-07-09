# polizas/services/renovaciones.py
from datetime import timedelta, datetime, time

from django.db import connection
from django.db.models import (
    BooleanField,
    Case,
    Count,
    DateField,
    DateTimeField,
    DurationField,
    ExpressionWrapper,
    F,
    IntegerField,
    OuterRef,
    Subquery,
    Value,
    When,
    Q,
)
from django.db.models.functions import Coalesce, ExtractDay, Cast
from django.utils import timezone

from pagos.models import Cuota


def _to_bool(v) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"1", "true", "t", "yes", "y", "on", "si", "sí"}


def _parse_base_date(params):
    raw = (params.get("fecha") or "").strip()
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except Exception:
            pass
    return timezone.localdate()


def _annotate_base_renovaciones(base_qs, hoy):
    base_qs = base_qs.select_related("cliente")

    last_cuota_qs = (
        Cuota.objects.filter(poliza_id=OuterRef("pk"))
        .exclude(fecha_vencimiento__isnull=True)
        .order_by("-cuota_nro", "-fecha_vencimiento", "-id")
    )

    ultima_cuota_nro_sq = last_cuota_qs.values("cuota_nro")[:1]
    ultima_cuota_vto_sq = last_cuota_qs.values("fecha_vencimiento")[:1]

    cuotas_total_sq = (
        Cuota.objects.filter(poliza_id=OuterRef("pk"))
        .values("poliza_id")
        .annotate(c=Count("id"))
        .values("c")[:1]
    )

    qs = base_qs.annotate(
        cuotas_total=Coalesce(Subquery(cuotas_total_sq, output_field=IntegerField()), Value(0)),
        ultima_cuota_nro=Subquery(ultima_cuota_nro_sq, output_field=IntegerField()),
        ultima_cuota_vencimiento=Subquery(ultima_cuota_vto_sq, output_field=DateField()),
    )

    # 🚀 ACÁ HACEMOS LO QUE PEDISTE: Agarramos EXACTAMENTE la fecha de la última cuota, sin sumarle nada.
    qs = qs.annotate(
        vto_referencia=Coalesce("ultima_cuota_vencimiento", "fecha_vencimiento")
    )

    vendor = getattr(connection, "vendor", "")

    hoy_dt = datetime.combine(hoy, time.min)
    if timezone.is_naive(hoy_dt):
        try:
            hoy_dt = timezone.make_aware(hoy_dt, timezone.get_current_timezone())
        except Exception:
            pass

    if vendor == "postgresql":
        delta = ExpressionWrapper(
            Cast(F("vto_referencia"), output_field=DateTimeField()) - Value(hoy_dt),
            output_field=DurationField(),
        )
        qs = qs.annotate(dias_para_vencer_poliza=ExtractDay(delta))
    else:
        qs = qs.annotate(dias_para_vencer_poliza=Value(None, output_field=IntegerField()))

    return qs


def build_renovaciones_queryset(base_qs, params):
    hoy = _parse_base_date(params)

    try:
        dias = int((params.get("dias") or "30").strip())
    except Exception:
        dias = 30
    if dias < 0:
        dias = 0
    limite = hoy + timedelta(days=dias)

    qs = _annotate_base_renovaciones(base_qs, hoy)

    qs = qs.annotate(
        necesita_refacturar=Case(
            When(vto_referencia__isnull=False, vto_referencia__lte=limite, then=Value(True)),
            default=Value(False), output_field=BooleanField()
        ),
        necesita_renovar=Case(
            When(vto_referencia__isnull=False, vto_referencia__lte=limite, then=Value(True)),
            default=Value(False), output_field=BooleanField()
        ),
    )

    solo_pend = _to_bool(params.get("solo_pendientes"))
    if solo_pend:
        qs = qs.filter(
            Q(estado__iexact="activa") | Q(estado__iexact="vencida"),
            vto_referencia__isnull=False,
            vto_referencia__lte=limite,
        )

    bucket = (params.get("bucket") or "").strip().lower()
    if bucket and bucket != "all":
        d1 = hoy + timedelta(days=1)
        d2 = hoy + timedelta(days=2)
        d3 = hoy + timedelta(days=3)
        m1 = hoy - timedelta(days=1)
        m2 = hoy - timedelta(days=2)
        m3 = hoy - timedelta(days=3)
        m4 = hoy - timedelta(days=4)

        if bucket == "hoy":
            qs = qs.filter(vto_referencia=hoy)
        elif bucket == "en_1":
            qs = qs.filter(vto_referencia=d1)
        elif bucket == "en_2":
            qs = qs.filter(vto_referencia=d2)
        elif bucket == "en_3":
            qs = qs.filter(vto_referencia=d3)
        elif bucket == "proximos_3":
            qs = qs.filter(vto_referencia__gte=hoy, vto_referencia__lte=d3)
        elif bucket == "vencida_1":
            qs = qs.filter(vto_referencia=m1)
        elif bucket == "vencida_2":
            qs = qs.filter(vto_referencia=m2)
        elif bucket == "vencida_3":
            qs = qs.filter(vto_referencia=m3)
        elif bucket == "vencidas_3":
            qs = qs.filter(vto_referencia__gte=m3, vto_referencia__lte=m1)
        elif bucket == "vencidas":
            qs = qs.filter(vto_referencia__lte=m4)

    qs = qs.order_by("vto_referencia", "ultima_cuota_vencimiento", "fecha_vencimiento", "-id")
    return qs


def build_renovaciones_resumen(base_qs, params):
    hoy = _parse_base_date(params)

    try:
        dias = int((params.get("dias") or "30").strip())
    except Exception:
        dias = 30
    if dias < 0:
        dias = 0
    limite = hoy + timedelta(days=dias)

    solo_pend = _to_bool(params.get("solo_pendientes"))

    qs = _annotate_base_renovaciones(base_qs, hoy)

    qs = qs.filter(
        Q(estado__iexact="activa") | Q(estado__iexact="vencida"),
        vto_referencia__isnull=False,
    )

    qs_ventana = qs.filter(vto_referencia__lte=limite) if solo_pend else qs

    d1 = hoy + timedelta(days=1)
    d2 = hoy + timedelta(days=2)
    d3 = hoy + timedelta(days=3)
    m1 = hoy - timedelta(days=1)
    m2 = hoy - timedelta(days=2)
    m3 = hoy - timedelta(days=3)
    m4 = hoy - timedelta(days=4)

    agg = qs.aggregate(
        vence_hoy=Count("id", filter=Q(vto_referencia=hoy)),
        vence_en_1=Count("id", filter=Q(vto_referencia=d1)),
        vence_en_2=Count("id", filter=Q(vto_referencia=d2)),
        vence_en_3=Count("id", filter=Q(vto_referencia=d3)),
        proximos_3=Count("id", filter=Q(vto_referencia__gte=hoy, vto_referencia__lte=d3)),
        vencida_1=Count("id", filter=Q(vto_referencia=m1)),
        vencida_2=Count("id", filter=Q(vto_referencia=m2)),
        vencida_3=Count("id", filter=Q(vto_referencia=m3)),
        vencidas_3=Count("id", filter=Q(vto_referencia__gte=m3, vto_referencia__lte=m1)),
        vencidas_4_mas=Count("id", filter=Q(vto_referencia__lte=m4)),
    )

    pendientes_ventana = qs_ventana.count()

    return {
        "hoy": hoy.isoformat(),
        "dias_ventana": dias,
        "limite": limite.isoformat(),
        "solo_pendientes": bool(solo_pend),
        "pendientes_ventana": int(pendientes_ventana),
        "buckets": {
            "vence_hoy": int(agg.get("vence_hoy") or 0),
            "vence_en_1": int(agg.get("vence_en_1") or 0),
            "vence_en_2": int(agg.get("vence_en_2") or 0),
            "vence_en_3": int(agg.get("vence_en_3") or 0),
            "proximos_3": int(agg.get("proximos_3") or 0),
            "vencida_1": int(agg.get("vencida_1") or 0),
            "vencida_2": int(agg.get("vencida_2") or 0),
            "vencida_3": int(agg.get("vencida_3") or 0),
            "vencidas_3": int(agg.get("vencidas_3") or 0),
            "vencidas_4_mas": int(agg.get("vencidas_4_mas") or 0),
        },
    }