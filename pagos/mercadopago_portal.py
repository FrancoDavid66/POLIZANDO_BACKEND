# pagos/mercadopago_portal.py
"""
Mercado Pago desde el PORTAL DEL ASEGURADO (público, sin login).

El cliente entra por su link único (/#/portal/<token>) y paga una cuota.
Público: se valida por el TOKEN del portal = Poliza.token_portal (UUID).

⚠️ MODO PRUEBA / MONTO MANUAL: acepta un `monto` mandado desde el portal.
🔑 Identifica la cuota por (token_portal + cuota_nro); no depende del id.

🔎 VERSIÓN CON DIAGNÓSTICO: toda la vista está envuelta en try/except que
   DEVUELVE el detalle del error en el JSON ({"detail","error","tipo"}), para
   verlo en la consola del navegador sin entrar a los logs de Railway. Cuando
   funcione, se puede volver a la versión que oculta el error.
"""
import logging
import traceback

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
    import mercadopago  # import adentro: si falta el paquete, lo capturamos como error claro
    token = getattr(settings, "MP_ACCESS_TOKEN", "") or ""
    if not token.strip():
        raise RuntimeError("Falta configurar MP_ACCESS_TOKEN en Railway (Polizando).")
    return mercadopago.SDK(token.strip())


def _base_url_backend(request) -> str:
    base = (getattr(settings, "MP_BACKEND_URL", "") or "").strip().rstrip("/")
    if base:
        return base
    return request.build_absolute_uri("/").rstrip("/")


def _front_base() -> str:
    return (getattr(settings, "MP_FRONT_URL", "") or "").strip().rstrip("/")


def _parse_monto(monto_raw, fallback):
    if monto_raw is not None and str(monto_raw).strip() != "":
        try:
            if isinstance(monto_raw, str):
                return float(monto_raw.replace(".", "").replace(",", "."))
            return float(monto_raw)
        except (TypeError, ValueError):
            pass
    return float(fallback) if fallback is not None else 0.0


@api_view(["POST"])
@authentication_classes([])          # público
@permission_classes([AllowAny])
def crear_preferencia_portal(request, token):
    """
    Body: { "cuota_nro": <int>, "monto": <number> }  (o "cuota_id")
    Devuelve: { preference_id, init_point, sandbox_init_point }
    En error, devuelve {detail, error, tipo} para diagnóstico.
    """
    try:
        # 1) Póliza por token del portal
        poliza = get_object_or_404(
            Poliza.objects.select_related("cliente"),
            token_portal=token,
        )

        # 2) Ubicar la cuota (cuota_id atajo, o cuota_nro dentro de la póliza)
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

        # 3) Monto (modo prueba: manual; si no, cuota.monto)
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
        front_base = _front_base()

        preference_data = {
            "items": [
                {
                    "id": str(cuota.id),
                    "title": titulo,
                    "quantity": 1,
                    "unit_price": round(float(monto), 2),
                    "currency_id": "ARS",
                }
            ],
            "external_reference": str(cuota.id),
            "metadata": {
                "cuota_id": cuota.id,
                "poliza_id": getattr(poliza, "id", None),
                "cuota_nro": cuota.cuota_nro,
                "origen": "portal",
            },
            "statement_descriptor": "POLIZANDO",
        }

        # notification_url: solo si el backend es https público (MP no acepta http/localhost).
        if base_back.startswith("https://"):
            preference_data["notification_url"] = f"{base_back}/public/pagos/mp/webhook/"

        if email_cliente:
            preference_data["payer"] = {"email": email_cliente}

        # back_urls: SIN el "#" (MP valida la URL y el fragmento le cae mal).
        # Mandamos la home del front; NO usamos auto_return para no arriesgar el
        # rechazo de la preferencia si la URL no le gusta a MP.
        if front_base.startswith("https://"):
            preference_data["back_urls"] = {
                "success": front_base,
                "pending": front_base,
                "failure": front_base,
            }

        # 4) Crear la preferencia
        sdk = _get_sdk()
        resp = sdk.preference().create(preference_data)

        body = resp.get("response", {}) or {}
        if resp.get("status") not in (200, 201) or "id" not in body:
            # Error devuelto por Mercado Pago (ej. token inválido, campo mal).
            log.error("[MP-portal] MP no devolvió preferencia válida: %s", resp)
            return Response(
                {
                    "detail": "Mercado Pago rechazó la preferencia.",
                    "mp_status": resp.get("status"),
                    "mp": body,
                },
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

    except Exception as e:
        # 🔎 Devolvemos el error REAL para verlo en la consola del navegador.
        log.exception("[MP-portal] 500 al crear preferencia: %s", e)
        return Response(
            {
                "detail": "No se pudo generar el link de pago.",
                "error": str(e),
                "tipo": type(e).__name__,
                "traceback": traceback.format_exc().splitlines()[-6:],
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )