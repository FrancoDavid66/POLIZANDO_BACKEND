import re
import requests
from django.conf import settings


ULTRAMSG_BASE_URL = "https://api.ultramsg.com"


def _only_digits(s: str) -> str:
    return re.sub(r"\D+", "", str(s or ""))


def normalizar_numero_ar(numero: str) -> str:
    """
    Normaliza a formato internacional para AR.
    - Quita espacios/guiones/paréntesis
    - Quita prefijos 00 / 0
    - Si parece número local AR sin país, agrega 54
    Devuelve string sin '@c.us' (UltraMsg acepta +E164 o digits; usamos digits con + si corresponde).
    """
    raw = str(numero or "").strip()
    if not raw:
        return ""

    # Si viene tipo chatId "xxxxxxxx@c.us" lo dejamos como digits base
    raw = raw.replace("@c.us", "").replace("@g.us", "")

    digits = _only_digits(raw)
    if not digits:
        return ""

    # prefijos comunes
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = digits[1:]

    # Si no empieza con código país y parece AR, prefijamos 54.
    # Heurística: números AR suelen tener 10-11 dígitos (sin país).
    if not digits.startswith("54") and (10 <= len(digits) <= 11):
        digits = "54" + digits

    # UltraMsg suele aceptar +E164 o digits; usamos + para claridad
    return f"+{digits}"


def _extract_oficina_from_poliza(poliza):
    """
    Extrae (oficina_id, oficina_label) de forma robusta.
    Soporta:
      - poliza.oficina FK (obj con .id / .nombre)
      - poliza.oficina int
      - poliza.oficina str
    """
    if not poliza:
        return (None, "")

    oficina = getattr(poliza, "oficina", None)
    if oficina is None:
        return (None, "")

    # FK u objeto
    if hasattr(oficina, "id"):
        oid = getattr(oficina, "id", None)
        label = getattr(oficina, "nombre", None) or getattr(oficina, "name", None) or str(oficina)
        try:
            oid = int(oid) if oid is not None else None
        except Exception:
            oid = None
        return (oid, str(label or "").strip())

    # número
    if isinstance(oficina, (int, float)) or (isinstance(oficina, str) and oficina.strip().isdigit()):
        try:
            return (int(str(oficina).strip()), str(oficina).strip())
        except Exception:
            return (None, str(oficina).strip())

    # texto
    return (None, str(oficina).strip())


def _get_ultramsg_credentials(oficina_id=None, oficina_label=""):
    """
    Busca credenciales por oficina en settings de manera flexible.

    Soporta 3 formatos típicos (cualquiera):
    1) ULTRAMSG_BY_OFICINA = { "2": {"INSTANCE_ID": "...", "TOKEN":"..."}, 2: {...}, "Axion": {...} }
    2) ULTRAMSG_INSTANCE_ID_OFICINA_2 / ULTRAMSG_TOKEN_OFICINA_2
    3) ULTRAMSG_INSTANCE_ID / ULTRAMSG_TOKEN (global) -> solo se usa si allow_global=True
    """
    by_oficina = getattr(settings, "ULTRAMSG_BY_OFICINA", None)
    if isinstance(by_oficina, dict):
        # intentos por id
        if oficina_id is not None:
            for k in (oficina_id, str(oficina_id)):
                cfg = by_oficina.get(k)
                if isinstance(cfg, dict):
                    iid = cfg.get("INSTANCE_ID") or cfg.get("instance_id")
                    tok = cfg.get("TOKEN") or cfg.get("token")
                    if iid and tok:
                        return str(iid), str(tok)

        # intentos por label/nombre
        if oficina_label:
            cfg = by_oficina.get(oficina_label) or by_oficina.get(str(oficina_label).strip())
            if isinstance(cfg, dict):
                iid = cfg.get("INSTANCE_ID") or cfg.get("instance_id")
                tok = cfg.get("TOKEN") or cfg.get("token")
                if iid and tok:
                    return str(iid), str(tok)

    # formato 2: vars por oficina
    if oficina_id is not None:
        iid = getattr(settings, f"ULTRAMSG_INSTANCE_ID_OFICINA_{oficina_id}", None)
        tok = getattr(settings, f"ULTRAMSG_TOKEN_OFICINA_{oficina_id}", None)
        if iid and tok:
            return str(iid), str(tok)

    return (None, None)


def enviar_whatsapp(numero, texto, *, poliza=None, oficina_id=None, oficina_label="", allow_global=False, timeout=15):
    """
    Envío real por UltraMsg.

    - Por defecto exige credenciales por oficina.
    - NO usa global por defecto (allow_global=False).
    - Devuelve dict con ok, status_code, provider_response/error.

    Params:
      numero: teléfono del cliente
      texto: mensaje
      poliza: si se pasa, de ahí saca oficina (si no pasás oficina_id)
      oficina_id/oficina_label: opcional, para forzar oficina
      allow_global: si True y no hay config por oficina, usa ULTRAMSG_INSTANCE_ID/TOKEN
    """
    if not numero or not texto:
        return {"ok": False, "error": "faltan datos"}

    to = normalizar_numero_ar(numero)
    if not to:
        return {"ok": False, "error": "numero invalido"}

    # resolver oficina
    if oficina_id is None and poliza is not None:
        oid, olabel = _extract_oficina_from_poliza(poliza)
        oficina_id = oid
        oficina_label = oficina_label or olabel

    # ✅ Guard rail: si no hay oficina y no se permite global, no enviamos
    if (oficina_id is None and not str(oficina_label or "").strip()) and not allow_global:
        return {
            "ok": False,
            "error": "falta oficina para enviar whatsapp (pasar poliza u oficina_id).",
            "oficina_id": oficina_id,
            "oficina_label": oficina_label,
            "to": to,
        }

    instance_id, token = _get_ultramsg_credentials(oficina_id=oficina_id, oficina_label=oficina_label)

    if not instance_id or not token:
        if allow_global:
            instance_id = getattr(settings, "ULTRAMSG_INSTANCE_ID", None)
            token = getattr(settings, "ULTRAMSG_TOKEN", None)
        if not instance_id or not token:
            return {
                "ok": False,
                "error": "no hay credenciales ultramsg para la oficina",
                "oficina_id": oficina_id,
                "oficina_label": oficina_label,
            }

    url = f"{ULTRAMSG_BASE_URL}/{instance_id}/messages/chat"

    try:
        # UltraMsg acepta token/to/body; lo mandamos como form-data.
        payload = {
            "token": token,
            "to": to,
            "body": str(texto),
            "priority": 10,
        }
        resp = requests.post(url, data=payload, timeout=timeout)
        ok = 200 <= resp.status_code < 300
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}

        return {
            "ok": ok,
            "status_code": resp.status_code,
            "to": to,
            "oficina_id": oficina_id,
            "provider_response": data,
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"error enviando whatsapp: {e}",
            "to": to,
            "oficina_id": oficina_id,
        }


def plantilla_solicitud(s):
    """
    Mensaje para el cliente (se puede ajustar desde views).
    """
    poliza_num = getattr(s.poliza, "numero_poliza", None) or getattr(s.poliza, "numero", None) or s.poliza_id
    prov = getattr(getattr(s, "proveedor", None), "nombre", "") or "Sin asignar"
    destino = s.destino or "-"
    return (
        f"🚨 *Grúa solicitada*\n"
        f"Solicitud #{s.id}\n"
        f"Póliza: {poliza_num}\n"
        f"Motivo: {s.motivo}\n"
        f"Estado: {s.estado}\n"
        f"Origen: {s.origen}\n"
        f"Destino: {destino}\n"
        f"Proveedor: {prov}\n"
        f"KM est.: {s.km_estimados}\n"
    )
