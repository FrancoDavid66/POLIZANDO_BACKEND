# gruas/utils/validaciones.py
from django.utils import timezone
from ..models import EstadoAdhesion


def _hoy():
    return timezone.localdate()


def poliza_vigente(poliza) -> bool:
    """Mantiene la validación de póliza vigente (no la tocamos)"""
    hoy = _hoy()
    estado = getattr(poliza, "estado", "").lower()
    if estado in ("finalizada", "vencida", "cancelada", "baja"):
        return False
    for attr in ("fecha_vigencia_hasta", "fecha_fin", "fecha_vencimiento"):
        d = getattr(poliza, attr, None)
        if d and d < hoy:
            return False
    return True


def adhesion_operable(adhesion):
    """
    VALIDACIÓN TEMPORALMENTE DESACTIVADA PARA PRUEBAS
    → Siempre devuelve OK aunque esté en mora, carencia o rehabilitación.
    """
    
    # ==================== DESACTIVADO PARA PRUEBAS ====================
    # hoy = _hoy()
    # if adhesion.estado != EstadoAdhesion.ACTIVA:
    #     return (False, f"Adhesión no operativa: {adhesion.estado}.")
    # if adhesion.fecha_carencia_fin and hoy < adhesion.fecha_carencia_fin:
    #     return (False, f"En carencia hasta {adhesion.fecha_carencia_fin}.")
    # if adhesion.rehabilitar_desde and hoy < adhesion.rehabilitar_desde:
    #     return (False, f"Rehabilita desde {adhesion.rehabilitar_desde}.")
    # =================================================================

    return (True, "OK")   # ← Siempre permite crear la solicitud en modo pruebas


def horario_prestacion_activo():
    """Mantengo esta validación porque es de horario comercial"""
    now = timezone.localtime()
    if now.weekday() > 5:        # domingo
        return False
    return 8 <= now.hour < 20    # 08:00 a 20:00