# notificaciones/services_balanzes.py
import requests
from typing import Optional

from django.conf import settings

from .utils.balanzes.messages import build_balance_message, format_phone_ar

# 🚀 CAMBIO AQUÍ: Agregamos el 549 (Código de Argentina + Celular)
# ✅ ÚNICO destinatario permitido (hardcodeado)
BALANCE_ONLY_PHONE = "5491164235336"


def _ultramsg_ok(info):
    """
    UltraMsg a veces devuelve 200 aunque el envío no se haya realizado.
    Este helper intenta detectar errores comunes en el JSON.
    """
    if not isinstance(info, dict):
        # si no es dict, no podemos inferir mucho
        return True

    # patrones típicos de error
    if info.get("error"):
        return False
    status = str(info.get("status") or "").lower().strip()
    if status in {"error", "failed", "fail"}:
        return False

    # algunos providers usan "sent": true/false
    sent = info.get("sent")
    if sent is False:
        return False

    # si hay un mensaje explícito que parece error
    msg = str(info.get("message") or info.get("msg") or "").lower()
    if "invalid" in msg or "token" in msg and "invalid" in msg:
        return False
    if "not connected" in msg or "disconnected" in msg:
        return False

    return True


def enviar_balance_por_whatsapp(fecha, data: dict, destinatario: Optional[str] = None):
    """
    Envía el balance diario por WhatsApp usando UltraMsg.

    ✅ REGLA: SIEMPRE envía únicamente a BALANCE_ONLY_PHONE = "5491164235336"
    - Se ignora el parámetro 'destinatario'
    - Se ignoran settings de teléfonos

    Devuelve: (ok: bool, info: dict|str)
    """
    instance_id = getattr(settings, "ULTRAMSG_INSTANCE_ID", None)
    token = getattr(settings, "ULTRAMSG_TOKEN", None)

    if not instance_id or not token:
        return False, {
            "error": "Faltan credenciales ULTRAMSG_INSTANCE_ID o ULTRAMSG_TOKEN en settings.",
            "instance_id": instance_id,
            "has_token": bool(token),
        }

    # ✅ Ignorar cualquier destinatario recibido
    to_raw = BALANCE_ONLY_PHONE

    to = format_phone_ar(to_raw)
    if not to:
        return False, {"error": "Número de destino inválido", "to_raw": to_raw}

    body = build_balance_message(fecha, data)

    url = f"https://api.ultramsg.com/{instance_id}/messages/chat"
    payload = {
        "token": token,
        "to": to,
        "body": body,
    }

    try:
        resp = requests.post(url, data=payload, timeout=20)
    except Exception as e:
        return False, {
            "error": "Error al conectar con UltraMsg",
            "exception": str(e),
            "url": url,
            "to": to,
        }

    try:
        ultramsg_info = resp.json()
    except Exception:
        ultramsg_info = resp.text

    # ✅ debug completo para que lo veas en la respuesta del endpoint
    debug = {
        "http_status": resp.status_code,
        "url": url,
        "to": to,
        "to_raw": to_raw,
        "instance_id": instance_id,
        "ultramsg": ultramsg_info,
    }

    # si HTTP no ok -> fallo
    if not resp.ok:
        return False, debug

    # si HTTP ok pero JSON muestra error -> fallo
    if not _ultramsg_ok(ultramsg_info):
        debug["error"] = "UltraMsg devolvió respuesta con error (aunque HTTP=200)."
        return False, debug

    return True, debug