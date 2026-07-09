# clientes/views_verificar.py
# ============================================================================
# 🚀 ENDPOINT DE VERIFICACIÓN PREVIA — BÚSQUEDA GLOBAL (Grupo Unificado)
# ============================================================================
#
# Búsqueda GLOBAL (todas las oficinas) por DNI o Patente para detectar:
#   - NUEVO              → cliente y auto nuevos → seguir alta normal
#   - PATENTE_VIGENTE    → auto ya asegurado → solo pagar/renovar
#   - PATENTE_BAJA       → patente con baja previa → permite crear nueva
#   - CLIENTE_OTRO_AUTO  → cliente existe + patente nueva → vincular cliente
#
# ----------------------------------------------------------------------------
# RECORDÁ: para que este endpoint exista hay que registrar la ruta en
# clientes/urls.py (ANTES del router):
#
#     from .views_verificar import VerificarGlobalAPIView
#     path("clientes/verificar-global/", VerificarGlobalAPIView.as_view(),
#          name="verificar-global"),
#
# ============================================================================

import re

from django.db.models import Q, F, Value
from django.db.models.functions import Replace, Upper
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

# 🔧 AJUSTAR ESTOS IMPORTS según tu estructura
from clientes.models import Cliente
from polizas.models import Poliza
from pagos.models import Cuota


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _only_digits(s):
    """Devuelve solo los dígitos del string. Ej: '30.123.456' -> '30123456'."""
    return re.sub(r"\D", "", str(s or ""))


def _normalize_patente(s):
    """Mayúsculas, sin espacios ni guiones ni símbolos. Ej: 'ab 123-cd' -> 'AB123CD'."""
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def _oficina_nombre(ofi):
    """Devuelve el nombre de la oficina (acepta FK u objeto plano)."""
    if not ofi:
        return ""
    if hasattr(ofi, "nombre"):
        return str(ofi.nombre)
    return str(ofi)


def _oficina_id(ofi):
    """Devuelve el ID de la oficina si es relación, None si no."""
    if not ofi:
        return None
    return getattr(ofi, "id", None)


# ─────────────────────────────────────────────────────────────────────────────
# Anotaciones para comparar "limpio contra limpio" directamente en la BD.
# Sacan puntos, espacios y guiones de la columna guardada antes de comparar.
# ─────────────────────────────────────────────────────────────────────────────

def _dni_columna_limpia():
    """
    Limpia la columna dni_cuit_cuil en la BD quitando . espacio - /
    para poder compararla contra el DNI normalizado del usuario.
    """
    expr = F("dni_cuit_cuil")
    for ch in (".", " ", "-", "/"):
        expr = Replace(expr, Value(ch), Value(""))
    return expr


def _patente_columna_limpia():
    """
    Limpia la columna patente en la BD: saca espacios/guiones/puntos
    y la pasa a MAYÚSCULAS, para compararla contra la patente normalizada.
    """
    expr = F("patente")
    for ch in (" ", "-", "."):
        expr = Replace(expr, Value(ch), Value(""))
    return Upper(expr)


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint principal
# ─────────────────────────────────────────────────────────────────────────────

class VerificarGlobalAPIView(APIView):
    """
    GET /clientes/verificar-global/?dni=30123456&patente=AB123CD

    Devuelve el estado del cliente/auto en TODA la base (sin filtro de oficina).

    Query params (al menos uno requerido):
      - dni:     número de DNI/CUIT/CUIL
      - patente: patente del vehículo

    Response:
    {
        "caso": "NUEVO" | "PATENTE_VIGENTE" | "PATENTE_BAJA" | "CLIENTE_OTRO_AUTO",
        "cliente_match": { ... } | null,
        "patente_match": { ... } | null
    }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        dni_raw = (request.query_params.get("dni") or "").strip()
        patente_raw = (request.query_params.get("patente") or "").strip()

        if not dni_raw and not patente_raw:
            return Response(
                {"detail": "Debe enviar al menos 'dni' o 'patente'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Detectar oficina del usuario (para flag 'es_de_mi_oficina')
        user = request.user
        mi_oficina_id = None
        if hasattr(user, "perfil") and user.perfil and getattr(user.perfil, "oficina", None):
            mi_oficina_id = _oficina_id(user.perfil.oficina)

        cliente_match = self._buscar_cliente(dni_raw, mi_oficina_id) if dni_raw else None
        patente_match = self._buscar_patente(patente_raw) if patente_raw else None

        # Determinar el caso
        caso = self._determinar_caso(cliente_match, patente_match)

        return Response(
            {
                "caso": caso,
                "cliente_match": cliente_match,
                "patente_match": patente_match,
            },
            status=status.HTTP_200_OK,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Búsqueda por DNI (GLOBAL, robusta a puntos/espacios/guiones)
    # ─────────────────────────────────────────────────────────────────────────
    def _buscar_cliente(self, dni_raw, mi_oficina_id):
        dni_norm = _only_digits(dni_raw)
        if not dni_norm:
            return None

        cli = (
            Cliente.objects
            .annotate(_dni_limpio=_dni_columna_limpia())
            .filter(
                Q(dni_cuit_cuil__iexact=dni_raw)   # match exacto original (compat)
                | Q(dni_cuit_cuil__iexact=dni_norm)
                | Q(_dni_limpio=dni_norm)          # 🚀 ignora puntos/espacios/guiones
            )
            .first()
        )

        if not cli:
            return None

        # Pólizas del cliente (también globales)
        pol_qs = (
            Poliza.objects.select_related("cliente", "oficina")
            .filter(cliente_id=cli.id)
            .order_by("-id")[:50]
        )

        polizas_data = []
        for p in pol_qs:
            estado = (getattr(p, "estado", "") or "").upper()
            fecha_baja = getattr(p, "fecha_baja", None)
            esta_vigente = not fecha_baja and estado not in (
                "FINALIZADA", "DADA_DE_BAJA", "BAJA", "CANCELADA", "ANULADA",
            )

            cuotas_pendientes = Cuota.objects.filter(
                poliza_id=p.id, pagado=False
            ).count()

            al_dia = None
            if esta_vigente:
                al_dia = cuotas_pendientes == 0

            polizas_data.append({
                "poliza_id": p.id,
                "numero_poliza": getattr(p, "numero_poliza", "") or "",
                "compania": str(getattr(p, "compania", "") or ""),
                "patente": getattr(p, "patente", "") or "",
                "marca": getattr(p, "marca", "") or "",
                "modelo": getattr(p, "modelo", "") or "",
                "oficina_id": _oficina_id(getattr(p, "oficina", None)),
                "oficina_nombre": _oficina_nombre(getattr(p, "oficina", None)),
                "estado": getattr(p, "estado", "") or "",
                "fecha_baja": fecha_baja.isoformat() if fecha_baja else None,
                "esta_vigente": esta_vigente,
                "al_dia": al_dia,
                "cuotas_pendientes": cuotas_pendientes,
            })

        oficina_cliente_id = None
        oficina_cliente_nombre = ""
        cli_oficina = getattr(cli, "oficina", None)
        if cli_oficina:
            oficina_cliente_id = _oficina_id(cli_oficina)
            oficina_cliente_nombre = _oficina_nombre(cli_oficina)

        # Si el cliente no tiene oficina propia, usamos la oficina de su póliza más reciente
        if not oficina_cliente_nombre and polizas_data:
            oficina_cliente_id = polizas_data[0]["oficina_id"]
            oficina_cliente_nombre = polizas_data[0]["oficina_nombre"]

        return {
            "id": cli.id,
            "nombre": getattr(cli, "nombre", "") or "",
            "apellido": getattr(cli, "apellido", "") or "",
            "nombre_apellido": f"{getattr(cli, 'apellido', '') or ''} {getattr(cli, 'nombre', '') or ''}".strip(),
            "dni_cuit_cuil": getattr(cli, "dni_cuit_cuil", "") or "",
            "telefono": getattr(cli, "telefono", "") or "",
            "email": getattr(cli, "email", "") or "",
            "oficina_id": oficina_cliente_id,
            "oficina_nombre": oficina_cliente_nombre,
            "es_de_mi_oficina": (
                oficina_cliente_id == mi_oficina_id
            ) if (mi_oficina_id and oficina_cliente_id) else False,
            "polizas": polizas_data,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Búsqueda por Patente (GLOBAL, robusta a espacios/guiones/mayúsculas)
    # ─────────────────────────────────────────────────────────────────────────
    def _buscar_patente(self, patente_raw):
        pat_norm = _normalize_patente(patente_raw)
        if not pat_norm:
            return None

        pol = (
            Poliza.objects.select_related("cliente", "oficina")
            .annotate(_pat_limpio=_patente_columna_limpia())
            .filter(
                Q(patente__iexact=patente_raw)   # match exacto original (compat)
                | Q(patente__iexact=pat_norm)
                | Q(_pat_limpio=pat_norm)         # 🚀 ignora espacios/guiones/puntos y mayúsc/minúsc
            )
            .order_by("-id")
            .first()
        )

        if not pol:
            return None

        estado = (getattr(pol, "estado", "") or "").upper()
        fecha_baja = getattr(pol, "fecha_baja", None)
        esta_vigente = not fecha_baja and estado not in (
            "FINALIZADA", "DADA_DE_BAJA", "BAJA", "CANCELADA", "ANULADA",
        )

        cuotas_pendientes = Cuota.objects.filter(
            poliza_id=pol.id, pagado=False
        ).count()

        al_dia = None
        if esta_vigente:
            al_dia = cuotas_pendientes == 0

        cli = pol.cliente
        cliente_payload = None
        if cli:
            cliente_payload = {
                "id": cli.id,
                "nombre_apellido": f"{getattr(cli, 'apellido', '') or ''} {getattr(cli, 'nombre', '') or ''}".strip(),
                "dni_cuit_cuil": getattr(cli, "dni_cuit_cuil", "") or "",
                "telefono": getattr(cli, "telefono", "") or "",
            }

        return {
            "poliza_id": pol.id,
            "numero_poliza": getattr(pol, "numero_poliza", "") or "",
            "patente": getattr(pol, "patente", "") or "",
            "marca": getattr(pol, "marca", "") or "",
            "modelo": getattr(pol, "modelo", "") or "",
            "compania": str(getattr(pol, "compania", "") or ""),
            "oficina_id": _oficina_id(getattr(pol, "oficina", None)),
            "oficina_nombre": _oficina_nombre(getattr(pol, "oficina", None)),
            "estado": getattr(pol, "estado", "") or "",
            "esta_vigente": esta_vigente,
            "al_dia": al_dia,
            "fecha_baja": fecha_baja.isoformat() if fecha_baja else None,
            "cuotas_pendientes": cuotas_pendientes,
            "cliente": cliente_payload,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Determinación del caso
    # ─────────────────────────────────────────────────────────────────────────
    def _determinar_caso(self, cliente_match, patente_match):
        if patente_match:
            if patente_match["esta_vigente"]:
                # Auto YA asegurado y vigente → solo pagar o renovar
                return "PATENTE_VIGENTE"
            # Patente existe pero fue dada de baja → permite crear nueva
            return "PATENTE_BAJA"

        if cliente_match:
            # Cliente existe pero patente no → vincular y continuar
            return "CLIENTE_OTRO_AUTO"

        # Todo nuevo
        return "NUEVO"