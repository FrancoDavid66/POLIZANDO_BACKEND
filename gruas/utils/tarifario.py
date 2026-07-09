from decimal import Decimal
from django.utils import timezone
from django.db import models

from ..models import TarifarioProveedor


def _to_decimal(v) -> Decimal:
    try:
        if v is None:
            return Decimal("0")
        return Decimal(str(v))
    except Exception:
        return Decimal("0")


def _vigente_para_proveedor(proveedor, on_date=None):
    """
    Devuelve el TarifarioProveedor vigente para el proveedor en una fecha.
    Reglas:
      - vigente_desde <= fecha
      - y (vigente_hasta is null o vigente_hasta >= fecha)
      - si hay varios, toma el más reciente (vigente_desde desc, id desc)
    """
    if not proveedor:
        return None

    d = on_date or timezone.localdate()
    qs = (
        TarifarioProveedor.objects
        .filter(proveedor=proveedor, vigente_desde__lte=d)
        .filter(models.Q(vigente_hasta__isnull=True) | models.Q(vigente_hasta__gte=d))
    )
    return qs.order_by("-vigente_desde", "-id").first()


def calcular_costo_proveedor(proveedor, km_totales, on_date=None):
    """
    Cálculo:
      1) Si hay rangos y km cae en un rango => base = precio_fijo del rango
      2) Luego, si km > km_extra_desde => suma extra = (km - km_extra_desde) * precio_km_extra
         (Se suma sobre la base, no reemplaza)
      3) Si no hay rango aplicable => base = 0 y se aplica solo extra si corresponde
    """
    if not proveedor:
        return Decimal("0.00")

    km = _to_decimal(km_totales)
    tp = _vigente_para_proveedor(proveedor, on_date=on_date)
    if not tp:
        return Decimal("0.00")

    base = Decimal("0.00")

    # 1) Precio fijo por rangos si existen
    rangos = list(tp.rangos.all().order_by("km_min"))
    for r in rangos:
        km_min = _to_decimal(r.km_min)
        km_max = None if r.km_max is None else _to_decimal(r.km_max)

        if km_max is None:
            if km >= km_min:
                base = _to_decimal(r.precio_fijo)
        else:
            if km_min <= km <= km_max:
                base = _to_decimal(r.precio_fijo)
                break

    # 2) Km extra a partir de km_extra_desde
    extra_desde = _to_decimal(tp.km_extra_desde)
    precio_km_extra = _to_decimal(getattr(tp, "precio_km_extra", None))

    extra = Decimal("0.00")
    if km > extra_desde and precio_km_extra > 0:
        extra = (km - extra_desde) * precio_km_extra

    total = base + extra
    if total < 0:
        return Decimal("0.00")

    return total.quantize(Decimal("0.01"))
