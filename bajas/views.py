# bajas/views.py

import logging
from datetime import timedelta
import csv
from django.http import HttpResponse

from rest_framework import viewsets, status, filters, serializers
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from django.db.models import Q, Count, Min, Max, OuterRef, Subquery, Exists
from django.utils import timezone

from seguros_project.pagination import LargeResultsSetPagination
from polizas.models import Poliza

from bajas.models import BajaPoliza, CorreoCompaniaBaja, HistorialBajaPoliza
from bajas.services import (
    construir_digest,
    enviar_digest_compania,
    enviar_todas_del_dia,
)
from polizas.utils.viewtools import hist_log as _hist_log

logger = logging.getLogger(__name__)


def _to_bool(v):
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"1", "true", "t", "yes", "y", "on", "si", "sí"}


def _ofi_str(ofi):
    """Nombre legible de una oficina (nombre → código → str), o None/— si no hay."""
    if not ofi:
        return None
    return getattr(ofi, "nombre", None) or getattr(ofi, "codigo", None) or str(ofi)


def _mora_dias(poliza, hoy):
    """Días de mora desde la PRIMERA cuota impaga (min_vto_impaga). 0 si no hay."""
    min_vto = getattr(poliza, "min_vto_impaga", None)
    return (hoy - min_vto).days if min_vto else 0


def _asegurado_apellido_nombre(cli):
    """'Apellido Nombre' del cliente, o '' si no hay."""
    if not cli:
        return ""
    return f"{getattr(cli, 'apellido', '') or ''} {getattr(cli, 'nombre', '') or ''}".strip()


# ─── Correos ABM ─────────────────────────────────────────────────────────────

class CorreoCompaniaBajaSerializer(serializers.ModelSerializer):
    class Meta:
        model  = CorreoCompaniaBaja
        fields = ["id", "compania", "email", "dias_gracia"]


class CorreoCompaniaBajaViewSet(viewsets.ModelViewSet):
    """
    CRUD para administrar correos por compañía.
    Endpoint: /api/bajas/correos/
    """
    queryset           = CorreoCompaniaBaja.objects.all().order_by("compania")
    serializer_class   = CorreoCompaniaBajaSerializer
    permission_classes = [IsAuthenticated]
    pagination_class   = None
    filter_backends    = [filters.SearchFilter]
    search_fields      = ["compania", "email"]


# ─── Serializers de bajas ────────────────────────────────────────────────────

class BajaPolizaListSerializer(serializers.Serializer):
    id             = serializers.IntegerField()
    numero_poliza  = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    patente        = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    compania       = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    oficina        = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    estado         = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    fase           = serializers.CharField(allow_blank=True, allow_null=True, required=False)

    cliente_id       = serializers.IntegerField(required=False, allow_null=True)
    cliente_nombre   = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    cliente_apellido = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    cliente_dni      = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    cliente_telefono = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    impagas_count  = serializers.IntegerField(required=False)
    cuotas_impagas = serializers.IntegerField(required=False)
    min_vto_impaga = serializers.DateField(required=False, allow_null=True)
    max_vto_impaga = serializers.DateField(required=False, allow_null=True)
    mora_dias      = serializers.IntegerField(required=False)

    baja_estado        = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    baja_email_destino = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    baja_notas         = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    baja_enviada_en    = serializers.DateTimeField(required=False, allow_null=True)
    baja_realizada_en  = serializers.DateTimeField(required=False, allow_null=True)


class BajaEstadoUpdateSerializer(serializers.Serializer):
    estado         = serializers.ChoiceField(choices=["PENDIENTE_ENVIO", "ENVIADA", "REALIZADA"])
    email_destino  = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    notas          = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    cancelar_poliza = serializers.BooleanField(required=False)


# ─── ViewSet principal de bajas ───────────────────────────────────────────────

class BajaPolizaViewSet(viewsets.GenericViewSet):
    """
    ViewSet operativo para gestión de bajas.
    Base URL: /api/bajas/operativo/
    """
    permission_classes = [IsAuthenticated]
    pagination_class   = LargeResultsSetPagination

    filter_backends  = [filters.SearchFilter, filters.OrderingFilter]
    search_fields    = [
        "patente", "marca", "modelo", "numero_poliza",
        "compania", "oficina",
        "cliente__nombre", "cliente__apellido",
        "cliente__dni_cuit_cuil", "cliente__telefono",
    ]
    ordering_fields = [
        "id", "min_vto_impaga", "impagas_count",
        "fecha_vencimiento", "patente", "compania", "oficina",
    ]
    ordering = ["min_vto_impaga", "id"]

    # ─── Queryset base ────────────────────────────────────────────────────────

    def _base_queryset(self):
        params = self.request.query_params
        hoy    = timezone.localdate()

        dias   = int(params.get("dias") or 4)
        limite = hoy - timedelta(days=dias)

        incluir_canceladas  = _to_bool(params.get("include_canceladas")  or params.get("incluir_canceladas"))
        incluir_finalizadas = _to_bool(params.get("include_finalizadas") or params.get("incluir_finalizadas"))

        qs = Poliza.objects.all().select_related("cliente")

        user = self.request.user
        if not user.is_authenticated:
            return qs.none()

        is_admin = user.is_superuser or getattr(getattr(user, "perfil", None), "rol", "") == "ADMIN"
        if not is_admin:
            ofi_id = getattr(getattr(user, "perfil", None), "oficina_id", None)
            if ofi_id:
                qs = qs.filter(oficina_id=ofi_id)

        if not incluir_finalizadas:
            qs = qs.exclude(estado__iexact="finalizada")
        if not incluir_canceladas:
            qs = qs.exclude(estado__iexact="cancelada")

        oficina = (params.get("oficina") or "").strip()
        if oficina and oficina.isdigit():
            qs = qs.filter(oficina_id=oficina)

        compania = (params.get("compania") or "").strip()
        if compania:
            qs = qs.filter(compania__iexact=compania)

        qs = qs.annotate(
            impagas_count=Count(
                "cuotas",
                filter=Q(cuotas__pagado=False, cuotas__fecha_vencimiento__lt=hoy),
                distinct=True,
            ),
            min_vto_impaga=Min(
                "cuotas__fecha_vencimiento",
                filter=Q(cuotas__pagado=False, cuotas__fecha_vencimiento__lt=hoy),
            ),
            max_vto_impaga=Max(
                "cuotas__fecha_vencimiento",
                filter=Q(cuotas__pagado=False, cuotas__fecha_vencimiento__lt=hoy),
            ),
        ).filter(
            # 🎯 La mora se mide desde la PRIMERA cuota impaga (min), no la última.
            # Antes usaba max_vto_impaga: una póliza con varias cuotas impagas y la
            # última recién vencida quedaba FUERA del filtro aunque arrastrara meses
            # de deuda. Con min_vto_impaga, "X días de mora" = días desde que dejó
            # de pagar, que es lo que el operador espera al setear el umbral.
            min_vto_impaga__isnull=False,
            min_vto_impaga__lte=limite,
        )

        baja_estado = (params.get("baja_estado") or params.get("estado") or "").strip().upper()
        if baja_estado in {"PENDIENTE_ENVIO", "ENVIADA", "REALIZADA"}:
            baja_qs = BajaPoliza.objects.filter(poliza_id=OuterRef("pk"))
            qs = qs.annotate(
                _has_baja    = Exists(baja_qs),
                _baja_estado = Subquery(baja_qs.values("estado")[:1]),
            )
            if baja_estado == "PENDIENTE_ENVIO":
                qs = qs.filter(Q(_has_baja=False) | Q(_baja_estado="PENDIENTE_ENVIO"))
            else:
                qs = qs.filter(_baja_estado=baja_estado)

        return qs

    # ─── List ─────────────────────────────────────────────────────────────────

    def list(self, request, *args, **kwargs):
        hoy = timezone.localdate()
        qs  = self._base_queryset()
        qs  = self.filter_queryset(qs)

        export = request.query_params.get("export", "").lower()
        if export == "csv":
            return self._export_csv(qs, hoy)

        page  = self.paginate_queryset(qs)
        items = page if page is not None else qs

        poliza_ids = [p.id for p in items]
        bajas_map  = {
            b.poliza_id: b
            for b in BajaPoliza.objects.filter(poliza_id__in=poliza_ids)
        }

        payload = []
        for p in items:
            cli      = getattr(p, "cliente", None)
            baja     = bajas_map.get(p.id)
            min_vto  = getattr(p, "min_vto_impaga", None)
            max_vto  = getattr(p, "max_vto_impaga", None)
            # 🎯 mora_dias se cuenta desde la PRIMERA cuota impaga (min), igual que
            # en el CSV, el Excel y services.py.
            mora_dias = _mora_dias(p, hoy)
            ofi_str   = _ofi_str(getattr(p, "oficina", None))

            payload.append({
                "id":            p.id,
                "numero_poliza": getattr(p, "numero_poliza", None),
                "patente":       getattr(p, "patente", None),
                "compania":      getattr(p, "compania", None),
                "oficina":       ofi_str,
                "estado":        getattr(p, "estado", None),
                "fase":          getattr(p, "fase", None),
                "cliente_id":      getattr(cli, "id",           None) if cli else None,
                "cliente_nombre":  getattr(cli, "nombre",       None) if cli else None,
                "cliente_apellido":getattr(cli, "apellido",     None) if cli else None,
                "cliente_dni":     getattr(cli, "dni_cuit_cuil",None) if cli else None,
                "cliente_telefono":getattr(cli, "telefono",     None) if cli else None,
                "impagas_count":   int(getattr(p, "impagas_count", 0) or 0),
                "cuotas_impagas":  int(getattr(p, "impagas_count", 0) or 0),
                "min_vto_impaga":  min_vto,
                "max_vto_impaga":  max_vto,
                "mora_dias":       int(mora_dias),
                "baja_estado":        getattr(baja, "estado",        None) if baja else "PENDIENTE_ENVIO",
                "baja_email_destino": getattr(baja, "email_destino", "")   if baja else "",
                "baja_notas":         getattr(baja, "notas",         "")   if baja else "",
                "baja_enviada_en":    getattr(baja, "enviada_en",    None) if baja else None,
                "baja_realizada_en":  getattr(baja, "realizada_en",  None) if baja else None,
            })

        ser = BajaPolizaListSerializer(payload, many=True)
        if page is not None:
            return self.get_paginated_response(ser.data)
        return Response(ser.data)

    def _export_csv(self, queryset, hoy):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="candidatas_baja.csv"'

        writer = csv.writer(response)
        writer.writerow([
            "Compañía", "Nro Póliza", "Patente", "Asegurado",
            "DNI", "Teléfono", "Oficina", "Días Mora",
            "Cuotas Impagas", "Últ. Vto Impago",
        ])

        for p in queryset:
            cli       = getattr(p, "cliente", None)
            # CSV histórico: nombre + apellido (mantiene el orden original de esta exportación).
            asegurado = f"{getattr(cli,'nombre','') or ''} {getattr(cli,'apellido','') or ''}".strip() if cli else ""
            min_vto   = getattr(p, "min_vto_impaga", None)
            writer.writerow([
                getattr(p, "compania", ""),
                getattr(p, "numero_poliza", ""),
                getattr(p, "patente", ""),
                asegurado,
                getattr(cli, "dni_cuit_cuil", "") if cli else "",
                getattr(cli, "telefono", "")       if cli else "",
                getattr(p, "oficina", ""),
                _mora_dias(p, hoy),
                int(getattr(p, "impagas_count", 0)),
                min_vto.strftime("%d/%m/%Y") if min_vto else "",
            ])

        return response

    # ─── Counters ─────────────────────────────────────────────────────────────

    @action(detail=False, methods=["get"], url_path="counters")
    def counters(self, request, *args, **kwargs):
        qs = self._base_queryset()

        total = qs.count()

        baja_qs = BajaPoliza.objects.filter(poliza_id=OuterRef("pk"))
        qs_ann  = qs.annotate(
            _has_baja    = Exists(baja_qs),
            _baja_estado = Subquery(baja_qs.values("estado")[:1]),
        )

        pendiente = qs_ann.filter(Q(_has_baja=False) | Q(_baja_estado="PENDIENTE_ENVIO")).count()
        enviada   = qs_ann.filter(_baja_estado="ENVIADA").count()
        realizada = qs_ann.filter(_baja_estado="REALIZADA").count()

        return Response({
            "total":           total,
            "pendiente_envio": pendiente,
            "enviada":         enviada,
            "realizada":       realizada,
        })

    # ─── Update estado ────────────────────────────────────────────────────────

    @action(detail=True, methods=["post"], url_path="estado")
    def update_estado(self, request, pk=None):
        try:
            poliza = Poliza.objects.get(pk=pk)
        except Poliza.DoesNotExist:
            return Response({"detail": "Póliza no encontrada."}, status=status.HTTP_404_NOT_FOUND)

        ser = BajaEstadoUpdateSerializer(data=request.data or {})
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        estado_new    = data["estado"]
        email_destino = (data.get("email_destino") or "").strip()
        notas         = (data.get("notas") or "").strip()

        raw_cancelar  = data.get("cancelar_poliza") or request.data.get("cancelar_poliza")
        cancelar_poliza = _to_bool(raw_cancelar) if raw_cancelar is not None else True

        baja, _created = BajaPoliza.objects.get_or_create(poliza=poliza)
        baja.estado = estado_new
        if email_destino:
            baja.email_destino = email_destino
        if notas:
            baja.notas = notas

        now = timezone.now()
        if estado_new == "ENVIADA":
            baja.enviada_en = now
        if estado_new == "REALIZADA":
            baja.realizada_en = now

        baja.save()

        if estado_new == "REALIZADA" and cancelar_poliza:
            try:
                if poliza.estado != "cancelada":
                    poliza.estado = "cancelada"
                    update_fields = ["estado"]
                    if hasattr(poliza, "fecha_baja"):
                        poliza.fecha_baja = timezone.localdate()
                        update_fields.append("fecha_baja")
                    if hasattr(poliza, "motivo_baja"):
                        poliza.motivo_baja = "INCUMPLIMIENTO_PAGO"
                        update_fields.append("motivo_baja")
                    poliza.save(update_fields=update_fields)
                    _hist_log(
                        poliza=poliza,
                        tipo="POLIZA_CANCELADA_BAJA",
                        mensaje="Póliza cancelada por baja operativa (morosidad).",
                        severidad="ACTION",
                        request=request,
                        subject=poliza,
                        categoria="POLIZA",
                    )
            except Exception as e:
                logger.error(
                    "[bajas.views] No se pudo cancelar la póliza %s al marcar REALIZADA: %s",
                    poliza.id, e,
                )

        return Response({
            "poliza_id":        poliza.id,
            "baja_estado":      baja.estado,
            "baja_email_destino": baja.email_destino,
            "baja_notas":       baja.notas,
            "baja_enviada_en":  baja.enviada_en,
            "baja_realizada_en":baja.realizada_en,
        })

    # ─── Export Excel ─────────────────────────────────────────────────────────

    @action(detail=False, methods=["get"], url_path="exportar-excel")
    def exportar_excel(self, request):
        try:
            import xlsxwriter
            from io import BytesIO
        except ImportError:
            return Response({"detail": "xlsxwriter no instalado."}, status=500)

        filtro_tarjeta = (request.query_params.get("estado_tarjeta") or "UNIVERSO").upper()
        estado_map = {
            "PENDIENTES": "PENDIENTE_ENVIO",
            "ENVIADAS":   "ENVIADA",
            "REALIZADAS": "REALIZADA",
        }

        mutable_params = request.query_params.copy()
        if filtro_tarjeta in estado_map:
            mutable_params["baja_estado"] = estado_map[filtro_tarjeta]

        old_params = request.query_params
        request._request.GET = mutable_params
        qs = self._base_queryset()
        qs = self.filter_queryset(qs)
        request._request.GET = old_params

        poliza_ids = list(qs.values_list("id", flat=True))
        bajas_map  = {b.poliza_id: b for b in BajaPoliza.objects.filter(poliza_id__in=poliza_ids)}

        output   = BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        ws       = workbook.add_worksheet("Reporte de Bajas")

        fmt_titulo   = workbook.add_format({"bold": True, "font_size": 14, "bg_color": "#18181B", "font_color": "white", "align": "center", "valign": "vcenter"})
        fmt_cabecera = workbook.add_format({"bold": True, "bg_color": "#27272A", "font_color": "white", "border": 1, "align": "center", "valign": "vcenter"})
        fmt_celda    = workbook.add_format({"border": 1, "valign": "vcenter"})
        fmt_centro   = workbook.add_format({"border": 1, "align": "center", "valign": "vcenter"})
        fmt_alerta   = workbook.add_format({"border": 1, "align": "center", "valign": "vcenter", "font_color": "#E11D48", "bold": True})

        ws.merge_range("A1:J1", f"REPORTE DE BAJAS — {filtro_tarjeta}", fmt_titulo)
        ws.set_row(0, 30)

        cabeceras = ["Póliza", "Compañía", "Patente", "Marca/Modelo", "Asegurado", "DNI", "Teléfono", "Sucursal", "Días Mora", "Estado Baja"]
        ws.write_row("A3", cabeceras, fmt_cabecera)
        ws.set_row(2, 25)
        ws.set_column("A:A", 18)
        ws.set_column("B:B", 20)
        ws.set_column("C:C", 12)
        ws.set_column("D:D", 25)
        ws.set_column("E:E", 30)
        ws.set_column("F:F", 15)
        ws.set_column("G:G", 15)
        ws.set_column("H:H", 20)
        ws.set_column("I:I", 15)
        ws.set_column("J:J", 18)

        hoy  = timezone.localdate()
        fila = 3

        for p in qs:
            cli       = getattr(p, "cliente", None)
            baja      = bajas_map.get(p.id)
            mora_dias = _mora_dias(p, hoy)
            estado_baja_txt = str(getattr(baja, "estado", "PENDIENTE ENVIO") if baja else "PENDIENTE ENVIO").replace("_", " ")
            vehiculo  = f"{getattr(p,'marca','') or ''} {getattr(p,'modelo','') or ''}".strip()
            asegurado = _asegurado_apellido_nombre(cli)

            ws.write(fila, 0, getattr(p, "numero_poliza", "—") or "—", fmt_celda)
            ws.write(fila, 1, getattr(p, "compania", "—")      or "—", fmt_celda)
            ws.write(fila, 2, getattr(p, "patente", "—")        or "—", fmt_centro)
            ws.write(fila, 3, vehiculo  or "—", fmt_celda)
            ws.write(fila, 4, asegurado or "—", fmt_celda)
            ws.write(fila, 5, getattr(cli, "dni_cuit_cuil", "—") if cli else "—", fmt_centro)
            ws.write(fila, 6, getattr(cli, "telefono",     "—") if cli else "—", fmt_centro)
            ws.write(fila, 7, _ofi_str(getattr(p, "oficina", None)) or "—", fmt_celda)
            ws.write(fila, 8, int(mora_dias), fmt_alerta if mora_dias > 30 else fmt_centro)
            ws.write(fila, 9, estado_baja_txt, fmt_centro)
            fila += 1

        if fila > 3:
            ws.autofilter(2, 0, fila - 1, len(cabeceras) - 1)

        workbook.close()
        output.seek(0)

        filename = f"Reporte_Bajas_{filtro_tarjeta}_{hoy.strftime('%d-%m-%Y')}.xlsx"
        response = HttpResponse(
            output.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["Access-Control-Expose-Headers"] = "Content-Disposition"
        return response

    # ─── Digest del día ───────────────────────────────────────────────────────

    @action(detail=False, methods=["get"], url_path="digest-del-dia")
    def digest_del_dia(self, request):
        """
        GET /api/bajas/operativo/digest-del-dia/
        Devuelve las pólizas en mora agrupadas por compañía para el panel del día.
        """
        oficina  = request.query_params.get("oficina", "").strip()
        ofi_id   = int(oficina) if oficina.isdigit() else None

        user     = request.user
        is_admin = user.is_superuser or getattr(getattr(user, "perfil", None), "rol", "") == "ADMIN"
        if not is_admin:
            ofi = getattr(getattr(user, "perfil", None), "oficina", None)
            ofi_id = getattr(ofi, "id", None)

        digest = construir_digest(oficina_id=ofi_id)

        grupos_data = [
            {
                "compania":         g.compania,
                "email_destino":    g.email_destino,
                "estado":           g.estado,
                "email_enviado_en": g.email_enviado_en,
                "polizas": [
                    {
                        "id":            p.id,
                        "numero_poliza": p.numero_poliza,
                        "patente":       p.patente,
                        "asegurado":     p.asegurado,
                        "mora_dias":     p.mora_dias,
                        "impagas_count": p.impagas_count,
                    }
                    for p in g.polizas
                ],
            }
            for g in digest.grupos
        ]

        return Response({
            "fecha":         str(digest.fecha),
            "total_polizas": digest.total_polizas,
            "grupos":        grupos_data,
        })

    # ─── Enviar una compañía ──────────────────────────────────────────────────

    @action(detail=False, methods=["post"], url_path="enviar-baja-email")
    def enviar_baja_email(self, request):
        """
        POST /api/bajas/operativo/enviar-baja-email/
        Body: { "compania": "Federación Patronal" }
        Envía el digest de una compañía y marca las pólizas como ENVIADA.
        """
        compania = (request.data.get("compania") or "").strip()
        if not compania:
            return Response(
                {"detail": "El campo 'compania' es requerido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user     = request.user
        is_admin = user.is_superuser or getattr(getattr(user, "perfil", None), "rol", "") == "ADMIN"
        ofi_id   = None
        if not is_admin:
            ofi    = getattr(getattr(user, "perfil", None), "oficina", None)
            ofi_id = getattr(ofi, "id", None)

        resultado   = enviar_digest_compania(compania=compania, oficina_id=ofi_id)
        http_status = status.HTTP_200_OK if resultado["ok"] else status.HTTP_502_BAD_GATEWAY
        return Response(resultado, status=http_status)

    # ─── Enviar todas las compañías ───────────────────────────────────────────

    @action(detail=False, methods=["post"], url_path="enviar-bajas-del-dia")
    def enviar_bajas_del_dia(self, request):
        """
        POST /api/bajas/operativo/enviar-bajas-del-dia/
        Botón "Enviar todo" del front. Manda el digest a todas las compañías pendientes.
        Body (opcional): { "dias": 3, "oficina": 1 }
        """
        oficina = str(request.data.get("oficina", "") or "").strip()
        ofi_id  = int(oficina) if oficina.isdigit() else None

        user     = request.user
        is_admin = user.is_superuser or getattr(getattr(user, "perfil", None), "rol", "") == "ADMIN"
        if not is_admin:
            ofi    = getattr(getattr(user, "perfil", None), "oficina", None)
            ofi_id = getattr(ofi, "id", None)

        resultados = enviar_todas_del_dia(oficina_id=ofi_id)
        ok_count   = sum(1 for r in resultados if r["ok"])

        return Response({
            "total_companias": len(resultados),
            "enviadas_ok":     ok_count,
            "con_error":       len(resultados) - ok_count,
            "detalle":         resultados,
        })


# ─── Historial ────────────────────────────────────────────────────────────────

class HistorialBajaPolizaSerializer(serializers.ModelSerializer):
    poliza_numero  = serializers.CharField(source="baja_poliza.poliza.numero_poliza", read_only=True)
    patente        = serializers.CharField(source="baja_poliza.poliza.patente",        read_only=True)
    compania       = serializers.CharField(source="baja_poliza.poliza.compania",       read_only=True)
    cliente_nombre = serializers.SerializerMethodField()

    class Meta:
        model  = HistorialBajaPoliza
        fields = [
            "id", "poliza_numero", "patente", "compania",
            "cliente_nombre", "estado_anterior", "estado_nuevo", "fecha",
        ]

    def get_cliente_nombre(self, obj):
        try:
            cli = obj.baja_poliza.poliza.cliente
            if cli:
                return f"{getattr(cli,'nombre','') or ''} {getattr(cli,'apellido','') or ''}".strip()
        except Exception:
            pass
        return "Asegurado"


class HistorialBajaPolizaViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Endpoint de solo lectura para el historial de bajas.
    /api/bajas/historial/
    """
    queryset           = HistorialBajaPoliza.objects.select_related("baja_poliza__poliza__cliente").order_by("-fecha")
    serializer_class   = HistorialBajaPolizaSerializer
    permission_classes = [IsAuthenticated]
    pagination_class   = LargeResultsSetPagination

    def get_queryset(self):
        qs   = super().get_queryset()
        user = self.request.user
        if not user.is_authenticated:
            return qs.none()

        is_admin = user.is_superuser or getattr(getattr(user, "perfil", None), "rol", "") == "ADMIN"
        if not is_admin:
            ofi_id = getattr(getattr(user, "perfil", None), "oficina_id", None)
            if ofi_id:
                qs = qs.filter(baja_poliza__poliza__oficina_id=ofi_id)

        poliza_id = self.request.query_params.get("poliza_id")
        if poliza_id:
            qs = qs.filter(baja_poliza__poliza_id=poliza_id)

        return qs