# tareas/apps.py
from django.apps import AppConfig


class TareasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tareas"
    verbose_name = "Tareas del día"

    def ready(self):
        # Conecta las señales (cuota pagada → póliza pendiente de enviar).
        from . import signals  # noqa: F401