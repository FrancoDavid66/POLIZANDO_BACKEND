# polizas/utils/errors.py
#
# Catálogo central de er rores estructurados.
# Cada error tiene:
#   - code: identificador único (UPPER_SNAKE_CASE)
#   - message: mensaje corto al usuario
#   - detail: explicación más larga
#   - action: qué puede hacer el usuario para resolverlo
#   - http_status: código HTTP a devolver
#
# Uso típico desde una vista/handler:
#
#   from polizas.utils.errors import RenovacionError, ErrorCodes
#   raise RenovacionError(ErrorCodes.COBERTURA_NO_CONFIGURADA,
#                         context={"compania": "Sancor", "cobertura": "A"})
#
# El mixin captura RenovacionError y devuelve un JSON estructurado al frontend.

from rest_framework import status


class ErrorCodes:
    """Códigos de error estables (no cambian). El frontend matchea por estos códigos."""

    # ── Renovación ──
    COBERTURA_NO_CONFIGURADA = "COBERTURA_NO_CONFIGURADA"
    POLIZA_YA_RENOVADA = "POLIZA_YA_RENOVADA"
    POLIZA_FINALIZADA = "POLIZA_FINALIZADA"
    SIN_CUOTAS_REFERENCIA = "SIN_CUOTAS_REFERENCIA"
    NUMERO_DUPLICADO = "NUMERO_DUPLICADO"
    COMPANIA_INVALIDA = "COMPANIA_INVALIDA"

    # ── Validaciones suaves (warnings, no bloquean) ──
    CUOTAS_IMPAGAS = "CUOTAS_IMPAGAS"
    FECHA_PASADA = "FECHA_PASADA"
    COMPANIA_CAMBIADA = "COMPANIA_CAMBIADA"

    # ── Generales ──
    SIN_PERMISO = "SIN_PERMISO"
    RED_CAIDA = "RED_CAIDA"
    SESION_EXPIRADA = "SESION_EXPIRADA"
    ERROR_DESCONOCIDO = "ERROR_DESCONOCIDO"


# ── Catálogo de mensajes ──────────────────────────────────────────
# Cada entrada: { message, detail, action, http_status }
ERROR_CATALOG = {
    ErrorCodes.COBERTURA_NO_CONFIGURADA: {
        "message": "Falta configurar la cobertura en el Admin",
        "detail": (
            "No pudimos determinar la cantidad de cuotas de esta cobertura porque "
            "no está en el catálogo del Admin y la póliza original tampoco la tiene cargada."
        ),
        "action": (
            "Configurá esta cobertura en Admin → Catálogos, "
            "o ingresá manualmente la cantidad de cuotas para esta renovación."
        ),
        "http_status": status.HTTP_400_BAD_REQUEST,
    },
    ErrorCodes.POLIZA_YA_RENOVADA: {
        "message": "Esta póliza ya fue renovada",
        "detail": "Existe una versión más nueva de esta póliza en el sistema.",
        "action": "Buscá la versión más nueva en la lista o pediselá al administrador.",
        "http_status": status.HTTP_409_CONFLICT,
    },
    ErrorCodes.POLIZA_FINALIZADA: {
        "message": "Esta póliza ya está finalizada",
        "detail": "No se puede renovar una póliza que ya está marcada como finalizada.",
        "action": "Si necesitás reactivarla, contactá al administrador.",
        "http_status": status.HTTP_409_CONFLICT,
    },
    ErrorCodes.SIN_CUOTAS_REFERENCIA: {
        "message": "Esta póliza no tiene cuotas para calcular el inicio",
        "detail": (
            "Para renovar necesitamos saber cuándo termina la cobertura actual. "
            "Esta póliza no tiene cuotas registradas."
        ),
        "action": "Ingresá manualmente la fecha de inicio de la nueva póliza.",
        "http_status": status.HTTP_400_BAD_REQUEST,
    },
    ErrorCodes.NUMERO_DUPLICADO: {
        "message": "El número de póliza ya está en uso",
        "detail": "Otra póliza del sistema ya tiene este número.",
        "action": "Usá un número distinto o dejalo en blanco (se genera uno automático).",
        "http_status": status.HTTP_400_BAD_REQUEST,
    },
    ErrorCodes.COMPANIA_INVALIDA: {
        "message": "La compañía es inválida",
        "detail": "El campo compañía está vacío o tiene un valor que no se puede procesar.",
        "action": "Seleccioná una compañía válida.",
        "http_status": status.HTTP_400_BAD_REQUEST,
    },
    ErrorCodes.CUOTAS_IMPAGAS: {
        "message": "Esta póliza tiene cuotas impagas",
        "detail": "Hay cuotas anteriores sin pagar. Renovar igual es válido pero deja un saldo pendiente.",
        "action": "Cobrá las cuotas pendientes antes de renovar, o continuá si el cliente está al tanto.",
        "http_status": status.HTTP_200_OK,  # Warning, no error
    },
    ErrorCodes.FECHA_PASADA: {
        "message": "La fecha de inicio es en el pasado",
        "detail": "La fecha que ingresaste es anterior a hoy.",
        "action": "Confirmá la fecha o ajustala.",
        "http_status": status.HTTP_200_OK,
    },
    ErrorCodes.COMPANIA_CAMBIADA: {
        "message": "Estás cambiando de compañía",
        "detail": "La nueva póliza va a tener una compañía distinta a la original.",
        "action": "Asegurate de que la cobertura y cantidad de cuotas sean correctas.",
        "http_status": status.HTTP_200_OK,
    },
    ErrorCodes.SIN_PERMISO: {
        "message": "No tenés permiso para esta acción",
        "detail": "Tu rol o sucursal no te permite renovar pólizas aquí.",
        "action": "Contactá al administrador para revisar tus permisos.",
        "http_status": status.HTTP_403_FORBIDDEN,
    },
    ErrorCodes.RED_CAIDA: {
        "message": "Sin conexión con el servidor",
        "detail": "El backend no respondió a tiempo.",
        "action": "Revisá tu internet y volvé a intentar.",
        "http_status": status.HTTP_503_SERVICE_UNAVAILABLE,
    },
    ErrorCodes.SESION_EXPIRADA: {
        "message": "Tu sesión expiró",
        "detail": "Tenés que volver a iniciar sesión.",
        "action": "Cerrá sesión y volvé a entrar.",
        "http_status": status.HTTP_401_UNAUTHORIZED,
    },
    ErrorCodes.ERROR_DESCONOCIDO: {
        "message": "Ocurrió un error inesperado",
        "detail": "Algo salió mal. Intentá de nuevo. Si persiste, avisá a soporte.",
        "action": "Intentá de nuevo en unos segundos.",
        "http_status": status.HTTP_500_INTERNAL_SERVER_ERROR,
    },
}


class RenovacionError(Exception):
    """
    Excepción estructurada para errores de renovación.
    El mixin la captura y devuelve un JSON al frontend.
    """

    def __init__(self, code, context=None, message_override=None, detail_override=None):
        self.code = code
        self.context = context or {}

        entry = ERROR_CATALOG.get(code, ERROR_CATALOG[ErrorCodes.ERROR_DESCONOCIDO])
        self.message = message_override or entry["message"]
        self.detail = detail_override or entry["detail"]
        self.action = entry["action"]
        self.http_status = entry["http_status"]

        super().__init__(self.message)

    def to_dict(self):
        """Formato JSON para devolver al frontend."""
        return {
            "error": self.code,
            "message": self.message,
            "detail": self.detail,
            "action": self.action,
            "context": self.context,
        }


def build_error_response(code, context=None, message_override=None, detail_override=None):
    """
    Helper para construir un Response con el formato de error estándar.

    Uso:
        from rest_framework.response import Response
        from polizas.utils.errors import build_error_response, ErrorCodes

        if not algo_valido:
            return build_error_response(
                ErrorCodes.COBERTURA_NO_CONFIGURADA,
                context={"compania": "Sancor", "cobertura": "A"}
            )
    """
    from rest_framework.response import Response

    err = RenovacionError(code, context, message_override, detail_override)
    return Response(err.to_dict(), status=err.http_status)