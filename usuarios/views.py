# usuarios/views.py
from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.contrib.auth.models import User

from .models import Oficina, Perfil
from .serializers import OficinaSerializer, UserSerializer

class IsAdminRole(permissions.BasePermission):
    """Permiso personalizado: Solo usuarios con rol ADMIN o Superusuarios"""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        return hasattr(request.user, 'perfil') and request.user.perfil.rol == 'ADMIN'

class OficinaViewSet(viewsets.ModelViewSet):
    """ABM de Oficinas.
    - Ver/listar: cualquier usuario logueado (lo necesitan varios paneles:
      carga rápida, selector de oficinas en Tareas, etc.).
    - Crear/editar/borrar: solo Admin.
    """
    queryset = Oficina.objects.all().order_by('nombre')
    serializer_class = OficinaSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        return [IsAdminRole()]

# 🚀 FIX: Cambiado a ModelViewSet para permitir POST, PUT, DELETE
class UserViewSet(viewsets.ModelViewSet):
    """ABM de usuarios y endpoint para obtener el usuario actual"""
    queryset = User.objects.all().select_related('perfil', 'perfil__oficina').order_by('username')
    serializer_class = UserSerializer
    # Por defecto, solo admin puede ver, crear o editar usuarios
    permission_classes = [IsAdminRole]

    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def me(self, request):
        """
        Endpoint crítico para el Frontend: /api/usuarios/users/me/
        Devuelve los datos, rol y oficina del usuario que ha iniciado sesión.
        Cualquier usuario logueado puede ver su propio 'me'.
        """
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)