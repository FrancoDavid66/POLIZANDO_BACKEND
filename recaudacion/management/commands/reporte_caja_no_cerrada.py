# recaudacion/management/commands/reporte_caja_no_cerrada.py
#
# Avisa qué oficinas NO cerraron la caja hoy.
# Corre 1 vez al día por cron (ej. 21:00 Argentina), cuando ya deberían haber cerrado.
#
#   python manage.py reporte_caja_no_cerrada
#   python manage.py reporte_caja_no_cerrada --dry-run   (muestra sin enviar)
#
# Solo controla las oficinas que operan con caja (cerraron al menos una vez en
# los últimos 30 días). Si todas cerraron, no manda nada.

import os
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand
from django.utils import timezone

from usuarios.models import Oficina
from recaudacion.models import CierreCaja
from notificaciones.utils.mensajeria import enviar_whatsapp

logger = logging.getLogger(__name__)

# Destinatarios (mismos que renovaciones/buchón). Email override: env EMAIL_AVISO_CAJA (coma).
_EMAILS_DEFAULT = "francodavid_dev@outlook.com,Gomezdamianricardo284@gmail.com"
EMAILS_AVISO = [e.strip() for e in os.environ.get("EMAIL_AVISO_CAJA", _EMAILS_DEFAULT).split(",") if e.strip()]
WHATSAPP_NUMEROS = ["1164235336", "1161332173"]
def _oficina_con_whatsapp():
    """
    Id de una oficina activa que tenga credenciales de UltraMsg cargadas (o None).
    Se usa para los avisos internos al dueño: no importa de qué oficina salgan,
    solo que tengan credenciales válidas. Sin hardcodear: se detecta desde la DB.
    """
    try:
        from usuarios.models import Oficina
        ofi = (
            Oficina.objects.filter(activa=True)
            .exclude(ultramsg_instance_id__isnull=True).exclude(ultramsg_instance_id="")
            .exclude(ultramsg_token__isnull=True).exclude(ultramsg_token="")
            .order_by("id")
            .first()
        )
        return ofi.id if ofi else None
    except Exception:
        return None

# Una oficina "se espera que cierre" si cerró al menos una vez en estos días.
DIAS_ACTIVIDAD = 30
# No controlar los domingos (las oficinas no operan). Poné False si abren domingo.
SALTAR_DOMINGOS = True

ROJO = "#b91c1c"


def _oficinas_sin_cierre(hoy):
    desde = hoy - timedelta(days=DIAS_ACTIVIDAD)

    esperadas = set(
        CierreCaja.objects
        .filter(creado_en__date__gte=desde, oficina__isnull=False)
        .values_list("oficina_id", flat=True).distinct()
    )
    cerraron_hoy = set(
        CierreCaja.objects
        .filter(creado_en__date=hoy, oficina__isnull=False)
        .values_list("oficina_id", flat=True).distinct()
    )
    faltan = esperadas - cerraron_hoy
    return list(Oficina.objects.filter(id__in=faltan).order_by("id"))


def _mensaje_whatsapp(oficinas, fecha_txt):
    partes = [
        f"🚨 *Caja sin cerrar* — {fecha_txt}",
        f"{len(oficinas)} oficina(s) no cerraron la caja hoy:",
        "",
    ]
    for o in oficinas:
        partes.append(f"   • {o.nombre}")
    return "\n".join(partes)


def _email_html(oficinas, fecha_txt):
    filas = ""
    for o in oficinas:
        filas += f"""
        <tr><td style="padding:10px 14px;border-bottom:1px solid #f3f4f6;font-size:14px;color:#111827">🏢 {o.nombre}</td></tr>"""
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f9fafb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f9fafb;padding:40px 20px"><tr><td>
    <table width="560" cellpadding="0" cellspacing="0" align="center" style="background:#fff;border-radius:8px;border:1px solid #e5e7eb;overflow:hidden">
      <tr><td style="background:{ROJO};padding:24px 32px">
        <p style="margin:0;color:#fff;font-size:18px;font-weight:500">Caja sin cerrar</p>
        <p style="margin:4px 0 0;color:#fecaca;font-size:13px">Thames Seguros · {fecha_txt}</p>
      </td></tr>
      <tr><td style="padding:24px 32px">
        <p style="margin:0 0 16px;font-size:14px;color:#4b5563">
          Estas oficinas <strong>no cerraron la caja hoy</strong>:
        </p>
        <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e7eb;border-radius:6px;overflow:hidden;border-collapse:collapse">
          <tbody>{filas}</tbody>
        </table>
      </td></tr>
      <tr><td style="background:#f9fafb;padding:20px 32px;border-top:1px solid #e5e7eb">
        <p style="margin:0;font-size:12px;color:#9ca3af">Thames Seguros · Generado el {fecha_txt}</p>
      </td></tr>
    </table>
  </td></tr></table>
</body></html>"""


class Command(BaseCommand):
    help = "Avisa qué oficinas no cerraron la caja hoy (email + WhatsApp)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Muestra sin enviar.")

    def handle(self, *args, **options):
        dry = bool(options.get("dry_run"))
        hoy = timezone.localdate()
        fecha_txt = hoy.strftime("%d/%m/%Y")

        if SALTAR_DOMINGOS and hoy.weekday() == 6:
            self.stdout.write("Domingo: no se controla.")
            return

        oficinas = _oficinas_sin_cierre(hoy)

        if not oficinas:
            self.stdout.write(self.style.SUCCESS("✓ Todas las oficinas cerraron la caja."))
            return

        nombres = ", ".join(o.nombre for o in oficinas)
        self.stdout.write(self.style.WARNING(f"Sin cerrar: {nombres}"))

        if dry:
            self.stdout.write(_mensaje_whatsapp(oficinas, fecha_txt))
            self.stdout.write("\n[dry-run] No se envió nada.")
            return

        # Email
        if EMAILS_AVISO:
            try:
                em = EmailMessage(
                    subject=f"🚨 Caja sin cerrar — {fecha_txt} ({len(oficinas)})",
                    body=_email_html(oficinas, fecha_txt),
                    from_email=settings.DEFAULT_FROM_EMAIL, to=EMAILS_AVISO,
                )
                em.content_subtype = "html"
                em.send(fail_silently=False)
            except Exception as e:
                logger.error(f"[caja_no_cerrada] Email falló: {e}")

        # WhatsApp
        msg_wa = _mensaje_whatsapp(oficinas, fecha_txt)
        ofi_wa = _oficina_con_whatsapp()
        for numero in WHATSAPP_NUMEROS:
            try:
                ok, info = enviar_whatsapp(numero, msg_wa, oficina=ofi_wa)
                if not ok:
                    logger.error(f"[caja_no_cerrada] WhatsApp a {numero} no se envió: {info}")
            except Exception as e:
                logger.error(f"[caja_no_cerrada] WhatsApp a {numero} excepción: {e}")

        self.stdout.write(self.style.SUCCESS(f"✓ Aviso enviado ({len(oficinas)} oficinas)"))