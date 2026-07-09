# tareas/views.py
from django.utils import timezone

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from polizas.models import Poliza
from .services import armar_tareas_dia, DIAS_DEFAULT
from .models import TareaCompletada


def _es_admin(user) -> bool:
    return bool(
        getattr(user, "is_superuser", False)
        or (hasattr(user, "perfil") and getattr(user.perfil, "rol", None) == "ADMIN")
    )


def _oficina_del_user(user):
    return getattr(getattr(user, "perfil", None), "oficina_id", None)


class TareasDiaView(APIView):
    """
    GET /api/tareas/dia/   (?dias=60  ?oficina=2 [admin])
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user

        try:
            dias = int(request.query_params.get("dias") or DIAS_DEFAULT)
        except (TypeError, ValueError):
            dias = DIAS_DEFAULT

        if _es_admin(user):
            ofi_id = request.query_params.get("oficina") or None
        else:
            ofi_id = _oficina_del_user(user)
            if not ofi_id:
                return Response(
                    {"detail": "Tu usuario no tiene oficina asignada."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        return Response(armar_tareas_dia(oficina_id=ofi_id, dias=dias))


class MarcarPolizaEnviadaView(APIView):
    """POST /api/tareas/marcar-enviada/   body: {"poliza_id": 123}"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        poliza_id = request.data.get("poliza_id")
        if not poliza_id:
            return Response({"detail": "Falta poliza_id."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            poliza = Poliza.objects.get(id=poliza_id)
        except Poliza.DoesNotExist:
            return Response({"detail": "Póliza no encontrada."}, status=status.HTTP_404_NOT_FOUND)

        user = request.user
        if not _es_admin(user):
            ofi_id = _oficina_del_user(user)
            if poliza.oficina_id and ofi_id and poliza.oficina_id != ofi_id:
                return Response(
                    {"detail": "No podés modificar pólizas de otra oficina."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        poliza.poliza_enviada = True
        poliza.poliza_enviada_en = timezone.now()
        poliza.save(update_fields=["poliza_enviada", "poliza_enviada_en"])

        # 🆕 Registramos la tarea completada (para el reporte diario)
        TareaCompletada.objects.create(
            tipo="enviar",
            oficina_id=poliza.oficina_id or _oficina_del_user(user),
            usuario=user if getattr(user, "is_authenticated", False) else None,
            poliza_id=poliza.id,
        )

        return Response({"ok": True, "poliza_id": poliza.id})


class RegistrarTareaCompletadaView(APIView):
    """
    POST /api/tareas/registrar-completada/
    body: {"tipo": "datos_cliente", "cliente_id": 5}  (o "poliza_id")
    Lo llaman los modales del panel cuando completan una tarea.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        tipo = request.data.get("tipo")
        if tipo not in dict(TareaCompletada.TIPOS):
            return Response({"detail": "Tipo de tarea inválido."}, status=status.HTTP_400_BAD_REQUEST)

        TareaCompletada.objects.create(
            tipo=tipo,
            oficina_id=_oficina_del_user(request.user),
            usuario=request.user if getattr(request.user, "is_authenticated", False) else None,
            poliza_id=request.data.get("poliza_id") or None,
            cliente_id=request.data.get("cliente_id") or None,
        )
        return Response({"ok": True})