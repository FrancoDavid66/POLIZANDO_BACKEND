# notificaciones/management/commands/verificar_envio_recordatorios.py
#
# Monitoreo: verifica que el envío de recordatorios de las 9:00 se haya
# ejecutado hoy. Si NO corrió, manda un WhatsApp de alerta (vos + Damián).
#
# Se apoya en el modelo EnvioRecordatoriosCuotas, que el envío crea (una fila
# por fecha+oficina) cada vez que corre. Si hoy no hay ninguna fila → no corrió.
#
# Cron Railway recomendado (11:00 Argentina = 14:00 UTC, 2 h después del envío):
#   0 14 * * *

import os
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from notificaciones.models import EnvioRecordatoriosCuotas
from notificaciones.utils.mensajeria import enviar_whatsapp

logger = logging.getLogger(__name__)

# Solo Franco recibe la alerta de monitoreo (no Damián).
_WA_DEFAULT = "1164235336"
WHATSAPP_ALERTA = [n.strip() for n in os.environ.get("WHATSAPP_ALERTA_CRON", _WA_DEFAULT).split(",") if n.strip()]


def _oficina_emisora():
    """Primera oficina activa con credenciales (para poder mandar la alerta)."""
    from usuarios.models import Oficina
    o = (
        Oficina.objects.filter(activa=True)
        .exclude(ultramsg_instance_id__isnull=True).exclude(ultramsg_instance_id="")
        .exclude(ultramsg_token__isnull=True).exclude(ultramsg_token="")
        .order_by("id")
        .first()
    )
    return str(o.id) if o else None


class Command(BaseCommand):
    help = "Avisa por WhatsApp si el envío de recordatorios de las 9 no corrió hoy."

    def handle(self, *args, **opts):
        hoy = timezone.localdate()
        fecha_txt = hoy.strftime("%d/%m/%Y")

        corrio = EnvioRecordatoriosCuotas.objects.filter(fecha=hoy).exists()

        if corrio:
            self.stdout.write(self.style.SUCCESS(f"✓ El envío de recordatorios SÍ corrió hoy ({fecha_txt})."))
            return

        self.stdout.write(self.style.ERROR(f"⚠️ El envío de recordatorios NO corrió hoy ({fecha_txt}). Avisando..."))

        msg = (
            f"🚨 *ALERTA — Recordatorios*\n\n"
            f"El envío automático de recordatorios de las 9:00 *NO se ejecutó* hoy "
            f"({fecha_txt}).\n\n"
            f"Revisá el cron en Railway o corré el envío a mano."
        )

        ofi = _oficina_emisora()
        if not ofi:
            self.stdout.write(self.style.ERROR("No hay oficina con credenciales para mandar la alerta."))
            return

        for numero in WHATSAPP_ALERTA:
            try:
                ok, info = enviar_whatsapp(numero, msg, oficina=ofi)
                if ok:
                    self.stdout.write(self.style.SUCCESS(f"📲 Alerta enviada a {numero}"))
                else:
                    self.stdout.write(self.style.ERROR(f"📲 Alerta a {numero} no salió: {info}"))
            except Exception as e:
                logger.error(f"[verificar_recordatorios] WhatsApp a {numero}: {e}")