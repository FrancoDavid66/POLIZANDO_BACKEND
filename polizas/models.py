# polizas/models.py
from datetime import timedelta
import uuid

from django.db import models
from django.db.models import Min, Max
from django.utils import timezone
from django.utils.crypto import get_random_string  # para generar número único

from clientes.models import Cliente

# 🚀 IMPORTAMOS LOS MODELOS REALES DE COTIZACIONES
from cotizaciones.models import CompaniaSeguro, TipoCobertura


# -------------------- Matcheo contra el catálogo (anti-duplicados) --------------------
# 🔧 Antes de crear una compañía/cobertura NUEVA, busca si ya existe en el catálogo
#    comparando nombres normalizados (sin acentos, sin mayúsculas, sin sufijos tipo
#    'SEGUROS'/'S.A.', sin puntuación). Así 'EQUIDAD SEGUROS S.A.' matchea 'Equidad'
#    y NO se duplica. Solo crea si realmente no existe.
import re as _re
import unicodedata as _ud

_STOP_CIA = {
    "seguros", "seguro", "aseguradora", "cia", "compania",
    "sa", "srl", "sociedad", "anonima", "la", "el", "los", "las",
}


def _strip_accents(s):
    return "".join(ch for ch in _ud.normalize("NFD", str(s or "")) if _ud.category(ch) != "Mn")


def _merge_singletons(toks):
    """Une corridas de letras sueltas: ["a","t","m"] -> ["atm"]; ["c","1"] -> ["c1"]."""
    out, buf = [], []
    for t in toks:
        if len(t) == 1:
            buf.append(t)
        else:
            if buf:
                out.append("".join(buf)); buf = []
            out.append(t)
    if buf:
        out.append("".join(buf))
    return out


def _norm_cia(s):
    base = _re.sub(r"[^a-z0-9]+", " ", _strip_accents(s).lower())
    toks = _merge_singletons(base.split())
    toks = [t for t in toks if t not in _STOP_CIA]
    return " ".join(toks)


def _norm_cob(s):
    base = _re.sub(r"[^a-z0-9]+", " ", _strip_accents(s).lower())
    return " ".join(_merge_singletons(base.split()))


def _match_compania_obj(nombre):
    """Devuelve una CompaniaSeguro existente que matchee (exacto o normalizado), o None."""
    raw = str(nombre or "").strip()
    if not raw:
        return None
    exacto = CompaniaSeguro.objects.filter(nombre__iexact=raw).order_by("id").first()
    if exacto:
        return exacto
    objetivo = _norm_cia(raw)
    if not objetivo:
        return None
    for c in CompaniaSeguro.objects.all().order_by("id"):
        if _norm_cia(c.nombre) == objetivo:
            return c
    return None


def _match_cobertura_obj(nombre, compania_obj):
    """Busca TipoCobertura existente (exacto o normalizado) DENTRO de la compañía dada."""
    raw = str(nombre or "").strip()
    if not raw:
        return None
    base = TipoCobertura.objects.all()
    if compania_obj is not None:
        base = base.filter(compania=compania_obj)
    exacto = base.filter(nombre__iexact=raw).order_by("id").first()
    if exacto:
        return exacto
    objetivo = _norm_cob(raw)
    if not objetivo:
        return None
    for c in base.order_by("id"):
        if _norm_cob(c.nombre) == objetivo:
            return c
    return None


# -------------------- QuerySet utilitario para filtros por fecha de vencimiento --------------------
class PolizaQuerySet(models.QuerySet):
    def vencimiento_entre(self, desde=None, hasta=None):
        qs = self
        if desde:
            qs = qs.filter(fecha_vencimiento__gte=desde)
        if hasta:
            qs = qs.filter(fecha_vencimiento__lte=hasta)
        return qs

    def vencidas_en_ultimos_dias(self, dias: int):
        hoy = timezone.localdate()
        limite = hoy - timedelta(days=int(dias))
        return self.filter(estado="vencida", fecha_vencimiento__gte=limite, fecha_vencimiento__lte=hoy)

    def vencidas_hace_mas_de(self, dias: int):
        hoy = timezone.localdate()
        limite = hoy - timedelta(days=int(dias))
        return self.filter(estado="vencida", fecha_vencimiento__lt=limite)


class PolizaFase(models.TextChoices):
    PRELIMINAR = "PRELIMINAR", "Preliminar"
    DEFINITIVA = "DEFINITIVA", "Definitiva"


class Poliza(models.Model):
    ESTADO_CHOICES = [
        ("activa",           "Activa"),
        ("vencida",          "Vencida"),
        ("cancelada",        "Cancelada"),
        ("finalizada",       "Finalizada"),
        ("en_verificacion",  "En verificación"),
    ]

    class MotivoBaja(models.TextChoices):
        INCUMPLIMIENTO_PAGO = "INCUMPLIMIENTO_PAGO", "Incumplimiento de pago"
        MIGRACION_COMPANIA  = "MIGRACION_COMPANIA",  "Migración a otra compañía"
        VENTA_VEHICULO      = "VENTA_VEHICULO",      "Venta del vehículo"
        SIN_USO             = "SIN_USO",             "Sin uso"
        OTRO                = "OTRO",                "Otro"

    # ── Motivos por los que un cliente NO renueva (uso operativo en la bandeja de renovaciones) ──
    class MotivoNoRenueva(models.TextChoices):
        CAMBIO_COMPANIA = "CAMBIO_COMPANIA", "Cambió de compañía"
        VENDIO_AUTO     = "VENDIO_AUTO",     "Vendió el auto"
        NO_QUIERE       = "NO_QUIERE",       "No quiere seguir"
        NO_CONTESTA     = "NO_CONTESTA",     "No contesta"
        NO_PAGO         = "NO_PAGO",         "No pagó"
        OTRO            = "OTRO",            "Otro"

    TIPO_VEHICULO_CHOICES = [
        ("Auto", "Auto"),
        ("Camioneta", "Camioneta"),
        ("Camion", "Camión"),
        ("Moto", "Moto"),
        ("Trailer", "Trailer"),
    ]

    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name="polizas", db_index=True)

    # 🚀 Mantenemos los campos de texto por compatibilidad con datos viejos
    compania = models.CharField(max_length=100, blank=True, null=True)
    cobertura = models.CharField(max_length=100, blank=True, null=True)

    # 🚀 VINCULAMOS AL CATÁLOGO REAL DE COTIZACIONES
    compania_obj = models.ForeignKey(CompaniaSeguro, on_delete=models.SET_NULL, null=True, blank=True, related_name="polizas")
    cobertura_obj = models.ForeignKey(TipoCobertura, on_delete=models.SET_NULL, null=True, blank=True, related_name="polizas")

    # ----- NÚMERO OPCIONAL + FLAG "SIN NÚMERO" -----
    numero_poliza = models.CharField(max_length=50, unique=True, null=True, blank=True)
    sin_numero = models.BooleanField(
        default=False,
        help_text="Marcar mientras la póliza aún no tiene número asignado por la compañía.",
    )

    # 🚀 VÍNCULO CON OFICINA (Multi-tenant)
    # 🔧 FIX SEGURIDAD: removido `default=1`. Antes apuntaba a una oficina específica
    # que si se borraba dejaba pólizas huérfanas y rompía la app. Ahora el campo
    # queda en NULL y la oficina se inyecta desde el backend al crear (ver create()
    # en PolizaViewSet, que asigna user.perfil.oficina automáticamente para no-admins).
    oficina = models.ForeignKey(
        'usuarios.Oficina',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='polizas_ficha',
    )

    # 🚀 VÍNCULO CON EL VENDEDOR (Sistema de Afiliados)
    vendedor = models.ForeignKey(
        'usuarios.Perfil',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='polizas_vendidas',
        help_text="El vendedor externo asociado a esta póliza."
    )

    patente = models.CharField(max_length=50, db_index=True)
    marca = models.CharField(max_length=100)
    modelo = models.CharField(max_length=100)
    anio = models.IntegerField()
    tipo = models.CharField(max_length=20, choices=TIPO_VEHICULO_CHOICES, default="Auto")

    # 🚀 Datos técnicos del vehículo (cargados en la solicitud)
    # Quedan opcionales a nivel base de datos para no romper pólizas existentes;
    # la obligatoriedad se controla en el formulario del frontend.
    numero_motor = models.CharField(max_length=50, blank=True, default="")
    numero_chasis = models.CharField(max_length=50, blank=True, default="")
    combustible = models.CharField(max_length=20, blank=True, default="")
    carroceria = models.CharField(max_length=40, blank=True, default="")
    observaciones = models.TextField(blank=True, default="")

    precio_cuota = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cantidad_cuotas = models.IntegerField(default=1)
    primer_pago = models.DateField()
    fecha_vencimiento = models.DateField(db_index=True)
    dias_a_vencer = models.IntegerField()
    fecha_emision = models.DateField()

    # 🕒 Timestamp REAL de creación del registro (cuándo se cargó la póliza en el
    # sistema). Distinto de fecha_emision (que es pago + 1 día). Sirve para contar
    # altas/renovaciones "del día" sin el desfase de la emisión.
    creado_en = models.DateTimeField(default=timezone.now, db_index=True)

    # 📤 Envío de la póliza al cliente (para el panel de "Tareas del día").
    # El empleado tilda cuando ya le mandó la póliza al cliente.
    poliza_enviada = models.BooleanField(
        default=False, db_index=True,
        help_text="True si ya se le envió la póliza al cliente.",
    )
    poliza_enviada_en = models.DateTimeField(null=True, blank=True)

    # Gestión y documentos
    alertas = models.TextField(blank=True)
    archivo_poliza = models.FileField(upload_to="polizas/documentos/", blank=True, null=True)

    # Estado operativo
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default="activa", db_index=True)

    # Fase
    fase = models.CharField(
        max_length=11,
        choices=PolizaFase.choices,
        default=PolizaFase.PRELIMINAR,
        db_index=True,
    )

    # Datos de baja/cancelación
    fecha_baja = models.DateField(null=True, blank=True)
    motivo_baja = models.CharField(max_length=40, choices=MotivoBaja.choices, null=True, blank=True)
    observaciones_baja = models.TextField(blank=True, default="")

    # Renovación — permite distinguir pólizas renovadas de altas nuevas
    es_renovacion = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True si esta póliza fue creada como renovación de otra existente.",
    )
    poliza_origen = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="renovaciones_generadas",
        help_text="Póliza original de la que se renovó esta.",
    )

    # ── GESTIÓN DE BANDEJA DE RENOVACIONES (no afectan la póliza, solo el flujo del operador) ──

    # ✓ Verificada: el operador la revisó y la deja en la lista como "ya la chequeé"
    renovacion_verificada = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True si el operador marcó la póliza como verificada en la bandeja de renovaciones.",
    )
    renovacion_verificada_en = models.DateTimeField(
        null=True, blank=True,
        help_text="Cuándo se marcó como verificada.",
    )

    # ✗ Descartada: el cliente NO va a renovar. NO toca el estado real de la póliza.
    renovacion_descartada = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True si el operador marcó que el cliente no va a renovar.",
    )
    renovacion_descartada_motivo = models.CharField(
        max_length=30,
        choices=MotivoNoRenueva.choices,
        null=True, blank=True,
        help_text="Motivo por el que no renueva.",
    )
    renovacion_descartada_detalle = models.TextField(
        blank=True, default="",
        help_text="Detalle adicional (texto libre cuando el motivo es 'Otro').",
    )
    renovacion_descartada_en = models.DateTimeField(
        null=True, blank=True,
        help_text="Cuándo se marcó como no-renueva.",
    )

    # ── VERIFICACIÓN CON LA COMPAÑÍA ──────────────────────────────────────────
    # Bandeja manual: confirmar que la póliza existe y está vigente en la aseguradora.
    # Estados: "" (sin verificar → entra a la pila) | "OK" (verificada) | "NO_FIGURA" (no existe / datos no coinciden)
    verificacion_compania = models.CharField(
        max_length=10,
        choices=[
            ("OK", "Verificada en la compañía"),
            ("NO_FIGURA", "No figura en la compañía"),
        ],
        blank=True,
        default="",
        db_index=True,
        help_text="Resultado de la verificación manual contra el portal de la compañía.",
    )
    verificacion_compania_en = models.DateTimeField(
        null=True, blank=True,
        help_text="Cuándo se marcó la verificación con la compañía.",
    )

    # Foto de perfil
    foto_perfil_url = models.TextField(blank=True, default="")
    foto_perfil_public_id = models.CharField(max_length=200, blank=True, default="")

    # 🔗 Token único para el link público de cupones de robo.
    # El cliente entra a /cupon/<token> y confirma sus pagos SIN usuario ni contraseña.
    token_portal = models.UUIDField(
        default=uuid.uuid4, unique=True, editable=False, db_index=True,
        help_text="Token para el link público donde el cliente confirma pagos de cupones.",
    )

    # Manager
    objects = PolizaQuerySet.as_manager()

    class Meta:
        indexes = [
            models.Index(fields=["estado", "fecha_vencimiento"]),
            models.Index(fields=["cliente", "estado"]),
            models.Index(fields=["patente", "estado"]),
            models.Index(fields=["cliente", "fecha_vencimiento"]),
            models.Index(fields=["fase", "estado"]),
            models.Index(fields=["sin_numero", "estado"]),
            models.Index(fields=["cliente", "patente"]),
            models.Index(fields=["oficina"]),
        ]

    @classmethod
    def generar_numero_poliza(cls) -> str:
        ts = timezone.now().strftime("%Y%m%d%H%M%S")
        sufijo = get_random_string(4, allowed_chars="0123456789")
        return f"SN-{ts}-{sufijo}"

    def save(self, *args, **kwargs):
        # 🚀 AUTO-SINCRONIZADOR AL CATÁLOGO REAL DE COTIZACIONES
        if self.compania_obj_id:
            # Si el frontend mandó el ID, copiamos el nombre al campo viejo
            self.compania = self.compania_obj.nombre
        elif self.compania:
            # Si el frontend mandó solo texto, buscamos o creamos el objeto Compañía
            c_nom = str(self.compania).strip()
            comp = _match_compania_obj(c_nom)
            if not comp:
                comp = CompaniaSeguro.objects.create(nombre=c_nom)
            self.compania_obj = comp
            self.compania = comp.nombre  # Normalizamos mayúsculas

        if self.cobertura_obj_id:
            self.cobertura = self.cobertura_obj.nombre
        elif self.cobertura:
            c_cob = str(self.cobertura).strip()
            cob = _match_cobertura_obj(c_cob, self.compania_obj)
            if not cob:
                # 🚀 Si la crea nueva, le asigna la compañía también
                cob = TipoCobertura.objects.create(nombre=c_cob, compania=self.compania_obj)
            self.cobertura_obj = cob
            self.cobertura = cob.nombre

        # Normalizar patente
        if self.patente:
            self.patente = str(self.patente).replace(" ", "").upper()

        # Normalizar / generar número de póliza
        if self.numero_poliza:
            self.numero_poliza = str(self.numero_poliza).strip()
        else:
            self.numero_poliza = self.generar_numero_poliza()
            self.sin_numero = False

        super().save(*args, **kwargs)

    def __str__(self):
        nro = self.numero_poliza or "s/n"
        return f"Póliza {nro} - {self.patente}"

    @property
    def es_preliminar(self) -> bool:
        return self.fase == PolizaFase.PRELIMINAR

    @property
    def es_definitiva(self) -> bool:
        return self.fase == PolizaFase.DEFINITIVA

    @property
    def tiene_numero(self) -> bool:
        return bool(self.numero_poliza)

    def calcular_mora_dias(self) -> int:
        hoy = timezone.localdate()
        if not hasattr(self, "cuotas"):
            return 0
        # Si no le quedan cuotas por pagar, no hay mora.
        if not self.cuotas.filter(pagado=False).exists():
            return 0
        # Cobertura vigente = vto de la ÚLTIMA cuota PAGADA (hasta cuándo está cubierto).
        cobertura = self.cuotas.filter(pagado=True).aggregate(m=Max("fecha_vencimiento"))["m"]
        if cobertura is None:
            # Nunca pagó nada: la mora arranca en el vto de su primera cuota impaga.
            cobertura = self.cuotas.filter(pagado=False).aggregate(m=Min("fecha_vencimiento"))["m"]
        if not cobertura or cobertura >= hoy:
            return 0
        return (hoy - cobertura).days

    def obtener_estado_financiero(self) -> str:
        dias = self.calcular_mora_dias()
        if dias <= 0:
            return "al_dia"
        if dias <= 30:
            return "mora_1_30"
        if dias <= 60:
            return "mora_31_60"
        if dias <= 90:
            return "mora_61_90"
        return "mora_90_mas"

    def estado_pago(self):
        total_pagos = sum(p.monto for p in self.pagos.all())
        esperado = (self.precio_cuota or 0) * (self.cantidad_cuotas or 0)
        if total_pagos >= esperado:
            return "Pagado completo"
        elif self.pagos.exists():
            return "Al día"
        else:
            return "Atrasado"

    def dias_desde_vencimiento(self) -> int:
        hoy = timezone.localdate()
        if self.fecha_vencimiento and self.fecha_vencimiento < hoy:
            return (hoy - self.fecha_vencimiento).days
        return 0

    def proxima_cuota_impaga(self):
        return self.cuotas.filter(pagado=False).order_by("fecha_vencimiento", "cuota_nro").first()

    def cuotas_impagas_en_rango(self, desde, hasta):
        return self.cuotas.filter(
            pagado=False,
            fecha_vencimiento__range=(desde, hasta)
        ).order_by("fecha_vencimiento", "cuota_nro")

    def tiene_cuotas_pendientes(self) -> bool:
        return self.cuotas.filter(pagado=False).exists()


# -------------------- Cuponeras de robo --------------------
class CuponRobo(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        REPORTADO = "REPORTADO", "Reportado por el cliente"
        PAGADA    = "PAGADA", "Pagada"
        VENCIDA   = "VENCIDA", "Vencida"

    poliza = models.ForeignKey(Poliza, on_delete=models.CASCADE, related_name="cupones_robo", db_index=True)
    periodo_desde = models.DateField()
    periodo_hasta = models.DateField()
    fecha_vencimiento = models.DateField(db_index=True)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE, db_index=True)
    monto = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Monto abonado por este cupón (egreso hacia compañía).")
    foto_url = models.TextField(blank=True, default="")
    foto_perfil_public_id = models.CharField(max_length=200, blank=True, default="")
    fecha_pago = models.DateTimeField(null=True, blank=True)
    reportado_en = models.DateTimeField(null=True, blank=True, help_text="Cuándo el cliente tocó 'Ya pagué' en el link.")
    comprobante_url = models.TextField(blank=True, default="", help_text="Comprobante de pago que sube el cliente desde el portal (opcional).")
    comprobante_public_id = models.CharField(max_length=200, blank=True, default="")
    medio_cobro = models.CharField(max_length=100, blank=True, default="", help_text="Alias de billetera / medio usado para pagar este cupón.")
    notas = models.TextField(blank=True, default="")
    creado_en = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["fecha_vencimiento", "id"]
        indexes = [
            models.Index(fields=["poliza", "fecha_vencimiento"]),
            models.Index(fields=["poliza", "estado"]),
        ]

    def __str__(self):
        return f"Cupon robo {self.poliza_id} {self.periodo_desde}–{self.periodo_hasta} [{self.estado}]"


class TipoFotoVehiculo(models.TextChoices):
    PATENTE       = "PATENTE", "Patente visible"
    FRENTE        = "FRENTE", "Frente"
    LATERAL_IZQ   = "LATERAL_IZQ", "Lateral izquierda"
    LATERAL_DER   = "LATERAL_DER", "Lateral derecha"
    TRASERA       = "TRASERA", "Trasera"
    INTERIOR      = "INTERIOR", "Interior"
    RUEDA_AUXILIO = "RUEDA_AUXILIO", "Rueda de auxilio"
    RUEDA_AUX     = "RUEDA_AUX", "Rueda aux. (alias)"
    TUBO_GNC      = "TUBO_GNC", "Tubo GNC"
    EQUIPO_GNC    = "EQUIPO_GNC", "Equipo GNC"
    OBLEA_GNC     = "OBLEA_GNC", "Oblea GNC"
    OTRA          = "OTRA", "Otra"


class OrigenFotoVehiculo(models.TextChoices):
    ONBOARDING = "ONBOARDING", "Onboarding póliza"
    OFICINA    = "OFICINA", "Ingreso a oficina"
    SINIESTRO  = "SINIESTRO", "Siniestro"
    SOLICITUD  = "SOLICITUD", "Desde solicitud"
    OTRO       = "OTRO", "Otro"


class FotoVehiculo(models.Model):
    poliza = models.ForeignKey(Poliza, on_delete=models.CASCADE, related_name="fotos_vehiculo")
    tipo = models.CharField(max_length=100, default="OTRA")
    url = models.TextField()
    public_id = models.CharField(max_length=200, blank=True, default="")
    origen = models.CharField(max_length=12, choices=OrigenFotoVehiculo.choices, default=OrigenFotoVehiculo.ONBOARDING)
    etiquetas = models.JSONField(default=list, blank=True)
    subido_en = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-subido_en"]
        indexes = [models.Index(fields=["poliza", "tipo"])]

    def __str__(self):
        return f"Poliza {self.poliza_id} - {self.tipo}"


class TipoDocumento(models.TextChoices):
    CEDULA_VERDE        = "CEDULA_VERDE", "Cédula verde"
    CEDULA_AZUL         = "CEDULA_AZUL", "Cédula azul"
    TITULO              = "TITULO", "Título del vehículo"
    VTV                 = "VTV", "VTV"
    OBLEA_GNC           = "OBLEA_GNC", "Oblea GNC"
    PERMISO             = "PERMISO", "Permiso de circulación"
    PERMISO_CIRCULACION = "PERMISO_CIRCULACION", "Permiso de circulación (alias)"
    SEGURO_ANEXO_GRUA   = "SEGURO_ANEXO_GRUA", "Anexo grúa"
    OTRO                = "OTRO", "Otro"


class LadoDocumento(models.TextChoices):
    FRENTE = "FRENTE", "Frente"
    DORSO  = "DORSO", "Dorso"


class PolizaDocumento(models.Model):
    poliza = models.ForeignKey(Poliza, on_delete=models.CASCADE, related_name="documentos")
    tipo = models.CharField(max_length=100, default="OTRO")
    url = models.TextField()
    public_id = models.CharField(max_length=200, blank=True, default="")
    nombre = models.CharField(max_length=255, blank=True, default="")
    mime = models.CharField(max_length=100, blank=True, default="")
    vencimiento = models.DateField(null=True, blank=True)
    notas = models.TextField(blank=True, default="")
    lado = models.CharField(max_length=10, choices=LadoDocumento.choices, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["poliza", "tipo"]),
            models.Index(fields=["poliza", "tipo", "lado"]),
            models.Index(fields=["poliza", "vencimiento"]),
        ]
        constraints = [
            models.CheckConstraint(
                name="polizadoc_lado_solo_en_cedulas",
                check=(
                    (
                        models.Q(tipo__in=[TipoDocumento.CEDULA_VERDE, TipoDocumento.CEDULA_AZUL])
                        & models.Q(lado__in=["", LadoDocumento.FRENTE, LadoDocumento.DORSO])
                    )
                    | (
                        ~models.Q(tipo__in=[TipoDocumento.CEDULA_VERDE, TipoDocumento.CEDULA_AZUL])
                        & models.Q(lado__exact="")
                    )
                ),
            ),
        ]

    def es_cedula(self) -> bool:
        return self.tipo in {TipoDocumento.CEDULA_VERDE, TipoDocumento.CEDULA_AZUL}

    def requiere_vencimiento(self) -> bool:
        return False

    def save(self, *args, **kwargs):
        if not self.es_cedula():
            self.lado = ""
        else:
            self.lado = (self.lado or "").strip().upper()
            if self.lado not in {"", LadoDocumento.FRENTE, LadoDocumento.DORSO}:
                self.lado = ""
        super().save(*args, **kwargs)

    def __str__(self):
        lado = f" ({self.lado})" if self.lado else ""
        return f"Doc {self.tipo}{lado} - Poliza {self.poliza_id}"


# -------------------- Motor de Comisiones --------------------
class Comision(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente de liquidar"
        LIQUIDADA = "LIQUIDADA", "Pagada al vendedor"

    # ¿A qué vendedor le pertenece el dinero?
    vendedor = models.ForeignKey(
        'usuarios.Perfil',
        on_delete=models.CASCADE,
        related_name='comisiones_ganadas'
    )

    # ¿De qué cuota proviene?
    # (Usamos 'pagos.Cuota' como string para evitar errores de importación cruzada)
    cuota = models.OneToOneField(
        'pagos.Cuota',
        on_delete=models.CASCADE,
        related_name='comision_generada'
    )

    monto = models.DecimalField(max_digits=10, decimal_places=2)

    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
        db_index=True
    )

    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_liquidacion = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-fecha_creacion']
        verbose_name = "Comisión"
        verbose_name_plural = "Comisiones"

    def __str__(self):
        return f"Comisión ${self.monto} - Vendedor: {self.vendedor} (Cuota {self.cuota_id})"