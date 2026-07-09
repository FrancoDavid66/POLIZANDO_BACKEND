# servicios/apps.py
from django.apps import AppConfig


class ServiciosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'servicios'
    verbose_name = 'Servicios y Gastos Fijos'

    def ready(self):
        # 🚀 Activa el espejo de categorías (Servicios <-> Balances)
        from . import signals  # noqa: F401