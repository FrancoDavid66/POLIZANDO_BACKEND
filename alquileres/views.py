from rest_framework import viewsets
from .models import Propietario, Inquilino, Alquiler, CuotaAlquiler, Garante
from .serializers import (
    PropietarioSerializer,
    InquilinoSerializer,
    InquilinoWithGarantesSerializer,
    AlquilerReadSerializer,
    AlquilerWriteSerializer,
    CuotaAlquilerSerializer,
    GaranteSerializer
)

class PropietarioViewSet(viewsets.ModelViewSet):
    queryset = Propietario.objects.all()
    serializer_class = PropietarioSerializer


class InquilinoViewSet(viewsets.ModelViewSet):
    queryset = Inquilino.objects.all()

    def get_serializer_class(self):
        if self.action in ['list', 'retrieve']:
            return InquilinoWithGarantesSerializer
        return InquilinoSerializer


class GaranteViewSet(viewsets.ModelViewSet):
    queryset = Garante.objects.all()
    serializer_class = GaranteSerializer


class AlquilerViewSet(viewsets.ModelViewSet):
    queryset = Alquiler.objects.all()

    def get_serializer_class(self):
        if self.action in ['list', 'retrieve']:
            return AlquilerReadSerializer
        return AlquilerWriteSerializer


class CuotaAlquilerViewSet(viewsets.ModelViewSet):
    queryset = CuotaAlquiler.objects.all()
    serializer_class = CuotaAlquilerSerializer
