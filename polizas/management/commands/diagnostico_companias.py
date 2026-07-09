# polizas/management/commands/diagnostico_companias.py
#
# 🔍 SOLO LECTURA — NO MODIFICA NADA.
# Lista los valores EXACTOS del campo "compania" de las pólizas y cuántas hay de cada uno,
# con patentes de ejemplo. Sirve para ver qué nombres quedaron mal guardados
# (ej: NRE guardadas como "EQUIDAD SEGUROS").
#
# USO:
#   python manage.py diagnostico_companias
#
# Ruta: polizas/management/commands/diagnostico_companias.py

from django.core.management.base import BaseCommand
from django.db.models import Count

from polizas.models import Poliza


class Command(BaseCommand):
    help = "Muestra los valores exactos del campo compañía y cuántas pólizas tiene cada uno. Solo lee."

    def handle(self, *args, **opts):
        self.stdout.write(self.style.WARNING("\n[diagnostico_companias] SOLO LECTURA\n"))

        filas = (
            Poliza.objects.values("compania")
            .annotate(n=Count("id"))
            .order_by("-n")
        )

        total = 0
        for f in filas:
            comp = f["compania"]
            n = f["n"]
            total += n
            ejemplos = list(
                Poliza.objects.filter(compania=comp)
                .exclude(patente__isnull=True).exclude(patente__exact="")
                .values_list("patente", flat=True)[:5]
            )
            comp_show = repr(comp) if comp not in (None, "") else "(vacío)"
            self.stdout.write(
                f"  {comp_show:<32} → {n:>4} pólizas   ej: {', '.join(ejemplos)}"
            )

        self.stdout.write(self.style.SUCCESS(
            f"\n  Total de pólizas: {total} · valores distintos: {len(filas)}"
        ))
        self.stdout.write(self.style.SUCCESS("  ✓ Fin (no se modificó nada).\n"))