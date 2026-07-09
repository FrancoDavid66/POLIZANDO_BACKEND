from rest_framework import serializers
from .models import HistorialMensajeMarketing, HistorialMensajeMarketingLog

# Filtros que el backend aceptará procesar desde el frontend
MARKETING_ALLOWED_FILTERS = {
    "oficina", 
    "anio", 
    "modelo", 
    "compania", 
    "marca",
    "estado",
    "dias_condicion", # 🚀 NUEVO: Para saber si es a futuro o a pasado
    "dias_cantidad"   # 🚀 NUEVO: Para saber cuántos días
}

# Variables que el usuario puede insertar en el mensaje para personalización
MARKETING_ALLOWED_VARIABLES = [
    "nombre", 
    "apellido", 
    "oficina", 
    "anio", 
    "modelo", 
    "compania", 
    "patente"
]

class EnviarMensajeMarketingSerializer(serializers.Serializer):
    """
    Serializer para validar la petición de lanzamiento de campaña masiva.
    Incluye soporte para mensajes de texto y envío opcional de imágenes.
    """
    mensaje = serializers.CharField(required=True, help_text="Cuerpo del mensaje con variables.")
    filtros = serializers.JSONField(required=False, default=dict)
    oficina = serializers.CharField(required=False, allow_blank=True, default="")
    
    # Nuevo campo para enviar archivos multimedia vía UltraMsg
    imagen_url = serializers.URLField(required=False, allow_blank=True, allow_null=True) 
    
    dry_run = serializers.BooleanField(required=False, default=False)
    
    # Opciones adicionales para control fino del envío
    limit = serializers.IntegerField(required=False, min_value=1)
    skip_already_ok = serializers.BooleanField(required=False, default=False)

    def validate_filtros(self, value):
        """Asegura que solo se procesen los filtros permitidos por el sistema."""
        if not isinstance(value, dict):
            return {}
        return {k: v for k, v in value.items() if k in MARKETING_ALLOWED_FILTERS}


class HistorialMensajeMarketingSerializer(serializers.ModelSerializer):
    """
    Serializer para el listado y detalle del historial de ejecuciones pasadas.
    """
    variables_disponibles = serializers.SerializerMethodField()

    class Meta:
        model = HistorialMensajeMarketing
        fields = [
            "id",
            "mensaje",
            "filtros",
            "oficina",
            "created_by",
            "created_at",
            "ejecutado_at",
            "dry_run",
            "total_polizas_match",
            "total_destinatarios",
            "total_enviados",
            "total_errores",
            "total_invalidos",
            "total_omitidos",
            "variables_disponibles",
        ]
        read_only_fields = fields

    def to_representation(self, instance):
        """Limpia los datos del JSON de filtros antes de enviarlos al frontend."""
        data = super().to_representation(instance)
        filtros = data.get("filtros") or {}
        if isinstance(filtros, dict):
            data["filtros"] = {
                k: v for k, v in filtros.items() if k in MARKETING_ALLOWED_FILTERS
            }
        else:
            data["filtros"] = {}
        return data

    def get_variables_disponibles(self, obj):
        """Devuelve la lista de etiquetas que el usuario puede usar para personalizar."""
        return MARKETING_ALLOWED_VARIABLES


class HistorialMensajeMarketingLogSerializer(serializers.ModelSerializer):
    """
    Serializer para los registros individuales de cada mensaje enviado (logs).
    """
    class Meta:
        model = HistorialMensajeMarketingLog
        fields = [
            "id",
            "historial",
            "cliente_id",
            "poliza_id",
            "numero",
            "numero_normalizado",
            "estado",
            "error",
            "mensaje_renderizado",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]