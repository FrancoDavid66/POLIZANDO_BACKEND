from django.core.management.base import BaseCommand
from django.utils.timezone import now
from balanzes.models import Ingreso, Egreso
from balanzes.serializers import IngresoSerializer, EgresoSerializer
from balanzes.ultramsg import enviar_balance_diario


class Command(BaseCommand):
    help = "Enviar balance diario por WhatsApp a un único número"

    def handle(self, *args, **kwargs):
        # Fecha actual
        hoy = now().date()

        # Movimientos del día
        ingresos = Ingreso.objects.filter(fecha=hoy)
        egresos = Egreso.objects.filter(fecha=hoy)

        # Totales
        total_ingresos = sum([ingreso.monto for ingreso in ingresos])
        total_egresos = sum([egreso.monto for egreso in egresos])
        balance_neto = total_ingresos - total_egresos

        # ✅ ÚNICO destinatario permitido
        destinatarios = ["1164235336"]

        # Enviamos a cada uno (en este caso, 1 solo)
        for numero in destinatarios:
            enviado = enviar_balance_diario(
                numero,
                hoy.strftime("%d-%m-%Y"),
                total_ingresos,
                total_egresos,
                balance_neto,
            )

            if enviado:
                self.stdout.write(self.style.SUCCESS(f"✅ Balance diario enviado a {numero}"))
            else:
                self.stdout.write(self.style.ERROR(f"❌ No se pudo enviar el balance a {numero}"))
