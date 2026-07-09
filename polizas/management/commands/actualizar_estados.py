# polizas/management/commands/actualizar_estados.py
from django.core.management.base import BaseCommand
from django.db.models import Count, Max, Min, Q
from django.utils import timezone

from polizas.models import Poliza


class Command(BaseCommand):
    help = (
        'Actualiza el estado de las pólizas según la cobertura REAL. '
        'Las cuotas se pagan por adelantado: la cobertura llega hasta el vto de '
        'la ÚLTIMA cuota PAGADA. Si esa cobertura ya venció y quedan cuotas '
        'impagas => "vencida". Si una póliza vencida volvió a quedar cubierta => "activa".'
    )

    def handle(self, *args, **kwargs):
        hoy = timezone.localdate()
        self.stdout.write(self.style.WARNING(f"[{hoy}] Escaneando pólizas por cobertura real..."))

        # Anotamos, por póliza:
        #   cobertura_hasta   = hasta cuándo está cubierta = vto de la ÚLTIMA cuota PAGADA
        #   impagas           = cantidad de cuotas sin pagar
        #   primer_vto_impaga = vto más viejo entre las impagas (para pólizas que nunca arrancaron)
        base = Poliza.objects.annotate(
            cobertura_hasta=Max("cuotas__fecha_vencimiento", filter=Q(cuotas__pagado=True)),
            impagas=Count("cuotas", filter=Q(cuotas__pagado=False)),
            primer_vto_impaga=Min("cuotas__fecha_vencimiento", filter=Q(cuotas__pagado=False)),
        )

        # ── 1) ACTIVAS descubiertas HOY -> VENCIDA ────────────────────────
        # Está descubierta hoy si:
        #   a) pagó algo y esa cobertura ya venció (cobertura_hasta < hoy), o
        #   b) nunca pagó nada y el vto de su primera cuota ya pasó (nunca arrancó).
        ids_vencer = list(
            base.filter(estado__iexact="activa", impagas__gt=0)
            .filter(
                Q(cobertura_hasta__lt=hoy)
                | Q(cobertura_hasta__isnull=True, primer_vto_impaga__lt=hoy)
            )
            .values_list("id", flat=True)
        )
        if ids_vencer:
            Poliza.objects.filter(id__in=ids_vencer).update(estado="vencida")
            self.stdout.write(self.style.SUCCESS(f"{len(ids_vencer)} pólizas pasaron a VENCIDA."))
        else:
            self.stdout.write(self.style.SUCCESS("No hay pólizas activas con la cobertura vencida."))

        # ── 2) VENCIDAS que volvieron a estar al día -> ACTIVA ────────────
        # (Le pagaron la cuota que faltaba: la cobertura vuelve a llegar hasta hoy o más.)
        # Si no querés que reactive solo, borrá este bloque.
        ids_reactivar = list(
            base.filter(estado__iexact="vencida", impagas__gt=0, cobertura_hasta__gte=hoy)
            .values_list("id", flat=True)
        )
        if ids_reactivar:
            Poliza.objects.filter(id__in=ids_reactivar).update(estado="activa")
            self.stdout.write(self.style.SUCCESS(f"{len(ids_reactivar)} pólizas volvieron a ACTIVA (al día)."))