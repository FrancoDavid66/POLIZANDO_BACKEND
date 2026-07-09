# servicios/serializers.py
from rest_framework import serializers
from .models import ServicioFijo, PagoServicio, CategoriaServicio


# ════════════════════════════════════════════════════════════════
# CategoriaServicio (CRUD)
# ════════════════════════════════════════════════════════════════
class CategoriaServicioSerializer(serializers.ModelSerializer):
    cantidad_servicios = serializers.SerializerMethodField()

    class Meta:
        model = CategoriaServicio
        fields = [
            'id',
            'nombre',
            'color',
            'activo',
            'creado_en',
            'creado_por',
            'cantidad_servicios',
        ]
        read_only_fields = ['creado_en', 'creado_por']

    def get_cantidad_servicios(self, obj):
        return ServicioFijo.objects.filter(categoria__iexact=obj.nombre).count()

    def validate_nombre(self, value):
        v = (value or "").strip()
        if not v:
            raise serializers.ValidationError("El nombre no puede estar vacío")
        qs = CategoriaServicio.objects.filter(nombre__iexact=v)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Ya existe una categoría con ese nombre")
        return v


# ════════════════════════════════════════════════════════════════
# ServicioFijo
# ════════════════════════════════════════════════════════════════
class ServicioFijoSerializer(serializers.ModelSerializer):
    oficina_nombre = serializers.CharField(source='oficina.nombre', read_only=True)
    oficina_codigo = serializers.CharField(source='oficina.codigo', read_only=True)
    creado_por_nombre = serializers.SerializerMethodField()

    total_pagos_realizados = serializers.SerializerMethodField()
    ultimo_pago_fecha = serializers.SerializerMethodField()
    ultimo_pago_monto = serializers.SerializerMethodField()

    class Meta:
        model = ServicioFijo
        fields = [
            'id',
            'nombre',
            'proveedor',
            'categoria',
            'oficina',
            'oficina_nombre',
            'oficina_codigo',
            'monto_estimado',
            'dia_vencimiento',
            'forma_pago_default',
            'activo',
            'notas',
            'creado_en',
            'actualizado_en',
            'creado_por',
            'creado_por_nombre',
            'total_pagos_realizados',
            'ultimo_pago_fecha',
            'ultimo_pago_monto',
        ]
        read_only_fields = ['creado_en', 'actualizado_en', 'creado_por']

    def get_creado_por_nombre(self, obj):
        if not obj.creado_por:
            return None
        full = f"{obj.creado_por.first_name} {obj.creado_por.last_name}".strip()
        return full or obj.creado_por.username

    def get_total_pagos_realizados(self, obj):
        return obj.pagos.filter(estado='PAGADO').count()

    def get_ultimo_pago_fecha(self, obj):
        ultimo = obj.pagos.filter(estado='PAGADO').order_by('-fecha_pago').first()
        return ultimo.fecha_pago if ultimo else None

    def get_ultimo_pago_monto(self, obj):
        ultimo = obj.pagos.filter(estado='PAGADO').order_by('-fecha_pago').first()
        return ultimo.monto_real if ultimo else None

    def validate_dia_vencimiento(self, value):
        if value < 1 or value > 31:
            raise serializers.ValidationError("El día debe estar entre 1 y 31.")
        return value


# ════════════════════════════════════════════════════════════════
# PagoServicio (read)
# ════════════════════════════════════════════════════════════════
class PagoServicioSerializer(serializers.ModelSerializer):
    servicio_nombre = serializers.CharField(source='servicio.nombre', read_only=True)
    servicio_proveedor = serializers.CharField(source='servicio.proveedor', read_only=True)
    servicio_categoria = serializers.CharField(source='servicio.categoria', read_only=True)
    servicio_dia_venc = serializers.IntegerField(source='servicio.dia_vencimiento', read_only=True)
    servicio_monto_estimado = serializers.DecimalField(
        source='servicio.monto_estimado',
        max_digits=12, decimal_places=2, read_only=True
    )

    oficina = serializers.IntegerField(source='servicio.oficina_id', read_only=True)
    oficina_nombre = serializers.CharField(source='servicio.oficina.nombre', read_only=True)

    pagado_por_nombre = serializers.SerializerMethodField()

    medio_cobro_etiqueta = serializers.SerializerMethodField()
    medio_cobro_valor = serializers.CharField(source='medio_cobro.valor', read_only=True)
    medio_cobro_titular = serializers.CharField(source='medio_cobro.titular_nombre', read_only=True)
    medio_cobro_proveedor = serializers.CharField(source='medio_cobro.proveedor', read_only=True)

    egreso_id_ref = serializers.IntegerField(source='egreso.id', read_only=True)

    dias_hasta_vencimiento = serializers.IntegerField(read_only=True)
    esta_por_vencer = serializers.BooleanField(read_only=True)
    esta_vencido = serializers.BooleanField(read_only=True)

    class Meta:
        model = PagoServicio
        fields = [
            'id',
            'servicio',
            'servicio_nombre',
            'servicio_proveedor',
            'servicio_categoria',
            'servicio_dia_venc',
            'servicio_monto_estimado',
            'oficina',
            'oficina_nombre',
            'periodo',
            'fecha_vencimiento',
            'estado',
            'monto_real',
            'fecha_pago',
            'hora_pago',
            'pagado_por',
            'pagado_por_nombre',
            'forma_pago',
            'medio_cobro',
            'medio_cobro_etiqueta',
            'medio_cobro_valor',
            'medio_cobro_titular',
            'medio_cobro_proveedor',
            'comprobante_url',
            'egreso',
            'egreso_id_ref',
            'observaciones',
            'creado_en',
            'actualizado_en',
            'dias_hasta_vencimiento',
            'esta_por_vencer',
            'esta_vencido',
        ]
        read_only_fields = ['creado_en', 'actualizado_en', 'egreso']

    def get_pagado_por_nombre(self, obj):
        if not obj.pagado_por:
            return None
        full = f"{obj.pagado_por.first_name} {obj.pagado_por.last_name}".strip()
        return full or obj.pagado_por.username

    def get_medio_cobro_etiqueta(self, obj):
        if not obj.medio_cobro:
            return None
        return obj.medio_cobro.etiqueta or obj.medio_cobro.titular_nombre or str(obj.medio_cobro)


# ════════════════════════════════════════════════════════════════
# Registrar pago
# ════════════════════════════════════════════════════════════════
class RegistrarPagoServicioSerializer(serializers.Serializer):
    monto = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0.01)
    fecha = serializers.DateField()
    forma_pago = serializers.ChoiceField(
        choices=[
            ("EFECTIVO", "Efectivo"),
            ("TRANSFERENCIA", "Transferencia"),
            ("MERCADOPAGO", "Mercado Pago"),
        ]
    )
    medio_cobro_id = serializers.IntegerField(required=False, allow_null=True)
    comprobante_url = serializers.URLField(required=False, allow_blank=True, default="")
    observaciones = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, data):
        if data['forma_pago'] != 'EFECTIVO' and not data.get('medio_cobro_id'):
            raise serializers.ValidationError({
                'medio_cobro_id': 'Para Transferencia o Mercado Pago debés seleccionar una billetera.'
            })
        return data