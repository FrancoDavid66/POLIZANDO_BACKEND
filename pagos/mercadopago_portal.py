# pagos/mercadopago_portal.py
"""
Mercado Pago desde el PORTAL DEL ASEGURADO (público, sin login).

El cliente entra por su link único (/#/portal/<token>) y paga una cuota.
Público: se valida por el TOKEN del portal = **Cliente.portal_token**
(token_urlsafe, NO es UUID). Mismo campo que usa clientes/public_views.py.

⚠️ MODO PRUEBA / MONTO MANUAL: acepta un `monto` mandado desde el portal.
🔑 Ubicación de la cuota (el JSON del portal NO manda id de cuota):
   token → Cliente → sus pólizas → cuota por cuota_nro (+ poliza_id si viene).

Flujo:
1) POST /public/pagos/portal/<token>/mp/crear-preferencia/
   body: { "cuota_nro": <int>, "poliza_id": <int opcional>, "monto": <number> }
2) Devuelve init_point → el cliente paga en Mercado Pago.
3) Webhook (pagos/mercadopago_pagos.webhook) marca la cuota pagada.
"""
import logging
import traceback

from django.conf import settings

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from clientes.models import Cliente
from polizas.models import Poliza
from .models import Cuota

log = logging.getLogger(__name__)


def _get_sdk():
    import mercadopago
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


@api_view(["GET"])
@authentication_classes([])          # público
@permission_classes([AllowAny])
def diagnostico_mp(request):
    """
    GET /public/pagos/mp/diag/
    Diagnóstico SEGURO (no expone el token): dice si el backend VE la config
    de Mercado Pago. Sirve para descartar problemas de variables de entorno.
    Borrar este endpoint cuando el pago funcione.
    """
    import os

    def _info(nombre):
        # settings (lo que la app tiene resuelto) y os.environ (lo que llega al proceso)
        val_settings = getattr(settings, nombre, None)
        val_env = os.environ.get(nombre, None)
        return {
            "en_settings": bool(val_settings and str(val_settings).strip()),
            "largo_settings": len(str(val_settings).strip()) if val_settings else 0,
            "en_environ": bool(val_env and str(val_env).strip()),
            "largo_environ": len(str(val_env).strip()) if val_env else 0,
            "empieza": (str(val_settings or val_env)[:5] + "…") if (val_settings or val_env) else "",
        }

    # Además: listamos los nombres de env vars que contienen "MP" o "MERCADO"
    import os as _os
    relacionadas = sorted(
        k for k in _os.environ.keys()
        if "MP_" in k.upper() or "MERCADO" in k.upper()
    )

    return Response({
        "MP_ACCESS_TOKEN": _info("MP_ACCESS_TOKEN"),
        "MP_BACKEND_URL": _info("MP_BACKEND_URL"),
        "MP_FRONT_URL": _info("MP_FRONT_URL"),
        "env_vars_relacionadas": relacionadas,
    })


@api_view(["POST"])
@authentication_classes([])          # público
@permission_classes([AllowAny])
def crear_preferencia_portal(request, token):
    """
    Body: { "cuota_nro": <int>, "poliza_id": <int opcional>, "monto": <number> }
    Devuelve: { preference_id, init_point, sandbox_init_point }
    En error, devuelve {detail, error, tipo, traceback} para diagnóstico.
    """
    try:
        # 1) El token identifica al CLIENTE (Cliente.portal_token), NO a la póliza.
        cli = (
            Cliente.objects
            .filter(portal_token=token)
            .first()
        )
        if cli is None:
            return Response(
                {"detail": "Link inválido o vencido."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 2) Pólizas de ese cliente (las mismas que muestra el portal).
        polizas_cli = list(
            Poliza.objects.filter(cliente=cli)
            .exclude(estado__in=["cancelada", "finalizada", "en_verificacion"])
        )
        if not polizas_cli:
            return Response(
                {"detail": "No tenés pólizas activas para pagar."},
                status=status.HTTP_404_NOT_FOUND,
            )
        poliza_ids = [p.id for p in polizas_cli]

        # 3) Ubicar la cuota: por poliza_id (si vino) o por cuota_nro dentro de
        #    las pólizas del cliente. También aceptamos cuota_id como atajo.
        cuota_id = request.data.get("cuota_id")
        cuota_nro = request.data.get("cuota_nro")
        poliza_id = request.data.get("poliza_id")

        cuota = None
        if cuota_id:
            cuota = Cuota.objects.filter(pk=cuota_id, poliza_id__in=poliza_ids).first()

        if cuota is None and cuota_nro is not None and str(cuota_nro).strip() != "":
            try:
                nro = int(cuota_nro)
            except (TypeError, ValueError):
                nro = None
            if nro is not None:
                qs = Cuota.objects.filter(poliza_id__in=poliza_ids, cuota_nro=nro)
                if poliza_id:
                    qs_p = qs.filter(poliza_id=poliza_id)
                    cuota = qs_p.first() or qs.first()
                else:
                    # Sin poliza_id: si hay una sola póliza, es inequívoco.
                    # Preferimos una cuota impaga de esa nro.
                    cuota = qs.filter(pagado=False).first() or qs.first()

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

        poliza = cuota.poliza

        # 4) Monto (modo prueba: manual; si no, cuota.monto)
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

        email_cliente = (getattr(cli, "email", "") or "").strip()

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

        # back_urls SIN "#" (MP valida la URL). Sin auto_return para no arriesgar rechazo.
        if front_base.startswith("https://"):
            preference_data["back_urls"] = {
                "success": front_base,
                "pending": front_base,
                "failure": front_base,
            }

        # 5) Crear la preferencia en Mercado Pago
        sdk = _get_sdk()
        resp = sdk.preference().create(preference_data)

        body = resp.get("response", {}) or {}
        if resp.get("status") not in (200, 201) or "id" not in body:
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