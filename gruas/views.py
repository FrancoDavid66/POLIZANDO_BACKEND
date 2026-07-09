# gruas/views.py
import logging
import re
from urllib.parse import quote

from django.apps import apps
from django.db.models import Q
from django.utils import timezone

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    PlanGrua,
    AdhesionGrua,
    ProveedorGrua,
    SolicitudGrua,
    SolicitudEvento,
)
from .serializers import (
    PlanGruaSerializer,
    AdhesionGruaSerializer,
    PolizaBuscarSerializer,
    ProveedorGruaSerializer,
    SolicitudGruaSerializer,
    SolicitudFotoSerializer,
)

logger = logging.getLogger(__name__)


def _to_bool(raw):
    s = str(raw or "").strip().lower()
    if s in ("1", "true", "t", "yes", "y", "on", "si", "sí"):
        return True
    if s in ("0", "false", "f", "no", "n", "off"):
        return False
    return None


def _digits(s: str) -> str:
    return re.sub(r"\D+", "", str(s or ""))


def _normalize_ar_phone_for_wa(phone: str) -> str:
    """
    Devuelve número para wa.me SIN '+', solo dígitos.
    Heurística AR:
    - limpia a dígitos
    - si empieza con 00 => lo saca
    - si empieza con 0 => lo saca
    - si no empieza con 54 => lo prefija 54
    """
    d = _digits(phone)

    if d.startswith("00"):
        d = d[2:]
    if d.startswith("0"):
        d = d[1:]
    if not d.startswith("54") and len(d) >= 8:
        d = "54" + d
    return d


def _build_solicitud_msg(obj: SolicitudGrua) -> str:
    pol = getattr(obj, "poliza", None)
    cli = getattr(pol, "cliente", None) if pol else None

    cliente_nombre = ""
    cliente_dni = ""
    cliente_tel = ""

    if cli:
        nombre = (getattr(cli, "nombre", "") or "").strip()
        apellido = (getattr(cli, "apellido", "") or "").strip()
        cliente_nombre = f"{apellido} {nombre}".strip()
        cliente_dni = str(getattr(cli, "dni_cuit_cuil", "") or "").strip()
        cliente_tel = str(getattr(cli, "telefono", "") or "").strip()

    patente = (getattr(pol, "patente", "") or "").strip()
    compania = (getattr(pol, "compania", "") or "").strip()
    numero_poliza = (getattr(pol, "numero_poliza", "") or "").strip()
    marca = (getattr(pol, "marca", "") or "").strip()
    modelo = (getattr(pol, "modelo", "") or "").strip()
    anio = getattr(pol, "anio", None)
    vehiculo = " ".join([x for x in [marca, modelo, str(anio or "").strip()] if x])

    motivo = (getattr(obj, "motivo", "") or "").strip()
    notas = (getattr(obj, "notas", "") or "").strip()

    origen_dir = (getattr(obj, "origen_direccion", "") or "").strip()
    destino_dir = (getattr(obj, "destino_direccion", "") or "").strip()

    # ✅ NUEVO: localidades
    origen_loc = (getattr(obj, "origen_localidad", "") or "").strip()
    destino_loc = (getattr(obj, "destino_localidad", "") or "").strip()

    origen_url = (getattr(obj, "origen_maps_url", "") or "").strip()
    destino_url = (getattr(obj, "destino_maps_url", "") or "").strip()
    km = getattr(obj, "km_estimados", None)

    lines = []
    lines.append("🚚 *SOLICITUD DE GRÚA*")
    lines.append(f"ID: {obj.id} | Estado: {obj.estado}")
    if motivo:
        lines.append(f"Motivo: {motivo}")
    if km is not None:
        lines.append(f"KM estimados: {km}")

    lines.append("")
    lines.append("📍 *ORIGEN*")
    if origen_loc:
        lines.append(f"Localidad: {origen_loc}")
    if origen_dir:
        lines.append(f"Dirección: {origen_dir}")
    if origen_url:
        lines.append(origen_url)

    lines.append("")
    lines.append("🏁 *DESTINO*")
    if destino_loc:
        lines.append(f"Localidad: {destino_loc}")
    if destino_dir:
        lines.append(f"Dirección: {destino_dir}")
    if destino_url:
        lines.append(destino_url)

    lines.append("")
    lines.append("👤 *CLIENTE*")
    if cliente_nombre:
        lines.append(cliente_nombre)
    if cliente_dni:
        lines.append(f"DNI/CUIT: {cliente_dni}")
    if cliente_tel:
        lines.append(f"Tel: {cliente_tel}")

    lines.append("")
    lines.append("🚗 *VEHÍCULO / PÓLIZA*")
    if patente:
        lines.append(f"Patente: {patente}")
    if vehiculo:
        lines.append(f"Vehículo: {vehiculo}")
    if compania or numero_poliza:
        lines.append(f"Póliza: {compania} {numero_poliza}".strip())

    if notas:
        lines.append("")
        lines.append("📝 Notas:")
        lines.append(notas)

    return "\n".join([x for x in lines if x is not None])


class PlanGruaViewSet(viewsets.ModelViewSet):
    queryset = PlanGrua.objects.all().order_by("-id")
    serializer_class = PlanGruaSerializer
    permission_classes = [AllowAny]

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        q = (request.query_params.get("q") or "").strip()
        activo = _to_bool(request.query_params.get("activo"))

        if activo is not None:
            qs = qs.filter(activo=activo)
        if q:
            qs = qs.filter(nombre__icontains=q)

        page = self.paginate_queryset(qs)
        if page is not None:
            ser = self.get_serializer(page, many=True)
            return self.get_paginated_response(ser.data)

        ser = self.get_serializer(qs, many=True)
        return Response(ser.data)


class ProveedorGruaViewSet(viewsets.ModelViewSet):
    queryset = ProveedorGrua.objects.all().order_by("-id")
    serializer_class = ProveedorGruaSerializer
    permission_classes = [AllowAny]

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        q = (request.query_params.get("q") or "").strip()
        activo = _to_bool(request.query_params.get("activo"))

        if activo is not None:
            qs = qs.filter(activo=activo)

        if q:
            qs = qs.filter(
                Q(nombre__icontains=q)
                | Q(patente_camion__icontains=q)
                | Q(modelo_camion__icontains=q)
                | Q(anio_camion__icontains=q)
                | Q(telefono__icontains=q)
            )

        page = self.paginate_queryset(qs)
        if page is not None:
            ser = self.get_serializer(page, many=True)
            return self.get_paginated_response(ser.data)

        ser = self.get_serializer(qs, many=True)
        return Response(ser.data)


class AdhesionGruaViewSet(viewsets.ModelViewSet):
    queryset = (
        AdhesionGrua.objects.select_related("plan", "poliza", "poliza__cliente")
        .all()
        .order_by("-id")
    )
    serializer_class = AdhesionGruaSerializer
    permission_classes = [AllowAny]

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        q = (request.query_params.get("q") or "").strip()
        estado = (request.query_params.get("estado") or "").strip().upper()

        if estado and estado != "TODAS":
            qs = qs.filter(estado=estado)

        if q:
            qs = qs.filter(
                Q(poliza__patente__icontains=q)
                | Q(poliza__compania__icontains=q)
                | Q(poliza__numero_poliza__icontains=q)
                | Q(poliza__cliente__nombre__icontains=q)
                | Q(poliza__cliente__apellido__icontains=q)
                | Q(poliza__cliente__dni_cuit_cuil__icontains=q)
            )

        page = self.paginate_queryset(qs)
        if page is not None:
            ser = self.get_serializer(page, many=True)
            return self.get_paginated_response(ser.data)

        ser = self.get_serializer(qs, many=True)
        return Response(ser.data)

    @action(detail=True, methods=["post"], url_path="cancelar")
    def cancelar(self, request, pk=None):
        obj = self.get_object()
        if obj.estado == "CANCELADA":
            return Response({"detail": "Ya está cancelada."}, status=status.HTTP_200_OK)

        motivo = (request.data.get("motivo") or "").strip()
        obj.estado = "CANCELADA"
        obj.motivo_cancelacion = motivo
        obj.cancelada_en = timezone.now()
        obj.save(update_fields=["estado", "motivo_cancelacion", "cancelada_en", "actualizado_en"])
        return Response(self.get_serializer(obj).data, status=status.HTTP_200_OK)


class PolizasBuscarAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        Poliza = apps.get_model("polizas", "Poliza")
        q = (request.query_params.get("q") or "").strip()
        if not q or len(q) < 2:
            return Response({"results": []})

        qs = Poliza.objects.select_related("cliente").all().order_by("-id")
        qs = qs.filter(
            Q(patente__icontains=q)
            | Q(compania__icontains=q)
            | Q(numero_poliza__icontains=q)
            | Q(cliente__nombre__icontains=q)
            | Q(cliente__apellido__icontains=q)
            | Q(cliente__dni_cuit_cuil__icontains=q)
        )[:30]

        results = [PolizaBuscarSerializer.from_poliza(p) for p in qs]
        return Response({"results": results})


class PolizasAdheridasBuscarAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        Poliza = apps.get_model("polizas", "Poliza")
        q = (request.query_params.get("q") or "").strip()
        if not q or len(q) < 2:
            return Response({"results": []})

        qs = (
            Poliza.objects.select_related("cliente")
            .filter(adhesiones_grua__estado="ACTIVA")
            .distinct()
            .order_by("-id")
        )

        qs = qs.filter(
            Q(patente__icontains=q)
            | Q(compania__icontains=q)
            | Q(numero_poliza__icontains=q)
            | Q(cliente__nombre__icontains=q)
            | Q(cliente__apellido__icontains=q)
            | Q(cliente__dni_cuit_cuil__icontains=q)
        )[:30]

        poliza_ids = [p.id for p in qs]
        adh_map = {
            a["poliza_id"]: a["id"]
            for a in (
                AdhesionGrua.objects.filter(poliza_id__in=poliza_ids, estado="ACTIVA")
                .order_by("poliza_id", "-id")
                .values("id", "poliza_id")
            )
        }

        results = []
        for p in qs:
            d = PolizaBuscarSerializer.from_poliza(p)
            d["adhesion_id"] = adh_map.get(p.id)
            results.append(d)

        return Response({"results": results})


class SolicitudGruaViewSet(viewsets.ModelViewSet):
    queryset = (
        SolicitudGrua.objects.select_related(
            "adhesion",
            "poliza",
            "poliza__cliente",
            "proveedor",
        )
        .prefetch_related("fotos", "eventos")
        .all()
        .order_by("-id")
    )
    serializer_class = SolicitudGruaSerializer
    permission_classes = [AllowAny]

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()

        q = (request.query_params.get("q") or "").strip()
        estado = (request.query_params.get("estado") or "").strip().upper()
        proveedor_id = (request.query_params.get("proveedor") or "").strip()

        if estado and estado != "TODAS":
            qs = qs.filter(estado=estado)

        if proveedor_id:
            try:
                qs = qs.filter(proveedor_id=int(proveedor_id))
            except Exception:
                pass

        if q:
            qs = qs.filter(
                Q(poliza__patente__icontains=q)
                | Q(poliza__compania__icontains=q)
                | Q(poliza__numero_poliza__icontains=q)
                | Q(poliza__cliente__nombre__icontains=q)
                | Q(poliza__cliente__apellido__icontains=q)
                | Q(poliza__cliente__dni_cuit_cuil__icontains=q)
                | Q(motivo__icontains=q)
                | Q(origen_direccion__icontains=q)
                | Q(origen_localidad__icontains=q)   # ✅ NUEVO
                | Q(destino_direccion__icontains=q)
                | Q(destino_localidad__icontains=q)  # ✅ NUEVO
            )

        page = self.paginate_queryset(qs)
        if page is not None:
            ser = self.get_serializer(page, many=True)
            return self.get_paginated_response(ser.data)

        ser = self.get_serializer(qs, many=True)
        return Response(ser.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        obj = serializer.save()

        if getattr(obj, "proveedor_id", None) and obj.estado == "ABIERTA":
            obj.estado = "ASIGNADA"
            obj.asignada_en = timezone.now()
            obj.save(update_fields=["estado", "asignada_en", "actualizado_en"])
            SolicitudEvento.objects.create(
                solicitud=obj,
                tipo="ASIGNADA",
                detalle="Proveedor asignado al crear",
            )

    @action(detail=True, methods=["post"], url_path="asignar_proveedor")
    def asignar_proveedor(self, request, pk=None):
        obj = self.get_object()

        raw_pid = request.data.get("proveedor_id", None)
        if raw_pid in (None, "", 0, "0"):
            raw_pid = request.data.get("proveedor", None)

        try:
            pid = int(raw_pid)
        except Exception:
            return Response({"detail": "proveedor_id inválido."}, status=status.HTTP_400_BAD_REQUEST)

        proveedor = ProveedorGrua.objects.filter(id=pid).first()
        if not proveedor:
            return Response({"detail": "Proveedor no encontrado."}, status=status.HTTP_404_NOT_FOUND)

        obj.proveedor = proveedor

        just_assigned = False
        if (obj.estado or "").upper() == "ABIERTA":
            obj.estado = "ASIGNADA"
            obj.asignada_en = timezone.now()
            just_assigned = True

        update_fields = ["proveedor", "actualizado_en"]
        if just_assigned:
            update_fields += ["estado", "asignada_en"]

        obj.save(update_fields=update_fields)

        SolicitudEvento.objects.create(
            solicitud=obj,
            tipo="ASIGNADA" if just_assigned else "PROVEEDOR",
            detalle=f"Proveedor asignado (id={proveedor.id})",
        )

        return Response(self.get_serializer(obj).data, status=status.HTTP_200_OK)

    # ✅ Enviar info al proveedor (devuelve wa_url para abrir desde front)
    @action(detail=True, methods=["post"], url_path="enviar_proveedor")
    def enviar_proveedor(self, request, pk=None):
        obj = self.get_object()

        if not obj.proveedor_id:
            return Response({"detail": "La solicitud no tiene proveedor asignado."}, status=status.HTTP_400_BAD_REQUEST)

        proveedor = obj.proveedor
        tel = (getattr(proveedor, "telefono", "") or "").strip()
        tel_wa = _normalize_ar_phone_for_wa(tel)

        if not tel_wa or len(tel_wa) < 10:
            return Response({"detail": "El proveedor no tiene teléfono válido para WhatsApp."}, status=status.HTTP_400_BAD_REQUEST)

        extra = (request.data.get("mensaje") or "").strip()
        base_msg = _build_solicitud_msg(obj)
        msg = base_msg + (("\n\n" + extra) if extra else "")

        wa_url = f"https://wa.me/{tel_wa}?text={quote(msg)}"

        SolicitudEvento.objects.create(
            solicitud=obj,
            tipo="ENVIADA_PROVEEDOR",
            detalle=f"WhatsApp generado a proveedor_id={proveedor.id} tel={tel_wa}",
        )

        return Response(
            {
                "ok": True,
                "solicitud_id": obj.id,
                "proveedor_id": proveedor.id,
                "telefono": tel,
                "telefono_wa": tel_wa,
                "wa_url": wa_url,
                "mensaje": msg,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get", "post", "delete"], url_path="fotos")
    def fotos(self, request, pk=None):
        obj = self.get_object()

        if request.method == "GET":
            fotos = obj.fotos.all().order_by("id")
            ser = SolicitudFotoSerializer(fotos, many=True)
            return Response({"results": ser.data})

        if request.method == "DELETE":
            foto_id = request.query_params.get("foto_id")
            if not foto_id:
                return Response({"detail": "Falta foto_id."}, status=status.HTTP_400_BAD_REQUEST)
            try:
                foto_id = int(foto_id)
            except Exception:
                return Response({"detail": "foto_id inválido."}, status=status.HTTP_400_BAD_REQUEST)

            foto = obj.fotos.filter(id=foto_id).first()
            if not foto:
                return Response({"detail": "Foto no encontrada."}, status=status.HTTP_404_NOT_FOUND)

            foto.delete()
            SolicitudEvento.objects.create(
                solicitud=obj,
                tipo="FOTO_BORRADA",
                detalle=f"Foto borrada (id={foto_id})",
            )
            return Response({"detail": "OK"}, status=status.HTTP_200_OK)

        ser = SolicitudFotoSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        foto = ser.save(solicitud=obj)

        SolicitudEvento.objects.create(
            solicitud=obj,
            tipo="FOTO",
            detalle=f"Foto agregada ({foto.tipo})",
        )

        return Response(SolicitudFotoSerializer(foto).data, status=status.HTTP_201_CREATED)
