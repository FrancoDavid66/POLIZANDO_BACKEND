# clientes/models.py
from django.db import models
import re
import secrets


class EstadoCliente(models.TextChoices):
    BORRADOR = "BORRADOR", "Borrador"
    COMPLETO = "COMPLETO", "Completo"


class Cliente(models.Model):
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    telefono = models.CharField(max_length=20)  # guardamos como lo escribe el usuario
    email = models.EmailField(blank=True, null=True)
    # 🔧 FIX: agregamos blank=True — el frontend de edición ya no lo exige
    # ("ya no es obligatorio según tu lógica"), pero el modelo seguía
    # rechazándolo. Ahora el serializer (fields = "__all__") hereda la regla
    # relajada automáticamente, sin tocar serializers.py.
    dni_cuit_cuil = models.CharField(max_length=20, blank=True)
    direccion = models.TextField(blank=True)
    localidad = models.CharField(max_length=100, blank=True, null=True)
    partido = models.CharField(max_length=100, blank=True, null=True)

    fecha_nacimiento = models.DateField(blank=True, null=True)

    # 🚀 VÍNCULO CON OFICINA (Multi-tenant)
    # 🔧 FIX SEGURIDAD: removido `default=1`. Antes apuntaba a una oficina específica
    # que si se borraba dejaba registros huérfanos. Ahora el campo queda en NULL
    # y el frontend / serializer inyecta la oficina correcta en cada alta.
    oficina = models.ForeignKey(
        'usuarios.Oficina',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='clientes_ficha',
    )

    # ⬇️ URLs de Cloudinary (no archivos locales)
    archivo_dni = models.URLField(max_length=500, blank=True, null=True)
    # DNI (frente/dorso)
    archivo_dni_frente = models.URLField(max_length=500, blank=True, null=True)
    archivo_dni_dorso = models.URLField(max_length=500, blank=True, null=True)
    # Pasaporte
    archivo_pasaporte_frente = models.URLField(max_length=500, blank=True, null=True)
    archivo_pasaporte_dorso = models.URLField(max_length=500, blank=True, null=True)

    estado = models.CharField(
        max_length=10,
        choices=EstadoCliente.choices,
        default=EstadoCliente.BORRADOR,
    )

    # 🆕 Token secreto para el acceso del cliente al PORTAL (link por WhatsApp, sin contraseña)
    portal_token = models.CharField(
        max_length=64, unique=True, blank=True, null=True, db_index=True,
        help_text="Token del link del portal del asegurado. Regenerable.",
    )

    class Meta:
        ordering = ["apellido", "nombre"]
        indexes = [
            models.Index(fields=["apellido", "nombre"]),
            models.Index(fields=["dni_cuit_cuil"]),
            models.Index(fields=["telefono"]),
            models.Index(fields=["email"]),
            models.Index(fields=["oficina"]),  # 🚀 Indexado para velocidad del "Escudo"
        ]

    # -------------------- Normalización suave --------------------
    def save(self, *args, **kwargs):
        if self.nombre:
            self.nombre = self.nombre.strip()
        if self.apellido:
            self.apellido = self.apellido.strip()
        if self.telefono:
            self.telefono = str(self.telefono).strip()
        if self.email:
            self.email = self.email.strip().lower()

        self.estado = (
            EstadoCliente.COMPLETO if self._es_perfil_completo() else EstadoCliente.BORRADOR
        )

        super().save(*args, **kwargs)

    # -------------------- Helpers útiles --------------------
    @property
    def nombre_completo(self) -> str:
        return f"{self.nombre} {self.apellido}".strip()

    def telefono_e164(self, default_cc: str = "54") -> str:
        """
        Devuelve teléfono en formato internacional E.164.
        """
        raw = (self.telefono or "").strip()
        if not raw:
            return ""

        s = raw.replace("whatsapp:", "").strip()

        if s.startswith("+"):
            digits = re.sub(r"\D", "", s[1:])
            if not digits:
                return ""
            if digits.startswith(default_cc) and len(digits) >= 3 and digits[2] != "9":
                digits = default_cc + "9" + digits[len(default_cc):]
            return f"+{digits}"

        digits = re.sub(r"\D", "", s)
        if not digits:
            return ""

        if digits.startswith("00"):
            digits = digits[2:]
        if digits.startswith("0"):
            digits = digits[1:]
        if digits.startswith("15"):
            digits = digits[2:]

        cc = str(default_cc or "54").strip() or "54"

        if digits.startswith(cc):
            rest = digits[len(cc):]
        else:
            rest = digits

        if cc == "54" and (not rest.startswith("9")):
            rest = "9" + rest

        return f"+{cc}{rest}"

    @property
    def dni_frente_url(self) -> str:
        return self.archivo_dni_frente or ""

    @property
    def dni_dorso_url(self) -> str:
        return self.archivo_dni_dorso or ""

    @property
    def documentacion_dni_completa(self) -> bool:
        return bool(self.archivo_dni_frente and self.archivo_dni_dorso)

    def _es_perfil_completo(self) -> bool:
        basicos_ok = bool(self.nombre and self.apellido and self.telefono)
        return basicos_ok and self.documentacion_dni_completa

    # -------------------- Portal del asegurado --------------------
    def asegurar_portal_token(self) -> str:
        """Crea el token si no existe y lo devuelve. Idempotente."""
        if not self.portal_token:
            for _ in range(5):
                t = secrets.token_urlsafe(32)
                if not Cliente.objects.filter(portal_token=t).exists():
                    self.portal_token = t
                    self.save(update_fields=["portal_token"])
                    break
        return self.portal_token or ""

    def regenerar_portal_token(self) -> str:
        """Invalida el link viejo y genera uno nuevo."""
        self.portal_token = None
        self.save(update_fields=["portal_token"])
        return self.asegurar_portal_token()

    def __str__(self):
        return f"{self.apellido}, {self.nombre} ({self.oficina.nombre if self.oficina else 'Sin Ofi'})"