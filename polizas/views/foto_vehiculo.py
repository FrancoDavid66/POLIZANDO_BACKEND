# polizas/views/foto_vehiculo.py

from rest_framework import viewsets, filters
from rest_framework.permissions import IsAuthenticated

from seguros_project.pagination import LargeResultsSetPagination
from polizas.models import FotoVehiculo
from polizas.serializers import FotoVehiculoSerializer

from polizas.utils.viewtools import hist_log as _hist_log

# 🚀 IMPORTAMOS NUESTRO MIXIN DE SEGURIDAD
from usuarios.mixins import MultiTenantMixin


class FotoVehiculoViewSet(MultiTenantMixin, viewsets.ModelViewSet):
    queryset = FotoVehiculo.objects.select_related("poliza").all()
    serializer_class = FotoVehiculoSerializer
    
    # 🚀 BLOQUEAMOS EL ACCESO LIBRE
    permission_classes = [IsAuthenticated]
    
    # 🚀 ENSEÑAMOS AL MIXIN CÓMO LLEGAR A LA OFICINA
    tenant_field = 'poliza__oficina'

    filter_backends = [filters.SearchFilter]
    search_fields = ["poliza__numero_poliza", "poliza__patente"]
    pagination_class = LargeResultsSetPagination

    def get_queryset(self):
        # 🚀 SUPER() AHORA PASA POR EL MULTITENANTMIXIN
        qs = super().get_queryset()
        
        poliza_id = self.request.query_params.get("poliza")
        tipo = self.request.query_params.get("tipo")
        origen = self.request.query_params.get("origen")
        tag = (self.request.query_params.get("tag") or self.request.query_params.get("etiqueta") or "").strip()
        
        if poliza_id:
            qs = qs.filter(poliza_id=poliza_id)
        if tipo:
            qs = qs.filter(tipo=tipo)
        if origen:
            qs = qs.filter(origen=origen)
        if tag:
            qs = qs.filter(etiquetas__contains=[tag])
        return qs

    def perform_create(self, serializer):
        instance = serializer.save()
        _hist_log(
            poliza=instance.poliza,
            tipo="FOTO_SUBIR",
            mensaje=f"Subida foto {instance.tipo}",
            severidad="INFO",
            data={
                "foto_id": instance.id,
                "tipo": instance.tipo,
                "origen": instance.origen,
                "url": instance.url,
                "public_id": instance.public_id,
                "etiquetas": instance.etiquetas,
            },
            request=self.request,
            subject=instance,
            categoria="FOTO",
        )

    def perform_destroy(self, instance):
        _hist_log(
            poliza=instance.poliza,
            tipo="FOTO_BORRAR",
            mensaje=f"Eliminada foto {instance.tipo}",
            severidad="WARNING",
            data={
                "foto_id": instance.id,
                "tipo": instance.tipo,
                "origen": instance.origen,
                "url": instance.url,
                "public_id": instance.public_id,
                "etiquetas": instance.etiquetas,
            },
            request=self.request,
            subject=instance,
            categoria="FOTO",
        )
        return super().perform_destroy(instance)