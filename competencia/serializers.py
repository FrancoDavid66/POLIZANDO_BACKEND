from rest_framework import serializers
from .models import (
    Competidor,
    CompetidorCanal,
    CompetidorUbicacion,
    MiPrecioReferencia,
    OficinaMapa,
    OportunidadCompetencia,
)


class CompetidorSerializer(serializers.ModelSerializer):
    """
    Pensado simple para el nuevo flujo:
    - nombre
    - redes
    - activo
    - timestamps (por si querés analizar después)
    """

    class Meta:
        model = Competidor
        fields = [
            "id",
            "nombre",
            "redes",
            "activo",
            "created_at",
            "updated_at",
        ]


class CompetidorCanalSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompetidorCanal
        fields = "__all__"


class CompetidorUbicacionSerializer(serializers.ModelSerializer):
    # ✅ Campos calculados para la tabla de análisis
    nombre = serializers.CharField(source="competidor.nombre", read_only=True)
    redes = serializers.CharField(source="competidor.redes", read_only=True)

    class Meta:
        model = CompetidorUbicacion
        fields = [
            "id",
            "competidor",  # FK para crear/editar
            # Datos para la tabla:
            "nombre",
            "precio",
            "compania",
            "cobertura",
            "redes",
            # Ubicación:
            "direccion",
            "ciudad",
            "url_maps",
            "latitud",
            "longitud",
            # Metadatos:
            "created_at",
            "updated_at",
        ]


class MiPrecioReferenciaSerializer(serializers.ModelSerializer):
    class Meta:
        model = MiPrecioReferencia
        fields = [
            "id",
            "cobertura",
            "compania",
            "ciudad",
            "precio",
            "notas",
            "activo",
            "created_at",
            "updated_at",
        ]


class OficinaMapaSerializer(serializers.ModelSerializer):
    class Meta:
        model = OficinaMapa
        fields = "__all__"


class OportunidadCompetenciaSerializer(serializers.ModelSerializer):
    class Meta:
        model = OportunidadCompetencia
        fields = "__all__"
