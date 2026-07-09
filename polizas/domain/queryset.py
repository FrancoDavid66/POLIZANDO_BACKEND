# polizas/domain/queryset.py

from django.db.models import (
    Count,
    Q,
    OuterRef,
    Subquery,
    IntegerField,
    DateField,
    Value,
)
from django.db.models.functions import Coalesce

from polizas.domain.bool import to_bool
from polizas.domain.oficinas import apply_oficina_filter
from polizas.utils.constants import normalizar_compania
from polizas.utils.viewtools import apply_financial_bucket, apply_vencimiento_filters


def build_poliza_queryset(poliza_model, cuota_model, request, action: str):
    """
    Fuente única para armar el queryset de PolizaViewSet (list/renovaciones/vencimientos/etc).
    Mantiene el mismo comportamiento que tenías en views.py pero segmentado.
    """
    qs = poliza_model.objects.all()
    params = getattr(request, "query_params", {}) or {}

    # Regla: FINALIZADA no se muestra en bandejas operativas por defecto
    include_finalizadas = to_bool(params.get("include_finalizadas") or params.get("incluir_finalizadas"))
    if action in {"vencimientos", "vencimientos_resumen", "renovaciones", "renovaciones_resumen"} and not include_finalizadas:
        qs = qs.exclude(estado__iexact="finalizada")

    # Listados livianos: select_related + anotaciones (sin traer cuotas[])
    if action in {"list", "versiones_por_patente", "renovaciones", "vencimientos", "vencimientos_resumen"}:
        qs = qs.select_related("cliente")

        impagas_count_sq = (
            cuota_model.objects.filter(poliza_id=OuterRef("pk"), pagado=False)
            .values("poliza_id")
            .annotate(c=Count("id"))
            .values("c")[:1]
        )

        proxima_vto_sq = (
            cuota_model.objects.filter(poliza_id=OuterRef("pk"), pagado=False)
            .exclude(fecha_vencimiento__isnull=True)
            .order_by("fecha_vencimiento")
            .values("fecha_vencimiento")[:1]
        )

        qs = qs.annotate(
            impagas_count=Coalesce(Subquery(impagas_count_sq, output_field=IntegerField()), Value(0)),
            proxima_vencimiento_impaga=Subquery(proxima_vto_sq, output_field=DateField()),
        )

    # Detail: evita N+1
    if action == "retrieve":
        qs = qs.select_related("cliente").prefetch_related(
            "cuotas",
            "pagos",
            "fotos_vehiculo",
            "documentos",
            "cupones_robo",
        )

    # Filtros comunes
    estado = (params.get("estado") or "").strip()
    compania = (params.get("compania") or "").strip()
    cliente_id = (params.get("cliente") or "").strip()
    patente = (params.get("patente") or "").strip()
    solo_activas = (params.get("solo_activas") or "").lower() in {"1", "true", "t", "yes", "y"}
    fase = (params.get("fase") or "").strip()
    sin_numero = (params.get("sin_numero") or "").lower() in {"1", "true", "t", "yes", "y"}
    oficina = (params.get("oficina") or "").strip()

    # Búsqueda directa por asegurado
    asegurado_q = (params.get("asegurado") or params.get("asegurado_nombre") or "").strip()
    if asegurado_q:
        tokens = [t for t in asegurado_q.split() if t]
        for t in tokens:
            qs = qs.filter(Q(cliente__nombre__icontains=t) | Q(cliente__apellido__icontains=t))

    if estado:
        qs = qs.filter(estado=estado)

    if compania:
        try:
            compania_canon = normalizar_compania(compania)
            qs = qs.filter(compania__iexact=compania_canon)
        except Exception:
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

    if oficina:
        qs = apply_oficina_filter(qs, poliza_model, oficina, field_name="oficina")

    # Filtros auxiliares existentes
    qs = apply_financial_bucket(qs, (params.get("estado_financiero") or ""))
    qs = apply_vencimiento_filters(qs, params)

    return qs
