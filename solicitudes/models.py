from django.db import models
from django.utils import timezone
from datetime import timedelta

# 🚀 IMPORTAMOS OFICINA PARA EL BLINDAJE MULTI-TENANT
from usuarios.models import Oficina

class EstadoSolicitud(models.TextChoices):
    BORRADOR = "BORRADOR", "Borrador"
    EN_REVISION = "EN_REVISION", "En revisión"
    VIGENTE_24H = "VIGENTE_24H", "Constancia 12 h vigente"
    CONVERTIDA = "CONVERTIDA", "Convertida a póliza"
    VENCIDA = "VENCIDA", "Vencida"
    CANCELADA = "CANCELADA", "Cancelada"
    TERMINADA = "TERMINADA", "Terminada"


class MotivoSolicitud(models.TextChoices):
    ALTA_POLIZA = "ALTA_POLIZA", "Alta de póliza"
    # 🔧 ASISTENCIA_GRUA se sacó: el feature de Grúas ya no existe en Polizando.
    OTRO = "OTRO", "Otro"


class TipoDocSolicitud(models.TextChoices):
    # ---------------- Documentación del cliente ----------------
    DNI_FRENTE = "DNI_FRENTE", "DNI (frente)"
    DNI_DORSO = "DNI_DORSO", "DNI (dorso)"
    PASAPORTE_FRENTE = "PASAPORTE_FRENTE", "Pasaporte (frente)"
    PASAPORTE_DORSO = "PASAPORTE_DORSO", "Pasaporte (dorso)"

    # ---------------- Documentos del vehículo ----------------
    CEDULA_VERDE = "CEDULA_VERDE", "Cédula verde"
    CEDULA_VERDE_FRENTE = "CEDULA_VERDE_FRENTE", "Cédula Verde (frente)"
    CEDULA_VERDE_DORSO = "CEDULA_VERDE_DORSO", "Cédula Verde (dorso)"

    CEDULA_AZUL = "CEDULA_AZUL", "Cédula azul"
    CEDULA_AZUL_FRENTE = "CEDULA_AZUL_FRENTE", "Cédula Azul (frente)"
    CEDULA_AZUL_DORSO = "CEDULA_AZUL_DORSO", "Cédula Azul (dorso)"

    TITULO = "TITULO", "Título"

    # ---------------- Fotos del vehículo ----------------
    PATENTE = "PATENTE", "Foto patente"
    FRENTE = "FRENTE", "Frente vehículo"
    LATERAL_IZQ = "LATERAL_IZQ", "Lateral izquierdo"
    LATERAL_DER = "LATERAL_DER", "Lateral derecho"
    TRASERA = "TRASERA", "Trasera"
    EQUIPO_GNC = "EQUIPO_GNC", "Equipo GNC"
    OBLEA_GNC = "OBLEA_GNC", "Oblea GNC"

    OTRO = "OTRO", "Otro"


DOCS_CLIENTE_SET = {
    TipoDocSolicitud.DNI_FRENTE,
    TipoDocSolicitud.DNI_DORSO,
    TipoDocSolicitud.PASAPORTE_FRENTE,
    TipoDocSolicitud.PASAPORTE_DORSO,
}

DOCS_VEHICULO_SET = {
    TipoDocSolicitud.CEDULA_VERDE,
    TipoDocSolicitud.CEDULA_VERDE_FRENTE,
    TipoDocSolicitud.CEDULA_VERDE_DORSO,
    TipoDocSolicitud.CEDULA_AZUL,
    TipoDocSolicitud.CEDULA_AZUL_FRENTE,
    TipoDocSolicitud.CEDULA_AZUL_DORSO,
    TipoDocSolicitud.TITULO,
}

FOTOS_VEHICULO_SET = {
    TipoDocSolicitud.PATENTE,
    TipoDocSolicitud.FRENTE,
    TipoDocSolicitud.LATERAL_IZQ,
    TipoDocSolicitud.LATERAL_DER,
    TipoDocSolicitud.TRASERA,
    TipoDocSolicitud.EQUIPO_GNC,
    TipoDocSolicitud.OBLEA_GNC,
}

TIPOS_REQUIEREN_VTO_SET = set()

_now = timezone.now

def now():
    return _now()


# ---------------- Catálogo de Empleados (Responsables) ----------------
class Empleado(models.Model):
    nombre = models.CharField(max_length=80, db_index=True)
    
    # 🚀 VÍNCULO MULTI-TENANT: Cada responsable pertenece a una oficina específica
    oficina = models.ForeignKey(
        Oficina, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='empleados_solicitudes'
    )
    
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(default=now)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nombre"]
        # 🔒 Evitamos nombres duplicados dentro de la misma sucursal
        # (dejado tal cual a pedido — ver nota en la auditoría de Solicitudes
        # sobre el comportamiento de NULL en unique_together con Postgres)
        unique_together = ('nombre', 'oficina')

    def __str__(self):
        ofi_tag = f" [{self.oficina.codigo}]" if self.oficina else ""
        return f"{self.nombre}{ofi_tag}"

    def save(self, *args, **kwargs):
        if self.nombre:
            self.nombre = " ".join(str(self.nombre).strip().split()).upper()
        super().save(*args, **kwargs)


class SolicitudSeguro(models.Model):
    codigo = models.CharField(max_length=32, unique=True, blank=True)

    cliente_nombre = models.CharField(max_length=128, blank=True)
    cliente_dni = models.CharField(max_length=32, blank=True)
    telefono = models.CharField(
        max_length=32,
        null=True,
        blank=True,
        help_text="Teléfono del cliente (WhatsApp / E.164 o similar)",
    )

    vehiculo_marca = models.CharField(max_length=64, blank=True)
    vehiculo_modelo = models.CharField(max_length=64, blank=True)
    vehiculo_anio = models.PositiveIntegerField(null=True, blank=True)
    vehiculo_patente = models.CharField(max_length=16, blank=True)
    vehiculo_vin = models.CharField(max_length=32, blank=True)

    cobertura_solicitada = models.CharField(max_length=128, blank=True)
    compania_preferida = models.CharField(max_length=64, blank=True)

    # 🏢 CAMBIO CLAVE PARA VISIBILIDAD: Relación ForeignKey real para el Escudo Multi-tenant
    oficina = models.ForeignKey(
        Oficina, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="solicitudes_sucursal"
    )

    motivo = models.CharField(
        max_length=20,
        choices=MotivoSolicitud.choices,
        default=MotivoSolicitud.ALTA_POLIZA,
        db_index=True,
    )

    estado = models.CharField(max_length=16, choices=EstadoSolicitud.choices, default=EstadoSolicitud.BORRADOR)
    inicio = models.DateTimeField(null=True, blank=True)
    fin = models.DateTimeField(null=True, blank=True)

    responsable_nombre = models.CharField(
        max_length=80,
        db_index=True,
        help_text="Nombre de quien carga la solicitud (obligatorio)",
        blank=True,
    )
    asignado_en = models.DateTimeField(null=True, blank=True)
    responsable_empleado = models.ForeignKey(
        Empleado, null=True, blank=True, on_delete=models.SET_NULL, related_name="solicitudes"
    )

    responsable = models.CharField(max_length=80, blank=True, db_index=True)
    qr_payload = models.URLField(max_length=512, blank=True)
    poliza_id = models.IntegerField(null=True, blank=True)
    observaciones = models.TextField(blank=True)
    prioridad = models.CharField(max_length=16, default="NORMAL", blank=True)

    alta_compania = models.BooleanField(
        default=False, db_index=True, help_text="Marcada cuando ya se dio el alta en la compañía"
    )
    enviar_poliza = models.BooleanField(
        default=False, db_index=True, help_text="Marcada cuando se envió la póliza al cliente"
    )

    terminada_en = models.DateTimeField(null=True, blank=True)

    creado_en = models.DateTimeField(default=now)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-creado_en"]
        indexes = [
            models.Index(fields=["motivo", "estado"]),
            models.Index(fields=["responsable", "estado"]),
            models.Index(fields=["responsable_nombre", "estado"]),
            models.Index(fields=["estado", "alta_compania"]),
            models.Index(fields=["estado", "enviar_poliza"]),
            models.Index(fields=["oficina", "estado"]),
        ]

    def __str__(self):
        return self.codigo or f"Solicitud #{self.pk}"

    @property
    def cliente(self):
        return None

    @property
    def vigente(self):
        now_ = _now()
        return self.estado == EstadoSolicitud.VIGENTE_24H and (self.fin and self.fin > now_)

    @property
    def asignada(self):
        return bool(self.responsable_nombre or self.responsable)

    def fotos_obligatorias(self) -> set[str]:
        return set()

    def emitir_constancia_24h(self, base_verify_url="/public/solicitudes"):
        now_ = _now()
        self.inicio = now_
        self.fin = now_ + timedelta(hours=12)
        self.estado = EstadoSolicitud.VIGENTE_24H
        if not self.codigo:
            super().save()
            self.codigo = f"ST-{now_:%Y%m}-{self.id:06d}"
        base = (base_verify_url or "/public/solicitudes").rstrip("/")
        self.qr_payload = f"{base}/{self.id}/verificar/"
        return self

    def _match_empleado(self, nombre: str):
        n = (nombre or "").strip()
        if not n:
            return None
        try:
            # 🚀 El match ahora debería ser consciente de la oficina
            return Empleado.objects.filter(activo=True).only("id", "nombre").get(nombre__iexact=n)
        except Empleado.DoesNotExist:
            return None

    def tomar(self, nombre: str) -> bool:
        if self.responsable_nombre or self.responsable:
            return False
        emp = self._match_empleado(nombre)
        self.responsable_empleado = emp
        self.responsable_nombre = (nombre or "").strip()
        self.responsable = self.responsable_nombre
        self.asignado_en = _now() if self.responsable_nombre else None
        return True

    def reasignar(self, nombre: str):
        emp = self._match_empleado(nombre)
        self.responsable_empleado = emp
        self.responsable_nombre = (nombre or "").strip()
        self.responsable = self.responsable_nombre
        self.asignado_en = _now() if self.responsable_nombre else None
        return self

    def caducar_si_corresponde(self):
        now_ = _now()
        if self.estado == EstadoSolicitud.VIGENTE_24H and self.fin and self.fin <= now_:
            self.estado = EstadoSolicitud.VENCIDA

    def documentos_queryset(self):
        return self.documentos.all()

    def documentos_por_tipo(self):
        out = {}
        for doc in self.documentos_queryset():
            out.setdefault(doc.tipo, []).append(doc)
        return out

    def fotos_vehiculo(self):
        return self.documentos.filter(tipo__in=FOTOS_VEHICULO_SET)

    def documentos_vehiculo(self):
        return self.documentos.filter(tipo__in=DOCS_VEHICULO_SET)

    def documentos_cliente(self):
        return self.documentos.filter(tipo__in=DOCS_CLIENTE_SET)

    def get_foto_frente(self):
        return self.documentos.filter(tipo=TipoDocSolicitud.FRENTE).order_by("-creado_en").first()

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if not self.responsable_nombre and self.responsable:
            self.responsable_nombre = self.responsable
        if not self.responsable_nombre:
            self.asignado_en = None
            self.responsable_empleado = None
            self.responsable = ""
        else:
            self.responsable = self.responsable_nombre

        self.caducar_si_corresponde()

        super().save(*args, **kwargs)

        if is_new and not self.codigo:
            self.codigo = f"ST-{_now():%Y%m}-{self.id:06d}"
            super().save(update_fields=["codigo"])


class SolicitudDocumento(models.Model):
    solicitud = models.ForeignKey(SolicitudSeguro, on_delete=models.CASCADE, related_name="documentos")
    tipo = models.CharField(max_length=32, choices=TipoDocSolicitud.choices, default=TipoDocSolicitud.OTRO)
    url = models.URLField(max_length=512)
    public_id = models.CharField(max_length=256, blank=True, db_index=True)
    nombre = models.CharField(max_length=128, blank=True)
    mime = models.CharField(max_length=64, blank=True)
    vencimiento = models.DateField(null=True, blank=True)
    notas = models.CharField(max_length=256, blank=True)
    creado_en = models.DateTimeField(default=now)

    class Meta:
        ordering = ["-creado_en"]
        indexes = [
            models.Index(fields=["solicitud", "tipo"]),
            models.Index(fields=["tipo"]),
            models.Index(fields=["solicitud", "public_id"]),
        ]

    def requiere_vencimiento(self) -> bool:
        return self.tipo in TIPOS_REQUIEREN_VTO_SET

    def es_foto_vehiculo(self) -> bool:
        return self.tipo in FOTOS_VEHICULO_SET

    def es_doc_vehiculo(self) -> bool:
        return self.tipo in DOCS_VEHICULO_SET

    def es_doc_cliente(self) -> bool:
        return self.tipo in DOCS_CLIENTE_SET

    def __str__(self):
        return f"{self.tipo} - {self.nombre or self.public_id or self.id}"