# alquileres/models.py

from django.db import models

class Propietario(models.Model):
    nombre = models.CharField(max_length=100)
    telefono = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True)
    direccion = models.TextField(blank=True)
    
    def __str__(self):
        return self.nombre


class Garante(models.Model):
    nombre = models.CharField(max_length=100)
    telefono = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True)
    direccion = models.TextField(blank=True)
    lugar_trabajo = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return self.nombre


class Inquilino(models.Model):
    nombre = models.CharField(max_length=100)
    telefono = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True)
    garantes = models.ManyToManyField(Garante, related_name='inquilinos', blank=True)
    direccion = models.TextField(blank=True)

    def __str__(self):
        return self.nombre


class Alquiler(models.Model):
    direccion = models.CharField(max_length=200)
    partido = models.CharField(max_length=100)
    localidad = models.CharField(max_length=100)
    requisitos = models.TextField(blank=True)

    propietarios = models.ManyToManyField(Propietario, related_name='alquileres')
    inquilinos = models.ManyToManyField(Inquilino, related_name='alquileres')

    contrato = models.FileField(upload_to='contratos/', blank=True, null=True)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    precio_alquiler = models.DecimalField(max_digits=10, decimal_places=2)

    aumento_cada_meses = models.IntegerField(default=12)
    porcentaje_aumento = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)

    def __str__(self):
        return f"{self.direccion} - {', '.join([i.nombre for i in self.inquilinos.all()])}"


class CuotaAlquiler(models.Model):
    alquiler = models.ForeignKey(Alquiler, on_delete=models.CASCADE, related_name='cuotas')
    nro_cuota = models.IntegerField()
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    fecha_vencimiento = models.DateField()
    pagado = models.BooleanField(default=False)

    def __str__(self):
        return f"Cuota {self.nro_cuota} - {self.alquiler.direccion}"
