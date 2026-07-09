# competencia/utils/geo_sync.py
import logging
from typing import Any

from geo.models import GeoItem

logger = logging.getLogger(__name__)

# 🛠️ FIX: antes se usaba tipo="competencia", que NO existe en GeoItem.TIPO_CHOICES,
# por lo que los competidores nunca aparecían en el mapa.
# El tipo válido para una oficina de la competencia es "oficina_rival".
GEO_TIPO_COMPETENCIA = "oficina_rival"


def _get_lat_lng(ubicacion: Any):
    """
    Obtiene lat/lng sin importar cómo se llamen los campos
    (latitud/longitud o lat/lng).
    """
    lat = getattr(ubicacion, "latitud", None) or getattr(ubicacion, "lat", None)
    lng = (
        getattr(ubicacion, "longitud", None)
        or getattr(ubicacion, "lng", None)
        or getattr(ubicacion, "long", None)
    )
    return lat, lng


def _build_descripcion(ubicacion: Any) -> str:
    partes_ubicacion = []
    if getattr(ubicacion, "direccion", None):
        partes_ubicacion.append(str(ubicacion.direccion))
    if getattr(ubicacion, "ciudad", None):
        partes_ubicacion.append(str(ubicacion.ciudad))
    linea_ubicacion = " - ".join(partes_ubicacion) if partes_ubicacion else ""

    detalles = []
    if getattr(ubicacion, "compania", None):
        detalles.append(f"Compañía: {ubicacion.compania}")
    if getattr(ubicacion, "cobertura", None):
        detalles.append(f"Cobertura: {ubicacion.cobertura}")
    if getattr(ubicacion, "precio", None) is not None:
        detalles.append(f"Precio: {ubicacion.precio}")
    linea_detalles = " | ".join(detalles) if detalles else ""

    partes = [p for p in [linea_ubicacion, linea_detalles] if p]
    if partes:
        return " / ".join(partes)
    return f"Ubicación de {ubicacion.competidor.nombre}"


def sync_ubicacion_competencia_to_geo(ubicacion: Any) -> None:
    """
    Crea/actualiza un GeoItem (tipo='oficina_rival') a partir de una
    CompetidorUbicacion.

    Reglas:
    - Solo sincroniza si hay latitud y longitud.
    - Agrupa por (tipo, nombre, lat, lng) para no duplicar puntos.
    """
    lat, lng = _get_lat_lng(ubicacion)
    if lat is None or lng is None:
        logger.info("[GEO SYNC] Ubicación sin lat/lng, no se sincroniza.")
        return

    descripcion = _build_descripcion(ubicacion)
    nota_base = descripcion or f"Ubicación de {ubicacion.competidor.nombre}"
    nota_con_emoji = f"⚔️ Competencia · {nota_base}"

    logger.info(
        "[GEO SYNC] Sincronizando id=%s nombre=%s lat=%s lng=%s",
        ubicacion.id,
        ubicacion.competidor.nombre,
        lat,
        lng,
    )

    GeoItem.objects.update_or_create(
        tipo=GEO_TIPO_COMPETENCIA,
        nombre=ubicacion.competidor.nombre,
        lat=lat,
        lng=lng,
        defaults={
            "direccion": getattr(ubicacion, "direccion", "") or "",
            "nota": nota_con_emoji,
            "activo": getattr(ubicacion.competidor, "activo", True),
        },
    )


def desactivar_ubicacion_competencia_en_geo(ubicacion: Any) -> None:
    """
    Marca como inactivos los GeoItem que correspondan a esa ubicación.
    """
    lat, lng = _get_lat_lng(ubicacion)
    if lat is None or lng is None:
        logger.info("[GEO SYNC] Sin lat/lng al desactivar, no se toca GEO.")
        return

    logger.info(
        "[GEO SYNC] Desactivando id=%s nombre=%s lat=%s lng=%s",
        ubicacion.id,
        ubicacion.competidor.nombre,
        lat,
        lng,
    )

    GeoItem.objects.filter(
        tipo=GEO_TIPO_COMPETENCIA,
        nombre=ubicacion.competidor.nombre,
        lat=lat,
        lng=lng,
    ).update(activo=False)