from rest_framework import serializers

from .models import Cliente, EstadoCliente
from polizas.serializers import PolizaSerializer


class ClienteBasicSerializer(serializers.ModelSerializer):
    """Serializer liviano para listado (evita traer pólizas/cuotas)."""

    # 🚀 VÍNCULO CON OFICINA
    oficina_nombre = serializers.CharField(source='oficina.nombre', read_only=True)

    # Campos agregados/anotados desde el queryset (si están presentes)
    polizas_total = serializers.IntegerField(read_only=True, required=False)
    polizas_activas = serializers.IntegerField(read_only=True, required=False)
    deuda = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True, required=False
    )
    ultima_fecha_vencimiento = serializers.DateField(
        read_only=True, required=False, allow_null=True
    )
    ultima_mora_dias = serializers.IntegerField(read_only=True, required=False)

    # Resumen para UI (sin queries extra)
    estado_pago = serializers.SerializerMethodField()

    class Meta:
        model = Cliente
        fields = [
            "id",
            "nombre",
            "apellido",
            "telefono",
            "email",
            "dni_cuit_cuil",
            "oficina",          # ID para asignación/edición (Admin)
            "oficina_nombre",   # Nombre para mostrar en la tabla
            "estado",
            "estado_pago",
            "polizas_total",
            "polizas_activas",
            "deuda",
            "ultima_fecha_vencimiento",
            "ultima_mora_dias",
        ]

    def get_estado_pago(self, cliente: Cliente) -> str:
        # 1) Perfil incompleto
        if getattr(cliente, "estado", None) == EstadoCliente.BORRADOR:
            return "Incompleto"

        # 2) Sin póliza (si viene anotado, NO hay query)
        pol_total = getattr(cliente, "polizas_total", None)
        if pol_total is not None:
            try:
                if int(pol_total) <= 0:
                    return "Sin póliza"
            except Exception:
                pass
        else:
            # fallback solo si no está anotado (evitar en list)
            try:
                if not cliente.polizas.exists():
                    return "Sin póliza"
            except Exception:
                return "Sin póliza"

        # 3) Mora (si viene anotada)
        mora = getattr(cliente, "ultima_mora_dias", None)
        if mora is None:
            # si no viene anotado: asumimos al día para no disparar queries
            return "Al día"

        try:
            mora_int = int(mora)
        except Exception:
            mora_int = 0

        return "Al día" if mora_int <= 0 else "Vencido"


class ClienteDetailSerializer(serializers.ModelSerializer):
    """Serializer completo (para retrieve/create/update)."""

    # 🚀 NOMBRE DE OFICINA PARA EL DETALLE
    oficina_nombre = serializers.CharField(source='oficina.nombre', read_only=True)

    estado_pago = serializers.SerializerMethodField()
    polizas = PolizaSerializer(many=True, read_only=True)

    fecha_nacimiento = serializers.DateField(allow_null=True, required=False)

    # Campos de URLs explícitos (Cloudinary)
    archivo_dni = serializers.URLField(allow_null=True, allow_blank=True, required=False)
    archivo_dni_frente = serializers.URLField(
        allow_null=True, allow_blank=True, required=False
    )
    archivo_dni_dorso = serializers.URLField(
        allow_null=True, allow_blank=True, required=False
    )
    archivo_pasaporte_frente = serializers.URLField(
        allow_null=True, allow_blank=True, required=False
    )
    archivo_pasaporte_dorso = serializers.URLField(
        allow_null=True, allow_blank=True, required=False
    )

    # Aliases útiles para el front (read-only, vienen de @property en el modelo)
    dni_frente_url = serializers.ReadOnlyField()
    dni_dorso_url = serializers.ReadOnlyField()
    documentacion_dni_completa = serializers.ReadOnlyField()

    class Meta:
        model = Cliente
        fields = "__all__"

    def get_estado_pago(self, cliente: Cliente) -> str:
        """
        Resumen simple para UI:
        - 'Incompleto' si el perfil está en BORRADOR.
        - 'Sin póliza' si no tiene pólizas.
        - 'Al día' si no hay mora.
        - 'Vencido' si tiene mora (>0 días).
        """
        if getattr(cliente, "estado", None) == EstadoCliente.BORRADOR:
            return "Incompleto"

        # Si viene prefetch de polizas, esto NO dispara query adicional
        try:
            pols = list(cliente.polizas.all())
        except Exception:
            pols = []

        if not pols:
            return "Sin póliza"

        # Elegimos la última por fecha_vencimiento
        def _key(p):
            fv = getattr(p, "fecha_vencimiento", None)
            return (fv is not None, fv)

        ultima = sorted(pols, key=_key, reverse=True)[0] if pols else None
        if not ultima:
            return "Sin póliza"

        # cálculo de mora: puede depender de cuotas; en detalle es aceptable
        try:
            dias_mora = int(ultima.calcular_mora_dias())
        except Exception:
            dias_mora = 0

        return "Al día" if dias_mora <= 0 else "Vencido"


# Backwards compatibility
ClienteSerializer = ClienteDetailSerializer