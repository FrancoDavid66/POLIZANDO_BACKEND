# polizas/views/portal_cupon.py
#
# Endpoints PÚBLICOS (sin login) para que el cliente vea y confirme sus cupones
# de robo desde el link /cupon/<token>.
#
# El token (Poliza.token_portal) es la llave: identifica la póliza sin usuario
# ni contraseña, y es imposible de adivinar.
#
# Rutas (se registran en polizas/urls.py):
#   GET  /api/polizas/portal/cupon/<uuid:token>/            -> datos + cupones
#   POST /api/polizas/portal/cupon/<uuid:token>/reportar/   -> marca "Ya pagué"

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status

from django.shortcuts import get_object_or_404
from django.utils import timezone

from polizas.models import Poliza, CuponRobo


def _cupon_publico(c):
    """Solo los campos que el cliente necesita ver (nada sensible)."""
    return {
        "id": c.id,
        "periodo_desde": c.periodo_desde,
        "periodo_hasta": c.periodo_hasta,
        "fecha_vencimiento": c.fecha_vencimiento,
        "monto": c.monto,
        "estado": c.estado,                 # PENDIENTE / REPORTADO / PAGADA / VENCIDA
        "reportado_en": c.reportado_en,
    }


def _primer_nombre(poliza):
    cliente = getattr(poliza, "cliente", None)
    nom = (getattr(cliente, "nombre", "") or "").strip() if cliente else ""
    return nom.split()[0].title() if nom else ""


class PortalCuponView(APIView):
    """GET público: devuelve los cupones de la póliza identificada por el token."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, token):
        poliza = get_object_or_404(Poliza, token_portal=token)
        cupones = poliza.cupones_robo.all().order_by("fecha_vencimiento", "id")
        vehiculo = f"{(poliza.marca or '').strip()} {(poliza.modelo or '').strip()}".strip()
        return Response({
            "nombre": _primer_nombre(poliza),
            "vehiculo": vehiculo or "Vehículo",
            "patente": (poliza.patente or "").upper(),
            "cupones": [_cupon_publico(c) for c in cupones],
        })


class PortalCuponReportarView(APIView):
    """POST público: el cliente confirma que pagó un cupón → pasa a REPORTADO."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, token):
        poliza = get_object_or_404(Poliza, token_portal=token)

        cupon_id = request.data.get("cupon_id")
        if not cupon_id:
            return Response({"ok": False, "error": "Falta cupon_id."},
                            status=status.HTTP_400_BAD_REQUEST)

        cupon = get_object_or_404(CuponRobo, id=cupon_id, poliza=poliza)

        # Si ya está pagado/confirmado por la oficina, no lo tocamos.
        if cupon.estado == CuponRobo.Estado.PAGADA:
            return Response({"ok": True, "estado": cupon.estado,
                             "msg": "Ese cupón ya figura como pagado."})

        cupon.estado = CuponRobo.Estado.REPORTADO
        cupon.reportado_en = timezone.now()
        cupon.save(update_fields=["estado", "reportado_en"])

        return Response({"ok": True, "estado": cupon.estado,
                         "msg": "¡Gracias! Registramos tu aviso de pago."})