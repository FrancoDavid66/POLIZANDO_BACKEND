from rest_framework import serializers
from .models import Propietario, Inquilino, Alquiler, CuotaAlquiler, Garante
from dateutil.relativedelta import relativedelta

# ─── SERIALIZADORES BASE ─────────────────────────────────────────────

class PropietarioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Propietario
        fields = '__all__'


class GaranteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Garante
        fields = '__all__'


class InquilinoWithGarantesSerializer(serializers.ModelSerializer):
    garantes = GaranteSerializer(many=True, read_only=True)

    class Meta:
        model = Inquilino
        fields = '__all__'


class InquilinoSerializer(serializers.ModelSerializer):
    garantes = serializers.PrimaryKeyRelatedField(queryset=Garante.objects.all(), many=True)

    class Meta:
        model = Inquilino
        fields = '__all__'


class CuotaAlquilerSerializer(serializers.ModelSerializer):
    class Meta:
        model = CuotaAlquiler
        fields = '__all__'

# ─── ALQUILER ────────────────────────────────────────────────────────

class AlquilerReadSerializer(serializers.ModelSerializer):
    propietarios = PropietarioSerializer(many=True, read_only=True)
    inquilinos = InquilinoWithGarantesSerializer(many=True, read_only=True)
    cuotas = CuotaAlquilerSerializer(many=True, read_only=True)

    class Meta:
        model = Alquiler
        fields = '__all__'


class AlquilerWriteSerializer(serializers.ModelSerializer):
    propietarios = serializers.PrimaryKeyRelatedField(queryset=Propietario.objects.all(), many=True)
    inquilinos = serializers.PrimaryKeyRelatedField(queryset=Inquilino.objects.all(), many=True)

    class Meta:
        model = Alquiler
        fields = '__all__'

    def create(self, validated_data):
        propietarios_data = validated_data.pop('propietarios')
        inquilinos_data = validated_data.pop('inquilinos')

        alquiler = Alquiler.objects.create(**validated_data)
        alquiler.propietarios.set(propietarios_data)
        alquiler.inquilinos.set(inquilinos_data)

        self.generar_cuotas_con_aumentos(alquiler)

        return alquiler

    def generar_cuotas_con_aumentos(self, alquiler):
        fecha = alquiler.fecha_inicio
        total_meses = (alquiler.fecha_fin.year - alquiler.fecha_inicio.year) * 12 + (alquiler.fecha_fin.month - alquiler.fecha_inicio.month)
        precio = float(alquiler.precio_alquiler)

        for i in range(total_meses):
            nro_cuota = i + 1
            vencimiento = fecha + relativedelta(months=i)

            if i > 0 and alquiler.aumento_cada_meses and i % alquiler.aumento_cada_meses == 0:
                aumento = precio * (float(alquiler.porcentaje_aumento) / 100)
                precio += aumento

            CuotaAlquiler.objects.create(
                alquiler=alquiler,
                nro_cuota=nro_cuota,
                monto=round(precio, 2),
                fecha_vencimiento=vencimiento
            )
