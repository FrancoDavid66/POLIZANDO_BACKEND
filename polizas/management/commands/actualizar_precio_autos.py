# polizas/management/commands/actualizar_precios_nre.py
# ──────────────────────────────────────────────────────────────────────────
# Sube las CUOTAS IMPAGAS de las pólizas NRE al PRECIO VIGENTE de hoy, para
# TODOS los tipos (auto, moto, camioneta, camión, trailer).
#
# - Solo compañía NRE, pólizas ACTIVAS o VENCIDAS.
# - Usa precio_vigente(tipo, hoy, oficina), que ya respeta El Talita
#   (auto de El Talita → su propio precio, no el de las oficinas normales).
# - Solo cuotas IMPAGAS que estén POR DEBAJO del vigente (incluye las que
#   están en $0). Las que ya están en el vigente o más NO se tocan.
# - Las cuotas PAGADAS nunca se tocan.
# - NUNCA baja una cuota (solo iguala hacia arriba).
#
# Uso:
#   python manage.py actualizar_precios_nre            → SIMULA (no escribe)
#   python manage.py actualizar_precios_nre --aplicar  → aplica los cambios
# ──────────────────────────────────────────────────────────────────────────
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from polizas.models import Poliza
from pagos.models import Cuota
from polizas.precios_nre import es_nre, precio_vigente, es_talita, _norm_tipo


def _money(n):
    try:
        return "$" + format(int(n), ",d").replace(",", ".")
    except Exception:
        return f"${n}"


class Command(BaseCommand):
    help = ("Sube las cuotas impagas de las pólizas NRE al precio vigente de hoy "
            "(todos los tipos). Por defecto SIMULA; usá --aplicar para escribir.")

    def add_arguments(self, parser):
        parser.add_argument(
            "--aplicar", action="store_true", default=False,
            help="Aplica los cambios. Sin esto, solo simula.",
        )

    def handle(self, *args, **opts):
        aplicar = opts["aplicar"]
        hoy = date.today()
        modo = "APLICANDO CAMBIOS" if aplicar else "SIMULACIÓN (no se escribe nada)"
        self.stdout.write(self.style.WARNING(f"\n=== Actualizar precios NRE — {modo} ===\n"))

        polizas_qs = Poliza.objects.filter(
            Q(estado__iexact="activa") | Q(estado__iexact="vencida"),
            compania__icontains="nre",
        ).order_by("id")

        total_pol = 0
        total_cuo = 0
        por_tipo = {}        # label -> [polizas, cuotas, precio]
        ejemplos = []

        for p in polizas_qs.iterator():
            if not es_nre(getattr(p, "compania", "")):
                continue

            ofi = getattr(p, "oficina", None)
            precio = precio_vigente(p.tipo, hoy, ofi)
            if not precio:
                continue

            # Impagas por debajo del vigente (incluye las que están en $0).
            impagas = Cuota.objects.filter(poliza=p, pagado=False).filter(
                Q(monto__isnull=True) | Q(monto__lt=precio)
            )
            n = impagas.count()
            if n == 0:
                continue

            total_pol += 1
            total_cuo += n

            # Etiqueta por tipo (separa el auto de El Talita para que se vea claro).
            tn = _norm_tipo(p.tipo) or str(p.tipo)
            label = f"{tn} (Talita)" if (tn == "Auto" and es_talita(ofi)) else tn
            fila = por_tipo.setdefault(label, [0, 0, precio])
            fila[0] += 1
            fila[1] += n
            fila[2] = precio

            if len(ejemplos) < 12:
                pat = getattr(p, "patente", "") or f"#{p.id}"
                ejemplos.append(f"  {pat} [{label}]: {n} cuota(s) → {_money(precio)}")

            if aplicar:
                with transaction.atomic():
                    impagas.update(monto=precio)

        # Reporte
        for e in ejemplos:
            self.stdout.write(e)
        if total_pol > 12:
            self.stdout.write(f"  ... y {total_pol - 12} póliza(s) más")

        self.stdout.write(self.style.MIGRATE_HEADING("\n--- Resumen por tipo ---"))
        for label in sorted(por_tipo):
            pol, cuo, precio = por_tipo[label]
            self.stdout.write(f"  {label:18} {pol:>4} pólizas · {cuo:>4} cuotas → {_money(precio)}")

        self.stdout.write(self.style.SUCCESS(
            f"\nTotal: {total_pol} póliza(s), {total_cuo} cuota(s) actualizadas."
        ))
        if not aplicar:
            self.stdout.write("\n  (SIMULACIÓN — no se escribió nada. Agregá --aplicar para aplicar.)\n")