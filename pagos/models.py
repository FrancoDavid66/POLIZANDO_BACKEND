# pagos/models.py
from django.db import models, transaction
from django.core.validators import MinValueValidator
from django.utils import timezone
from django.apps import apps
from django.db.models.signals import post_save
from django.dispatch import receiver
import logging

from polizas.models import Poliza  # ✅ Import correcto

log = logging.getLogger(__name__)

# =========================
# Choices de Verificación (Micaela)
# =========================

ESTADO_VERIFICACION_CHOICES = [
    ("pendiente",        "Pendiente de verificar"),
    ("verificado",       "Verificado · todo OK"),
    ("falta_emitir",     "Atención · Falta emitir en compañía"),
    ("pago_post_baja",   "Atención · Pagó después de baja"),
    ("avisar_vendedor",  "Atención · Avisar al vendedor"),
    ("revisar_mariano",  "Atención · Revisar con Mariano"),
]

ESTADOS_ATENCION = {
    "falta_emitir",
    "pago_post_baja",
    "avisar_vendedor",
    "revisar_mariano",
}


# =========================
# Modelos de Pagos y Cuotas
# =========================

class Pago(models.Model):
    poliza = models.ForeignKey(
        Poliza,
        on_delete=models.CASCADE,
        related_name="pagos"
    )
    # 🔗 Relación directa a la cuota (opcional pero recomendable para trazabilidad)
    cuota = models.ForeignKey(
        "Cuota",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pagos"
    )

    # Fecha efectiva del pago (si no viene, se setea a hoy en save)
    fecha = models.DateField(null=True, blank=True)

    # ✅ Timestamp real cuando se registró el pago (para historial con hora real)
    registrado_en = models.DateTimeField(auto_now_add=True, db_index=True)

    # ✅ Auditoría
    creado = models.DateTimeField(auto_now_add=True, db_index=True)
    actualizado = models.DateTimeField(auto_now=True, db_index=True)

    monto = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)]
    )

    # ✅ Simplificado a 2 métodos: efectivo | transferencia
    metodo = models.CharField(
        max_length=50,
        choices=[
            ("efectivo", "Efectivo"),
            ("transferencia", "Transferencia"),
        ]
    )
    observaciones = models.TextField(blank=True, null=True)

    # 🆕 Datos de la transferencia (para que Balances tenga el detalle real,
    #    no solo el monto). El front ya los manda; antes se calculaban y se
    #    tiraban, porque el Pago no tenía dónde guardarlos.
    destino_cuenta = models.CharField(max_length=120, blank=True, default="")
    enviado_por    = models.CharField(max_length=150, blank=True, default="")
    cuit_remitente = models.CharField(max_length=20,  blank=True, default="")
    nro_operacion  = models.CharField(max_length=60,  blank=True, default="")

    # Se mantiene para compatibilidad y consultas rápidas
    cuota_nro = models.IntegerField(db_index=True)

    # Flag para backend de balances
    registrado_en_balance = models.BooleanField(default=False)

    # =========================
    # ✅ Verificación de Micaela
    # =========================
    estado_verificacion = models.CharField(
        max_length=30,
        choices=ESTADO_VERIFICACION_CHOICES,
        default="pendiente",
        db_index=True,
    )
    verificacion_nota = models.TextField(blank=True, null=True)
    verificado_por = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pagos_verificados",
    )
    verificado_en = models.DateTimeField(null=True, blank=True, db_index=True)

    # 🆕 Quién cobró (empleado elegido al momento de cobrar).
    #    Mismo patrón que tareas/models_fijas.py (CumplimientoTareaFija).
    responsable_empleado = models.ForeignKey(
        "solicitudes.Empleado",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pagos_cobrados",
    )
    # Nombre congelado (por si el empleado se borra después).
    responsable_nombre = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        ordering = ["-fecha", "poliza_id", "cuota_nro"]
        indexes = [
            models.Index(fields=["poliza", "cuota_nro"]),
            models.Index(fields=["fecha"]),
            models.Index(fields=["registrado_en_balance"]),
            models.Index(fields=["creado"]),
            models.Index(fields=["registrado_en"]),
            models.Index(fields=["estado_verificacion"]),
        ]

    def save(self, *args, **kwargs):
        """
        Normaliza relaciones y datos:
        - Si viene `cuota` y no hay `cuota_nro`, lo completa.
        - Si viene `cuota` y no hay `poliza`, la infiere.
        - Si falta `fecha`, usa la fecha local de hoy.
        - Si falta `monto` y hay `cuota`, lo toma de la cuota.
        """
        if self.cuota:
            if not self.cuota_nro:
                self.cuota_nro = self.cuota.cuota_nro
            if not self.poliza_id:
                self.poliza = self.cuota.poliza
            if self.monto is None:
                self.monto = self.cuota.monto
        if not self.fecha:
            self.fecha = timezone.localdate()
        super().save(*args, **kwargs)

    # =========================
    # ✅ Helpers para recibo (hora/minuto)
    # =========================
    @property
    def registrado_hm(self) -> str:
        """
        Hora local (HH:MM) del registro real del pago.
        Ideal para imprimir en recibo/ticket.
        """
        if not self.registrado_en:
            return ""
        return timezone.localtime(self.registrado_en).strftime("%H:%M")

    @property
    def registrado_hm_full(self) -> str:
        """
        Fecha y hora local (DD/MM/YYYY HH:MM) del registro real del pago.
        """
        if not self.registrado_en:
            return ""
        return timezone.localtime(self.registrado_en).strftime("%d/%m/%Y %H:%M")

    @property
    def requiere_atencion(self) -> bool:
        """True si el pago está en alguno de los estados de atención de Micaela."""
        return self.estado_verificacion in ESTADOS_ATENCION

    def __str__(self):
        pol = getattr(self.poliza, "numero_poliza", "-") if self.poliza_id else "-"
        return f"Pago cuota {self.cuota_nro} - {pol} - {self.fecha}"


class Cuota(models.Model):
    poliza = models.ForeignKey(
        Poliza,
        on_delete=models.CASCADE,
        related_name="cuotas"
    )
    cuota_nro = models.IntegerField(db_index=True)
    fecha_vencimiento = models.DateField(db_index=True)

    monto = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)]
    )

    pagado = models.BooleanField(default=False, db_index=True)

    forma_pago = models.CharField(
        max_length=20,
        choices=[
            ("efectivo", "Efectivo"),
            ("transferencia", "Transferencia"),
        ],
        null=True,
        blank=True
    )

    # ✅ Clave para auditoría y reportes
    fecha_pago = models.DateField(null=True, blank=True)

    # ✅ Timestamp preciso (Fecha + Hora + Segundos) del momento del cobro
    pago_registrado_en = models.DateTimeField(null=True, blank=True, db_index=True)

    # =========================
    # ✅ NUEVO (FIX con front + buscar)
    # =========================
    # Observación escrita al momento de pagar (la que ve el usuario)
    observaciones_pago = models.TextField(null=True, blank=True, default="")

    # Última observación (compat para front y para mantener histórico rápido)
    ultima_observacion_pago = models.TextField(null=True, blank=True, default="")

    # 🆕 Quién cobró esta cuota (empleado elegido al momento de cobrar).
    #    Mismo patrón que tareas/models_fijas.py (CumplimientoTareaFija).
    responsable_empleado = models.ForeignKey(
        "solicitudes.Empleado",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cuotas_cobradas",
    )
    # Nombre congelado (por si el empleado se borra después).
    responsable_nombre = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        ordering = ["poliza_id", "cuota_nro"]
        unique_together = [("poliza", "cuota_nro")]
        indexes = [
            models.Index(fields=["poliza", "cuota_nro"]),
            models.Index(fields=["pagado", "fecha_vencimiento"]),
        ]
        constraints = [
            models.CheckConstraint(
                name="cuota_pagada_requiere_fecha_pago",
                check=models.Q(pagado=False) | models.Q(fecha_pago__isnull=False)
            ),
        ]

    def marcar_pagada(self, *, fecha=None, forma=None, monto=None, observaciones=None,
                      responsable_empleado=None, responsable_nombre=None, commit=True):
        # ✅ instante exacto del servidor (timezone-aware)
        ahora = timezone.now()
        if not fecha:
            fecha = ahora.date()

        self.pagado = True
        self.fecha_pago = fecha

        # ✅ Guardamos el momento exacto (sirve para hora:minuto del recibo)
        self.pago_registrado_en = ahora

        if forma:
            self.forma_pago = forma
        if monto is not None:
            self.monto = monto

        # ✅ guardar observaciones si vienen
        if observaciones is not None:
            txt = str(observaciones or "").strip()
            self.observaciones_pago = txt
            self.ultima_observacion_pago = txt

        # 🆕 Quién cobró (opcional; si no viene, no se pisa lo que ya hubiera).
        update_fields = [
            "pagado", "fecha_pago", "pago_registrado_en", "forma_pago", "monto",
            "observaciones_pago", "ultima_observacion_pago"
        ]
        if responsable_empleado is not None:
            self.responsable_empleado = responsable_empleado
            self.responsable_nombre = responsable_nombre or getattr(responsable_empleado, "nombre", "") or ""
            update_fields += ["responsable_empleado", "responsable_nombre"]
        elif responsable_nombre is not None:
            self.responsable_nombre = responsable_nombre
            update_fields += ["responsable_nombre"]

        if commit:
            self.save(update_fields=update_fields)

    def save(self, *args, **kwargs):
        if self.pagado:
            if not self.fecha_pago:
                self.fecha_pago = timezone.localdate()
            # ✅ Fallback: si se marca como pagada por otra vía que no sea marcar_pagada
            if not self.pago_registrado_en:
                self.pago_registrado_en = timezone.now()

        super().save(*args, **kwargs)

    # =========================
    # ✅ Helpers para recibo (hora/minuto)
    # =========================
    @property
    def pago_hm(self) -> str:
        """
        Hora local (HH:MM) de cuando se cobró realmente la cuota.
        """
        if not self.pago_registrado_en:
            return ""
        return timezone.localtime(self.pago_registrado_en).strftime("%H:%M")

    @property
    def pago_hm_full(self) -> str:
        """
        Fecha y hora local (DD/MM/YYYY HH:MM) de cuando se cobró realmente la cuota.
        """
        if not self.pago_registrado_en:
            return ""
        return timezone.localtime(self.pago_registrado_en).strftime("%d/%m/%Y %H:%M")

    @property
    def esta_vencida(self) -> bool:
        return self.fecha_vencimiento < timezone.localdate() and not self.pagado

    def __str__(self):
        pol = getattr(self.poliza, "numero_poliza", "-") if self.poliza_id else "-"
        return f"Cuota {self.cuota_nro} - {pol}"


class AlertaEnviada(models.Model):
    cuota = models.ForeignKey(
        Cuota,
        on_delete=models.CASCADE,
        related_name="alertas"
    )
    tipo = models.CharField(
        max_length=50,
        choices=[
            ("3_antes", "3 días antes"),
            ("hoy", "Día de vencimiento"),
            ("3_despues", "3 días después"),
            ("7_despues", "7 días después"),
            ("30_despues", "30 días después"),
        ]
    )
    enviada = models.BooleanField(default=True)
    
    # 🚀 CAMBIO APLICADO AQUÍ: DateField a DateTimeField
    fecha = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        unique_together = [("cuota", "tipo")]
        ordering = ["-fecha"]
        indexes = [
            models.Index(fields=["tipo"]),
            models.Index(fields=["fecha"]),
            models.Index(fields=["cuota", "tipo"]),
        ]

    def __str__(self):
        return f"Alerta {self.tipo} - Cuota {self.cuota_id}"


# =========================
# Medios de cobro
# =========================

class MedioCobro(models.Model):
    class Proveedor(models.TextChoices):
        MERCADO_PAGO      = "mercado_pago", "Mercado Pago"
        BILLETERA_VIRTUAL = "billetera_virtual", "Billetera Virtual"
        GRUBANK           = "grubank", "Grubank"
        ASTROPAY          = "astropay", "AstroPay"
        UALA              = "uala", "Ualá"
        BANCO             = "banco", "Banco"
        OTRO              = "otro", "Otro"

    class Tipo(models.TextChoices):
        ALIAS = "alias", "Alias"
        CBU   = "cbu", "CBU"
        CVU   = "cvu", "CVU"
        LINK  = "link", "Link de pago"

    proveedor = models.CharField(max_length=20, choices=Proveedor.choices, default=Proveedor.MERCADO_PAGO, db_index=True)
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.ALIAS, db_index=True)
    valor = models.CharField(max_length=150, help_text="Alias/CBU/CVU o URL del link de pago")

    titular_nombre = models.CharField(max_length=120, blank=True, default="")
    etiqueta = models.CharField(max_length=100, blank=True, default="")

    qr_url = models.URLField(blank=True, default="")
    notas = models.TextField(blank=True, default="")

    activo = models.BooleanField(default=True, db_index=True)
    ultimo_uso = models.DateTimeField(null=True, blank=True, db_index=True)
    usos_totales = models.PositiveIntegerField(default=0)

    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    # 🚀 NUEVO: Identificador lógico de la oficina para aislar billeteras
    oficina = models.CharField(
        max_length=15,
        null=True,
        blank=True,
        db_index=True,
        help_text="Sucursal dueña de este alias (ej: '1', '2', '3')."
    )

    class Meta:
        ordering = ["-activo", "ultimo_uso", "id"]
        indexes = [
            models.Index(fields=["activo", "ultimo_uso"]),
            models.Index(fields=["proveedor", "tipo"]),
            models.Index(fields=["oficina"]), # Índice para búsquedas rápidas
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["proveedor", "tipo", "valor", "oficina"],
                name="medio_cobro_unico_por_proveedor_tipo_valor_oficina",
            ),
        ]

    def marcar_uso(self):
        self.ultimo_uso = timezone.now()
        self.usos_totales = (self.usos_totales or 0) + 1
        self.save(update_fields=["ultimo_uso", "usos_totales"])

    def __str__(self):
        estado = "✅" if self.activo else "⛔"
        ofi_str = f"[Ofi {self.oficina}]" if self.oficina else "[Global]"
        return f"{estado} {ofi_str} {self.get_proveedor_display()} · {self.get_tipo_display()} · {self.valor} ({self.titular_nombre})"


# =========================
# Señales: crear Ingreso al registrar un Pago
# =========================

def _mapear_forma_ingreso_desde_pago(metodo_pago: str) -> str:
    if (metodo_pago or "").lower() == "efectivo":
        return "efectivo"
    return "transferencia"

# 🚀 TRADUCTOR INFALIBLE DE SUCURSALES
def _obtener_codigo_caja(poliza):
    ofi = getattr(poliza, 'oficina', None)
    if not ofi: return ""
    
    # Si la oficina ya tiene un código, lo usamos
    if hasattr(ofi, 'codigo') and ofi.codigo: 
        return str(ofi.codigo).strip()
    
    # Si es un texto o un ID, lo limpiamos y traducimos
    s = str(getattr(ofi, 'id', ofi)).strip().lower()
    
    if "1" == s or "5 esquinas" in s: return "1"
    if "2" == s or "axion" in s: return "2"
    if "3" == s or "39" in s: return "3"
    
    return str(getattr(ofi, 'id', ofi)).strip()


@receiver(post_save, sender=Pago)
def crear_ingreso_automatico(sender, instance: Pago, created, **kwargs):
    try:
        if instance.registrado_en_balance:
            return
        if instance.monto is None:
            return
        try:
            if float(instance.monto) <= 0:
                return
        except Exception:
            return

        # 🚀 CORRECCIÓN: "balances" con 'c'
        try:
            Ingreso = apps.get_model("balances", "Ingreso")
        except LookupError:
            Ingreso = apps.get_model("balanzes", "Ingreso")

        poliza_num = getattr(instance.poliza, "numero_poliza", "") if getattr(instance, "poliza_id", None) else ""

        # 🚀 Datos para la descripción: patente y compañía (en vez del número de póliza)
        patente = ""
        compania = ""
        try:
            pol = getattr(instance, "poliza", None) if getattr(instance, "poliza_id", None) else None
            if pol:
                patente = (getattr(pol, "patente", "") or "").strip().upper()
                # Compañía: texto plano o, si está vacío, el nombre del modelo nuevo
                compania = (getattr(pol, "compania", "") or "").strip()
                if not compania:
                    comp_obj = getattr(pol, "compania_obj", None)
                    compania = (getattr(comp_obj, "nombre", "") or "").strip()
        except Exception:
            patente = ""
            compania = ""

        # Armamos: "Pago cuota 3 - FDT601 (AMCA)". Si falta algún dato, no rompe.
        _ref_partes = [p for p in [patente, f"({compania})" if compania else ""] if p]
        _ref = " ".join(_ref_partes) if _ref_partes else (poliza_num or "s/d")
        descripcion_ingreso = f"Pago cuota {instance.cuota_nro} - {_ref}"

        cliente_nombre = ""
        try:
            cliente = getattr(instance.poliza, "cliente", None) if getattr(instance, "poliza_id", None) else None
            if cliente:
                nom = (getattr(cliente, "nombre", "") or "").strip()
                ape = (getattr(cliente, "apellido", "") or "").strip()
                if ape and nom:
                    cliente_nombre = f"{ape}, {nom}"
                else:
                    cliente_nombre = ape or nom
        except Exception:
            cliente_nombre = ""

        with transaction.atomic():

            # 🐛 FIX: Ingreso.oficina es un ForeignKey a Oficina (objeto), no texto.
            # _obtener_codigo_caja devolvía un código en string (ej: "OFI-2"),
            # y eso rompía con: Cannot assign "'OFI-2'": "Ingreso.oficina" must
            # be a "Oficina" instance. Ahora pasamos el objeto real.
            ofi_obj = getattr(instance.poliza, "oficina", None)

            Ingreso.objects.create(
                # 🚀 Descripción: cuota + patente + compañía (sin número de póliza)
                descripcion=descripcion_ingreso,
                monto=instance.monto,
                fecha=instance.fecha or timezone.localdate(),
                oficina=ofi_obj,  # 👈 OBJETO Oficina real (no texto)
                categoria="Cobro de Cuota", # 🚀 CATEGORÍA UNIFICADA
                forma_pago=_mapear_forma_ingreso_desde_pago(instance.metodo),
                # 🆕 Preferimos quién transfirió realmente; si no vino, el cliente de la póliza.
                pagado_por=instance.enviado_por or cliente_nombre,
                # 🆕 Detalle de la transferencia — antes se calculaba y se perdía.
                billetera=instance.destino_cuenta,
                cuit_remitente=instance.cuit_remitente,
                nro_operacion=instance.nro_operacion,
                observaciones=instance.observaciones,
            )
            instance.registrado_en_balance = True
            instance.save(update_fields=["registrado_en_balance"])

    except Exception as e:
        log.exception(f"[pagos] No se pudo crear Ingreso automático para Pago id={instance.id}: {e}")