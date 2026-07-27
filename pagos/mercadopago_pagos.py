# pagos/mercadopago_pagos.py
"""
Integración Mercado Pago — Checkout Pro (pago manual de una cuota).

Flujo:
1) El front pide una preferencia de pago para una cuota concreta
   (POST /api/pagos/mp/crear-preferencia/  ->  devuelve init_point).
2) El cliente paga en la pantalla de Mercado Pago.
3) Mercado Pago avisa por webhook (POST /public/pagos/mp/webhook/).
4) El webhook confirma el pago aprobado y registra un Pago
   (que dispara el Ingreso en Balances por la señal existente) +
   marca la Cuota como pagada.

NO hereda ninguna credencial de Thames: el token se lee SIEMPRE de
la variable de entorno MP_ACCESS_TOKEN (Railway / Polizando).
"""
import logging

import mercadopago
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from .models import Cuota, Pago

log = logging.getLogger(__name__)


# =========================================================================
# Helpers
# =========================================================================
def _get_sdk():
    """
    Devuelve el SDK de Mercado Pago inicializado con el Access Token.

    El token se lee de settings.MP_ACCESS_TOKEN (que a su vez sale de la
    variable de entorno MP_ACCESS_TOKEN en Railway). Si falta, cortamos
    con un error claro en vez de fallar de forma silenciosa.
    """
    token = getattr(settings, "MP_ACCESS_TOKEN", "") or ""
    if not token.strip():
        raise RuntimeError(
            "Falta configurar MP_ACCESS_TOKEN en las variables de entorno "
            "de Railway (Polizando)."
        )
    return mercadopago.SDK(token.strip())


def _base_url_backend(request) -> str:
    """
    URL pública del backend (para armar la notification_url del webhook).
    Preferimos settings.MP_BACKEND_URL; si no está, la deducimos del request.
    """
    base = (getattr(settings, "MP_BACKEND_URL", "") or "").strip().rstrip("/")
    if base:
        return base
    return request.build_absolute_uri("/").rstrip("/")


def _url_front_retorno() -> str:
    """
    A dónde vuelve el cliente después de pagar (pantalla del front).
    Configurable con MP_FRONT_URL; si no está, cae en "/".
    """
    return (getattr(settings, "MP_FRONT_URL", "") or "").strip().rstrip("/") or ""


# =========================================================================
# 1) Crear preferencia de pago (lo llama el FRONT, requiere auth)
# =========================================================================
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def crear_preferencia(request):
    """
    Body esperado: { "cuota_id": <int> }

    Devuelve:
      {
        "preference_id": "...",
        "init_point": "https://www.mercadopago.com.ar/checkout/...",
        "sandbox_init_point": "https://sandbox.mercadopago.com.ar/checkout/..."
      }
    """
    cuota_id = request.data.get("cuota_id")
    if not cuota_id:
        return Response(
            {"detail": "Falta cuota_id."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        cuota = (
            Cuota.objects
            .select_related("poliza", "poliza__cliente")
            .get(pk=cuota_id)
        )
    except Cuota.DoesNotExist:
        return Response(
            {"detail": "La cuota no existe."},
            status=status.HTTP_404_NOT_FOUND,
        )

    if cuota.pagado:
        return Response(
            {"detail": "Esta cuota ya figura como pagada."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if cuota.monto is None or float(cuota.monto) <= 0:
        return Response(
            {"detail": "La cuota no tiene un monto válido para cobrar."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Datos para mostrar en el checkout
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
    url_front = _url_front_retorno()

    preference_data = {
        "items": [
            {
                "id": str(cuota.id),
                "title": titulo,
                "quantity": 1,
                "unit_price": float(cuota.monto),
                "currency_id": "ARS",
            }
        ],
        # external_reference = id de la cuota -> lo recuperamos en el webhook
        "external_reference": str(cuota.id),
        "notification_url": f"{base_back}/public/pagos/mp/webhook/",
        "metadata": {
            "cuota_id": cuota.id,
            "poliza_id": getattr(poliza, "id", None),
            "cuota_nro": cuota.cuota_nro,
        },
        "statement_descriptor": "POLIZANDO",
    }

    if email_cliente:
        preference_data["payer"] = {"email": email_cliente}

    if url_front:
        preference_data["back_urls"] = {
            "success": f"{url_front}/pago-exitoso",
            "pending": f"{url_front}/pago-pendiente",
            "failure": f"{url_front}/pago-error",
        }
        preference_data["auto_return"] = "approved"

    try:
        sdk = _get_sdk()
        resp = sdk.preference().create(preference_data)
    except Exception as e:
        log.exception("[MP] Error creando preferencia para cuota %s: %s", cuota_id, e)
        return Response(
            {"detail": "No se pudo generar el link de pago.", "error": str(e)},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    body = resp.get("response", {}) or {}
    if resp.get("status") not in (200, 201) or "id" not in body:
        log.error("[MP] Respuesta inesperada al crear preferencia: %s", resp)
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


# =========================================================================
# 2) Webhook (lo llama MERCADO PAGO, público / sin auth)
# =========================================================================
@api_view(["POST", "GET"])
@permission_classes([AllowAny])
def webhook(request):
    """
    Mercado Pago pega acá cuando cambia el estado de un pago.
    Puede llegar por query (?type=payment&data.id=123) o por body JSON.

    Respondemos 200 SIEMPRE que hayamos procesado (o ignorado) sin error,
    para que Mercado Pago no siga reintentando. Si el pago está aprobado,
    marcamos la cuota y registramos el Pago (idempotente).
    """
    # --- 1) Sacar el ID del pago venga por donde venga ---
    payment_id = (
        request.query_params.get("data.id")
        or request.query_params.get("id")
        or (request.data.get("data", {}) or {}).get("id")
        or request.data.get("id")
    )
    tipo = (
        request.query_params.get("type")
        or request.query_params.get("topic")
        or request.data.get("type")
        or request.data.get("topic")
        or ""
    )

    # Solo nos interesan notificaciones de pagos
    if tipo and tipo not in ("payment", "payment.updated", "payment.created"):
        return Response({"ok": True, "ignored": f"tipo {tipo}"}, status=status.HTTP_200_OK)

    if not payment_id:
        return Response({"ok": True, "ignored": "sin payment_id"}, status=status.HTTP_200_OK)

    # --- 2) Consultar el pago REAL a Mercado Pago (nunca confiar en el body) ---
    try:
        sdk = _get_sdk()
        mp_resp = sdk.payment().get(payment_id)
    except Exception as e:
        log.exception("[MP] Error consultando pago %s: %s", payment_id, e)
        # 200 igual: si devolvemos error, MP reintenta en loop. Ya quedó logueado.
        return Response({"ok": False, "error": str(e)}, status=status.HTTP_200_OK)

    pago_mp = mp_resp.get("response", {}) or {}
    estado_mp = pago_mp.get("status")  # approved / pending / rejected / ...
    external_reference = pago_mp.get("external_reference")

    if estado_mp != "approved":
        log.info("[MP] Pago %s en estado '%s' (no aprobado). No se marca cuota.", payment_id, estado_mp)
        return Response({"ok": True, "estado": estado_mp}, status=status.HTTP_200_OK)

    # --- 3) Recuperar la cuota (external_reference o metadata) ---
    cuota_id = external_reference
    if not cuota_id:
        meta = pago_mp.get("metadata", {}) or {}
        cuota_id = meta.get("cuota_id")

    if not cuota_id:
        log.error("[MP] Pago %s aprobado pero sin external_reference/cuota_id.", payment_id)
        return Response({"ok": False, "error": "sin cuota"}, status=status.HTTP_200_OK)

    try:
        with transaction.atomic():
            cuota = (
                Cuota.objects
                .select_for_update()
                .select_related("poliza")
                .get(pk=cuota_id)
            )

            # --- IDEMPOTENCIA: ¿ya registramos este payment_id? ---
            marca_pago = f"MP:{payment_id}"
            ya_registrado = Pago.objects.filter(
                cuota=cuota,
                observaciones__icontains=marca_pago,
            ).exists()

            if ya_registrado or cuota.pagado:
                log.info("[MP] Pago %s ya estaba aplicado a cuota %s. Nada que hacer.", payment_id, cuota_id)
                return Response({"ok": True, "duplicado": True}, status=status.HTTP_200_OK)

            monto = pago_mp.get("transaction_amount")
            if monto is None:
                monto = cuota.monto

            # 1) Registrar el Pago -> la señal post_save crea el Ingreso en Balances.
            #    Este Pago, por su save(), NO marca la cuota (eso lo hacemos abajo),
            #    así evitamos disparar el Ingreso dos veces.
            Pago.objects.create(
                poliza=cuota.poliza,
                cuota=cuota,
                cuota_nro=cuota.cuota_nro,
                monto=monto,
                metodo="transferencia",  # pago electrónico
                fecha=timezone.localdate(),
                observaciones=f"Pago online Mercado Pago ({marca_pago})",
                responsable_nombre="Mercado Pago",
            )

            # 2) Marcar la cuota como pagada SIN volver a tocar Balances.
            #    Usamos marcar_pagada con commit=True: setea pagado/fecha_pago/
            #    pago_registrado_en/forma_pago/observaciones.
            cuota.marcar_pagada(
                forma="transferencia",
                monto=monto,
                observaciones=f"Pago online Mercado Pago ({marca_pago})",
                responsable_nombre="Mercado Pago",
                commit=True,
            )

        log.info("[MP] Cuota %s marcada pagada por pago MP %s.", cuota_id, payment_id)

        # --- 4) Avisar al cliente por WhatsApp (no rompe el webhook si falla) ---
        _avisar_pago_whatsapp(cuota, monto)

        return Response({"ok": True, "cuota_id": cuota_id, "payment_id": payment_id}, status=status.HTTP_200_OK)

    except Cuota.DoesNotExist:
        log.error("[MP] Pago %s aprobado pero la cuota %s no existe.", payment_id, cuota_id)
        return Response({"ok": False, "error": "cuota inexistente"}, status=status.HTTP_200_OK)
    except Exception as e:
        log.exception("[MP] Error aplicando pago %s a cuota %s: %s", payment_id, cuota_id, e)
        return Response({"ok": False, "error": str(e)}, status=status.HTTP_200_OK)


def _avisar_pago_whatsapp(cuota, monto):
    """
    Manda un WhatsApp de confirmación al cliente cuando pagó una cuota online.
    Reusa notificaciones.utils.mensajeria.enviar_whatsapp (UltraMsg por oficina).
    NUNCA rompe el webhook: cualquier error se loguea y se ignora.
    """
    try:
        poliza = getattr(cuota, "poliza", None)
        cliente = getattr(poliza, "cliente", None) if poliza else None
        if cliente is None:
            return

        numero = (
            getattr(cliente, "telefono", "") or ""
        ).strip()
        if not numero:
            log.info("[MP] Cliente sin teléfono, no se envía WhatsApp (cuota %s).", getattr(cuota, "id", "?"))
            return

        nombre = (getattr(cliente, "nombre", "") or "").strip().split(" ")[0] or "Hola"
        try:
            monto_txt = f"${float(monto):,.0f}".replace(",", ".")
        except Exception:
            monto_txt = ""

        patente = (getattr(poliza, "patente", "") or "").strip()
        veh = f" de tu {patente}" if patente else ""

        mensaje = (
            f"¡Hola {nombre}! 👋 Recibimos tu pago{(' de ' + monto_txt) if monto_txt else ''} "
            f"de la cuota {cuota.cuota_nro}{veh}. ✅\n"
            f"Ya figura como pagada en tu portal. ¡Gracias por confiar en Polizando! 🐐"
        )

        # oficina de la póliza (UltraMsg toma sus credenciales por oficina)
        oficina = getattr(poliza, "oficina", None)

        from notificaciones.utils.mensajeria import enviar_whatsapp
        ok, info = enviar_whatsapp(numero, mensaje, oficina=oficina)
        if ok:
            log.info("[MP] WhatsApp de pago enviado a %s (cuota %s).", numero, cuota.id)
        else:
            log.warning("[MP] No se pudo enviar WhatsApp de pago (cuota %s): %s", cuota.id, info)
    except Exception as e:
        log.exception("[MP] Error enviando WhatsApp de pago: %s", e)