# polizas/management/commands/sync_estados.py
#
# Estructura de carpetas necesaria (si no existe):
#   polizas/
#     management/
#       __init__.py       ← archivo vacío
#       commands/
#         __init__.py     ← archivo vacío
#         sync_estados.py ← este archivo
#
# USO:
#   python manage.py sync_estados
#   python manage.py sync_estados --dias 45
#   python manage.py sync_estados --oficina 1
#
# RAILWAY CRON — agregar en railway.toml:
#   [cron]
#   schedule = "0 6 * * *"
#   command   = "python manage.py sync_estados"

from django.core.management.base import BaseCommand

from polizas.views.poliza import sincronizar_estados_polizas


class Command(BaseCommand):
    help = (
        "Sincroniza el estado de todas las pólizas según la realidad de sus cuotas. "
        "Marca como 'vencida' las que superan el umbral de mora crítica, "
        "y reactiva a 'activa' las que ya no tienen deuda."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dias",
            type=int,
            default=60,
            help=(
                "Días de mora para marcar una póliza como 'vencida' (default: 60). "
                "Pólizas con mora entre 1 y este valor siguen 'activas' "
                "pero el front las muestra con badge de mora."
            ),
        )
        parser.add_argument(
            "--oficina",
            type=int,
            default=None,
            help="Filtrar por ID de oficina. Sin este parámetro procesa todas.",
        )

    def handle(self, *args, **options):
        dias    = options["dias"]
        oficina = options["oficina"]

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\n[sync_estados] Sincronizando estados"
                f" · mora crítica ≥ {dias} días"
                + (f" · oficina_id={oficina}" if oficina else " · todas las oficinas")
                + "\n"
            )
        )

        resultado = sincronizar_estados_polizas(
            dias_mora_critica=dias,
            oficina_id=oficina,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"  ✓ Marcadas como vencidas:  {resultado['marcadas_vencidas']}"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"  ✓ Reactivadas a activas:   {resultado['reactivadas']}"
            )
        )
        self.stdout.write(
            f"\n  Fecha: {resultado['fecha']} "
            f"· días mora crítica: {resultado['dias_mora_critica']}\n"
        )