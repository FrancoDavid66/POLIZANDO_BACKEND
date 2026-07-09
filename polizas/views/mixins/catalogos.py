# polizas/views/mixins/catalogos.py

from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

from polizas.models import Poliza
from polizas.utils.constants import list_companias


class PolizaCatalogosMixin:
    @action(detail=False, methods=["get"], url_path="companias", permission_classes=[AllowAny])
    def companias(self, request):
        vals = list_companias()
        flat = (request.query_params.get("flat") or "").lower() in {"1", "true", "t", "yes", "y"}
        if flat:
            return Response(vals, status=status.HTTP_200_OK)
        data = [{"id": v, "nombre": v} for v in vals]
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="coberturas", permission_classes=[AllowAny])
    def coberturas(self, request):
        vals = (
            Poliza.objects.values_list("cobertura", flat=True)
            .exclude(cobertura__isnull=True)
            .exclude(cobertura__exact="")
            .distinct()
            .order_by("cobertura")
        )
        flat = (request.query_params.get("flat") or "").lower() in {"1", "true", "t", "yes", "y"}
        if flat:
            return Response(list(vals), status=status.HTTP_200_OK)
        data = [{"id": v, "nombre": v} for v in vals]
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="oficinas", permission_classes=[AllowAny])
    def oficinas(self, request):
        """
        GET /api/polizas/oficinas/?flat=1
        - Si oficina es FK: devuelve [{id, nombre}] o flat=[nombre]
        - Si oficina es campo plano: devuelve [{id, nombre}] con id=valor o flat=[valor]
        """
        flat = (request.query_params.get("flat") or "0").lower() in {"1", "true", "t", "yes", "y"}

        qs = Poliza.objects.all()
        try:
            f = Poliza._meta.get_field("oficina")
            if getattr(f, "is_relation", False):
                rel = getattr(f, "remote_field", None)
                rel_model = getattr(rel, "model", None)

                if rel_model is not None and hasattr(rel_model, "nombre"):
                    rows = (
                        qs.values("oficina_id", "oficina__nombre")
                        .exclude(oficina_id__isnull=True)
                        .distinct()
                        .order_by("oficina__nombre")
                    )
                    if flat:
                        out = [r["oficina__nombre"] for r in rows if (r.get("oficina__nombre") or "").strip()]
                        return Response(out, status=status.HTTP_200_OK)

                    out = [{"id": r["oficina_id"], "nombre": (r["oficina__nombre"] or str(r["oficina_id"]))} for r in rows]
                    return Response(out, status=status.HTTP_200_OK)

                rows = (
                    qs.values_list("oficina_id", flat=True)
                    .exclude(oficina_id__isnull=True)
                    .distinct()
                    .order_by("oficina_id")
                )
                if flat:
                    return Response([str(x) for x in rows], status=status.HTTP_200_OK)
                return Response([{"id": int(x), "nombre": str(x)} for x in rows], status=status.HTTP_200_OK)

            rows = (
                qs.values_list("oficina", flat=True)
                .exclude(oficina__isnull=True)
                .exclude(oficina__exact="")
                .distinct()
                .order_by("oficina")
            )
            if flat:
                return Response([str(x) for x in rows], status=status.HTTP_200_OK)
            return Response([{"id": str(x), "nombre": str(x)} for x in rows], status=status.HTTP_200_OK)

        except Exception:
            rows = (
                qs.values_list("oficina", flat=True)
                .exclude(oficina__isnull=True)
                .exclude(oficina__exact="")
                .distinct()
                .order_by("oficina")
            )
            if flat:
                return Response([str(x) for x in rows], status=status.HTTP_200_OK)
            return Response([{"id": str(x), "nombre": str(x)} for x in rows], status=status.HTTP_200_OK)
