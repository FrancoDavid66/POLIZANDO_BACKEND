# polizas/serializers.py
from datetime import timedelta
from decimal import Decimal, InvalidOperation
import re

from rest_framework import serializers
from django.utils import timezone

from polizas.models import (
    Poliza,
    FotoVehiculo,
    PolizaDocumento,
    CuponRobo,            
)
from clientes.models import Cliente
from clientes.serializers_basic import ClienteBasicSerializer

from pagos.serializers import PagoSerializer  
from pagos.models import Cuota  
from polizas.precios_nre import es_nre, precio_vigente

def _to_bool(v) -> bool:
    if v is None:
        return False
    return str(v).strip().lower() in {"1", "true", "t", "yes", "y", "on", "si", "sí"}

def _get_compania_nombre_robusto(obj):
    if hasattr(obj, "compania_obj") and obj.compania_obj:
        return obj.compania_obj.nombre
    posibles_fk = ["compania", "aseguradora", "cia", "company"]
    posibles_nombre = ["nombre", "razon_social", "razonSocial", "name", "razon"]
    for fk in posibles_fk:
        ref = getattr(obj, fk, None)
        if not ref:
            continue
        if isinstance(ref, str):
            val = ref.strip()
            if val:
                return val
            continue
        for attr in posibles_nombre:
            val = getattr(ref, attr, None)
            if val:
                return str(val)
        try:
            s = str(ref)
            if s and s != obj.__class__.__name__:
                return s
        except Exception:
            pass
    for plano in ["compania", "aseguradora", "cia", "company"]:
        val = getattr(obj, plano, None)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None

def _get_cobertura_nombre_robusto(obj):
    if hasattr(obj, "cobertura_obj") and obj.cobertura_obj:
        return obj.cobertura_obj.nombre
    return getattr(obj, "cobertura", None)

def _safe_annot(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default

def _get_cliente_telefono_robusto(cliente) -> str:
    if not cliente:
        return ""
    candidates = ["telefono", "celular", "whatsapp", "telefono1", "telefono2", "numero", "phone", "mobile"]
    for k in candidates:
        try:
            v = getattr(cliente, k, None)
        except Exception:
            v = None
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""

def _telefono_to_e164_ar(raw: str, default_cc: str = "54") -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    if s.startswith("+"):
        digits = re.sub(r"\D", "", s[1:])
        return f"+{digits}" if digits else ""
    digits = re.sub(r"\D", "", s)
    if not digits:
        return ""
    return f"+{default_cc}{digits}"


class CuotaMiniSerializer(serializers.ModelSerializer):
    monto = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Cuota
        fields = ["id", "cuota_nro", "fecha_vencimiento", "monto", "pagado", "forma_pago", "fecha_pago"]
        read_only_fields = ["id", "cuota_nro", "fecha_vencimiento", "pagado", "forma_pago", "fecha_pago"]

    def get_monto(self, obj):
        """Mismo criterio que CuotaFlatSerializer (pagos/serializers.py):
        si la cuota está IMPAGA y en $0, sugerimos un monto (SIEMPRE editable
        en el modal de cobro, nunca fijo):
          1) precio_cuota de la póliza (cargado a mano al crear/renovar);
          2) si sigue en 0 y es NRE → precio de lista según el `tipo`.
        Si nada da un número, se muestra $0. Cuotas ya pagadas: tal cual se cobraron.
        """
        raw = obj.monto
        try:
            val = Decimal(str(raw)) if raw is not None else Decimal("0")
        except (InvalidOperation, TypeError, ValueError):
            val = Decimal("0")

        if not getattr(obj, "pagado", False) and val <= 0:
            pol = getattr(obj, "poliza", None)
            if pol is not None:
                try:
                    pc = getattr(pol, "precio_cuota", None)
                    if pc is not None and Decimal(str(pc)) > 0:
                        val = Decimal(str(pc))
                except (InvalidOperation, TypeError, ValueError):
                    pass
                if val <= 0:
                    try:
                        if es_nre(getattr(pol, "compania", "")):
                            precio = precio_vigente(
                                getattr(pol, "tipo", None),
                                timezone.localdate(),
                                getattr(pol, "oficina", None),
                            )
                            if precio:
                                val = Decimal(str(precio))
                    except Exception:
                        pass

        return f"{val:.2f}"


class FotoVehiculoSerializer(serializers.ModelSerializer):
    tipo = serializers.CharField(max_length=30, required=False, allow_blank=True)
    origen = serializers.CharField(max_length=30, required=False, allow_blank=True)
    
    class Meta:
        model = FotoVehiculo
        fields = "__all__"
        
    def validate(self, attrs):
        def _u(x: str) -> str:
            return (x or "").strip().upper().replace(" ", "_")
        
        t = attrs.get("tipo")
        if isinstance(t, str) and t:
            t_upper = _u(t)
            if t_upper in {"EQUIPO_GNC", "TUBO_GNC"}:
                t_upper = "TUBO_GNC"
            if t_upper in {"RUEDA_DE_AUXILIO", "RUEDA_AUXILIO", "RUEDA_AUX"}:
                t_upper = "RUEDA_AUXILIO"
            attrs["tipo"] = t_upper
        else:
            attrs["tipo"] = "OTRA"
            
        o = attrs.get("origen")
        if isinstance(o, str):
            attrs["origen"] = _u(o)
            
        if attrs.get("public_id") is None:
            attrs["public_id"] = ""
            
        return attrs


class PolizaDocumentoSerializer(serializers.ModelSerializer):
    tipo = serializers.CharField(max_length=50, required=False, allow_blank=True)
    
    class Meta:
        model = PolizaDocumento
        fields = "__all__"
        
    def validate(self, attrs):
        instance = getattr(self, "instance", None)
        def _u(x: str) -> str:
            return (x or "").strip().upper().replace(" ", "_")
            
        t_in = attrs.get("tipo", getattr(instance, "tipo", None))
        if isinstance(t_in, str) and t_in:
            t_in = _u(t_in)
        else:
            t_in = "OTRO"
            
        lado_extra = None
        for base in ("CEDULA_VERDE", "CEDULA_AZUL"):
            if isinstance(t_in, str) and t_in.startswith(base + "_"):
                suf = t_in[len(base) + 1 :]
                if suf in {"FRENTE", "DORSO"}:
                    lado_extra = suf
                    t_in = base
                    break
                    
        if instance is None and not t_in:
            raise serializers.ValidationError({"tipo": "Este campo es requerido."})
            
        attrs["tipo"] = t_in
        lado_in = attrs.get("lado", getattr(instance, "lado", ""))
        lado = _u(lado_in) if isinstance(lado_in, str) else ""
        synonyms = {
            "FRONTAL": "FRENTE", "DELANTERA": "FRENTE", "DELANTERO": "FRENTE", 
            "ANVERSO": "FRENTE", "REVERSO": "DORSO", "TRASERA": "DORSO", 
            "TRASERO": "DORSO", "ATRAS": "DORSO", "DORSAL": "DORSO"
        }
        if lado in synonyms:
            lado = synonyms[lado]
            
        es_cedula = t_in in {"CEDULA_VERDE", "CEDULA_AZUL"}
        if lado_extra:
            lado = lado_extra
            
        if es_cedula:
            if lado and lado not in {"FRENTE", "DORSO"}:
                raise serializers.ValidationError({"lado": "Use 'FRENTE' o 'DORSO'."})
            attrs["lado"] = lado or ""
        else:
            attrs["lado"] = ""
            
        if attrs.get("public_id") is None:
            attrs["public_id"] = ""
        if attrs.get("nombre") is None:
            attrs["nombre"] = attrs["tipo"]  
        if attrs.get("mime") is None:
            attrs["mime"] = ""
            
        return attrs


class CuponRoboSerializer(serializers.ModelSerializer):
    poliza_numero = serializers.CharField(source="poliza.numero_poliza", read_only=True)
    poliza_patente = serializers.CharField(source="poliza.patente", read_only=True)
    poliza_modelo = serializers.CharField(source="poliza.modelo", read_only=True)
    poliza_compania = serializers.SerializerMethodField(read_only=True)
    asegurado_nombre = serializers.SerializerMethodField()
    asegurado_telefono = serializers.SerializerMethodField()
    asegurado_telefono_e164 = serializers.SerializerMethodField()
    poliza_oficina_nombre = serializers.CharField(source="poliza.oficina.nombre", read_only=True)

    class Meta:
        model = CuponRobo
        fields = "__all__"

    def get_poliza_compania(self, obj):
        pol = getattr(obj, "poliza", None)
        if pol:
            return _get_compania_nombre_robusto(pol)
        return ""

    def _get_cliente(self, obj):
        poliza = getattr(obj, "poliza", None)
        return getattr(poliza, "cliente", None) if poliza else None

    def get_asegurado_nombre(self, obj):
        cliente = self._get_cliente(obj)
        if not cliente:
            return ""
        apellido = getattr(cliente, "apellido", "") or ""
        nombre = getattr(cliente, "nombre", "") or ""
        if apellido and nombre:
            return f"{apellido}, {nombre}"
        return apellido or nombre or ""

    def get_asegurado_telefono(self, obj):
        cliente = self._get_cliente(obj)
        return _get_cliente_telefono_robusto(cliente)

    def get_asegurado_telefono_e164(self, obj):
        cliente = self._get_cliente(obj)
        if not cliente:
            return ""
        try:
            fn = getattr(cliente, "telefono_e164", None)
            if callable(fn):
                return fn()
        except Exception:
            pass
        raw = _get_cliente_telefono_robusto(cliente)
        return _telefono_to_e164_ar(raw)


class PolizaListSerializer(serializers.ModelSerializer):
    cliente = ClienteBasicSerializer(read_only=True)
    compania_nombre = serializers.SerializerMethodField(read_only=True)
    oficina_nombre = serializers.CharField(source='oficina.nombre', read_only=True)
    impagas_count = serializers.IntegerField(read_only=True)
    proxima_vencimiento_impaga = serializers.DateField(read_only=True)
    estado_cuotas = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Poliza
        fields = ["id", "numero_poliza", "sin_numero", "compania", "compania_nombre", "cliente", "patente", "marca", "modelo", "oficina", "oficina_nombre", "estado", "fase", "fecha_emision", "fecha_vencimiento", "impagas_count", "proxima_vencimiento_impaga", "estado_cuotas"]

    def get_compania_nombre(self, obj):
        return _get_compania_nombre_robusto(obj)

    def get_estado_cuotas(self, obj):
        impagas = getattr(obj, "impagas_count", 0) or 0
        if impagas <= 0:
            return "al_dia"
        proxima = getattr(obj, "proxima_vencimiento_impaga", None)
        if not proxima:
            return "vencidas"
        hoy = timezone.localdate()
        try:
            diff_days = (hoy - proxima).days
        except Exception:
            return "vencidas"
        if diff_days == 0:
            return "vence_hoy"
        if diff_days > 0:
            if diff_days <= 7:
                return "vencida_7"
            if diff_days <= 30:
                return "vencida_30"
            return "vencidas"
        return "por_vencer" if abs(diff_days) <= 7 else "al_dia"


class PolizaRenovacionListSerializer(serializers.ModelSerializer):
    cliente = serializers.SerializerMethodField(read_only=True)
    cliente_id = serializers.IntegerField(read_only=True)
    compania_nombre = serializers.SerializerMethodField(read_only=True)
    oficina_nombre = serializers.CharField(source='oficina.nombre', read_only=True)
    impagas_count = serializers.SerializerMethodField()
    proxima_vencimiento_impaga = serializers.SerializerMethodField()
    cuotas_total = serializers.SerializerMethodField()
    ultima_cuota_nro = serializers.SerializerMethodField()
    ultima_cuota_vencimiento = serializers.SerializerMethodField()
    vto_referencia = serializers.SerializerMethodField()
    necesita_renovar = serializers.SerializerMethodField()
    necesita_refacturar = serializers.SerializerMethodField()
    dias_para_vencer_poliza = serializers.SerializerMethodField()

    class Meta:
        model = Poliza
        fields = ["id", "numero_poliza", "sin_numero", "compania", "compania_nombre", "oficina", "oficina_nombre", "cliente", "cliente_id", "patente", "marca", "modelo", "estado", "fase", "fecha_emision", "primer_pago", "fecha_vencimiento", "cantidad_cuotas", "precio_cuota", "impagas_count", "proxima_vencimiento_impaga", "cuotas_total", "ultima_cuota_nro", "ultima_cuota_vencimiento", "vto_referencia", "dias_para_vencer_poliza", "necesita_renovar", "necesita_refacturar",
                  # 🚀 Estados de bandeja de renovaciones
                  "es_renovacion", "poliza_origen",
                  "renovacion_verificada", "renovacion_verificada_en",
                  "renovacion_descartada", "renovacion_descartada_motivo",
                  "renovacion_descartada_detalle", "renovacion_descartada_en"]

    def get_cliente(self, obj):
        c = getattr(obj, "cliente", None)
        if not c:
            return None
        return {"id": getattr(c, "id", None), "apellido": getattr(c, "apellido", "") or "", "nombre": getattr(c, "nombre", "") or "", "dni": getattr(c, "dni", "") or getattr(c, "documento", "") or ""}

    def get_compania_nombre(self, obj):
        return _get_compania_nombre_robusto(obj)

    def get_impagas_count(self, obj):
        return int(_safe_annot(obj, "impagas_count", 0) or 0)

    def get_proxima_vencimiento_impaga(self, obj):
        return _safe_annot(obj, "proxima_vencimiento_impaga", None)

    def get_cuotas_total(self, obj):
        return int(_safe_annot(obj, "cuotas_total", 0) or 0)

    def get_ultima_cuota_nro(self, obj):
        v = _safe_annot(obj, "ultima_cuota_nro", None)
        return int(v) if v is not None else None

    def get_ultima_cuota_vencimiento(self, obj):
        return _safe_annot(obj, "ultima_cuota_vencimiento", None)

    def get_vto_referencia(self, obj):
        v = _safe_annot(obj, "vto_referencia", None)
        if v is not None:
            return v
        return _safe_annot(obj, "ultima_cuota_vencimiento", None) or getattr(obj, "fecha_vencimiento", None)

    def get_necesita_renovar(self, obj):
        return bool(_safe_annot(obj, "necesita_renovar", False))

    def get_necesita_refacturar(self, obj):
        return bool(_safe_annot(obj, "necesita_refacturar", False))

    def get_dias_para_vencer_poliza(self, obj):
        v = _safe_annot(obj, "dias_para_vencer_poliza", None)
        if v is None:
            return None
        try:
            return int(v)
        except Exception:
            return None


class PolizaVencimientoListSerializer(serializers.ModelSerializer):
    cliente = serializers.SerializerMethodField(read_only=True)
    cliente_id = serializers.IntegerField(read_only=True)
    compania_nombre = serializers.SerializerMethodField(read_only=True)
    cliente_telefono = serializers.SerializerMethodField(read_only=True)
    oficina_nombre = serializers.CharField(source='oficina.nombre', read_only=True)
    vto_referencia = serializers.SerializerMethodField()
    dias_para_vencer = serializers.SerializerMethodField()

    class Meta:
        model = Poliza
        fields = ["id", "numero_poliza", "sin_numero", "compania", "compania_nombre", "oficina", "oficina_nombre", "cliente", "cliente_id", "cliente_telefono", "patente", "marca", "modelo", "estado", "fase", "fecha_emision", "primer_pago", "fecha_vencimiento", "cantidad_cuotas", "precio_cuota", "vto_referencia", "dias_para_vencer"]

    def get_cliente(self, obj):
        c = getattr(obj, "cliente", None)
        if not c:
            return None
        tel = _get_cliente_telefono_robusto(c)
        return {"id": getattr(c, "id", None), "apellido": getattr(c, "apellido", "") or "", "nombre": getattr(c, "nombre", "") or "", "dni": getattr(c, "dni", "") or getattr(c, "dni_cuit_cuil", "") or getattr(c, "documento", "") or "", "telefono": tel or ""}

    def get_cliente_telefono(self, obj):
        c = getattr(obj, "cliente", None)
        return _get_cliente_telefono_robusto(c)

    def get_compania_nombre(self, obj):
        return _get_compania_nombre_robusto(obj)

    def get_vto_referencia(self, obj):
        v = _safe_annot(obj, "vto_referencia", None)
        if v is not None:
            return v
        return _safe_annot(obj, "ultima_cuota_vencimiento", None) or getattr(obj, "fecha_vencimiento", None)

    def get_dias_para_vencer(self, obj):
        vto = self.get_vto_referencia(obj)
        if not vto:
            return None
        hoy = timezone.localdate()
        try:
            vto_date = vto.date() if hasattr(vto, "date") else vto
            return int((vto_date - hoy).days)
        except Exception:
            return None


class PolizaSerializer(serializers.ModelSerializer):
    cliente = ClienteBasicSerializer(read_only=True)
    cliente_id = serializers.PrimaryKeyRelatedField(source="cliente", queryset=Cliente.objects.all(), write_only=True)
    oficina_nombre = serializers.CharField(source='oficina.nombre', read_only=True)
    cuotas = serializers.SerializerMethodField(read_only=True)
    pagos = PagoSerializer(many=True, read_only=True)
    fotos_vehiculo = FotoVehiculoSerializer(many=True, read_only=True)
    documentos = PolizaDocumentoSerializer(many=True, read_only=True)
    cupones_robo = CuponRoboSerializer(many=True, read_only=True)
    compania_nombre = serializers.SerializerMethodField(read_only=True)
    cobertura_nombre = serializers.SerializerMethodField(read_only=True)
    mora_dias = serializers.SerializerMethodField(read_only=True)
    estado_financiero = serializers.SerializerMethodField(read_only=True)
    estado_pagos = serializers.SerializerMethodField(read_only=True)
    dias_desde_vencimiento = serializers.SerializerMethodField(read_only=True)
    es_preliminar = serializers.SerializerMethodField(read_only=True)
    es_definitiva = serializers.SerializerMethodField(read_only=True)
    tiene_numero = serializers.SerializerMethodField(read_only=True)

    # ── Estado de baja activa ─────────────────────────────────────────────────
    # Devuelve el estado de BajaPoliza si existe, o None.
    # El front lo usa en el modal de pago para mostrar la advertencia.
    baja_estado = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Poliza
        fields = "__all__"
        extra_kwargs = {
            "cantidad_cuotas": {"read_only": True},
            "fecha_vencimiento": {"required": False},
            "precio_cuota": {"required": False, "allow_null": True},
        }

    def _resolve_cuotas_queryset(self, obj):
        try:
            rel = getattr(obj, "cuotas", None)
            if rel is not None and hasattr(rel, "all"):
                return rel.all()
        except Exception:
            pass
        try:
            rel = getattr(obj, "cuota_set", None)
            if rel is not None and hasattr(rel, "all"):
                return rel.all()
        except Exception:
            pass
        return Cuota.objects.filter(poliza=obj)

    def get_cuotas(self, obj):
        req = self.context.get("request")
        if req:
            if "include_cuotas" in req.query_params:
                include = _to_bool(req.query_params.get("include_cuotas"))
            else:
                include = True
        else:
            include = True
        if not include:
            return []
        qs = self._resolve_cuotas_queryset(obj).order_by("cuota_nro", "fecha_vencimiento", "id")
        return CuotaMiniSerializer(qs, many=True, context=self.context).data

    def get_compania_nombre(self, obj):
        return _get_compania_nombre_robusto(obj)

    def get_cobertura_nombre(self, obj):
        return _get_cobertura_nombre_robusto(obj)

    def validate(self, attrs):
        instance = getattr(self, "instance", None)
        if "numero_poliza" in attrs:
            num = attrs.get("numero_poliza")
            if num is None or (isinstance(num, str) and num.strip() == ""):
                attrs["numero_poliza"] = None
        final_num = attrs.get("numero_poliza", None if instance is None else getattr(instance, "numero_poliza", None))
        if final_num:
            attrs["sin_numero"] = False
        return attrs

    def create(self, validated_data):
        validated_data.pop("cantidad_cuotas", None)
        if not validated_data.get("fecha_emision"):
            validated_data["fecha_emision"] = timezone.localdate()
        if not validated_data.get("fecha_vencimiento"):
            fv = validated_data.get("primer_vencimiento")
            if not fv:
                fv = validated_data["fecha_emision"] + timedelta(days=30)
            validated_data["fecha_vencimiento"] = fv
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("cantidad_cuotas", None)
        if "fecha_emision" in validated_data and not validated_data.get("fecha_emision"):
            validated_data["fecha_emision"] = timezone.localdate()
        if "fecha_vencimiento" not in validated_data and not instance.fecha_vencimiento:
            base = (validated_data.get("primer_vencimiento") or validated_data.get("fecha_emision") or timezone.localdate())
            validated_data["fecha_vencimiento"] = base + timedelta(days=30)
        return super().update(instance, validated_data)

    def get_mora_dias(self, obj):
        try:
            return obj.calcular_mora_dias()
        except Exception:
            return 0

    def get_estado_financiero(self, obj):
        try:
            return obj.obtener_estado_financiero()
        except Exception:
            return "al_dia"

    def get_dias_desde_vencimiento(self, obj):
        try:
            hoy = timezone.localdate()
            if getattr(obj, "fecha_vencimiento", None) and obj.fecha_vencimiento < hoy:
                return (hoy - obj.fecha_vencimiento).days
            return 0
        except Exception:
            return 0

    def get_estado_pagos(self, obj):
        hoy = timezone.localdate()
        if not getattr(obj, "fecha_vencimiento", None) or not getattr(obj, "primer_pago", None):
            return "Inactivo"
        vto = obj.fecha_vencimiento
        dias_para_vencer = (vto - hoy).days
        dias_desde_vto = (hoy - vto).days
        if dias_para_vencer > 3:
            return "Al día"
        elif 0 <= dias_para_vencer <= 3:
            return "Por vencer"
        elif 0 < dias_desde_vto <= 60:
            return "Vencido"
        else:
            return "Inactivo"

    def get_es_preliminar(self, obj):
        try:
            return bool(obj.es_preliminar)
        except Exception:
            return getattr(obj, "fase", "") == "PRELIMINAR"

    def get_es_definitiva(self, obj):
        try:
            return bool(obj.es_definitiva)
        except Exception:
            return getattr(obj, "fase", "") == "DEFINITIVA"

    def get_tiene_numero(self, obj):
        try:
            return bool(obj.numero_poliza)
        except Exception:
            return False

    def get_baja_estado(self, obj):
        """
        Devuelve el estado de la BajaPoliza activa si existe.
        Usado en el front para mostrar la advertencia en el modal de pago.
        Retorna: "PENDIENTE_ENVIO" | "ENVIADA" | "REALIZADA" | None
        """
        try:
            baja = getattr(obj, "baja_operativa", None)
            if baja is None:
                # Evitar query si ya fue prefetched
                return None
            return baja.estado
        except Exception:
            return None