# bajas/management/commands/sync_bajas.py
#
# Estructura de carpetas necesaria:
#   bajas/
#     management/
#       __init__.py       ← archivo vacío
#       commands/
#         __init__.py     ← archivo vacío
#         sync_bajas.py   ← este archivo
#
# USO:
#   python manage.py sync_bajas
#   python manage.py sync_bajas --dias 5
#   python manage.py sync_bajas --oficina 1
#   python manage.py sync_bajas --enviar
#
# RAILWAY CRON:
#   schedule = "0 8 * * 1-5"
#   command  = "python manage.py sync_bajas"

from django.core.management.base import BaseCommand

from bajas.services import crear_bajas_pendientes, enviar_todas_del_dia


class Command(BaseCommand):
    help = "Detecta pólizas en mora, crea BajaPoliza y opcionalmente envía emails a las compañías."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dias",
            type=int,
            default=3,
            help="Mora mínima en días (default: 3). Usa los dias_gracia de cada compañía si están configurados.",
        )
        parser.add_argument(
            "--oficina",
            type=int,
            default=None,
            help="Filtrar por ID de oficina. Sin este parámetro procesa todas las oficinas.",
        )
        parser.add_argument(
            "--enviar",
            action="store_true",
            default=False,
            help="Si se incluye, también envía los emails a las compañías después de crear los registros.",
        )

    def handle(self, *args, **options):
        dias    = options["dias"]
        oficina = options["oficina"]
        enviar  = options["enviar"]

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\n[sync_bajas] Procesando mora >= {dias} días"
                + (f" · oficina_id={oficina}" if oficina else " · todas las oficinas")
                + "\n"
            )
        )

        # Paso 1: crear registros BajaPoliza
        creadas = crear_bajas_pendientes(dias_default=dias, oficina_id=oficina)
        self.stdout.write(self.style.SUCCESS(f"  ✓ BajaPoliza nuevas creadas: {creadas}"))

        if not enviar:
            self.stdout.write(
                "\n  Tip: agregá --enviar para también mandar los emails a las compañías.\n"
            )
            return

        # Paso 2: enviar emails
        self.stdout.write(self.style.MIGRATE_HEADING("\n[sync_bajas] Enviando emails a las compañías...\n"))
        resultados = enviar_todas_del_dia(dias_default=dias, oficina_id=oficina)

        if not resultados:
            self.stdout.write("  Sin compañías pendientes de envío.\n")
            return

        for r in resultados:
            if r["ok"]:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  ✓ {r['compania']} → {r['email_destino']} ({r['polizas_count']} pólizas)"
                    )
                )
            else:
                self.stdout.write(
                    self.style.ERROR(
                        f"  ✗ {r['compania']} → ERROR: {r.get('error', 'desconocido')}"
                    )
                )

        ok_count  = sum(1 for r in resultados if r["ok"])
        err_count = len(resultados) - ok_count
        self.stdout.write(
            f"\n  Resumen: {ok_count} enviado(s) correctamente, {err_count} con error.\n"
        )