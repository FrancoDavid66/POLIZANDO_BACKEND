# polizas/utils/viewtools.py
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional, Mapping

from django.db.models import (
    OuterRef,
    Subquery,
    Exists,
    DateField,
    QuerySet,
    Q,
    F,
    Case,
    When,
    Value,
    BooleanField,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

# Si tu modelo Cuota está en la app pagos:
from pagos.models import Cuota

# Normalización opcional de compañías (RNE/NRE → RCE, etc.)
try:
    from polizas.utils.constants import normalizar_compania
except Exception:  # pragma: no cover
    normalizar_compania = None


# ---------------- Historia (opcional) ----------------
def hist_log(
    *,
    poliza,
    tipo: str,
    mensaje: str,
    data: Optional[dict] = None,
    categoria: Optional[str] = None,
    severidad: str = "INFO",
    request=None,
    subject=None,
    source: Optional[str] = None,
) -> None:
    """
    Crea un evento en la app 'historia' si está instalada. Si no, no hace nada.
    """
    try:
        from historia.utils import create_event
        from historia.models import PolizaEvento
    except Exception:  # pragma: no cover
        return  # historia no instalada/migrada

    actor = None
    src = source or "SYSTEM"
    if request is not None and getattr(request, "user", None) and request.user.is_authenticated:
        actor = request.user
        if source is None:
            src = "USER"

    create_event(
        poliza=poliza,
        tipo=tipo,
        categoria=categoria or PolizaEvento.Categoria.POLIZA,
        severidad=severidad,
        mensaje=mensaje,
        data=data or {},
        actor=actor,
        subject=subject,
        source=src,
    )


# ---------------- Mora / buckets financieros ----------------
def annotate_mora(qs: QuerySet, hoy: Optional[date] = None) -> QuerySet:
    """
    Anota la mora REAL de cada póliza.

    Las cuotas se pagan POR ADELANTADO, así que la cobertura llega hasta el vto
    de la ÚLTIMA cuota PAGADA. La póliza está en mora si esa cobertura ya venció
    y todavía quedan cuotas impagas. (Si nunca pagó nada, se mira el vto de su
    primera cuota impaga.)

      - min_overdue: fecha en que se cortó la cobertura, o NULL si está al día.
                     Los días de mora = hoy - min_overdue.
      - overdue_exists: True si la póliza está descubierta hoy.

    OJO: NO se usa el vto propio de la cuota impaga (eso daba la mora ~1 mes tarde).
    """
    if hoy is None:
        hoy = timezone.localdate()

    # Cobertura vigente = vto de la ÚLTIMA cuota PAGADA (hasta cuándo está cubierto).
    cobertura_hasta_sq = (
        Cuota.objects
        .filter(poliza_id=OuterRef("pk"), pagado=True)
        .exclude(fecha_vencimiento__isnull=True)
        .order_by("-fecha_vencimiento")
        .values("fecha_vencimiento")[:1]
    )

    # Si nunca pagó nada, la mora arranca en el vto de su primera cuota impaga.
    primer_impaga_sq = (
        Cuota.objects
        .filter(poliza_id=OuterRef("pk"), pagado=False)
        .exclude(fecha_vencimiento__isnull=True)
        .order_by("fecha_vencimiento")
        .values("fecha_vencimiento")[:1]
    )

    qs = qs.annotate(
        _cobertura_hasta=Subquery(cobertura_hasta_sq, output_field=DateField()),
        _primer_impaga=Subquery(primer_impaga_sq, output_field=DateField()),
        _tiene_impaga=Exists(
            Cuota.objects.filter(poliza_id=OuterRef("pk"), pagado=False)
        ),
    ).annotate(
        # Fecha de corte de la cobertura: fin de lo pagado, o (si nunca pagó) el vto de la 1ra cuota.
        _corte_cobertura=Coalesce(F("_cobertura_hasta"), F("_primer_impaga")),
    ).annotate(
        overdue_exists=Case(
            When(Q(_tiene_impaga=True) & Q(_corte_cobertura__lt=hoy), then=Value(True)),
            default=Value(False),
            output_field=BooleanField(),
        ),
        min_overdue=Case(
            When(Q(_tiene_impaga=True) & Q(_corte_cobertura__lt=hoy), then=F("_corte_cobertura")),
            default=Value(None, output_field=DateField()),
            output_field=DateField(),
        ),
    )
    return qs


FIN_BUCKETS = {"al_dia", "mora_1_30", "mora_31_60", "mora_61_90", "mora_90_mas"}


def apply_financial_bucket(qs: QuerySet, bucket: str) -> QuerySet:
    """
    Aplica el filtro por bucket financiero al queryset.
    Si el bucket es inválido, devuelve qs.none() para hacer visible el error de tipado.
    """
    bucket = (bucket or "").strip()
    if not bucket:
        return qs
    if bucket not in FIN_BUCKETS:
        return qs.none()

    hoy = timezone.localdate()
    qs = annotate_mora(qs, hoy)

    if bucket == "al_dia":
        return qs.filter(overdue_exists=False)
    if bucket == "mora_1_30":
        return qs.filter(min_overdue__gte=hoy - timedelta(days=30), min_overdue__lt=hoy)
    if bucket == "mora_31_60":
        return qs.filter(min_overdue__gte=hoy - timedelta(days=60), min_overdue__lt=hoy - timedelta(days=30))
    if bucket == "mora_61_90":
        return qs.filter(min_overdue__gte=hoy - timedelta(days=90), min_overdue__lt=hoy - timedelta(days=60))
    if bucket == "mora_90_mas":
        return qs.filter(min_overdue__lt=hoy - timedelta(days=90))
    return qs


# ---------------- Fechas de vencimiento ----------------
def parse_iso_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s)  # YYYY-MM-DD
    except Exception:
        return None


def apply_vencimiento_filters(qs: QuerySet, params: Mapping[str, str]) -> QuerySet:
    """
    Aplica al queryset:
      - Rango inclusivo: fecha_vencimiento_desde / fecha_vencimiento_hasta
      - Presets: vencidas_ultimos_dias / vencidas_mas_de_dias
    """
    vto_desde = parse_iso_date(params.get("fecha_vencimiento_desde"))
    vto_hasta = parse_iso_date(params.get("fecha_vencimiento_hasta"))
    if vto_desde:
        qs = qs.filter(fecha_vencimiento__gte=vto_desde)
    if vto_hasta:
        qs = qs.filter(fecha_vencimiento__lte=vto_hasta)

    ultimos = params.get("vencidas_ultimos_dias")
    if (ultimos or "").isdigit():
        hoy = timezone.localdate()
        limite = hoy - timedelta(days=int(ultimos))
        qs = qs.filter(estado="vencida", fecha_vencimiento__gte=limite, fecha_vencimiento__lte=hoy)

    mas_de = params.get("vencidas_mas_de_dias")
    if (mas_de or "").isdigit():
        hoy = timezone.localdate()
        limite = hoy - timedelta(days=int(mas_de))
        qs = qs.filter(estado="vencida", fecha_vencimiento__lt=limite)

    return qs


# ---------------- Filtros integrales (para body en acciones custom) ----------------
SEARCH_FIELDS = (
    "patente",
    "marca",
    "modelo",
    "cliente__nombre",
    "cliente__apellido",
    "cliente__dni_cuit_cuil",
    "numero_poliza",
    "compania",
)


def apply_basic_poliza_filters(qs: QuerySet, params: Mapping[str, str]) -> QuerySet:
    """
    Aplica estado, compañia (normalizada si es posible), cliente, patente, fase, sin_numero, solo_activas y search.
    """
    estado = (params.get("estado") or "").strip()
    compania = (params.get("compania") or "").strip()
    cliente_id = (params.get("cliente") or "").strip()
    patente = (params.get("patente") or "").strip()
    solo_activas = (params.get("solo_activas") or "").lower() in {"1", "true", "t", "yes", "y"}
    fase = (params.get("fase") or "").strip()
    sin_numero = (params.get("sin_numero") or "").lower() in {"1", "true", "t", "yes", "y"}

    if estado:
        qs = qs.filter(estado=estado)

    # Normalizar compañía si tenemos util disponible; si no, comparar iexact
    if compania:
        if normalizar_compania:
            try:
                canon = normalizar_compania(compania)
                qs = qs.filter(compania__iexact=canon)
            except Exception:
                qs = qs.filter(compania__iexact=compania)
        else:
            qs = qs.filter(compania__iexact=compania)

    if cliente_id.isdigit():
        qs = qs.filter(cliente_id=int(cliente_id))
    if patente:
        qs = qs.filter(patente__iexact=patente)
    if solo_activas:
        qs = qs.filter(estado="activa")
    if fase:
        qs = qs.filter(fase=fase)
    if sin_numero:
        qs = qs.filter(sin_numero=True)

    search = (params.get("search") or "").strip()
    if search:
        q = Q()
        for f in SEARCH_FIELDS:
            q |= Q(**{f"{f}__icontains": search})
        qs = qs.filter(q)

    return qs


def apply_poliza_filters(qs: QuerySet, params: Mapping[str, str]) -> QuerySet:
    """Aplica filtros básicos + bucket financiero + vencimientos (para acciones custom)."""
    qs = apply_basic_poliza_filters(qs, params)
    qs = apply_financial_bucket(qs, (params.get("estado_financiero") or ""))
    qs = apply_vencimiento_filters(qs, params)
    return qs