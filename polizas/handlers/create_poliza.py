# polizas/handlers/create_poliza.py
from datetime import date, datetime
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from dateutil.relativedelta import relativedelta

from pagos.models import Cuota
from polizas.models import Poliza, CuponRobo
from polizas.utils.constants import normalizar_compania

# 🆕 Lista de precios NRE: precio automático de las cuotas en el alta nueva.
from polizas.precios_nre import es_nre

# Default fallback si no hay cobertura configurada en el Admin
# (solo se usa si el usuario tampoco mandó un override)
DEFAULT_CUOTAS_FALLBACK = 6


def _to_date(d):
    """Acepta date|datetime|None y retorna date (o hoy si None)."""
    if d is None:
        return timezone.localdate()
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    try:
        return datetime.fromisoformat(str(d)).date()
    except Exception:
        return timezone.localdate()


def _resolver_cuotas_y_cupones(poliza, override_cuotas=None):
    """
    Resuelve cantidad de cuotas + flag de cuponera.

    Prioridad:
      1) cobertura_obj (FK al Admin) → si existe, manda
      2) Búsqueda en TipoCobertura por nombre (compañía + cobertura)
      3) override del usuario (si el frontend lo mandó)
      4) Fallback: 6 cuotas, sin cuponera

    Devuelve tupla (cantidad_cuotas, genera_cupones_robo, fuente)
    fuente = "ADMIN_FK" | "ADMIN_LOOKUP" | "OVERRIDE" | "FALLBACK"
    """
    # 1) FK directa
    if poliza.cobertura_obj_id:
        return (
            int(poliza.cobertura_obj.cuotas_a_generar or DEFAULT_CUOTAS_FALLBACK),
            bool(poliza.cobertura_obj.genera_cupones_robo),
            "ADMIN_FK",
        )

    # 2) Búsqueda por nombre (compañía + cobertura) en el Admin
    try:
        from cotizaciones.models import TipoCobertura
        from polizas.utils.constants import normalizar_cobertura

        cob_nombre = normalizar_cobertura(poliza.cobertura or "")
        comp_nombre = normalizar_compania(poliza.compania or "")

        if cob_nombre and comp_nombre:
            cob = (
                TipoCobertura.objects
                .filter(nombre__iexact=cob_nombre, compania__nombre__iexact=comp_nombre)
                .first()
            )
            if cob is not None:
                return (
                    int(cob.cuotas_a_generar or DEFAULT_CUOTAS_FALLBACK),
                    bool(cob.genera_cupones_robo),
                    "ADMIN_LOOKUP",
                )
    except Exception:
        pass

    # 3) Override manual del usuario
    if override_cuotas is not None:
        try:
            return int(override_cuotas), False, "OVERRIDE"
        except (TypeError, ValueError):
            pass

    # 4) Fallback final
    return DEFAULT_CUOTAS_FALLBACK, False, "FALLBACK"


@transaction.atomic
def handle_create_poliza(serializer, compania_config=None):
    numero = serializer.validated_data.get('numero_poliza')

    if numero and Poliza.objects.filter(numero_poliza=numero).exists():
        raise ValidationError({"numero_poliza": "Ya existe una póliza con este número."})

    poliza: Poliza = serializer.save()

    try:
        compania_canonica = normalizar_compania(poliza.compania or "")
    except Exception:
        raise ValidationError({"compania": f"Compañía inválida o no configurada: {poliza.compania!r}"})

    if poliza.compania != compania_canonica:
        poliza.compania = compania_canonica
        poliza.save(update_fields=["compania"])

    fecha_emision = _to_date(getattr(poliza, "fecha_emision", None))

    # ========================================================
    # 🚀 LÓGICA DINÁMICA DE FACTURACIÓN (DESDE COTIZACIONES)
    # Prioridad: cobertura_obj → TipoCobertura por nombre → override → fallback
    # ========================================================
    override_cuotas = None
    if hasattr(serializer, "initial_data"):
        override_cuotas = serializer.initial_data.get("cantidad_cuotas_override")

    cantidad_cuotas, genera_cupones_robo, _fuente = _resolver_cuotas_y_cupones(
        poliza, override_cuotas=override_cuotas
    )

    # 🆕 NRE es trimestral: SIEMPRE 3 cuotas (no importa el fallback ni el override).
    if es_nre(poliza.compania):
        cantidad_cuotas = 3

    # 🆕 CUPONERA (AMCA, La Equidad): si el frontend mandó cupones, MANDAN ellos
    #    (cantidad + fechas + importes reales). NRE nunca tiene cuponera.
    cupones_pdf = []
    if hasattr(serializer, "initial_data"):
        cupones_pdf = serializer.initial_data.get("cupones") or []
    cupones_pdf = [c for c in cupones_pdf if _to_date(c.get("vencimiento"))]
    cupones_pdf.sort(key=lambda c: _to_date(c.get("vencimiento")))
    usar_cupones = bool(cupones_pdf) and not es_nre(poliza.compania)
    if usar_cupones:
        cantidad_cuotas = len(cupones_pdf)

    if getattr(poliza, "cantidad_cuotas", None) != cantidad_cuotas:
        poliza.cantidad_cuotas = cantidad_cuotas
        poliza.save(update_fields=["cantidad_cuotas"])

    # Vigencia total de la póliza basada en la cantidad de cuotas (en meses)
    fecha_vencimiento_calculada = fecha_emision + relativedelta(months=cantidad_cuotas)
    # 🆕 Con cuponera, la vigencia real es el último vencimiento del cupón.
    if usar_cupones:
        fecha_vencimiento_calculada = _to_date(cupones_pdf[-1].get("vencimiento")) or fecha_vencimiento_calculada
    if getattr(poliza, "fecha_vencimiento", None) != fecha_vencimiento_calculada:
        poliza.fecha_vencimiento = fecha_vencimiento_calculada
        poliza.save(update_fields=["fecha_vencimiento"])

    # ========================================================
    # 🏭 FABRICACIÓN DE CUOTAS
    # ========================================================
    existing = list(Cuota.objects.filter(poliza=poliza).values_list("id", flat=True))
    if existing:
        Cuota.objects.filter(id__in=existing).delete()

    cuotas_bulk = []

    # 🆕 Precio: todas las compañías arrancan con las cuotas en 0. El usuario
    #    carga el precio a mano y lo cobra después desde Pagos. Excepción: si
    #    vino una cuponera, cada cuota toma el importe real del cupón.
    if usar_cupones:
        # 🆕 Cuotas EXACTAS de la cuponera (fecha + importe del cupón).
        for i, cup in enumerate(cupones_pdf, start=1):
            try:
                monto_i = float(cup.get("importe") or 0)
            except (TypeError, ValueError):
                monto_i = 0
            cuotas_bulk.append(Cuota(
                poliza=poliza,
                cuota_nro=i,
                fecha_vencimiento=_to_date(cup.get("vencimiento")),
                monto=monto_i,
                pagado=False,
            ))
    else:
        for i in range(1, cantidad_cuotas + 1):
            venc = fecha_emision + relativedelta(months=i)
            cuotas_bulk.append(Cuota(
                poliza=poliza,
                cuota_nro=i,
                fecha_vencimiento=venc,
                monto=0,
                pagado=False,
            ))
    Cuota.objects.bulk_create(cuotas_bulk)

    # ========================================================
    # 🎟️ GENERACIÓN DE CUPONES DE ROBO AUTOMÁTICA
    # ========================================================
    existing_cupones = list(CuponRobo.objects.filter(poliza=poliza).values_list("id", flat=True))
    if existing_cupones:
        CuponRobo.objects.filter(id__in=existing_cupones).delete()

    if genera_cupones_robo:
        cupones_bulk = []
        for i in range(1, cantidad_cuotas + 1):
            venc_cupon = fecha_emision + relativedelta(months=i - 1)
            desde = venc_cupon
            hasta = venc_cupon + relativedelta(months=1)

            cupones_bulk.append(CuponRobo(
                poliza=poliza,
                periodo_desde=desde,
                periodo_hasta=hasta,
                fecha_vencimiento=venc_cupon,
                estado=CuponRobo.Estado.PENDIENTE,
                monto=0,
            ))
        CuponRobo.objects.bulk_create(cupones_bulk)

    return poliza