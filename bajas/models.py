# bajas/models.py
from django.db import models
from django.utils import timezone

from polizas.models import Poliza


class CorreoCompaniaBaja(models.Model):
    """
    Un registro por compañía: a qué email mandar la solicitud de baja
    y cuántos días de mora se esperan antes de iniciar el proceso.
    """
    compania = models.CharField(
        max_length=150,
        unique=True,
        verbose_name="Nombre de la compañía",
        help_text="Debe coincidir exactamente con el campo 'compania' de Poliza.",
    )
    email = models.TextField(
        verbose_name="Correo(s) de bajas",
        help_text="Uno o varios emails separados por coma. Ej: bajas@cia.com, mesa@cia.com",
    )
    dias_gracia = models.PositiveSmallIntegerField(
        default=3,
        verbose_name="Días de mora mínimos",
        help_text="Pólizas con mora menor a este valor no entran al proceso de baja.",
    )

    def emails_lista(self):
        """Devuelve la lista de emails válidos (parsea comas, ; y espacios)."""
        import re
        partes = re.split(r"[,;\s]+", self.email or "")
        return [e.strip() for e in partes if e.strip() and "@" in e]

    def __str__(self):
        return f"{self.compania} → {self.email} ({self.dias_gracia}d)"

    class Meta:
        verbose_name = "Correo de compañía para bajas"
        verbose_name_plural = "Correos de compañías para bajas"
        ordering = ["compania"]


class BajaPoliza(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE_ENVIO = "PENDIENTE_ENVIO", "Pendiente de envío"
        ENVIADA         = "ENVIADA",         "Email enviado a compañía"
        REALIZADA       = "REALIZADA",       "Baja confirmada por compañía"

    poliza = models.OneToOneField(
        Poliza,
        on_delete=models.CASCADE,
        related_name="baja_operativa",
    )
    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.PENDIENTE_ENVIO,
        db_index=True,
    )
    email_destino = models.EmailField(blank=True, default="")
    notas         = models.TextField(blank=True, default="")

    enviada_en   = models.DateTimeField(null=True, blank=True)
    realizada_en = models.DateTimeField(null=True, blank=True)

    # Auditoría del email enviado
    email_asunto = models.CharField(max_length=300, blank=True, default="")
    email_cuerpo = models.TextField(blank=True, default="")
    email_ok     = models.BooleanField(null=True, blank=True)
    email_error  = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._estado_original = self.estado

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new:
            HistorialBajaPoliza.objects.create(
                baja_poliza=self,
                estado_anterior="",
                estado_nuevo=self.estado,
            )
        elif self.estado != self._estado_original:
            HistorialBajaPoliza.objects.create(
                baja_poliza=self,
                estado_anterior=self._estado_original,
                estado_nuevo=self.estado,
            )
            self._estado_original = self.estado

    def marcar_enviada(self):
        self.estado     = self.Estado.ENVIADA
        self.enviada_en = timezone.now()
        self.save(update_fields=["estado", "enviada_en", "updated_at"])

    def marcar_realizada(self):
        self.estado      = self.Estado.REALIZADA
        self.realizada_en = timezone.now()
        self.save(update_fields=["estado", "realizada_en", "updated_at"])

    def __str__(self):
        return f"BajaPoliza(poliza_id={self.poliza_id}, estado={self.estado})"

    class Meta:
        verbose_name        = "Baja de póliza"
        verbose_name_plural = "Bajas de pólizas"
        indexes = [
            models.Index(fields=["estado"]),
            models.Index(fields=["enviada_en"]),
        ]


class HistorialBajaPoliza(models.Model):
    baja_poliza = models.ForeignKey(
        BajaPoliza,
        on_delete=models.CASCADE,
        related_name="historial",
    )
    estado_anterior = models.CharField(
        max_length=20,
        blank=True,
        choices=BajaPoliza.Estado.choices,
        verbose_name="Estado anterior",
    )
    estado_nuevo = models.CharField(
        max_length=20,
        choices=BajaPoliza.Estado.choices,
        verbose_name="Estado nuevo",
    )
    fecha = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        try:
            nro = self.baja_poliza.poliza.numero_poliza
        except Exception:
            nro = "—"
        return f"{nro} | {self.estado_anterior or '—'} → {self.estado_nuevo}"

    class Meta:
        verbose_name        = "Historial de baja"
        verbose_name_plural = "Historiales de bajas"
        ordering            = ["-fecha"]