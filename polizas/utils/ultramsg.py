# polizas/utils/ultramsg.py
import os
import re
import requests
from django.conf import settings

"""
UltraMsg – Envío de WhatsApp
- Usa credenciales de settings/ENV.
- Normaliza números (Argentina -> +549… para móviles; remueve 0/15).
- Soporta modo simulación.
"""

ULTRAMSG_INSTANCE_ID = getattr(
    settings, "ULTRAMSG_INSTANCE_ID", os.environ.get("ULTRAMSG_INSTANCE_ID", "")
)
ULTRAMSG_TOKEN = getattr(
    settings, "ULTRAMSG_TOKEN", os.environ.get("ULTRAMSG_TOKEN", "")
)
ULTRAMSG_TIMEOUT = int(getattr(
    settings, "ULTRAMSG_TIMEOUT", os.environ.get("ULTRAMSG_TIMEOUT", "12")
))
ULTRAMSG_SIMULATE = bool(getattr(
    settings, "ULTRAMSG_SIMULATE", os.environ.get("ULTRAMSG_SIMULATE", "false")).__str__().lower() == "true"
)
ULTRAMSG_DEFAULT_CC = str(getattr(
    settings, "ULTRAMSG_DEFAULT_CC", os.environ.get("ULTRAMSG_DEFAULT_CC", "54")
))

_E164 = re.compile(r"^\+\d{8,15}$")

def _normalizar_numero(numero: str) -> str:
    if not numero:
        raise ValueError("Número vacío")
    s = str(numero).strip()
    if s.startswith("+"):
        s = "+" + re.sub(r"\D", "", s[1:])
    else:
        s = re.sub(r"\D", "", s)
        s = f"+{ULTRAMSG_DEFAULT_CC}{s}"

    # Ajustes para Argentina (WhatsApp => +549…)
    if s.startswith("+54"):
        resto = s[3:]
        if resto.startswith("0"):
            resto = resto[1:]
        if resto.startswith("15"):
            resto = resto[2:]
        if not resto.startswith("9"):
            resto = "9" + resto
        s = "+54" + resto

    s = "+" + re.sub(r"\D", "", s[1:])
    return s

def enviar_mensaje(numero: str, mensaje: str, *, simulate: bool | None = None):
    """
    Retorna (ok: bool, info: dict)
    info siempre incluye el 'to' normalizado si fue posible.
    """
    if simulate is None:
        simulate = ULTRAMSG_SIMULATE

    try:
        to = _normalizar_numero(numero)
    except Exception as e:
        return False, {"error": "invalid_number", "detail": str(e), "to": None}

    if simulate:
        print(f"🧪 [SIMULADO] UltraMsg a {to}: {mensaje[:120]}{'…' if len(mensaje) > 120 else ''}")
        return True, {"provider": "ultramsg", "simulate": True, "to": to}

    if not ULTRAMSG_INSTANCE_ID or not ULTRAMSG_TOKEN:
        return False, {"error": "config_missing", "to": to}

    url = f"https://api.ultramsg.com/{ULTRAMSG_INSTANCE_ID}/messages/chat"
    data = {"token": ULTRAMSG_TOKEN, "to": to, "body": mensaje}

    try:
        r = requests.post(url, data=data, timeout=ULTRAMSG_TIMEOUT)
        if r.ok:
            try:
                payload = r.json()
            except Exception:
                payload = {"status_code": r.status_code, "text": r.text}
            if isinstance(payload, dict):
                payload.setdefault("to", to)
                payload.setdefault("provider", "ultramsg")
            print(f"✅ UltraMsg enviado a {to}")
            return True, payload
        print(f"❌ UltraMsg error {r.status_code} → {r.text}")
        return False, {"status_code": r.status_code, "text": r.text, "to": to}
    except requests.RequestException as e:
        print(f"❌ UltraMsg excepción: {e}")
        return False, {"error": str(e), "to": to}
