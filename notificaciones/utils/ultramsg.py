import os
import re
import requests
from django.conf import settings

"""
UltraMsg – Envío de WhatsApp para la app 'notificaciones'.

Actualización: 
- Soporte para envío de imágenes (URL o archivos locales convertidos a URL).
- Detección automática de endpoint: /messages/chat para texto, /messages/image para fotos.
- 🚀 SISTEMA DINÁMICO: Lee las credenciales (Instancia y Token) directamente de la Base de Datos (modelo Oficina).
"""

ULTRAMSG_TIMEOUT = int(
    getattr(settings, "ULTRAMSG_TIMEOUT", None) or os.getenv("ULTRAMSG_TIMEOUT", 10)
)
ULTRAMSG_SIMULATE = (
    getattr(settings, "ULTRAMSG_SIMULATE", None)
    or os.getenv("ULTRAMSG_SIMULATE", "false")
).lower() in {"1", "true", "yes", "y", "on"}

# Código de país por defecto (Argentina = 54)
ULTRAMSG_DEFAULT_CC = getattr(settings, "ULTRAMSG_DEFAULT_CC", None) or os.getenv(
    "ULTRAMSG_DEFAULT_CC", "54"
)

# ------------------ Config por oficina (Dinámico desde DB) ------------------

def _get_env_val(name: str) -> str:
    """Busca en settings, y si está vacío, devuelve un string vacío seguro."""
    val = getattr(settings, name, None) or os.getenv(name)
    return str(val).strip() if val else ""


def _get_creds_for_oficina(oficina: str | int | None):
    print(f"\n--- 🔍 DEBUG ULTRAMSG: Buscando credenciales para oficina_raw='{oficina}' ---")
    
    # Fallback: Credenciales globales por si la oficina falla o no tiene configuración
    global_inst = _get_env_val("ULTRAMSG_INSTANCE_ID")
    global_tok = _get_env_val("ULTRAMSG_TOKEN")

    if not oficina:
        print("⚠️ Oficina vacía, usando credenciales globales.")
        return global_inst, global_tok

    # 🚀 Importación local para evitar errores de carga circular en Django
    from usuarios.models import Oficina 

    try:
        oficina_str = str(oficina).strip()
        
        # 1. Buscamos la oficina en la base de datos
        if oficina_str.isdigit():
            oficina_obj = Oficina.objects.get(id=int(oficina_str))
        else:
            oficina_obj = Oficina.objects.get(codigo__iexact=oficina_str)

        # 2. Verificamos si tiene credenciales propias cargadas en el Admin
        if oficina_obj.ultramsg_instance_id and oficina_obj.ultramsg_token:
            inst = oficina_obj.ultramsg_instance_id.strip()
            tok = oficina_obj.ultramsg_token.strip()
            
            tok_mask = f"{tok[:4]}***"
            inst_mask = f"{inst[:4]}***"
            print(f"✅ Encontró en DB: Instancia={inst_mask} | Token={tok_mask} para la oficina '{oficina_obj.nombre}'")
            return inst, tok
        else:
            print(f"⚠️ La oficina '{oficina_obj.nombre}' existe pero no tiene credenciales cargadas. Usando GLOBAL.")

    except Oficina.DoesNotExist:
        print(f"⚠️ Oficina '{oficina}' no encontrada en la base de datos. Usando GLOBAL.")
    except Exception as e:
        print(f"❌ Error buscando oficina en DB: {e}. Usando GLOBAL.")

    return global_inst, global_tok


# ------------------ Normalización de número ------------------

def _normalizar_numero(raw: str) -> str:
    """
    Normaliza un número a formato E.164 (+54911XXXXXXXX para móviles AR).

    Reglas Argentina:
    - Móvil AR completo con CC: 54 + 9 + area + numero = 13 dígitos → +5491157053435
    - Fijo AR completo con CC:  54 + area + numero = 12 dígitos     → +541157053435
    - Local sin CC:             area + numero ≥ 10 dígitos          → se agrega +549

    Bug que arregla: si los dígitos empiezan con "54" pero son < 12, NO es código
    de país, es coincidencia (ej: un local de 10 dígitos que arranca con 54).
    Antes se mandaba "+5457053435" → UltraMsg lo marcaba inválido.
    Ahora se trata como local y se le agrega el prefijo completo +549.
    """
    if not raw:
        raise ValueError("Número vacío")

    s = str(raw).strip()

    # Caso 1: viene con + explícito → confiamos pero limpiamos
    if s.startswith("+"):
        solo_digitos = re.sub(r"\D", "", s[1:])
        if len(solo_digitos) < 10:
            raise ValueError(f"Número muy corto: +{solo_digitos}")
        return f"+{solo_digitos}"

    # Caso 2: sin +, limpiamos y normalizamos
    digits = re.sub(r"\D", "", s)
    if not digits:
        raise ValueError(f"Número inválido: {raw!r}")

    # Sacar 0 inicial (larga distancia local AR)
    if digits.startswith("0"):
        digits = digits[1:]

    # Sacar 15 inicial (prefijo móvil viejo AR)
    if digits.startswith("15"):
        digits = digits[2:]

    cc = ULTRAMSG_DEFAULT_CC  # "54" por defecto

    # --- Lógica específica para Argentina ---
    if cc == "54":
        # Si empieza con 54, validamos que sea CC real (no coincidencia)
        # Móvil AR completo = 13 dígitos (54 + 9 + 10), fijo AR = 12 dígitos (54 + 10)
        if digits.startswith("54") and len(digits) >= 12:
            return f"+{digits}"

        # Si empieza con 549 y tiene 13 dígitos, es móvil AR completo
        if digits.startswith("549") and len(digits) == 13:
            return f"+{digits}"

        # Local AR: necesita al menos 10 dígitos (código área + número)
        if len(digits) < 10:
            raise ValueError(
                f"Número AR muy corto: '{digits}' ({len(digits)} dig). "
                f"Faltan dígitos (¿código de área?). Raw: {raw!r}"
            )

        # Local AR de 10+ dígitos → agregar 549 (convención WhatsApp móvil AR)
        return f"+549{digits}"

    # Otros países: lógica simple
    if digits.startswith(cc):
        return f"+{digits}"
    return f"+{cc}{digits}"


# ------------------ Envío ------------------

def enviar_mensaje(
    numero: str,
    mensaje: str,
    *,
    simulate: bool | None = None,
    oficina: str | int | None = None,
    imagen: str | None = None,  # 🆕 Parámetro agregado para multimedia
):
    """
    Envía un mensaje de WhatsApp usando UltraMsg.
    Ahora soporta de forma nativa el envío de imágenes si se pasa el argumento 'imagen'.
    """
    if simulate is None:
        simulate = ULTRAMSG_SIMULATE

    try:
        numero_norm = _normalizar_numero(numero)
    except Exception as exc:
        print(f"❌ Error de número: {exc}")
        return False, {"error": "invalid_number", "detail": str(exc), "raw": numero}

    instance_id, token = _get_creds_for_oficina(oficina)

    if simulate:
        tipo = "IMAGEN" if imagen else "TEXTO"
        print(
            f"🧪 [SIMULADO] UltraMsg ({tipo}) (oficina={oficina!r}) "
            f"a {numero_norm}: {mensaje[:80]!r}..."
        )
        if imagen:
            print(f"📸 URL Imagen: {imagen}")
            
        return True, {
            "simulate": True,
            "to": numero_norm,
            "body_preview": mensaje[:120],
            "imagen_url": imagen,
            "oficina": str(oficina) if oficina is not None else None,
        }

    if not instance_id or not token:
        print("❌ Faltan credenciales (instance_id o token están vacíos).")
        return False, {
            "error": "config_missing",
            "detail": "Faltan credenciales UltraMSG para la oficina o global.",
        }

    # 🆕 Lógica de selección de Endpoint y Datos
    if imagen:
        # Si hay imagen, usamos el endpoint de imágenes
        url = f"https://api.ultramsg.com/{instance_id}/messages/image"
        data = {
            "token": token,
            "to": numero_norm,
            "image": imagen,      # URL de la imagen
            "caption": mensaje,   # El mensaje de texto se convierte en el pie de foto
        }
    else:
        # Si NO hay imagen, enviamos texto simple
        url = f"https://api.ultramsg.com/{instance_id}/messages/chat"
        data = {
            "token": token,
            "to": numero_norm,
            "body": mensaje,
        }

    print(f"🚀 Disparando request a URL: {url}")
    
    try:
        resp = requests.post(url, data=data, timeout=ULTRAMSG_TIMEOUT)
        print(f"📥 Respuesta UltraMsg HTTP {resp.status_code}: {resp.text}")
    except requests.RequestException as exc:
        print(f"❌ Error de red con UltraMsg: {exc}")
        return False, {
            "error": "request_exception",
            "detail": str(exc),
            "to": numero_norm,
        }

    if not resp.ok:
        print(f"❌ UltraMsg devolvió error {resp.status_code}: {resp.text[:500]}")
        return False, {
            "error": "http_error",
            "status_code": resp.status_code,
            "text": resp.text[:500],
            "to": numero_norm,
        }

    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": resp.text[:500]}

    payload.setdefault("to", numero_norm)
    payload.setdefault("provider", "ultramsg")
    payload.setdefault("instance_id", instance_id)
    payload.setdefault("multimedia", bool(imagen))

    print(
        f"✅ UltraMsg [{'IMAGE' if imagen else 'TEXT'}] enviado "
        f"a {numero_norm} (oficina={oficina!r})"
    )
    return True, payload