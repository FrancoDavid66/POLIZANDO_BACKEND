from django.db import models
from django.conf import settings
from django.utils import timezone

class CierreCaja(models.Model):
    # Foto de Cloudinary
    foto_url = models.TextField()
    foto_public_id = models.CharField(max_length=200, blank=True, default="")
    
    # Auditoría Inteligente
    monto_declarado = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    monto_sistema = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    diferencia = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    estado_auditoria = models.CharField(max_length=20, blank=True, default="PENDIENTE")

    # Turno del cierre (lo detecta el sistema por hora: <15hs mediodía, si no noche)
    TURNOS = (("mediodia", "Mediodía"), ("noche", "Noche"))
    turno = models.CharField(max_length=10, choices=TURNOS, blank=True, default="")

    # 🚀 NUEVO: Vínculo con el Empleado físico (de la app solicitudes)
    empleado = models.ForeignKey('solicitudes.Empleado', on_delete=models.SET_NULL, null=True, blank=True, related_name='cierres_caja')
    
    # Cuenta y Oficina
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='cierres_caja')
    oficina = models.ForeignKey('usuarios.Oficina', on_delete=models.SET_NULL, null=True, blank=True, related_name='cierres_caja')
    
    creado_en = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-creado_en']
        verbose_name = 'Cierre de Caja'
        verbose_name_plural = 'Cierres de Caja'

    def __str__(self):
        ofi = self.oficina.nombre if self.oficina else "Sin Sucursal"
        return f"Cierre {ofi} - {self.creado_en.strftime('%d/%m/%Y %H:%M')}"

class HorarioCierreCaja(models.Model):
    """
    Horarios de cierre de caja por oficina (2 turnos: mediodía y noche).
    Configurable desde el panel de admin. Lo usa el pop-up recordatorio.
    """
    oficina = models.OneToOneField(
        'usuarios.Oficina', on_delete=models.CASCADE, related_name='horario_cierre'
    )
    mediodia = models.TimeField(null=True, blank=True, help_text="Ej: 13:00. Vacío = sin cierre de mediodía.")
    noche = models.TimeField(null=True, blank=True, help_text="Ej: 20:00. Vacío = sin cierre de noche.")
    aviso_min = models.PositiveIntegerField(default=30, help_text="Minutos antes para avisar con el pop-up.")
    tolerancia_min = models.PositiveIntegerField(default=5, help_text="Minutos de tolerancia después de la hora.")
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Horario de cierre de caja"
        verbose_name_plural = "Horarios de cierre de caja"

    def __str__(self):
        ofi = self.oficina.nombre if self.oficina else "?"
        return f"Horarios {ofi}: med {self.mediodia} / noche {self.noche}"