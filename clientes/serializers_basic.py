from rest_framework import serializers
from .models import Cliente

class ClienteBasicSerializer(serializers.ModelSerializer):
    # ✅ Estos campos pueden venir anotados en list(); si no, caen a null/0 sin romper
    polizas_total = serializers.IntegerField(read_only=True, required=False)
    polizas_activas = serializers.IntegerField(read_only=True, required=False)
    deuda = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True, required=False)
    ultima_fecha_vencimiento = serializers.DateField(read_only=True, required=False, allow_null=True)
    ultima_mora_dias = serializers.IntegerField(read_only=True, required=False, allow_null=True)

    class Meta:
        model = Cliente
        fields = [
            "id",
            "nombre",
            "apellido",
            "telefono",
            "email",
            "dni_cuit_cuil",
            "direccion",
            "localidad",          # 🚀 NUEVO: para mostrarlo en la auditoría de calidad
            "fecha_nacimiento",
            "estado",

            # ✅ extras (si vienen anotados)
            "polizas_total",
            "polizas_activas",
            "deuda",
            "ultima_fecha_vencimiento",
            "ultima_mora_dias",

            # Documentación del cliente (frente/dorso)
            "archivo_dni",  # compatibilidad legada
            "archivo_dni_frente",
            "archivo_dni_dorso",
            "archivo_pasaporte_frente",
            "archivo_pasaporte_dorso",
        ]