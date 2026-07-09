# polizas/domain/robo.py

from datetime import date
from calendar import monthrange

from polizas.models import CuponRobo
from pagos.models import Cuota
from polizas.utils.viewtools import hist_log as _hist_log


def _cobertura_tiene_cupones(poliza) -> bool:
    """
    Decide si una póliza lleva cuponera de robo.

    Prioridad:
      1) Si la póliza tiene cobertura_obj (FK al catálogo Admin) → usar el flag de ahí.
      2) Si no, buscar TipoCobertura por (compañía + cobertura) en el Admin.
      3) Si no encuentra, devolver False (no se generan cupones).
    """
    # 1) Cobertura vinculada (FK) — fuente más confiable
    cob_obj = getattr(poliza, "cobertura_obj", None)
    if cob_obj is not None:
        return bool(getattr(cob_obj, "genera_cupones_robo", False))

    # 2) Búsqueda por nombre (compañía + cobertura)
    try:
        from cotizaciones.models import TipoCobertura
        from polizas.utils.constants import normalizar_compania, normalizar_cobertura

        cob_nombre = normalizar_cobertura(getattr(poliza, "cobertura", "") or "")
        comp_nombre = normalizar_compania(getattr(poliza, "compania", "") or "")

        if not cob_nombre or not comp_nombre:
            return False

        cob = (
            TipoCobertura.objects
            .filter(nombre__iexact=cob_nombre, compania__nombre__iexact=comp_nombre)
            .first()
        )
        if cob is not None:
            return bool(cob.genera_cupones_robo)
    except Exception:
        pass

    return False


def ensure_cupones_robo_for_poliza(poliza) -> None:
    """
    Genera cupones de robo mensuales basados en las cuotas de la póliza.

    Reglas:
      - ✅ Solo si la cobertura del Admin tiene genera_cupones_robo=True.
        (Ya NO se mira si el nombre de cobertura contiene "ROBO".)
      - Solo si aún no existen cupones para esa póliza (idempotente).
      - Crea 1 cupón por cuota:
          periodo_desde = primer día del mes del vencimiento
          periodo_hasta = último día del mes del vencimiento
          fecha_vencimiento = fecha_vencimiento de la cuota
          estado = PENDIENTE
    """
    if not _cobertura_tiene_cupones(poliza):
        return

    # Si ya hay cupones, no duplicar
    if CuponRobo.objects.filter(poliza=poliza).exists():
        return

    cuotas = (
        Cuota.objects.filter(poliza=poliza)
        .exclude(fecha_vencimiento__isnull=True)
        .order_by("fecha_vencimiento", "cuota_nro", "id")
    )
    if not cuotas.exists():
        return

    created = 0
    for c in cuotas:
        vto = c.fecha_vencimiento
        if not vto:
            continue

        last_day = monthrange(vto.year, vto.month)[1]
        periodo_desde = date(vto.year, vto.month, 1)
        periodo_hasta = date(vto.year, vto.month, last_day)

        CuponRobo.objects.create(
            poliza=poliza,
            periodo_desde=periodo_desde,
            periodo_hasta=periodo_hasta,
            fecha_vencimiento=vto,
            estado=CuponRobo.Estado.PENDIENTE,
        )
        created += 1

    if created:
        _hist_log(
            poliza=poliza,
            tipo="CUPONES_ROBO_AUTOGENERADOS",
            mensaje=f"Generados {created} cupones de robo a partir de cuotas",
            severidad="INFO",
            data={"cupones_creados": created},
            request=None,
            subject=poliza,
            categoria="POLIZA",
        )