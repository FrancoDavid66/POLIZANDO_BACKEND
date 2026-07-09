# gruas/handlers/solicitudes.py
from decimal import Decimal
from django.utils import timezone
from django.db import transaction
from rest_framework import serializers
from django.apps import apps

from ..models import (
    SolicitudGrua, SolicitudFoto, SolicitudEvento,
    EstadoSolicitud, TipoFoto
)
from ..utils.validaciones import adhesion_operable, horario_prestacion_activo
from ..utils.tarifario import calcular_costo_proveedor


def _add_evento(solicitud, nuevo_estado, notas="", actor=""):
    SolicitudEvento.objects.create(
        solicitud=solicitud,
        estado_anterior=solicitud.estado,
        estado_nuevo=nuevo_estado,
        notas=notas or "",
        actor=actor or "",
    )


def crear_solicitud(adhesion, poliza, motivo, origen, destino="", km_estimados=0, notas=""):
    """
    Crea la solicitud de grúa.
    → Validación de operable (mora, carencia, rehabilitar_desde) DESACTIVADA para pruebas.
    """
    
    # ==================== VALIDACIÓN DESACTIVADA PARA PRUEBAS ====================
    # ok, msg = adhesion_operable(adhesion)
    # if not ok:
    #     raise serializers.ValidationError(msg)
    # =============================================================================

    fuera = not horario_prestacion_activo()
    s = SolicitudGrua.objects.create(
        adhesion=adhesion,
        poliza=poliza,
        motivo=motivo,
        origen=origen,
        destino=destino or "",
        fuera_de_horario=fuera,
        km_estimados=km_estimados or 0,
        notas=notas or "",
    )
    _add_evento(s, s.estado, "Creada")
    return s


def validar_fotos_obligatorias(solicitud):
    tipos = set(solicitud.fotos.values_list("tipo", flat=True))
    if TipoFoto.PATENTE not in tipos or TipoFoto.ENTORNO not in tipos:
        raise serializers.ValidationError("Faltan fotos obligatorias (patente y entorno).")
    solicitud.validada_en = timezone.now()
    solicitud.estado = EstadoSolicitud.ABIERTA
    solicitud.save(update_fields=["validada_en","estado"])
    _add_evento(solicitud, solicitud.estado, "Validación OK")
    return solicitud


def asignar_proveedor(solicitud, proveedor, costo_estimado=None):
    if not solicitud.validada_en:
        raise serializers.ValidationError("Debe validar fotos antes de asignar un proveedor.")
    solicitud.proveedor = proveedor
    if costo_estimado is not None:
        solicitud.costo_proveedor = costo_estimado
    solicitud.estado = EstadoSolicitud.ASIGNADA
    solicitud.save(update_fields=["proveedor","costo_proveedor","estado"])
    _add_evento(solicitud, solicitud.estado, "Proveedor asignado")
    return solicitud


def cambiar_estado(solicitud, nuevo_estado, notas=""):
    if nuevo_estado not in EstadoSolicitud.values:
        raise serializers.ValidationError("Estado inválido.")
    if nuevo_estado in [EstadoSolicitud.ASIGNADA, EstadoSolicitud.EN_TRAYECTO, EstadoSolicitud.COMPLETADA] and not solicitud.proveedor:
        raise serializers.ValidationError("No hay proveedor asignado.")
    solicitud.estado = nuevo_estado
    if notas:
        solicitud.notas = (solicitud.notas + "\n" if solicitud.notas else "") + notas
    solicitud.save(update_fields=["estado","notas"])
    _add_evento(solicitud, solicitud.estado, notas or "")
    return solicitud


@transaction.atomic
def cerrar_solicitud(solicitud, km_totales, registrar_copago_en_balances=False):
    if not solicitud.proveedor:
        raise serializers.ValidationError("No hay proveedor asignado.")
    if not solicitud.validada_en:
        raise serializers.ValidationError("La solicitud no fue validada (fotos).")

    km = Decimal(km_totales or 0)
    solicitud.km_totales = km

    incluidos = Decimal(solicitud.adhesion.plan.km_incluidos or 0)
    exced = km - incluidos
    solicitud.km_excedentes_cliente = exced if exced > 0 else Decimal("0")

    costo = calcular_costo_proveedor(solicitud.proveedor, km)
    solicitud.costo_proveedor = costo

    if registrar_copago_en_balances:
        solicitud.copago_cliente = solicitud.km_excedentes_cliente * Decimal(solicitud.adhesion.plan.costo_km_adicional or 0)

    solicitud.estado = EstadoSolicitud.COMPLETADA
    solicitud.save(update_fields=[
        "km_totales","km_excedentes_cliente","costo_proveedor","copago_cliente","estado"
    ])
    _add_evento(solicitud, solicitud.estado, "Cierre")

    # Movimientos contables en balanzes
    Egreso = apps.get_model("balanzes", "Egreso")
    Ingreso = apps.get_model("balanzes", "Ingreso")

    if costo and not solicitud.egreso:
        eg = Egreso.objects.create(
            monto=costo, categoria="Servicio de grúa", observaciones=f"Solicitud #{solicitud.id} - {km} km"
        )
        solicitud.egreso = eg
        solicitud.save(update_fields=["egreso"])

    if registrar_copago_en_balances and solicitud.copago_cliente and not solicitud.ingreso:
        ing = Ingreso.objects.create(
            monto=solicitud.copago_cliente, categoria="Copago de grúa",
            pagado_por=getattr(solicitud.poliza, "asegurado", "") or "",
        )
        solicitud.ingreso = ing
        solicitud.save(update_fields=["ingreso"])

    return solicitud