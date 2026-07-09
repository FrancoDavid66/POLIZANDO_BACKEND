# pagos/serializers .py
from decimal import Decimal, InvalidOperation
import re

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework import serializers

from .models import Pago, Cuota, MedioCobro
from polizas.models import Poliza
from clientes.models import Cliente
from polizas.precios_nre import es_nre, precio_vigente

# ------------------ Helpers oficina ------------------

OFICINAS_MAP = {
    "1": "5 esquinas (1)",
    "2": "axion (2)",
    "3": "kilometro 39 (3)",
}


def _normalize_oficina_bucket(raw):
    s0 = str(raw or "").strip()
    if not s0:
        return ""
    up = s0.upper()
    if s0 in ("1", "2", "3"):
        return s0
    if re.search(r"\bOFI\s*[-_]*\s*1\b", up) or re.search(r"\bOFI1\b", up):
        return "1"
    if re.search(r"\bOFI\s*[-_]*\s*2\b", up) or re.search(r"\bOFI2\b", up):
        return "2"
    if re.search(r"\bOFI\s*[-_]*\s*3\b", up) or re.search(r"\bOFI3\b", up):
        return "3"
    if "(1)" in up: return "1"
    if "(2)" in up: return "2"
    if "(3)" in up: return "3"
    if "5 ESQUINAS" in up: return "1"
    if "AXION" in up: return "2"
    if "KILOMETRO 39" in up or re.search(r"\bKM\s*39\b", up) or "KM39" in up: return "3"
    return ""


def _oficina_nombre(raw):
    b = _normalize_oficina_bucket(raw)
    if b in OFICINAS_MAP:
        return OFICINAS_MAP[b]
    return str(raw).strip() if raw not in (None, "") else ""


def _compania_nombre_robusto(poliza):
    try:
        if not poliza:
            return ""
        comp = getattr(poliza, "compania", None)
        if comp is None:
            cn = getattr(poliza, "compania_nombre", None)
            return str(cn or "").strip()
        if hasattr(comp, "nombre"):
            return str(getattr(comp, "nombre", "") or "").strip()
        return str(comp).strip()
    except Exception:
        return ""


# ------------------ Helpers fecha/hora ------------------

def _safe_localtime(dt):
    if not dt:
        return None
    try:
        return timezone.localtime(dt)
    except Exception:
        return dt


def _fmt_hm(dt) -> str:
    dtx = _safe_localtime(dt)
    if not dtx:
        return ""
    try:
        return dtx.strftime("%H:%M")
    except Exception:
        return ""


def _fmt_full(dt) -> str:
    dtx = _safe_localtime(dt)
    if not dtx:
        return ""
    try:
        return dtx.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return ""


# ------------------ Mini serializadores ------------------

class ClienteMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cliente
        fields = ["nombre", "apellido", "telefono", "dni_cuit_cuil"]


class PolizaMiniSerializer(serializers.ModelSerializer):
    cliente = serializers.SerializerMethodField()
    oficina = serializers.CharField(read_only=True)
    oficina_nombre = serializers.SerializerMethodField(read_only=True)
    oficina_bucket = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Poliza
        fields = [
            "id", "numero_poliza", "marca", "modelo", "patente", "cobertura",
            "oficina", "oficina_nombre", "oficina_bucket", "cliente",
            "fecha_emision", "fecha_vencimiento",
        ]

    def get_oficina_nombre(self, obj):
        return _oficina_nombre(getattr(obj, "oficina", None))

    def get_oficina_bucket(self, obj):
        return _normalize_oficina_bucket(getattr(obj, "oficina", None))

    def get_cliente(self, obj):
        c = getattr(obj, "cliente", None)
        if not c:
            return None
        return {
            "id": c.id,
            "nombre": c.nombre,
            "apellido": c.apellido,
            "telefono": c.telefono,
            "dni_cuit_cuil": c.dni_cuit_cuil,
        }


# ================== CuotaFlatSerializer ==================

class CuotaFlatSerializer(serializers.ModelSerializer):
    monto = serializers.SerializerMethodField(read_only=True)
    observaciones = serializers.SerializerMethodField(read_only=True)
    poliza = serializers.SerializerMethodField(read_only=True)
    cliente = serializers.SerializerMethodField(read_only=True)
    total_cuotas = serializers.SerializerMethodField(read_only=True)
    cuota_label = serializers.SerializerMethodField(read_only=True)
    pago_registrado_en = serializers.SerializerMethodField(read_only=True)
    pago_hm = serializers.SerializerMethodField(read_only=True)
    pago_hm_full = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Cuota
        fields = [
            "id", "cuota_nro", "monto", "pagado", "fecha_vencimiento",
            "fecha_pago", "forma_pago", "observaciones", "ultima_observacion_pago",
            "poliza", "cliente", "total_cuotas", "cuota_label",
            "pago_registrado_en", "pago_hm", "pago_hm_full",
        ]

    def _pol(self, obj):
        return getattr(obj, "poliza", None)

    def _cli(self, obj):
        pol = self._pol(obj)
        return getattr(pol, "cliente", None) if pol else None

    def get_monto(self, obj):
        """Monto a cobrar de la cuota.
        Si la cuota está IMPAGA y en $0 (o sin monto), buscamos una SUGERENCIA
        (el operador siempre la puede editar en el modal de cobro, no hay
        candado en ningún caso):
          1) precio_cuota de la póliza (lo que se cargó a mano al crear/renovar),
             cualquier compañía;
          2) si sigue en 0 y es NRE → precio de lista vigente según el `tipo`
             (Auto/Camioneta/etc.). Esto es seguro porque el tipo ahora se
             elige a mano y de forma obligatoria al cargar/renovar la póliza.
        Si nada de esto da un número, se muestra $0 y el operador lo carga a
        mano. Las cuotas ya pagadas se muestran tal cual se cobraron.
        """
        raw = obj.monto
        try:
            val = Decimal(str(raw)) if raw is not None else Decimal("0")
        except (InvalidOperation, TypeError, ValueError):
            val = Decimal("0")

        if not getattr(obj, "pagado", False) and val <= 0:
            pol = self._pol(obj)
            if pol is not None:
                # 1) precio_cuota de la póliza (cargado a mano).
                try:
                    pc = getattr(pol, "precio_cuota", None)
                    if pc is not None and Decimal(str(pc)) > 0:
                        val = Decimal(str(pc))
                except (InvalidOperation, TypeError, ValueError):
                    pass
                # 2) Si sigue en 0 y es NRE → sugerencia de precio de lista.
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

    def get_observaciones(self, obj):
        v = getattr(obj, "observaciones_pago", None)
        if v not in (None, ""):
            return str(v)
        v2 = getattr(obj, "ultima_observacion_pago", None)
        if v2 not in (None, ""):
            return str(v2)
        return ""

    def _get_pago_registrado_en_dt(self, obj):
        ann = getattr(obj, "pago_ts", None)
        if ann:
            return ann
        dt = getattr(obj, "pago_registrado_en", None)
        if dt:
            return dt
        pol = self._pol(obj)
        if not pol:
            return None
        pago = (
            Pago.objects.filter(poliza=pol, cuota_nro=obj.cuota_nro)
            .order_by("-registrado_en", "-id")
            .only("registrado_en")
            .first()
        )
        return getattr(pago, "registrado_en", None) if pago else None

    def get_pago_registrado_en(self, obj):
        dt = self._get_pago_registrado_en_dt(obj)
        if not dt:
            return None
        dtx = _safe_localtime(dt)
        try:
            return dtx.isoformat()
        except Exception:
            return dt.isoformat() if hasattr(dt, "isoformat") else dt

    def get_pago_hm(self, obj):
        return _fmt_hm(self._get_pago_registrado_en_dt(obj))

    def get_pago_hm_full(self, obj):
        return _fmt_full(self._get_pago_registrado_en_dt(obj))

    def _get_total_cuotas_poliza(self, pol, obj=None):
        if obj is not None:
            ann = getattr(obj, "total_cuotas", None)
            if ann not in (None, ""):
                try:
                    return int(ann)
                except Exception:
                    pass
        if not pol:
            return None
        total = getattr(pol, "cantidad_cuotas", None)
        if total:
            return total
        try:
            return pol.cuotas.aggregate(mx=Max("cuota_nro"))["mx"]
        except Exception:
            return None

    def get_total_cuotas(self, obj):
        pol = self._pol(obj)
        return self._get_total_cuotas_poliza(pol, obj=obj)

    def get_cuota_label(self, obj):
        pol = self._pol(obj)
        nro = getattr(obj, "cuota_nro", None)
        if not nro:
            return ""
        total = self._get_total_cuotas_poliza(pol, obj=obj)
        if not total:
            return str(nro)
        return f"{nro}/{total}"

    def get_poliza(self, obj):
        pol = self._pol(obj)
        if not pol:
            return {"poliza_id": None, "numero_poliza": "", "patente": "",
                    "marca": "", "modelo": "", "cobertura": "", "compania_nombre": "",
                    "oficina": "", "oficina_bucket": "", "oficina_nombre": "",
                    "estado": "", "fecha_baja": None}
        ofi_raw = getattr(pol, "oficina", None)
        # 🚨 Para alertas: incluimos estado y fecha_baja de la póliza
        fecha_baja = getattr(pol, "fecha_baja", None)
        return {
            "poliza_id": getattr(pol, "id", None),
            "numero_poliza": str(getattr(pol, "numero_poliza", "") or "").strip(),
            "patente": str(getattr(pol, "patente", "") or "").strip(),
            "marca": str(getattr(pol, "marca", "") or "").strip(),
            "modelo": str(getattr(pol, "modelo", "") or "").strip(),
            "cobertura": str(getattr(pol, "cobertura", "") or "").strip(),
            "compania_nombre": _compania_nombre_robusto(pol),
            "oficina": str(ofi_raw or "").strip(),
            "oficina_bucket": _normalize_oficina_bucket(ofi_raw),
            "oficina_nombre": _oficina_nombre(ofi_raw),
            "estado": str(getattr(pol, "estado", "") or "").strip().upper(),
            "fecha_baja": fecha_baja.isoformat() if fecha_baja else None,
        }

    def get_cliente(self, obj):
        cli = self._cli(obj)
        if not cli:
            return {"cliente_id": None, "apellido": "", "nombre": "", "dni_cuit_cuil": "", "telefono": ""}
        return {
            "cliente_id": getattr(cli, "id", None),
            "apellido": str(getattr(cli, "apellido", "") or "").strip(),
            "nombre": str(getattr(cli, "nombre", "") or "").strip(),
            "dni_cuit_cuil": str(getattr(cli, "dni_cuit_cuil", "") or "").strip(),
            "telefono": str(getattr(cli, "telefono", "") or "").strip(),
        }

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if self.context.get("only_cuotas"):
            return {
                "id": data.get("id"),
                "cuota_nro": data.get("cuota_nro"),
                "cuota_label": data.get("cuota_label"),
                "monto": data.get("monto"),
                "pagado": data.get("pagado"),
                "fecha_vencimiento": data.get("fecha_vencimiento"),
                "fecha_pago": data.get("fecha_pago"),
                "forma_pago": data.get("forma_pago"),
                "observaciones": data.get("observaciones"),
                "ultima_observacion_pago": data.get("ultima_observacion_pago"),
                "total_cuotas": data.get("total_cuotas"),
                "pago_registrado_en": data.get("pago_registrado_en"),
                "pago_hm": data.get("pago_hm"),
                "pago_hm_full": data.get("pago_hm_full"),
                # 🚀 FIX recibo vacío: conservamos póliza y cliente aunque sea modo "only_cuotas".
                # El front (recibo/ticket/WhatsApp) los necesita para mostrar nombre, DNI,
                # marca, modelo y patente. Ya están calculados arriba, no cuesta nada incluirlos.
                "poliza": data.get("poliza"),
                "cliente": data.get("cliente"),
            }
        return data


# ------------------ MedioCobroSerializer ------------------

class MedioCobroSerializer(serializers.ModelSerializer):
    proveedor_display = serializers.CharField(source="get_proveedor_display", read_only=True)
    tipo_display = serializers.CharField(source="get_tipo_display", read_only=True)
    display = serializers.SerializerMethodField()

    class Meta:
        model = MedioCobro
        fields = [
            "id", "proveedor", "proveedor_display", "tipo", "tipo_display",
            "valor", "titular_nombre", "etiqueta", "qr_url", "notas",
            "activo", "ultimo_uso", "usos_totales", "creado", "actualizado",
            "display", "oficina",
        ]
        read_only_fields = ["ultimo_uso", "usos_totales", "creado", "actualizado"]
        extra_kwargs = {
            "titular_nombre": {"required": False, "allow_blank": True},
            "tipo": {"required": False},
            "proveedor": {"required": False},
            "oficina": {"required": False, "allow_null": True, "allow_blank": True},
        }

    def get_display(self, obj):
        base = obj.etiqueta or obj.valor
        try:
            prov = obj.get_proveedor_display()
        except Exception:
            prov = str(getattr(obj, "proveedor", "") or "")
        try:
            tipo = obj.get_tipo_display()
        except Exception:
            tipo = str(getattr(obj, "tipo", "") or "")
        ofi_tag = f"[Ofi {obj.oficina}]" if obj.oficina else "[Global]"
        return " · ".join([v for v in [ofi_tag, prov, tipo, base] if v])


# ------------------ PagoSerializer ------------------

def _normalizar_metodo(value):
    if value in (None, ""):
        return value
    v = str(value).lower().strip()
    if v in ("mercado_pago", "tarjeta"):
        return "transferencia"
    if v in ("efectivo", "transferencia"):
        return v
    raise serializers.ValidationError({"metodo": 'Método inválido. Use "efectivo" o "transferencia".'})


class PagoSerializer(serializers.ModelSerializer):
    registrado_hm = serializers.SerializerMethodField(read_only=True)
    registrado_hm_full = serializers.SerializerMethodField(read_only=True)

    # 🚀 Campos extra para Micaela (verificación)
    patente = serializers.SerializerMethodField(read_only=True)
    cliente_nombre = serializers.SerializerMethodField(read_only=True)
    compania = serializers.SerializerMethodField(read_only=True)
    oficina = serializers.SerializerMethodField(read_only=True)
    verificado_por_username = serializers.SerializerMethodField(read_only=True)
    requiere_atencion = serializers.BooleanField(read_only=True)

    class Meta:
        model = Pago
        fields = "__all__"
        extra_kwargs = {"fecha": {"required": False}}

    def get_registrado_hm(self, obj):
        return _fmt_hm(getattr(obj, "registrado_en", None))

    def get_registrado_hm_full(self, obj):
        return _fmt_full(getattr(obj, "registrado_en", None))

    # 🚀 Getters para Micaela
    def get_patente(self, obj):
        return getattr(obj.poliza, "patente", "") if obj.poliza_id else ""

    def get_cliente_nombre(self, obj):
        if not obj.poliza_id:
            return ""
        cli = getattr(obj.poliza, "cliente", None)
        if not cli:
            return ""
        return f"{getattr(cli, 'apellido', '')} {getattr(cli, 'nombre', '')}".strip()

    def get_compania(self, obj):
        return getattr(obj.poliza, "compania", "") if obj.poliza_id else ""

    def get_oficina(self, obj):
        if not obj.poliza_id:
            return ""
        ofi = getattr(obj.poliza, "oficina", None)
        return str(ofi) if ofi else ""

    def get_verificado_por_username(self, obj):
        return getattr(obj.verificado_por, "username", None) if obj.verificado_por_id else None

    def validate(self, attrs):
        poliza = attrs.get("poliza")
        cuota = attrs.get("cuota")
        cuota_nro = attrs.get("cuota_nro")
        metodo_raw = attrs.get("metodo", None)
        monto = attrs.get("monto", None)

        metodo = _normalizar_metodo(metodo_raw)
        if metodo is not None:
            attrs["metodo"] = metodo

        if not cuota and poliza and cuota_nro is not None:
            try:
                cuota = Cuota.objects.get(poliza=poliza, cuota_nro=cuota_nro)
                attrs["cuota"] = cuota
            except Cuota.DoesNotExist:
                raise serializers.ValidationError({"cuota_nro": "No existe la cuota indicada para esta póliza."})

        if cuota and poliza and cuota.poliza_id != poliza.id:
            raise serializers.ValidationError({"cuota": "La cuota no pertenece a la póliza indicada."})

        if cuota:
            if getattr(cuota, "pagado", False):
                raise serializers.ValidationError({"cuota": "Esta cuota ya figura como pagada."})
            attrs.setdefault("cuota_nro", cuota.cuota_nro)
            attrs.setdefault("poliza", cuota.poliza)
            if monto is None:
                attrs["monto"] = cuota.monto
        else:
            if not (poliza and cuota_nro is not None):
                raise serializers.ValidationError("Debes indicar `cuota` o bien `poliza` + `cuota_nro`.")

        if monto not in (None, ""):
            try:
                monto_dec = Decimal(str(monto))
                if monto_dec < 0:
                    raise serializers.ValidationError({"monto": "Debe ser un número positivo."})
            except (InvalidOperation, TypeError, ValueError):
                raise serializers.ValidationError({"monto": "Monto inválido."})

        return attrs

    def create(self, validated_data):
        cuota = validated_data.get("cuota")
        poliza = validated_data.get("poliza") or (cuota.poliza if cuota else None)
        cuota_nro = validated_data.get("cuota_nro") or (cuota.cuota_nro if cuota else None)
        metodo = validated_data.get("metodo")
        fecha_pago = validated_data.get("fecha")
        monto = validated_data.get("monto")
        observaciones = (validated_data.get("observaciones", "") or "").strip()
        forma_pago_cuota = metodo if metodo in ("efectivo", "transferencia") else "transferencia"

        with transaction.atomic():
            pago_defaults = {
                "fecha": fecha_pago, "monto": monto,
                "metodo": forma_pago_cuota, "observaciones": observaciones,
            }
            pago, creado = Pago.objects.get_or_create(
                poliza=poliza, cuota=cuota, cuota_nro=cuota_nro,
                defaults=pago_defaults,
            )
            if not creado:
                for k, v in pago_defaults.items():
                    setattr(pago, k, v)
                pago.save()

            if cuota:
                cuota.marcar_pagada(
                    fecha=fecha_pago, forma=forma_pago_cuota,
                    monto=monto, observaciones=observaciones, commit=True
                )
        return pago


# ------------------ CuotaSerializer ------------------

class CuotaSerializer(serializers.ModelSerializer):
    poliza = PolizaMiniSerializer(read_only=True)
    poliza_id = serializers.PrimaryKeyRelatedField(
        queryset=Poliza.objects.all(), source="poliza", write_only=True, required=False,
    )
    oficina = serializers.SerializerMethodField(read_only=True)
    oficina_nombre = serializers.SerializerMethodField(read_only=True)
    oficina_bucket = serializers.SerializerMethodField(read_only=True)
    cliente_nombre = serializers.SerializerMethodField(read_only=True)
    cliente_dni = serializers.SerializerMethodField(read_only=True)
    patente = serializers.SerializerMethodField(read_only=True)
    numero_poliza = serializers.SerializerMethodField(read_only=True)
    compania = serializers.SerializerMethodField(read_only=True)
    medio = serializers.SerializerMethodField(read_only=True)
    ultima_observacion_pago = serializers.SerializerMethodField(read_only=True)
    pago_registrado_en = serializers.SerializerMethodField(read_only=True)
    pago_hm = serializers.SerializerMethodField(read_only=True)
    pago_hm_full = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Cuota
        fields = [
            "id", "poliza", "poliza_id", "cuota_nro", "fecha_vencimiento",
            "monto", "pagado", "forma_pago", "fecha_pago",
            "pago_registrado_en", "pago_hm", "pago_hm_full",
            "oficina", "oficina_nombre", "oficina_bucket",
            "cliente_nombre", "cliente_dni", "patente", "numero_poliza",
            "compania", "medio", "ultima_observacion_pago",
        ]
        read_only_fields = [
            "poliza", "cuota_nro", "monto", "fecha_vencimiento",
            "oficina", "oficina_nombre", "oficina_bucket",
            "cliente_nombre", "cliente_dni", "patente", "numero_poliza",
            "compania", "medio", "ultima_observacion_pago",
            "pago_registrado_en", "pago_hm", "pago_hm_full",
        ]

    def _pol(self, obj):
        return getattr(obj, "poliza", None)

    def _get_pago_registrado_en_dt(self, obj):
        ann = getattr(obj, "pago_ts", None)
        if ann:
            return ann
        dt = getattr(obj, "pago_registrado_en", None)
        if dt:
            return dt
        pol = self._pol(obj)
        if not pol:
            return None
        pago = (
            Pago.objects.filter(poliza=pol, cuota_nro=obj.cuota_nro)
            .order_by("-registrado_en", "-id")
            .only("registrado_en")
            .first()
        )
        return getattr(pago, "registrado_en", None) if pago else None

    def get_pago_registrado_en(self, obj):
        dt = self._get_pago_registrado_en_dt(obj)
        if not dt:
            return None
        dtx = _safe_localtime(dt)
        try:
            return dtx.isoformat()
        except Exception:
            return dt.isoformat() if hasattr(dt, "isoformat") else dt

    def get_pago_hm(self, obj):
        return _fmt_hm(self._get_pago_registrado_en_dt(obj))

    def get_pago_hm_full(self, obj):
        return _fmt_full(self._get_pago_registrado_en_dt(obj))

    def get_oficina(self, obj):
        pol = self._pol(obj)
        return str(getattr(pol, "oficina", "") or "").strip() if pol else ""

    def get_oficina_nombre(self, obj):
        pol = self._pol(obj)
        return _oficina_nombre(getattr(pol, "oficina", None)) if pol else ""

    def get_oficina_bucket(self, obj):
        pol = self._pol(obj)
        return _normalize_oficina_bucket(getattr(pol, "oficina", None)) if pol else ""

    def get_cliente_nombre(self, obj):
        pol = self._pol(obj)
        c = getattr(pol, "cliente", None) if pol else None
        if not c:
            return ""
        ape = (getattr(c, "apellido", "") or "").strip()
        nom = (getattr(c, "nombre", "") or "").strip()
        return f"{ape}, {nom}".strip(", ").strip() if (ape or nom) else ""

    def get_cliente_dni(self, obj):
        pol = self._pol(obj)
        c = getattr(pol, "cliente", None) if pol else None
        return str(getattr(c, "dni_cuit_cuil", "") or "").strip() if c else ""

    def get_patente(self, obj):
        pol = self._pol(obj)
        return str(getattr(pol, "patente", "") or "").strip() if pol else ""

    def get_numero_poliza(self, obj):
        pol = self._pol(obj)
        return str(getattr(pol, "numero_poliza", "") or "").strip() if pol else ""

    def get_compania(self, obj):
        pol = self._pol(obj)
        return _compania_nombre_robusto(pol)

    def get_medio(self, obj):
        return str(getattr(obj, "forma_pago", "") or "").strip()

    def get_ultima_observacion_pago(self, obj):
        v = getattr(obj, "observaciones_pago", None)
        if v not in (None, ""):
            return str(v)
        v2 = getattr(obj, "ultima_observacion_pago", None)
        if v2 not in (None, ""):
            return str(v2)
        return ""


# ------------------ CuotaPagoHistorialSerializer ------------------

class CuotaPagoHistorialSerializer(serializers.ModelSerializer):
    poliza_id = serializers.IntegerField(read_only=True)

    cliente_nombre = serializers.SerializerMethodField()
    cliente_dni    = serializers.SerializerMethodField()
    patente        = serializers.SerializerMethodField()
    numero_poliza  = serializers.SerializerMethodField()

    compania       = serializers.SerializerMethodField()
    compania_nombre = serializers.SerializerMethodField()

    marca          = serializers.SerializerMethodField()
    modelo         = serializers.SerializerMethodField()

    observaciones  = serializers.SerializerMethodField()

    oficina        = serializers.SerializerMethodField()
    oficina_nombre = serializers.SerializerMethodField()
    oficina_bucket = serializers.SerializerMethodField()

    medio          = serializers.SerializerMethodField()
    cuota_label    = serializers.SerializerMethodField()

    pago_registrado_en = serializers.SerializerMethodField()
    pago_hora      = serializers.SerializerMethodField()
    pago_hm        = serializers.SerializerMethodField()
    pago_hm_full   = serializers.SerializerMethodField()

    cuota_va           = serializers.SerializerMethodField()
    hora_guardado_pago = serializers.SerializerMethodField()
    fecha_guardado_pago = serializers.SerializerMethodField()

    # ✅ NUEVOS: datos de transferencia desde Ingreso relacionado
    destino_cuenta = serializers.SerializerMethodField()
    pagado_por     = serializers.SerializerMethodField()
    cuit_remitente = serializers.SerializerMethodField()
    nro_operacion  = serializers.SerializerMethodField()

    class Meta:
        model = Cuota
        fields = [
            "id",
            "poliza_id",
            "fecha_pago",
            "cuota_nro",
            "monto",
            "forma_pago",
            "cuota_label",
            "pago_registrado_en",
            "pago_hora",
            "pago_hm",
            "pago_hm_full",
            "cuota_va",
            "hora_guardado_pago",
            "fecha_guardado_pago",
            "observaciones",
            "cliente_nombre",
            "cliente_dni",
            "patente",
            "numero_poliza",
            "compania",
            "compania_nombre",
            "marca",
            "modelo",
            "oficina",
            "oficina_nombre",
            "oficina_bucket",
            "medio",
            # ✅ NUEVOS campos de transferencia
            "destino_cuenta",
            "pagado_por",
            "cuit_remitente",
            "nro_operacion",
        ]

    def _pol(self, obj):
        return getattr(obj, "poliza", None)

    def _cli(self, obj):
        pol = self._pol(obj)
        return getattr(pol, "cliente", None) if pol else None

    def _get_ingreso_relacionado(self, obj):
        """Busca el Ingreso en balanzes relacionado para leer billetera/pagado_por."""
        try:
            from django.apps import apps
            try:
                Ingreso = apps.get_model("balances", "Ingreso")
            except LookupError:
                Ingreso = apps.get_model("balanzes", "Ingreso")

            pol = self._pol(obj)
            if not pol:
                return None

            desc_fragment = f"cuota {obj.cuota_nro}"
            pol_ref = str(pol.numero_poliza or pol.id)

            ingreso = (
                Ingreso.objects
                .filter(descripcion__icontains=desc_fragment)
                .filter(descripcion__icontains=pol_ref)
                .order_by("-id")
                .first()
            )
            if not ingreso and obj.fecha_pago:
                ingreso = (
                    Ingreso.objects
                    .filter(fecha=obj.fecha_pago, descripcion__icontains=desc_fragment)
                    .order_by("-id")
                    .first()
                )
            return ingreso
        except Exception:
            return None

    def get_cliente_nombre(self, obj):
        c = self._cli(obj)
        if not c:
            return ""
        ape = (getattr(c, "apellido", "") or "").strip()
        nom = (getattr(c, "nombre", "") or "").strip()
        return f"{ape}, {nom}".strip(", ").strip() if (ape or nom) else ""

    def get_cliente_dni(self, obj):
        c = self._cli(obj)
        return str(getattr(c, "dni_cuit_cuil", "") or "").strip() if c else ""

    def get_patente(self, obj):
        pol = self._pol(obj)
        return str(getattr(pol, "patente", "") or "").strip() if pol else ""

    def get_numero_poliza(self, obj):
        pol = self._pol(obj)
        return str(getattr(pol, "numero_poliza", "") or "").strip() if pol else ""

    def get_compania(self, obj):
        pol = self._pol(obj)
        return _compania_nombre_robusto(pol)

    def get_compania_nombre(self, obj):
        return self.get_compania(obj)

    def get_marca(self, obj):
        pol = self._pol(obj)
        return str(getattr(pol, "marca", "") or "").strip() if pol else ""

    def get_modelo(self, obj):
        pol = self._pol(obj)
        return str(getattr(pol, "modelo", "") or "").strip() if pol else ""

    def get_observaciones(self, obj):
        v = getattr(obj, "observaciones_pago", None)
        if v not in (None, ""):
            return str(v)
        v2 = getattr(obj, "ultima_observacion_pago", None)
        if v2 not in (None, ""):
            return str(v2)
        return ""

    def get_oficina(self, obj):
        pol = self._pol(obj)
        return str(getattr(pol, "oficina", "") or "").strip() if pol else ""

    def get_oficina_nombre(self, obj):
        pol = self._pol(obj)
        return _oficina_nombre(getattr(pol, "oficina", None)) if pol else ""

    def get_oficina_bucket(self, obj):
        pol = self._pol(obj)
        return _normalize_oficina_bucket(getattr(pol, "oficina", None)) if pol else ""

    def get_medio(self, obj):
        """Forma de pago legible."""
        fp = str(getattr(obj, "forma_pago", "") or "").strip().lower()
        if fp == "transferencia":
            return "Transferencia"
        if fp == "efectivo":
            return "Efectivo"
        return fp.capitalize() if fp else ""

    def get_destino_cuenta(self, obj):
        """Alias/CBU/cuenta destino del estudio donde cayó la transferencia."""
        ingreso = self._get_ingreso_relacionado(obj)
        if ingreso:
            return str(getattr(ingreso, "billetera", "") or "").strip()
        return ""

    def get_pagado_por(self, obj):
        """Nombre de quien realizó el pago/transferencia."""
        ingreso = self._get_ingreso_relacionado(obj)
        if ingreso:
            v = str(getattr(ingreso, "pagado_por", "") or "").strip()
            if v:
                return v
        # fallback: nombre del cliente
        c = self._cli(obj)
        if c:
            ape = (getattr(c, "apellido", "") or "").strip()
            nom = (getattr(c, "nombre", "") or "").strip()
            return f"{ape}, {nom}".strip(", ") if (ape or nom) else ""
        return ""

    def get_cuit_remitente(self, obj):
        """CUIT de quien transfirió."""
        ingreso = self._get_ingreso_relacionado(obj)
        if ingreso:
            v = str(getattr(ingreso, "cuit_remitente", "") or "").strip()
            if v:
                return v
        # fallback: parsear de observaciones
        obs = self.get_observaciones(obj)
        m = re.search(r'CUIT:\s*([^\s|]+)', obs)
        return m.group(1) if m else ""

    def get_nro_operacion(self, obj):
        """N° de comprobante/operación."""
        ingreso = self._get_ingreso_relacionado(obj)
        if ingreso:
            v = str(getattr(ingreso, "nro_operacion", "") or "").strip()
            if v:
                return v
        # fallback: parsear de observaciones
        obs = self.get_observaciones(obj)
        m = re.search(r'Op:\s*([^\s|]+)', obs)
        return m.group(1) if m else ""

    def _get_total_cuotas_poliza(self, pol):
        if not pol:
            return None
        total = getattr(pol, "cantidad_cuotas", None)
        if total:
            return total
        try:
            return pol.cuotas.aggregate(mx=Max("cuota_nro"))["mx"]
        except Exception:
            return None

    def get_cuota_label(self, obj):
        pol = self._pol(obj)
        if not pol:
            return ""
        total = self._get_total_cuotas_poliza(pol)
        nro = getattr(obj, "cuota_nro", None)
        if not nro:
            return ""
        if not total:
            return str(nro)
        return f"{nro}/{total}"

    def _get_pago_ts_dt(self, obj):
        ann = getattr(obj, "pago_ts", None)
        if ann:
            return ann
        dt = getattr(obj, "pago_registrado_en", None)
        if dt:
            return dt
        return None

    def get_pago_registrado_en(self, obj):
        dt = self._get_pago_ts_dt(obj)
        if not dt:
            return None
        dtx = _safe_localtime(dt)
        try:
            return dtx.isoformat()
        except Exception:
            return dt.isoformat() if hasattr(dt, "isoformat") else dt

    def get_pago_hora(self, obj):
        dt = self._get_pago_ts_dt(obj)
        if not dt:
            return ""
        try:
            dt = timezone.localtime(dt)
            return dt.strftime("%H:%M:%S")
        except Exception:
            try:
                return str(dt)[11:19]
            except Exception:
                return ""

    def get_pago_hm(self, obj):
        return _fmt_hm(self._get_pago_ts_dt(obj))

    def get_pago_hm_full(self, obj):
        return _fmt_full(self._get_pago_ts_dt(obj))

    def get_cuota_va(self, obj):
        return self.get_cuota_label(obj)

    def get_hora_guardado_pago(self, obj):
        return self.get_pago_hora(obj)

    def get_fecha_guardado_pago(self, obj):
        dt = self._get_pago_ts_dt(obj)
        if not dt:
            return ""
        try:
            dt = timezone.localtime(dt)
            return dt.strftime("%d/%m/%Y")
        except Exception:
            return ""