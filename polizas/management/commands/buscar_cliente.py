# polizas/management/commands/buscar_cliente.py
#
# 🔍 SOLO LECTURA — muestra TODO de una patente (o DNI): póliza(s), cuotas y pagos.
#
# USO:
#   python manage.py buscar_cliente --patente AA870GR
#   python manage.py buscar_cliente --dni 38242795
#
# Ruta: polizas/management/commands/buscar_cliente.py

from django.core.management.base import BaseCommand

from polizas.models import Poliza
from pagos.models import Cuota

try:
    from pagos.models import Pago
except Exception:
    Pago = None


class Command(BaseCommand):
    help = "Muestra póliza(s), cuotas y pagos de una patente o DNI. Solo lee."

    def add_arguments(self, parser):
        parser.add_argument("--patente", type=str, default=None)
        parser.add_argument("--dni", type=str, default=None)

    def handle(self, *args, **opts):
        patente = (opts.get("patente") or "").strip().upper()
        dni = (opts.get("dni") or "").strip()

        qs = Poliza.objects.all().select_related("cliente")
        if patente:
            qs = qs.filter(patente__iexact=patente)
        elif dni:
            qs = qs.filter(cliente__dni_cuit_cuil__icontains=dni)
        else:
            self.stdout.write("Pasá --patente o --dni")
            return

        self.stdout.write(self.style.WARNING(
            f"\n[buscar_cliente] SOLO LECTURA · {'patente '+patente if patente else 'dni '+dni} · {qs.count()} póliza(s)\n"
        ))

        for pol in qs.order_by("id"):
            cli = getattr(pol, "cliente", None)
            nom = f"{getattr(cli,'apellido','') or ''}, {getattr(cli,'nombre','') or ''}".strip(", ") if cli else "—"
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\n═══ Póliza id={pol.id} · N°={pol.numero_poliza or '—'} · {nom} ═══"
            ))
            self.stdout.write(
                f"  compañía={pol.compania or '—'} · cobertura={pol.cobertura or '—'} · estado={pol.estado} "
                f"· emisión={getattr(pol,'fecha_emision','—')} · fecha_venc(póliza)={getattr(pol,'fecha_vencimiento','—')}"
            )

            cuotas = Cuota.objects.filter(poliza=pol).order_by("cuota_nro", "id")
            self.stdout.write(f"  Cuotas ({cuotas.count()}):")
            for c in cuotas:
                estado = f"PAGADA {c.fecha_pago or '—'}" if c.pagado else "IMPAGA"
                reg = getattr(c, "pago_registrado_en", None)
                extra = f" · pago_registrado_en={reg}" if reg else ""
                self.stdout.write(
                    f"    C{c.cuota_nro} (id {c.id}) · vto={c.fecha_vencimiento or '—'} · ${c.monto} · {estado}{extra}"
                )

            if Pago is not None:
                pagos = Pago.objects.filter(cuota__poliza=pol).order_by("id")
                if pagos.exists():
                    self.stdout.write(f"  Pagos ({pagos.count()}):")
                    for p in pagos:
                        self.stdout.write(
                            f"    Pago id={p.id} · cuota={getattr(p,'cuota_id','—')} · ${getattr(p,'monto','—')} "
                            f"· fecha={getattr(p,'fecha',getattr(p,'fecha_pago','—'))} "
                            f"· registrado_en={getattr(p,'pago_registrado_en','—')} · metodo={getattr(p,'metodo','—')}"
                        )

        self.stdout.write(self.style.SUCCESS("\n  ✓ Fin (no se modificó nada).\n"))