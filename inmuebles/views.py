# inmuebles/views.py
from rest_framework import viewsets, filters
from .models import Propiedad, Alquiler, CuotaAlquiler, Inquilino, Propietario
from .serializers import (
    PropiedadSerializer,
    AlquilerSerializer,
    CuotaAlquilerSerializer,
    InquilinoSerializer,
    PropietarioSerializer,
)

class PropiedadViewSet(viewsets.ModelViewSet):
    queryset = Propiedad.objects.all().order_by('-fecha_publicacion')
    serializer_class = PropiedadSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['direccion', 'localidad', 'partido', 'tipo', 'estado']


class AlquilerViewSet(viewsets.ModelViewSet):
    queryset = Alquiler.objects.all().order_by('-fecha_inicio')
    serializer_class = AlquilerSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['direccion', 'partido', 'localidad']


class CuotaAlquilerViewSet(viewsets.ModelViewSet):
    queryset = CuotaAlquiler.objects.all().order_by('fecha_vencimiento')
    serializer_class = CuotaAlquilerSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['alquiler__direccion']


class InquilinoViewSet(viewsets.ModelViewSet):
    queryset = Inquilino.objects.all().order_by('apellido')
    serializer_class = InquilinoSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['nombre', 'apellido', 'dni']


class PropietarioViewSet(viewsets.ModelViewSet):
    queryset = Propietario.objects.all().order_by('apellido')
    serializer_class = PropietarioSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['nombre', 'apellido', 'dni']
