# pagos/apps.py
from django.apps import AppConfig


class PagosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "pagos"

    def ready(self):
        import pagos.signals  # noqa: F401