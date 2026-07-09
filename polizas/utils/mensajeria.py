# polizas/utils/mensajeria.py
from __future__ import annotations
from typing import Tuple, Dict, Any
from datetime import date
from django.conf import settings
from django.utils import timezone
from pagos.models import Cuota

# Proveedor principal: UltraMsg
try:
    from polizas.utils.ultramsg import enviar_mensaje as ultramsg_enviar
    _ULTRAMSG_OK = True
except Exception:
    _ULTRAMSG_OK = False

def _fmt_fecha(d: date) -> str:
    try:
        return d.strftime("%d/%m/%Y")
    except Exception:
        return str(d)

def construir_mensaje_estado_cuotas(poliza) -> str:
    hoy = timezone.localdate()
    cli = getattr(poliza, "cliente", None)
    nom = " ".join(filter(None, [getattr(cli, "nombre", ""), getattr(cli, "apellido", "")])).strip()

    ident = poliza.numero_poliza or poliza.patente or f"ID #{poliza.id}"
    marca = (poliza.marca or "").strip()
    modelo = (poliza.modelo or "").strip()
    compania = (poliza.compania or "").strip()

    # ⚠️ Bloque de bienvenida del día 10 DESACTIVADO.
    # El mensaje de post-venta automático ya no se envía.

    impagas = list(
        Cuota.objects.filter(poliza=poliza, pagado=False)
        .order_by("fecha_vencimiento", "cuota_nro", "id")
    )

    encabezado = f"Hola {nom}," if nom else "Hola,"
    header_poliza = f" póliza {ident}" if ident else " tu póliza"
    header_compania = f" de {compania}" if compania else ""
    header_auto = f" ({marca} {modelo})".strip()

    intro = f"{encabezado} te escribimos por el estado de{header_poliza}{header_compania}"

    if not impagas:
        cuerpo = (f"{intro}{' ' + header_auto if marca or modelo else ''}.\n"
                  "✅ Estás al día con tus cuotas. ¡Gracias!")
        return cuerpo

    primera = impagas[0]
    vto = getattr(primera, "fecha_vencimiento", None)

    if vto:
        if vto < hoy:
            dias = (hoy - vto).days
            detalle = f"La más antigua venció el {_fmt_fecha(vto)} (hace {dias} día{'s' if dias != 1 else ''})."
        elif vto == hoy:
            detalle = f"Tu cuota vence hoy ({_fmt_fecha(vto)})."
        else:
            dias = (vto - hoy).days
            detalle = f"Tu próxima cuota vence el {_fmt_fecha(vto)} (en {dias} día{'s' if dias != 1 else ''})."
    else:
        detalle = "Tenés cuotas pendientes."

    try:
        monto_total = sum([(c.monto or 0) for c in impagas])
    except Exception:
        monto_total = 0
    monto_txt = f" Importe pendiente aprox.: ${monto_total:,.0f}".replace(",", ".") if monto_total else ""

    cuerpo = (f"{intro}{' ' + header_auto if marca or modelo else ''}.\n"
              f"⚠️ Tenés {len(impagas)} cuota{'s' if len(impagas)!=1 else ''} pendiente{'s' if len(impagas)!=1 else ''}. "
              f"{detalle}{monto_txt}\n"
              "Si ya pagaste, por favor ignorá este mensaje. Ante cualquier consulta, respondé este WhatsApp. Gracias.")

    return cuerpo

def enviar_whatsapp(numero: str, mensaje: str) -> Tuple[bool, Dict[str, Any]]:
    # Se mantiene la lógica de UltraMsg y Twilio igual a tu versión original
    if _ULTRAMSG_OK:
        ok, info = ultramsg_enviar(numero, mensaje)
        if ok:
            return True, info
        ultimo_to = (info or {}).get("to")

    sid = getattr(settings, "TWILIO_ACCOUNT_SID", None)
    token = getattr(settings, "TWILIO_AUTH_TOKEN", None)
    from_ = getattr(settings, "TWILIO_WHATSAPP_FROM", None)
    if sid and token and from_:
        try:
            from twilio.rest import Client
            client = Client(sid, token)
            to = numero if str(numero).startswith("+") else f"+{numero}"
            msg = client.messages.create(to=f"whatsapp:{to}", from_=f"whatsapp:{from_}", body=mensaje)
            return True, {"provider": "twilio", "sid": msg.sid, "to": to}
        except Exception as e:
            return False, {"provider": "twilio", "error": str(e), "to": numero}

    return False, {"error": "no_provider_or_failed"}