# cotizaciones/views.py
from rest_framework import viewsets, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from .models import Cotizacion, CompaniaSeguro, TipoCobertura, ConfiguracionGlobal
from .serializers import CotizacionSerializer, CompaniaSeguroSerializer, TipoCoberturaSerializer, ConfiguracionGlobalSerializer

class IsAdminRule(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return user.is_superuser or (hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN')

# 🚀 NUEVA REGLA: Todos leen, solo Admin escribe
class IsAdminOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        # Si es una petición segura (GET, HEAD, OPTIONS), dejamos pasar a cualquier usuario logueado
        if request.method in permissions.SAFE_METHODS:
            return request.user and request.user.is_authenticated
        
        # Si es POST, PUT, PATCH, DELETE, aplicamos la regla de Admin
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return user.is_superuser or (hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN')

class CompaniaSeguroViewSet(viewsets.ModelViewSet):
    queryset = CompaniaSeguro.objects.all()
    serializer_class = CompaniaSeguroSerializer
    # 🚀 Aplicamos la nueva regla para que los vendedores puedan leer las aseguradoras
    permission_classes = [IsAdminOrReadOnly]

class TipoCoberturaViewSet(viewsets.ModelViewSet):
    serializer_class = TipoCoberturaSerializer
    # 🚀 Aplicamos la nueva regla para que los vendedores puedan leer las fotos requeridas
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        qs = TipoCobertura.objects.all()
        compania_id = self.request.query_params.get('compania', None)
        if compania_id is not None:
            qs = qs.filter(compania_id=compania_id)
        return qs

class CotizacionViewSet(viewsets.ModelViewSet):
    queryset = Cotizacion.objects.all().prefetch_related('opciones__compania', 'opciones__cobertura')
    serializer_class = CotizacionSerializer
    permission_classes = [IsAdminRule] 

    def perform_create(self, serializer):
        serializer.save(creado_por=self.request.user)

class ConfiguracionGlobalView(APIView):
    permission_classes = [IsAdminRule]

    def get(self, request):
        config, created = ConfiguracionGlobal.objects.get_or_create(pk=1)
        serializer = ConfiguracionGlobalSerializer(config)
        return Response(serializer.data)

    def put(self, request):
        config, created = ConfiguracionGlobal.objects.get_or_create(pk=1)
        serializer = ConfiguracionGlobalSerializer(config, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)