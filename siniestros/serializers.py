# siniestros/serializers.py
from rest_framework import serializers
from .models import Siniestro, SiniestroEvento, SiniestroFoto


class SiniestroFotoSerializer(serializers.ModelSerializer):
    """Serializer simple para fotos del siniestro."""
    siniestro_id = serializers.PrimaryKeyRelatedField(
        queryset=Siniestro.objects.all(),
        source='siniestro',
        write_only=True,
    )
    siniestro = serializers.PrimaryKeyRelatedField(read_only=True)
    subida_por_nombre = serializers.SerializerMethodField()

    class Meta:
        model = SiniestroFoto
        fields = [
            'id',
            'siniestro', 'siniestro_id',
            'url', 'public_id',
            'nombre', 'mime', 'descripcion',
            'subida_por', 'subida_por_nombre',
            'fecha_creacion',
        ]
        read_only_fields = ['id', 'subida_por', 'fecha_creacion']

    def get_subida_por_nombre(self, obj):
        u = obj.subida_por
        if not u:
            return ''
        return u.get_full_name() or u.username

    def validate_url(self, value):
        if not value:
            raise serializers.ValidationError("La URL es obligatoria.")
        # Bloqueamos URLs locales: deben venir de Cloudinary
        low = value.lower()
        if "localhost" in low or "127.0.0.1" in low or "/media/" in low:
            raise serializers.ValidationError(
                "La URL debe ser de Cloudinary, no del servidor local."
            )
        return value

    def validate_public_id(self, value):
        if not value:
            raise serializers.ValidationError(
                "public_id es obligatorio (lo devuelve Cloudinary)."
            )
        return value


class SiniestroSerializer(serializers.ModelSerializer):
    """Serializer con labels de lectura y galería de fotos embebida."""
    cliente_label = serializers.SerializerMethodField()
    poliza_label = serializers.SerializerMethodField()
    estado_label = serializers.CharField(source='get_estado_display', read_only=True)
    responsabilidad_label = serializers.CharField(source='get_responsabilidad_display', read_only=True)
    # 📸 Lista de fotos embebida en el detalle del siniestro
    fotos = SiniestroFotoSerializer(many=True, read_only=True)
    fotos_count = serializers.SerializerMethodField()

    class Meta:
        model = Siniestro
        fields = [
            'id',
            'cliente', 'cliente_label',
            'poliza', 'poliza_label',
            'marca_auto', 'modelo_auto', 'ano_auto', 'patente',
            'nro_reclamo_cia', 'fecha_siniestro',
            'responsabilidad', 'responsabilidad_label',
            'estado', 'estado_label',
            'descripcion',
            'tercero_nombre', 'tercero_telefono', 'tercero_patente',
            'tercero_compania', 'tercero_poliza',
            'fecha_creacion', 'fecha_modificacion',
            'fotos', 'fotos_count',
        ]

    def get_cliente_label(self, obj):
        return str(obj.cliente) if obj.cliente else "—"

    def get_poliza_label(self, obj):
        return str(obj.poliza) if obj.poliza else "—"

    def get_fotos_count(self, obj):
        # Si la relación ya fue prefetcheada, usamos len; sino, count.
        try:
            return obj.fotos.count()
        except Exception:
            return 0

    def validate_patente(self, value):
        if value:
            return value.replace(' ', '').upper()
        return value

    def validate_tercero_patente(self, value):
        if value:
            return value.replace(' ', '').upper()
        return value


class SiniestroEventoSerializer(serializers.ModelSerializer):
    siniestro_id = serializers.PrimaryKeyRelatedField(
        queryset=Siniestro.objects.all(),
        source='siniestro',
        write_only=True,
    )
    siniestro = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = SiniestroEvento
        fields = ['id', 'siniestro', 'siniestro_id', 'fecha_evento', 'descripcion_evento']