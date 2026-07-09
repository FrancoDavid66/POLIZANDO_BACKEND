# polizas/views/mixins/duplicados.py

from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from django.db.models import Count
from django.db import transaction

import math

from polizas.domain.duplicados import (
    dup_parse_pagination,
    dup_patente_norm_expr,
    dup_poliza_rows,
)


class PolizaDuplicadosMixin:
    @action(detail=False, methods=["get"], url_path="duplicadas", permission_classes=[AllowAny])
    def duplicadas(self, request):
        por = (request.query_params.get("por") or "numero_poliza_compania").strip()
        page, page_size = dup_parse_pagination(request)

        try:
            per_group = int((request.query_params.get("per_group") or "12").strip() or 12)
        except Exception:
            per_group = 12
        per_group = max(1, min(200, per_group))

        base_qs = self.filter_queryset(self.get_queryset())
        pat_norm = dup_patente_norm_expr()

        if por == "numero_poliza":
            groups_qs = (
                base_qs.exclude(numero_poliza__isnull=True)
                .exclude(numero_poliza__exact="")
                .values("numero_poliza")
                .annotate(c=Count("id"))
                .filter(c__gt=1)
                .order_by("-c", "numero_poliza")
            )

            total_groups = groups_qs.count()
            total_pages = max(1, int(math.ceil(total_groups / page_size))) if page_size else 1
            page = min(page, total_pages)
            start = (page - 1) * page_size
            keys = list(groups_qs[start : start + page_size].values_list("numero_poliza", flat=True))

            results = []
            for key in keys:
                qs = base_qs.filter(numero_poliza=key)
                results.append({"key": str(key), "count": qs.count(), "rows": dup_poliza_rows(qs, per_group)})

            return Response(
                {
                    "por": por,
                    "count_groups": total_groups,
                    "page": page,
                    "page_size": page_size,
                    "results": results,
                    "next": page + 1 if page < total_pages else None,
                    "previous": page - 1 if page > 1 else None,
                },
                status=status.HTTP_200_OK,
            )

        if por == "numero_poliza_compania":
            groups_qs = (
                base_qs.exclude(numero_poliza__isnull=True)
                .exclude(numero_poliza__exact="")
                .exclude(compania__isnull=True)
                .exclude(compania__exact="")
                .values("numero_poliza", "compania")
                .annotate(c=Count("id"))
                .filter(c__gt=1)
                .order_by("-c", "compania", "numero_poliza")
            )

            total_groups = groups_qs.count()
            total_pages = max(1, int(math.ceil(total_groups / page_size))) if page_size else 1
            page = min(page, total_pages)
            start = (page - 1) * page_size
            keys = list(groups_qs[start : start + page_size])

            results = []
            for g in keys:
                num = g.get("numero_poliza")
                comp = g.get("compania")
                qs = base_qs.filter(numero_poliza=num, compania=comp)
                results.append({"key": f"{comp} | {num}", "count": qs.count(), "rows": dup_poliza_rows(qs, per_group)})

            return Response(
                {
                    "por": por,
                    "count_groups": total_groups,
                    "page": page,
                    "page_size": page_size,
                    "results": results,
                    "next": page + 1 if page < total_pages else None,
                    "previous": page - 1 if page > 1 else None,
                },
                status=status.HTTP_200_OK,
            )

        if por == "patente_activa":
            groups_qs = (
                base_qs.filter(estado="activa")
                .exclude(patente__isnull=True)
                .exclude(patente__exact="")
                .annotate(_pat=pat_norm)
                .exclude(_pat__exact="")
                .values("_pat")
                .annotate(c=Count("id"))
                .filter(c__gt=1)
                .order_by("-c", "_pat")
            )

            total_groups = groups_qs.count()
            total_pages = max(1, int(math.ceil(total_groups / page_size))) if page_size else 1
            page = min(page, total_pages)
            start = (page - 1) * page_size
            keys = list(groups_qs[start : start + page_size].values_list("_pat", flat=True))

            results = []
            for pat in keys:
                qs = base_qs.filter(estado="activa").annotate(_pat=pat_norm).filter(_pat=pat)
                results.append({"key": str(pat), "count": qs.count(), "rows": dup_poliza_rows(qs, per_group)})

            return Response(
                {
                    "por": por,
                    "count_groups": total_groups,
                    "page": page,
                    "page_size": page_size,
                    "results": results,
                    "next": page + 1 if page < total_pages else None,
                    "previous": page - 1 if page > 1 else None,
                },
                status=status.HTTP_200_OK,
            )

        if por == "cliente_patente_activa":
            groups_qs = (
                base_qs.filter(estado="activa")
                .exclude(patente__isnull=True)
                .exclude(patente__exact="")
                .exclude(cliente_id__isnull=True)
                .annotate(_pat=pat_norm)
                .exclude(_pat__exact="")
                .values("cliente_id", "_pat")
                .annotate(c=Count("id"))
                .filter(c__gt=1)
                .order_by("-c", "cliente_id", "_pat")
            )

            total_groups = groups_qs.count()
            total_pages = max(1, int(math.ceil(total_groups / page_size))) if page_size else 1
            page = min(page, total_pages)
            start = (page - 1) * page_size
            keys = list(groups_qs[start : start + page_size])

            results = []
            for g in keys:
                cli = g.get("cliente_id")
                pat = g.get("_pat")
                qs = base_qs.filter(estado="activa", cliente_id=cli).annotate(_pat=pat_norm).filter(_pat=pat)
                results.append({"key": f"cliente:{cli} | {pat}", "count": qs.count(), "rows": dup_poliza_rows(qs, per_group)})

            return Response(
                {
                    "por": por,
                    "count_groups": total_groups,
                    "page": page,
                    "page_size": page_size,
                    "results": results,
                    "next": page + 1 if page < total_pages else None,
                    "previous": page - 1 if page > 1 else None,
                },
                status=status.HTTP_200_OK,
            )

        if por == "patente":
            # Igual que patente_activa pero SIN filtrar por estado: agrupa TODAS las pólizas
            # (activas, vencidas, canceladas) que comparten la misma patente.
            groups_qs = (
                base_qs
                .exclude(patente__isnull=True)
                .exclude(patente__exact="")
                .annotate(_pat=pat_norm)
                .exclude(_pat__exact="")
                .values("_pat")
                .annotate(c=Count("id"))
                .filter(c__gt=1)
                .order_by("-c", "_pat")
            )

            total_groups = groups_qs.count()
            total_pages = max(1, int(math.ceil(total_groups / page_size))) if page_size else 1
            page = min(page, total_pages)
            start = (page - 1) * page_size
            keys = list(groups_qs[start : start + page_size].values_list("_pat", flat=True))

            results = []
            for pat in keys:
                qs = base_qs.annotate(_pat=pat_norm).filter(_pat=pat)
                results.append({"key": str(pat), "count": qs.count(), "rows": dup_poliza_rows(qs, per_group)})

            return Response(
                {
                    "por": por,
                    "count_groups": total_groups,
                    "page": page,
                    "page_size": page_size,
                    "results": results,
                    "next": page + 1 if page < total_pages else None,
                    "previous": page - 1 if page > 1 else None,
                },
                status=status.HTTP_200_OK,
            )

        if por == "cliente_patente":
            # Mismo cliente + misma patente, SIN filtrar por estado.
            groups_qs = (
                base_qs
                .exclude(patente__isnull=True)
                .exclude(patente__exact="")
                .exclude(cliente_id__isnull=True)
                .annotate(_pat=pat_norm)
                .exclude(_pat__exact="")
                .values("cliente_id", "_pat")
                .annotate(c=Count("id"))
                .filter(c__gt=1)
                .order_by("-c", "cliente_id", "_pat")
            )

            total_groups = groups_qs.count()
            total_pages = max(1, int(math.ceil(total_groups / page_size))) if page_size else 1
            page = min(page, total_pages)
            start = (page - 1) * page_size
            keys = list(groups_qs[start : start + page_size])

            results = []
            for g in keys:
                cli = g.get("cliente_id")
                pat = g.get("_pat")
                qs = base_qs.filter(cliente_id=cli).annotate(_pat=pat_norm).filter(_pat=pat)
                results.append({"key": f"cliente:{cli} | {pat}", "count": qs.count(), "rows": dup_poliza_rows(qs, per_group)})

            return Response(
                {
                    "por": por,
                    "count_groups": total_groups,
                    "page": page,
                    "page_size": page_size,
                    "results": results,
                    "next": page + 1 if page < total_pages else None,
                    "previous": page - 1 if page > 1 else None,
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {
                "detail": "Parámetro 'por' inválido.",
                "por_validos": ["numero_poliza", "numero_poliza_compania", "patente_activa", "patente", "cliente_patente_activa", "cliente_patente"],
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    @action(detail=False, methods=["post"], url_path="resolver-duplicado", permission_classes=[IsAuthenticated])
    def resolver_duplicado(self, request):
        """
        POST /api/polizas/resolver-duplicado/
        Body: { "activa_id": 6322, "vencer_ids": [5432, 4464] }

        Deja UNA póliza como 'activa' y pasa las demás del grupo a 'vencida'.
        NO borra nada: las pólizas viejas conservan sus cuotas/pagos/historial.
        """
        data = request.data or {}
        try:
            activa_id = int(data.get("activa_id"))
        except (TypeError, ValueError):
            return Response({"error": "Falta 'activa_id' válido."}, status=status.HTTP_400_BAD_REQUEST)

        vencer_ids = []
        for x in (data.get("vencer_ids") or []):
            try:
                xi = int(x)
            except (TypeError, ValueError):
                continue
            if xi != activa_id:
                vencer_ids.append(xi)
        vencer_ids = list(dict.fromkeys(vencer_ids))
        if not vencer_ids:
            return Response({"error": "No hay pólizas para vencer."}, status=status.HTTP_400_BAD_REQUEST)

        Model = self.get_queryset().model
        try:
            with transaction.atomic():
                Model.objects.filter(pk=activa_id).update(estado="activa")
                # Las duplicadas pasan a "finalizada" (no "vencida") para no confundirlas
                # con morosos y para que el sistema de recordatorios no las notifique.
                n = Model.objects.filter(pk__in=vencer_ids).update(estado="finalizada")
        except Exception as e:
            return Response({"error": f"No se pudo resolver: {e}"}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"ok": True, "activa_id": activa_id, "vencidas": vencer_ids, "cantidad_vencidas": n},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="duplicadas/resumen", permission_classes=[AllowAny])
    def duplicadas_resumen(self, request):
        from django.db.models import Count  # local import por seguridad

        base_qs = self.filter_queryset(self.get_queryset())
        pat_norm = dup_patente_norm_expr()

        g_num = (
            base_qs.exclude(numero_poliza__isnull=True)
            .exclude(numero_poliza__exact="")
            .values("numero_poliza")
            .annotate(c=Count("id"))
            .filter(c__gt=1)
        )
        g_num_comp = (
            base_qs.exclude(numero_poliza__isnull=True)
            .exclude(numero_poliza__exact="")
            .exclude(compania__isnull=True)
            .exclude(compania__exact="")
            .values("numero_poliza", "compania")
            .annotate(c=Count("id"))
            .filter(c__gt=1)
        )
        g_pat = (
            base_qs.filter(estado="activa")
            .exclude(patente__isnull=True)
            .exclude(patente__exact="")
            .annotate(_pat=pat_norm)
            .exclude(_pat__exact="")
            .values("_pat")
            .annotate(c=Count("id"))
            .filter(c__gt=1)
        )
        g_cli_pat = (
            base_qs.filter(estado="activa")
            .exclude(patente__isnull=True)
            .exclude(patente__exact="")
            .exclude(cliente_id__isnull=True)
            .annotate(_pat=pat_norm)
            .exclude(_pat__exact="")
            .values("cliente_id", "_pat")
            .annotate(c=Count("id"))
            .filter(c__gt=1)
        )

        g_pat_all = (
            base_qs.exclude(patente__isnull=True)
            .exclude(patente__exact="")
            .annotate(_pat=pat_norm)
            .exclude(_pat__exact="")
            .values("_pat")
            .annotate(c=Count("id"))
            .filter(c__gt=1)
        )
        g_cli_pat_all = (
            base_qs.exclude(patente__isnull=True)
            .exclude(patente__exact="")
            .exclude(cliente_id__isnull=True)
            .annotate(_pat=pat_norm)
            .exclude(_pat__exact="")
            .values("cliente_id", "_pat")
            .annotate(c=Count("id"))
            .filter(c__gt=1)
        )

        return Response(
            {
                "numero_poliza": g_num.count(),
                "numero_poliza_compania": g_num_comp.count(),
                "patente_activa": g_pat.count(),
                "patente": g_pat_all.count(),
                "cliente_patente_activa": g_cli_pat.count(),
                "cliente_patente": g_cli_pat_all.count(),
            },
            status=status.HTTP_200_OK,
        )