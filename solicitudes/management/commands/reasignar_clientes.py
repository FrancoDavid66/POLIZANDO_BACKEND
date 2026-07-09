# usuarios/management/commands/reasignar_clientes.py
from django.core.management.base import BaseCommand
from clientes.models import Cliente
from usuarios.models import Oficina

class Command(BaseCommand):
    help = 'Reasigna 3000+ clientes a sus oficinas basándose en su historial de pólizas'

    def handle(self, *args, **kwargs):
        self.stdout.write("Iniciando reasignación mágica de clientes... 🪄")

        try:
            ofi_5esq = Oficina.objects.get(id=1)
            ofi_axion = Oficina.objects.get(id=2)
            ofi_km39 = Oficina.objects.get(id=3)
        except Oficina.DoesNotExist:
            self.stdout.write(self.style.ERROR("❌ Error: Las oficinas 1, 2 o 3 no existen."))
            return

        axion_count = 0
        km39_count = 0
        total = Cliente.objects.count()

        self.stdout.write(f"Procesando {total} clientes. Por favor esperá...")

        # Guardamos en bloque para no saturar la RAM
        for cliente in Cliente.objects.all().iterator():
            poliza = cliente.polizas.order_by('-id').first()
            
            if poliza and poliza.oficina:
                texto_viejo = str(poliza.oficina).lower().strip()
                
                if "axion" in texto_viejo or texto_viejo == "2":
                    cliente.oficina = ofi_axion
                    axion_count += 1
                elif "km" in texto_viejo or "39" in texto_viejo or texto_viejo == "3":
                    cliente.oficina = ofi_km39
                    km39_count += 1
                else:
                    cliente.oficina = ofi_5esq
            else:
                cliente.oficina = ofi_5esq
                
            cliente.save(update_fields=['oficina'])

        self.stdout.write(self.style.SUCCESS("✅ ¡Operación exitosa!"))
        self.stdout.write(self.style.SUCCESS(f"🏢 Clientes recuperados para Axion: {axion_count}"))
        self.stdout.write(self.style.SUCCESS(f"🏢 Clientes recuperados para Km 39: {km39_count}"))