# clientes/portal_link.py
# ──────────────────────────────────────────────────────────────────────────
# Endpoint INTERNO (staff) para obtener el link del Portal del Asegurado de un
# cliente, para que desde la app puedan ver lo que ve el cliente.
#
#   GET  /api/clientes/<pk>/portal-link/  → asegura (crea si no existe) y devuelve el token.
#   POST /api/clientes/<pk>/portal-link/  → REGENERA el token (invalida el link viejo).
#
# Respuesta:
#   { "token": "abc...", "portal_path": "/#/portal/abc..." }
#
# El front arma la URL final con su propio origin:
#   `${window.location.origin}${portal_path}`
#
# Solo usuarios autenticados (empleados logueados).
# ──────────────────────────────────────────────────────────────────────────
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from .models import Cliente


class PortalLinkView(APIView):
    permission_classes = [IsAuthenticated]

    def _payload(self, token):
        return {
            "token": token or "",
            "portal_path": f"/#/portal/{token}" if token else "",
        }

    def get(self, request, pk):
        cli = Cliente.objects.filter(pk=pk).first()
        if not cli:
            return Response({"detail": "Cliente no encontrado."}, status=status.HTTP_404_NOT_FOUND)
        token = cli.asegurar_portal_token()
        return Response(self._payload(token), status=status.HTTP_200_OK)

    def post(self, request, pk):
        cli = Cliente.objects.filter(pk=pk).first()
        if not cli:
            return Response({"detail": "Cliente no encontrado."}, status=status.HTTP_404_NOT_FOUND)
        token = cli.regenerar_portal_token()
        return Response(self._payload(token), status=status.HTTP_200_OK)