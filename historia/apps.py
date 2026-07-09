from django.apps import AppConfig

class HistoriaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'historia'

    def ready(self):
        # Carga los signals al iniciar la app
        import historia.signals  # noqa
