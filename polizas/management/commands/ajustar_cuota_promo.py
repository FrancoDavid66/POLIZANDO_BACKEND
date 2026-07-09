# polizas/management/commands/ajustar_cuota_promo.py
#
# Deja en un monto fijo las cuotas IMPAGAS de una patente (para respetar una promo).
# Por defecto SIMULA; usá --aplicar para guardar.
#
# USO (caso Rojas — AA870GR a $25.000):
#   python manage.py ajustar_cuota_promo --patente AA870GR --monto 25000
#   python manage.py ajustar_cuota_promo --patente AA870GR --monto 25000 --aplicar
#
# Ruta: polizas/management/commands/ajustar_cuota_promo.py

from decimal import Decimal

from django.core.management.base import BaseCommand

from polizas.models import Poliza
from pagos.models import Cuota


class Command(BaseCommand):
    help = "Fija el monto de las cuotas IMPAGAS de una patente. Por defecto SIMULA; usá --aplicar."

    def add_arguments(self, parser):
        parser.add_argument("--patente", type=str, required=True)
        parser.add_argument("--monto", type=str, required=True, help="Monto nuevo, ej: 25000")
        parser.add_argument("--aplicar", action="store_true",
                            help="Aplica los cambios. Sin esto es SOLO simulación.")

    def handle(self, *args, **opts):
        patente = (opts["patente"] or "").strip().upper()
        try:
            monto = Decimal(str(opts["monto"]))
        except Exception:
            self.stdout.write(self.style.ERROR("Monto inválido."))
            return
        aplicar = bool(opts.get("aplicar"))

        modo = "APLICANDO CAMBIOS" if aplicar else "SIMULACIÓN (no toca nada)"
        self.stdout.write(self.style.WARNING(
            f"\n[ajustar_cuota_promo] {modo} · patente {patente} · nuevo monto = ${monto}\n"
        ))

        polizas = Poliza.objects.filter(patente__iexact=patente)
        if not polizas.exists():
            self.stdout.write(self.style.ERROR("No hay pólizas con esa patente."))
            return

        tocadas = 0
        for pol in polizas.order_by("id"):
            # Solo cuotas IMPAGAS (nunca tocamos una pagada) de pólizas vivas.
            if pol.estado in ("cancelada", "finalizada"):
                continue
            cuotas = Cuota.objects.filter(poliza=pol, pagado=False).order_by("cuota_nro", "id")
            if not cuotas.exists():
                continue
            self.stdout.write(f"  Póliza {pol.numero_poliza or pol.id} · {pol.compania} · estado={pol.estado}")
            for c in cuotas:
                self.stdout.write(f"      Cuota {c.cuota_nro} (impaga): ${c.monto} → ${monto}")
                if aplicar:
                    c.monto = monto
                    c.save(update_fields=["monto"])
                tocadas += 1

        self.stdout.write(self.style.SUCCESS(f"\n  Cuotas ajustadas: {tocadas}"))
        if not aplicar:
            self.stdout.write(self.style.WARNING(
                "  ⚠️  Fue SIMULACIÓN. Revisá y, si está bien, corré con --aplicar.\n"
            ))
        else:
            self.stdout.write(self.style.SUCCESS("  ✓ Cambios guardados.\n"))