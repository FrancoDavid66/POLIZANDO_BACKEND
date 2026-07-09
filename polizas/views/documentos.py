# polizas/views/documentos.py

from rest_framework import viewsets, filters
from rest_framework.permissions import IsAuthenticated

from django.utils import timezone

from seguros_project.pagination import LargeResultsSetPagination
from polizas.models import PolizaDocumento
from polizas.serializers import PolizaDocumentoSerializer

from polizas.utils.viewtools import hist_log as _hist_log

# 🚀 IMPORTAMOS NUESTRO MIXIN DE SEGURIDAD
from usuarios.mixins import MultiTenantMixin


class PolizaDocumentoViewSet(MultiTenantMixin, viewsets.ModelViewSet):
    queryset = PolizaDocumento.objects.select_related("poliza").all()
    serializer_class = PolizaDocumentoSerializer
    
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
        lado = self.request.query_params.get("lado")
        
        if poliza_id:
            qs = qs.filter(poliza_id=poliza_id)
        if tipo:
            qs = qs.filter(tipo=tipo)
        if lado:
            qs = qs.filter(lado=lado)
            
        return qs

    def perform_create(self, serializer):
        instance = serializer.save()
        _hist_log(
            poliza=instance.poliza,
            tipo="DOC_SUBIR",
            mensaje=f"Subido {instance.tipo}",
            severidad="INFO",
            data={
                "documento_id": instance.id,
                "tipo": instance.tipo,
                "nombre": instance.nombre,
                "mime": instance.mime,
                "vencimiento": instance.vencimiento.isoformat() if instance.vencimiento else None,
                "url": instance.url,
                "public_id": instance.public_id,
            },
            request=self.request,
            subject=instance,
            categoria="DOC",
        )

    def perform_destroy(self, instance):
        _hist_log(
            poliza=instance.poliza,
            tipo="DOC_BORRAR",
            mensaje=f"Eliminado {instance.tipo}",
            severidad="WARNING",
            data={
                "documento_id": instance.id,
                "tipo": instance.tipo,
                "nombre": instance.nombre,
                "url": instance.url,
                "public_id": instance.public_id,
            },
            request=self.request,
            subject=instance,
            categoria="DOC",
        )
        return super().perform_destroy(instance)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        old_vto = instance.vencimiento
        resp = super().update(request, *args, **kwargs)
        instance.refresh_from_db()
        new_vto = instance.vencimiento
        if old_vto != new_vto:
            _hist_log(
                poliza=instance.poliza,
                tipo="DOC_CAMBIAR_VTO",
                mensaje=f"Cambio de vencimiento en {instance.tipo}",
                severidad="ACTION",
                data={
                    "documento_id": instance.id,
                    "tipo": instance.tipo,
                    "antes": old_vto.isoformat() if old_vto else None,
                    "despues": new_vto.isoformat() if new_vto else None,
                    "nombre": instance.nombre,
                },
                request=self.request,
                subject=instance,
                categoria="DOC",
            )
        return resp

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        old_vto = instance.vencimiento
        resp = super().partial_update(request, *args, **kwargs)
        instance.refresh_from_db()
        new_vto = instance.vencimiento
        if old_vto != new_vto:
            _hist_log(
                poliza=instance.poliza,
                tipo="DOC_CAMBIAR_VTO",
                mensaje=f"Cambio de vencimiento en {instance.tipo}",
                severidad="ACTION",
                data={
                    "documento_id": instance.id,
                    "tipo": instance.tipo,
                    "antes": old_vto.isoformat() if old_vto else None,
                    "despues": new_vto.isoformat() if new_vto else None,
                    "nombre": instance.nombre,
                },
                request=self.request,
                subject=instance,
                categoria="DOC",
            )
        return resp