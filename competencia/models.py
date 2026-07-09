from django.db import models
from clientes.models import Cliente
import re
from urllib.parse import unquote


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


def extract_coords_from_google_maps(url: str):
    """
    Extrae latitud y longitud de una URL de Google Maps.
    Ejemplo:
    https://.../@-34.779551,-58.6344017,15z/...
    """
    if not url:
        return None, None

    try:
        decoded = unquote(url)
        match = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", decoded)
        if not match:
            return None, None

        lat = float(match.group(1))
        lng = float(match.group(2))
        return lat, lng
    except Exception:
        return None, None


class Competidor(TimeStampedModel):
    TIPO_CHOICES = [
        ("productor", "Productor"),
        ("broker", "Broker"),
        ("banco", "Banco"),
        ("online", "Venta online"),
        ("compania_directa", "Compañía directa"),
        ("otro", "Otro"),
    ]

    nombre = models.CharField(max_length=255)

    # ✅ Redes sociales / web en un solo campo simple
    redes = models.TextField(
        blank=True,
        default="",
        help_text="Links o usuarios de redes sociales (Instagram, web, etc.)",
    )

    # El resto queda por compatibilidad, pero el front nuevo no los va a usar
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default="productor")
    descripcion = models.TextField(blank=True)
    nicho_fuerte = models.CharField(max_length=100, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Competidor"
        verbose_name_plural = "Competidores"

    def __str__(self):
        return self.nombre


class CompetidorCanal(TimeStampedModel):
    """
    Redes / canales del competidor (Instagram, Facebook, web, etc.).
    Permite múltiples redes por cada competidor.
    """
    TIPO_CANAL_CHOICES = [
        ("instagram", "Instagram"),
        ("facebook", "Facebook"),
        ("tiktok", "TikTok"),
        ("web", "Página web"),
        ("whatsapp", "WhatsApp"),
        ("linkedin", "LinkedIn"),
        ("otro", "Otro"),
    ]

    competidor = models.ForeignKey(
        Competidor,
        on_delete=models.CASCADE,
        related_name="canales",
    )
    tipo_canal = models.CharField(max_length=20, choices=TIPO_CANAL_CHOICES)
    url_o_user = models.CharField(max_length=255)
    activo = models.BooleanField(default=True)
    notas = models.TextField(blank=True)

    class Meta:
        verbose_name = "Canal del competidor"
        verbose_name_plural = "Canales de competidores"

    def __str__(self):
        return f"{self.competidor.nombre} - {self.tipo_canal}"


class CompetidorUbicacion(TimeStampedModel):
    """
    Punto / sucursal / lugar donde compite el competidor.

    En la práctica, cada fila te da:
    - nombre (viene del Competidor)
    - precio
    - compañía
    - cobertura
    - redes (viene del Competidor)
    - ubicación (dirección + coords)

    ✅ Un mismo competidor puede tener varias coberturas y precios
    creando varias filas con distinto `cobertura` y `precio`.
    """

    competidor = models.ForeignKey(
        Competidor,
        on_delete=models.CASCADE,
        related_name="ubicaciones",
    )

    # Ubicación básica
    # ⚠️ La dejamos opcional porque en el alta rápida solo pegás la URL de Maps
    direccion = models.CharField(max_length=255, blank=True)
    ciudad = models.CharField(max_length=100, blank=True)

    # Info comercial (simplificada)
    compania = models.CharField(max_length=100, blank=True)
    cobertura = models.CharField(max_length=100, blank=True)
    precio = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # Horarios (no los vas a usar en este front, pero se mantienen opcionales)
    horario_desde = models.CharField(max_length=50, blank=True)
    horario_hasta = models.CharField(max_length=50, blank=True)

    # Mapa
    # ⬇️ Aumentamos max_length para permitir URLs largas de Google Maps
    url_maps = models.URLField(max_length=1000, blank=True)
    latitud = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitud = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )

    class Meta:
        verbose_name = "Ubicación del competidor"
        verbose_name_plural = "Ubicaciones de competidores"

    def __str__(self):
        base = self.competidor.nombre
        if self.direccion:
            return f"{base} - {self.direccion}"
        if self.url_maps:
            return f"{base} - {self.url_maps}"
        return base

    def save(self, *args, **kwargs):
        # Si tenemos una URL y aún no hay coordenadas, las intento extraer
        if self.url_maps and (self.latitud is None or self.longitud is None):
            lat, lng = extract_coords_from_google_maps(self.url_maps)
            if lat is not None and lng is not None:
                self.latitud = lat
                self.longitud = lng
        super().save(*args, **kwargs)


class MiPrecioReferencia(TimeStampedModel):
    """
    Tus propios precios de referencia para comparar contra la competencia.

    Ejemplo:
    - cobertura = "Terceros completo"
    - compania = "Allianz"
    - ciudad = "Moreno"
    - precio = 15000
    """
    cobertura = models.CharField(max_length=100)
    compania = models.CharField(max_length=100, blank=True)
    ciudad = models.CharField(max_length=100, blank=True)
    precio = models.DecimalField(max_digits=15, decimal_places=2)
    notas = models.TextField(blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Precio propio de referencia"
        verbose_name_plural = "Precios propios de referencia"

    def __str__(self):
        base = self.cobertura
        if self.compania:
            base = f"{self.compania} - {base}"
        if self.ciudad:
            base = f"{base} ({self.ciudad})"
        return base


class OficinaMapa(TimeStampedModel):
    """
    Tus propias oficinas para mostrarlas en el mismo mapa que la competencia.
    """

    nombre = models.CharField(max_length=255)
    # Podés guardar acá el código interno tipo "1", "2", "3" (5 esquinas, Axion, etc.)
    codigo = models.CharField(max_length=50, blank=True)

    # También opcional por si solo pegás la URL
    direccion = models.CharField(max_length=255, blank=True)
    ciudad = models.CharField(max_length=100, blank=True)

    horario_desde = models.CharField(max_length=50, blank=True)
    horario_hasta = models.CharField(max_length=50, blank=True)

    # Igual que arriba: URLs largas
    url_maps = models.URLField(max_length=1000, blank=True)
    latitud = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitud = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )

    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Oficina propia (mapa)"
        verbose_name_plural = "Oficinas propias (mapa)"

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        if self.url_maps and (self.latitud is None or self.longitud is None):
            lat, lng = extract_coords_from_google_maps(self.url_maps)
            if lat is not None and lng is not None:
                self.latitud = lat
                self.longitud = lng
        super().save(*args, **kwargs)


class OportunidadCompetencia(TimeStampedModel):
    RESULTADO_CHOICES = [
        ("gano_competidor", "Ganó el competidor"),
        ("gano_yo", "Gané yo"),
        ("no_cerro", "No cerró"),
    ]

    MOTIVO_CHOICES = [
        ("precio", "Precio"),
        ("cuotas", "Cuotas / financiación"),
        ("servicio", "Servicio / atención"),
        ("siniestros", "Manejo de siniestros"),
        ("confianza", "Confianza / relación"),
        ("otro", "Otro"),
    ]

    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="oportunidades_competencia",
    )
    competidor = models.ForeignKey(
        Competidor,
        on_delete=models.CASCADE,
        related_name="oportunidades",
    )
    ramo = models.CharField(max_length=50)
    resultado = models.CharField(max_length=20, choices=RESULTADO_CHOICES)
    motivo = models.CharField(max_length=20, choices=MOTIVO_CHOICES, default="otro")
    fecha = models.DateField()
    notas = models.TextField(blank=True)

    class Meta:
        verbose_name = "Oportunidad vs competencia"
        verbose_name_plural = "Oportunidades vs competencia"

    def __str__(self):
        return f"{self.fecha} - {self.ramo} - {self.get_resultado_display()}"
