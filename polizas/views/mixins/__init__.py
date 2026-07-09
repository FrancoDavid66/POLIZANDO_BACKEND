# polizas/views/mixins/__init__.py

from .catalogos import PolizaCatalogosMixin
from .exports import PolizaExportsMixin
from .vencimientos import PolizaVencimientosMixin
from .renovaciones import PolizaRenovacionesMixin
from .duplicados import PolizaDuplicadosMixin
from .kpis import PolizaKpisMixin
from .diagnostico import PolizaDiagnosticoMixin  # 🚀 NUEVO

__all__ = [
    "PolizaCatalogosMixin",
    "PolizaExportsMixin",
    "PolizaVencimientosMixin",
    "PolizaRenovacionesMixin",
    "PolizaDuplicadosMixin",
    "PolizaKpisMixin",
    "PolizaDiagnosticoMixin",  # 🚀 NUEVO
]