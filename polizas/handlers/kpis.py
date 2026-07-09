# polizas/handlers/kpis.py
from datetime import timedelta

from django.db.models import Count, OuterRef, Subquery, Q
from django.utils import timezone

from polizas.models import Poliza
from pagos.models import Cuota
from polizas.utils.viewtools import annotate_mora as _annotate_mora


def build_polizas_kpis(viewset, request):
    """
    Lógica de /polizas/kpis extraída del ViewSet.
    Devuelve un dict listo para usar en Response(payload).
    """
    params = request.query_params

    # Base filtrada por los mismos backends del ViewSet (SearchFilter, etc.)
    base_all = Poliza.objects.all().order_by("id")
    for backend in getattr(viewset, "filter_backends", []):
        base_all = backend().filter_queryset(request, base_all, viewset)

    cliente_id = (params.get("cliente") or "").strip()
    patente = (params.get("patente") or "").strip()
    solo_activas = (params.get("solo_activas") or "").lower() in {"1", "true", "t", "yes", "y"}

    if cliente_id.isdigit():
        base_all = base_all.filter(cliente_id=int(cliente_id))
    if patente:
        base_all = base_all.filter(patente__iexact=patente)
    if solo_activas:
        base_all = base_all.filter(estado="activa")

    hoy = timezone.localdate()

    # Anotamos mora sobre activas
    activas = _annotate_mora(base_all.filter(estado="activa"), hoy)

    por_estado = {
        "activa": base_all.filter(estado="activa").count(),
        "vencida": base_all.filter(estado="vencida").count(),
        "cancelada": base_all.filter(estado="cancelada").count(),
        "finalizada": base_all.filter(estado="finalizada").count(),
    }

    kpis_fin = {
        "activas_al_dia": activas.filter(overdue_exists=False).count(),
        "activas_mora_1_30": activas.filter(
            min_overdue__gte=hoy - timedelta(days=30),
            min_overdue__lt=hoy,
        ).count(),
        "activas_mora_31_60": activas.filter(
            min_overdue__gte=hoy - timedelta(days=60),
            min_overdue__lt=hoy - timedelta(days=30),
        ).count(),
        "activas_mora_61_90": activas.filter(
            min_overdue__gte=hoy - timedelta(days=90),
            min_overdue__lt=hoy - timedelta(days=60),
        ).count(),
        "activas_mora_90_mas": activas.filter(
            min_overdue__lt=hoy - timedelta(days=90)
        ).count(),
    }

    # Distribuciones por compañía / cobertura / tipo
    por_compania_qs = Poliza.objects.all()
    for backend in getattr(viewset, "filter_backends", []):
        por_compania_qs = backend().filter_queryset(request, por_compania_qs, viewset)

    por_compania = {
        row["compania"] or "—": row["c"]
        for row in por_compania_qs.values("compania").annotate(c=Count("id")).order_by()
    }

    por_cobertura = None
    if hasattr(Poliza, "cobertura"):
        por_cobertura = {
            row["cobertura"] or "—": row["c"]
            for row in por_compania_qs.values("cobertura").annotate(c=Count("id")).order_by()
        }

    por_tipo = None
    if hasattr(Poliza, "tipo"):
        por_tipo = {
            row["tipo"] or "—": row["c"]
            for row in por_compania_qs.values("tipo").annotate(c=Count("id")).order_by()
        }

    payload = {
        **kpis_fin,
        "vencidas": por_estado["vencida"],
        "canceladas": por_estado["cancelada"],
        "finalizadas": por_estado["finalizada"],
        "total": base_all.count(),
        "por_estado": por_estado,
        "por_compania": por_compania,
        "por_cobertura": por_cobertura,
        "por_tipo": por_tipo,
        "total_global": Poliza.objects.count(),
    }
    return payload


def build_resumen_estados():
    """
    Lógica de /polizas/resumen-estados.

    🆕 UNIFICADO A "ÚLTIMA CUOTA": una póliza está al día si su cuota MÁS RECIENTE
    (la de fecha_vencimiento más alta) está pagada o todavía no venció. Está en mora
    si esa última cuota venció y sigue impaga. Es la MISMA regla que usa la tarjeta de
    Estadísticas y `auto_marcar_vencidas`, así todos los números coinciden.

    Antes usaba el campo `fecha_vencimiento` de la póliza — el mismo que quedó mal por
    el bug de la carga rápida — y por eso mostraba vencidas que no lo eran.
    """
    today = timezone.localdate()
    qs = Poliza.objects.all()

    # Última cuota de cada póliza (la de vencimiento más reciente) + si está pagada.
    ultima_vto = (
        Cuota.objects.filter(poliza=OuterRef("pk"))
        .order_by("-fecha_vencimiento").values("fecha_vencimiento")[:1]
    )
    ultima_pagada = (
        Cuota.objects.filter(poliza=OuterRef("pk"))
        .order_by("-fecha_vencimiento").values("pagado")[:1]
    )

    act = qs.filter(estado="activa").annotate(
        uvto=Subquery(ultima_vto),
        upag=Subquery(ultima_pagada),
    )

    # Al día: última cuota pagada, sin cuotas, o su vencimiento aún está lejos (>7 días).
    al_dia = act.filter(
        Q(upag=True) | Q(uvto__isnull=True) | Q(uvto__gt=today + timedelta(days=7))
    ).count()

    # Los buckets de mora/vencimiento aplican solo a la última cuota IMPAGA.
    impagas = act.filter(upag=False)

    resumen = {
        "al_dia": al_dia,
        "por_vencer": impagas.filter(
            uvto__gt=today, uvto__lte=today + timedelta(days=7)
        ).count(),
        "vence_hoy": impagas.filter(uvto=today).count(),
        "vencida_7": impagas.filter(
            uvto__lt=today, uvto__gte=today - timedelta(days=7)
        ).count(),
        "vencida_30": impagas.filter(
            uvto__lt=today - timedelta(days=7),
            uvto__gte=today - timedelta(days=30),
        ).count(),
        "vencidas": impagas.filter(uvto__lt=today - timedelta(days=30)).count(),
        "canceladas": qs.filter(estado="cancelada").count(),
        "todos": qs.count(),
    }
    return resumen