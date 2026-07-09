# polizas/domain/annotations.py

from __future__ import annotations

from django.apps import apps
from django.db.models import OuterRef, Subquery, DateField


def with_ultima_cuota_vencimiento(qs):
    """
    Anota en Poliza queryset:
      - ultima_cuota_vencimiento: fecha_vencimiento máxima de sus cuotas (Date)

    Se implementa con Subquery para que funcione en SQLite/Postgres.
    """
    try:
        Cuota = apps.get_model("pagos", "Cuota")
    except Exception:
        # Si la app/modelo no existe, devolvemos qs sin romper
        return qs

    ultima_vto_sq = (
        Cuota.objects.filter(poliza_id=OuterRef("pk"))
        .exclude(fecha_vencimiento__isnull=True)
        .order_by("-fecha_vencimiento")
        .values("fecha_vencimiento")[:1]
    )

    return qs.annotate(
        ultima_cuota_vencimiento=Subquery(ultima_vto_sq, output_field=DateField())
    )
