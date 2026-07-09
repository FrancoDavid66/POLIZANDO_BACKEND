# pagos/signals.py
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from pagos.models import Cuota

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Cuota)
def cuota_pagada__sincronizar_estado_poliza(sender, instance, created, **kwargs):
    """
    Cuando se guarda una Cuota con pagado=True, sincroniza el estado
    de la póliza asociada.

    Reglas:
      - Si la cuota no está pagada → no hace nada.
      - Si la póliza está en estado terminal (cancelada, finalizada) → no toca nada.
      - Si la póliza está en_verificacion → no toca nada (lo gestiona registrar_pago).
      - Si la póliza está vencida y ya no tiene cuotas vencidas sin pagar
        y no tiene una BajaPoliza activa → la reactiva a 'activa'.
    """
    if not getattr(instance, "pagado", False):
        return

    poliza = getattr(instance, "poliza", None)
    if not poliza:
        return

    estado_actual = str(getattr(poliza, "estado", "")).strip().lower()

    if estado_actual in ("cancelada", "finalizada", "en_verificacion"):
        return

    if estado_actual != "vencida":
        return

    try:
        from bajas.models import BajaPoliza

        hoy = timezone.localdate()

        hay_vencidas = poliza.cuotas.filter(
            pagado=False,
            fecha_vencimiento__lt=hoy,
        ).exists()

        if hay_vencidas:
            return

        tiene_baja = BajaPoliza.objects.filter(
            poliza=poliza,
            estado__in=[BajaPoliza.Estado.PENDIENTE_ENVIO, BajaPoliza.Estado.ENVIADA],
        ).exists()

        if tiene_baja:
            logger.info(
                f"[cuota_signal] Póliza {poliza.id}: sin mora pero tiene BajaPoliza activa. "
                f"No se reactiva automáticamente."
            )
            return

        poliza.estado = "activa"
        poliza.save(update_fields=["estado"])
        logger.info(
            f"[cuota_signal] Póliza {poliza.id} reactivada a 'activa' "
            f"tras pago de cuota #{instance.cuota_nro}."
        )

    except Exception as exc:
        logger.error(
            f"[cuota_signal] Error sincronizando estado póliza "
            f"{getattr(poliza, 'id', '?')}: {exc}"
        )