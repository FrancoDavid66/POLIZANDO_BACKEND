# estadisticas/models.py
from django.conf import settings
from django.db import models


class OficinaCode(models.TextChoices):
    OFI_1 = "1", "5 esquinas (1)"
    OFI_2 = "2", "axion (2)"
    OFI_3 = "3", "kilometro 39 (3)"
    OTRAS = "OTRAS", "Otras / sin mapear"
    SIN_OFICINA = "SIN_OFICINA", "Sin oficina"


class PolizaOficinaSnapshot(models.Model):
    """
    Snapshot mensual de pólizas por oficina.
    Sirve para cachear KPIs de un período (año/mes).

    Nota:
    - A partir de ahora conviene guardar oficina normalizada como:
      "1" | "2" | "3" | "OTRAS" | "SIN_OFICINA"
    """

    oficina = models.CharField(
        max_length=80,
        db_index=True,
        choices=OficinaCode.choices,
        help_text='Guardar código normalizado: "1","2","3","OTRAS","SIN_OFICINA".',
    )
    anio = models.PositiveIntegerField(db_index=True)
    mes = models.PositiveIntegerField(db_index=True)

    # Totales de stock
    total_polizas = models.PositiveIntegerField(default=0)
    total_activas = models.PositiveIntegerField(default=0)

    # Movimiento del mes
    nuevas_mes = models.PositiveIntegerField(default=0)
    bajas_mes = models.PositiveIntegerField(default=0)

    # Data extra serializada (mix por compañía, coberturas, etc.)
    data_extra = models.JSONField(default=dict, blank=True)

    creado_el = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("oficina", "anio", "mes")
        verbose_name = "Snapshot pólizas por oficina"
        verbose_name_plural = "Snapshots pólizas por oficina"

    def __str__(self):
        label = getattr(self, "get_oficina_display", lambda: self.oficina)()
        return f"{label or 'SIN_OFICINA'} {self.anio:04d}-{self.mes:02d}"


class KpiDiarioOficina(models.Model):
    """
    KPIs diarios por oficina (opcional, para históricos y gráficos finos).
    No lo vamos a usar todavía en las vistas, pero ya queda listo.
    """

    fecha = models.DateField(db_index=True)
    oficina = models.CharField(
        max_length=80,
        db_index=True,
        choices=OficinaCode.choices,
        help_text='Guardar código normalizado: "1","2","3","OTRAS","SIN_OFICINA".',
    )

    polizas_activas = models.PositiveIntegerField(default=0)
    polizas_morosas = models.PositiveIntegerField(default=0)

    # Cobranzas (si querés después las completamos desde Cuota / Ingreso)
    cobranzas_del_dia = models.DecimalField(
        max_digits=14, decimal_places=2, default=0
    )

    data_extra = models.JSONField(default=dict, blank=True)

    creado_el = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("fecha", "oficina")
        verbose_name = "KPI diario por oficina"
        verbose_name_plural = "KPIs diarios por oficina"

    def __str__(self):
        label = getattr(self, "get_oficina_display", lambda: self.oficina)()
        return f"{label or 'SIN_OFICINA'} @ {self.fecha.isoformat()}"


class AlertaKpi(models.Model):
    """
    Configuración de alertas sobre KPIs (morosidad, bajas, etc.).
    A futuro podemos enganchar esto a un cron / tarea que evalue y dispare avisos.
    """

    TIPO_CHOICES = (
        ("morosidad", "Morosidad"),
        ("bajas", "Bajas de póliza"),
        ("produccion", "Producción"),
        ("custom", "Personalizada"),
    )

    # Acá lo dejamos libre porque querés poder poner vacío = todas las oficinas
    oficina = models.CharField(
        max_length=80, blank=True, null=True, db_index=True,
        help_text='Código ("1","2","3") o vacío = todas.',
    )
    tipo = models.CharField(max_length=40, choices=TIPO_CHOICES, default="morosidad")
    umbral = models.FloatField(
        help_text="Por ejemplo, 0.2 para 20% de morosidad."
    )
    activo = models.BooleanField(default=True)

    creado_el = models.DateTimeField(auto_now_add=True)
    ultimo_disparo = models.DateTimeField(blank=True, null=True)

    descripcion = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "Alerta de KPI"
        verbose_name_plural = "Alertas de KPI"

    def __str__(self):
        base = self.descripcion or self.get_tipo_display()
        return f"{base} ({self.oficina or 'todas las oficinas'})"


class ExportLog(models.Model):
    """
    Log de exports de reportes (Excel, CSV, etc.) de estadísticas.
    Útil para auditoría y para poder repetir un reporte con los mismos parámetros.
    """

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="estadisticas_exports",
    )
    tipo = models.CharField(
        max_length=80,
        help_text="Ej.: 'polizas_oficina', 'cobranzas_oficina', etc.",
    )
    parametros = models.JSONField(default=dict, blank=True)
    creado_el = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Log de export de estadísticas"
        verbose_name_plural = "Logs de exports de estadísticas"
        ordering = ("-creado_el",)

    def __str__(self):
        return f"{self.tipo} @ {self.creado_el:%Y-%m-%d %H:%M}"
