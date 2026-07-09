# polizas/management/commands/relabel_companias.py
#
# Relabela el campo "compania" de los grupos EQUIDAD, de forma QUIRÚRGICA por COBERTURA:
#   - Cobertura "A"        -> "NRE"      (A es de NRE)
#   - Cualquier otra cob   -> "Equidad"  (Equidad de verdad, unificado)
#
# Se aplica a estos grupos mal etiquetados:
GRUPOS = ["EQUIDAD SEGUROS", "Equidad", "EQUIDAD"]
#
# USO:
#   python manage.py relabel_companias              # SIMULACIÓN (no toca nada)
#   python manage.py relabel_companias --aplicar    # aplica los cambios
#
# Ruta: polizas/management/commands/relabel_companias.py

from django.core.management.base import BaseCommand

from polizas.models import Poliza


def _es_cobertura_a(cob) -> bool:
    """True si la cobertura es 'A' (ignora mayúsculas y espacios). Ojo: 'A+GRUA' NO es 'A'."""
    return (str(cob or "").strip().upper()) == "A"


class Command(BaseCommand):
    help = "Relabela EQUIDAD/EQUIDAD SEGUROS: cobertura A → NRE, el resto → Equidad. SIMULA salvo --aplicar."

    def add_arguments(self, parser):
        parser.add_argument("--aplicar", action="store_true",
                            help="Aplica los cambios. Sin esto es SOLO simulación.")

    def handle(self, *args, **opts):
        aplicar = bool(opts.get("aplicar"))
        modo = "APLICANDO CAMBIOS" if aplicar else "SIMULACIÓN (no toca nada)"
        self.stdout.write(self.style.WARNING(f"\n[relabel_companias] {modo}\n"))

        a_nre = []       # ids → NRE
        a_equidad = []   # ids → Equidad
        ej_nre, ej_eq = [], []

        qs = Poliza.objects.filter(compania__in=GRUPOS).only("id", "compania", "cobertura", "patente")
        for p in qs.iterator():
            destino = "NRE" if _es_cobertura_a(p.cobertura) else "Equidad"
            if p.compania == destino:
                continue  # ya está bien
            if destino == "NRE":
                a_nre.append(p.id)
                if len(ej_nre) < 6:
                    ej_nre.append(f"{p.patente or '—'} (cob {p.cobertura or '—'})")
            else:
                a_equidad.append(p.id)
                if len(ej_eq) < 6:
                    ej_eq.append(f"{p.patente or '—'} (cob {p.cobertura or '—'})")

        self.stdout.write(f"  Cobertura A → 'NRE':     {len(a_nre)} pólizas   ej: {', '.join(ej_nre)}")
        self.stdout.write(f"  Otras cob   → 'Equidad': {len(a_equidad)} pólizas   ej: {', '.join(ej_eq)}")

        if aplicar:
            if a_nre:
                Poliza.objects.filter(id__in=a_nre).update(compania="NRE")
            if a_equidad:
                Poliza.objects.filter(id__in=a_equidad).update(compania="Equidad")

        self.stdout.write(self.style.SUCCESS(
            f"\n  Total relabeladas: {len(a_nre) + len(a_equidad)} "
            f"(→NRE: {len(a_nre)} · →Equidad: {len(a_equidad)})"
        ))
        if not aplicar:
            self.stdout.write(self.style.WARNING(
                "  ⚠️  Fue SIMULACIÓN. Revisá y, si está bien, corré con --aplicar.\n"
            ))
        else:
            self.stdout.write(self.style.SUCCESS("  ✓ Cambios guardados.\n"))