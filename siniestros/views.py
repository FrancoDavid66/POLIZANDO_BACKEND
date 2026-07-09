# siniestros/views.py
import logging
import json

from rest_framework import viewsets, status, filters
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, BasePermission
from rest_framework.exceptions import PermissionDenied
from django.db.models import Q

from .models import Siniestro, SiniestroEvento, SiniestroFoto
from .serializers import (
    SiniestroSerializer,
    SiniestroEventoSerializer,
    SiniestroFotoSerializer,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 🔐 PERMISO PERSONALIZADO
# ──────────────────────────────────────────────────────────────────────────────
class IsAdminOrReadDeleteRestricted(BasePermission):
    """
    Solo el ADMIN o el superuser pueden borrar siniestros.
    El resto puede listar / crear / editar (limitado por get_queryset al multi-tenant).
    Defense in depth: la UI esconde el botón, pero la API también lo bloquea.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if view.action == 'destroy':
            if request.user.is_superuser:
                return True
            return (
                hasattr(request.user, 'perfil')
                and request.user.perfil.rol == 'ADMIN'
            )
        return True


# ──────────────────────────────────────────────────────────────────────────────
# 🚨 VIEWSET DE SINIESTROS
# ──────────────────────────────────────────────────────────────────────────────
class SiniestroViewSet(viewsets.ModelViewSet):
    serializer_class = SiniestroSerializer
    permission_classes = [IsAuthenticated, IsAdminOrReadDeleteRestricted]

    # 🚀 Búsqueda y ordenamiento server-side
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = [
        'marca_auto', 'modelo_auto', 'patente',
        'nro_reclamo_cia', 'descripcion',
        'tercero_nombre', 'tercero_patente', 'tercero_compania',
        'cliente__nombre', 'cliente__apellido', 'cliente__dni_cuit_cuil',
        'poliza__numero_poliza', 'poliza__patente',
    ]
    ordering_fields = ['id', 'fecha_siniestro', 'fecha_creacion', 'estado']
    ordering = ['-id']

    def get_queryset(self):
        # 🐛 FIX CRÍTICO: era 'order_of' (no existe), corregido a 'order_by'
        # 📸 prefetch de fotos para evitar N+1 cuando el front pida fotos_count o fotos
        qs = (
            Siniestro.objects
            .all()
            .select_related('cliente', 'poliza')
            .prefetch_related('fotos')
            .order_by('-id')
        )
        user = self.request.user

        if not user.is_authenticated:
            return qs.none()

        es_admin = user.is_superuser or (
            hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN'
        )

        # 1. Admin: puede filtrar por oficina vía URL, o ver todo
        if es_admin:
            oficina_id = self.request.query_params.get("oficina")
            if oficina_id:
                try:
                    return qs.filter(poliza__oficina_id=int(oficina_id))
                except (ValueError, TypeError):
                    return qs.none()
            return qs

        # 2. Empleado: solo siniestros de pólizas de su oficina
        if hasattr(user, 'perfil') and user.perfil.oficina_id:
            return qs.filter(poliza__oficina_id=user.perfil.oficina_id)

        # 3. Sin oficina ni rol elevado: nada
        return qs.none()

    @action(detail=True, methods=['get'])
    def eventos(self, request, pk=None):
        siniestro = self.get_object()
        eventos = SiniestroEvento.objects.filter(siniestro=siniestro).order_by('-fecha_evento', '-id')
        serializer = SiniestroEventoSerializer(eventos, many=True)
        return Response(serializer.data)

    # ──────────────────────────────────────────────────────────────────
    # 🐛 DEBUG: interceptamos create y update para loguear todo
    # ──────────────────────────────────────────────────────────────────
    def create(self, request, *args, **kwargs):
        print("\n" + "═" * 70)
        print("🚨 [SINIESTRO CREATE] Petición recibida")
        print("═" * 70)
        print(f"👤 Usuario:        {request.user} (id={request.user.id}, super={request.user.is_superuser})")
        try:
            print(f"   Perfil rol:     {request.user.perfil.rol}")
            print(f"   Perfil oficina: {request.user.perfil.oficina} (id={request.user.perfil.oficina_id})")
        except Exception as e:
            print(f"   ⚠️ No tiene perfil: {e}")

        print(f"\n📦 PAYLOAD recibido:")
        try:
            print(json.dumps(request.data, indent=2, default=str, ensure_ascii=False))
        except Exception:
            print(repr(request.data))

        # Validamos el serializer manualmente para loguear los errores antes de devolverlos
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            print(f"\n❌ SERIALIZER ERRORS:")
            print(json.dumps(serializer.errors, indent=2, default=str, ensure_ascii=False))
            print("═" * 70 + "\n")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        print(f"\n✅ Serializer válido. Datos validados:")
        try:
            # validated_data puede tener objetos del ORM, los convertimos
            validated_print = {k: str(v) for k, v in serializer.validated_data.items()}
            print(json.dumps(validated_print, indent=2, default=str, ensure_ascii=False))
        except Exception:
            print(repr(serializer.validated_data))

        try:
            self.perform_create(serializer)
        except PermissionDenied as e:
            print(f"\n🚫 PERMISSION DENIED: {e}")
            print("═" * 70 + "\n")
            raise
        except Exception as e:
            print(f"\n💥 EXCEPCIÓN EN perform_create: {type(e).__name__}: {e}")
            print("═" * 70 + "\n")
            raise

        print(f"\n✅ Siniestro creado OK: id={serializer.instance.id}")
        print("═" * 70 + "\n")

        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    # ──────────────────────────────────────────────────────────────────
    # 🔐 SEGURIDAD MULTI-TENANT (defense in depth)
    # ──────────────────────────────────────────────────────────────────
    def _validar_oficina(self, user, poliza):
        """
        Regla de negocio:
        - Admin/superuser: puede cargar siniestros sobre pólizas de cualquier oficina.
        - Empleado/Vendedor: SOLO sobre pólizas de SU oficina (perfil.oficina).
        El frontend ya esconde la UI, pero acá blindamos contra peticiones
        directas a la API (curl, Postman, manipulación del navegador, etc.).
        """
        if user.is_superuser:
            return
        if hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN':
            return

        # No-admin: oficina obligatoria en su perfil
        if not hasattr(user, 'perfil') or not user.perfil.oficina_id:
            raise PermissionDenied(
                "Tu usuario no tiene oficina asignada. Pedile al administrador que te configure una."
            )

        # La oficina de la póliza debe coincidir con la del usuario
        if poliza.oficina_id != user.perfil.oficina_id:
            raise PermissionDenied(
                "No podés cargar un siniestro sobre una póliza de otra oficina."
            )

    def perform_create(self, serializer):
        user = self.request.user
        poliza = serializer.validated_data.get('poliza')
        if poliza is None:
            # El serializer ya validará que es obligatorio, pero por las dudas.
            raise PermissionDenied("Falta la póliza.")
        self._validar_oficina(user, poliza)
        serializer.save()

    def perform_update(self, serializer):
        user = self.request.user
        # Si quisieran reasignar a otra póliza, validar también la nueva.
        poliza = serializer.validated_data.get('poliza') or serializer.instance.poliza
        self._validar_oficina(user, poliza)
        serializer.save()


# ──────────────────────────────────────────────────────────────────────────────
# ⏱️ VIEWSET DE EVENTOS (BITÁCORA)
# ──────────────────────────────────────────────────────────────────────────────
class SiniestroEventoViewSet(viewsets.ModelViewSet):
    serializer_class = SiniestroEventoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = SiniestroEvento.objects.all().select_related('siniestro').order_by('-fecha_evento', '-id')
        user = self.request.user

        if not user.is_authenticated:
            return qs.none()

        es_admin = user.is_superuser or (
            hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN'
        )

        if es_admin:
            return qs

        # Empleado solo ve eventos de siniestros de su oficina
        if hasattr(user, 'perfil') and user.perfil.oficina_id:
            return qs.filter(siniestro__poliza__oficina_id=user.perfil.oficina_id)

        return qs.none()


# ──────────────────────────────────────────────────────────────────────
# 📸 VIEWSET DE FOTOS DEL SINIESTRO
# ──────────────────────────────────────────────────────────────────────
class SiniestroFotoViewSet(viewsets.ModelViewSet):
    """
    CRUD de fotos del siniestro.
    Endpoints:
      GET    /api/siniestro-fotos/?siniestro=<id>   → lista fotos del siniestro
      POST   /api/siniestro-fotos/                   → crear foto (ya subida a Cloudinary)
      DELETE /api/siniestro-fotos/<id>/              → borrar foto (admin)
    """
    serializer_class = SiniestroFotoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = SiniestroFoto.objects.all().select_related('siniestro', 'subida_por').order_by('-fecha_creacion', '-id')
        user = self.request.user

        if not user.is_authenticated:
            return qs.none()

        # Filtro por siniestro (querystring)
        siniestro_id = self.request.query_params.get('siniestro')
        if siniestro_id:
            try:
                qs = qs.filter(siniestro_id=int(siniestro_id))
            except (ValueError, TypeError):
                return qs.none()

        es_admin = user.is_superuser or (
            hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN'
        )

        if es_admin:
            return qs

        # Empleado: solo fotos de siniestros de su oficina
        if hasattr(user, 'perfil') and user.perfil.oficina_id:
            return qs.filter(siniestro__poliza__oficina_id=user.perfil.oficina_id)

        return qs.none()

    def perform_create(self, serializer):
        """Al crear, validamos que el siniestro pertenezca a la oficina del usuario."""
        user = self.request.user
        siniestro = serializer.validated_data.get('siniestro')

        if not user.is_superuser:
            es_admin = hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN'
            if not es_admin:
                if not hasattr(user, 'perfil') or not user.perfil.oficina_id:
                    raise PermissionDenied("Tu usuario no tiene oficina asignada.")
                if siniestro.poliza.oficina_id != user.perfil.oficina_id:
                    raise PermissionDenied(
                        "No podés subir fotos a siniestros de otra oficina."
                    )

        serializer.save(subida_por=user)

    def perform_destroy(self, instance):
        """Solo admin puede borrar fotos."""
        user = self.request.user
        es_admin = user.is_superuser or (
            hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN'
        )
        if not es_admin:
            raise PermissionDenied("Solo los administradores pueden eliminar fotos.")

        # TODO opcional: borrar también del CDN de Cloudinary usando public_id.
        # Necesitaría cloudinary SDK + signed delete. Por ahora la foto queda en CDN
        # pero desaparece de la app (no es visible para nadie).
        instance.delete()