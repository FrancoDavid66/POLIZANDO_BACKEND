# recaudacion/management/commands/alerta_cierre_mediodia.py
#
# Vigilante del CIERRE DE MEDIODÍA. Corre ~15:15 (un rato después de las 15:00)
# y revisa qué oficinas todavía NO cerraron la caja del turno "mediodia".
# Avisa por EMAIL + WhatsApp a los responsables (los 2 de siempre).
#
# Cron en Railway:
#     CRON_COMMAND = alerta_cierre_mediodia
#     Horario      = 15 18 * * *   (18:15 UTC = 15:15 Argentina)
#
import os

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand
from django.utils import timezone

from usuarios.models import Oficina
from recaudacion.models import CierreCaja, HorarioCierreCaja


# Los 2 emails y 2 números de siempre (overrideables por env).
EMAILS = [e.strip() for e in os.environ.get(
    "EMAIL_CIERRE_CAJA",
    "francodavid_dev@outlook.com,gomezdamianricardo284@gmail.com",
).split(",") if e.strip()]

WHATSAPP = [n.strip() for n in os.environ.get(
    "WHATSAPP_CIERRE_CAJA", "1164235336,1161332173",
).split(",") if n.strip()]

# No controlamos los domingos.
SALTAR_DOMINGOS = True


def _oficina_con_whatsapp():
    try:
        ofi = (
            Oficina.objects.filter(activa=True)
            .exclude(ultramsg_instance_id__isnull=True).exclude(ultramsg_instance_id="")
            .exclude(ultramsg_token__isnull=True).exclude(ultramsg_token="")
            .order_by("id").first()
        )
        return ofi.id if ofi else None
    except Exception:
        return None


def _enviar_email(oficinas_faltan, fecha_txt):
    if not EMAILS:
        return
    items = "".join(f"<li style='margin:2px 0'>🔴 {n}</li>" for n in oficinas_faltan)
    html = f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:24px;background:#f9fafb;font-family:-apple-system,Segoe UI,sans-serif">
  <table width="520" cellpadding="0" cellspacing="0" align="center" style="background:#fff;border-radius:8px;border:1px solid #e5e7eb;overflow:hidden">
    <tr><td style="background:#b45309;padding:18px 24px">
      <p style="margin:0;color:#fff;font-size:16px;font-weight:600">⚠️ Cierre de mediodía pendiente</p>
    </td></tr>
    <tr><td style="padding:18px 24px">
      <p style="margin:0 0 10px;font-size:14px;color:#374151">Estas oficinas todavía NO cerraron la caja del mediodía ({fecha_txt}):</p>
      <ul style="margin:0;padding:0 0 0 18px;color:#111827;font-size:14px">{items}</ul>
    </td></tr>
  </table>
</body></html>"""
    try:
        em = EmailMessage(
            subject=f"⚠️ Cierre de mediodía pendiente ({fecha_txt})",
            body=html, from_email=settings.DEFAULT_FROM_EMAIL, to=EMAILS,
        )
        em.content_subtype = "html"
        em.send(fail_silently=True)
    except Exception:
        pass


def _enviar_whatsapp(oficinas_faltan, fecha_txt):
    if not WHATSAPP:
        return
    try:
        from notificaciones.utils.mensajeria import enviar_whatsapp
    except Exception:
        return
    lista = "\n".join(f"🔴 {n}" for n in oficinas_faltan)
    msg = (
        f"⚠️ *Cierre de mediodía pendiente* ({fecha_txt})\n"
        f"Estas oficinas todavía no cerraron:\n{lista}"
    )
    ofi_wa = _oficina_con_whatsapp()
    for numero in WHATSAPP:
        try:
            enviar_whatsapp(numero, msg, oficina=ofi_wa)
        except Exception:
            pass


class Command(BaseCommand):
    help = "Avisa por email + WhatsApp las oficinas que no cerraron la caja del mediodía."

    def handle(self, *args, **options):
        hoy = timezone.localdate()

        if SALTAR_DOMINGOS and hoy.weekday() == 6:
            self.stdout.write("Domingo: no se controla.")
            return

        # Oficinas que tienen configurado un horario de mediodía (activo).
        horarios = HorarioCierreCaja.objects.filter(
            activo=True, mediodia__isnull=False
        ).select_related("oficina")

        if not horarios:
            self.stdout.write("Ninguna oficina tiene cierre de mediodía configurado.")
            return

        # Turnos "mediodia" ya cerrados hoy.
        cerraron_ids = set(
            CierreCaja.objects
            .filter(creado_en__date=hoy, turno="mediodia")
            .values_list("oficina_id", flat=True)
        )

        faltan = []
        for h in horarios:
            ofi = h.oficina
            if not ofi or not getattr(ofi, "activa", True):
                continue
            if ofi.id not in cerraron_ids:
                faltan.append(ofi.nombre)

        if not faltan:
            self.stdout.write(self.style.SUCCESS("✓ Todas cerraron la caja del mediodía."))
            return

        fecha_txt = hoy.strftime("%d/%m/%Y")
        _enviar_email(faltan, fecha_txt)
        _enviar_whatsapp(faltan, fecha_txt)
        self.stdout.write(self.style.WARNING(f"⚠ Avisé. Faltan: {', '.join(faltan)}"))