# siniestros/models.py
from django.db import models
from django.conf import settings

# Importamos los modelos de Cliente y Poliza asumiendo que están en otras apps.
from clientes.models import Cliente
from polizas.models import Poliza


class Siniestro(models.Model):
    CHOICE_RESPONSABILIDAD = [
        ('CHOCO', 'Nuestro asegurado chocó'),
        ('CHOCARON', 'Nuestro asegurado fue chocado'),
        ('ROBO', 'Robo / Hurto'),
        ('INCENDIO', 'Incendio'),
        ('OTRO', 'Otro / Varios'),
    ]

    CHOICE_ESTADO = [
        ('PENDIENTE', 'Falta Documentación'),
        ('DENUNCIADO', 'Denunciado en Cía'),
        ('INSPECCION', 'Inspección Pendiente'),
        ('LIQUIDACION', 'En Liquidación'),
        ('CERRADO', 'Cerrado / Finalizado'),
    ]

    # 🚀 RELACIONES REALES (ForeignKeys)
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='siniestros')
    poliza = models.ForeignKey(Poliza, on_delete=models.CASCADE, related_name='siniestros')

    # 🚗 Datos del Vehículo Asegurado (Al momento del choque)
    marca_auto = models.CharField(max_length=50, blank=True, null=True)
    modelo_auto = models.CharField(max_length=50, blank=True, null=True)
    ano_auto = models.PositiveIntegerField(blank=True, null=True)
    patente = models.CharField(max_length=15, blank=True, null=True)

    # 📝 Datos del Siniestro
    nro_reclamo_cia = models.CharField(max_length=50, blank=True, null=True, help_text="N° de siniestro que da la compañía")
    fecha_siniestro = models.DateField(help_text="Cuándo ocurrió realmente el accidente", null=True, blank=True)
    responsabilidad = models.CharField(max_length=15, choices=CHOICE_RESPONSABILIDAD)
    estado = models.CharField(max_length=15, choices=CHOICE_ESTADO, default='PENDIENTE')
    descripcion = models.TextField()

    # 🛑 Datos del Tercero (Si lo chocaron o chocó a alguien)
    tercero_nombre = models.CharField(max_length=100, blank=True, null=True)
    tercero_telefono = models.CharField(max_length=50, blank=True, null=True)
    tercero_patente = models.CharField(max_length=15, blank=True, null=True)
    tercero_compania = models.CharField(max_length=50, blank=True, null=True)
    tercero_poliza = models.CharField(max_length=50, blank=True, null=True)

    # 🕒 Tiempos de Sistema
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # Autocompletar datos del vehículo desde la póliza si están vacíos.
        if self.poliza_id:
            if not self.marca_auto:
                self.marca_auto = getattr(self.poliza, 'marca', None) or None
            if not self.modelo_auto:
                self.modelo_auto = getattr(self.poliza, 'modelo', None) or None
            if not self.ano_auto:
                self.ano_auto = getattr(self.poliza, 'anio', None) or None
            if not self.patente:
                self.patente = getattr(self.poliza, 'patente', None) or None
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Siniestro {self.id} ({self.get_estado_display()}) - Cliente: {self.cliente}'


class SiniestroEvento(models.Model):
    siniestro = models.ForeignKey(Siniestro, on_delete=models.CASCADE, related_name='eventos')
    fecha_evento = models.DateTimeField()
    descripcion_evento = models.TextField()

    def __str__(self):
        return f'Evento {self.id} - Siniestro: {self.siniestro.id}'


# ──────────────────────────────────────────────────────────────────────
# 📸 NUEVO: Galería de fotos del siniestro
# ──────────────────────────────────────────────────────────────────────
class SiniestroFoto(models.Model):
    """
    Fotos del siniestro almacenadas en Cloudinary.
    El archivo se sube primero desde el frontend a Cloudinary, y acá guardamos
    SOLO la URL pública y el public_id (para poder borrarla después).
    """
    siniestro = models.ForeignKey(
        Siniestro,
        on_delete=models.CASCADE,
        related_name='fotos',
    )

    # URL pública de Cloudinary
    url = models.URLField(max_length=1000)
    # ID interno de Cloudinary (necesario para borrar el archivo del CDN)
    public_id = models.CharField(max_length=255)

    # Metadatos opcionales
    nombre = models.CharField(max_length=255, blank=True, default='')
    mime = models.CharField(max_length=100, blank=True, default='image/jpeg')
    descripcion = models.TextField(blank=True, default='')

    # Trazabilidad
    subida_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='siniestro_fotos_subidas',
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_creacion', '-id']
        verbose_name = 'Foto de siniestro'
        verbose_name_plural = 'Fotos de siniestros'

    def __str__(self):
        return f'Foto #{self.id} de Siniestro {self.siniestro_id}'