# tareas/management/commands/reporte_tareas.py
from django.core.management.base import BaseCommand

from tareas.reporte import enviar_reporte_tareas


class Command(BaseCommand):
    help = "Envía el reporte diario de tareas por oficina (email + WhatsApp)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Muestra el reporte sin enviarlo.")

    def handle(self, *args, **options):
        enviar_reporte_tareas(dry_run=options.get("dry_run", False))
        self.stdout.write(self.style.SUCCESS("Reporte de tareas procesado."))