from rest_framework.routers import DefaultRouter
from .views import SolicitudSeguroViewSet, SolicitudDocumentoViewSet, EmpleadoViewSet

app_name = "solicitudes"

# ✅ micro-opt: router sin trailing slash (menos redirects / URLs más cortas)
# OJO: esto solo aplica si tu proyecto no depende del "/" final.
# Si preferís mantenerlo, cambiá DefaultRouter() por DefaultRouter()
router = DefaultRouter()
router.trailing_slash = "/?"  # acepta con o sin "/" (evita 301)

# Registrar documentos primero evita que el detail de solicitudes capture "/documentos/"
router.register(r"documentos", SolicitudDocumentoViewSet, basename="solicitud-documentos")
router.register(r"solicitudes", SolicitudSeguroViewSet, basename="solicitudes")
router.register(r"empleados", EmpleadoViewSet, basename="empleados")

urlpatterns = router.urls
