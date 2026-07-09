# inmuebles /models.py
from django.db import models

class Propiedad(models.Model):
    TIPO_CHOICES = [
        ('alquiler', 'Alquiler'),
        ('venta', 'Venta'),
    ]
    ESTADO_CHOICES = [
        ('disponible', 'Disponible'),
        ('reservada', 'Reservada'),
        ('vendida', 'Vendida'),
        ('alquilada', 'Alquilada'),
    ]

    direccion = models.CharField(max_length=255)
    localidad = models.CharField(max_length=100)
    partido = models.CharField(max_length=100)

    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default='disponible')

    precio = models.DecimalField(max_digits=10, decimal_places=2)
    descripcion = models.TextField(blank=True)

    fecha_publicacion = models.DateField(auto_now_add=True)

    def __str__(self):
        return f"{self.direccion} ({self.get_tipo_display()})"

class Inquilino(models.Model):
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    telefono = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True)
    dni = models.CharField(max_length=20)
    direccion = models.TextField(blank=True)

    def __str__(self):
        return f"{self.apellido}, {self.nombre}"


class Propietario(models.Model):
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    telefono = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True)
    dni = models.CharField(max_length=20)
    direccion = models.TextField(blank=True)

    def __str__(self):
        return f"{self.apellido}, {self.nombre}"


class Alquiler(models.Model):
    propiedad = models.ForeignKey(Propiedad, on_delete=models.CASCADE, related_name='alquileres')

    direccion = models.CharField(max_length=255)
    partido = models.CharField(max_length=100)
    localidad = models.CharField(max_length=100)

    inquilinos = models.ManyToManyField('Inquilino', related_name='alquileres')
    propietarios = models.ManyToManyField('Propietario', related_name='propiedades')

    contrato = models.FileField(upload_to='contratos_alquiler/', null=True, blank=True)
    requisitos = models.TextField(blank=True)

    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()

    precio_mensual = models.DecimalField(max_digits=10, decimal_places=2)
    aumento_cada_n_meses = models.PositiveIntegerField(help_text="Ej: cada 4 meses")
    porcentaje_aumento = models.DecimalField(max_digits=5, decimal_places=2, help_text="Ej: 10.00 para 10%")

    comisionado = models.BooleanField(default=False)
    observaciones = models.TextField(blank=True)

    def __str__(self):
        return f"Alquiler en {self.direccion} ({self.fecha_inicio} - {self.fecha_fin})"



class CuotaAlquiler(models.Model):
    alquiler = models.ForeignKey('Alquiler', on_delete=models.CASCADE, related_name='cuotas')
    numero = models.PositiveIntegerField()
    fecha_vencimiento = models.DateField()
    monto = models.DecimalField(max_digits=10, decimal_places=2)

    pagado = models.BooleanField(default=False)
    fecha_pago = models.DateField(null=True, blank=True)
    forma_pago = models.CharField(max_length=100, blank=True)
    observaciones = models.TextField(blank=True)

    def __str__(self):
        return f"Cuota {self.numero} - {self.alquiler.direccion}"