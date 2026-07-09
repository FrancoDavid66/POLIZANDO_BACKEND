# usuarios/management/commands/setup_legacy.py
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from usuarios.models import Oficina, Perfil

class Command(BaseCommand):
    help = 'Crea oficinas y usuarios legacy al arrancar el servidor en Railway'

    def handle(self, *args, **kwargs):
        self.stdout.write("Verificando datos legacy críticos...")

        # 1. Crear Oficinas SOLO si no existen (get_or_create)
        ofi1, c1 = Oficina.objects.get_or_create(id=1, defaults={'codigo': 'OFI-1', 'nombre': '5 esquinas (1)', 'activa': True})
        ofi2, c2 = Oficina.objects.get_or_create(id=2, defaults={'codigo': 'OFI-2', 'nombre': 'axion (2)', 'activa': True})
        ofi3, c3 = Oficina.objects.get_or_create(id=3, defaults={'codigo': 'OFI-3', 'nombre': 'kilometro 39 (3)', 'activa': True})
        
        if c1 or c2 or c3:
            self.stdout.write(self.style.SUCCESS("✅ Oficinas legacy inyectadas."))

        # 2. Configurar Usuarios SOLO si no existen
        default_password = "Password123!"
        users_data = [
            {'username': '5esquinas', 'email': '5esquinas@thames.com', 'oficina': ofi1},
            {'username': 'axion', 'email': 'axion@thames.com', 'oficina': ofi2},
            {'username': 'km39', 'email': 'km39@thames.com', 'oficina': ofi3},
        ]

        for data in users_data:
            user, created = User.objects.get_or_create(username=data['username'])
            if created:
                user.email = data['email']
                user.set_password(default_password)
                user.save()
                
                # Vincular el Perfil con el Rol y la Oficina
                # Como usamos señales, el perfil ya se creó, solo lo actualizamos
                perfil = user.perfil
                perfil.rol = 'OFICINA'
                perfil.oficina = data['oficina']
                perfil.save()
                self.stdout.write(self.style.SUCCESS(f"   - Usuario {user.username} creado y vinculado."))

        self.stdout.write(self.style.SUCCESS("🚀 Verificación de entorno finalizada."))