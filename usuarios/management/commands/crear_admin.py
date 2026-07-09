from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    help = 'Crea el superusuario administrador global automáticamente'

    def handle(self, *args, **kwargs):
        User = get_user_model()
        username = 'david-admin'
        password = 'BIUTUX333'

        # Verificamos si el usuario ya existe para no pisarlo ni tirar error
        if not User.objects.filter(username=username).exists():
            User.objects.create_superuser(
                username=username, 
                email='', 
                password=password
            )
            self.stdout.write(self.style.SUCCESS(f'✅ Superusuario "{username}" creado con éxito! 👑'))
        else:
            self.stdout.write(self.style.WARNING(f'⚡ El superusuario "{username}" ya existe. Todo en orden.'))