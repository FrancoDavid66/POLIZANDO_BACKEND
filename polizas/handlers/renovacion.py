# polizas/handlers/renovacion.py
from datetime import datetime, date
from calendar import monthrange
from typing import Optional

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.response import Response
from rest_framework import status

from pagos.models import Cuota
from polizas.models import Poliza, FotoVehiculo, PolizaDocumento, CuponRobo
from polizas.serializers import PolizaSerializer

# ✅ Importamos hist_log para dejar registro de la auditoría
from polizas.utils.viewtools import hist_log as _hist_log

# 🆕 Sistema de errores estructurados
from polizas.utils.errors import RenovacionError, ErrorCodes

# 🆕 precio y tipo ahora son 100% manuales al renovar (ver _duplicar_con_cuotas).

# Default fallback final si no hay nada configurado
DEFAULT_CUOTAS_FALLBACK = 6

# ✅ IMPORT grúas (si la app existe)
try:
    from gruas.models import AdhesionGrua, EstadoAdhesion  # type: ignore
except Exception:
    AdhesionGrua = None  # type: ignore
    EstadoAdhesion = None  # type: ignore


# --- Relativedelta (con fallback si falta python-dateutil) ---
try:
    from dateutil.relativedelta import relativedelta  # type: ignore

    def _add_months(d: date, months: int) -> date:
        return d + relativedelta(months=months)

except Exception:
    def _add_months(d: date, months: int) -> date:
        """
        Fallback sin dateutil: suma meses preservando el día en lo posible.
        Si el mes destino no tiene ese día, usa el último día del mes.
        """
        if months == 0:
            return d
        m = (d.month - 1) + months
        y = d.year + (m // 12)
        mm = (m % 12) + 1
        last_day = monthrange(y, mm)[1]
        dd = min(d.day, last_day)
        return date(y, mm, dd)


# ---------- Helpers ----------

def _parse_date(value, fallback: date) -> date:
    """Devuelve date a partir de 'YYYY-MM-DD' / datetime / date; usa fallback si no viene."""
    if not value:
        return fallback
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except Exception:
        return fallback


def _fecha_con_dia(base: date, dia: int) -> date:
    """
    Devuelve una fecha con el mismo AÑO y MES que `base`, pero forzando el DÍA `dia`.
    Si el mes no tiene ese día (ej. 31 en febrero), usa el último día disponible.
    Sirve para mantener el día de vencimiento histórico (ej. siempre el 10).
    """
    try:
        ultimo = monthrange(base.year, base.month)[1]
        d = min(max(1, int(dia)), ultimo)
        return date(base.year, base.month, d)
    except Exception:
        return base


def _unique_numero(base: Optional[str]) -> str:
    """Garantiza numero_poliza único agregando sufijos -R1, -R2, … si ya existe."""
    if not base:
        base = "SN"
    base = str(base).strip() or "SN"

    candidate = base
    n = 1
    while Poliza.objects.filter(numero_poliza=candidate).exists():
        candidate = f"{base}-R{n}"
        n += 1
    return candidate


def _resolver_cuotas_para_renovar(compania_nueva, cobertura, original, override=None):
    """
    Resuelve cantidad de cuotas + flag de cuponera para la NUEVA póliza.

    Prioridad:
      1) Admin (TipoCobertura por compañía + cobertura) — fuente más nueva
      2) Póliza ORIGINAL (su cantidad_cuotas) — fuente de verdad de cómo se vendió
      3) Override del usuario (si vino en el payload)
      4) Si nada anduvo → raise RenovacionError(COBERTURA_NO_CONFIGURADA)

    Retorna: (cantidad_cuotas, genera_cupones_robo, fuente)
    """
    from polizas.utils.constants import normalizar_compania, normalizar_cobertura

    # 1) Buscar en el Admin (cotizaciones.TipoCobertura)
    try:
        from cotizaciones.models import TipoCobertura

        cob_nombre = normalizar_cobertura(cobertura or "")
        comp_nombre = normalizar_compania(compania_nueva or "")

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

    # 2) Heredar de la póliza ORIGINAL (las pólizas viejas ya tienen cantidad cargada)
    orig_cuotas = getattr(original, "cantidad_cuotas", None)
    if orig_cuotas and int(orig_cuotas) > 0:
        # Heredar también el flag de cuponera: si la original tiene cupones generados,
        # la nueva también los lleva.
        from polizas.models import CuponRobo
        tenia_cupones = CuponRobo.objects.filter(poliza=original).exists()
        return (int(orig_cuotas), tenia_cupones, "POLIZA_ORIGINAL")

    # 3) Override manual del usuario (frontend manda 'cantidad_cuotas_override')
    if override is not None:
        try:
            n = int(override)
            if n > 0:
                return (n, False, "OVERRIDE")
        except (TypeError, ValueError):
            pass

    # 4) Sin información suficiente → error claro
    raise RenovacionError(
        ErrorCodes.COBERTURA_NO_CONFIGURADA,
        context={
            "compania": str(compania_nueva or ""),
            "cobertura": str(cobertura or ""),
            "poliza_id": getattr(original, "id", None),
        }
    )


def _ultimo_vencimiento(original: Poliza) -> date:
    """Ancla para conservar el día: último vencimiento de la póliza vieja."""
    last = (
        Cuota.objects.filter(poliza=original)
        .exclude(fecha_vencimiento__isnull=True)
        .order_by("-fecha_vencimiento", "-cuota_nro", "-id")
        .first()
    )
    if last and last.fecha_vencimiento:
        return last.fecha_vencimiento
    return original.fecha_vencimiento or original.primer_pago or timezone.localdate()


def _safe_str(v, default: str = "") -> str:
    if v is None:
        return default
    s = str(v).strip()
    return s if s else default


def _safe_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _dec_or_none(v):
    """Convierte a Decimal si viene un precio manual válido; None si no vino nada
    o es inválido (así el precio queda en 0 y se carga después desde Pagos)."""
    if v is None or v == "":
        return None
    try:
        from decimal import Decimal, InvalidOperation
        d = Decimal(str(v))
        return d if d >= 0 else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _to_bool(v) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return s in {"1", "true", "t", "yes", "y", "on", "si", "sí"}


def _should_transfer_grua(request) -> bool:
    """
    Lee flags del front/back.
    - RenovacionModal manda: transferir_grua: 1/0
    Default: True (si no viene, mantenemos la grúa)
    """
    data = getattr(request, "data", {}) or {}
    v = None
    if "transferir_grua" in data:
        v = data.get("transferir_grua")
    elif "transferirGrua" in data:
        v = data.get("transferirGrua")
    elif "grua" in data:
        v = data.get("grua")

    if v is None:
        return True
    return _to_bool(v)


def _transferir_adhesion_grua(request, original: Poliza, nueva: Poliza) -> None:
    """
    Si la póliza original tenía una adhesión ACTIVA/PAUSADA, la copiamos a la póliza nueva.

    - No rompe si la app gruas no está instalada.
    - Respeta `transferir_grua` (default sí).
    - Copia plan/estado/fechas/mora/contrato/notas.
    - IMPORTANTE: Plan es obligatorio en AdhesionGrua, por eso copiamos el mismo plan.
    """
    if AdhesionGrua is None:
        return
    if not _should_transfer_grua(request):
        return

    # si la póliza nueva ya tiene una adhesión ACTIVA/PAUSADA, no hacemos nada (regla de unicidad)
    try:
        if EstadoAdhesion is not None:
            if AdhesionGrua.objects.filter(
                poliza=nueva,
                estado__in=[EstadoAdhesion.ACTIVA, EstadoAdhesion.PAUSADA],
            ).exists():
                return
        else:
            if AdhesionGrua.objects.filter(poliza=nueva).exists():
                return
    except Exception:
        return

    # buscar adhesión más reciente en la póliza vieja
    try:
        adh = (
            AdhesionGrua.objects.filter(poliza=original)
            .order_by("-fecha_activacion", "-id")
            .first()
        )
    except Exception:
        return

    if not adh:
        return

    # solo transferimos si era ACTIVA o PAUSADA
    estado = getattr(adh, "estado", None)
    if estado not in ("ACTIVA", "PAUSADA"):
        return

    plan = getattr(adh, "plan", None)
    if not plan:
        # plan es obligatorio en tu modelo, sin plan no podemos copiar
        return

    # ✅ creamos una nueva adhesión para la póliza renovada
    try:
        AdhesionGrua.objects.create(
            poliza=nueva,
            plan=plan,
            estado=estado,
            fecha_activacion=getattr(adh, "fecha_activacion", None) or timezone.localdate(),
            # copia carencia ya calculada (si existe)
            fecha_carencia_fin=getattr(adh, "fecha_carencia_fin", None),
            # mora
            suspendida_por_mora_desde=getattr(adh, "suspendida_por_mora_desde", None),
            rehabilitar_desde=getattr(adh, "rehabilitar_desde", None),
            # baja / notas
            fecha_baja=getattr(adh, "fecha_baja", None),
            notas=getattr(adh, "notas", "") or "",
            # contrato
            contrato_firmado=bool(getattr(adh, "contrato_firmado", False)),
            contrato_firmado_en=getattr(adh, "contrato_firmado_en", None),
            contrato_archivo_url=getattr(adh, "contrato_archivo_url", "") or "",
        )
    except Exception:
        # no frenamos la renovación si falla la transferencia
        return


# ---------- Core ----------

@transaction.atomic
def _duplicar_con_cuotas(request, original: Poliza) -> Response:
    """
    Crea una NUEVA póliza que:
      - Permite cambiar número y compañía.
      - Mantiene el mismo DÍA de vencimiento (anclado en el último vencimiento de la póliza vieja).
      - Genera N cuotas nuevas según la compañía nueva (o la cantidad de la original; fallback 6).
      - Devuelve 201 con la póliza nueva serializada (incluye id).
      - Marca la original como 'finalizada'.
    """
    # 1) Entrada (permite override)
    numero_in = (
        request.data.get("nuevoNumero")
        or request.data.get("nuevo_numero")
        or original.numero_poliza
    )
    compania_nueva = (
        request.data.get("nuevaCompania")
        or request.data.get("nueva_compania")
        or request.data.get("compania")
        or original.compania
    )
    numero_unico = _unique_numero(numero_in)

    # 🆕 Precio: 100% manual (como en alta nueva). Si el operador cargó un precio
    # en el modal de renovación, se usa. Si no, las cuotas quedan en 0 y se cobran
    # después desde Pagos (igual que siempre para las demás compañías).
    nuevo_precio = _dec_or_none(request.data.get("precio_cuota"))
    if nuevo_precio is None:
        nuevo_precio = 0

    # 2) Ancla de fechas y cantidad de cuotas
    # 🚀 LÓGICA DE NEGOCIO (renovación = como póliza nueva):
    # - La nueva póliza ARRANCA el mismo día que vence la última cuota de la vieja
    #   (empalme sin huecos de cobertura).
    # - La PRIMERA cuota vence UN MES DESPUÉS del alta (igual que una póliza nueva),
    #   NO el mismo día. Así la cuota 1 cubre el primer mes completo.
    # - Las cuotas siguientes son mensuales: cuota i vence en (alta + i meses).
    # - La cobertura de la nueva termina en la última cuota = alta + N meses.
    ancla = _ultimo_vencimiento(original)

    # Inicio de vigencia (alta de la nueva póliza):
    # - Si el operador eligió una fecha en el modal de renovación, la respetamos.
    # - Si no la eligió, usamos el día que vence la última cuota de la vieja
    #   (empalme automático, sin huecos de cobertura).
    fecha_alta_payload = (
        request.data.get("nuevaFecha")
        or request.data.get("nueva_fecha")
        or request.data.get("inicio_vigencia")
        or request.data.get("fecha_emision")
    )
    inicio_vigencia = _parse_date(fecha_alta_payload, ancla)

    # ¿Mantener el DÍA de vencimiento histórico? (lo manda la renovación rápida de Pagos)
    # Si viene, las cuotas vencen SIEMPRE el mismo día del mes (el de la póliza vieja),
    # sin importar qué día se renueve: el alta puede ser hoy, pero el vto queda fijo.
    _mantener_dia = str(request.data.get("mantener_dia_vencimiento") or "").strip().lower() in ("1", "true", "t", "yes", "si", "sí")
    _dia_fijo = ancla.day if _mantener_dia else None

    # Primera cuota = UN MES después del inicio (como una póliza nueva).
    # Con día fijo: cae en el día histórico del mes siguiente (ej. siempre el 10).
    if _dia_fijo:
        primer_pago = _fecha_con_dia(_add_months(inicio_vigencia, 1), _dia_fijo)
    else:
        primer_pago = _add_months(inicio_vigencia, 1)

    # 4) Campos obligatorios según tu modelo Poliza (NO NULL)
    cobertura = _safe_str(getattr(original, "cobertura", ""), default="")

    # 🆕 RESOLVER CUOTAS Y CUPONERAS (puede lanzar RenovacionError)
    # Prioridad: Admin → Original → Override → Error
    override_cuotas = request.data.get("cantidad_cuotas_override") or request.data.get("cantidad_cuotas")
    cantidad_cuotas, genera_cupones_robo, _fuente = _resolver_cuotas_para_renovar(
        compania_nueva=compania_nueva,
        cobertura=cobertura,
        original=original,
        override=override_cuotas,
    )

    # Fecha de vencimiento de la nueva póliza = fin de cobertura = última cuota.
    # Con día fijo, la última cuota mantiene el día histórico; sin día fijo, queda
    # igual que antes (alta + N meses), sin tocar el flujo del módulo de Renovaciones.
    if _dia_fijo:
        fecha_vto_poliza = _add_months(primer_pago, cantidad_cuotas - 1)
    else:
        fecha_vto_poliza = _add_months(inicio_vigencia, cantidad_cuotas)

    # 🚀 FIX: Obtenemos la oficina como objeto ForeignKey directo (o None) sin convertirlo a texto
    oficina_original = getattr(original, "oficina", None)
    
    patente = _safe_str(getattr(original, "patente", ""), default="")
    marca = _safe_str(getattr(original, "marca", ""), default="")
    modelo = _safe_str(getattr(original, "modelo", ""), default="")
    anio = _safe_int(getattr(original, "anio", None), default=0) or timezone.localdate().year

    # 🆕 Tipo: por defecto se hereda de la póliza vieja, pero el operador puede
    # corregirlo en el modal de renovación (ej: nació como "Moto" por error del
    # lector de PDF y en realidad es "Auto"). Si manda `tipo`, ese manda.
    tipo_in = request.data.get("tipo")
    tipo = _safe_str(tipo_in, default="") or _safe_str(getattr(original, "tipo", "Auto"), default="Auto")

    dias_a_vencer = _safe_int(getattr(original, "dias_a_vencer", None), default=30) or 30

    # 5) Crear NUEVA póliza
    nueva = Poliza.objects.create(
        cliente=original.cliente,
        compania=_safe_str(compania_nueva, default=_safe_str(original.compania, default="")),
        numero_poliza=numero_unico,
        cobertura=cobertura,
        oficina=oficina_original,  # 🚀 Asignamos el objeto original, no un string
        patente=patente,
        marca=marca,
        modelo=modelo,
        anio=anio,
        tipo=tipo,
        precio_cuota=nuevo_precio,
        cantidad_cuotas=cantidad_cuotas,
        primer_pago=primer_pago,
        fecha_emision=inicio_vigencia,
        fecha_vencimiento=fecha_vto_poliza,
        dias_a_vencer=dias_a_vencer,
        estado="activa",
        alertas=getattr(original, "alertas", "") or "",
        foto_perfil_url=getattr(original, "foto_perfil_url", "") or "",
        foto_perfil_public_id=getattr(original, "foto_perfil_public_id", "") or "",
    )

    # 🚀 REGISTRO HISTÓRICO: Creación de nueva póliza por renovación
    try:
        _hist_log(
            poliza=nueva,
            tipo="POLIZA_RENOVADA_NUEVA",
            mensaje=f"Póliza creada por renovación de la póliza #{original.id}",
            severidad="SUCCESS",
            request=request,
            subject=nueva,
            categoria="POLIZA",
        )
    except Exception as e:
        print(f"Error al registrar historial de nueva póliza: {e}")

    # ✅ 5b) Transferir adhesión de grúa (si corresponde)
    _transferir_adhesion_grua(request, original, nueva)

    # 6) Generar cuotas NUEVAS:
    # cuota 1 vence en primer_pago; cuota i vence en primer_pago + (i-1) meses.
    # 🆕 Todas las cuotas (cualquier compañía, incluida NRE) van al mismo precio
    #    manual (`nuevo_precio`, 0 si no se cargó nada en el modal).
    for i in range(1, cantidad_cuotas + 1):
        venc = _add_months(primer_pago, i - 1)
        monto_i = nuevo_precio
        Cuota.objects.create(
            poliza=nueva,
            cuota_nro=i,
            fecha_vencimiento=venc,
            monto=monto_i,
            pagado=False,
        )

    # 6a) Generar cupones de robo si esta cobertura los lleva.
    #     Fechas provisorias (alineadas a las cuotas): se ajustan a las REALES
    #     cuando se sube la cuponera desde Tareas → "Subir póliza a sistema".
    if genera_cupones_robo:
        for i in range(1, cantidad_cuotas + 1):
            venc_cupon = _add_months(primer_pago, i - 1)
            CuponRobo.objects.create(
                poliza=nueva,
                periodo_desde=venc_cupon,
                periodo_hasta=_add_months(venc_cupon, 1),
                fecha_vencimiento=venc_cupon,
                estado=CuponRobo.Estado.PENDIENTE,
                monto=0,
            )

    # 6b) MOVER fotos y documentos de la vieja a la nueva (reasigna el FK; no duplica
    #     en Cloudinary). La póliza vieja queda sin estas fotos/documentos: ahora viven en la nueva.
    try:
        fotos_movidas = FotoVehiculo.objects.filter(poliza=original).update(poliza=nueva)

        # Documentos que se RENUEVAN con cada póliza (Mercosur, cuponera, frente de
        # póliza / propuesta, certificado): NO se arrastran — se suben nuevos a la
        # póliza nueva, porque los de la póliza vieja quedan finalizados.
        # El resto (DNI, cédula, título, VTV, etc.) sí se mueve porque no cambia.
        _KW_RENUEVAN = ["merco", "cupon", "poliza", "prp", "frente", "propuesta", "certificado"]
        _q_renuevan = Q()
        for _kw in _KW_RENUEVAN:
            _q_renuevan |= Q(tipo__icontains=_kw) | Q(nombre__icontains=_kw)
        docs_movidos = (
            PolizaDocumento.objects.filter(poliza=original)
            .exclude(_q_renuevan)
            .update(poliza=nueva)
        )
        if fotos_movidas or docs_movidos:
            try:
                _hist_log(
                    poliza=nueva,
                    tipo="RENOVACION_MOVER_ARCHIVOS",
                    mensaje=f"Se movieron {fotos_movidas} foto(s) y {docs_movidos} documento(s) desde la póliza #{original.id}",
                    severidad="INFO",
                    request=request,
                    subject=nueva,
                    categoria="POLIZA",
                )
            except Exception:
                pass
    except Exception as e:
        print(f"Error al mover fotos/documentos en renovación: {e}")

    # 7) Cerrar original
    if original.estado != "finalizada":
        original.estado = "finalizada"
        original.save(update_fields=["estado"])
        
        # 🚀 REGISTRO HISTÓRICO: Cierre de póliza vieja
        try:
            _hist_log(
                poliza=original,
                tipo="POLIZA_FINALIZADA_RENOVACION",
                mensaje=f"Póliza finalizada por renovación. Reemplazada por la póliza #{nueva.id}",
                severidad="INFO",
                request=request,
                subject=original,
                categoria="POLIZA",
            )
        except Exception as e:
            print(f"Error al registrar historial de póliza vieja: {e}")

    return Response(
        PolizaSerializer(nueva, context={"request": request}).data,
        status=status.HTTP_201_CREATED,
    )


# ---------- Endpoints usados por el ViewSet ----------

@transaction.atomic
def handle_renovar_poliza(request, poliza: Poliza):
    return _duplicar_con_cuotas(request, poliza)


@transaction.atomic
def handle_duplicar_renovacion(request, poliza: Poliza):
    return _duplicar_con_cuotas(request, poliza)