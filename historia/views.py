import csv
from io import StringIO
from django.http import HttpResponse
from django.db.models import Q
from rest_framework import viewsets, filters, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from historia.models import PolizaEvento
from historia.serializers import PolizaEventoSerializer
from historia.utils import create_event

class PolizaEventoViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/polizas/historia/?poliza=<id>&categoria=&tipo=&actor=&severity=&q=&desde=&hasta=&page=
    GET /api/polizas/historia/<id>/
    """
    queryset = PolizaEvento.objects.select_related("poliza", "actor").all()
    serializer_class = PolizaEventoSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [filters.SearchFilter]
    search_fields = ["mensaje", "actor_name"]

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params

        if p.get("poliza"):
            qs = qs.filter(poliza_id=p.get("poliza"))
        if p.get("categoria"):
            qs = qs.filter(categoria=p.get("categoria"))
        if p.get("tipo"):
            qs = qs.filter(tipo=p.get("tipo"))
        if p.get("severity"):
            qs = qs.filter(severidad=p.get("severity"))
        if p.get("actor"):
            qs = qs.filter(Q(actor_name__icontains=p.get("actor")) | Q(actor__username__icontains=p.get("actor")))
        if p.get("desde"):
            qs = qs.filter(created_at__gte=p.get("desde"))
        if p.get("hasta"):
            qs = qs.filter(created_at__lte=p.get("hasta"))
        if p.get("q"):
            q = p.get("q")
            qs = qs.filter(Q(mensaje__icontains=q) | Q(actor_name__icontains=q))

        return qs.order_by("-created_at")

    @action(detail=False, methods=["post"], url_path="nota", permission_classes=[permissions.AllowAny])
    def crear_nota(self, request):
        """
        Body: { "poliza": <id>, "mensaje": "...", "data": {...}, "severidad": "INFO|WARNING|ERROR|ACTION" }
        """
        poliza_id = request.data.get("poliza")
        mensaje = request.data.get("mensaje") or ""
        data = request.data.get("data") or {}
        severidad = request.data.get("severidad") or "INFO"
        if not poliza_id or not mensaje:
            return Response({"detail": "poliza y mensaje son obligatorios"}, status=status.HTTP_400_BAD_REQUEST)
        from polizas.models import Poliza
        try:
            poliza = Poliza.objects.get(pk=poliza_id)
        except Poliza.DoesNotExist:
            return Response({"detail": "Póliza no encontrada"}, status=status.HTTP_404_NOT_FOUND)
        actor = request.user if getattr(request, "user", None) and request.user.is_authenticated else None
        create_event(
            poliza=poliza,
            tipo=PolizaEvento.Tipo.NOTA,
            categoria=PolizaEvento.Categoria.NOTA,
            severidad=severidad,
            mensaje=mensaje,
            data=data,
            actor=actor,
            source="USER" if actor else "SYSTEM",
        )
        return Response({"ok": True}, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], url_path="export", permission_classes=[permissions.AllowAny])
    def export_csv(self, request):
        qs = self.get_queryset()
        out = StringIO()
        wr = csv.writer(out)
        wr.writerow(["id","poliza","categoria","tipo","severidad","mensaje","actor","created_at"])
        for ev in qs[:10000]:  # límite sano
            wr.writerow([ev.id, ev.poliza_id, ev.categoria, ev.tipo, ev.severidad, ev.mensaje, ev.actor_name or "", ev.created_at.isoformat()])
        resp = HttpResponse(out.getvalue(), content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="historia.csv"'
        return resp
