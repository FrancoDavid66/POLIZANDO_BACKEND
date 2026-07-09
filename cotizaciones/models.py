# cotizaciones/models.py
from django.db import models
from django.conf import settings

class CompaniaSeguro(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    comision_default = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)
    antiguedad_maxima = models.IntegerField(default=25)
    logo_url = models.URLField(max_length=500, blank=True, null=True)
    activa = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['nombre']

    def __str__(self):
        return f"{self.nombre} ({self.comision_default}%)"

class TipoCobertura(models.Model):
    nombre = models.CharField(max_length=100)
    compania = models.ForeignKey(CompaniaSeguro, on_delete=models.CASCADE, related_name='coberturas', null=True, blank=True)
    beneficios_default = models.JSONField(default=list, blank=True)
    fotos_requeridas = models.JSONField(default=list, blank=True, help_text="Lista de fotos obligatorias")
    documentos_requeridos = models.JSONField(default=list, blank=True, help_text="Lista de documentos obligatorios")
    
    # 🚀 AHORA SÍ: Los campos en el modelo correcto
    cuotas_a_generar = models.IntegerField(default=6, help_text="Cantidad de cuotas a generar por defecto")
    genera_cupones_robo = models.BooleanField(default=False, help_text="¿Esta cobertura incluye cuponera de robo?")
    
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ['compania__nombre', 'nombre']

    def __str__(self):
        cia_nombre = self.compania.nombre if self.compania else "Sin Cía"
        return f"{self.nombre} ({cia_nombre})"

class Cotizacion(models.Model):
    cliente_nombre = models.CharField(max_length=150)
    telefono = models.CharField(max_length=50, blank=True, null=True)
    marca_auto = models.CharField(max_length=100)
    modelo_auto = models.CharField(max_length=100)
    anio_auto = models.IntegerField()
    tiene_gnc = models.BooleanField(default=False)
    estado = models.CharField(max_length=20, default='PENDIENTE')
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class OpcionCotizacion(models.Model):
    cotizacion = models.ForeignKey(Cotizacion, on_delete=models.CASCADE, related_name='opciones')
    compania = models.ForeignKey(CompaniaSeguro, on_delete=models.RESTRICT, related_name='opciones')
    cobertura = models.ForeignKey(TipoCobertura, on_delete=models.RESTRICT, related_name='opciones')
    costo_compania = models.DecimalField(max_digits=12, decimal_places=2)
    porcentaje_comision = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)
    precio_cliente = models.DecimalField(max_digits=12, decimal_places=2)
    suma_asegurada = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True, default=0)
    detalles_cobertura = models.JSONField(default=list, blank=True)
    es_recomendada = models.BooleanField(default=False)
    objetivo_ganancia = models.DecimalField(max_digits=5, decimal_places=2, default=35.00)

class ConfiguracionGlobal(models.Model):
    margen_ganancia_default = models.DecimalField(max_digits=5, decimal_places=2, default=35.00)
    def save(self, *args, **kwargs):
        self.pk = 1 
        super(ConfiguracionGlobal, self).save(*args, **kwargs)