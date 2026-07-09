# tareas/serializers_fijas.py
from rest_framework import serializers

from .models_fijas import TareaFija, Feriado


class TareaFijaSerializer(serializers.ModelSerializer):
    responsable_nombre = serializers.SerializerMethodField()
    oficina_nombre = serializers.SerializerMethodField()

    class Meta:
        model = TareaFija
        fields = [
            "id", "nombre",
            "oficina", "oficina_nombre",
            "responsable", "responsable_nombre",
            "frecuencia", "dias_semana", "hora_esperada", "margen_alerta",
            "requiere_foto", "instruccion_foto", "premia_demora", "activa", "orden",
        ]

    def get_responsable_nombre(self, obj):
        if not obj.responsable:
            return ""
        return (obj.responsable.get_full_name() or obj.responsable.username or "")

    def get_oficina_nombre(self, obj):
        return obj.oficina.nombre if obj.oficina else "Todas"


class FeriadoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feriado
        fields = ["id", "fecha", "nombre", "nacional"]