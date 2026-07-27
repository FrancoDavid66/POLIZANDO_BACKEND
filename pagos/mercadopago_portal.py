# pagos/mercadopago_portal.py
"""
Mercado Pago desde el PORTAL DEL ASEGURADO (público, sin login).

El cliente entra por su link único (/public/portal/<token>/) y paga una cuota.
Como el portal es público (el cliente no tiene sesión), este endpoint NO exige
autenticación: se valida por el TOKEN del portal, igual que el resto de
/public/portal/.

⚠️ MODO PRUEBA / MONTO MANUAL:
Este endpoint acepta un `monto` mandado desde el portal. Sirve para probar el
cobro mientras las cuotas todavía se crean sin monto. Cuando las cuotas ya
nazcan con su monto real, se puede ignorar el `monto` del body y usar el de la
cuota (queda comentado abajo dónde).

Flujo:
1) El portal hace POST /public/portal/<token>/mp/crear-preferencia/
   body: { "cuota_id": <int>, "monto": <number> }
2) Devuelve init_point → el cliente paga en Mercado Pago.
3) Mercado Pago pega al webhook (pagos/mercadopago_pagos.webhook) → marca pagada.

El token se resuelve con la MISMA lógica que usa el portal para servir datos.
Para no acoplarnos a una implementación puntual, intentamos resolver el cliente
por el token de varias formas conocidas y, si no se puede, devolvemos 404.
"""
import logging

import mercadopago
from django.conf import settings

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

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


def _front_portal_url(request, token: str) -> str:
    """A dónde vuelve el cliente después de pagar (su propio portal)."""
    front = (getattr(settings, "MP_FRONT_URL", "") or "").strip().rstrip("/")
    if front:
        # El portal del asegurado vive en /#/portal/<token> (HashRouter)
        return f"{front}/#/portal/{token}"
    return ""


def _cuota_pertenece_al_token(cuota: Cuota, token: str) -> bool:
    """
    Verifica que la cuota sea de una póliza accesible por ese token de portal.

    El portal identifica al cliente por un token en la póliza o el cliente.
    Chequeamos los campos más probables sin romper si alguno no existe.
    Si tu modelo usa otro nombre de campo para el token, agregalo a la lista
    CAMPOS_TOKEN de abajo.
    """
    token = (token or "").strip()
    if not token:
        return False

    poliza = getattr(cuota, "poliza", None)
    if poliza is None:
        return False

    cliente = getattr(poliza, "cliente", None)

    # Nombres de campo candidatos donde puede vivir el token del portal.
    CAMPOS_TOKEN = ("portal_token", "token_portal", "token", "public_token", "uuid")

    for obj in (poliza, cliente):
        if obj is None:
            continue
        for campo in CAMPOS_TOKEN:
            val = getattr(obj, campo, None)
            if val and str(val).strip() == token:
                return True
    return False


@api_view(["POST"])
@permission_classes([AllowAny])
def crear_preferencia_portal(request, token):
    """
    Body: { "cuota_id": <int>, "monto": <number opcional en modo prueba> }
    Devuelve: { preference_id, init_point, sandbox_init_point }
    """
    cuota_id = request.data.get("cuota_id")
    monto_manual = request.data.get("monto")

    if not cuota_id:
        return Response({"detail": "Falta cuota_id."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        cuota = (
            Cuota.objects
            .select_related("poliza", "poliza__cliente")
            .get(pk=cuota_id)
        )
    except Cuota.DoesNotExist:
        return Response({"detail": "La cuota no existe."}, status=status.HTTP_404_NOT_FOUND)

    # 🔒 Seguridad: la cuota tiene que ser de una póliza de ESE token de portal.
    if not _cuota_pertenece_al_token(cuota, token):
        return Response(
            {"detail": "Esta cuota no corresponde a tu portal."},
            status=status.HTTP_403_FORBIDDEN,
        )

    if cuota.pagado:
        return Response(
            {"detail": "Esta cuota ya figura como pagada."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # ── Monto ─────────────────────────────────────────────────────────────
    # MODO PRUEBA: si viene monto manual, lo usamos. Si no, el de la cuota.
    # PARA PRODUCCIÓN (cuando las cuotas ya tengan monto real): borrá el bloque
    # del monto_manual y dejá solo:  monto = cuota.monto
    monto = None
    if monto_manual is not None and str(monto_manual).strip() != "":
        try:
            monto = float(str(monto_manual).replace(".", "").replace(",", ".")) \
                if isinstance(monto_manual, str) else float(monto_manual)
        except (TypeError, ValueError):
            monto = None
    if monto is None:
        monto = float(cuota.monto) if cuota.monto is not None else 0.0

    if monto <= 0:
        return Response(
            {"detail": "El monto a pagar no es válido. Ingresá un importe mayor a 0."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    poliza = cuota.poliza
    num_pol = getattr(poliza, "numero_poliza", "") or ""
    titulo = f"Cuota {cuota.cuota_nro}"
    if num_pol:
        titulo += f" · Póliza {num_pol}"

    email_cliente = ""
    cliente = getattr(poliza, "cliente", None)
    if cliente:
        email_cliente = (getattr(cliente, "email", "") or "").strip()

    base_back = _base_url_backend(request)
    url_portal = _front_portal_url(request, token)

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
        log.exception("[MP-portal] Error creando preferencia para cuota %s: %s", cuota_id, e)
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