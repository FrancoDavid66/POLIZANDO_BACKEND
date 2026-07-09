from django.apps import AppConfig


class SolicitudesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "solicitudes"
    verbose_name = "Solicitudes"

    def ready(self):
        # Importa señales para el copiado automático de documentos/fotos
        from . import signals  # noqa: F401
