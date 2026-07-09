# inmuebles/serializers.py
from rest_framework import serializers
from .models import Propiedad, Alquiler, CuotaAlquiler, Inquilino, Propietario
from dateutil.relativedelta import relativedelta
from datetime import date



class PropiedadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Propiedad
        fields = '__all__'




### 🧍‍♂️ Inquilino
class InquilinoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Inquilino
        fields = '__all__'


### 🧍‍♂️ Propietario
class PropietarioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Propietario
        fields = '__all__'


### 🏠 Propiedad
class PropiedadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Propiedad
        fields = '__all__'


### 💵 Cuotas de Alquiler
class CuotaAlquilerSerializer(serializers.ModelSerializer):
    class Meta:
        model = CuotaAlquiler
        fields = '__all__'


### 📄 Alquiler
class AlquilerSerializer(serializers.ModelSerializer):
    inquilinos = serializers.PrimaryKeyRelatedField(queryset=Inquilino.objects.all(), many=True)
    propietarios = serializers.PrimaryKeyRelatedField(queryset=Propietario.objects.all(), many=True)
    cuotas = CuotaAlquilerSerializer(many=True, read_only=True)

    class Meta:
        model = Alquiler
        fields = '__all__'

    def create(self, validated_data):
        inquilinos = validated_data.pop('inquilinos', [])
        propietarios = validated_data.pop('propietarios', [])
        alquiler = Alquiler.objects.create(**validated_data)

        alquiler.inquilinos.set(inquilinos)
        alquiler.propietarios.set(propietarios)

        # ✅ Generar cuotas automáticas con aumentos
        self.generar_cuotas_con_aumento(alquiler)

        return alquiler

    def generar_cuotas_con_aumento(self, alquiler):
        fecha = alquiler.fecha_inicio
        fin = alquiler.fecha_fin
        monto = alquiler.precio_mensual
        aumento_cada = alquiler.aumento_cada_n_meses
        aumento_porcentaje = alquiler.porcentaje_aumento

        numero = 1
        while fecha < fin:
            CuotaAlquiler.objects.create(
                alquiler=alquiler,
                numero=numero,
                fecha_vencimiento=fecha,
                monto=round(monto, 2)
            )
            numero += 1
            if (numero - 1) % aumento_cada == 0:
                monto += monto * (aumento_porcentaje / 100)
            fecha += relativedelta(months=1)
