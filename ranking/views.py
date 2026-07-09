# ranking/views.py
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .services import ranking_puntos


class RankingView(APIView):
    """GET /api/ranking/?rango=hoy|semana|mes&categoria=control_diario  (lo ven todos)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        rango = request.query_params.get("rango") or "mes"
        categoria = request.query_params.get("categoria") or None
        data = ranking_puntos(rango=rango, categoria=categoria)
        return Response(data)