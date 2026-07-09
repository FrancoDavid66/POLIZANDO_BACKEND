# tareas/models.py
from django.conf import settings
from django.db import models
from django.utils import timezone


class TareaCompletada(models.Model):
    """
    Registro histórico de cada tarea que un empleado completa desde el panel.
    Sirve para el reporte diario ("buchón") por oficina.
    """

    TIPOS = [
        ("enviar", "Enviar póliza"),
        ("datos_poliza", "Datos de la póliza"),
        ("datos_cliente", "Datos del cliente"),
        ("fotos_dni", "Fotos de DNI"),
        ("fotos_poliza", "Fotos del vehículo"),
    ]

    tipo = models.CharField(max_length=20, choices=TIPOS, db_index=True)
    oficina = models.ForeignKey(
        "usuarios.Oficina", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="tareas_completadas",
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="tareas_completadas",
    )
    # Guardamos solo el id (registro histórico, no necesita integridad referencial)
    poliza_id = models.IntegerField(null=True, blank=True)
    cliente_id = models.IntegerField(null=True, blank=True)
    creado_en = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-creado_en"]
        indexes = [
            models.Index(fields=["oficina", "creado_en"]),
            models.Index(fields=["tipo", "creado_en"]),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} · ofi {self.oficina_id} · {self.creado_en:%d/%m %H:%M}"