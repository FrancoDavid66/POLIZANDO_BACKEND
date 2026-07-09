# gruas/models.py
from datetime import timedelta

from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError

POLIZA_FK = "polizas.Poliza"


def _is_bad_local_url(url: str) -> bool:
    u = (url or "").strip().lower()
    if not u:
        return False
    return (
        u.startswith("/media/")
        or u.startswith("media/")
        or "localhost" in u
        or "127.0.0.1" in u
        or u.startswith("http://localhost")
        or u.startswith("http://127.0.0.1")
    )


class PlanGrua(models.Model):
    nombre = models.CharField(max_length=120)
    km_incluidos = models.PositiveIntegerField(default=100)
    precio_mensual = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # ✅ por ahora (sin CRUD de proveedores): texto opcional
    proveedor_nombre = models.CharField(max_length=120, blank=True, default="")

    activo = models.BooleanField(default=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.nombre} ({self.km_incluidos} km)"


class ProveedorGrua(models.Model):
    """
    CRUD Proveedores (chofer + camión + documentos).
    IMPORTANTE: Archivos se suben a Cloudinary desde el FRONT.
    En backend guardamos URL + public_id.
    """

    nombre = models.CharField(max_length=160)

    # ✅ NUEVO: teléfono del proveedor (para WhatsApp / llamadas)
    telefono = models.CharField(max_length=40, blank=True, default="")

    patente_camion = models.CharField(max_length=20, db_index=True)
    modelo_camion = models.CharField(max_length=120, blank=True, default="")
    anio_camion = models.PositiveIntegerField(default=0)

    # 2 fotos del camión
    foto_camion_1_url = models.URLField(blank=True, default="")
    foto_camion_1_public_id = models.CharField(max_length=255, blank=True, default="")
    foto_camion_2_url = models.URLField(blank=True, default="")
    foto_camion_2_public_id = models.CharField(max_length=255, blank=True, default="")

    # licencia + vtv
    licencia_url = models.URLField(blank=True, default="")
    licencia_public_id = models.CharField(max_length=255, blank=True, default="")
    vtv_url = models.URLField(blank=True, default="")
    vtv_public_id = models.CharField(max_length=255, blank=True, default="")

    activo = models.BooleanField(default=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["patente_camion"]),
            models.Index(fields=["activo", "creado_en"]),
            models.Index(fields=["telefono"]),
        ]

    def clean(self):
        # año razonable
        y = int(self.anio_camion or 0)
        current = timezone.localdate().year
        if y and (y < 1950 or y > current + 1):
            raise ValidationError({"anio_camion": "Año inválido"})

        # no aceptar urls locales
        for f in [
            "foto_camion_1_url",
            "foto_camion_2_url",
            "licencia_url",
            "vtv_url",
        ]:
            if _is_bad_local_url(getattr(self, f, "")):
                raise ValidationError({f: "URL inválida (no /media ni localhost). Usar Cloudinary."})

        # si hay url => public_id obligatorio
        pairs = [
            ("foto_camion_1_url", "foto_camion_1_public_id"),
            ("foto_camion_2_url", "foto_camion_2_public_id"),
            ("licencia_url", "licencia_public_id"),
            ("vtv_url", "vtv_public_id"),
        ]
        for url_f, pid_f in pairs:
            url = (getattr(self, url_f, "") or "").strip()
            pid = (getattr(self, pid_f, "") or "").strip()
            if url and not pid:
                raise ValidationError({pid_f: "public_id requerido si hay URL (Cloudinary)."})

    def __str__(self) -> str:
        pat = (self.patente_camion or "").strip().upper()
        return f"{self.nombre} - {pat}"


class AdhesionGrua(models.Model):
    ESTADOS = (
        ("ACTIVA", "ACTIVA"),
        ("PAUSADA", "PAUSADA"),
        ("CANCELADA", "CANCELADA"),
        ("VENCIDA", "VENCIDA"),
    )

    poliza = models.ForeignKey(
        POLIZA_FK, on_delete=models.CASCADE, related_name="adhesiones_grua"
    )
    plan = models.ForeignKey(PlanGrua, on_delete=models.PROTECT, related_name="adhesiones")

    estado = models.CharField(max_length=12, choices=ESTADOS, default="ACTIVA")

    # fecha de alta operativa (puede ser anterior a hoy)
    fecha_activacion = models.DateField(default=timezone.localdate)

    # carencia: se calcula como fecha_activacion + carencia_dias
    carencia_dias = models.PositiveIntegerField(default=15)

    # para trazabilidad
    motivo_cancelacion = models.TextField(blank=True, default="")
    cancelada_en = models.DateTimeField(null=True, blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["poliza", "estado"]),
            models.Index(fields=["estado", "fecha_activacion"]),
        ]

    def clean(self):
        if int(self.carencia_dias or 0) < 0:
            raise ValidationError("carencia_dias inválido")

    @property
    def fecha_carencia_fin(self):
        return self.fecha_activacion + timedelta(days=int(self.carencia_dias or 0))

    def __str__(self) -> str:
        return f"Adhesión {self.id} - póliza {self.poliza_id} - {self.estado}"


# ============================================================
# ✅ SOLICITUDES
# ============================================================

class SolicitudGrua(models.Model):
    ESTADOS = (
        ("ABIERTA", "ABIERTA"),
        ("ASIGNADA", "ASIGNADA"),
        ("EN_CAMINO", "EN_CAMINO"),
        ("CERRADA", "CERRADA"),
        ("CANCELADA", "CANCELADA"),
    )

    # La solicitud SIEMPRE pertenece a una adhesión y una póliza (redundante pero útil)
    adhesion = models.ForeignKey(
        AdhesionGrua, on_delete=models.CASCADE, related_name="solicitudes"
    )
    poliza = models.ForeignKey(
        POLIZA_FK, on_delete=models.CASCADE, related_name="solicitudes_grua"
    )

    proveedor = models.ForeignKey(
        ProveedorGrua, on_delete=models.SET_NULL, null=True, blank=True, related_name="solicitudes"
    )

    estado = models.CharField(max_length=12, choices=ESTADOS, default="ABIERTA")

    motivo = models.CharField(max_length=160, blank=True, default="")
    notas = models.TextField(blank=True, default="")

    # Origen
    origen_direccion = models.CharField(max_length=220, blank=True, default="")
    origen_localidad = models.CharField(max_length=120, blank=True, default="")  # ✅ NUEVO
    origen_maps_url = models.URLField(blank=True, default="", max_length=1000)

    origen_lat = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    origen_lng = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)

    # Destino
    destino_direccion = models.CharField(max_length=220, blank=True, default="")
    destino_localidad = models.CharField(max_length=120, blank=True, default="")  # ✅ NUEVO
    destino_maps_url = models.URLField(blank=True, default="", max_length=1000)

    destino_lat = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    destino_lng = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)

    # cálculo
    km_estimados = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # timestamps
    asignada_en = models.DateTimeField(null=True, blank=True)
    cerrada_en = models.DateTimeField(null=True, blank=True)
    cancelada_en = models.DateTimeField(null=True, blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["estado", "creado_en"]),
            models.Index(fields=["poliza", "estado"]),
            models.Index(fields=["proveedor", "estado"]),
        ]

    def clean(self):
        # urls locales prohibidas
        for f in ["origen_maps_url", "destino_maps_url"]:
            if _is_bad_local_url(getattr(self, f, "")):
                raise ValidationError({f: "URL inválida (no /media ni localhost)."})

        # coherencia mínima: la póliza debe coincidir con la adhesión
        if self.adhesion_id and self.poliza_id and self.adhesion.poliza_id != self.poliza_id:
            raise ValidationError("La póliza no coincide con la adhesión.")

    def __str__(self) -> str:
        return f"Solicitud {self.id} - {self.estado}"


class SolicitudFoto(models.Model):
    TIPOS = (
        ("AUTO", "AUTO"),       # 4 fotos del auto
        ("LUGAR", "LUGAR"),     # 2 fotos del lugar
        ("REGISTRO", "REGISTRO"),  # 1 foto
        ("DNI", "DNI"),         # 1 foto
    )

    solicitud = models.ForeignKey(
        SolicitudGrua, on_delete=models.CASCADE, related_name="fotos"
    )

    tipo = models.CharField(max_length=12, choices=TIPOS)
    url = models.URLField()
    public_id = models.CharField(max_length=255)

    descripcion = models.CharField(max_length=180, blank=True, default="")

    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["solicitud", "tipo"]),
        ]

    def clean(self):
        if _is_bad_local_url(self.url):
            raise ValidationError({"url": "URL inválida (no /media ni localhost). Usar Cloudinary."})
        if not (self.public_id or "").strip():
            raise ValidationError({"public_id": "public_id requerido (Cloudinary)."})

    def __str__(self) -> str:
        return f"Foto {self.id} ({self.tipo})"


class SolicitudEvento(models.Model):
    solicitud = models.ForeignKey(
        SolicitudGrua, on_delete=models.CASCADE, related_name="eventos"
    )
    tipo = models.CharField(max_length=40)  # ej: "CREADA", "ASIGNADA", "ESTADO", "CERRADA"
    detalle = models.TextField(blank=True, default="")
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["solicitud", "creado_en"]),
        ]

    def __str__(self) -> str:
        return f"Evento {self.tipo} - Solicitud {self.solicitud_id}"
