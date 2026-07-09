# geo/models.py
from django.db import models


class GeoItem(models.Model):
    TIPO_CHOICES = [
        ("cliente", "Cliente"),
        ("prospecto", "Prospecto"),
        ("oficina_rival", "Oficina rival"),
        ("cartel", "Cartel / publicidad"),
        ("alquiler_disponible", "Alquiler disponible"),
        ("potencial", "Ubicación potencial"),
    ]

    nombre = models.CharField(max_length=150)
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES)

    # Dirección textual (opcional)
    direccion = models.CharField(max_length=255, blank=True)

    # Coordenadas (pueden venir parseadas desde la URL de Google Maps)
    lat = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
    )
    lng = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
    )

    # Nota libre
    nota = models.TextField(blank=True)

    # Activo / inactivo
    activo = models.BooleanField(default=True)

    # Solo para ordenar por fecha si hace falta
    creado_en = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.nombre}"
