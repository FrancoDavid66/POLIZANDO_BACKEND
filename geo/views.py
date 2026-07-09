# geo/views.py
from rest_framework.viewsets import ModelViewSet
from rest_framework.response import Response

from .models import GeoItem
from .serializers import GeoItemSerializer


class GeoItemViewSet(ModelViewSet):
    queryset = GeoItem.objects.all().order_by("-creado_en")
    serializer_class = GeoItemSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        request = self.request

        tipo = request.query_params.get("tipo")
        activo = request.query_params.get("activo")

        if tipo:
            qs = qs.filter(tipo=tipo)

        if activo is not None:
            if activo.lower() in ["true", "1", "yes", "si"]:
                qs = qs.filter(activo=True)
            elif activo.lower() in ["false", "0", "no"]:
                qs = qs.filter(activo=False)

        return qs

    def create(self, request, *args, **kwargs):
        # Debug opcional para ver qué está llegando desde el front
        print("🚨 POST incoming:", request.data)
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            print("❌ Serializer errors:", serializer.errors)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=201)
