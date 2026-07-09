# notificaciones/services_cuotas.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Tuple
from collections import defaultdict
import re

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from pagos.models import Cuota, MedioCobro
from notificaciones.models import (
    NotificacionCuotaLog,
    EnvioRecordatoriosCuotas,
    EnvioRecordatorioDetalle,
)
from notificaciones.utils.mensajeria import enviar_whatsapp


# Deltas en días respecto a la FECHA DE PAGO (= fin de cobertura de la cuota
# anterior; ver _fecha_pago_objetivo).
#   POSITIVO = faltan días para pagar · 0 = vence hoy · NEGATIVO = ya venció.
# Mismos momentos que el reporte de contactos:
#   +7 (falta 1 semana) · +3 · +1 (mañana) · 0 (hoy) ·
#   -2 (aviso de baja: mañana se da de baja) · -3 · -7 · -30 (último aviso).
TRIGGER_DELTAS = {7, 3, 1, 0, -2, -3, -7, -30}

# ✅ Permite siempre re-enviar (la auditoría registra cada intento)
DISABLE_LOCKS = True

# 🆕 Venta cruzada: a los N días del pago se ofrece el resto de servicios.
OFERTA_DIAS_DESPUES_PAGO = 14

OFICINA_PATTERNS = {
    "1": ["1", "ofi 1", "ofi1", "(1)", "5 esquinas", "5esquinas", "cinco esquinas"],
    "2": ["2", "ofi 2", "ofi2", "(2)", "axion"],
    "3": ["3", "ofi 3", "ofi3", "(3)", "39", "km 39", "kilometro 39", "kilómetro 39"],
}


@dataclass
class ResultadoEnvioCuotas:
    hoy: date
    enviados: int
    procesadas: int
    errores: List[Dict[str, Any]]
    trigger_deltas: List[int]
    candidatas_por_delta: Dict[int, int]
    seleccionadas_por_delta: Dict[int, int]
    detalles_enviados: List[Dict[str, Any]]
    no_enviados: List[Dict[str, Any]] = None


def _safe_str(v) -> str:
    return ("" if v is None else str(v)).strip()


def _normalize_oficina_bucket(raw: str | None) -> str | None:
    s0 = _safe_str(raw)
    if not s0: return None
    low = s0.lower()
    if low in ("1", "2", "3"): return low
    for bucket, pats in OFICINA_PATTERNS.items():
        for p in pats:
            if p in low: return bucket
    m = re.search(r"\bofi\s*[-_ ]*\s*([123])\b", low)
    if m: return m.group(1)
    return s0


def _apply_oficina_filter(qs, oficina_raw: str):
    bucket = _normalize_oficina_bucket(oficina_raw)
    if not bucket: return qs
    tokens = OFICINA_PATTERNS.get(bucket, [bucket])
    tokens = [t for t in tokens if t]
    is_fk = False
    try:
        f = qs.model._meta.get_field("poliza").related_model._meta.get_field("oficina")
        is_fk = bool(getattr(f, "is_relation", False))
    except Exception: pass
    q = Q()
    try:
        bucket_int = int(bucket)
        if is_fk: q |= Q(poliza__oficina_id=bucket_int)
        else: q |= Q(poliza__oficina=bucket)
    except ValueError:
        if not is_fk: q |= Q(poliza__oficina=bucket)
    for t in tokens:
        if len(t) >= 1:
            if is_fk: q |= Q(poliza__oficina__nombre__icontains=t)
            else: q |= Q(poliza__oficina__icontains=t)
    return qs.filter(q)


def obtener_cuotas_candidatas(hoy: date, oficina: str | None = None) -> Iterable[Cuota]:
    qs = (
        Cuota.objects.select_related("poliza", "poliza__cliente")
        .filter(pagado=False, fecha_vencimiento__isnull=False)
        .exclude(poliza__estado__in=["cancelada", "anulada", "baja", "eliminada"])
        .order_by("fecha_vencimiento")
    )
    if oficina: qs = _apply_oficina_filter(qs, oficina)
    return qs


def _fecha_pago_objetivo(cuota: Cuota) -> date | None:
    """
    Fecha en la que el cliente tiene que VENIR A PAGAR esta cuota.

    Regla de negocio (confirmada): cada cuota se cobra cuando se termina la
    cobertura de la cuota ANTERIOR. O sea, la fecha objetivo del recordatorio
    es el `fecha_vencimiento` de la cuota anterior (cuota_nro - 1), que en una
    póliza al día es la última cuota PAGADA.

    Caso especial — cuota #1 (no hay anterior en la póliza):
      - En una RENOVACIÓN, la cuota #1 vence justo el día en que termina la
        cobertura de la póliza vieja, así que su propio `fecha_vencimiento`
        ya es la fecha correcta de pago.
      - En una póliza nueva, la #1 se paga al darla de alta; usar su propio
        vencimiento es el comportamiento razonable.
    """
    nro = getattr(cuota, "cuota_nro", None)
    if nro and nro > 1:
        vto_anterior = (
            Cuota.objects
            .filter(poliza_id=cuota.poliza_id, cuota_nro=nro - 1)
            .values_list("fecha_vencimiento", flat=True)
            .first()
        )
        if vto_anterior:
            return vto_anterior
    return getattr(cuota, "fecha_vencimiento", None)


def _get_numero_whatsapp(cuota: Cuota) -> str | None:
    poliza = getattr(cuota, "poliza", None)
    cliente = getattr(poliza, "cliente", None) if poliza else None
    if not cliente: return None
    for field in ("whatsapp", "telefono", "telefono_alt", "celular"):
        numero = getattr(cliente, field, None)
        if numero: return str(numero).strip() or None
    return None


def _fmt_fecha(d: date) -> str:
    return d.strftime("%d/%m")


def _label_delta(d) -> str:
    return {
        7: "Falta 1 semana", 3: "Faltan unos días", 1: "Vence mañana",
        0: "Vence hoy", -2: "Aviso de baja", -3: "Pago pendiente",
        -7: "Pendiente 1 semana", -30: "Último aviso",
    }.get(d, f"Δ{d}")


def _motivo_error(info) -> str:
    """Traduce el error técnico de envío a un texto entendible."""
    if isinstance(info, dict):
        err = (info.get("error") or "").strip()
        mapa = {
            "invalid_phone": "Número de teléfono inválido",
            "invalid_number": "Número de teléfono inválido",
            "config_missing": "Oficina sin credenciales de WhatsApp",
            "http_error": "UltraMsg rechazó el envío",
            "request_exception": "Sin conexión con UltraMsg",
            "no_provider_or_failed": "No se pudo enviar (sin proveedor)",
        }
        return mapa.get(err, err or "Error desconocido")
    return str(info)[:80]


def _nombre_cliente(cliente) -> str:
    nom = getattr(cliente, "nombre", "") or ""
    return str(nom).strip().split()[0].title() or "cliente"


def _descripcion_cuota(cuota: Cuota) -> Tuple[str, str]:
    poliza = getattr(cuota, "poliza", None)
    if poliza:
        marca = (getattr(poliza, "auto_marca", None) or getattr(poliza, "marca", None) or "").strip()
        modelo = (getattr(poliza, "auto_modelo", None) or getattr(poliza, "modelo", None) or "").strip()
        vehiculo = f"{marca} {modelo}".strip() or "Vehículo"
        patente = getattr(poliza, "patente", "S/P").upper()
    else:
        vehiculo, patente = "Vehículo", "S/P"
    return patente, vehiculo


def _resolver_alias_transferencia(
    alias_transferencia: str | None, medio_cobro_id: int | None
) -> Tuple[str, str | None]:
    alias, titular = None, None
    if alias_transferencia: alias = str(alias_transferencia).strip() or None
    medio = None
    if medio_cobro_id:
        try: medio = MedioCobro.objects.filter(pk=medio_cobro_id, activo=True).first()
        except: pass
    if medio:
        if not alias:
            candidate = getattr(medio, "etiqueta", None) or getattr(medio, "valor", None)
            if candidate: alias = str(candidate).strip()
        titular_nombre = getattr(medio, "titular_nombre", None)
        if titular_nombre: titular = str(titular_nombre).strip().title()
    return (alias or ""), titular


# Mensajes cálidos y amables según urgencia
def _build_mensaje_cliente(cliente, items, delta_principal=None, alias_transferencia=None, titular_billetera=None) -> str:
    nombre = _nombre_cliente(cliente)
    alias_txt = str(alias_transferencia or "").strip().upper()

    # Cada item es (cuota, delta, fecha_objetivo). Si no nos pasan delta_principal
    # lo calculamos acá. (Soporta también tuplas viejas de 2 elementos.)
    if delta_principal is None:
        _deltas = [it[1] for it in items if len(it) > 1]
        delta_principal = min(_deltas) if _deltas else None

    # Intro según urgencia — siempre amable, nunca amenazante
    if delta_principal == 7:
        intro = f"¡Hola {nombre}! 😊 Te recordamos que la semana que viene vence el pago de tu seguro. Te avisamos con tiempo así lo tenés listo."
    elif delta_principal == 3:
        intro = f"¡Hola {nombre}! 😊 Te escribimos para avisarte que en unos días vence el pago de tu seguro. ¡Así podés tenerlo listo con tiempo!"
    elif delta_principal == 1:
        intro = f"¡Hola {nombre}! 😊 Te recordamos que mañana vence el pago de tu seguro. ¡Estás a tiempo de dejarlo al día!"
    elif delta_principal == 0:
        intro = f"¡Hola {nombre}! 👋 Te mandamos un recordatorio porque hoy vence el pago de tu póliza. ¡Ya estás a tiempo!"
    elif delta_principal == -2:
        intro = f"¡Hola {nombre}! 😊 Te avisamos que el pago de tu póliza está pendiente y, de no regularizarse, *mañana se daría de baja* por falta de pago. Todavía estás a tiempo: pagá hoy y escribinos para mantener la cobertura activa."
    elif delta_principal == -3:
        intro = f"¡Hola {nombre}! 😊 Te escribimos porque tenemos pendiente el pago de tu póliza. Cuando puedas, te pasamos los datos para regularizarlo sin problema."
    elif delta_principal == -7:
        intro = f"¡Hola {nombre}! 😊 Vemos que quedó pendiente el pago de tu seguro de la semana pasada. Para mantener la cobertura activa, te pasamos los datos y lo regularizamos enseguida."
    elif delta_principal == -30:
        intro = f"¡Hola {nombre}! 😊 Tu póliza tiene un pago pendiente desde hace un tiempo y, para no perder la cobertura, necesitamos regularizarlo. Escribinos y lo resolvemos juntos."
    else:
        intro = f"¡Hola {nombre}! 😊 Te enviamos tu recordatorio de pago del seguro. Cualquier cosa que necesites, acá estamos."

    # Listado de cuotas
    msg = f"{intro}\n\n"
    for it in items:
        cuota = it[0]
        # La fecha que mostramos es CUÁNDO tiene que pagar (fin de cobertura de
        # la cuota anterior), no el vencimiento propio de la cuota.
        fecha_objetivo = it[2] if len(it) > 2 else getattr(cuota, "fecha_vencimiento", None)
        patente, vehiculo = _descripcion_cuota(cuota)
        vto = _fmt_fecha(fecha_objetivo) if fecha_objetivo else "—"
        msg += f"• *{vehiculo}* ({patente}) — Vencimiento: *{vto}*\n"

    # Datos de pago y cierre cálido
    msg += f"\n💳 *Alias:* {alias_txt if alias_txt else 'Consultanos y te lo pasamos'}\n"
    if titular_billetera:
        msg += f"👤 *Titular:* {titular_billetera}\n"

    msg += "\n¡Gracias por confiar en nosotros! Ante cualquier duda, escribinos. 🙌"

    return msg


def enviar_recordatorios_cuotas(
    *,
    hoy: date | None = None,
    alias_transferencia: str | None = None,
    medio_cobro_id: int | None = None,
    oficina: str | None = None,
) -> ResultadoEnvioCuotas:
    if hoy is None: hoy = timezone.localdate()
    oficina_norm = _normalize_oficina_bucket(oficina) if oficina not in (None, "", []) else None
    
    envio_obj = None
    if oficina_norm:
        try:
            with transaction.atomic():
                envio_obj = EnvioRecordatoriosCuotas.objects.create(fecha=hoy, oficina=oficina_norm)
        except: pass

    alias_resuelto, titular_billetera = _resolver_alias_transferencia(alias_transferencia, medio_cobro_id)
    cuotas = list(obtener_cuotas_candidatas(hoy, oficina=oficina_norm))
    por_cliente = {}
    no_enviados: List[Dict[str, Any]] = []
    _sin_tel = set()

    for cuota in cuotas:
        # 🎯 La fecha que dispara el recordatorio es CUÁNDO hay que pagar esta
        # cuota = fin de cobertura de la cuota anterior (no su propio vto).
        fecha_objetivo = _fecha_pago_objetivo(cuota)
        if not fecha_objetivo: continue
        delta = (fecha_objetivo - hoy).days
        if delta not in TRIGGER_DELTAS: continue

        cliente = getattr(cuota.poliza, "cliente", None)
        if not cliente: continue

        numero = _get_numero_whatsapp(cuota)
        if not numero:
            if cliente.id not in _sin_tel:
                _sin_tel.add(cliente.id)
                no_enviados.append({
                    "cliente": _nombre_cliente(cliente),
                    "telefono": "—",
                    "motivo": "Sin WhatsApp cargado",
                    "situacion": _label_delta(delta),
                })
            continue

        key = (cliente.id, numero)
        if key not in por_cliente:
            por_cliente[key] = {"cliente": cliente, "numero": numero, "items": []}
        por_cliente[key]["items"].append((cuota, delta, fecha_objetivo))

    enviados = 0
    errores, detalles_enviados = [], []

    for (cliente_id, numero), data in por_cliente.items():
        cliente, items = data["cliente"], data["items"]
        delta_principal = min(d for _c, d, _f in items)
        
        poliza_p = items[0][0].poliza
        oficina_det = oficina_norm or _safe_str(getattr(poliza_p, "oficina", ""))
        oficina_envio = _normalize_oficina_bucket(oficina_det)

        try:
            mensaje = _build_mensaje_cliente(cliente, items, delta_principal, alias_resuelto, titular_billetera)
            ok, info = enviar_whatsapp(numero, mensaje, oficina=oficina_envio)
            
            if not ok:
                errores.append({"cliente": cliente_id, "error": str(info)})
                no_enviados.append({
                    "cliente": _nombre_cliente(cliente),
                    "telefono": numero,
                    "motivo": _motivo_error(info),
                    "situacion": _label_delta(delta_principal),
                })
                continue

            NotificacionCuotaLog.objects.get_or_create(cliente=cliente, numero=numero, fecha=hoy)
            if envio_obj:
                EnvioRecordatorioDetalle.objects.create(
                    envio=envio_obj, cliente=cliente, poliza_principal=poliza_p,
                    oficina=oficina_envio, telefono=numero, estado_envio="OK"
                )
            enviados += 1
            detalles_enviados.append({
                "telefono": numero,
                "cliente": _nombre_cliente(cliente),
                "situacion": _label_delta(delta_principal),
                "tipo": "Recordatorio",
            })
        except Exception as exc:
            errores.append({"cliente": cliente_id, "error": str(exc)})
            no_enviados.append({
                "cliente": _nombre_cliente(cliente),
                "telefono": numero,
                "motivo": str(exc)[:80],
                "situacion": _label_delta(delta_principal),
            })

    return ResultadoEnvioCuotas(hoy=hoy, enviados=enviados, procesadas=len(cuotas), errores=errores, trigger_deltas=list(TRIGGER_DELTAS), candidatas_por_delta={}, seleccionadas_por_delta={}, detalles_enviados=detalles_enviados, no_enviados=no_enviados)


def _build_mensaje_oferta(cliente) -> str:
    """Mensaje de venta cruzada (se manda a los 14 días del pago)."""
    nombre = _nombre_cliente(cliente)
    return (
        f"¡Hola {nombre}! 😊 Gracias por estar al día con el seguro de tu auto.\n"
        "¿Sabías que en *Estudio Thames* te damos una mano en mucho más?\n\n"
        "📱 *Seguros:* celulares, carteras, bicicletas, hogar y comercio\n"
        "⚖️ *Abogados:* accidentes, ART, temas de familia, laboral y temas de propiedad, asuntos penales.\n"
        "📜 *Escribanía:* contratos de compra-venta, cesiones, escrituras.\n"
        "🚗 *Gestoría del automotor:* trámites para circular más tranquilo.\n"
        "Transferencias, cédula verde, formularios 08. Te ayudamos a comprar tu auto.\n\n"
        "Escribinos y te asesoramos sin compromiso. 🙌"
    )


def enviar_ofertas_postpago(hoy: date, oficina_norm: str | None = None) -> Tuple[int, List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Manda el mensaje de venta cruzada a los clientes que PAGARON hace
    OFERTA_DIAS_DESPUES_PAGO días. Un mensaje por cliente.
    Devuelve (enviados, errores).
    """
    from datetime import timedelta
    fecha_pago_oferta = hoy - timedelta(days=OFERTA_DIAS_DESPUES_PAGO)

    qs = (
        Cuota.objects.select_related("poliza", "poliza__cliente")
        .filter(pagado=True, fecha_pago=fecha_pago_oferta)
        .exclude(poliza__estado__in=["cancelada", "anulada", "baja", "eliminada"])
        .order_by("poliza__cliente_id")
    )
    if oficina_norm:
        qs = _apply_oficina_filter(qs, oficina_norm)

    enviados = 0
    errores: List[Dict[str, Any]] = []
    detalles: List[Dict[str, Any]] = []
    no_enviados: List[Dict[str, Any]] = []
    vistos = set()

    for cuota in qs:
        cliente = getattr(cuota.poliza, "cliente", None)
        if not cliente or cliente.id in vistos:
            continue
        vistos.add(cliente.id)

        numero = _get_numero_whatsapp(cuota)
        if not numero:
            no_enviados.append({
                "cliente": _nombre_cliente(cliente),
                "telefono": "—",
                "motivo": "Sin WhatsApp cargado",
                "situacion": "Oferta (14 días)",
            })
            continue

        oficina_envio = oficina_norm or _normalize_oficina_bucket(
            _safe_str(getattr(cuota.poliza, "oficina", ""))
        )
        try:
            mensaje = _build_mensaje_oferta(cliente)
            ok, info = enviar_whatsapp(numero, mensaje, oficina=oficina_envio)
            if ok:
                enviados += 1
                detalles.append({
                    "telefono": numero,
                    "cliente": _nombre_cliente(cliente),
                    "situacion": "Oferta (14 días)",
                    "tipo": "Venta",
                })
            else:
                errores.append({"cliente": cliente.id, "error": str(info)})
                no_enviados.append({
                    "cliente": _nombre_cliente(cliente),
                    "telefono": numero,
                    "motivo": _motivo_error(info),
                    "situacion": "Oferta (14 días)",
                })
        except Exception as exc:
            errores.append({"cliente": cliente.id, "error": str(exc)})
            no_enviados.append({
                "cliente": _nombre_cliente(cliente),
                "telefono": numero,
                "motivo": str(exc)[:80],
                "situacion": "Oferta (14 días)",
            })

    return enviados, errores, detalles, no_enviados


def enviar_todo(
    *,
    hoy: date | None = None,
    alias_transferencia: str | None = None,
    medio_cobro_id: int | None = None,
    oficina: str | None = None,
) -> dict:
    """
    Punto de entrada único que corre los recordatorios de cuotas.

    Retorna un dict con el resultado.
    Usar este en el cron en lugar de llamar a la función directamente.
    """
    if hoy is None:
        hoy = timezone.localdate()

    # Recordatorios de cuotas
    resultado_cuotas = enviar_recordatorios_cuotas(
        hoy=hoy,
        alias_transferencia=alias_transferencia,
        medio_cobro_id=medio_cobro_id,
        oficina=oficina,
    )

    # 🆕 Venta cruzada a los 14 días del pago (solo flujo automático)
    oficina_norm = _normalize_oficina_bucket(oficina) if oficina not in (None, "", []) else None
    ofertas_enviadas, ofertas_errores, ofertas_detalles, ofertas_no_env = enviar_ofertas_postpago(hoy, oficina_norm)

    return {
        "recordatorios": {
            "enviados":   resultado_cuotas.enviados,
            "procesadas": resultado_cuotas.procesadas,
            "errores":    resultado_cuotas.errores,
        },
        "ofertas": {
            "enviados": ofertas_enviadas,
            "errores":  ofertas_errores,
        },
        "detalles": list(resultado_cuotas.detalles_enviados) + ofertas_detalles,
        "no_enviados": list(resultado_cuotas.no_enviados or []) + ofertas_no_env,
        # Compatibilidad histórica
        "postventa": {
            "enviados": 0,
            "errores":  [],
        },
    }