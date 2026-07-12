# notificaciones/management/commands/enviar_recordatorios_cupones_robo.py
#
# Envía recordatorios por WhatsApp a los clientes que tienen CUPONERAS DE ROBO
# pendientes de pago. Avisa en 3 momentos: 3 días ANTES de vencer, el MISMO día
# y 3 días DESPUÉS del vencimiento.
#
# Reutiliza la infraestructura de UltraMsg por oficina (enviar_whatsapp).
#
# Uso:
#   python manage.py enviar_recordatorios_cupones_robo
#   python manage.py enviar_recordatorios_cupones_robo --simulate
#   python manage.py enviar_recordatorios_cupones_robo --cliente-id 123
#   python manage.py enviar_recordatorios_cupones_robo --tel 1166
#
# Cron Railway (9:30 Argentina = 12:30 UTC, después del de cuotas):
#   30 12 * * *

import logging
import os
from collections import defaultdict
from datetime import timedelta

from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand
from django.utils import timezone

from polizas.models import CuponRobo
from notificaciones.utils.mensajeria import enviar_whatsapp

logger = logging.getLogger(__name__)

# URL del frontend para armar el link del portal.
# 🔒 Sin default: cada proyecto (Thames / Polizando) tiene que apuntar al SUYO.
# Antes esto caía en el front de Thames si faltaba la env var — ahora el
# comando no arranca en vez de mandarle al cliente el link de otro proyecto.
FRONTEND_URL = os.environ.get("FRONTEND_URL")
if not FRONTEND_URL:
    raise ImproperlyConfigured(
        "❌ Falta la variable de entorno FRONTEND_URL (URL del front de Polizando). "
        "Setealá en Railway antes de correr este comando."
    )
FRONTEND_URL = FRONTEND_URL.rstrip("/")


def _portal_link(cliente):
    """Asegura el token del cliente y devuelve el link a su portal (HashRouter)."""
    try:
        token = cliente.asegurar_portal_token()
    except Exception:
        token = getattr(cliente, "portal_token", "") or ""
    return f"{FRONTEND_URL}/#/portal/{token}" if token else ""


# Cuándo avisar (días respecto a HOY): +3 = vence en 3 días, 0 = hoy, -3 = venció hace 3
DELTAS = {
    "antes_3":   3,
    "hoy":       0,
    "despues_3": -3,
}
ETIQUETA = {
    "antes_3":   "vence en 3 días",
    "hoy":       "vence hoy",
    "despues_3": "venció hace 3 días",
}


def _primer_nombre(cliente):
    n = (getattr(cliente, "nombre", "") or "").strip()
    if n:
        return n.split()[0]
    full = (getattr(cliente, "nombre_completo", "") or "").strip()
    return full.split(",")[-1].strip().split()[0] if full else "Hola"


def _datos_poliza(poliza):
    numero = getattr(poliza, "numero_poliza", "") or f"#{getattr(poliza, 'id', '')}"
    veh = " ".join([str(getattr(poliza, "marca", "") or ""), str(getattr(poliza, "modelo", "") or "")]).strip()
    patente = getattr(poliza, "patente", "") or ""
    return numero, veh, patente


def armar_mensaje(cliente, items):
    """items: lista de tuplas (cupon, tipo_delta)."""
    nombre = _primer_nombre(cliente)
    partes = [f"Hola {nombre} 👋\n", "Te recordamos el pago de tu *cuponera de robo*:\n"]
    for cupon, tipo in items:
        numero, veh, patente = _datos_poliza(cupon.poliza)
        venc = cupon.fecha_vencimiento.strftime("%d/%m/%Y") if cupon.fecha_vencimiento else "—"
        det_veh = f" {veh}" if veh else ""
        det_pat = f" ({patente})" if patente else ""
        partes.append(f"• Póliza {numero}{det_veh}{det_pat}\n   {ETIQUETA.get(tipo, '')} — vence {venc}")
    partes.append("\nPor favor regularizá el pago para mantener tu cobertura de robo activa.")
    link = _portal_link(cliente)
    if link:
        partes.append(f"\nMirá tus cupones y avisanos tu pago desde acá:\n{link}")
    partes.append("\n¡Gracias! 💙")
    return "\n".join(partes)


def ejecutar(simulate=False, cliente_id=None, telefono_contiene=None):
    hoy = timezone.localdate()
    print(f"\n📅 Hoy: {hoy}\n🔎 Buscando cuponeras de robo para recordar...\n")

    # cliente -> lista de (cupon, tipo)
    por_cliente = defaultdict(list)
    contadores = defaultdict(int)

    for tipo, delta in DELTAS.items():
        fecha = hoy + timedelta(days=delta)
        qs = (
            CuponRobo.objects
            .filter(estado__in=[CuponRobo.Estado.PENDIENTE, CuponRobo.Estado.VENCIDA], fecha_vencimiento=fecha)
            .select_related("poliza", "poliza__cliente")
        )
        if cliente_id:
            qs = qs.filter(poliza__cliente_id=cliente_id)
        if telefono_contiene:
            qs = qs.filter(poliza__cliente__telefono__icontains=telefono_contiene)

        for cupon in qs:
            cli = getattr(cupon.poliza, "cliente", None)
            if not cli:
                continue
            por_cliente[cli].append((cupon, tipo))
            contadores[tipo] += 1

    total_ok = total_err = total_sin_tel = 0

    for cliente, items in por_cliente.items():
        tel = getattr(cliente, "telefono", None)
        if not tel:
            print(f"⚠️ Cliente {getattr(cliente, 'id', '?')} sin teléfono. Omitido.")
            total_sin_tel += 1
            continue

        # Oficina emisora = la de la póliza del primer cupón
        oficina_id = getattr(items[0][0].poliza, "oficina_id", None)
        mensaje = armar_mensaje(cliente, items)

        if simulate:
            print(f"🧪 [SIMULADO] WhatsApp a {tel} ({len(items)} cupón/es)")
            total_ok += 1
            continue

        try:
            ok, info = enviar_whatsapp(tel, mensaje, oficina=str(oficina_id) if oficina_id else None)
            if ok:
                print(f"✅ WhatsApp a {tel} ({len(items)} cupón/es)")
                total_ok += 1
            else:
                print(f"❌ No salió a {tel}: {info}")
                total_err += 1
        except Exception as e:
            logger.error(f"[recordatorios_cupones_robo] {tel}: {e}")
            print(f"❌ Error a {tel}: {e}")
            total_err += 1

    print("\n— Resumen por momento —")
    for tipo in DELTAS:
        print(f"  {ETIQUETA[tipo]}: {contadores.get(tipo, 0)} cupón/es")
    print(f"\n📤 Clientes OK: {total_ok} | Errores: {total_err} | Sin teléfono: {total_sin_tel}")

    return {"fecha": str(hoy), "ok": total_ok, "errores": total_err, "sin_telefono": total_sin_tel}


class Command(BaseCommand):
    help = "Recordatorios por WhatsApp de cuponeras de robo (3 días antes, el día y 3 después)."

    def add_arguments(self, parser):
        parser.add_argument("--simulate", action="store_true", help="No envía; solo simula.")
        parser.add_argument("--cliente-id", type=int, help="Filtra por ID de cliente (pruebas).")
        parser.add_argument("--tel", type=str, help="Filtra por teléfono que contenga el texto (pruebas).")

    def handle(self, *args, **opts):
        ejecutar(
            simulate=bool(opts.get("simulate")),
            cliente_id=opts.get("cliente_id"),
            telefono_contiene=opts.get("tel"),
        )