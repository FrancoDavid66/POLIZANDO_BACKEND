# polizas/management/commands/diagnostico_equidad.py
#
# 🔍 SOLO LECTURA — NO MODIFICA NADA.
# Compara los 3 grupos ("EQUIDAD SEGUROS", "Equidad", "EQUIDAD") para decidir
# cuáles son NRE y cuáles Equidad de verdad. Muestra, por grupo:
#   - cobertura, número de póliza, precio de cuota, cantidad de cuotas
#   - si el número tiene formato "SN-..." (alta rápida NRE) o no
#   - ejemplos concretos con patente
#
# USO:
#   python manage.py diagnostico_equidad
#
# Ruta: polizas/management/commands/diagnostico_equidad.py

from collections import Counter

from django.core.management.base import BaseCommand

from polizas.models import Poliza
from pagos.models import Cuota

GRUPOS = ["EQUIDAD SEGUROS", "Equidad", "EQUIDAD"]


class Command(BaseCommand):
    help = "Compara los grupos EQUIDAD SEGUROS / Equidad / EQUIDAD. Solo lee."

    def handle(self, *args, **opts):
        self.stdout.write(self.style.WARNING("\n[diagnostico_equidad] SOLO LECTURA\n"))

        for g in GRUPOS:
            qs = Poliza.objects.filter(compania=g).select_related("cliente")
            n = qs.count()
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n═══ '{g}' → {n} pólizas ═══"))
            if n == 0:
                continue

            # Coberturas más comunes
            cobs = Counter(str(p.cobertura or "—").strip().upper() for p in qs)
            self.stdout.write("  Coberturas: " + ", ".join(f"{c}×{k}" for c, k in cobs.most_common(6)))

            # ¿Cuántas tienen número tipo "SN-" (alta rápida) vs número real?
            con_sn = qs.filter(numero_poliza__istartswith="SN-").count()
            self.stdout.write(f"  Números 'SN-...' (alta rápida): {con_sn} de {n}")

            # Precio de cuota típico (primera cuota de cada una)
            precios = Counter()
            for p in qs[:200]:
                c1 = Cuota.objects.filter(poliza=p).order_by("cuota_nro", "id").first()
                if c1 and c1.monto:
                    precios[int(float(c1.monto))] += 1
            if precios:
                self.stdout.write("  Precios cuota 1: " + ", ".join(f"${m:,}×{k}" for m, k in precios.most_common(5)))

            # Ejemplos concretos
            self.stdout.write("  Ejemplos:")
            for p in qs[:6]:
                cli = getattr(p, "cliente", None)
                nom = f"{getattr(cli,'apellido','') or ''}, {getattr(cli,'nombre','') or ''}".strip(", ") if cli else "—"
                self.stdout.write(
                    f"    • {(p.patente or '—'):<9} · {nom[:28]:<28} · N°={p.numero_poliza or '—'} · cob={p.cobertura or '—'}"
                )

        self.stdout.write(self.style.SUCCESS("\n  ✓ Fin (no se modificó nada).\n"))