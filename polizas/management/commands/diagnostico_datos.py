# polizas/management/commands/diagnostico_datos.py
"""
🔍 COMANDO DE DIAGNÓSTICO — SOLO LECTURA, NO MODIFICA NADA

Uso:
    python manage.py diagnostico_datos

Detecta y reporta problemas de calidad de datos:
  1. Clientes sin oficina (huérfanos)
  2. Pólizas sin oficina (huérfanas)
  3. Pólizas "activas" con cuotas atrasadas (deberían estar "vencida")
  4. Pólizas "vencidas" con todas las cuotas pagas (deberían estar "activa")
  5. Pólizas "canceladas" con pagos recientes (revisar)

⚠️  IMPORTANTE: Este comando NO modifica datos. Solo cuenta y muestra ejemplos.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q, Count, Exists, OuterRef
from django.utils import timezone

from clientes.models import Cliente
from polizas.models import Poliza
from pagos.models import Cuota


# ───────────────────────────────────────────────────────
# Helpers de impresión bonita
# ───────────────────────────────────────────────────────

def _line(char="─", length=63):
    return char * length


def _box_title(title):
    print()
    print(f"╔{_line('═')}╗")
    print(f"║  {title:<59} ║")
    print(f"╚{_line('═')}╝")


def _section(emoji, title):
    print()
    print(f"{emoji}  {title}")
    print(_line())


def _count_line(label, count, indent="  "):
    """Imprime una línea con conteo. Si es 0 va en verde, si tiene casos en rojo."""
    if count == 0:
        marker = "✅"
    elif count <= 5:
        marker = "🟡"
    else:
        marker = "🔴"

    print(f"{indent}{marker} {label:<48} {count}")


def _print_examples(label, queryset, fmt_fn, limit=5):
    """Muestra primeros N ejemplos de un queryset."""
    items = list(queryset[:limit])
    if not items:
        return
    print(f"\n     Ejemplos ({len(items)} de los primeros {limit}):")
    for item in items:
        print(f"       • {fmt_fn(item)}")


# ───────────────────────────────────────────────────────
# Command
# ───────────────────────────────────────────────────────

class Command(BaseCommand):
    help = "Diagnóstico de calidad de datos. NO modifica nada, solo lee."

    def add_arguments(self, parser):
        parser.add_argument(
            "--ejemplos",
            type=int,
            default=5,
            help="Cantidad de ejemplos a mostrar por categoría (default: 5)",
        )
        parser.add_argument(
            "--dias-mora",
            type=int,
            default=30,
            help="Días de mora a partir de los cuales una póliza activa es 'sospechosa' (default: 30)",
        )

    def handle(self, *args, **options):
        ejemplos = options["ejemplos"]
        dias_mora = options["dias_mora"]

        hoy = timezone.localdate()
        cutoff_mora = hoy - timedelta(days=dias_mora)

        _box_title("📊 DIAGNÓSTICO DE DATOS — Thames Seguros")
        print(f"  Fecha: {hoy.isoformat()}")
        print(f"  Umbral de mora considerado 'sospechoso': {dias_mora} días")

        # ════════════════════════════════════════════════════
        # 1. OFICINAS HUÉRFANAS
        # ════════════════════════════════════════════════════
        _section("🏢", "OFICINAS HUÉRFANAS")

        # Clientes sin oficina
        clientes_sin_oficina = Cliente.objects.filter(oficina__isnull=True)
        count_clientes = clientes_sin_oficina.count()
        _count_line("Clientes sin oficina asignada", count_clientes)

        if count_clientes > 0:
            _print_examples(
                "Clientes",
                clientes_sin_oficina.order_by("-id"),
                lambda c: f"ID {c.id} · {c.apellido}, {c.nombre} · DNI {c.dni_cuit_cuil or '—'}",
                limit=ejemplos,
            )

        # Pólizas sin oficina
        polizas_sin_oficina = Poliza.objects.filter(oficina__isnull=True)
        count_polizas = polizas_sin_oficina.count()
        _count_line("Pólizas sin oficina asignada", count_polizas)

        if count_polizas > 0:
            _print_examples(
                "Pólizas",
                polizas_sin_oficina.select_related("cliente").order_by("-id"),
                lambda p: (
                    f"ID {p.id} · {p.numero_poliza or 'SIN N°'} · "
                    f"{(p.cliente.apellido + ', ' + p.cliente.nombre) if p.cliente else '—'} · "
                    f"Patente: {p.patente or '—'}"
                ),
                limit=ejemplos,
            )

        # ════════════════════════════════════════════════════
        # 2. ESTADOS INCONSISTENTES
        # ════════════════════════════════════════════════════
        _section("📋", "ESTADOS INCONSISTENTES")

        # 2a. Pólizas "activas" con cuotas atrasadas hace +N días
        cuotas_muy_atrasadas = Cuota.objects.filter(
            poliza=OuterRef("pk"),
            pagado=False,
            fecha_vencimiento__lt=cutoff_mora,
        )
        polizas_activas_morosas = Poliza.objects.filter(
            estado__iexact="activa"
        ).annotate(
            tiene_atraso=Exists(cuotas_muy_atrasadas)
        ).filter(tiene_atraso=True)

        count_act_mora = polizas_activas_morosas.count()
        _count_line(
            f"Pólizas 'activas' con mora de +{dias_mora} días",
            count_act_mora,
        )

        if count_act_mora > 0:
            _print_examples(
                "Pólizas activas morosas",
                polizas_activas_morosas.select_related("cliente").order_by("-id"),
                lambda p: (
                    f"ID {p.id} · {p.numero_poliza or 'SIN N°'} · "
                    f"{(p.cliente.apellido + ', ' + p.cliente.nombre) if p.cliente else '—'}"
                ),
                limit=ejemplos,
            )

        # 2b. Pólizas "vencidas" con todas las cuotas pagas
        cuotas_impagas_vencidas = Cuota.objects.filter(
            poliza=OuterRef("pk"),
            pagado=False,
            fecha_vencimiento__lt=hoy,
        )
        polizas_vencidas_al_dia = Poliza.objects.filter(
            estado__iexact="vencida"
        ).annotate(
            tiene_impagas_vencidas=Exists(cuotas_impagas_vencidas)
        ).filter(tiene_impagas_vencidas=False)

        count_venc_al_dia = polizas_vencidas_al_dia.count()
        _count_line(
            "Pólizas 'vencidas' pero sin cuotas atrasadas",
            count_venc_al_dia,
        )

        if count_venc_al_dia > 0:
            _print_examples(
                "Pólizas vencidas al día",
                polizas_vencidas_al_dia.select_related("cliente").order_by("-id"),
                lambda p: (
                    f"ID {p.id} · {p.numero_poliza or 'SIN N°'} · "
                    f"{(p.cliente.apellido + ', ' + p.cliente.nombre) if p.cliente else '—'}"
                ),
                limit=ejemplos,
            )

        # 2c. Pólizas "canceladas" con pagos recientes (últimos 30 días)
        hace_30 = hoy - timedelta(days=30)
        cuotas_pagadas_recientes = Cuota.objects.filter(
            poliza=OuterRef("pk"),
            pagado=True,
            fecha_pago__gte=hace_30,
        )
        polizas_canceladas_con_pago = Poliza.objects.filter(
            estado__iexact="cancelada"
        ).annotate(
            tiene_pago_reciente=Exists(cuotas_pagadas_recientes)
        ).filter(tiene_pago_reciente=True)

        count_canc_pago = polizas_canceladas_con_pago.count()
        _count_line(
            "Pólizas 'canceladas' con pagos en últimos 30 días",
            count_canc_pago,
        )

        if count_canc_pago > 0:
            _print_examples(
                "Pólizas canceladas con pagos",
                polizas_canceladas_con_pago.select_related("cliente").order_by("-id"),
                lambda p: (
                    f"ID {p.id} · {p.numero_poliza or 'SIN N°'} · "
                    f"{(p.cliente.apellido + ', ' + p.cliente.nombre) if p.cliente else '—'}"
                ),
                limit=ejemplos,
            )

        # ════════════════════════════════════════════════════
        # 3. RESUMEN POR ESTADO
        # ════════════════════════════════════════════════════
        _section("📈", "DISTRIBUCIÓN ACTUAL DE ESTADOS")

        por_estado = (
            Poliza.objects.values("estado")
            .annotate(total=Count("id"))
            .order_by("-total")
        )

        total_polizas = Poliza.objects.count()
        print(f"  Total de pólizas en la base: {total_polizas}\n")

        for row in por_estado:
            estado = (row["estado"] or "SIN ESTADO").upper()
            total = row["total"]
            pct = (total / total_polizas * 100) if total_polizas > 0 else 0
            print(f"    {estado:<25} {total:>6}  ({pct:>5.1f}%)")

        # ════════════════════════════════════════════════════
        # 4. RESUMEN FINAL
        # ════════════════════════════════════════════════════
        _section("🎯", "RESUMEN")

        total_problemas = (
            count_clientes
            + count_polizas
            + count_act_mora
            + count_venc_al_dia
            + count_canc_pago
        )

        if total_problemas == 0:
            print("  ✅ ¡No se encontraron problemas! La base está limpia.")
        else:
            print(f"  📊 Total de casos detectados: {total_problemas}")
            print()
            print("  Categorías con casos:")
            if count_clientes:
                print(f"     • Clientes huérfanos: {count_clientes}")
            if count_polizas:
                print(f"     • Pólizas huérfanas: {count_polizas}")
            if count_act_mora:
                print(f"     • Activas con mora: {count_act_mora}")
            if count_venc_al_dia:
                print(f"     • Vencidas al día: {count_venc_al_dia}")
            if count_canc_pago:
                print(f"     • Canceladas con pago: {count_canc_pago}")
            print()
            print("  ℹ️  Pasá los resultados al equipo para decidir cómo corregir.")
            print("  ⚠️  Este comando NO modifica datos.")

        print()
        print(_line("═"))
        print("  Diagnóstico completado. Nada se modificó en la base.")
        print(_line("═"))
        print()