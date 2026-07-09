from django.conf import settings
from django.db import models

class HistorialMensajeMarketing(models.Model):
    """
    Registro maestro de cada ejecución de marketing.
    Almacena el mensaje base, los filtros aplicados y las estadísticas consolidadas.
    """
    mensaje = models.TextField(help_text="Cuerpo del mensaje con variables como {nombre}, {apellido}, {marca}, etc.")
    # Almacena los filtros usados: {"marca": "renault", "anio": "2015", ...}
    filtros = models.JSONField(default=dict, blank=True, help_text="Copia de los filtros aplicados.")
    
    # Oficina: "1", "2", "3" para identificar la sucursal
    oficina = models.CharField(max_length=16, blank=True, default="")
    
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="marketing_historial_creado",
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    ejecutado_at = models.DateTimeField(null=True, blank=True)
    dry_run = models.BooleanField(default=False, help_text="Indica si fue una simulación.")

    # Estadísticas consolidadas para el resumen en el frontend
    total_polizas_match = models.PositiveIntegerField(default=0, help_text="Total de pólizas que coincidieron con los filtros.")
    total_destinatarios = models.PositiveIntegerField(default=0, help_text="Total de destinatarios únicos (mensajes reales).")
    total_enviados = models.PositiveIntegerField(default=0)
    total_errores = models.PositiveIntegerField(default=0)
    total_invalidos = models.PositiveIntegerField(default=0)
    total_omitidos = models.PositiveIntegerField(default=0, help_text="Mensajes omitidos (ej: ya enviados previamente).")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Historial de Marketing"
        verbose_name_plural = "Historiales de Marketing"

    def __str__(self):
        return f"Campaña {self.id} - {self.created_at.strftime('%d/%m/%Y %H:%M')}"


class HistorialMensajeMarketingLog(models.Model):
    """
    Registro individual de cada mensaje enviado a un cliente.
    Permite ver exactamente qué mensaje recibió cada persona.
    """
    ESTADO_OK = "ok"
    ESTADO_ERROR = "error"
    ESTADO_INVALIDO = "invalido"
    ESTADO_OMITIDO = "omitido"
    ESTADO_DRY_RUN = "dry_run"

    ESTADOS = [
        (ESTADO_OK, "OK"),
        (ESTADO_ERROR, "Error"),
        (ESTADO_INVALIDO, "Inválido"),
        (ESTADO_OMITIDO, "Omitido"),
        (ESTADO_DRY_RUN, "Dry run"),
    ]

    historial = models.ForeignKey(
        HistorialMensajeMarketing,
        on_delete=models.CASCADE,
        related_name="logs",
    )
    
    # IDs de referencia para trazabilidad
    cliente_id = models.IntegerField(null=True, blank=True)
    poliza_id = models.IntegerField(null=True, blank=True)
    
    numero = models.CharField(max_length=64, blank=True, default="")
    numero_normalizado = models.CharField(max_length=32, blank=True, default="")
    
    estado = models.CharField(
        max_length=16, 
        choices=ESTADOS
    )
    
    error = models.TextField(blank=True, default="")
    mensaje_renderizado = models.TextField(blank=True, default="", help_text="Mensaje final con {nombre}, {apellido}, etc. ya reemplazados.")
    
    # Campos para auditoría técnica con proveedores (UltraMsg, etc.)
    provider = models.CharField(max_length=32, blank=True, default="")
    provider_meta = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "Log de Envío"

    def __str__(self):
        return f"Log {self.id} - {self.numero_normalizado} ({self.estado})"