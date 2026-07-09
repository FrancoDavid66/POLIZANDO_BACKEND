# polizas/management/commands/actualizar_precios_camiones_motos.py
#
# Pone las cuotas IMPAGAS de CAMIONES y MOTOS de NRE al precio NRE ACTUAL.
# El precio sale de polizas/precios_nre.py (hoy: Camión $75.000 · Moto $18.000),
# así que si mañana cambia la tabla, este comando aplica el nuevo precio.
#
# 🔒 Seguridad:
#   - SOLO toca cuotas IMPAGAS (nunca las ya pagadas → no rompe el historial).
#   - SOLO pólizas de NRE con tipo Camion / Moto.
#   - NO pisa cuotas que estén en un precio de descuento multi-vehículo
#     (para no cobrarle de más a un cliente con 2do/3er vehículo).
#   - Ignora pólizas canceladas / finalizadas.
#
# USO:
#   python manage.py actualizar_precios_camiones_motos --dry-run   (prueba, no guarda)
#   python manage.py actualizar_precios_camiones_motos             (aplica)
#   python manage.py actualizar_precios_camiones_motos --tipo camion
#   python manage.py actualizar_precios_camiones_motos --tipo moto

import logging

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from polizas.models import Poliza
from pagos.models import Cuota
from polizas.precios_nre import precio_vigente, DESCUENTO_MULTIVEHICULO

logger = logging.getLogger(__name__)

TIPOS_OBJETIVO = ["Camion", "Moto"]


def _money(n):
    try:
        return f"${float(n):,.0f}".replace(",", ".")
    except Exception:
        return f"${n}"


def _descuentos_de(tipo):
    """Precios de descuento multi-vehículo para un tipo (para NO pisarlos)."""
    tabla = DESCUENTO_MULTIVEHICULO.get(tipo, {}) or {}
    return {int(v) for v in tabla.values()}


class Command(BaseCommand):
    help = ("Pone las cuotas impagas de camiones y motos de NRE al precio NRE "
            "actual (hoy: Camión $75.000 · Moto $18.000).")

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="No guarda nada. Solo muestra qué cambiaría.",
        )
        parser.add_argument(
            "--tipo", choices=["camion", "moto", "todos"], default="todos",
            help="Qué tipo actualizar (default: todos).",
        )

    def handle(self, *args, **opts):
        dry = bool(opts["dry_run"])
        filtro = opts["tipo"]

        if filtro == "camion":
            tipos = ["Camion"]
        elif filtro == "moto":
            tipos = ["Moto"]
        else:
            tipos = list(TIPOS_OBJETIVO)

        # NRE (por texto libre o por el FK del catálogo) + tipo objetivo, sin terminales.
        qs = (
            Poliza.objects
            .filter(tipo__in=tipos)
            .filter(Q(compania__icontains="nre") | Q(compania_obj__nombre__icontains="nre"))
            .exclude(estado__in=["cancelada", "finalizada"])
            .select_related("cliente")
        )

        prefijo = "[DRY-RUN] " if dry else ""
        self.stdout.write("=" * 64)
        self.stdout.write(f"{prefijo}Actualizando precios NRE — tipos: {', '.join(tipos)}")
        self.stdout.write("=" * 64)

        total_polizas = 0
        total_cuotas = 0
        resumen = {}
        saltadas_descuento = 0

        for poliza in qs.iterator(chunk_size=500):
            precio = precio_vigente(poliza.tipo)  # 75000 / 18000 (según tipo, a hoy)
            if not precio:
                continue
            precio = int(precio)
            descuentos = _descuentos_de(poliza.tipo)

            impagas = list(poliza.cuotas.filter(pagado=False))
            a_cambiar = []
            for c in impagas:
                monto = int(c.monto or 0)
                if monto == precio:
                    continue                      # ya está en el precio correcto
                if monto in descuentos:
                    saltadas_descuento += 1       # descuento multi-vehículo → no tocar
                    continue
                a_cambiar.append(c)

            if not a_cambiar:
                continue

            n = len(a_cambiar)
            total_polizas += 1
            total_cuotas += n
            resumen[poliza.tipo] = resumen.get(poliza.tipo, 0) + n

            self.stdout.write(
                f"  {poliza.tipo:7s} · {(poliza.patente or '—'):8s} · "
                f"{n} cuota(s) → {_money(precio)}"
            )

            if not dry:
                ids = [c.id for c in a_cambiar]
                Cuota.objects.filter(id__in=ids).update(monto=precio)
                if int(poliza.precio_cuota or 0) != precio:
                    poliza.precio_cuota = precio
                    poliza.save(update_fields=["precio_cuota"])

        self.stdout.write("-" * 64)
        for t, c in resumen.items():
            self.stdout.write(f"  {t}: {c} cuota(s)")
        if saltadas_descuento:
            self.stdout.write(f"  (se saltaron {saltadas_descuento} cuota(s) con descuento multi-vehículo)")

        accion = "Se cambiarían" if dry else "✅ Se cambiaron"
        self.stdout.write(
            f"{accion} {total_cuotas} cuota(s) impaga(s) en {total_polizas} póliza(s)."
        )
        if dry:
            self.stdout.write(self.style.WARNING(
                "Fue una PRUEBA (--dry-run): no se guardó nada. "
                "Corré el mismo comando SIN --dry-run para aplicar."
            ))
        else:
            self.stdout.write(self.style.SUCCESS("Listo."))