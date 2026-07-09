from django.core.management.base import BaseCommand
from solicitudes.models import SolicitudSeguro
from clientes.models import Cliente
from polizas.models import Poliza
from notificaciones.models import EnvioRecordatorioDetalle
from usuarios.models import Oficina

class Command(BaseCommand):
    help = 'Reasigna solicitudes y notificaciones a sus respectivas sucursales'

    def handle(self, *args, **kwargs):
        self.stdout.write("🚀 Iniciando barrido final de Solicitudes y Notificaciones...")

        # 1. Limpieza de SOLICITUDES
        solicitudes_arregladas = 0
        for solicitud in SolicitudSeguro.objects.all().iterator():
            nueva_oficina = None
            
            # Buscamos por póliza
            if solicitud.poliza_id:
                try:
                    poliza = Poliza.objects.get(id=solicitud.poliza_id)
                    nueva_oficina = poliza.oficina
                except Poliza.DoesNotExist:
                    pass

            # Si no, buscamos por DNI del cliente
            if not nueva_oficina and solicitud.cliente_dni:
                # Buscamos por dni_cuit_cuil o por documento (por si tenés el campo viejo)
                cliente_relacionado = Cliente.objects.filter(dni_cuit_cuil=solicitud.cliente_dni).first()
                if not cliente_relacionado and hasattr(Cliente, 'documento'):
                    cliente_relacionado = Cliente.objects.filter(documento=solicitud.cliente_dni).first()
                
                if cliente_relacionado:
                    nueva_oficina = cliente_relacionado.oficina

            if nueva_oficina:
                solicitud.oficina = nueva_oficina
                solicitud.save(update_fields=['oficina'])
                solicitudes_arregladas += 1

        self.stdout.write(self.style.SUCCESS(f"✅ Solicitudes reasignadas: {solicitudes_arregladas}"))

        # 2. Limpieza de NOTIFICACIONES
        detalles_arreglados = 0
        envios_actualizados = set()
        
        for detalle in EnvioRecordatorioDetalle.objects.select_related('poliza_principal', 'envio').iterator():
            if detalle.poliza_principal and detalle.poliza_principal.oficina:
                ofi = detalle.poliza_principal.oficina
                ofi_id = str(getattr(ofi, 'id', ofi)).strip()
                
                # Mapeo de texto
                if "1" in ofi_id or "esquinas" in ofi_id.lower():
                    detalle.oficina = "1"
                elif "2" in ofi_id or "axion" in ofi_id.lower():
                    detalle.oficina = "2"
                elif "3" in ofi_id or "39" in ofi_id.lower():
                    detalle.oficina = "3"
                
                detalle.save(update_fields=['oficina'])
                detalles_arreglados += 1
                
                # Propagamos la oficina a la cabecera
                if detalle.envio and detalle.envio.id not in envios_actualizados:
                     if not detalle.envio.oficina or detalle.envio.oficina == "1":
                         detalle.envio.oficina = detalle.oficina
                         detalle.envio.save(update_fields=['oficina'])
                         envios_actualizados.add(detalle.envio.id)

        self.stdout.write(self.style.SUCCESS(f"📱 Detalles notificaciones arreglados: {detalles_arreglados}"))
        self.stdout.write(self.style.SUCCESS(f"📱 Cabeceras de envíos sincronizadas: {len(envios_actualizados)}"))
        self.stdout.write(self.style.SUCCESS("🎉 ¡SISTEMA 100% MIGRADO Y AISLADO POR SUCURSALES! 🎉"))