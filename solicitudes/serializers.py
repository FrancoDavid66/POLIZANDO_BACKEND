# solicitudes/serializers.py
from django.db import transaction
from rest_framework import serializers

from .models import (
    SolicitudSeguro,
    SolicitudDocumento,
    TipoDocSolicitud,
    Empleado,
)
from polizas.models import Poliza


class EmpleadoSerializer(serializers.ModelSerializer):
    oficina_nombre = serializers.SerializerMethodField()

    class Meta:
        model = Empleado
        fields = "__all__"
        read_only_fields = ("id", "creado_en", "actualizado_en")

    def get_oficina_nombre(self, obj):
        return obj.oficina.nombre if obj.oficina else ""

    @staticmethod
    def _norm_nombre(v):
        return " ".join(str(v or "").strip().split()).upper()

    def validate_nombre(self, value):
        value = self._norm_nombre(value)
        if not value: raise serializers.ValidationError("El nombre es obligatorio.")
        return value

    def create(self, validated_data):
        validated_data["nombre"] = self._norm_nombre(validated_data.get("nombre"))
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if "nombre" in validated_data:
            validated_data["nombre"] = self._norm_nombre(validated_data.get("nombre"))
        return super().update(instance, validated_data)


class SolicitudDocumentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = SolicitudDocumento
        fields = "__all__"
        read_only_fields = ("id", "creado_en")

    def validate(self, attrs):
        tipo = attrs.get("tipo")
        if isinstance(tipo, str): attrs["tipo"] = tipo.upper()
        if not attrs.get("tipo"): attrs["tipo"] = TipoDocSolicitud.OTRO
        tipo_up = str(attrs["tipo"]).upper()
        if tipo_up in {"REGISTRO", "REGISTRO_CONDUCIR"}:
            raise serializers.ValidationError({"tipo": "Este documento ya no se solicita en esta etapa."})
        return attrs


class SolicitudSeguroSerializer(serializers.ModelSerializer):
    documentos = SolicitudDocumentoSerializer(many=True, read_only=True)
    responsable_empleado_nombre = serializers.CharField(source="responsable_empleado.nombre", read_only=True)
    tareas = serializers.SerializerMethodField(read_only=True)
    cliente_id = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = SolicitudSeguro
        fields = "__all__"
        read_only_fields = (
            "id", "codigo", "estado", "creado_en",
            "actualizado_en", "asignado_en", "terminada_en", "cliente_id"
        )

    def get_tareas(self, obj):
        return {
            "alta_compania": bool(getattr(obj, "alta_compania", False)),
            "enviar_poliza": bool(getattr(obj, "enviar_poliza", False)),
        }

    def get_cliente_id(self, obj):
        # 🔧 FIX: 'poliza_id' es un IntegerField plano (no ForeignKey), así que
        # obj nunca tiene un atributo 'poliza' de verdad — hasattr(obj, 'poliza')
        # siempre daba False y esto devolvía None sin importar el caso.
        if not obj.poliza_id:
            return None
        return Poliza.objects.filter(id=obj.poliza_id).values_list("cliente_id", flat=True).first()

    def validate(self, attrs):
        is_create = self.instance is None
        nom = attrs.get("responsable_nombre", None)
        if nom is not None: attrs["responsable_nombre"] = (str(nom).strip() or "")
        legacy = attrs.get("responsable", None)
        if legacy is not None: attrs["responsable"] = (str(legacy).strip() or "")

        chosen_name = (attrs.get("responsable_nombre") or attrs.get("responsable") or "").strip()
        emp = attrs.get("responsable_empleado", serializers.empty)
        emp_instance = None if emp is serializers.empty else emp

        if is_create and not (chosen_name or emp_instance):
            raise serializers.ValidationError({"responsable_nombre": "Campo obligatorio: indicá el responsable."})
        
        final_name = chosen_name or (emp_instance.nombre if emp_instance else "")
        attrs["responsable_nombre"] = final_name
        attrs["responsable"] = final_name
        return attrs

    def create(self, validated_data):
        responsable_nombre = validated_data.pop("responsable_nombre", None)
        responsable = validated_data.pop("responsable", None)
        responsable_empleado = validated_data.pop("responsable_empleado", None)
        obj: SolicitudSeguro = super().create(validated_data)
        if responsable_empleado is not None:
            obj.reasignar(responsable_empleado.nombre)
            obj.responsable_empleado = responsable_empleado
        else:
            obj.reasignar(responsable_nombre or responsable or "")
        obj.save(update_fields=["responsable", "responsable_empleado", "asignado_en", "actualizado_en"])
        return obj

    def update(self, instance, validated_data):
        sentinel = object()
        responsable_nombre = validated_data.pop("responsable_nombre", sentinel)
        responsable = validated_data.pop("responsable", sentinel)
        responsable_empleado = validated_data.pop("responsable_empleado", sentinel)
        obj: SolicitudSeguro = super().update(instance, validated_data)

        if responsable_empleado is not sentinel:
            nombre = responsable_empleado.nombre if responsable_empleado else ""
            obj.reasignar(nombre)
            obj.responsable_empleado = responsable_empleado
            obj.save(update_fields=["responsable", "responsable_empleado", "asignado_en", "actualizado_en"])
        return obj


class SolicitudAsociarPolizaSerializer(serializers.Serializer):
    solicitud_id = serializers.IntegerField()
    poliza_id = serializers.IntegerField()
    @transaction.atomic
    def save(self, **kwargs):
        sol = SolicitudSeguro.objects.get(id=self.validated_data["solicitud_id"])
        pol = Poliza.objects.get(id=self.validated_data["poliza_id"])
        sol.poliza_id = pol.id
        sol.save(update_fields=["poliza_id", "actualizado_en"])
        return {"ok": True, "solicitud_id": sol.id, "poliza_id": pol.id}

# 🚀 El flujo pesado de alta (CrearCompletoSerializer + su importer y helpers de
#    cuponera) vive en serializers_crear_completo.py. Se re-exporta acá para que
#    los imports existentes sigan funcionando (views.py hace
#    `from .serializers import CrearCompletoSerializer`).
from .serializers_crear_completo import CrearCompletoSerializer  # noqa: E402,F401