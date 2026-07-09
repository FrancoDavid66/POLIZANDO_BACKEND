# polizas/domain/renovadas.py

from django.db.models import Q, OuterRef, Exists, Value
from django.db.models.functions import Coalesce, Upper, Trim, Replace

from polizas.domain.bool import to_bool


def exclude_ya_renovadas(qs, request, model_cls):
    """
    Por defecto, en RENOVACIONES ocultamos pólizas que ya tienen una versión más nueva.
    Override: ?include_renovadas=1 (o include_ya_renovadas=1).

    Regla simple:
      - Si existe otra póliza con mismo (patente normalizada) con id mayor -> oculta.
      - Si existe otra póliza con mismo (compania+numero_poliza) con id mayor -> oculta.
    """
    params = getattr(request, "query_params", {}) or {}
    include_renovadas = to_bool(params.get("include_renovadas") or params.get("include_ya_renovadas"))
    if include_renovadas:
        return qs

    pat_norm = Replace(
        Replace(Upper(Trim(Coalesce("patente", Value("")))), Value(" "), Value("")),
        Value("-"),
        Value(""),
    )

    newer_pat_sq = (
        model_cls.objects.exclude(patente__isnull=True)
        .exclude(patente__exact="")
        .annotate(
            _pat=Replace(
                Replace(Upper(Trim(Coalesce("patente", Value("")))), Value(" "), Value("")),
                Value("-"),
                Value(""),
            )
        )
        .filter(_pat=OuterRef("_pat_norm"))
        .filter(id__gt=OuterRef("id"))
    )

    newer_num_comp_sq = (
        model_cls.objects.exclude(numero_poliza__isnull=True)
        .exclude(numero_poliza__exact="")
        .exclude(compania__isnull=True)
        .exclude(compania__exact="")
        .filter(numero_poliza=OuterRef("numero_poliza"), compania=OuterRef("compania"))
        .filter(id__gt=OuterRef("id"))
    )

    qs2 = qs.annotate(
        _pat_norm=pat_norm,
        _has_newer_pat=Exists(newer_pat_sq),
        _has_newer_num_comp=Exists(newer_num_comp_sq),
    )

    return qs2.exclude(
        Q(_pat_norm__isnull=False) & ~Q(_pat_norm__exact="") & Q(_has_newer_pat=True)
    ).exclude(
        Q(numero_poliza__isnull=False)
        & ~Q(numero_poliza__exact="")
        & Q(compania__isnull=False)
        & ~Q(compania__exact="")
        & Q(_has_newer_num_comp=True)
    )
