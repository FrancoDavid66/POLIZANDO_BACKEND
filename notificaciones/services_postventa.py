# notificaciones/se rvices_postventa.py
"""
⚠️ MÓDULO DESACTIVADO ⚠️

El servicio de mensaje post-venta automático fue eliminado de la app.
Este archivo se mantiene como stub para evitar romper imports históricos.

Si alguna parte del código sigue llamando a `enviar_mensajes_postventa(...)`,
la función retorna un resultado vacío sin enviar nada.

Para volver a habilitarlo, ver el historial de Git previo a esta versión.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


@dataclass
class ResultadoPostVenta:
    hoy: date
    enviados: int = 0
    omitidos: int = 0
    errores: List[Dict[str, Any]] = field(default_factory=list)
    detalles: List[Dict[str, Any]] = field(default_factory=list)

    def __str__(self):
        return f"PostVenta DESACTIVADO ({self.hoy})"


def enviar_mensajes_postventa(
    oficina: Optional[str] = None,
    hoy: Optional[date] = None,
    dry_run: bool = False,
) -> ResultadoPostVenta:
    """
    ⚠️ DESACTIVADO ⚠️
    No envía nada. Retorna un ResultadoPostVenta vacío.
    """
    hoy = hoy or timezone.localdate()
    logger.info("[postventa] DESACTIVADO — no se envían mensajes de post-venta.")
    return ResultadoPostVenta(hoy=hoy)