# cotizaciones/serializers.py
from rest_framework import serializers
from .models import Cotizacion, OpcionCotizacion, CompaniaSeguro, TipoCobertura, ConfiguracionGlobal

class CompaniaSeguroSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompaniaSeguro
        fields = ['id', 'nombre', 'comision_default', 'antiguedad_maxima', 'logo_url', 'activa']

class TipoCoberturaSerializer(serializers.ModelSerializer):
    compania_nombre = serializers.CharField(source='compania.nombre', read_only=True)

    class Meta:
        model = TipoCobertura
        # 🚀 AGREGAMOS LOS CAMPOS DE FACTURACIÓN A LA API
        fields = ['id', 'nombre', 'compania', 'compania_nombre', 'beneficios_default', 'fotos_requeridas', 'documentos_requeridos', 'cuotas_a_generar', 'genera_cupones_robo', 'activa'] 

class ConfiguracionGlobalSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConfiguracionGlobal
        fields = ['id', 'margen_ganancia_default']

class OpcionCotizacionSerializer(serializers.ModelSerializer):
    ganancia_neta = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    compania_nombre = serializers.CharField(source='compania.nombre', read_only=True) 
    cobertura_nombre = serializers.CharField(source='cobertura.nombre', read_only=True)

    class Meta:
        model = OpcionCotizacion
        fields = ['id', 'compania', 'cobertura', 'compania_nombre', 'cobertura_nombre', 
                  'costo_compania', 'porcentaje_comision', 
                  'precio_cliente', 'detalles_cobertura', 'es_recomendada', 'ganancia_neta', 'suma_asegurada', 'objetivo_ganancia']
        read_only_fields = ['cotizacion']

class CotizacionSerializer(serializers.ModelSerializer):
    opciones = OpcionCotizacionSerializer(many=True, required=False)
    
    class Meta:
        model = Cotizacion
        fields = ['id', 'cliente_nombre', 'telefono', 'marca_auto', 'modelo_auto', 
                  'anio_auto', 'tiene_gnc', 'estado', 'creado_por', 'created_at', 'updated_at', 'opciones']
        read_only_fields = ['creado_por', 'created_at', 'updated_at']

    def create(self, validated_data):
        opciones_data = validated_data.pop('opciones', [])
        cotizacion = Cotizacion.objects.create(**validated_data)
        for op_data in opciones_data:
            OpcionCotizacion.objects.create(cotizacion=cotizacion, **op_data)
        return cotizacion

    def update(self, instance, validated_data):
        opciones_data = validated_data.pop('opciones', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if opciones_data is not None:
            instance.opciones.all().delete()
            for op_data in opciones_data:
                OpcionCotizacion.objects.create(cotizacion=instance, **op_data)
        return instance