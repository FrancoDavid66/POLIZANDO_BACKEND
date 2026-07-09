# pagos/management/commands/diagnosticar_alertas_patentes.py
#
# Diagnóstico de SOLO LECTURA (no modifica nada en la base). Para un listado de
# patentes, muestra cada cuota con dos fechas:
#   - vto_propio    = fecha_vencimiento de la cuota misma (lo que usa el sistema
#                     VIEJO: pagos/management/commands/enviar_alertas.py)
#   - vto_anterior  = fecha_vencimiento de la cuota ANTERIOR en la misma póliza
#                     (lo que usa el sistema NUEVO: notificaciones/services_cuotas.py,
#                     según la regla de negocio confirmada: se paga cuando termina
#                     la cobertura de la cuota anterior)
#
# Marca con 🔴 cuando los dos sistemas dispararían una alerta DISTINTA (o solo
# uno de los dos dispara) — que es exactamente el síntoma que reportó la empleada.
#
# Uso:
#   python manage.py diagnosticar_alertas_patentes
#   python manage.py diagnosticar_alertas_patentes --patentes ABC123,XYZ789

from django.core.management.base import BaseCommand
from django.utils import timezone

from pagos.models import Cuota
from polizas.models import Poliza

PATENTES_DEFAULT = [
    "SGZ885", "SYB556", "KHV257", "PNL095", "RKE033",
    "AB240QM", "IMJ039", "FKH582", "THS325", "RWF714",
]

# Mismos rangos que armar_rangos() en pagos/management/commands/enviar_alertas.py,
# expresados como delta de días (fecha_vencimiento - hoy).
RANGOS_VIEJOS = {
    "3_antes":    (1, 3),
    "hoy":        (0, 0),
    "3_despues":  (-3, -1),
    "7_despues":  (-7, -4),
    "30_despues": (-60, -30),
}


def _bucket(delta):
    for nombre, (lo, hi) in RANGOS_VIEJOS.items():
        if lo <= delta <= hi:
            return nombre
    return None


class Command(BaseCommand):
    help = "Diagnóstico de solo lectura: compara fecha propia vs fecha de cuota anterior, para un listado de patentes."

    def add_arguments(self, parser):
        parser.add_argument(
            "--patentes", type=str, default=None,
            help="Lista de patentes separadas por coma. Si no se pasa, usa el listado por defecto.",
        )

    def handle(self, *args, **options):
        hoy = timezone.localdate()
        patentes_arg = options.get("patentes")
        patentes = (
            [p.strip().upper() for p in patentes_arg.split(",") if p.strip()]
            if patentes_arg else PATENTES_DEFAULT
        )

        self.stdout.write(f"\n📅 Hoy: {hoy}\n")
        total_discrepancias = 0

        for patente in patentes:
            polizas = Poliza.objects.filter(patente__iexact=patente).order_by("-id")
            if not polizas.exists():
                polizas = Poliza.objects.filter(patente__icontains=patente).order_by("-id")
            if not polizas.exists():
                self.stdout.write(f"\n=== {patente}: NO ENCONTRADA ===")
                continue

            for p in polizas:
                self.stdout.write(
                    f"\n=== {patente} | póliza id={p.id} | estado={p.estado} | "
                    f"es_renovacion={getattr(p, 'es_renovacion', '?')} | "
                    f"fecha_emision={getattr(p, 'fecha_emision', '?')} ==="
                )

                cuotas = list(Cuota.objects.filter(poliza_id=p.id).order_by("cuota_nro"))
                if not cuotas:
                    self.stdout.write("  (sin cuotas)")
                    continue

                for c in cuotas:
                    anterior = next(
                        (x.fecha_vencimiento for x in cuotas if x.cuota_nro == c.cuota_nro - 1),
                        None,
                    )
                    es_primera_renovacion = (c.cuota_nro == 1 and getattr(p, "es_renovacion", False))
                    fecha_correcta = anterior or c.fecha_vencimiento

                    delta_propio = (c.fecha_vencimiento - hoy).days
                    delta_correcto = (fecha_correcta - hoy).days

                    bucket_viejo = _bucket(delta_propio) if not c.pagado else None
                    bucket_nuevo = _bucket(delta_correcto) if not c.pagado else None

                    marcas = []
                    if not c.pagado and bucket_viejo != bucket_nuevo:
                        marcas.append("🔴 DISCREPANCIA viejo/nuevo")
                        total_discrepancias += 1
                    elif not c.pagado and bucket_viejo:
                        marcas.append("⚠️ ambos dispararían acá")
                    if es_primera_renovacion:
                        marcas.append("🟡 cuota#1 de renovación")

                    marca_txt = ("  " + " | ".join(marcas)) if marcas else ""

                    self.stdout.write(
                        f"  cuota#{c.cuota_nro} | pagado={c.pagado} | monto={c.monto} | "
                        f"vto_propio={c.fecha_vencimiento} (Δ{delta_propio:+d}, {bucket_viejo or '-'}) | "
                        f"vto_anterior={anterior if anterior else '(no hay, usa la propia)'} "
                        f"(Δ{delta_correcto:+d}, {bucket_nuevo or '-'})"
                        f"{marca_txt}"
                    )

        self.stdout.write(f"\n\n📊 Total discrepancias encontradas: {total_discrepancias}")
        self.stdout.write("Pegame esta salida completa y seguimos.\n")