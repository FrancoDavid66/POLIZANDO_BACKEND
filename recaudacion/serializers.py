from rest_framework import serializers
from .models import CierreCaja

class CierreCajaSerializer(serializers.ModelSerializer):
    usuario_nombre = serializers.SerializerMethodField(read_only=True)
    oficina_nombre = serializers.CharField(source='oficina.nombre', read_only=True)
    # 🚀 NUEVO: Exponemos el nombre del empleado
    empleado_nombre = serializers.CharField(source='empleado.nombre', read_only=True)

    class Meta:
        model = CierreCaja
        fields = [
            'id', 'foto_url', 'foto_public_id', 'monto_declarado',
            'monto_sistema', 'diferencia', 'estado_auditoria', 'turno',
            'empleado', 'empleado_nombre', # 🚀 Agregados
            'usuario', 'usuario_nombre', 'oficina', 'oficina_nombre', 'creado_en'
        ]
        read_only_fields = ['usuario', 'oficina', 'creado_en', 'monto_sistema', 'diferencia', 'estado_auditoria', 'turno']

    def get_usuario_nombre(self, obj):
        if obj.usuario:
            return f"{getattr(obj.usuario, 'first_name', '')} {getattr(obj.usuario, 'last_name', '')}".strip() or obj.usuario.username
        return "Desconocido"

from .models import HorarioCierreCaja

class HorarioCierreCajaSerializer(serializers.ModelSerializer):
    oficina_nombre = serializers.CharField(source='oficina.nombre', read_only=True)

    class Meta:
        model = HorarioCierreCaja
        fields = ['id', 'oficina', 'oficina_nombre', 'mediodia', 'noche',
                  'aviso_min', 'tolerancia_min', 'activo']