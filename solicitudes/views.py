# solicitudes/views.py
import logging

from django.utils import timezone
from django.db import IntegrityError

from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from django_filters.rest_framework import DjangoFilterBackend

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


logger = logging.getLogger(__name__)


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
    ordering_fields = ("creado_en", "actualizado_en", "asignado_en")

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

        # 🛡️ Envolvemos el save: si algo revienta a nivel base (IntegrityError,
        #    p.ej. un campo NOT NULL que llegó vacío) devolvemos 400 con el
        #    detalle REAL en JSON, en vez de un 500 con HTML que el front no
        #    puede parsear (mostraba "detalle: undefined").
        try:
            if not is_admin and ofi_id_empleado:
                result = ser.save(oficina_id=ofi_id_empleado)
            else:
                result = ser.save()
        except IntegrityError as e:
            logger.error("[crear_completo] IntegrityError: %s", e, exc_info=True)
            return Response(
                {"detail": "No se pudo crear la solicitud: faltan datos obligatorios "
                           "o hay un valor inválido en la póliza/cliente.",
                 "error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.error("[crear_completo] Error inesperado: %s", e, exc_info=True)
            return Response(
                {"detail": "Error al crear la solicitud.", "error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

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

    @action(detail=False, methods=["get"])
    def counters(self, request):
        qs = self.get_queryset().exclude(estado=EstadoSolicitud.TERMINADA)
        return Response({
            "pendiente_alta": qs.filter(alta_compania=False).count(),
            "pendiente_envio": qs.filter(enviar_poliza=False).count()
        })

    @action(detail=False, methods=["get"])
    def pendientes(self, request):
        tipo = request.query_params.get("tipo", "").lower()
        key = "alta_compania" if "alta" in tipo else "enviar_poliza"
        qs = self.get_queryset().exclude(estado=EstadoSolicitud.TERMINADA).filter(**{f"{key}": False})
        return Response([_build_item_brief(s) for s in qs[:200]])


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