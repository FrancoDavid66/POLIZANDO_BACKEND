# polizas/views/cupon_robo.py

from rest_framework import viewsets, filters
from rest_framework.response import Response
from rest_framework.decorators import action
# 🚀 FIX: Cambiamos AllowAny por IsAuthenticated
from rest_framework.permissions import IsAuthenticated

from django.db.models import Q, OuterRef, Subquery
from django.utils import timezone
from django.apps import apps
from django.db import transaction

from datetime import timedelta, date

from seguros_project.pagination import LargeResultsSetPagination

from polizas.models import Poliza, CuponRobo
from polizas.serializers import CuponRoboSerializer

from polizas.utils.viewtools import hist_log as _hist_log
from polizas.domain.robo import ensure_cupones_robo_for_poliza


class CuponRoboViewSet(viewsets.ModelViewSet):
    queryset = (
        CuponRobo.objects.select_related("poliza", "poliza__cliente")
        .all()
        .order_by("poliza_id", "id")
    )
    serializer_class = CuponRoboSerializer
    # 🚀 FIX: Blindaje de seguridad. Solo usuarios logueados.
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = [
        "poliza__numero_poliza",
        "poliza__patente",
        "poliza__cliente__nombre",
        "poliza__cliente__apellido",
        "poliza__cliente__dni_cuit_cuil",
    ]
    pagination_class = LargeResultsSetPagination

    def _to_bool(self, v):
        s = str(v or "").strip().lower()
        return s in {"1", "true", "t", "yes", "y", "on", "si", "sí"}

    # 🚀 NUEVO: ESCUDO MULTI-TENANT (SUCURSALES Y VENDEDORES)
    def _get_shielded_queryset(self):
        """
        Retorna la base de cupones filtrada SIEMPRE por la oficina o el vendedor.
        """
        qs = super().get_queryset()
        user = self.request.user
        
        if not user.is_authenticated:
            return qs.none()
            
        is_admin = user.is_superuser or getattr(user.perfil, 'rol', '') == 'ADMIN'
        
        if not is_admin:
            # 🚀 FILTRO VENDEDOR
            if getattr(user.perfil, 'rol', '') == 'VENDEDOR':
                return qs.filter(poliza__vendedor=user.perfil)
            
            # FILTRO OFICINA
            ofi_id = getattr(user.perfil, 'oficina_id', None)
            if ofi_id:
                qs = qs.filter(poliza__oficina_id=ofi_id)
            else:
                return qs.none()
        
        return qs

    def _apply_ultimo_por_poliza(self, qs):
        base = qs.exclude(estado=CuponRobo.Estado.PAGADA)

        pick_id = (
            CuponRobo.objects.filter(poliza_id=OuterRef("poliza_id"))
            .exclude(estado=CuponRobo.Estado.PAGADA)
            .order_by("fecha_vencimiento", "-id")
            .values("id")[:1]
        )
        return base.filter(id=Subquery(pick_id)).order_by("fecha_vencimiento", "-id")

    def _apply_scope(self, qs, scope_raw: str):
        scope = (scope_raw or "").strip().upper()
        if not scope or scope == "ALL":
            return qs

        today = timezone.localdate()
        in_7_days = today + timedelta(days=7)

        if scope == "VENCIDA":
            return qs.filter(fecha_vencimiento__lt=today).exclude(estado=CuponRobo.Estado.PAGADA)

        if scope == "POR_VENCER_7":
            return (
                qs.filter(fecha_vencimiento__gte=today, fecha_vencimiento__lte=in_7_days)
                .exclude(estado=CuponRobo.Estado.PAGADA)
            )

        if scope == "PENDIENTE":
            return (
                qs.exclude(estado=CuponRobo.Estado.PAGADA)
                .filter(Q(fecha_vencimiento__isnull=True) | Q(fecha_vencimiento__gte=today))
            )

        return qs

    def _build_counters(self, qs):
        today = timezone.localdate()
        in_7_days = today + timedelta(days=7)

        total = qs.count()
        pendientes = qs.filter(estado=CuponRobo.Estado.PENDIENTE).count()
        vencidas = qs.filter(fecha_vencimiento__lt=today).exclude(estado=CuponRobo.Estado.PAGADA).count()
        por_vencer_7 = (
            qs.filter(fecha_vencimiento__gte=today, fecha_vencimiento__lte=in_7_days)
            .exclude(estado=CuponRobo.Estado.PAGADA)
            .count()
        )

        return {
            "total": total,
            "pendientes": pendientes,
            "por_vencer_7": por_vencer_7,
            "vencidas": vencidas,
            "hoy": today.isoformat(),
            "hasta": in_7_days.isoformat(),
        }

    def _apply_oficina(self, qs, oficina):
        if not oficina:
            return qs
        vals = [v.strip() for v in oficina.split(",") if v.strip()] if "," in oficina else [oficina]
        try:
            f = Poliza._meta.get_field("oficina")
            if getattr(f, "is_relation", False):
                id_vals = [int(v) for v in vals if str(v).isdigit()]
                name_vals = [v for v in vals if not str(v).isdigit()]

                if id_vals:
                    qs = qs.filter(poliza__oficina_id__in=id_vals)
                if name_vals:
                    rel = getattr(f, "remote_field", None)
                    rel_model = getattr(rel, "model", None)
                    if rel_model is not None and hasattr(rel_model, "nombre"):
                        qs = qs.filter(poliza__oficina__nombre__in=name_vals)
                    else:
                        qs = qs.filter(poliza__oficina__pk__in=name_vals)
            else:
                qs = qs.filter(poliza__oficina__in=vals)
        except Exception:
            qs = qs.filter(poliza__oficina__in=vals)
        return qs

    def get_queryset(self):
        # 🚀 FIX: Usamos el queryset blindado por sucursal y vendedor
        qs = self._get_shielded_queryset()
        params = self.request.query_params

        poliza_id = (params.get("poliza") or "").strip()
        estado = (params.get("estado") or "").strip()
        vto_antes = (params.get("vencimiento_antes_de") or "").strip()
        vto_despues = (params.get("vencimiento_despues_de") or "").strip()

        numero_poliza = (params.get("numero_poliza") or "").strip()
        patente = (params.get("patente") or "").strip()
        asegurado = (params.get("asegurado") or "").strip()
        dni = (params.get("dni") or "").strip()
        oficina = (params.get("oficina") or "").strip()
        compania = (params.get("compania") or "").strip()

        if poliza_id:
            qs = qs.filter(poliza_id=poliza_id)
        if estado:
            qs = qs.filter(estado=estado)
        if vto_despues:
            try:
                d = date.fromisoformat(vto_despues)
                qs = qs.filter(fecha_vencimiento__gte=d)
            except ValueError:
                pass
        if vto_antes:
            try:
                d = date.fromisoformat(vto_antes)
                qs = qs.filter(fecha_vencimiento__lte=d)
            except ValueError:
                pass
        if numero_poliza:
            qs = qs.filter(poliza__numero_poliza__icontains=numero_poliza)
        if patente:
            qs = qs.filter(poliza__patente__icontains=patente)
        if asegurado:
            qs = qs.filter(
                Q(poliza__cliente__nombre__icontains=asegurado)
                | Q(poliza__cliente__apellido__icontains=asegurado)
            )
        if dni:
            qs = qs.filter(poliza__cliente__dni_cuit_cuil__icontains=dni)
        if compania:
            qs = qs.filter(poliza__compania__icontains=compania)

        qs = self._apply_oficina(qs, oficina)

        if self._to_bool(params.get("solo_ultimo")):
            qs = self._apply_ultimo_por_poliza(qs)

        return qs

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())

        limit_raw = (request.query_params.get("limit") or "").strip()
        if limit_raw:
            try:
                limit_n = int(limit_raw)
                if limit_n > 0:
                    qs = qs[:limit_n]
                    serializer = self.get_serializer(qs, many=True)
                    return Response(serializer.data, status=200)
            except Exception:
                pass

        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=["get"], url_path="dashboard")
    def dashboard(self, request):
        base_qs = self.filter_queryset(self.get_queryset())
        counters_filtrados = self._build_counters(base_qs)

        global_qs = self._get_shielded_queryset()
        params = request.query_params
        global_qs = self._apply_oficina(global_qs, (params.get("oficina") or "").strip())
        if self._to_bool(params.get("solo_ultimo")):
            global_qs = self._apply_ultimo_por_poliza(global_qs)
        
        counters_global = self._build_counters(global_qs)

        scope = (request.query_params.get("scope") or "").strip()
        table_qs = self._apply_scope(base_qs, scope) if scope else base_qs

        page = self.paginate_queryset(table_qs)
        if page is not None:
            ser = self.get_serializer(page, many=True)
            paged = self.get_paginated_response(ser.data).data
            return Response(
                {
                    "counters_global": counters_global,
                    "counters_filtrados": counters_filtrados,
                    "count": paged.get("count", 0),
                    "next": paged.get("next"),
                    "previous": paged.get("previous"),
                    "results": paged.get("results", []),
                },
                status=200,
            )

        ser = self.get_serializer(table_qs, many=True)
        return Response(
            {
                "counters_global": counters_global,
                "counters_filtrados": counters_filtrados,
                "count": len(ser.data),
                "next": None,
                "previous": None,
                "results": ser.data,
            },
            status=200,
        )

    @action(detail=False, methods=["get"], url_path="counters")
    def counters(self, request):
        global_qs = self._get_shielded_queryset()
        params = request.query_params
        global_qs = self._apply_oficina(global_qs, (params.get("oficina") or "").strip())
        if self._to_bool(params.get("solo_ultimo")):
            global_qs = self._apply_ultimo_por_poliza(global_qs)
        return Response(self._build_counters(global_qs), status=200)

    def perform_create(self, serializer):
        instance = serializer.save()
        _hist_log(
            poliza=instance.poliza,
            tipo="CUPON_ROBO_CREAR",
            mensaje="Creado cupón de robo",
            severidad="ACTION",
            data={
                "cupon_id": instance.id,
                "numero": getattr(instance, "numero", None),
                "estado": getattr(instance, "estado", None),
                "periodo_desde": getattr(instance, "periodo_desde", None),
                "periodo_hasta": getattr(instance, "periodo_hasta", None),
                "fecha_vencimiento": getattr(instance, "fecha_vencimiento", None),
            },
            request=self.request,
            subject=instance,
            categoria="POLIZA",
        )

    def perform_update(self, serializer):
        instance_before = self.get_object()
        old_estado = getattr(instance_before, "estado", None)
        old_monto = getattr(instance_before, "monto", None)

        instance = serializer.save()
        new_estado = getattr(instance, "estado", None)
        monto = getattr(instance, "monto", None)

        if new_estado == CuponRobo.Estado.PAGADA and instance.fecha_pago is None:
            instance.fecha_pago = timezone.now()
            instance.save(update_fields=["fecha_pago"])

        if old_estado != new_estado:
            _hist_log(
                poliza=instance.poliza,
                tipo="CUPON_ROBO_CAMBIAR_ESTADO",
                mensaje="Cambio de estado en cupón de robo",
                severidad="ACTION",
                data={
                    "cupon_id": instance.id,
                    "antes": old_estado,
                    "despues": new_estado,
                    "numero": getattr(instance, "numero", None),
                },
                request=self.request,
                subject=instance,
                categoria="POLIZA",
            )

        if new_estado == CuponRobo.Estado.PAGADA and old_estado != CuponRobo.Estado.PAGADA:
            # 🆕 NUEVO MODELO: el cliente paga directo a la compañía (NO hay egreso).
            # Lo único que registramos es NUESTRA comisión como ingreso.
            self._registrar_comision_ingreso(instance, self.request)

        return instance

    def _registrar_comision_ingreso(self, cupon: CuponRobo, request) -> None:
        """
        🆕 Registra como INGRESO la comisión que la compañía nos paga por este cupón.
        El % sale del catálogo: poliza.compania_obj.comision_default.
        Ya NO se genera egreso: el cliente paga el cupón directo a la compañía.
        """
        try:
            monto_cupon = float(getattr(cupon, "monto", 0) or 0)
        except Exception:
            monto_cupon = 0.0
        if monto_cupon <= 0:
            return

        poliza = getattr(cupon, "poliza", None)
        comp = getattr(poliza, "compania_obj", None) if poliza else None
        try:
            pct = float(getattr(comp, "comision_default", 0) or 0)
        except Exception:
            pct = 0.0
        if pct <= 0:
            return  # sin % configurado en el catálogo → no registramos nada

        comision = round(monto_cupon * pct / 100.0, 2)
        if comision <= 0:
            return

        fecha_ing = cupon.fecha_pago.date() if getattr(cupon, "fecha_pago", None) else timezone.localdate()
        poliza_num = getattr(poliza, "numero_poliza", "") if poliza else "s/n"
        patente = getattr(poliza, "patente", "") if poliza else ""
        oficina_obj = getattr(poliza, "oficina", None) if poliza else None
        usuario_obj = getattr(request, "user", None) if request else None

        descripcion_txt = f"Comisión cupón robo - Póliza {poliza_num} ({patente})"
        if getattr(cupon, "periodo_desde", None):
            descripcion_txt += f" - Período {cupon.periodo_desde.strftime('%m/%Y')}"

        try:
            from balanzes.models import Ingreso
            with transaction.atomic():
                Ingreso.objects.create(
                    descripcion=descripcion_txt,
                    monto=comision,
                    fecha=fecha_ing,
                    categoria="Comisión Compañía",
                    oficina=oficina_obj,
                    usuario=usuario_obj,
                    forma_pago="TRANSFERENCIA",
                )
        except Exception:
            # No rompemos la confirmación del cupón si el ingreso falla.
            pass