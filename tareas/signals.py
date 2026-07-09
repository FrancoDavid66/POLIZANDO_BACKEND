# tareas/signals.py
#
# Cuando una cuota PASA a pagada, la póliza queda marcada como "pendiente de
# enviar" (poliza_enviada=False) → aparece sola en el panel "Enviar póliza".
# El empleado la marca como enviada cuando se la manda al cliente.
#
# Escuchamos el modelo Cuota desde acá para no tener que tocar la app `pagos`.

from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from pagos.models import Cuota
from polizas.models import Poliza


@receiver(pre_save, sender=Cuota)
def _guardar_estado_previo(sender, instance, **kwargs):
    """Antes de guardar, recordamos si la cuota YA estaba pagada."""
    if not instance.pk:
        instance._era_pagada = False
        return
    try:
        instance._era_pagada = bool(
            sender.objects.filter(pk=instance.pk).values_list("pagado", flat=True).first()
        )
    except Exception:
        instance._era_pagada = False


@receiver(post_save, sender=Cuota)
def _marcar_poliza_para_enviar(sender, instance, created, **kwargs):
    """Si la cuota pasó de NO pagada a pagada, la póliza necesita reenvío."""
    paso_a_pagada = instance.pagado and not getattr(instance, "_era_pagada", False)
    if paso_a_pagada and instance.poliza_id:
        # .update() no vuelve a disparar señales → evita loops.
        Poliza.objects.filter(pk=instance.poliza_id).update(poliza_enviada=False)