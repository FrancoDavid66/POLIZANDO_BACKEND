# competencia/views.py
import logging

from rest_framework import viewsets, permissions

from .models import (
    Competidor,
    CompetidorCanal,
    CompetidorUbicacion,
    MiPrecioReferencia,
    OficinaMapa,
    OportunidadCompetencia,
)
from .serializers import (
    CompetidorSerializer,
    CompetidorCanalSerializer,
    CompetidorUbicacionSerializer,
    MiPrecioReferenciaSerializer,
    OficinaMapaSerializer,
    OportunidadCompetenciaSerializer,
)
from .utils.geo_sync import (
    sync_ubicacion_competencia_to_geo,
    desactivar_ubicacion_competencia_en_geo,
)

logger = logging.getLogger(__name__)


class BaseAuthViewSet(viewsets.ModelViewSet):
    """
    ViewSet base para Competencia.
    🔒 FIX de seguridad: ahora requiere usuario autenticado.
    """

    permission_classes = [permissions.IsAuthenticated]


class CompetidorViewSet(BaseAuthViewSet):
    queryset = Competidor.objects.all().order_by("nombre")
    serializer_class = CompetidorSerializer


class CompetidorCanalViewSet(BaseAuthViewSet):
    queryset = CompetidorCanal.objects.all().select_related("competidor")
    serializer_class = CompetidorCanalSerializer


class CompetidorUbicacionViewSet(BaseAuthViewSet):
    """
    Cada fila de la tabla de competencia.
    Al crear/editar/borrar, sincroniza el punto con el mapa GEO.
    """

    queryset = (
        CompetidorUbicacion.objects.all()
        .select_related("competidor")
        .order_by("competidor__nombre", "direccion")
    )
    serializer_class = CompetidorUbicacionSerializer

    def perform_create(self, serializer):
        instance = serializer.save()
        logger.info(
            "[COMPETENCIA] Ubicación creada id=%s lat=%s lng=%s",
            instance.id,
            instance.latitud,
            instance.longitud,
        )
        self._sync_geo(instance, accion="create")

    def perform_update(self, serializer):
        instance = serializer.save()
        logger.info(
            "[COMPETENCIA] Ubicación actualizada id=%s lat=%s lng=%s",
            instance.id,
            instance.latitud,
            instance.longitud,
        )
        self._sync_geo(instance, accion="update")

    def perform_destroy(self, instance):
        logger.info("[COMPETENCIA] Eliminando ubicación id=%s", instance.id)
        try:
            desactivar_ubicacion_competencia_en_geo(instance)
        except Exception as e:
            logger.exception(
                "[COMPETENCIA] Error desactivando en GEO id=%s: %s",
                instance.id,
                e,
            )
        super().perform_destroy(instance)

    @staticmethod
    def _sync_geo(instance, accion=""):
        try:
            sync_ubicacion_competencia_to_geo(instance)
        except Exception as e:
            logger.exception(
                "[COMPETENCIA] Error sincronizando a GEO (%s) id=%s: %s",
                accion,
                instance.id,
                e,
            )


class MiPrecioReferenciaViewSet(BaseAuthViewSet):
    """
    CRUD de tus precios propios de referencia.
    Ordenado por cobertura, compañía y ciudad.
    """

    queryset = MiPrecioReferencia.objects.all().order_by(
        "cobertura", "compania", "ciudad"
    )
    serializer_class = MiPrecioReferenciaSerializer


class OficinaMapaViewSet(BaseAuthViewSet):
    queryset = OficinaMapa.objects.all().order_by("nombre")
    serializer_class = OficinaMapaSerializer


class OportunidadCompetenciaViewSet(BaseAuthViewSet):
    queryset = OportunidadCompetencia.objects.all().select_related(
        "competidor", "cliente"
    )
    serializer_class = OportunidadCompetenciaSerializer