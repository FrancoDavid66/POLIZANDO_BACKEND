# tareas/urls.py
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    TareasDiaView,
    MarcarPolizaEnviadaView,
    RegistrarTareaCompletadaView,
)
from .papeles_sistema import SubirPapelesSistemaView

# 🆕 Tareas fijas (recurrentes con foto)
from .views_fijas import (
    TareaFijaViewSet,
    FeriadoViewSet,
    TareasFijasDiaView,
    CumplirTareaFijaView,
    RankingControlDiarioView,
)

app_name = "tareas"

router = DefaultRouter()
router.register(r"tareas-fijas", TareaFijaViewSet, basename="tareas-fijas")
router.register(r"feriados", FeriadoViewSet, basename="feriados")

urlpatterns = [
    # Tareas del día (las que salen solas de pólizas/clientes)
    path("tareas/dia/", TareasDiaView.as_view(), name="tareas-dia"),
    path("tareas/marcar-enviada/", MarcarPolizaEnviadaView.as_view(), name="tareas-marcar-enviada"),
    path("tareas/registrar-completada/", RegistrarTareaCompletadaView.as_view(), name="tareas-registrar-completada"),
    path("tareas/subir-papeles-sistema/", SubirPapelesSistemaView.as_view(), name="tareas-subir-papeles-sistema"),

    # 🆕 Tareas fijas — endpoints especiales (van ANTES del router)
    path("tareas-fijas/dia/", TareasFijasDiaView.as_view(), name="tareas-fijas-dia"),
    path("tareas-fijas/cumplir/", CumplirTareaFijaView.as_view(), name="tareas-fijas-cumplir"),
    path("tareas-fijas/ranking/", RankingControlDiarioView.as_view(), name="tareas-fijas-ranking"),
]

# 🆕 CRUD de tareas fijas y feriados (router)
urlpatterns += router.urls