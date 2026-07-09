# solicitudes/serializers.py
from datetime import date, datetime
from typing import Dict
from decimal import Decimal
import sys
from calendar import monthrange

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers

from .models import (
    SolicitudSeguro,
    SolicitudDocumento,
    TipoDocSolicitud,
    Empleado,
    MotivoSolicitud,
)

try:
    from clientes.models import Cliente, EstadoCliente  
except Exception:  
    Cliente = None

    class EstadoCliente:  
        BORRADOR = "BORRADOR"

from polizas.models import (
    Poliza,
    PolizaFase,
    FotoVehiculo,
    PolizaDocumento,
    TipoFotoVehiculo,
    OrigenFotoVehiculo,
    CuponRobo,  
)
from pagos.models import Cuota
from cotizaciones.models import TipoCobertura
from polizas.precios_nre import es_nre, precio_multivehiculo, precio_vigente
from usuarios.models import Oficina

try:
    from polizas.utils.constants import get_cuotas_por_compania, normalizar_compania  
except Exception:  

    def get_cuotas_por_compania(_compania: str) -> int:  
        return 12

    def normalizar_compania(nombre: str) -> str:  
        return nombre


def _add_months(d: date, months: int) -> date:
    from calendar import monthrange as _mr
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    day = min(d.day, _mr(y, m)[1])
    return date(y, m, day)

def _to_date_cupon(v):
    """Convierte 'YYYY-MM-DD' (o date) a date. None si no se puede."""
    if not v:
        return None
    if isinstance(v, date):
        return v
    try:
        return datetime.fromisoformat(str(v)[:10]).date()
    except Exception:
        return None


def _fechas_cupones(cupones):
    """De la cuponera leída del PDF (AMCA, La Equidad, etc.) saca las fechas de
    vencimiento REALES, ordenadas. Devuelve [] si no vino cuponera.

    Esto es lo que hace que una póliza de robo tome las cuotas EXACTAS de la
    cuponera (cantidad y fechas), en vez de 6 mensuales por defecto.
    """
    out = []
    for cp in (cupones or []):
        d = _to_date_cupon((cp or {}).get("vencimiento"))
        if d:
            out.append(d)
    return sorted(out)


def _dec_or_none(x):
    if x is None or x == "":
        return None
    try:
        return Decimal(str(x))
    except Exception:
        return None


def _cupones_norm(cupones):
    """Normaliza la cuponera leída del PDF (AMCA, La Equidad, etc.).

    - Descarta cupones sin fecha válida.
    - ELIMINA DUPLICADOS: si el PDF trae el mismo cupón repetido (mismo número,
      o misma fecha cuando no hay número), se queda con UNO solo. Así la CANTIDAD
      de cuotas es siempre exacta aunque el lector devuelva la cuponera 2 veces.
    - Empareja cada fecha con SU importe (el de la boleta), para NO perder el monto.

    Devuelve una lista ordenada por fecha:
        [{"fecha": date, "importe": Decimal|None}, ...]
    """
    vistos = set()
    out = []
    for cp in (cupones or []):
        cp = cp or {}
        f = _to_date_cupon(cp.get("vencimiento"))
        if not f:
            continue
        num = cp.get("numero")
        # Clave anti-duplicado: por número si vino; si no, por fecha.
        key = ("N", num) if num is not None else ("F", f)
        if key in vistos:
            continue
        vistos.add(key)
        out.append({"fecha": f, "importe": _dec_or_none(cp.get("importe"))})
    out.sort(key=lambda x: x["fecha"])
    return out

def _log(context: str, **kwargs):
    try:
        parts = [f"[SOLICITUDES][{context}]"]
        for k, v in kwargs.items():
            parts.append(f"{k}={v!r}")
        print(" ".join(parts), file=sys.stdout, flush=True)
    except Exception:
        pass


_FOTO_TIPOS_ADMITIDOS: Dict[str, str] = {}
for _k, _enum_name in [
    ("PATENTE", "PATENTE"), ("FRENTE", "FRENTE"), ("LATERAL_IZQ", "LATERAL_IZQ"),
    ("LATERAL_DER", "LATERAL_DER"), ("TRASERA", "TRASERA"), ("INTERIOR", "INTERIOR"),
    ("RUEDA_AUXILIO", "RUEDA_AUXILIO"), ("RUEDA_AUX", "RUEDA_AUX"),
    ("TUBO_GNC", "TUBO_GNC"), ("EQUIPO_GNC", "EQUIPO_GNC"),
]:
    _val = getattr(TipoFotoVehiculo, _enum_name, None)
    if _val is not None:
        _FOTO_TIPOS_ADMITIDOS[_k] = _val

_DOC_LADOS = {
    "CEDULA_VERDE_FRENTE": ("CEDULA_VERDE", "FRENTE"),
    "CEDULA_VERDE_DORSO": ("CEDULA_VERDE", "DORSO"),
    "CEDULA_AZUL_FRENTE": ("CEDULA_AZUL", "FRENTE"),
    "CEDULA_AZUL_DORSO": ("CEDULA_AZUL", "DORSO"),
}
_TIPOS_DOC_ADMITIDOS = {
    "CEDULA_VERDE", "CEDULA_AZUL", "TITULO", "VTV", "OBLEA_GNC",
    "PERMISO", "PERMISO_CIRCULACION",
}


def _ensure_cupones_robo_for_poliza(poliza: Poliza) -> int:
    print("\n" + "="*40)
    print(" 🛠️ DEBUG: INICIANDO GENERACIÓN DE CUPONES")
    print("="*40)
    
    poliza.refresh_from_db()
    poliza_id = getattr(poliza, "id", None)
    
    print(f"👉 1. Póliza ID: {poliza_id}")
    print(f"👉 2. Compañía registrada: '{poliza.compania}'")
    print(f"👉 3. Cobertura registrada: '{poliza.cobertura}'")

    genera_cupones = False
    cob_nombre = (poliza.cobertura or "").strip()
    comp_nombre = (poliza.compania or "").strip()
    
    cob_obj = TipoCobertura.objects.filter(
        nombre__iexact=cob_nombre,
        compania__nombre__iexact=comp_nombre
    ).first()
    
    print(f"👉 4. ¿Encontró la cobertura en BD cruzando ambos datos?: {'SÍ' if cob_obj else 'NO'}")
    
    if cob_obj:
        genera_cupones = cob_obj.genera_cupones_robo
        print(f"👉 5. El check 'genera_cupones_robo' en BD es: {genera_cupones}")
    else:
        print("❌ ERROR: No se generarán cupones porque no se encontró la cobertura exacta en el catálogo.")

    if not genera_cupones:
        print("🛑 Abortando: La cobertura no requiere cupones.")
        print("="*40 + "\n")
        return 0

    if CuponRobo.objects.filter(poliza=poliza).exists():
        print("🛑 Abortando: Los cupones ya existen para esta póliza.")
        print("="*40 + "\n")
        return 0

    cuotas = list(
        Cuota.objects.filter(poliza=poliza)
        .exclude(fecha_vencimiento__isnull=True)
        .order_by("fecha_vencimiento", "cuota_nro", "id")
    )
    print(f"👉 6. Cuotas detectadas para esta póliza: {len(cuotas)}")

    if not cuotas:
        print("❌ ERROR: No hay cuotas generadas, imposible crear cupones.")
        print("="*40 + "\n")
        return 0

    objs = []
    for c in cuotas:
        vto = c.fecha_vencimiento
        if not vto: continue
        last_day = monthrange(vto.year, vto.month)[1]
        periodo_desde = date(vto.year, vto.month, 1)
        periodo_hasta = date(vto.year, vto.month, last_day)
        objs.append(
            CuponRobo(
                poliza=poliza,
                periodo_desde=periodo_desde,
                periodo_hasta=periodo_hasta,
                fecha_vencimiento=vto,
                estado=CuponRobo.Estado.PENDIENTE,
                monto=0,
            )
        )

    if objs:
        CuponRobo.objects.bulk_create(objs, ignore_conflicts=False)
        print(f"✅ ¡ÉXITO! Se acaban de generar y guardar {len(objs)} cupones de robo.")
    
    print("="*40 + "\n")
    return len(objs)


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
            "id", "codigo", "estado", "inicio", "fin", "qr_payload", "creado_en",
            "actualizado_en", "asignado_en", "terminada_en", "cliente_id"
        )

    def get_tareas(self, obj):
        return {
            "alta_compania": bool(getattr(obj, "alta_compania", False)),
            "enviar_poliza": bool(getattr(obj, "enviar_poliza", False)),
        }

    def get_cliente_id(self, obj):
        if hasattr(obj, 'poliza') and obj.poliza: return obj.poliza.cliente_id
        return None

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


def _importar_desde_solicitud_hacia_poliza(solicitud, poliza, set_foto_perfil_frente=True, sobreescribir_foto_perfil=False, importar_documentos=True) -> Dict:
    creadas_fotos, creados_docs, seteo_perfil = 0, 0, False
    docs = list(solicitud.documentos.all().order_by("id"))

    def _upsert_foto(url, public_id, tipo):
        if not url: return False
        public_id = (public_id or "").strip()
        obj = FotoVehiculo.objects.filter(poliza=poliza, public_id=public_id).first() if public_id else FotoVehiculo.objects.filter(poliza=poliza, url=url, tipo=tipo).first()
        if obj: return False
        FotoVehiculo.objects.create(poliza=poliza, url=url, public_id=public_id or "", tipo=tipo, origen=OrigenFotoVehiculo.SOLICITUD)
        return True

    def _upsert_doc(tipo, url, public_id="", lado="", nombre="", mime=""):
        if not url: return False
        public_id = (public_id or "").strip()
        lado = (lado or "").strip().upper()
        if tipo not in {"CEDULA_VERDE", "CEDULA_AZUL"}: lado = ""
        obj = PolizaDocumento.objects.filter(poliza=poliza, public_id=public_id).first() if public_id else PolizaDocumento.objects.filter(poliza=poliza, tipo=tipo, lado=lado, url=url).first()
        if obj: return False
        PolizaDocumento.objects.create(poliza=poliza, tipo=tipo, url=url, public_id=public_id or "", lado=lado or "", nombre=nombre or "", mime=mime or "")
        return True

    for doc in docs:
        tipo = str(doc.tipo).upper() if doc.tipo else "OTRO"
        if (tipo in _FOTO_TIPOS_ADMITIDOS or doc.notas == "ES_FOTO") and doc.url:
            if _upsert_foto(doc.url, (doc.public_id or ""), _FOTO_TIPOS_ADMITIDOS.get(tipo, getattr(TipoFotoVehiculo, "OTRA", "OTRA"))): creadas_fotos += 1

    if set_foto_perfil_frente:
        frente = next((d for d in docs if d.tipo == TipoDocSolicitud.FRENTE), None)
        if frente and frente.url and (sobreescribir_foto_perfil or not (poliza.foto_perfil_url or "")):
            poliza.foto_perfil_url = frente.url
            if hasattr(poliza, "foto_perfil_public_id"): poliza.foto_perfil_public_id = getattr(frente, "public_id", "") or ""
            poliza.save(update_fields=["foto_perfil_url", "foto_perfil_public_id"] if hasattr(poliza, "foto_perfil_public_id") else ["foto_perfil_url"])
            seteo_perfil = True

    if importar_documentos:
        for doc in docs:
            tipo = str(doc.tipo).upper() if doc.tipo else "OTRO"
            url = doc.url or ""
            if not url or doc.notas == "ES_FOTO": continue 

            if tipo in _TIPOS_DOC_ADMITIDOS:
                if _upsert_doc(tipo, url, (doc.public_id or "")): creados_docs += 1
            elif tipo in _DOC_LADOS:
                base, lado = _DOC_LADOS[tipo]
                if _upsert_doc(base, url, (doc.public_id or ""), lado=lado): creados_docs += 1
            else:
                if _upsert_doc(tipo, url, (doc.public_id or "")): creados_docs += 1

    return {"fotos_creadas": creadas_fotos, "docs_creados": creados_docs, "foto_perfil_actualizada": seteo_perfil}


class _FotoSlotSerializer(serializers.Serializer):
    url = serializers.URLField()
    public_id = serializers.CharField(required=False, allow_blank=True, allow_null=True, default="")
    vencimiento = serializers.DateField(required=False, allow_null=True)

class _ClienteInSerializer(serializers.Serializer):
    modo = serializers.ChoiceField(choices=("nuevo", "existente"))
    id = serializers.IntegerField(required=False, allow_null=True)
    nombre = serializers.CharField(required=False, allow_blank=True)
    apellido = serializers.CharField(required=False, allow_blank=True)
    telefono = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    dni_cuit_cuil = serializers.CharField(required=False, allow_blank=True)
    direccion = serializers.CharField(required=False, allow_blank=True)
    localidad = serializers.CharField(required=False, allow_blank=True)
    partido = serializers.CharField(required=False, allow_blank=True)
    fecha_nacimiento = serializers.DateField(required=False, allow_null=True)
    archivo_dni_frente = serializers.URLField(required=False, allow_blank=True, allow_null=True)
    archivo_dni_dorso = serializers.URLField(required=False, allow_blank=True, allow_null=True)
    oficina = serializers.IntegerField(required=False, allow_null=True)

class _ClienteFotosSerializer(serializers.Serializer):
    DNI_FRENTE = _FotoSlotSerializer(required=False, allow_null=True)
    DNI_DORSO = _FotoSlotSerializer(required=False, allow_null=True)

class _PolizaInSerializer(serializers.Serializer):
    modo = serializers.ChoiceField(choices=("nueva", "existente"))
    id = serializers.IntegerField(required=False, allow_null=True)
    compania = serializers.CharField(required=False, allow_blank=True)
    numero_poliza = serializers.CharField(required=False, allow_blank=True)
    cobertura = serializers.CharField(required=False, allow_blank=True)
    oficina = serializers.IntegerField(required=False, allow_null=True)
    patente = serializers.CharField(required=False, allow_blank=True)
    marca = serializers.CharField(required=False, allow_blank=True)
    modelo = serializers.CharField(required=False, allow_blank=True)
    anio = serializers.IntegerField(required=False, allow_null=True)
    tipo = serializers.CharField(required=False, allow_blank=True)
    numero_motor = serializers.CharField(required=False, allow_blank=True)
    numero_chasis = serializers.CharField(required=False, allow_blank=True)
    combustible = serializers.CharField(required=False, allow_blank=True)
    carroceria = serializers.CharField(required=False, allow_blank=True)
    observaciones = serializers.CharField(required=False, allow_blank=True)
    precio_cuota = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True)
    cantidad_cuotas_override = serializers.IntegerField(required=False, allow_null=True)
    primer_vencimiento = serializers.DateField(required=False, allow_null=True)
    fecha_emision = serializers.DateField(required=False, allow_null=True)
    dias_a_vencer = serializers.IntegerField(required=False, allow_null=True)
    generar_cuotas_ahora = serializers.BooleanField(required=False, default=True)
    # 🎟️ Cuponera leída del PDF (AMCA, La Equidad…): [{numero, vencimiento, importe}, ...]
    #    Si viene, las cuotas se generan con estas fechas exactas.
    cupones = serializers.ListField(child=serializers.DictField(), required=False, default=list)

class _SolicitudInSerializer(serializers.Serializer):
    motivo = serializers.ChoiceField(choices=[m[0] for m in MotivoSolicitud.choices], required=False)
    observaciones = serializers.CharField(required=False, allow_blank=True)
    prioridad = serializers.CharField(required=False, allow_blank=True)
    responsable_nombre = serializers.CharField(required=False, allow_blank=True)
    responsable = serializers.CharField(required=False, allow_blank=True)
    responsable_empleado = serializers.PrimaryKeyRelatedField(queryset=Empleado.objects.all(), required=False, allow_null=True)


class CrearCompletoSerializer(serializers.Serializer):
    cliente = _ClienteInSerializer()
    cliente_fotos = _ClienteFotosSerializer(required=False)
    poliza = _PolizaInSerializer()
    solicitud = _SolicitudInSerializer()
    fotos = serializers.DictField(required=False)
    documentos = serializers.DictField(required=False)
    oficina = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
        solicitud = attrs.get("solicitud", {})
        nom = (solicitud.get("responsable_nombre") or solicitud.get("responsable") or "").strip()
        if not (nom or solicitud.get("responsable_empleado")):
            raise serializers.ValidationError({"solicitud": {"responsable_nombre": "Campo obligatorio."}})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        c_in, p_in, s_in = validated_data["cliente"], validated_data["poliza"], validated_data["solicitud"]
        cf_in = validated_data.get("cliente_fotos") or {}
        f_in = validated_data.get("fotos") or {}
        d_in = validated_data.get("documentos") or {}
        oficina_id_final = validated_data.get("oficina")

        if c_in["modo"] == "existente":
            cli = Cliente.objects.get(id=c_in["id"])
        else:
            cli = Cliente.objects.create(
                nombre=(c_in.get("nombre") or "").strip(), apellido=(c_in.get("apellido") or "").strip(),
                telefono=(c_in.get("telefono") or "").strip(), email=c_in.get("email"),
                dni_cuit_cuil=(c_in.get("dni_cuit_cuil") or "").strip(),
                direccion=(c_in.get("direccion") or "").strip(), localidad=(c_in.get("localidad") or "").strip(),
                partido=(c_in.get("partido") or "").strip(),
                fecha_nacimiento=c_in.get("fecha_nacimiento"),
                oficina_id=oficina_id_final,
            )
        
        def _pk(slot, key): return (slot.get(key) or {}).get("url") or ""
        uf = c_in.get("archivo_dni_frente") or _pk(cf_in, "DNI_FRENTE") or _pk(f_in, "DNI_FRENTE")
        ud = c_in.get("archivo_dni_dorso") or _pk(cf_in, "DNI_DORSO") or _pk(f_in, "DNI_DORSO")
        if uf or ud: 
            if uf: cli.archivo_dni_frente = uf
            if ud: cli.archivo_dni_dorso = ud
            cli.save(update_fields=["archivo_dni_frente", "archivo_dni_dorso"])

        if p_in["modo"] == "existente":
            pol = Poliza.objects.get(id=p_in["id"])
        else:
            comp = (p_in.get("compania") or "").strip()
            cob_nombre = (p_in.get("cobertura") or "").strip()
            emision = p_in.get("fecha_emision") or timezone.localdate()
            dv = p_in.get("dias_a_vencer") if p_in.get("dias_a_vencer") is not None else 30

            # 🎟️ ¿Vino una cuponera con fechas REALES? (AMCA, La Equidad, etc.)
            #    Si sí, las cuotas son EXACTAMENTE las de la cuponera: misma CANTIDAD
            #    y mismas FECHAS. NO se usan 6 mensuales ni la cantidad de la cobertura.
            cupones_norm = _cupones_norm(p_in.get("cupones"))

            cob_obj = TipoCobertura.objects.filter(
                nombre__iexact=cob_nombre,
                compania__nombre__iexact=comp
            ).first()

            if es_nre(comp):
                # 🆕 FIX: NRE es trimestral: SIEMPRE 3 cuotas, sin importar la
                # cobertura del catálogo ni el override. Antes esta rama caía
                # en "elif cob_obj" y usaba cob_obj.cuotas_a_generar: si ese
                # campo estaba vacío (None) para la cobertura de NRE, el
                # cálculo de fecha de abajo (_add_months) explotaba con un 500.
                cuotas_final = 3
                vto = p_in.get("primer_vencimiento") or _add_months(emision, 1)
                vto_total = _add_months(emision, cuotas_final)
            elif cupones_norm:
                cuotas_final = len(cupones_norm)
                vto = cupones_norm[0]["fecha"]
                vto_total = cupones_norm[-1]["fecha"]
            elif cob_obj:
                cuotas_final = cob_obj.cuotas_a_generar
                vto = p_in.get("primer_vencimiento") or _add_months(emision, 1)
                vto_total = _add_months(emision, cuotas_final)
            else:
                override_cuotas = p_in.get("cantidad_cuotas_override")
                if override_cuotas is not None:
                    cuotas_final = int(override_cuotas)
                else:
                    cuotas_final = int(get_cuotas_por_compania(comp))
                vto = p_in.get("primer_vencimiento") or _add_months(emision, 1)
                vto_total = _add_months(emision, cuotas_final)

            # 🆕 Precio: lo carga el usuario en el formulario. Para NRE ya NO
            #    se pisa con el cálculo del sistema (lista de precios /
            #    descuento multivehículo) — se dejó de usar acá.
            precio_final = _dec_or_none(p_in.get("precio_cuota"))

            # 🎟️ Cuponera (AMCA/La Equidad): si el operador no cargó precio
            #     (suele quedar en 0/None), usamos el importe del cupón como
            #     precio de cabecera de la póliza, así no queda en $0.
            if not es_nre(comp) and cupones_norm:
                imp_cab = next((cp["importe"] for cp in cupones_norm if cp["importe"] is not None), None)
                if imp_cab is not None and (precio_final is None or precio_final == 0):
                    precio_final = imp_cab

            pol = Poliza.objects.create(
                cliente=cli, compania=comp, numero_poliza=None,
                cobertura=cob_nombre, oficina_id=oficina_id_final,
                patente=(p_in.get("patente") or "").strip().upper(),
                marca=(p_in.get("marca") or "").strip(), modelo=(p_in.get("modelo") or "").strip(),
                anio=p_in.get("anio"), tipo=(p_in.get("tipo") or "Auto"),
                numero_motor=(p_in.get("numero_motor") or "").strip(),
                numero_chasis=(p_in.get("numero_chasis") or "").strip(),
                combustible=(p_in.get("combustible") or "").strip(),
                carroceria=(p_in.get("carroceria") or "").strip(),
                observaciones=(p_in.get("observaciones") or "").strip(),
                precio_cuota=precio_final,
                cantidad_cuotas=cuotas_final, 
                primer_pago=vto, fecha_vencimiento=vto_total, dias_a_vencer=int(dv), fecha_emision=emision,
                fase=getattr(PolizaFase, "DEFINITIVA", "DEFINITIVA"),
            )
            if not pol.numero_poliza:
                pol.numero_poliza = f"SN-{pol.id:07d}"
                pol.save(update_fields=["numero_poliza"])

            if p_in.get("generar_cuotas_ahora", True):
                if cupones_norm:
                    # 🎟️ Cuotas con FECHA e IMPORTE EXACTOS de cada cupón (1 a 1).
                    #     Si algún cupón viniera sin importe, cae al precio de la póliza.
                    objs = [
                        Cuota(
                            poliza=pol, cuota_nro=i + 1,
                            fecha_vencimiento=cp["fecha"],
                            monto=cp["importe"] if cp["importe"] is not None else pol.precio_cuota,
                            pagado=False,
                        )
                        for i, cp in enumerate(cupones_norm)
                    ]
                else:
                    objs = [
                        Cuota(poliza=pol, cuota_nro=i + 1, fecha_vencimiento=_add_months(vto, i),
                              monto=pol.precio_cuota, pagado=False)
                        for i in range(pol.cantidad_cuotas)
                    ]
                Cuota.objects.bulk_create(objs)

        rn = (s_in.get("responsable_nombre") or s_in.get("responsable") or "").strip()
        sol = SolicitudSeguro.objects.create(
            poliza_id=pol.id, motivo=s_in.get("motivo") or MotivoSolicitud.ALTA_POLIZA,
            observaciones=s_in.get("observaciones") or "", prioridad=s_in.get("prioridad") or "NORMAL",
            responsable=rn, responsable_nombre=rn, responsable_empleado=s_in.get("responsable_empleado"),
            cliente_nombre=f"{cli.apellido}, {cli.nombre}".strip(", "), cliente_dni=cli.dni_cuit_cuil,
            telefono=cli.telefono, vehiculo_patente=pol.patente, vehiculo_marca=pol.marca,
            vehiculo_modelo=pol.modelo, vehiculo_anio=pol.anio, cobertura_solicitada=pol.cobertura,
            compania_preferida=pol.compania, oficina_id=oficina_id_final,
        )

        # 🐛 FIX MAGISTRAL — Bug "fotos del vehículo no se guardan en la póliza"
        # ────────────────────────────────────────────────────────────────────
        # Antes usábamos `SolicitudDocumento.objects.bulk_create(docs_objs)`, PERO
        # bulk_create NO dispara la señal post_save en Django (comportamiento documentado).
        # Eso significa que el receiver `solicitudes__replicar_documento_a_poliza`
        # (en signals.py) NUNCA corría durante la creación masiva → las fotos del
        # vehículo nunca se replicaban a polizas.FotoVehiculo.
        #
        # El DNI sí se guardaba porque va por otra rama: setea directo
        # cli.archivo_dni_frente / cli.archivo_dni_dorso sobre el Cliente.
        #
        # Solución: usamos .create() individual (1 query por doc) para que los
        # signals SÍ disparen, y dejamos `_importar_desde_solicitud_hacia_poliza`
        # como red de seguridad (es idempotente: _upsert_foto / _upsert_doc
        # verifican public_id/url+tipo antes de crear).
        creados_count = 0
        fallidos = []
        for src_name, src in [("fotos", f_in), ("documentos", d_in), ("cliente_fotos", cf_in)]:
            for k, v in (src or {}).items():
                if not isinstance(v, dict) or not v.get("url"):
                    continue
                try:
                    SolicitudDocumento.objects.create(
                        solicitud=sol,
                        tipo=str(k).upper().strip(),
                        url=v["url"],
                        public_id=v.get("public_id", "") or "",
                        mime=v.get("mime", "") or "",
                        nombre=v.get("nombre", "") or "",
                        # 🚀 Marca crítica: el signal y el importer leen "ES_FOTO"
                        # para saber que es foto del vehículo (no documento).
                        notas="ES_FOTO" if src_name == "fotos" else "",
                    )
                    creados_count += 1
                except Exception as e:
                    fallidos.append({"src": src_name, "key": k, "error": str(e)})
                    _log("CREAR_COMPLETO_DOC_FAIL", src=src_name, key=k, error=str(e))

        _log("CREAR_COMPLETO_DOCS", creados=creados_count, fallidos=len(fallidos))

        pol.refresh_from_db()
        # Red de seguridad: idempotente, no duplica gracias a los _upsert_*.
        importer_result = _importar_desde_solicitud_hacia_poliza(sol, pol)
        _log("CREAR_COMPLETO_IMPORT", **(importer_result or {}))

        _ensure_cupones_robo_for_poliza(pol)

        return {
            "cliente_id": cli.id,
            "poliza_id": pol.id,
            "solicitud_id": sol.id,
            # Campos opcionales para diagnóstico desde el frontend
            "docs_creados": creados_count,
            "docs_fallidos": fallidos,
            "import_result": importer_result,
        }

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