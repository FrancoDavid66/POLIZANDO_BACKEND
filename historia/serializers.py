from rest_framework import serializers
from historia.models import PolizaEvento

class PolizaEventoSerializer(serializers.ModelSerializer):
    actor_display = serializers.SerializerMethodField()

    class Meta:
        model = PolizaEvento
        fields = [
            'id', 'poliza',
            'categoria', 'tipo', 'severidad',
            'mensaje', 'data',
            'subject_type', 'subject_id',
            'actor', 'actor_name', 'actor_display',
            'source', 'idempotency_key',
            'created_at',
        ]

    def get_actor_display(self, obj):
        if obj.actor:
            fn = getattr(obj.actor, "first_name", "") or ""
            ln = getattr(obj.actor, "last_name", "") or ""
            nm = (fn + " " + ln).strip() or getattr(obj.actor, "username", "")
            return nm
        return obj.actor_name or "sistema"
