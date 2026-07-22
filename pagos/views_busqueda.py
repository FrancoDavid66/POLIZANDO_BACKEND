# pagos/views_busqueda.py
#
# Mixin con los 2 buscadores de PagoViewSet (buscar-cliente por DNI, buscar
# cuotas con filtros), separado de pagos/views.py para que ese archivo no sea
# un solo bloque enorme. Se usa por herencia — mismo comportamiento, mismas
# URLs, solo cambia en qué archivo vive el código.

from datetime import timedelta

from django.db.models import Q, OuterRef, Subquery, DateField, Max
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from .models import Cuota
from polizas.models import Poliza
from pagos.views_helpers import (
    _get_seguridad_oficina_brute,
    _build_oficina_q_from_keys,
    _to_bool,
    _to_int,
    _only_digits,
    _compania_nombre_robusto,
)


class BusquedaMixin:
    @action(detail=False, methods=["get"], url_path="buscar-cliente")
    def buscar_cliente(self, request):
        dni_raw = (request.query_params.get("dni") or request.query_params.get("q") or "").strip()
        dni = _only_digits(dni_raw)

        if not dni:
            return Response({"detail": "Falta parámetro dni (solo números)."}, status=status.HTTP_400_BAD_REQUEST)

        # 🆕 Refrescamos el estado de las pólizas antes de buscar, para que las que ya
        # vencieron y están pagas pasen a "finalizada" (y muestren el botón Renovar).
        # Sin esto, el estado solo se actualiza al entrar al módulo de Pólizas.
        try:
            from polizas.views.poliza import auto_marcar_vencidas
            auto_marcar_vencidas()
        except Exception:
            pass

        pol_qs = (
            Poliza.objects.select_related("cliente", "oficina")
            .only(
                "id",
                "oficina",
                "compania",
                "patente",
                "marca",
                "modelo",
                "estado",
                "fecha_baja",
                "fecha_vencimiento",
                "cliente_id",
                "cliente__apellido",
                "cliente__nombre",
                "cliente__dni_cuit_cuil",
            )
            .filter(
                Q(cliente__dni_cuit_cuil__iexact=dni_raw)
                | Q(cliente__dni_cuit_cuil__iexact=dni)
                | Q(cliente__dni_cuit_cuil__icontains=dni)
            )
            # 🆕 Fecha de la ÚLTIMA cuota (la mayor): es el "fin real" que usa el sistema
            # para finalizar la póliza. La tolerancia de 3 días se mide contra esto,
            # no contra poliza.fecha_vencimiento (que puede no estar cargada).
            .annotate(
                ult_cuota_vto=Subquery(
                    Cuota.objects.filter(poliza_id=OuterRef("pk"))
                    .order_by("-fecha_vencimiento")
                    .values("fecha_vencimiento")[:1],
                    output_field=DateField(),
                )
            )
        )

        # 🚀 MULTI-TENANT: la búsqueda por DNI ve TODAS las oficinas. Cualquier
        # empleado puede atender y cobrar a cualquier cliente.
        if not request.user.is_authenticated:
            return Response({"detail": "Acceso denegado"}, status=403)

        pol_qs = pol_qs.order_by("-id")[:50]

        first = pol_qs.first()
        if not first or not getattr(first, "cliente", None):
            return Response({"detail": "No se encontró cliente con ese DNI."}, status=status.HTTP_404_NOT_FOUND)

        cli = first.cliente
        nombre_apellido = f"{(cli.apellido or '').strip()} {(cli.nombre or '').strip()}".strip()

        def get_ofi_str(ofi_obj):
            if not ofi_obj: return ""
            if hasattr(ofi_obj, 'nombre'): return str(ofi_obj.nombre)
            return str(ofi_obj)

        oficina_str = get_ofi_str(getattr(first, "oficina", None))
        try:
            counts = {}
            for p in pol_qs:
                o_str = get_ofi_str(getattr(p, "oficina", None))
                if not o_str:
                    continue
                counts[o_str] = counts.get(o_str, 0) + 1
            if counts:
                oficina_str = sorted(counts.items(), key=lambda x: (-x[1], str(x[0])))[0][0]
        except Exception:
            pass

        # 🆕 Marcar cuáles ya tienen una renovación hecha: existe una póliza "hija"
        #    que las apunta como origen. El front usa esto para NO ofrecer "Renovar"
        #    sobre una póliza que ya fue renovada (evita el 409 POLIZA_YA_RENOVADA).
        pol_ids = [p.id for p in pol_qs]
        renovadas_origen_ids = set(
            Poliza.objects.filter(poliza_origen_id__in=pol_ids)
            .values_list("poliza_origen_id", flat=True)
        )

        polizas = []
        for p in pol_qs:
            modelo_txt = f"{(getattr(p, 'marca', '') or '').strip()} {(getattr(p, 'modelo', '') or '').strip()}".strip()
            fecha_baja = getattr(p, "fecha_baja", None)
            # Fin real = última cuota; si por algún motivo no hay, caemos al campo de la póliza.
            fecha_fin = getattr(p, "ult_cuota_vto", None) or getattr(p, "fecha_vencimiento", None)
            polizas.append(
                {
                    "poliza_id":  p.id,
                    "compania":   _compania_nombre_robusto(p),
                    "patente":    getattr(p, "patente", "") or "",
                    "modelo":     modelo_txt,
                    "oficina":    get_ofi_str(getattr(p, "oficina", None)),
                    "estado":     getattr(p, "estado", "") or "",
                    "fecha_baja": fecha_baja.isoformat() if fecha_baja else None,
                    "fecha_fin":  fecha_fin.isoformat() if fecha_fin else None,
                    "tiene_renovacion": p.id in renovadas_origen_ids,
                }
            )

        return Response(
            {
                "cliente": {"dni": getattr(cli, "dni_cuit_cuil", "") or dni, "nombre_apellido": nombre_apellido, "oficina": oficina_str},
                "polizas": polizas,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="buscar")
    def buscar(self, request):
        q = (request.query_params.get("q") or request.query_params.get("search") or "").strip()

        oficina_raw = (request.query_params.get("oficina") or "").strip()
        # 🚀 MULTI-TENANT: la búsqueda de pagos ve TODAS las oficinas. Cualquier
        # empleado puede buscar y cobrar a cualquier cliente (el ingreso se registra
        # en la oficina del que cobra, no en la de la póliza). Solo filtramos si se
        # pide una oficina explícita en la URL (?oficina=...), útil para el admin.
        if not request.user.is_authenticated:
            return Response({"detail": "Acceso denegado"}, status=403)
        oficina_keys = []
        if oficina_raw and oficina_raw.upper() != "ALL":
            _keys = _get_seguridad_oficina_brute(request, oficina_raw)
            if "BLOQUEADO" not in _keys:
                oficina_keys = _keys

        poliza_id = _to_int(request.query_params.get("poliza_id") or request.query_params.get("poliza"), None)
        ocultar_pagadas = _to_bool(request.query_params.get("ocultar_pagadas") or request.query_params.get("solo_pendientes"))

        pagado_raw = request.query_params.get("pagado")
        pagado_filter = None
        if pagado_raw not in (None, ""):
            pagado_filter = _to_bool(pagado_raw)

        vencidas = _to_bool(request.query_params.get("vencidas"))
        por_vencer = _to_bool(request.query_params.get("por_vencer"))
        por_vencer_dias = _to_int(request.query_params.get("por_vencer_dias"), 7)
        por_vencer_dias = max(1, min(365, por_vencer_dias or 7))

        ordering = (request.query_params.get("ordering") or "").strip()

        page_size = _to_int(request.query_params.get("page_size"), None)
        limit = _to_int(request.query_params.get("limit"), None)
        if page_size is None and limit is not None:
            page_size = limit
        if page_size is None:
            page_size = 150
        page_size = max(1, min(500, page_size))

        _PAGE_SIZE = page_size

        class _SearchPagination(PageNumberPagination):
            page_size = _PAGE_SIZE
            page_size_query_param = "page_size"
            max_page_size = 500

        total_cuotas_sq = Subquery(
            Cuota.objects.filter(poliza_id=OuterRef("poliza_id"))
            .order_by()
            .values("poliza_id")
            .annotate(mx=Max("cuota_nro"))
            .values("mx")[:1]
        )

        qs = (
            Cuota.objects.all()
            .select_related("poliza", "poliza__cliente")
            .annotate(total_cuotas=total_cuotas_sq)
            .only(
                "id",
                "cuota_nro",
                "monto",
                "pagado",
                "fecha_vencimiento",
                "fecha_pago",
                "pago_registrado_en",
                "forma_pago",
                "observaciones_pago",
                "ultima_observacion_pago",
                "poliza_id",
                "poliza__numero_poliza",
                "poliza__patente",
                "poliza__marca",
                "poliza__modelo",
                "poliza__cobertura",
                "poliza__oficina",
                "poliza__compania",
                "poliza__cantidad_cuotas",
                "poliza__cliente_id",
                "poliza__cliente__apellido",
                "poliza__cliente__nombre",
                "poliza__cliente__dni_cuit_cuil",
                "poliza__cliente__telefono",
            )
        )

        if poliza_id:
            qs = qs.filter(poliza_id=poliza_id)

        if pagado_filter is not None:
            qs = qs.filter(pagado=pagado_filter)
        elif ocultar_pagadas:
            qs = qs.filter(pagado=False)

        if oficina_keys:
            qs = qs.filter(_build_oficina_q_from_keys(oficina_keys))

        if (not poliza_id) and q:
            terminos = q.split()
            for t in terminos:
                qs = qs.filter(
                    Q(poliza__numero_poliza__icontains=t)
                    | Q(poliza__patente__icontains=t)
                    | Q(poliza__cliente__apellido__icontains=t)
                    | Q(poliza__cliente__nombre__icontains=t)
                    | Q(poliza__cliente__dni_cuit_cuil__icontains=t)
                )

        hoy = timezone.localdate()
        if vencidas:
            qs = qs.filter(pagado=False, fecha_vencimiento__lt=hoy)

        if por_vencer:
            hasta = hoy + timedelta(days=por_vencer_dias)
            qs = qs.filter(pagado=False, fecha_vencimiento__gte=hoy, fecha_vencimiento__lte=hasta)

        if ordering in ("vencimiento", "fecha_vencimiento"):
            qs = qs.order_by("fecha_vencimiento", "poliza_id", "cuota_nro", "id")
        elif ordering in ("-vencimiento", "-fecha_vencimiento"):
            qs = qs.order_by("-fecha_vencimiento", "poliza_id", "cuota_nro", "id")
        elif ordering == "poliza":
            qs = qs.order_by("poliza__numero_poliza", "cuota_nro", "id")
        elif ordering == "-poliza":
            qs = qs.order_by("-poliza__numero_poliza", "cuota_nro", "id")
        elif ordering == "cuota":
            qs = qs.order_by("cuota_nro", "poliza_id", "id")
        elif ordering == "-cuota":
            qs = qs.order_by("-cuota_nro", "poliza_id", "id")
        else:
            qs = qs.order_by("poliza_id", "cuota_nro", "id")

        from .serializers import CuotaFlatSerializer

        paginator = _SearchPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            ser = CuotaFlatSerializer(page, many=True, context={"only_cuotas": bool(poliza_id)})
            return paginator.get_paginated_response(ser.data)

        ser = CuotaFlatSerializer(qs[:page_size], many=True)
        return Response({"count": len(ser.data), "results": ser.data}, status=status.HTTP_200_OK)