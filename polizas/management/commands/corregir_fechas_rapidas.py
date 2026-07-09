# polizas/management/commands/corregir_fechas_rapidas.py
#
# Corrige fechas de cuotas de pólizas NUEVAS creadas con la CARGA RÁPIDA bugueada.
#
# SEÑAL DE BUG (estricta):
#   La CUOTA 1 vence EXACTO el día de emisión (o tiene fecha basura, año < 2000).
#   En un plan sano la cuota 1 vence un mes después.
#
# SEGURIDAD (por lo visto en las simulaciones):
#   - NO toca RENOVACIONES: se detectan por "-R" en el número (ej. -R1, -R2) o por poliza_origen.
#   - NO toca pólizas con CUOTAS DUPLICADAS: las lista aparte.
#   - NO toca pólizas 100% pagadas (nada que arreglar).
#
# ARREGLO: cada cuota N vence a N meses de la emisión (C1 = emisión+1, C2 = +2, ...).
#
# USO:
#   python manage.py corregir_fechas_rapidas              # SIMULACIÓN (no toca nada)
#   python manage.py corregir_fechas_rapidas --aplicar    # aplica los cambios
#   python manage.py corregir_fechas_rapidas --oficina 5  # solo una sucursal
#
# Ruta: polizas/management/commands/corregir_fechas_rapidas.py

from datetime import date, datetime

from dateutil.relativedelta import relativedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from polizas.models import Poliza
from pagos.models import Cuota

ESTADOS_EXCLUIDOS = ["cancelada", "finalizada", "en_verificacion"]


def _to_date(v):
    if not v:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return datetime.fromisoformat(str(v)[:10]).date()
    except Exception:
        return None


def _es_renovacion(pol) -> bool:
    """Renovación = tiene poliza_origen O el número termina/contiene un sufijo -R (ej. -R1)."""
    if getattr(pol, "poliza_origen_id", None):
        return True
    return "-R" in (pol.numero_poliza or "").upper()


class Command(BaseCommand):
    help = (
        "Corrige fechas de cuotas de pólizas NUEVAS de la carga rápida bugueada "
        "(cuota 1 vence el día de emisión). Salta renovaciones y cuotas duplicadas. "
        "Por defecto SIMULA; usá --aplicar."
    )

    def add_arguments(self, parser):
        parser.add_argument("--aplicar", action="store_true",
                            help="Aplica los cambios. Sin esto es SOLO simulación.")
        parser.add_argument("--oficina", type=int, default=None,
                            help="Filtrar por ID de oficina.")

    def handle(self, *args, **opts):
        aplicar = bool(opts.get("aplicar"))
        oficina = opts.get("oficina")
        hoy = timezone.localdate()

        qs = Poliza.objects.exclude(estado__in=ESTADOS_EXCLUIDOS)
        if oficina:
            qs = qs.filter(oficina_id=oficina)

        modo = "APLICANDO CAMBIOS" if aplicar else "SIMULACIÓN (no toca nada)"
        self.stdout.write(self.style.WARNING(
            f"\n[corregir_fechas_rapidas] {modo} · hoy = {hoy}"
            + (f" · oficina_id={oficina}" if oficina else " · todas las oficinas")
            + "\n"
        ))

        afectadas = 0
        cuotas_tocadas = 0
        reactivadas = 0
        patentes = []
        duplicadas = []

        for pol in qs.iterator():
            # ── (1) Saltar RENOVACIONES (por poliza_origen o por "-R" en el número).
            if _es_renovacion(pol):
                continue

            emision = _to_date(getattr(pol, "fecha_emision", None))
            if not emision:
                continue

            cuotas = list(Cuota.objects.filter(poliza=pol).order_by("cuota_nro", "id"))
            if not cuotas:
                continue

            # ── (2) Saltar CUOTAS DUPLICADAS (mismo cuota_nro repetido) → listar aparte.
            nros = [c.cuota_nro for c in cuotas]
            if len(nros) != len(set(nros)):
                duplicadas.append((pol.patente or "SIN PATENTE").upper())
                continue

            c1 = cuotas[0]
            v1 = c1.fecha_vencimiento
            if v1 is None:
                continue

            # ── (3) SEÑAL DE BUG: C1 vence exacto el día de emisión, o fecha basura.
            es_bug = (v1 == emision) or (v1.year < 2000)
            if not es_bug:
                continue

            # ── (4) Debe tener al menos una cuota IMPAGA (si todo pagado, nada que arreglar).
            if not any(not c.pagado for c in cuotas):
                continue

            # ── ARREGLO: re-anclar cada cuota a "emisión + N meses" (N = cuota_nro).
            cambios = []
            for c in cuotas:
                nueva = emision + relativedelta(months=c.cuota_nro)
                if c.fecha_vencimiento != nueva:
                    cambios.append((c, c.fecha_vencimiento, nueva))
            if not cambios:
                continue

            afectadas += 1
            patente = (pol.patente or "SIN PATENTE").upper()
            patentes.append(patente)
            cli = getattr(pol, "cliente", None)
            nombre = "—"
            if cli:
                nombre = f"{getattr(cli, 'apellido', '') or ''}, {getattr(cli, 'nombre', '') or ''}".strip(", ")
            self.stdout.write(
                f"  • PATENTE {patente} · {nombre} · {pol.numero_poliza or pol.id} "
                f"· emisión {emision}"
            )
            for c, vieja, nueva in cambios:
                marca = " (pagada)" if c.pagado else ""
                self.stdout.write(f"      Cuota {c.cuota_nro}{marca}: {vieja} → {nueva}")
                if aplicar:
                    c.fecha_vencimiento = nueva
                    c.save(update_fields=["fecha_vencimiento"])
                cuotas_tocadas += 1

            # ── Reactivar a 'activa' si, con las fechas nuevas, no queda impaga atrasada.
            nuevas_impagas = [nueva for (c, vieja, nueva) in cambios if not c.pagado]
            sin_atraso = bool(nuevas_impagas) and all(v >= hoy for v in nuevas_impagas)
            if pol.estado == "vencida" and sin_atraso:
                self.stdout.write("      Estado: vencida → activa")
                if aplicar:
                    pol.estado = "activa"
                    pol.save(update_fields=["estado"])
                reactivadas += 1

        self.stdout.write(self.style.SUCCESS(
            f"\n  Pólizas afectadas: {afectadas} · "
            f"cuotas corregidas: {cuotas_tocadas} · reactivadas: {reactivadas}"
        ))
        if patentes:
            self.stdout.write("\n  Patentes corregidas:")
            self.stdout.write("    " + ", ".join(patentes))
        if duplicadas:
            self.stdout.write(self.style.WARNING(
                f"\n  ⚠️  {len(duplicadas)} pólizas con CUOTAS DUPLICADAS (NO tocadas, revisar a mano):"
            ))
            self.stdout.write("    " + ", ".join(duplicadas))
        if not aplicar:
            self.stdout.write(self.style.WARNING(
                "\n  ⚠️  Fue SIMULACIÓN. Revisá y, si está bien, corré con --aplicar.\n"
            ))
        else:
            self.stdout.write(self.style.SUCCESS("\n  ✓ Cambios guardados.\n"))