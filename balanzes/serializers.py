# balanzes/serializers.py
import re
from rest_framework import serializers
from .models import Ingreso, Egreso, Categoria


class CategoriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Categoria
        fields = ['id', 'nombre', 'tipo', 'created_at']


class IngresoSerializer(serializers.ModelSerializer):
    oficina_nombre        = serializers.SerializerMethodField()
    usuario_nombre        = serializers.SerializerMethodField()
    verificada_por_nombre = serializers.SerializerMethodField()
    # 🚀 NUEVO: patente resuelta a partir del N° de póliza guardado en la descripción.
    # Funciona para pagos VIEJOS y NUEVOS por igual (no requiere recargar nada).
    patente               = serializers.SerializerMethodField()

    class Meta:
        model = Ingreso
        fields = [
            "id", "descripcion", "patente", "monto", "fecha", "oficina", "oficina_nombre",
            "categoria", "forma_pago", "pagado_por", "billetera",
            "cuit_remitente", "nro_operacion", "observaciones",
            "verificada", "verificada_por", "verificada_por_nombre",
            "verificada_en", "nota_verificacion",
            "usuario", "usuario_nombre", "created_at", "updated_at",
        ]
        read_only_fields = ["usuario", "verificada_por", "verificada_en", "created_at", "updated_at"]

    def get_oficina_nombre(self, obj):
        return obj.oficina.nombre if obj.oficina else None

    def get_usuario_nombre(self, obj):
        if obj.usuario:
            return f"{obj.usuario.first_name} {obj.usuario.last_name}".strip() or obj.usuario.username
        return "Sistema"

    def get_verificada_por_nombre(self, obj):
        if obj.verificada_por:
            return f"{obj.verificada_por.first_name} {obj.verificada_por.last_name}".strip() or obj.verificada_por.username
        return None

    # ──────────────────────────────────────────────────────────────────
    # PATENTE
    # La descripción de un cobro de cuota es: "Pago cuota N - Póliza 12345".
    # Sacamos ese 12345, buscamos la póliza y devolvemos su patente.
    # Usamos un cache en el propio serializer para que, si hay 50 pagos de
    # la misma póliza, se haga UNA sola consulta y no 50.
    # ──────────────────────────────────────────────────────────────────
    _RE_POLIZA = re.compile(r'P[oó]liza\s+(.+?)\s*$', re.IGNORECASE)

    def get_patente(self, obj):
        # 1) Si el Ingreso ya guarda la patente como campo, usarla directo.
        patente_directa = getattr(obj, "patente", None)
        if isinstance(patente_directa, str) and patente_directa.strip():
            return patente_directa.strip().upper()

        # 2) Si no, deducirla del número de póliza que está en la descripción.
        desc = obj.descripcion or ""
        m = self._RE_POLIZA.search(desc)
        if not m:
            return ""
        numero = (m.group(1) or "").strip()
        if not numero:
            return ""

        # Cache por número de póliza (vive durante esta serialización)
        if not hasattr(self, "_patente_cache"):
            self._patente_cache = {}
        if numero in self._patente_cache:
            return self._patente_cache[numero]

        patente = ""
        try:
            from polizas.models import Poliza
            pol = Poliza.objects.filter(numero_poliza=numero).only("patente").first()
            if pol and pol.patente:
                patente = str(pol.patente).strip().upper()
        except Exception:
            patente = ""

        self._patente_cache[numero] = patente
        return patente


class EgresoSerializer(serializers.ModelSerializer):
    oficina_nombre = serializers.SerializerMethodField()
    usuario_nombre = serializers.SerializerMethodField()

    class Meta:
        model = Egreso
        fields = [
            "id", "descripcion", "monto", "fecha", "oficina", "oficina_nombre",
            "categoria", "forma_pago", "observaciones", "usuario",
            "usuario_nombre", "created_at", "updated_at",
        ]
        read_only_fields = ["usuario", "created_at", "updated_at"]

    def get_oficina_nombre(self, obj):
        return obj.oficina.nombre if obj.oficina else None

    def get_usuario_nombre(self, obj):
        if obj.usuario:
            return f"{obj.usuario.first_name} {obj.usuario.last_name}".strip() or obj.usuario.username
        return "Sistema"