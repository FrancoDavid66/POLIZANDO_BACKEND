from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

from solicitudes.models import SolicitudSeguro


class Command(BaseCommand):
    help = "Elimina solicitudes TERMINADAS con terminada_en < now - days (default 7)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=7)

    def handle(self, *args, **opts):
        days = int(opts["days"] or 7)
        cutoff = timezone.now() - timedelta(days=days)

        qs = SolicitudSeguro.objects.filter(
            estado="TERMINADA",
            terminada_en__isnull=False,
            terminada_en__lt=cutoff,
        )

        count = qs.count()
        qs.delete()

        self.stdout.write(self.style.SUCCESS(f"OK: eliminadas {count} TERMINADAS (> {days} días)."))
