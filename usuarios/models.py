# usuarios/models.py
from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

class Oficina(models.Model):
    codigo = models.CharField(max_length=50, unique=True, help_text="Ej: CENTRAL, OFI-001")
    nombre = models.CharField(max_length=150)
    direccion = models.CharField(max_length=255, blank=True, null=True)
    activa = models.BooleanField(default=True)

    # 📞 WhatsApp de la oficina (para que el cliente la contacte desde el portal).
    #    Formato internacional sin signos, ej: 5492284123456
    whatsapp = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="WhatsApp de la oficina (ej: 5492284123456) para el botón 'Pedir mis papeles' del portal.",
    )
    
    # 🚀 NUEVOS CAMPOS PARA EL WHATSAPP DINÁMICO DE ULTRAMSG
    ultramsg_instance_id = models.CharField(
        max_length=32, 
        blank=True, 
        null=True, 
        help_text="Ej: instance171359"
    )
    ultramsg_token = models.CharField(
        max_length=64, 
        blank=True, 
        null=True,
        help_text="El token largo de la API de UltraMsg"
    )

    # 🚀 VINCULACIÓN CON EL RESPONSABLE DE SOLICITUDES
    # Permite asignar a un usuario como el encargado de esta oficina.
    responsable = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='oficinas_bajo_mando'
    )

    creado_en = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nombre} ({self.codigo})"

    class Meta:
        verbose_name = "Oficina"
        verbose_name_plural = "Oficinas"
        ordering = ['nombre']

class Perfil(models.Model):
    ROL_CHOICES = (
        ('ADMIN', 'Administrador Global'),
        ('OFICINA', 'Personal de Oficina'),
        ('VENDEDOR', 'Vendedor Externo'), # 🚀 NUEVO ROL AÑADIDO
    )
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil')
    rol = models.CharField(max_length=20, choices=ROL_CHOICES, default='OFICINA')
    oficina = models.ForeignKey(Oficina, on_delete=models.SET_NULL, null=True, blank=True, related_name='empleados')

    def __str__(self):
        return f"{self.user.username} - {self.rol}"

    class Meta:
        verbose_name = "Perfil"
        verbose_name_plural = "Perfiles"

# --- Señales para crear el Perfil automáticamente cuando se crea un User ---
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Perfil.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    instance.perfil.save()