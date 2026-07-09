# polizas/views/mixins/vencimientos.py

from rest_framework.decorators import action
# 🚀 CAMBIAMOS AllowAny POR IsAuthenticated
from rest_framework.permissions import IsAuthenticated 
from rest_framework.response import Response
from rest_framework import status, filters

from django.db.models import F, DateField
from django.db.models.functions import Coalesce, Cast

from polizas.domain.annotations import with_ultima_cuota_vencimiento
from polizas.services.vencimientos import build_vencimientos_queryset, build_vencimientos_resumen


class PolizaVencimientosMixin:
    def _ensure_vto_referencia_annotations(self, qs):
        """
        Garantiza que exista vto_referencia/vto_referencia_date para:
        - ordering=vto_referencia
        - filtros por fechas del service
        """
        vto_ref_expr = Coalesce(
            F("proxima_vencimiento_impaga"),
            F("ultima_cuota_vencimiento"),
            F("fecha_vencimiento"),
        )
        qs = qs.annotate(vto_referencia=vto_ref_expr)
        qs = qs.annotate(vto_referencia_date=Cast(F("vto_referencia"), output_field=DateField()))
        return qs

    # 🚀 APLICAMOS EL PERMISO IsAuthenticated AQUÍ
    @action(detail=False, methods=["get"], url_path="vencimientos", permission_classes=[IsAuthenticated])
    def vencimientos(self, request):
        """
        GET /api/polizas/vencimientos/?past_days=30&future_days=3&modo=all
        modo: all | vencidas | hoy | por_vencer
        """
        base_qs = self.get_queryset()

        # aplicar search/filtros excepto ordering
        for backend in self.filter_backends:
            if backend is filters.OrderingFilter:
                continue
            base_qs = backend().filter_queryset(request, base_qs, self)

        # ✅ FIX: el helper ahora recibe SOLO qs
        base_qs = with_ultima_cuota_vencimiento(base_qs)

        base_qs = self._ensure_vto_referencia_annotations(base_qs)

        qs = build_vencimientos_queryset(base_qs, request.query_params)

        # ordering al final (si vino)
        if (request.query_params.get("ordering") or "").strip():
            qs = filters.OrderingFilter().filter_queryset(request, qs, self)

        page = self.paginate_queryset(qs)
        if page is not None:
            ser = self.get_serializer(page, many=True)
            return self.get_paginated_response(ser.data)

        ser = self.get_serializer(qs, many=True)
        return Response(ser.data, status=status.HTTP_200_OK)

    # 🚀 APLICAMOS EL PERMISO IsAuthenticated AQUÍ TAMBIÉN
    @action(detail=False, methods=["get"], url_path="vencimientos/resumen", permission_classes=[IsAuthenticated])
    def vencimientos_resumen(self, request):
        base_qs = self.get_queryset()

        # aplicar search/filtros excepto ordering (resumen no n ec e sita  ordenar)
        for backend in self.filter_backends:
            if backend is filters.OrderingFilter:
                continue
            base_qs = backend().filter_queryset(request, base_qs, self)

        # ✅ FIX: el helper ahora recibe SOLO qs
        base_qs = with_ultima_cuota_vencimiento(base_qs)

        base_qs = self._ensure_vto_referencia_annotations(base_qs)

        payload = build_vencimientos_resumen(base_qs, request.query_params)
        return Response(payload, status=status.HTTP_200_OK)