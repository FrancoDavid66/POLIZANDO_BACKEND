from django.db import models
from django.conf import settings
from django.utils import timezone
from polizas.models import Poliza

class PolizaEvento(models.Model):
    class Categoria(models.TextChoices):
        POLIZA   = "POLIZA", "Póliza"
        VEHICULO = "VEHICULO", "Vehículo"
        DOC      = "DOC", "Documento"
        FOTO     = "FOTO", "Foto"
        CUOTA    = "CUOTA", "Cuota"
        PAGO     = "PAGO", "Pago"
        GRUA     = "GRUA", "Grúa"
        SINIESTRO= "SINIESTRO", "Siniestro"
        COM      = "COM", "Comunicación"
        NOTA     = "NOTA", "Nota"
        SISTEMA  = "SISTEMA", "Sistema"

    class Severidad(models.TextChoices):
        INFO    = "INFO", "Info"
        WARNING = "WARNING", "Advertencia"
        ERROR   = "ERROR", "Error"
        ACTION  = "ACTION", "Acción"

    class Tipo(models.TextChoices):
        POLIZA_CREAR       = "POLIZA_CREAR", "Creación de póliza"
        POLIZA_EDITAR      = "POLIZA_EDITAR", "Edición de póliza"
        POLIZA_CAMBIAR_ESTADO = "POLIZA_CAMBIAR_ESTADO", "Cambio de estado"
        POLIZA_CAMBIO_TITULAR = "POLIZA_CAMBIO_TITULAR", "Cambio de titular"
        POLIZA_CAMBIO_COBERTURA = "POLIZA_CAMBIO_COBERTURA", "Cambio de cobertura"
        POLIZA_CAMBIO_PREMIO = "POLIZA_CAMBIO_PREMIO", "Cambio de premio"
        PERFIL_CAMBIAR     = "PERFIL_CAMBIAR", "Cambio de foto de perfil"

        VEHICULO_EDITAR    = "VEHICULO_EDITAR", "Edición de vehículo"

        DOC_SUBIR          = "DOC_SUBIR", "Documento subido"
        DOC_BORRAR         = "DOC_BORRAR", "Documento eliminado"
        DOC_CAMBIAR_VTO    = "DOC_CAMBIAR_VTO", "Cambio de vencimiento de documento"
        DOC_VALIDAR        = "DOC_VALIDAR", "Documento validado"
        DOC_FALTANTE       = "DOC_FALTANTE", "Documento faltante"

        FOTO_SUBIR         = "FOTO_SUBIR", "Foto subida"
        FOTO_BORRAR        = "FOTO_BORRAR", "Foto eliminada"

        CUOTA_GENERAR      = "CUOTA_GENERAR", "Cuotas generadas"
        CUOTA_RECALCULAR   = "CUOTA_RECALCULAR", "Cuotas recalculadas"

        PAGO_REGISTRAR     = "PAGO_REGISTRAR", "Pago registrado"
        PAGO_ANULAR        = "PAGO_ANULAR", "Pago anulado"
        PAGO_FALLAR        = "PAGO_FALLAR", "Pago fallido"
        PAGO_APLICAR_A_CUOTA = "PAGO_APLICAR_A_CUOTA", "Pago aplicado a cuota"

        GRUA_ADHESION_CREAR = "GRUA_ADHESION_CREAR", "Adhesión creada"
        GRUA_ADHESION_ACTUALIZAR = "GRUA_ADHESION_ACTUALIZAR", "Adhesión actualizada"
        GRUA_ADHESION_BAJA  = "GRUA_ADHESION_BAJA", "Adhesión dada de baja"
        GRUA_SERVICIO_SOLICITAR = "GRUA_SERVICIO_SOLICITAR", "Servicio solicitado"
        GRUA_SERVICIO_CERRAR = "GRUA_SERVICIO_CERRAR", "Servicio cerrado"

        SINIESTRO_ABRIR    = "SINIESTRO_ABRIR", "Siniestro abierto"
        SINIESTRO_ACTUALIZAR = "SINIESTRO_ACTUALIZAR", "Siniestro actualizado"
        SINIESTRO_CERRAR   = "SINIESTRO_CERRAR", "Siniestro cerrado"

        COM_EMAIL_ENVIADO  = "COM_EMAIL_ENVIADO", "Email enviado"
        COM_EMAIL_EVENTO   = "COM_EMAIL_EVENTO", "Evento email"
        COM_WHATSAPP_EVENTO= "COM_WHATSAPP_EVENTO", "Evento WhatsApp"
        COM_LLAMADA        = "COM_LLAMADA", "Llamada registrada"

        NOTA               = "NOTA", "Nota"

        ALERTA_VTO_PROXIMO = "ALERTA_VTO_PROXIMO", "Alerta de vencimiento"
        ALERTA_CUOTA_VENCIDA = "ALERTA_CUOTA_VENCIDA", "Cuota vencida"
        MILESTONE_COMPLETADO = "MILESTONE_COMPLETADO", "Hito completado"

    class Source(models.TextChoices):
        USER    = "USER", "Usuario"
        SYSTEM  = "SYSTEM", "Sistema"
        WEBHOOK = "WEBHOOK", "Webhook"
        BATCH   = "BATCH", "Proceso batch"

    poliza = models.ForeignKey(Poliza, on_delete=models.CASCADE, related_name="eventos")
    categoria = models.CharField(max_length=16, choices=Categoria.choices, default=Categoria.POLIZA)
    tipo = models.CharField(max_length=32, choices=Tipo.choices)
    severidad = models.CharField(max_length=8, choices=Severidad.choices, default=Severidad.INFO)

    mensaje = models.CharField(max_length=255)
    data = models.JSONField(default=dict, blank=True)

    subject_type = models.CharField(max_length=40, blank=True, default="")
    subject_id = models.IntegerField(null=True, blank=True)

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='eventos_poliza'
    )
    actor_name = models.CharField(max_length=150, blank=True, default="")

    source = models.CharField(max_length=12, choices=Source.choices, default=Source.USER)
    idempotency_key = models.CharField(max_length=80, blank=True, default="", db_index=True)

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['poliza', 'created_at']),
            models.Index(fields=['categoria']),
            models.Index(fields=['tipo']),
            models.Index(fields=['subject_type', 'subject_id']),
            models.Index(fields=['idempotency_key']),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} · póliza {self.poliza_id}"
