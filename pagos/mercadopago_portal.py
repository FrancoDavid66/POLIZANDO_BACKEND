# pagos/mercadopago_portal.py
"""
Mercado Pago desde el PORTAL DEL ASEGURADO (público, sin login).

El cliente entra por su link único (/#/portal/<token>) y paga una cuota.
Como el portal es público (el cliente no tiene sesión), este endpoint NO exige
autenticación: se valida por el TOKEN del portal = Poliza.token_portal (UUID).

⚠️ MODO PRUEBA / MONTO MANUAL:
Acepta un `monto` mandado desde el portal (mientras las cuotas se crean sin
monto). Cuando las cuotas ya nazcan con monto real, se ignora el `monto` del
body y se usa el de la cuota (ver comentario abajo).

🔑 IDENTIFICACIÓN DE LA CUOTA SIN `id`:
El JSON del portal no manda el id de cada cuota, así que NO dependemos de él.
Identificamos la cuota por (token_portal de la póliza + cuota_nro). Igual
aceptamos cuota_id si algún día viene, como atajo.

Flujo:
1) POST /public/pagos/portal/<token>/mp/crear-preferencia/
   body: { "cuota_nro": <int>, "monto": <number> }   (o { "cuota_id": <int>, ... })
2) Devuelve init_point → el cliente paga en Mercado Pago.
3) Mercado Pago pega al webhook (pagos/mercadopago_pagos.webhook) → marca pagada.
"""
import logging

import mercadopago
from django.conf import settings
from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from polizas.models import Poliza
from .models import Cuota

log = logging.getLogger(__name__)


def _get_sdk():
    token = getattr(settings, "MP_ACCESS_TOKEN", "") or ""
    if not token.strip():
        raise RuntimeError(
            "Falta configurar MP_ACCESS_TOKEN en las variables de entorno "
            "de Railway (Polizando)."
        )
    return mercadopago.SDK(token.strip())


def _base_url_backend(request) -> str:
    base = (getattr(settings, "MP_BACKEND_URL", "") or "").strip().rstrip("/")
    if base:
        return base
    return request.build_absolute_uri("/").rstrip("/")


def _front_portal_url(token: str) -> str:
    """A dónde vuelve el cliente después de pagar (su propio portal)."""
    front = (getattr(settings, "MP_FRONT_URL", "") or "").strip().rstrip("/")
    if front:
        # El portal del asegurado vive en /#/portal/<token> (HashRouter)
        return f"{front}/#/portal/{token}"
    return ""


def _parse_monto(monto_raw, fallback):
    """Normaliza el monto que viene del portal ('47.000' / '47000' / 47000)."""
    if monto_raw is not None and str(monto_raw).strip() != "":
        try:
            if isinstance(monto_raw, str):
                return float(monto_raw.replace(".", "").replace(",", "."))
            return float(monto_raw)
        except (TypeError, ValueError):
            pass
    return float(fallback) if fallback is not None else 0.0


@api_view(["POST"])
@authentication_classes([])          # público: sin auth
@permission_classes([AllowAny])
def crear_preferencia_portal(request, token):
    """
    Body: { "cuota_nro": <int>, "monto": <number> }
    (también acepta "cuota_id" como atajo si algún día el portal lo manda)
    Devuelve: { preference_id, init_point, sandbox_init_point }
    """
    # 1) El token identifica la póliza (Poliza.token_portal). 404 si no existe.
    poliza = get_object_or_404(
        Poliza.objects.select_related("cliente"),
        token_portal=token,
    )

    # 2) Ubicar la cuota: por cuota_id (atajo) o por cuota_nro dentro de ESA póliza.
    cuota_id = request.data.get("cuota_id")
    cuota_nro = request.data.get("cuota_nro")

    cuota = None
    if cuota_id:
        cuota = Cuota.objects.filter(pk=cuota_id, poliza=poliza).first()
    if cuota is None and cuota_nro is not None and str(cuota_nro).strip() != "":
        try:
            cuota = Cuota.objects.filter(poliza=poliza, cuota_nro=int(cuota_nro)).first()
        except (TypeError, ValueError):
            cuota = None

    if cuota is None:
        return Response(
            {"detail": "No encontramos esa cuota en tu póliza."},
            status=status.HTTP_404_NOT_FOUND,
        )

    if cuota.pagado:
        return Response(
            {"detail": "Esta cuota ya figura como pagada."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # 3) Monto ── MODO PRUEBA: usa el monto manual; si no viene, el de la cuota.
    #    PRODUCCIÓN: borrá el uso de monto_manual y dejá  monto = float(cuota.monto or 0)
    monto = _parse_monto(request.data.get("monto"), cuota.monto)
    if monto <= 0:
        return Response(
            {"detail": "El monto a pagar no es válido. Ingresá un importe mayor a 0."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    num_pol = getattr(poliza, "numero_poliza", "") or ""
    titulo = f"Cuota {cuota.cuota_nro}"
    if num_pol:
        titulo += f" · Póliza {num_pol}"

    email_cliente = ""
    cliente = getattr(poliza, "cliente", None)
    if cliente:
        email_cliente = (getattr(cliente, "email", "") or "").strip()

    base_back = _base_url_backend(request)
    url_portal = _front_portal_url(token)

    preference_data = {
        "items": [
            {
                "id": str(cuota.id),
                "title": titulo,
                "quantity": 1,
                "unit_price": round(monto, 2),
                "currency_id": "ARS",
            }
        ],
        # external_reference = id real de la cuota → el webhook la marca por acá.
        "external_reference": str(cuota.id),
        "notification_url": f"{base_back}/public/pagos/mp/webhook/",
        "metadata": {
            "cuota_id": cuota.id,
            "poliza_id": getattr(poliza, "id", None),
            "cuota_nro": cuota.cuota_nro,
            "origen": "portal",
        },
        "statement_descriptor": "POLIZANDO",
    }

    if email_cliente:
        preference_data["payer"] = {"email": email_cliente}

    if url_portal:
        preference_data["back_urls"] = {
            "success": url_portal,
            "pending": url_portal,
            "failure": url_portal,
        }
        preference_data["auto_return"] = "approved"

    try:
        sdk = _get_sdk()
        resp = sdk.preference().create(preference_data)
    except Exception as e:
        log.exception("[MP-portal] Error creando preferencia (cuota %s): %s", cuota.id, e)
        return Response(
            {"detail": "No se pudo generar el link de pago.", "error": str(e)},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    body = resp.get("response", {}) or {}
    if resp.get("status") not in (200, 201) or "id" not in body:
        log.error("[MP-portal] Respuesta inesperada al crear preferencia: %s", resp)
        return Response(
            {"detail": "Mercado Pago no devolvió una preferencia válida.", "mp": body},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    return Response(
        {
            "preference_id": body.get("id"),
            "init_point": body.get("init_point"),
            "sandbox_init_point": body.get("sandbox_init_point"),
        },
        status=status.HTTP_201_CREATED,
    )