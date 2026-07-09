from django.db import models


class NotificacionCuotaLog(models.Model):
    """
    Registro de envíos de WhatsApp de recordatorio de cuotas.

    Sirve para asegurarnos de que a cada cliente/número
    solo se le envíe una vez por día, aunque el endpoint
    se ejecute varias veces.
    """

    cliente = models.ForeignKey(
        "clientes.Cliente",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="logs_notificaciones_cuotas",
    )
    numero = models.CharField(max_length=32)
    fecha = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Log de notificación de cuotas"
        verbose_name_plural = "Logs de notificaciones de cuotas"
        unique_together = ("cliente", "numero", "fecha")

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.fecha} - {self.numero}"


class EnvioRecordatoriosCuotas(models.Model):
    """
    Registro de ejecuciones del envío de recordatorios de cuotas
    por día y por oficina.

    Garantiza que por (fecha, oficina) solo se dispare una vez
    el flujo de envíos de WhatsApp.
    """

    fecha = models.DateField()
    oficina = models.CharField(
        max_length=16,
        help_text="ID lógico de la oficina (por ejemplo: '1', '2', '3').",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Envío de recordatorios de cuotas"
        verbose_name_plural = "Envíos de recordatorios de cuotas"
        unique_together = ("fecha", "oficina")

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.fecha} - oficina {self.oficina}"


class EnvioRecordatorioDetalle(models.Model):
    """
    Detalle por cliente de un envío de recordatorios.

    Una fila por cliente/número al que se le envió mensaje
    en un EnvioRecordatoriosCuotas.
    """

    envio = models.ForeignKey(
        EnvioRecordatoriosCuotas,
        on_delete=models.CASCADE,
        related_name="detalles",
        null=True,
        blank=True,
        help_text="Ejecución (día + oficina) asociada al envío.",
    )
    cliente = models.ForeignKey(
        "clientes.Cliente",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="detalles_recordatorios_cuotas",
    )
    poliza_principal = models.ForeignKey(
        "polizas.Poliza",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="detalles_recordatorios_cuotas",
    )
    oficina = models.CharField(
        max_length=16,
        null=True,
        blank=True,
        help_text="ID lógico de la oficina desde donde se envió.",
    )
    telefono = models.CharField(
        max_length=32,
        help_text="Número de WhatsApp al que se envió el mensaje.",
    )
    monto_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Suma de los importes de las cuotas incluidas en el mensaje.",
    )
    cuotas_ids = models.JSONField(
        default=list,
        blank=True,
        help_text="Lista de IDs de cuotas incluidas en el mensaje.",
    )
    texto_resumen = models.CharField(
        max_length=255,
        blank=True,
        help_text="Resumen corto: ej. '3 cuotas, total $45.000'.",
    )
    estado_envio = models.CharField(
        max_length=16,
        default="OK",
        help_text="Estado del envío: p.ej. 'OK' o 'ERROR'.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Detalle de envío de recordatorio"
        verbose_name_plural = "Detalles de envíos de recordatorios"
        ordering = ["-created_at"]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.created_at:%Y-%m-%d %H:%M} - {self.telefono} ({self.estado_envio})"
