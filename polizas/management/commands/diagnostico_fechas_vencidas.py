# polizas/management/commands/diagnostico_fechas_vencidas.py
#
# 🔍 SOLO LECTURA — NO MODIFICA NADA.
# Lista las pólizas que la app marca como vencidas (tienen cuotas impagas con
# vencimiento en el pasado) y muestra TODAS sus cuotas, para entender por qué.
#
# USO:
#   python manage.py diagnostico_fechas_vencidas
#   python manage.py diagnostico_fechas_vencidas --oficina 5
#   python manage.py diagnostico_fechas_vencidas --limit 40
#   python manage.py diagnostico_fechas_vencidas --patente FKN566
#
# Ruta: polizas/management/commands/diagnostico_fechas_vencidas.py

from django.core.management.base import BaseCommand
from django.utils import timezone

from polizas.models import Poliza
from pagos.models import Cuota

ESTADOS_EXCLUIDOS = ["cancelada", "finalizada", "en_verificacion"]


class Command(BaseCommand):
    help = "Diagnóstico SOLO LECTURA: muestra las cuotas de las pólizas vencidas para entender el bug de fechas."

    def add_arguments(self, parser):
        parser.add_argument("--oficina", type=int, default=None, help="Filtrar por ID de oficina.")
        parser.add_argument("--limit", type=int, default=25, help="Máximo de pólizas a mostrar (default 25).")
        parser.add_argument("--patente", type=str, default=None, help="Ver una patente puntual.")

    def handle(self, *args, **opts):
        hoy = timezone.localdate()
        oficina = opts.get("oficina")
        limit = opts.get("limit")
        patente = (opts.get("patente") or "").strip().upper()

        self.stdout.write(self.style.WARNING(
            f"\n[diagnostico_fechas_vencidas] SOLO LECTURA · hoy = {hoy}\n"
        ))

        qs = Poliza.objects.exclude(estado__in=ESTADOS_EXCLUIDOS)
        if oficina:
            qs = qs.filter(oficina_id=oficina)
        if patente:
            qs = qs.filter(patente__iexact=patente)
        else:
            # Solo las que tienen alguna cuota impaga y vencida (lo que la app ve como "vencida")
            qs = qs.filter(cuotas__pagado=False, cuotas__fecha_vencimiento__lt=hoy).distinct()

        qs = qs.order_by("-id")
        total = qs.count()
        self.stdout.write(f"  Encontradas: {total}  (muestro hasta {limit})\n")

        n = 0
        for pol in qs[:limit]:
            n += 1
            cli = getattr(pol, "cliente", None)
            nombre = "—"
            if cli:
                nombre = f"{getattr(cli, 'apellido', '') or ''}, {getattr(cli, 'nombre', '') or ''}".strip(", ")
            pat = (pol.patente or "SIN PATENTE").upper()
            self.stdout.write(
                f"[{n}] PATENTE {pat} · {nombre} · {pol.numero_poliza or pol.id} "
                f"· emisión {getattr(pol, 'fecha_emision', '—')} · {pol.estado}"
            )
            cuotas = Cuota.objects.filter(poliza=pol).order_by("cuota_nro", "id")
            for c in cuotas:
                if c.pagado:
                    estado = f"✓ pagada {c.fecha_pago or '—'}"
                else:
                    atraso = ""
                    if c.fecha_vencimiento and c.fecha_vencimiento < hoy:
                        atraso = " (ATRASADA)"
                    estado = f"✗ impaga{atraso}"
                self.stdout.write(
                    f"      C{c.cuota_nro}  vto {c.fecha_vencimiento or '—'}  ·  {estado}"
                )
            self.stdout.write("")

        self.stdout.write(self.style.SUCCESS("  ✓ Diagnóstico terminado (no se modificó nada).\n"))