# balanzes/models.py
from django.db import models
from django.utils import timezone
from django.conf import settings
from decimal import Decimal

FORMA_PAGO = (
    ("EFECTIVO", "Efectivo"),
    ("TRANSFERENCIA", "Transferencia"),
    ("TARJETA", "Tarjeta"),
    ("MERCADOPAGO", "Mercado Pago"),
    ("OTRO", "Otro"),
)

# ==========================================
# 🟣 MODELO: CATEGORÍAS
# ==========================================
class Categoria(models.Model):
    nombre = models.CharField(max_length=120, unique=True)
    TIPO_CHOICES = (
        ("INGRESO", "Ingreso"),
        ("EGRESO", "Egreso"),
        ("AMBOS", "Ambos"),
    )
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default="AMBOS")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Categoría"
        verbose_name_plural = "Categorías"

    def __str__(self):
        return f"{self.nombre} ({self.tipo})"


# ==========================================
# 🟢 MODELO: INGRESO
# ==========================================
class Ingreso(models.Model):
    descripcion = models.CharField(max_length=255)
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    fecha = models.DateField(default=timezone.localdate)

    # 🚀 SOLUCIÓN PROFESIONAL: Enlace directo a la tabla de Oficinas
    oficina = models.ForeignKey(
        'usuarios.Oficina', 
        on_delete=models.SET_NULL, 
        blank=True, null=True, 
        related_name="ingresos_caja"
    )

    categoria = models.CharField(max_length=120, blank=True, null=True)
    forma_pago = models.CharField(max_length=20, choices=FORMA_PAGO, blank=True, null=True)
    pagado_por = models.CharField(max_length=120, blank=True, null=True)
    billetera = models.CharField(max_length=255, blank=True, null=True, help_text="Cuenta destino del estudio (alias, CBU, nombre billetera)")
    cuit_remitente = models.CharField(max_length=30, blank=True, null=True, help_text="CUIT/CUIL de quien transfirió")
    nro_operacion  = models.CharField(max_length=60, blank=True, null=True, help_text="N° de operación/comprobante de la transferencia")
    observaciones = models.TextField(blank=True, null=True)

    # ── Auditoría de transferencias ──────────────────────────────
    verificada = models.BooleanField(default=False, help_text="¿La transferencia fue verificada con el comprobante?")
    verificada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="transferencias_verificadas"
    )
    verificada_en = models.DateTimeField(null=True, blank=True)
    nota_verificacion = models.CharField(max_length=255, blank=True, null=True)
    
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, blank=True,
        related_name="ingresos_cargados"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._monto_original = self.monto
        self._forma_pago_original = self.forma_pago

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        if is_new:
            HistorialIngreso.objects.create(
                ingreso=self, monto_anterior=Decimal('0.00'), monto_nuevo=self.monto,
                forma_pago_anterior="", forma_pago_nuevo=self.forma_pago or "",
                detalle="Creación de ingreso"
            )
        elif self.monto != self._monto_original or self.forma_pago != self._forma_pago_original:
            HistorialIngreso.objects.create(
                ingreso=self, monto_anterior=self._monto_original, monto_nuevo=self.monto,
                forma_pago_anterior=self._forma_pago_original or "", forma_pago_nuevo=self.forma_pago or "",
                detalle="Modificación de ingreso"
            )
            self._monto_original = self.monto
            self._forma_pago_original = self.forma_pago

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "Ingreso"
        verbose_name_plural = "Ingresos"
        indexes = [models.Index(fields=["fecha", "oficina"])]

    def __str__(self):
        return f"Ingreso {self.id} - ${self.monto}"


class HistorialIngreso(models.Model):
    ingreso = models.ForeignKey(Ingreso, on_delete=models.CASCADE, related_name="historial")
    monto_anterior = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    monto_nuevo = models.DecimalField(max_digits=12, decimal_places=2)
    forma_pago_anterior = models.CharField(max_length=20, blank=True)
    forma_pago_nuevo = models.CharField(max_length=20, blank=True)
    detalle = models.CharField(max_length=255, blank=True)
    fecha = models.DateTimeField(auto_now_add=True)


# ==========================================
# 🔴 MODELO: EGRESO
# ==========================================
class Egreso(models.Model):
    descripcion = models.CharField(max_length=255)
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    fecha = models.DateField(default=timezone.localdate)

    # 🚀 SOLUCIÓN PROFESIONAL: Enlace directo a la tabla de Oficinas
    oficina = models.ForeignKey(
        'usuarios.Oficina', 
        on_delete=models.SET_NULL, 
        blank=True, null=True, 
        related_name="egresos_caja"
    )

    categoria = models.CharField(max_length=120, blank=True, null=True)
    forma_pago = models.CharField(max_length=20, choices=FORMA_PAGO, blank=True, null=True, default="EFECTIVO")
    observaciones = models.TextField(blank=True, null=True)
    
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, blank=True,
        related_name="egresos_cargados"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._monto_original = self.monto
        self._forma_pago_original = self.forma_pago

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        if is_new:
            HistorialEgreso.objects.create(
                egreso=self, monto_anterior=Decimal('0.00'), monto_nuevo=self.monto,
                forma_pago_anterior="", forma_pago_nuevo=self.forma_pago or "",
                detalle="Creación de egreso"
            )
        elif self.monto != self._monto_original or self.forma_pago != self._forma_pago_original:
            HistorialEgreso.objects.create(
                egreso=self, monto_anterior=self._monto_original, monto_nuevo=self.monto,
                forma_pago_anterior=self._forma_pago_original or "", forma_pago_nuevo=self.forma_pago or "",
                detalle="Modificación de egreso"
            )
            self._monto_original = self.monto
            self._forma_pago_original = self.forma_pago

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "Egreso"
        verbose_name_plural = "Egresos"
        indexes = [models.Index(fields=["fecha", "oficina"])]

    def __str__(self):
        return f"Egreso {self.id} - ${self.monto}"


class HistorialEgreso(models.Model):
    egreso = models.ForeignKey(Egreso, on_delete=models.CASCADE, related_name="historial")
    monto_anterior = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    monto_nuevo = models.DecimalField(max_digits=12, decimal_places=2)
    forma_pago_anterior = models.CharField(max_length=20, blank=True)
    forma_pago_nuevo = models.CharField(max_length=20, blank=True)
    detalle = models.CharField(max_length=255, blank=True)
    fecha = models.DateTimeField(auto_now_add=True)