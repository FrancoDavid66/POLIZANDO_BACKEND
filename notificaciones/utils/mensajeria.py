# notificaciones/utils/mensajeria.py
from __future__ import annotations

import re
from typing import Any, Dict, Tuple

from django.conf import settings

# UltraMsg como proveedor principal
try:
    from notificaciones.utils.ultramsg import enviar_mensaje as ultramsg_enviar

    _ULTRAMSG_OK = True
except Exception:  # pragma: no cover
    ultramsg_enviar = None  # type: ignore
    _ULTRAMSG_OK = False

# Twilio como fallback opcional
try:
    from twilio.rest import Client as TwilioClient  # type: ignore

    _TWILIO_OK = True
except Exception:  # pragma: no cover
    TwilioClient = None  # type: ignore
    _TWILIO_OK = False


def _to_bool(v, default=False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "true", "t", "yes", "y", "on", "si", "sí"):
        return True
    if s in ("0", "false", "f", "no", "n", "off"):
        return False
    return default


def _mask(s: Any, keep: int = 3) -> str:
    """
    Enmascara tokens/ids para logs de debug.
    """
    x = str(s or "")
    if len(x) <= keep:
        return "*" * len(x)
    return x[:keep] + ("*" * (len(x) - keep))


def _normalize_phone_ar(numero: str) -> str | None:
    """
    Normaliza a formato E.164 para AR:
    - Deja solo dígitos
    - Quita 00 / 0 inicial
    - Asegura prefijo 54 si falta
    """
    raw = (numero or "").strip()
    if not raw:
        return None

    # permitir "whatsapp:+54..." o "whatsapp:549..."
    raw = raw.replace("whatsapp:", "").strip()

    digits = re.sub(r"\D+", "", raw)
    if not digits:
        return None

    # 00... => ...
    if digits.startswith("00"):
        digits = digits[2:]

    # 0... => ...
    if digits.startswith("0"):
        digits = digits[1:]

    # si viene con 54 ya ok
    if digits.startswith("54"):
        return f"+{digits}"

    # si parece un nro AR sin prefijo país => le agrego 54
    # (ej: 9xxxxxxxxxx o 11xxxxxxxx o 3xxxxxxxx)
    return f"+54{digits}"


def enviar_whatsapp(
    numero: str,
    mensaje: str,
    oficina: str | int | None = None,
    imagen: str | None = None, # 🆕 Parámetro agregado para soportar multimedia
) -> Tuple[bool, Dict[str, Any]]:
    """
    Envía un WhatsApp usando UltraMsg (principal) o Twilio (fallback).
    Ahora acepta 'imagen' (URL pública de la imagen) para envíos multimedia.
    Devuelve (ok, info).
    """
    debug = _to_bool(getattr(settings, "NOTIFICACIONES_DEBUG_WHATSAPP", False), False)

    last_error: Dict[str, Any] = {}

    # Normalizar número SIEMPRE
    numero_norm = _normalize_phone_ar(numero)
    if not numero_norm:
        return False, {
            "provider": None,
            "error": "invalid_phone",
            "detail": "Número vacío o inválido",
            "numero_in": str(numero or ""),
        }

    # 1) UltraMsg (principal)
    if _ULTRAMSG_OK and ultramsg_enviar is not None:
        extra_kwargs: Dict[str, Any] = {}
        if oficina is not None:
            extra_kwargs["oficina"] = str(oficina)

        # 🆕 Se pasa el argumento 'imagen' explícitamente a ultramsg_enviar
        ok, info = ultramsg_enviar(numero_norm, mensaje, imagen=imagen, **extra_kwargs)

        if ok:
            out = dict(info or {})
            out.setdefault("provider", "ultramsg")
            if debug:
                out["_debug"] = {
                    "oficina": str(oficina) if oficina is not None else None,
                    "numero_in": str(numero or ""),
                    "numero_norm": numero_norm,
                    "ultramsg_enabled": True,
                    "imagen": imagen,
                }
            return True, out

        # fallo UltraMsg
        last_error = {"provider": "ultramsg", **(info or {})}
        if debug:
            inst = getattr(settings, "ULTRAMSG_INSTANCE_ID", None)
            tok = getattr(settings, "ULTRAMSG_TOKEN", None)
            last_error["_debug"] = {
                "oficina": str(oficina) if oficina is not None else None,
                "numero_in": str(numero or ""),
                "numero_norm": numero_norm,
                "ultramsg_enabled": True,
                "global_instance_id_masked": _mask(inst),
                "global_token_masked": _mask(tok),
                "imagen": imagen,
            }

    # 2) Twilio (fallback opcional)
    if _TWILIO_OK:
        sid = getattr(settings, "TWILIO_ACCOUNT_SID", None)
        token = getattr(settings, "TWILIO_AUTH_TOKEN", None)
        from_number = getattr(settings, "TWILIO_WHATSAPP_FROM", None)

        if sid and token and from_number:
            try:
                client = TwilioClient(sid, token)
                to_val = (
                    numero_norm
                    if str(numero_norm).startswith("whatsapp:")
                    else f"whatsapp:{numero_norm}"
                )
                
                # 🆕 Preparar parámetros para Twilio incluyendo multimedia si existe
                params = {
                    "body": mensaje,
                    "from_": from_number,
                    "to": to_val,
                }
                if imagen:
                    params["media_url"] = [imagen]

                msg = client.messages.create(**params)
                
                out = {
                    "provider": "twilio",
                    "sid": msg.sid,
                    "status": msg.status,
                }
                if debug:
                    out["_debug"] = {
                        "numero_in": str(numero or ""),
                        "numero_norm": numero_norm,
                        "to": to_val,
                        "from_masked": _mask(from_number),
                        "imagen": imagen,
                    }
                return True, out
            except Exception as exc:  # noqa: BLE001
                last_error = {
                    "provider": "twilio",
                    "error": str(exc),
                }
                if debug:
                    last_error["_debug"] = {
                        "numero_in": str(numero or ""),
                        "numero_norm": numero_norm,
                        "from_masked": _mask(from_number),
                    }

    # 3) Ningún proveedor disponible o ambos fallaron
    if not last_error:
        last_error = {
            "error": "no_provider_or_failed",
            "detail": "No hay proveedor de WhatsApp configurado o ambos fallaron",
        }
        if debug:
            last_error["_debug"] = {
                "ultramsg_enabled": bool(_ULTRAMSG_OK and ultramsg_enviar),
                "twilio_enabled": bool(_TWILIO_OK),
                "numero_in": str(numero or ""),
                "numero_norm": numero_norm,
                "oficina": str(oficina) if oficina is not None else None,
            }

    return False, last_error