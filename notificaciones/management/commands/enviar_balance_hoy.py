# balanzes/management/commands/enviar_balance_hoy.py
from datetime import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Sum, Count
from django.db.models.functions import Coalesce

from balanzes.models import Ingreso, Egreso
from notificaciones.services_balanzes import enviar_balance_por_whatsapp


def build_balance(fecha):
    """
    Mismo cálculo que en BalanceViewSet._build_balance(fecha),
    pero usable desde el management command.
    """
    ingresos_qs = Ingreso.objects.filter(fecha=fecha)
    egresos_qs = Egreso.objects.filter(fecha=fecha)

    total_ingresos = ingresos_qs.aggregate(
        t=Coalesce(Sum("monto"), Decimal("0"))
    )["t"]
    total_egresos = egresos_qs.aggregate(
        t=Coalesce(Sum("monto"), Decimal("0"))
    )["t"]

    ingresos_por_categoria = list(
        ingresos_qs.values("categoria")
        .annotate(total=Coalesce(Sum("monto"), Decimal("0")), cantidad=Count("id"))
        .order_by("categoria")
    )

    ingresos_por_forma = list(
        ingresos_qs.values("forma_pago")
        .annotate(total=Coalesce(Sum("monto"), Decimal("0")), cantidad=Count("id"))
        .order_by("forma_pago")
    )

    egresos_por_categoria = list(
        egresos_qs.values("categoria")
        .annotate(total=Coalesce(Sum("monto"), Decimal("0")), cantidad=Count("id"))
        .order_by("categoria")
    )

    payload = {
        "fecha_iso": fecha.isoformat(),
        "fecha_hum": fecha.strftime("%d/%m/%Y"),
        "totales": {
            "ingresos": str(total_ingresos),
            "egresos": str(total_egresos),
            "balance": str((total_ingresos or 0) - (total_egresos or 0)),
        },
        "ingresos": {
            "por_categoria": ingresos_por_categoria,
            "por_forma_pago": ingresos_por_forma,
        },
        "egresos": {
            "por_categoria": egresos_por_categoria,
        },
    }
    return payload


class Command(BaseCommand):
    help = "Envía por WhatsApp el balance de un día (por defecto, hoy)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fecha",
            type=str,
            help="Fecha en formato YYYY-MM-DD (opcional, por defecto hoy).",
        )
        parser.add_argument(
            "--destinatario",
            type=str,
            help="Número de destino (ej: 1164235336). Si se omite, usa settings.",
        )

    def handle(self, *args, **options):
        raw_fecha = options.get("fecha")
        destinatario = options.get("destinatario")

        if raw_fecha:
            try:
                fecha = datetime.fromisoformat(raw_fecha).date()
            except Exception:
                self.stderr.write(self.style.ERROR("Fecha inválida. Use YYYY-MM-DD."))
                return
        else:
            fecha = timezone.localdate()

        self.stdout.write(f"Calculando balance para el día {fecha}...")
        data = build_balance(fecha)

        self.stdout.write("Enviando WhatsApp...")
        ok, info = enviar_balance_por_whatsapp(
            fecha=fecha,
            data=data,
            destinatario=destinatario or None,
        )

        if ok:
            self.stdout.write(self.style.SUCCESS("✅ Mensaje enviado correctamente."))
            self.stdout.write(str(info))
        else:
            self.stderr.write(self.style.ERROR("❌ Error al enviar el mensaje."))
            self.stderr.write(str(info))
