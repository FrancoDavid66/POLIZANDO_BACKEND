# servicios/models.py
from django.db import models
from django.utils import timezone
from django.conf import settings
from datetime import date
import calendar


# ════════════════════════════════════════════════════════════════
# 🟣 MODELO 0: CategoriaServicio (CRUD propio)
# ════════════════════════════════════════════════════════════════
class CategoriaServicio(models.Model):
    nombre = models.CharField(max_length=120, unique=True)
    color = models.CharField(
        max_length=20,
        blank=True,
        default="sky",
        help_text="Color para identificación visual (sky, emerald, amber, rose, etc.)"
    )
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='categorias_servicios_creadas'
    )

    class Meta:
        verbose_name = "Categoría de Servicio"
        verbose_name_plural = "Categorías de Servicios"
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


# ════════════════════════════════════════════════════════════════
# 🟦 MODELO 1: ServicioFijo (la plantilla)
# ════════════════════════════════════════════════════════════════
class ServicioFijo(models.Model):
    nombre = models.CharField(
        max_length=120,
        help_text="Ej: Edenor, Telecentro, Alquiler Oficina Centro"
    )
    proveedor = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Razón social del proveedor (opcional). Ej: Edenor S.A."
    )

    # Categoría: free-text para retrocompatibilidad
    # Recomendado: cargar el nombre de una CategoriaServicio existente
    categoria = models.CharField(
        max_length=120,
        help_text="Categoría del servicio (cargar desde CategoriaServicio)"
    )

    oficina = models.ForeignKey(
        'usuarios.Oficina',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='servicios_fijos'
    )

    monto_estimado = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )

    dia_vencimiento = models.PositiveSmallIntegerField(
        help_text="Día del mes en que vence (1-31)"
    )

    FORMA_PAGO = (
        ("EFECTIVO", "Efectivo"),
        ("TRANSFERENCIA", "Transferencia"),
        ("MERCADOPAGO", "Mercado Pago"),
    )
    forma_pago_default = models.CharField(
        max_length=20,
        choices=FORMA_PAGO,
        default="TRANSFERENCIA"
    )

    activo = models.BooleanField(default=True)
    notas = models.TextField(blank=True, default="")

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='servicios_creados'
    )

    class Meta:
        verbose_name = "Servicio Fijo"
        verbose_name_plural = "Servicios Fijos"
        ordering = ['oficina', 'dia_vencimiento', 'nombre']
        indexes = [
            models.Index(fields=['oficina', 'activo']),
            models.Index(fields=['dia_vencimiento']),
        ]

    def __str__(self):
        ofi_tag = f" [{self.oficina.codigo}]" if self.oficina else ""
        return f"{self.nombre}{ofi_tag} (día {self.dia_vencimiento})"

    def fecha_vencimiento_del_mes(self, anio: int, mes: int) -> date:
        ultimo_dia_mes = calendar.monthrange(anio, mes)[1]
        dia = min(self.dia_vencimiento, ultimo_dia_mes)
        return date(anio, mes, dia)


# ════════════════════════════════════════════════════════════════
# 🟢 MODELO 2: PagoServicio
# ════════════════════════════════════════════════════════════════
class PagoServicio(models.Model):
    ESTADO_CHOICES = (
        ("PENDIENTE", "Pendiente"),
        ("PAGADO", "Pagado"),
        ("VENCIDO", "Vencido"),
        ("OMITIDO", "Omitido"),
    )

    FORMA_PAGO = (
        ("EFECTIVO", "Efectivo"),
        ("TRANSFERENCIA", "Transferencia"),
        ("MERCADOPAGO", "Mercado Pago"),
    )

    servicio = models.ForeignKey(
        ServicioFijo,
        on_delete=models.CASCADE,
        related_name='pagos'
    )
    periodo = models.CharField(max_length=7, help_text="Formato AAAA-MM. Ej: 2026-05")
    fecha_vencimiento = models.DateField()
    estado = models.CharField(
        max_length=15,
        choices=ESTADO_CHOICES,
        default="PENDIENTE",
        db_index=True
    )

    monto_real = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    fecha_pago = models.DateField(null=True, blank=True)
    hora_pago = models.DateTimeField(null=True, blank=True)

    pagado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='servicios_pagados'
    )

    forma_pago = models.CharField(max_length=20, choices=FORMA_PAGO, blank=True, default="")

    medio_cobro = models.ForeignKey(
        'pagos.MedioCobro',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='pagos_servicios',
    )

    comprobante_url = models.URLField(max_length=600, blank=True, default="")

    egreso = models.OneToOneField(
        'balanzes.Egreso',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='pago_servicio_origen'
    )

    observaciones = models.TextField(blank=True, default="")

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Pago de Servicio"
        verbose_name_plural = "Pagos de Servicios"
        ordering = ['-periodo', 'servicio__dia_vencimiento']
        indexes = [
            models.Index(fields=['periodo', 'estado']),
            models.Index(fields=['estado', 'fecha_vencimiento']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['servicio', 'periodo'],
                name='un_pago_por_servicio_y_periodo'
            ),
        ]

    def __str__(self):
        return f"{self.servicio.nombre} - {self.periodo} ({self.get_estado_display()})"

    @property
    def dias_hasta_vencimiento(self) -> int:
        if not self.fecha_vencimiento:
            return 0
        delta = self.fecha_vencimiento - timezone.localdate()
        return delta.days

    @property
    def esta_por_vencer(self) -> bool:
        return self.estado == "PENDIENTE" and 0 <= self.dias_hasta_vencimiento <= 3

    @property
    def esta_vencido(self) -> bool:
        return self.estado == "PENDIENTE" and self.dias_hasta_vencimiento < 0

    def actualizar_estado_automatico(self):
        if self.estado == "PENDIENTE" and self.dias_hasta_vencimiento < 0:
            self.estado = "VENCIDO"
            self.save(update_fields=['estado', 'actualizado_en'])