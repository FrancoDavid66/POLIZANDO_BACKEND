# solicitudes/views.py
import io
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from django.http import HttpResponse
from django.db.models import Q, Case, When, IntegerField, Sum

from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from django_filters.rest_framework import DjangoFilterBackend

from PIL import Image, ImageDraw, ImageFont
import qrcode

from .models import (
    SolicitudSeguro,
    SolicitudDocumento,
    EstadoSolicitud,
    Empleado,
    TipoDocSolicitud,
)
from .serializers import (
    SolicitudSeguroSerializer,
    SolicitudDocumentoSerializer,
    EmpleadoSerializer,
    CrearCompletoSerializer,
    SolicitudAsociarPolizaSerializer,
)

from polizas.models import Poliza, PolizaDocumento

try:
    from clientes.models import Cliente
except Exception:  # pragma: no cover
    Cliente = None


CLIENTE_TIPO_TO_FLAG = {}
if hasattr(TipoDocSolicitud, "DNI_FRENTE"):
    CLIENTE_TIPO_TO_FLAG[TipoDocSolicitud.DNI_FRENTE] = "dni_frente"
if hasattr(TipoDocSolicitud, "DNI_DORSO"):
    CLIENTE_TIPO_TO_FLAG[TipoDocSolicitud.DNI_DORSO] = "dni_dorso"
if hasattr(TipoDocSolicitud, "PASAPORTE_FRENTE"):
    CLIENTE_TIPO_TO_FLAG[TipoDocSolicitud.PASAPORTE_FRENTE] = "pasaporte_frente"
if hasattr(TipoDocSolicitud, "PASAPORTE_DORSO"):
    CLIENTE_TIPO_TO_FLAG[TipoDocSolicitud.PASAPORTE_DORSO] = "pasaporte_dorso"

CLIENTE_DOC_FIELDS = {
    "dni_frente": "archivo_dni_frente",
    "dni_dorso": "archivo_dni_dorso",
    "pasaporte_frente": "archivo_pasaporte_frente",
    "pasaporte_dorso": "archivo_pasaporte_dorso",
}

RETENCION_TERMINADA_DIAS = 7


def _tarea_flag(s, key: str) -> bool:
    if hasattr(s, key):
        return bool(getattr(s, key))
    tareas = getattr(s, "tareas", None)
    if isinstance(tareas, dict):
        return bool(tareas.get(key))
    return False


def _build_item_brief(s):
    title = f"{getattr(s, 'cliente_nombre', 'Cliente')} – {getattr(s, 'vehiculo_patente', '') or ''}".strip()
    comp = getattr(s, "compania_preferida", None) or getattr(s, "compania", None) or ""
    cov = getattr(s, "cobertura_solicitada", None) or ""
    subtitle = " · ".join([x for x in [comp, cov] if x]) or "Solicitud sin detalle"
    return {
        "id": s.id,
        "title": title,
        "subtitle": subtitle,
        "action_url": f"/solicitudes?tab=proceso#{s.id}",
    }


def _map_tipo_solicitud_a_poliza(s_tipo: str):
    t = str(s_tipo or "").upper()
    if not t:
        return None
    if "REGISTRO" in t or "LICENCIA" in t:
        return "REGISTRO_CONDUCIR"
    if "CEDULA" in t and "VERDE" in t:
        return "CEDULA_VERDE"
    if "CEDULA" in t and "AZUL" in t:
        return "CEDULA_AZUL"
    return None


_SOLICITUD_FIELDS = {f.name for f in SolicitudSeguro._meta.get_fields()}
_HAS_ALTA_COMPANIA = "alta_compania" in _SOLICITUD_FIELDS
_HAS_ENVIAR_POLIZA = "enviar_poliza" in _SOLICITUD_FIELDS


def _expire_constancias():
    """1 query. Llamar solo en endpoints 'livianos' (resumen/counters/pendientes), no en cada request."""
    now_ = timezone.now()
    SolicitudSeguro.objects.filter(
        estado=EstadoSolicitud.VIGENTE_24H,
        fin__isnull=False,
        fin__lte=now_,
    ).update(estado=EstadoSolicitud.VENCIDA)


class SolicitudSeguroViewSet(viewsets.ModelViewSet):
    queryset = SolicitudSeguro.objects.all().order_by("-creado_en")
    serializer_class = SolicitudSeguroSerializer

    # 🔧 BLOQUEAMOS EL ACCESO LIBRE (Solo usuarios logueados) — antes no estaba
    # explícito acá y dependía solo del chequeo manual en get_queryset(), que
    # no cubre create()/update() y podía terminar en un 500 feo en vez de un
    # 401 limpio para un usuario anónimo.
    permission_classes = [IsAuthenticated]

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ("estado", "cliente_dni", "vehiculo_patente", "responsable", "responsable_empleado", "responsable_nombre")
    search_fields = ("cliente_nombre", "cliente_dni", "vehiculo_patente", "codigo", "responsable", "responsable_nombre")
    ordering_fields = ("creado_en", "actualizado_en", "asignado_en", "fin")

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        
        if not user.is_authenticated:
            return qs.none()

        is_admin = user.is_superuser or getattr(user.perfil, 'rol', '') == 'ADMIN'
        
        if not is_admin:
            ofi_id = getattr(user.perfil, 'oficina_id', None)
            if ofi_id:
                qs = qs.filter(oficina_id=ofi_id)
                
        qs = qs.select_related("responsable_empleado")
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        is_admin = user.is_superuser or getattr(user.perfil, 'rol', '') == 'ADMIN'
        
        if is_admin:
            oficina_id = self.request.data.get('oficina')
            serializer.save(oficina_id=oficina_id)
        else:
            ofi_id = getattr(user.perfil, 'oficina_id', None)
            serializer.save(oficina_id=ofi_id)

    @action(detail=False, methods=["post"], url_path="crear-completo")
    def crear_completo(self, request):
        user = request.user
        is_admin = user.is_superuser or getattr(user.perfil, 'rol', '') == 'ADMIN'
        
        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
        
        ofi_id_empleado = None
        if not is_admin:
            ofi_id_empleado = getattr(user.perfil, 'oficina_id', None)
            if ofi_id_empleado:
                data['oficina'] = ofi_id_empleado
        
        ser = CrearCompletoSerializer(data=data, context={'request': request})
        ser.is_valid(raise_exception=True)
        
        if not is_admin and ofi_id_empleado:
            result = ser.save(oficina_id=ofi_id_empleado)
        else:
            result = ser.save()
            
        return Response(result, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def terminar(self, request, pk=None):
        s: SolicitudSeguro = self.get_object()
        if s.estado != EstadoSolicitud.TERMINADA:
            s.estado = EstadoSolicitud.TERMINADA
            s.terminada_en = timezone.now()
            s.save(update_fields=["estado", "terminada_en"])
        return Response(self.get_serializer(s).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="marcar_tarea")
    def marcar_tarea(self, request, pk=None):
        s: SolicitudSeguro = self.get_object()
        key_in = str(request.data.get("key", "")).strip().lower()
        done = bool(request.data.get("done", True))

        alias = {
            "alta": "alta_compania",
            "pendiente_alta": "alta_compania",
            "envio": "enviar_poliza",
            "pendiente_envio": "enviar_poliza",
            "enviar_poliza": "enviar_poliza",
            "alta_compania": "alta_compania",
        }
        key = alias.get(key_in)
        if key not in ("alta_compania", "enviar_poliza"):
            return Response({"detail": "Key inválida."}, status=status.HTTP_400_BAD_REQUEST)

        if hasattr(s, key):
            setattr(s, key, done)
            s.save(update_fields=[key])

        tareas = getattr(s, "tareas", None)
        if isinstance(tareas, dict):
            tareas[key] = done
            try:
                s.tareas = tareas
                s.save(update_fields=["tareas"])
            except Exception:
                pass

        data = self.get_serializer(s).data
        data["tareas"] = {
            "alta_compania": _tarea_flag(s, "alta_compania"),
            "enviar_poliza": _tarea_flag(s, "enviar_poliza"),
        }
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def asociar_a_poliza(self, request, pk=None):
        s: SolicitudSeguro = self.get_object()
        docs = list(s.documentos.all().order_by("id"))
        data_in = {"solicitud_id": s.id, **request.data}
        ser_in = SolicitudAsociarPolizaSerializer(data=data_in)
        ser_in.is_valid(raise_exception=True)
        resumen = ser_in.save()

        importar_documentos = request.data.get("importar_documentos", True)
        documentos_importados_backend = []
        if importar_documentos:
            try:
                poliza = Poliza.objects.get(id=resumen["poliza_id"])
            except Poliza.DoesNotExist:
                poliza = None

            if poliza is not None:
                existentes = set(
                    f"{(pd.get('tipo') or '').upper()}|{pd.get('url') or ''}"
                    for pd in PolizaDocumento.objects.filter(poliza_id=poliza.id).values("tipo", "url")
                )
                for d in docs:
                    target_tipo = _map_tipo_solicitud_a_poliza(getattr(d, "tipo", None))
                    if not target_tipo: continue
                    url = getattr(d, "url", "") or ""
                    if not url: continue
                    key = f"{target_tipo}|{url}"
                    if key in existentes: continue
                    
                    item = PolizaDocumento.objects.create(
                        poliza=poliza, tipo=target_tipo, url=url,
                        public_id=getattr(d, "public_id", ""),
                        nombre=(getattr(d, "nombre", "") or target_tipo).strip(),
                        mime=getattr(d, "mime", ""), vencimiento=getattr(d, "vencimiento", None),
                        notas=getattr(d, "notas", ""),
                    )
                    existentes.add(key)
                    documentos_importados_backend.append({"id": item.id, "tipo": item.tipo, "url": item.url})

        cliente_actualizado = False
        if bool(request.data.get("copiar_docs_cliente", False)):
            if Cliente is None:
                return Response(
                    {"detail": "App 'clientes' no disponible para copiar documentación.", "resumen": resumen},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            flags = request.data.get("cliente") or {}
            wants = {
                "dni_frente": bool(flags.get("dni_frente")),
                "dni_dorso": bool(flags.get("dni_dorso")),
                "pasaporte_frente": bool(flags.get("pasaporte_frente")),
                "pasaporte_dorso": bool(flags.get("pasaporte_dorso")),
            }

            try:
                poliza = Poliza.objects.select_related("cliente").get(id=resumen["poliza_id"])
            except Poliza.DoesNotExist:
                poliza = None

            cli = None
            explicit_id = request.data.get("cliente_id")
            if explicit_id and Cliente:
                try:
                    cli = Cliente.objects.get(id=explicit_id)
                except Cliente.DoesNotExist:
                    pass
            if not cli and poliza is not None:
                cli = getattr(poliza, "cliente", None)

            if cli is not None and any(wants.values()):
                first = {k: None for k in CLIENTE_DOC_FIELDS.keys()}
                for d in docs:
                    flag = CLIENTE_TIPO_TO_FLAG.get(getattr(d, "tipo", None))
                    if not flag or not wants.get(flag) or first[flag] is not None:
                        continue
                    first[flag] = getattr(d, "url", None)

                changed = []
                for flag_key, model_field in CLIENTE_DOC_FIELDS.items():
                    url_val = first.get(flag_key)
                    if url_val and hasattr(cli, model_field) and getattr(cli, model_field) != url_val:
                        setattr(cli, model_field, url_val)
                        changed.append(model_field)
                if changed:
                    cli.save(update_fields=changed)
                    cliente_actualizado = True

        return Response({
            "ok": True, "solicitud_id": resumen.get("solicitud_id"), "poliza_id": resumen.get("poliza_id"),
            "documentos_importados_backend": documentos_importados_backend,
            "cliente_actualizado": cliente_actualizado,
        })

    @action(detail=True, methods=["post"])
    def tomar(self, request, pk=None):
        s: SolicitudSeguro = self.get_object()
        empleado_id = request.data.get("empleado_id")
        if empleado_id:
            try:
                empleado = Empleado.objects.filter(activo=True).get(id=empleado_id)
                s.tomar(empleado.nombre)
                s.responsable_empleado = empleado
            except Empleado.DoesNotExist:
                return Response({"detail": "Empleado no disponible."}, status=400)
        else:
            nombre = (request.data.get("responsable") or "").strip()
            if not nombre: return Response({"detail": "Responsable requerido."}, status=400)
            s.tomar(nombre)
        
        s.save(update_fields=["responsable", "responsable_nombre", "responsable_empleado", "asignado_en"])
        return Response(self.get_serializer(s).data)

    @action(detail=True, methods=["post"])
    def reasignar(self, request, pk=None):
        s: SolicitudSeguro = self.get_object()
        nombre = (request.data.get("responsable") or "").strip()
        if not nombre: return Response({"detail": "Nombre requerido."}, status=400)
        s.reasignar(nombre)
        s.save()
        return Response(self.get_serializer(s).data)

    @action(detail=True, methods=["post"])
    def enviar(self, request, pk=None):
        s: SolicitudSeguro = self.get_object()
        faltantes = []
        if not getattr(s, "telefono", None):
            faltantes.append("telefono")
        if not getattr(s, "cliente_nombre", None):
            faltantes.append("cliente_nombre")
        if not getattr(s, "cobertura_solicitada", None):
            faltantes.append("cobertura_solicitada")
        if faltantes:
            return Response({"detail": f"Faltan campos requeridos: {', '.join(faltantes)}"}, status=status.HTTP_400_BAD_REQUEST)

        if s.estado in (EstadoSolicitud.EN_REVISION, EstadoSolicitud.CONVERTIDA, EstadoSolicitud.CANCELADA, EstadoSolicitud.VENCIDA):
            data = self.get_serializer(s).data
            return Response({"detail": "La solicitud ya fue enviada/procesada.", "solicitud": data}, status=status.HTTP_200_OK)

        s.estado = EstadoSolicitud.EN_REVISION
        s.save(update_fields=["estado"])
        return Response(self.get_serializer(s).data)

    @action(detail=True, methods=["post"])
    def emitir_constancia(self, request, pk=None):
        base_verify_url = request.data.get("base_verify_url") or getattr(settings, "PUBLIC_VERIFY_URL", "/public/solicitudes")
        s: SolicitudSeguro = self.get_object()
        s.emitir_constancia_24h(base_verify_url=base_verify_url)
        s.save()
        return Response(self.get_serializer(s).data)

    @action(detail=True, methods=["post"])
    def cancelar(self, request, pk=None):
        s: SolicitudSeguro = self.get_object()
        s.estado = EstadoSolicitud.CANCELADA
        s.save(update_fields=["estado"])
        return Response(self.get_serializer(s).data)

    @action(detail=True, methods=["post"])
    def convertir(self, request, pk=None):
        s: SolicitudSeguro = self.get_object()
        s.estado = EstadoSolicitud.CONVERTIDA
        if request.data.get("poliza_id"): s.poliza_id = request.data.get("poliza_id")
        s.save()
        return Response(self.get_serializer(s).data)

    @action(detail=False, methods=["get"])
    def resumen(self, request):
        _expire_constancias()
        ahora = timezone.now()
        qs = self.get_queryset()
        agg = qs.aggregate(
            total=Sum(Case(When(id__isnull=False, then=1), output_field=IntegerField())),
            borrador_o_revision=Sum(Case(When(estado__in=[EstadoSolicitud.BORRADOR, EstadoSolicitud.EN_REVISION], then=1), default=0, output_field=IntegerField())),
            vigentes_24h=Sum(Case(When(estado=EstadoSolicitud.VIGENTE_24H, fin__gt=ahora, then=1), default=0, output_field=IntegerField())),
            vencidas=Sum(Case(When(estado=EstadoSolicitud.VENCIDA, then=1), When(estado=EstadoSolicitud.VIGENTE_24H, fin__lte=ahora, then=1), default=0, output_field=IntegerField())),
            convertidas=Sum(Case(When(estado=EstadoSolicitud.CONVERTIDA, then=1), default=0, output_field=IntegerField())),
        )
        return Response({
            "por_asegurar": (int(agg.get('borrador_o_revision') or 0) + int(agg.get('vigentes_24h') or 0)),
            "vigentes_24h": int(agg.get('vigentes_24h') or 0),
            "vencidas": int(agg.get('vencidas') or 0),
            "convertidas": int(agg.get('convertidas') or 0),
            "total": int(agg.get('total') or 0),
        })

    @action(detail=False, methods=["get"])
    def counters(self, request):
        _expire_constancias()
        qs = self.get_queryset().exclude(estado=EstadoSolicitud.TERMINADA)
        return Response({
            "pendiente_alta": qs.filter(alta_compania=False).count(),
            "pendiente_envio": qs.filter(enviar_poliza=False).count()
        })

    @action(detail=False, methods=["get"])
    def pendientes(self, request):
        _expire_constancias()
        tipo = request.query_params.get("tipo", "").lower()
        key = "alta_compania" if "alta" in tipo else "enviar_poliza"
        qs = self.get_queryset().exclude(estado=EstadoSolicitud.TERMINADA).filter(**{f"{key}": False})
        return Response([_build_item_brief(s) for s in qs[:200]])

    @action(detail=True, methods=["get"])
    def comprobante_png(self, request, pk=None):
        s: SolicitudSeguro = self.get_object()
        if s.estado not in (EstadoSolicitud.VIGENTE_24H, EstadoSolicitud.VENCIDA, EstadoSolicitud.CONVERTIDA):
            base_verify_url = getattr(settings, "PUBLIC_VERIFY_URL", "/public/solicitudes")
            s.emitir_constancia_24h(base_verify_url=base_verify_url)
            s.save()

        W, H = 1240, 1754
        img = Image.new("RGB", (W, H), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        # 🔧 Banner con marca de Polizando (antes decía "Estudio Thames" en dorado).
        #    Verde primario #1F7A4C = (31, 122, 76); texto en crema #F4EFE6 = (244, 239, 230).
        draw.rectangle([0, 0, W, 160], fill=(31, 122, 76))
        draw.text((60, 60), "Polizando", fill=(244, 239, 230))
        
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        resp = HttpResponse(buf.read(), content_type="image/png")
        resp["Content-Disposition"] = f'attachment; filename="constancia_{s.codigo}.png"'
        return resp


class SolicitudDocumentoViewSet(viewsets.ModelViewSet):
    queryset = SolicitudDocumento.objects.all().order_by("-creado_en")
    serializer_class = SolicitudDocumentoSerializer
    permission_classes = [IsAuthenticated]  # 🔧 igual que arriba: antes no estaba explícito
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ("solicitud", "tipo")
    search_fields = ("nombre", "public_id")
    ordering_fields = ("creado_en", "tipo")

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.is_authenticated:
            return qs.none()
        is_admin = user.is_superuser or getattr(user.perfil, 'rol', '') == 'ADMIN'
        if not is_admin:
            ofi_id = getattr(user.perfil, 'oficina_id', None)
            if ofi_id:
                qs = qs.filter(solicitud__oficina_id=ofi_id)
        return qs


# 🚀 EMPLEADOS (RESPONSABLES) BLINDADOS DE FORMA SEGURA
class EmpleadoViewSet(viewsets.ModelViewSet):
    queryset = Empleado.objects.select_related('oficina').all().order_by("nombre")
    serializer_class = EmpleadoSerializer
    permission_classes = [IsAuthenticated]  # 🔧 igual que arriba: antes no estaba explícito

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ("activo", "oficina")
    search_fields = ("nombre",)
    ordering_fields = ("nombre", "creado_en", "actualizado_en")

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        
        if not user.is_authenticated:
            return qs.none()
            
        # 🚀 CORRECCIÓN CLAVE: Verificación segura usando "hasattr"
        is_admin = user.is_superuser or (hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN')
        
        if not is_admin:
            ofi_id = user.perfil.oficina_id if hasattr(user, 'perfil') else None
            if ofi_id:
                qs = qs.filter(oficina_id=ofi_id)
                
        return qs

    @action(detail=False, methods=["get"])
    def activos(self, request):
        qs = self.get_queryset().filter(activo=True)
        return Response(self.get_serializer(qs, many=True).data)

    @action(detail=True, methods=["post"])
    def activar(self, request, pk=None):
        emp: Empleado = self.get_object()
        emp.activo = True
        emp.save(update_fields=["activo", "actualizado_en"])
        return Response(self.get_serializer(emp).data)

    @action(detail=True, methods=["post"])
    def desactivar(self, request, pk=None):
        emp: Empleado = self.get_object()
        emp.activo = False
        emp.save(update_fields=["activo", "actualizado_en"])
        return Response(self.get_serializer(emp).data)