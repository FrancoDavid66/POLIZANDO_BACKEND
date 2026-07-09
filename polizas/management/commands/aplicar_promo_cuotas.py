# pagos/management/commands/aplicar_promo_cuotas.py
"""
Aplica un precio promocional a las primeras N cuotas IMPAGAS de una poliza,
buscada por patente.

Uso (primero SIN --confirmar, para ver que va a cambiar sin tocar nada):
    python manage.py aplicar_promo_cuotas SBB971
    python manage.py aplicar_promo_cuotas SBB971 --monto 25000 --cantidad 3 --confirmar
"""
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from polizas.models import Poliza
from pagos.models import Cuota


class Command(BaseCommand):
    help = "Aplica un monto promocional a las primeras N cuotas impagas de una poliza (por patente)."

    def add_arguments(self, parser):
        parser.add_argument("patente", type=str, help="Patente de la poliza (ej: SBB971)")
        parser.add_argument("--monto", type=str, default="25000", help="Monto promocional por cuota (default: 25000)")
        parser.add_argument("--cantidad", type=int, default=3, help="Cantidad de cuotas a modificar (default: 3)")
        parser.add_argument(
            "--confirmar", action="store_true",
            help="Sin esta bandera solo se MUESTRA el cambio (dry-run), no se guarda nada.",
        )

    def handle(self, *args, **options):
        patente = options["patente"].strip().upper()
        cantidad = options["cantidad"]
        confirmar = options["confirmar"]

        try:
            monto_nuevo = Decimal(str(options["monto"]))
        except (InvalidOperation, TypeError, ValueError):
            raise CommandError(f"Monto invalido: {options['monto']!r}")

        if monto_nuevo <= 0:
            raise CommandError("El monto tiene que ser mayor a 0.")
        if cantidad <= 0:
            raise CommandError("La cantidad de cuotas tiene que ser mayor a 0.")

        # ── Buscar la poliza activa por patente ──────────────────────────
        polizas = list(
            Poliza.objects.filter(patente__iexact=patente)
            .exclude(estado__in=["cancelada", "finalizada"])
        )

        if not polizas:
            raise CommandError(
                f'No encontre ninguna poliza ACTIVA con patente "{patente}". '
                f"(Se excluyen canceladas y finalizadas; si buscabas una de esas, avisame y lo ajusto.)"
            )

        if len(polizas) > 1:
            self.stdout.write(self.style.ERROR(
                f'Encontre {len(polizas)} polizas activas con patente "{patente}" — '
                f"no puedo elegir sola. Corre el comando de nuevo indicando cual por ID:"
            ))
            for p in polizas:
                cli = getattr(p, "cliente", None)
                nombre_cli = getattr(cli, "nombre_completo", None) or getattr(cli, "id", "-")
                self.stdout.write(
                    f"  - ID {p.id} | {p.compania or '(sin compania)'} | estado={p.estado} | cliente={nombre_cli}"
                )
            return

        poliza = polizas[0]

        # ── Cuotas impagas, en orden, las primeras N ─────────────────────
        cuotas = list(
            Cuota.objects.filter(poliza=poliza, pagado=False)
            .order_by("cuota_nro")[:cantidad]
        )

        if not cuotas:
            raise CommandError(f"La poliza {poliza.id} (patente {patente}) no tiene cuotas impagas.")

        if len(cuotas) < cantidad:
            self.stdout.write(self.style.WARNING(
                f"Ojo: pedidas {cantidad} cuotas, pero solo hay {len(cuotas)} impagas. Sigo con esas."
            ))

        # ── Aviso si alguna ya tiene comision de vendedor generada ────────
        con_comision = [c for c in cuotas if getattr(c, "comision_generada", None) is not None]
        if con_comision:
            nros = ", ".join(str(c.cuota_nro) for c in con_comision)
            self.stdout.write(self.style.WARNING(
                f"Ojo: las cuotas {nros} ya tienen una comision de vendedor generada. "
                f"Cambiarles el monto aca NO actualiza esa comision — revisala a mano si hace falta."
            ))

        # ── Mostrar el cambio ─────────────────────────────────────────────
        cli = getattr(poliza, "cliente", None)
        nombre_cli = getattr(cli, "nombre_completo", None) or getattr(cli, "id", "-")
        self.stdout.write(self.style.SUCCESS(
            f"\nPoliza {poliza.id} | patente {patente} | compania {poliza.compania or '-'} | cliente {nombre_cli}\n"
        ))
        self.stdout.write(f"{'Cuota':<8}{'Vencimiento':<14}{'Monto actual':<16}{'Monto nuevo':<14}")
        for c in cuotas:
            self.stdout.write(
                f"{c.cuota_nro:<8}{c.fecha_vencimiento.strftime('%d/%m/%Y'):<14}"
                f"${c.monto:<15}${monto_nuevo}"
            )

        if not confirmar:
            self.stdout.write(self.style.WARNING(
                "\nEsto fue solo una vista previa (dry-run) — no se guardo nada. "
                "Corre el mismo comando agregando --confirmar para aplicar el cambio."
            ))
            return

        with transaction.atomic():
            for c in cuotas:
                c.monto = monto_nuevo
                c.save(update_fields=["monto"])

        self.stdout.write(self.style.SUCCESS(
            f"\nListo — {len(cuotas)} cuota(s) de la poliza {poliza.id} quedaron en ${monto_nuevo}."
        ))
        self.stdout.write(self.style.WARNING(
            "Recordatorio: cuando esta poliza se renueve, la poliza NUEVA no hereda este precio "
            "promocional solo — hay que cobrarle $36.000 a mano en ese momento."
        ))