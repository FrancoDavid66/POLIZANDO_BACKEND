# polizas/views/__init__.py

from .poliza import PolizaViewSet
from .foto_vehiculo import FotoVehiculoViewSet
from .documentos import PolizaDocumentoViewSet
from .cupon_robo import CuponRoboViewSet

__all__ = [
    "PolizaViewSet",
    "FotoVehiculoViewSet",
    "PolizaDocumentoViewSet",
    "CuponRoboViewSet",
]