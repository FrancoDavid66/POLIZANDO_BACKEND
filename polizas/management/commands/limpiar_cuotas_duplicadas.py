# polizas/management/commands/limpiar_cuotas_duplicadas.py
#
# Limpia CUOTAS DUPLICADAS: cuando una póliza tiene el mismo cuota_nro repetido
# (ej. dos "Cuota 2"), deja UNA sola y borra la repetida.
#
# SEGURIDAD:
#   - Si una de las repetidas está PAGADA, se conserva ESA (nunca se borra un pago).
#   - Si ninguna está pagada, se conserva la más vieja (menor id) y se borra el resto.
#   - Si hay 2+ repetidas PAGADAS (raro), NO toca esa póliza y la lista para revisar.
#
# USO:
#   python manage.py limpiar_cuotas_duplicadas              # SIMULACIÓN (no toca nada)
#   python manage.py limpiar_cuotas_duplicadas --aplicar    # borra las repetidas
#   python manage.py limpiar_cuotas_duplicadas --oficina 5  # solo una sucursal
#
# Ruta: polizas/management/commands/limpiar_cuotas_duplicadas.py

from collections import defaultdict

from django.core.management.base import BaseCommand

from polizas.models import Poliza
from pagos.models import Cuota

ESTADOS_EXCLUIDOS = ["cancelada", "finalizada"]


class Command(BaseCommand):
    help = (
        "Borra cuotas duplicadas (mismo cuota_nro repetido en una póliza). "
        "Conserva la pagada o la más vieja. Por defecto SIMULA; usá --aplicar."
    )

    def add_arguments(self, parser):
        parser.add_argument("--aplicar", action="store_true",
                            help="Aplica los borrados. Sin esto es SOLO simulación.")
        parser.add_argument("--oficina", type=int, default=None,
                            help="Filtrar por ID de oficina.")

    def handle(self, *args, **opts):
        aplicar = bool(opts.get("aplicar"))
        oficina = opts.get("oficina")

        qs = Poliza.objects.exclude(estado__in=ESTADOS_EXCLUIDOS)
        if oficina:
            qs = qs.filter(oficina_id=oficina)

        modo = "APLICANDO CAMBIOS" if aplicar else "SIMULACIÓN (no toca nada)"
        self.stdout.write(self.style.WARNING(
            f"\n[limpiar_cuotas_duplicadas] {modo}"
            + (f" · oficina_id={oficina}" if oficina else " · todas las oficinas")
            + "\n"
        ))

        polizas_tocadas = 0
        cuotas_borradas = 0
        para_revisar = []   # pólizas con 2+ pagadas duplicadas

        for pol in qs.iterator():
            cuotas = list(Cuota.objects.filter(poliza=pol).order_by("cuota_nro", "id"))
            if not cuotas:
                continue

            grupos = defaultdict(list)
            for c in cuotas:
                grupos[c.cuota_nro].append(c)

            duplicados = {nro: lista for nro, lista in grupos.items() if len(lista) > 1}
            if not duplicados:
                continue

            patente = (pol.patente or "SIN PATENTE").upper()
            a_borrar = []
            conflicto = False

            for nro, lista in sorted(duplicados.items()):
                pagadas = [c for c in lista if c.pagado]
                if len(pagadas) > 1:
                    conflicto = True  # 2+ pagadas iguales → no tocar, revisar a mano
                    break
                keep = pagadas[0] if pagadas else min(lista, key=lambda c: c.id)
                for c in lista:
                    if c.id != keep.id and not c.pagado:
                        a_borrar.append((nro, c))

            if conflicto:
                para_revisar.append(patente)
                continue
            if not a_borrar:
                continue

            polizas_tocadas += 1
            cli = getattr(pol, "cliente", None)
            nombre = "—"
            if cli:
                nombre = f"{getattr(cli, 'apellido', '') or ''}, {getattr(cli, 'nombre', '') or ''}".strip(", ")
            self.stdout.write(f"  • PATENTE {patente} · {nombre} · {pol.numero_poliza or pol.id}")
            for nro, c in a_borrar:
                self.stdout.write(
                    f"      Borrar Cuota {nro} repetida (id {c.id}, vto {c.fecha_vencimiento}, impaga)"
                )
                if aplicar:
                    c.delete()
                cuotas_borradas += 1

        self.stdout.write(self.style.SUCCESS(
            f"\n  Pólizas tocadas: {polizas_tocadas} · cuotas borradas: {cuotas_borradas}"
        ))
        if para_revisar:
            self.stdout.write(self.style.WARNING(
                f"\n  ⚠️  {len(para_revisar)} pólizas con 2+ cuotas PAGADAS duplicadas (revisar a mano):"
            ))
            self.stdout.write("    " + ", ".join(para_revisar))
        if not aplicar:
            self.stdout.write(self.style.WARNING(
                "\n  ⚠️  Fue SIMULACIÓN. Revisá y, si está bien, corré con --aplicar.\n"
            ))
        else:
            self.stdout.write(self.style.SUCCESS("\n  ✓ Duplicadas borradas.\n"))