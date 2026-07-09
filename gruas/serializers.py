# gruas/serializers.py
from urllib.parse import unquote
import re
from math import radians, sin, cos, sqrt, atan2

from rest_framework import serializers
from django.db.models import Q
from django.utils import timezone

from .models import (
    PlanGrua,
    AdhesionGrua,
    ProveedorGrua,
    SolicitudGrua,
    SolicitudFoto,
    SolicitudEvento,
)


# =========================
# Utils
# =========================
def _is_bad_local_url(url: str) -> bool:
    u = (url or "").strip().lower()
    if not u:
        return False
    return (
        u.startswith("/media/")
        or u.startswith("media/")
        or "localhost" in u
        or "127.0.0.1" in u
        or u.startswith("http://localhost")
        or u.startswith("http://127.0.0.1")
    )


def _extract_coords_from_maps_url(url: str):
    """
    Soporta:
    - .../@-34.64,-58.56,17z/...
    - ...!3d-34.64!4d-58.56...
    - ...?q=-34.64,-58.56
    - ...?ll=-34.64,-58.56
    Acepta enteros o decimales.
    """
    u = (url or "").strip()
    if not u:
        return (None, None)

    try:
        u = unquote(u)
    except Exception:
        pass

    num = r"(-?\d+(?:\.\d+)?)"

    # Caso @lat,lng
    m = re.search(rf"@{num}\s*,\s*{num}", u)
    if m:
        try:
            return (float(m.group(1)), float(m.group(2)))
        except Exception:
            return (None, None)

    # Caso q=lat,lng
    m = re.search(rf"[?&]q={num}\s*,\s*{num}", u)
    if m:
        try:
            return (float(m.group(1)), float(m.group(2)))
        except Exception:
            return (None, None)

    # Caso ll=lat,lng
    m = re.search(rf"[?&]ll={num}\s*,\s*{num}", u)
    if m:
        try:
            return (float(m.group(1)), float(m.group(2)))
        except Exception:
            return (None, None)

    # Caso !3dlat!4dlng
    m = re.search(rf"!3d{num}!4d{num}", u)
    if m:
        try:
            return (float(m.group(1)), float(m.group(2)))
        except Exception:
            return (None, None)

    return (None, None)


def _haversine_km(lat1, lng1, lat2, lng2):
    R = 6371.0
    p1 = radians(float(lat1))
    p2 = radians(float(lat2))
    dlat = radians(float(lat2) - float(lat1))
    dlng = radians(float(lng2) - float(lng1))
    a = sin(dlat / 2) ** 2 + cos(p1) * cos(p2) * sin(dlng / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


def _prov_id(v):
    """
    ✅ DRF en PATCH puede pasar proveedor como:
    - int / str numérica
    - instancia ProveedorGrua
    """
    if v is None or v == "" or v == 0 or v == "0":
        return None
    if isinstance(v, ProveedorGrua):
        return v.id
    try:
        return int(v)
    except Exception:
        try:
            return int(getattr(v, "id", None))
        except Exception:
            return None


# =========================
# Planes / Proveedores
# =========================
class PlanGruaSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanGrua
        fields = [
            "id",
            "nombre",
            "km_incluidos",
            "precio_mensual",
            "proveedor_nombre",
            "activo",
            "creado_en",
            "actualizado_en",
        ]

    def validate_nombre(self, v):
        v = (v or "").strip()
        if not v:
            raise serializers.ValidationError("El nombre es obligatorio.")
        return v

    def validate_km_incluidos(self, v):
        try:
            v = int(v)
        except Exception:
            raise serializers.ValidationError("Kilómetros inválidos.")
        if v <= 0:
            raise serializers.ValidationError("Los kilómetros deben ser > 0.")
        return v

    def validate_precio_mensual(self, v):
        if v is None:
            return 0
        if v < 0:
            raise serializers.ValidationError("El precio mensual no puede ser negativo.")
        return v


class ProveedorGruaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProveedorGrua
        fields = [
            "id",
            "nombre",
            "telefono",  # ✅ NUEVO
            "patente_camion",
            "modelo_camion",
            "anio_camion",
            "foto_camion_1_url",
            "foto_camion_1_public_id",
            "foto_camion_2_url",
            "foto_camion_2_public_id",
            "licencia_url",
            "licencia_public_id",
            "vtv_url",
            "vtv_public_id",
            "activo",
            "creado_en",
            "actualizado_en",
        ]

    def validate_nombre(self, v):
        v = (v or "").strip()
        if len(v) < 2:
            raise serializers.ValidationError("El nombre es obligatorio.")
        return v

    def validate_telefono(self, v):
        v = (v or "").strip()
        if not v:
            return ""
        if len(v) < 6:
            raise serializers.ValidationError("Teléfono inválido.")
        return v

    def validate_patente_camion(self, v):
        v = (v or "").strip().upper()
        if len(v) < 5:
            raise serializers.ValidationError("Patente inválida.")
        return v

    def validate_anio_camion(self, v):
        try:
            v = int(v or 0)
        except Exception:
            raise serializers.ValidationError("Año inválido.")
        if not v:
            return 0
        current = timezone.localdate().year
        if v < 1950 or v > current + 1:
            raise serializers.ValidationError("Año inválido.")
        return v

    def _validate_pair(self, attrs, url_key, pid_key):
        url = (attrs.get(url_key, "") or "").strip()
        pid = (attrs.get(pid_key, "") or "").strip()
        if url and not pid:
            raise serializers.ValidationError({pid_key: "public_id requerido si hay URL (Cloudinary)."})
        return attrs

    def validate(self, attrs):
        attrs = self._validate_pair(attrs, "foto_camion_1_url", "foto_camion_1_public_id")
        attrs = self._validate_pair(attrs, "foto_camion_2_url", "foto_camion_2_public_id")
        attrs = self._validate_pair(attrs, "licencia_url", "licencia_public_id")
        attrs = self._validate_pair(attrs, "vtv_url", "vtv_public_id")
        return attrs


# =========================
# Polizas buscar
# =========================
class ClienteMiniSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    nombre = serializers.CharField(required=False, allow_blank=True)
    apellido = serializers.CharField(required=False, allow_blank=True)
    dni_cuit_cuil = serializers.CharField(required=False, allow_blank=True)


class PolizaBuscarSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    patente = serializers.CharField(allow_blank=True, required=False)
    compania = serializers.CharField(allow_blank=True, required=False)
    numero_poliza = serializers.CharField(allow_blank=True, required=False)
    marca = serializers.CharField(allow_blank=True, required=False)
    modelo = serializers.CharField(allow_blank=True, required=False)
    anio = serializers.IntegerField(required=False)
    cliente = ClienteMiniSerializer(required=False)

    @staticmethod
    def from_poliza(p):
        cli = getattr(p, "cliente", None)
        return {
            "id": p.id,
            "patente": getattr(p, "patente", "") or "",
            "compania": getattr(p, "compania", "") or "",
            "numero_poliza": getattr(p, "numero_poliza", "") or "",
            "marca": getattr(p, "marca", "") or "",
            "modelo": getattr(p, "modelo", "") or "",
            "anio": getattr(p, "anio", None),
            "cliente": {
                "id": getattr(cli, "id", None) if cli else None,
                "nombre": getattr(cli, "nombre", "") if cli else "",
                "apellido": getattr(cli, "apellido", "") if cli else "",
                "dni_cuit_cuil": str(getattr(cli, "dni_cuit_cuil", "") or "") if cli else "",
            },
        }


# =========================
# Adhesiones
# =========================
class AdhesionGruaSerializer(serializers.ModelSerializer):
    plan_detalle = PlanGruaSerializer(source="plan", read_only=True)
    fecha_carencia_fin = serializers.SerializerMethodField()

    poliza_patente = serializers.SerializerMethodField()
    poliza_compania = serializers.SerializerMethodField()
    poliza_numero_poliza = serializers.SerializerMethodField()
    cliente_nombre = serializers.SerializerMethodField()
    cliente_dni = serializers.SerializerMethodField()
    vehiculo_texto = serializers.SerializerMethodField()

    poliza = serializers.IntegerField(write_only=True)
    plan = serializers.IntegerField(write_only=True)

    class Meta:
        model = AdhesionGrua
        fields = [
            "id",
            "estado",
            "fecha_activacion",
            "carencia_dias",
            "fecha_carencia_fin",
            "motivo_cancelacion",
            "cancelada_en",
            "creado_en",
            "actualizado_en",
            "poliza",
            "plan",
            "plan_detalle",
            "poliza_patente",
            "poliza_compania",
            "poliza_numero_poliza",
            "cliente_nombre",
            "cliente_dni",
            "vehiculo_texto",
        ]
        read_only_fields = [
            "motivo_cancelacion",
            "cancelada_en",
            "creado_en",
            "actualizado_en",
        ]

    def get_fecha_carencia_fin(self, obj):
        try:
            d = obj.fecha_carencia_fin
            return d.isoformat() if d else None
        except Exception:
            return None

    def _poliza(self, obj):
        try:
            return obj.poliza
        except Exception:
            return None

    def get_poliza_patente(self, obj):
        p = self._poliza(obj)
        return getattr(p, "patente", "") if p else ""

    def get_poliza_compania(self, obj):
        p = self._poliza(obj)
        return getattr(p, "compania", "") if p else ""

    def get_poliza_numero_poliza(self, obj):
        p = self._poliza(obj)
        return getattr(p, "numero_poliza", "") if p else ""

    def get_cliente_nombre(self, obj):
        p = self._poliza(obj)
        cli = getattr(p, "cliente", None) if p else None
        if not cli:
            return ""
        nombre = getattr(cli, "nombre", "") or ""
        apellido = getattr(cli, "apellido", "") or ""
        return f"{apellido} {nombre}".strip()

    def get_cliente_dni(self, obj):
        p = self._poliza(obj)
        cli = getattr(p, "cliente", None) if p else None
        return str(getattr(cli, "dni_cuit_cuil", "") or "") if cli else ""

    def get_vehiculo_texto(self, obj):
        p = self._poliza(obj)
        if not p:
            return ""
        parts = [getattr(p, "marca", ""), getattr(p, "modelo", ""), getattr(p, "anio", "")]
        parts = [str(x).strip() for x in parts if x not in (None, "", 0)]
        return " ".join(parts)

    def validate(self, attrs):
        poliza_id = int(attrs.get("poliza"))
        exists = (
            AdhesionGrua.objects.filter(poliza_id=poliza_id)
            .filter(Q(estado="ACTIVA") | Q(estado="PAUSADA"))
            .exists()
        )
        if exists:
            raise serializers.ValidationError("Ya existe una adhesión ACTIVA/PAUSADA para esta póliza.")
        return attrs

    def create(self, validated_data):
        from django.apps import apps

        Poliza = apps.get_model("polizas", "Poliza")

        poliza_id = int(validated_data.pop("poliza"))
        plan_id = int(validated_data.pop("plan"))

        poliza = Poliza.objects.get(id=poliza_id)
        plan = PlanGrua.objects.get(id=plan_id)

        return AdhesionGrua.objects.create(
            poliza=poliza,
            plan=plan,
            fecha_activacion=validated_data.get("fecha_activacion"),
            carencia_dias=validated_data.get("carencia_dias", 15),
            estado="ACTIVA",
        )


# =========================
# Solicitudes
# =========================
class SolicitudFotoSerializer(serializers.ModelSerializer):
    class Meta:
        model = SolicitudFoto
        fields = ["id", "tipo", "url", "public_id", "descripcion", "creado_en"]
        read_only_fields = ["id", "creado_en"]

    def validate(self, attrs):
        url = (attrs.get("url", "") or "").strip()
        pid = (attrs.get("public_id", "") or "").strip()
        if not url:
            raise serializers.ValidationError({"url": "URL requerida."})
        if not pid:
            raise serializers.ValidationError({"public_id": "public_id requerido (Cloudinary)."})
        if _is_bad_local_url(url):
            raise serializers.ValidationError({"url": "URL inválida (no /media ni localhost). Usar Cloudinary."})
        return attrs


class SolicitudEventoSerializer(serializers.ModelSerializer):
    class Meta:
        model = SolicitudEvento
        fields = ["id", "tipo", "detalle", "creado_en"]
        read_only_fields = ["id", "creado_en"]


class SolicitudGruaSerializer(serializers.ModelSerializer):
    # read
    fotos = SolicitudFotoSerializer(many=True, read_only=True)
    eventos = SolicitudEventoSerializer(many=True, read_only=True)
    proveedor_detalle = ProveedorGruaSerializer(source="proveedor", read_only=True)

    # ✅ extras para UI + envío
    proveedor_nombre = serializers.SerializerMethodField()
    proveedor_telefono = serializers.SerializerMethodField()

    # ✅ write: para aceptar el payload del front (sin tocar front)
    fotos_input = serializers.JSONField(write_only=True, required=False)

    # ui helpers
    poliza_patente = serializers.SerializerMethodField()
    poliza_compania = serializers.SerializerMethodField()
    cliente_nombre = serializers.SerializerMethodField()
    cliente_dni = serializers.SerializerMethodField()
    vehiculo_texto = serializers.SerializerMethodField()

    # write (ids) + aliases
    adhesion = serializers.IntegerField(write_only=True, required=False)
    adhesion_id = serializers.IntegerField(write_only=True, required=False)
    poliza = serializers.IntegerField(write_only=True, required=False)
    poliza_id = serializers.IntegerField(write_only=True, required=False)

    class Meta:
        model = SolicitudGrua
        fields = [
            "id",
            "estado",
            "motivo",
            "notas",
            "adhesion",
            "adhesion_id",
            "poliza",
            "poliza_id",
            "proveedor",
            "proveedor_detalle",
            "proveedor_nombre",
            "proveedor_telefono",
            "origen_direccion",
            "origen_localidad",
            "origen_maps_url",
            "origen_lat",
            "origen_lng",
            "destino_direccion",
            "destino_localidad",
            "destino_maps_url",
            "destino_lat",
            "destino_lng",
            "km_estimados",
            "asignada_en",
            "cerrada_en",
            "cancelada_en",
            "creado_en",
            "actualizado_en",
            "poliza_patente",
            "poliza_compania",
            "cliente_nombre",
            "cliente_dni",
            "vehiculo_texto",
            "fotos",
            "fotos_input",
            "eventos",
        ]
        read_only_fields = [
            "estado",
            "origen_lat",
            "origen_lng",
            "destino_lat",
            "destino_lng",
            "km_estimados",
            "asignada_en",
            "cerrada_en",
            "cancelada_en",
            "creado_en",
            "actualizado_en",
            "fotos",
            "eventos",
        ]

    # -------- helpers --------
    def _poliza_obj(self, obj):
        try:
            return obj.poliza
        except Exception:
            return None

    def _proveedor_obj(self, obj):
        try:
            return obj.proveedor
        except Exception:
            return None

    def get_proveedor_nombre(self, obj):
        p = self._proveedor_obj(obj)
        if not p:
            return ""
        return (getattr(p, "nombre", "") or "").strip()

    def get_proveedor_telefono(self, obj):
        p = self._proveedor_obj(obj)
        if not p:
            return ""
        return (getattr(p, "telefono", "") or "").strip()

    def get_poliza_patente(self, obj):
        p = self._poliza_obj(obj)
        return getattr(p, "patente", "") if p else ""

    def get_poliza_compania(self, obj):
        p = self._poliza_obj(obj)
        return getattr(p, "compania", "") if p else ""

    def get_cliente_nombre(self, obj):
        p = self._poliza_obj(obj)
        cli = getattr(p, "cliente", None) if p else None
        if not cli:
            return ""
        nombre = getattr(cli, "nombre", "") or ""
        apellido = getattr(cli, "apellido", "") or ""
        return f"{apellido} {nombre}".strip()

    def get_cliente_dni(self, obj):
        p = self._poliza_obj(obj)
        cli = getattr(p, "cliente", None) if p else None
        return str(getattr(cli, "dni_cuit_cuil", "") or "") if cli else ""

    def get_vehiculo_texto(self, obj):
        p = self._poliza_obj(obj)
        if not p:
            return ""
        parts = [getattr(p, "marca", ""), getattr(p, "modelo", ""), getattr(p, "anio", "")]
        parts = [str(x).strip() for x in parts if x not in (None, "", 0)]
        return " ".join(parts)

    def _get_fotos_payload(self, attrs):
        payload = attrs.get("fotos_input", None)
        if payload is None:
            try:
                payload = self.initial_data.get("fotos", None)
            except Exception:
                payload = None
        return payload

    def _validate_foto_item(self, item, ctx="foto"):
        if not isinstance(item, dict):
            raise serializers.ValidationError({"fotos": f"{ctx}: formato inválido"})
        url = (item.get("url") or "").strip()
        pid = (item.get("public_id") or "").strip()
        if not url:
            raise serializers.ValidationError({"fotos": f"{ctx}: falta url"})
        if not pid:
            raise serializers.ValidationError({"fotos": f"{ctx}: falta public_id"})
        if _is_bad_local_url(url):
            raise serializers.ValidationError({"fotos": f"{ctx}: URL inválida (no /media ni localhost)"})
        return {"url": url, "public_id": pid, "descripcion": (item.get("descripcion") or "").strip()}

    # -------- validate/create/update --------
    def validate(self, attrs):
        """
        ✅ CREATE: valida todo (adhesion/maps/fotos)
        ✅ UPDATE/PATCH: permite update liviano (ej: solo proveedor) sin pedir adhesion/maps/fotos
        """
        # -------- UPDATE liviano --------
        if self.instance is not None:
            if "proveedor" in attrs and attrs.get("proveedor") is not None:
                pid = _prov_id(attrs.get("proveedor"))
                if not pid:
                    raise serializers.ValidationError({"proveedor": "Proveedor inválido."})
                prov = ProveedorGrua.objects.filter(id=pid).first()
                if not prov:
                    raise serializers.ValidationError({"proveedor": "Proveedor inválido."})
                if not prov.activo:
                    raise serializers.ValidationError({"proveedor": "Proveedor inactivo."})
                # deja el valor en formato id para update()
                attrs["proveedor"] = pid
            return attrs

        # -------- CREATE completo --------
        adhesion_raw = attrs.get("adhesion", None)
        if adhesion_raw is None:
            adhesion_raw = attrs.get("adhesion_id", None)
        if adhesion_raw is None:
            raise serializers.ValidationError({"adhesion": "Falta adhesión (adhesion o adhesion_id)."})

        try:
            adhesion_id = int(adhesion_raw)
        except Exception:
            raise serializers.ValidationError({"adhesion": "Adhesión inválida."})

        adhesion = (
            AdhesionGrua.objects.select_related("poliza", "poliza__cliente")
            .filter(id=adhesion_id)
            .first()
        )
        if not adhesion:
            raise serializers.ValidationError({"adhesion": "Adhesión inválida."})
        if adhesion.estado != "ACTIVA":
            raise serializers.ValidationError({"adhesion": "La adhesión debe estar ACTIVA."})

        poliza_in = attrs.get("poliza", None)
        if poliza_in is None:
            poliza_in = attrs.get("poliza_id", None)
        if poliza_in is not None:
            try:
                poliza_in = int(poliza_in)
            except Exception:
                raise serializers.ValidationError({"poliza": "Póliza inválida."})
            if poliza_in != adhesion.poliza_id:
                raise serializers.ValidationError({"poliza": "La póliza no coincide con la adhesión."})

        # ✅ localidades
        o_loc = (attrs.get("origen_localidad", "") or "").strip()
        d_loc = (attrs.get("destino_localidad", "") or "").strip()
        if len(o_loc) < 2:
            raise serializers.ValidationError({"origen_localidad": "Localidad de origen requerida."})
        if len(d_loc) < 2:
            raise serializers.ValidationError({"destino_localidad": "Localidad de destino requerida."})

        o_url = (attrs.get("origen_maps_url", "") or "").strip()
        d_url = (attrs.get("destino_maps_url", "") or "").strip()

        o_lat, o_lng = _extract_coords_from_maps_url(o_url)
        d_lat, d_lng = _extract_coords_from_maps_url(d_url)

        if not o_url or o_lat is None or o_lng is None:
            raise serializers.ValidationError(
                {"origen_maps_url": "Pegá un link de Google Maps con coordenadas (ej: @lat,lng o q=lat,lng)."}
            )
        if not d_url or d_lat is None or d_lng is None:
            raise serializers.ValidationError(
                {"destino_maps_url": "Pegá un link de Google Maps con coordenadas (ej: @lat,lng o q=lat,lng)."}
            )
        attrs["origen_lat"] = o_lat
        attrs["origen_lng"] = o_lng
        attrs["destino_lat"] = d_lat
        attrs["destino_lng"] = d_lng

        try:
            km = _haversine_km(o_lat, o_lng, d_lat, d_lng)
            attrs["km_estimados"] = round(km, 2)
        except Exception:
            attrs["km_estimados"] = None

        if len((attrs.get("origen_direccion", "") or "").strip()) < 3:
            raise serializers.ValidationError({"origen_direccion": "Dirección de origen requerida."})
        if len((attrs.get("destino_direccion", "") or "").strip()) < 3:
            raise serializers.ValidationError({"destino_direccion": "Dirección de destino requerida."})

        pid = _prov_id(attrs.get("proveedor"))
        if pid is not None:
            prov = ProveedorGrua.objects.filter(id=pid).first()
            if not prov:
                raise serializers.ValidationError({"proveedor": "Proveedor inválido."})
            if not prov.activo:
                raise serializers.ValidationError({"proveedor": "Proveedor inactivo."})
            attrs["proveedor"] = pid  # deja id, no objeto

        fotos_payload = self._get_fotos_payload(attrs)
        if fotos_payload is None:
            raise serializers.ValidationError({"fotos": "Faltan fotos (auto/lugar/documentos)."})
        if not isinstance(fotos_payload, dict):
            raise serializers.ValidationError({"fotos": "Formato inválido."})

        auto = fotos_payload.get("auto") or []
        lugar = fotos_payload.get("lugar") or []
        docs = fotos_payload.get("documentos") or []

        if not isinstance(auto, list) or len(auto) != 4:
            raise serializers.ValidationError({"fotos": "Se requieren 4 fotos del auto."})
        if not isinstance(lugar, list) or len(lugar) != 2:
            raise serializers.ValidationError({"fotos": "Se requieren 2 fotos del lugar."})
        if not isinstance(docs, list) or len(docs) != 2:
            raise serializers.ValidationError({"fotos": "Se requieren 2 fotos de documentos (registro y dni)."})

        auto_norm = [self._validate_foto_item(x, f"auto[{i+1}]") for i, x in enumerate(auto)]
        lugar_norm = [self._validate_foto_item(x, f"lugar[{i+1}]") for i, x in enumerate(lugar)]

        docs_norm = []
        seen = set()
        for i, x in enumerate(docs):
            if not isinstance(x, dict):
                raise serializers.ValidationError({"fotos": f"documentos[{i+1}]: formato inválido"})
            t = (x.get("tipo") or "").strip().lower()
            if t not in ("registro", "dni"):
                raise serializers.ValidationError({"fotos": f"documentos[{i+1}]: tipo inválido (registro/dni)"})
            if t in seen:
                raise serializers.ValidationError({"fotos": f"documentos: tipo repetido ({t})"})
            seen.add(t)
            base = self._validate_foto_item(x, f"documentos[{i+1}]")
            base["tipo_doc"] = t
            docs_norm.append(base)

        if "registro" not in seen or "dni" not in seen:
            raise serializers.ValidationError({"fotos": "documentos debe incluir registro y dni."})

        attrs["_adhesion_obj"] = adhesion
        attrs["_fotos_norm"] = {
            "auto": auto_norm,
            "lugar": lugar_norm,
            "docs": docs_norm,
        }
        return attrs

    def create(self, validated_data):
        adhesion = validated_data.pop("_adhesion_obj")
        fotos_norm = validated_data.pop("_fotos_norm", None)

        validated_data.pop("adhesion", None)
        validated_data.pop("adhesion_id", None)
        validated_data.pop("poliza", None)
        validated_data.pop("poliza_id", None)
        validated_data.pop("fotos_input", None)

        obj = SolicitudGrua.objects.create(
            adhesion=adhesion,
            poliza=adhesion.poliza,
            proveedor_id=_prov_id(validated_data.get("proveedor")),
            motivo=(validated_data.get("motivo") or "").strip(),
            notas=(validated_data.get("notas") or "").strip(),
            origen_direccion=(validated_data.get("origen_direccion") or "").strip(),
            origen_localidad=(validated_data.get("origen_localidad") or "").strip(),
            origen_maps_url=(validated_data.get("origen_maps_url") or "").strip(),
            origen_lat=validated_data.get("origen_lat"),
            origen_lng=validated_data.get("origen_lng"),
            destino_direccion=(validated_data.get("destino_direccion") or "").strip(),
            destino_localidad=(validated_data.get("destino_localidad") or "").strip(),
            destino_maps_url=(validated_data.get("destino_maps_url") or "").strip(),
            destino_lat=validated_data.get("destino_lat"),
            destino_lng=validated_data.get("destino_lng"),
            km_estimados=validated_data.get("km_estimados"),
            estado="ABIERTA",
        )

        SolicitudEvento.objects.create(
            solicitud=obj,
            tipo="CREADA",
            detalle="Solicitud creada",
        )

        if fotos_norm:
            bulk = []

            for x in fotos_norm.get("auto", []):
                bulk.append(
                    SolicitudFoto(
                        solicitud=obj,
                        tipo="AUTO",
                        url=x["url"],
                        public_id=x["public_id"],
                        descripcion=x.get("descripcion", ""),
                    )
                )

            for x in fotos_norm.get("lugar", []):
                bulk.append(
                    SolicitudFoto(
                        solicitud=obj,
                        tipo="LUGAR",
                        url=x["url"],
                        public_id=x["public_id"],
                        descripcion=x.get("descripcion", ""),
                    )
                )

            for x in fotos_norm.get("docs", []):
                tipo = "REGISTRO" if x.get("tipo_doc") == "registro" else "DNI"
                bulk.append(
                    SolicitudFoto(
                        solicitud=obj,
                        tipo=tipo,
                        url=x["url"],
                        public_id=x["public_id"],
                        descripcion=x.get("descripcion", ""),
                    )
                )

            SolicitudFoto.objects.bulk_create(bulk)

            SolicitudEvento.objects.create(
                solicitud=obj,
                tipo="FOTOS",
                detalle=f"Fotos cargadas ({len(bulk)})",
            )

        return obj

    def update(self, instance, validated_data):
        """
        ✅ PATCH { proveedor: X } sin pedir adhesion/maps/fotos.
        Si estaba ABIERTA => ASIGNADA (+asignada_en) y evento.
        """
        changed = False

        if "proveedor" in validated_data:
            pid = _prov_id(validated_data.get("proveedor"))
            instance.proveedor_id = pid
            changed = True

            if (instance.estado or "").upper() == "ABIERTA" and pid:
                instance.estado = "ASIGNADA"
                instance.asignada_en = timezone.now()

        if changed:
            instance.save()

            if "proveedor" in validated_data:
                SolicitudEvento.objects.create(
                    solicitud=instance,
                    tipo="ASIGNADA" if (instance.estado or "").upper() == "ASIGNADA" else "PROVEEDOR",
                    detalle=f"Proveedor asignado (id={instance.proveedor_id or 'null'})",
                )

        return instance
