# polizas/utils/constants.py
#
# ✅ Sistema NUEVO: Las cuotas y cuponeras se gestionan desde el Admin
#    (cotizaciones.TipoCobertura) usando los campos:
#       - cuotas_a_generar
#       - genera_cupones_robo
#
# 🪦 Sistema VIEJO eliminado: el diccionario hardcodeado de compañías ya no se usa.
#    Las funciones que dependían de él (`get_cuotas_por_compania`, etc.) ahora
#    lanzan un error CLARO con instrucciones de qué usar en su lugar.
#
# 🛡️ Lo que SE MANTIENE útil:
#    - normalizar_compania: para matchear nombres de pólizas viejas (texto libre)
#      contra el catálogo de Admin (CompaniaSeguro). Sin esto, "Federación Patronal"
#      y "Federacion Patronal" no matchean.
#    - normalizar_cobertura: lo mismo pero para coberturas (A, A+GRUA, B, etc.)
#    - list_companias / list_coberturas: helpers de lectura

from __future__ import annotations
from typing import Dict, List
import unicodedata

# ============================================================
# Helpers de normalización (USAR)
# ============================================================

def _normalize_key(name: str) -> str:
    """Normaliza texto: quita acentos, pasa a minúsculas y colapsa espacios."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.strip().lower().split())


def _limpiar_texto(nombre: str) -> str:
    """Quita tildes y pasa a mayúsculas."""
    if not nombre:
        return ""
    s = "".join(c for c in unicodedata.normalize("NFD", str(nombre)) if unicodedata.category(c) != "Mn")
    return s.strip().upper()


# ============================================================
# COMPAÑÍAS — Alias para normalizar nombres viejos
# ============================================================
# Estos alias ya NO definen cuotas (eso está en el Admin).
# Solo sirven para que "Federación Patronal" y "FEDERACION PATRONAL" sean lo mismo
# al buscar en el catálogo CompaniaSeguro.

_ALIAS_NORMALIZADOS: Dict[str, str] = {
    "nre": "NRE",
    "rne": "NRE",
    "federacion patronal": "Federacion Patronal",
    "federación patronal": "Federacion Patronal",
    "federacion_patronal": "Federacion Patronal",
    "atm": "ATM",
    "a.t.m.": "ATM",
    "atm seguros": "ATM",
    "agrosalta": "Agrosalta",
    "equidad": "Equidad",
    "la equidad": "LA EQUIDAD",
    "providencia": "Providencia",
}


def normalizar_compania(nombre: str) -> str:
    """
    Devuelve un nombre canónico para matchear con el catálogo de CompaniaSeguro.
    Si la compañía es nueva y no tiene alias, simplemente la limpia y la deja pasar.
    """
    if not nombre:
        return ""

    key = _normalize_key(nombre)

    if key in _ALIAS_NORMALIZADOS:
        return _ALIAS_NORMALIZADOS[key]

    # Si no la conocemos, limpiamos y dejamos pasar
    return _limpiar_texto(nombre)


def list_companias() -> List[str]:
    """
    Devuelve la lista de compañías ACTIVAS desde el catálogo dinámico (Admin).
    Si la app cotizaciones no está disponible, devuelve [].
    """
    try:
        from cotizaciones.models import CompaniaSeguro
        return list(
            CompaniaSeguro.objects.filter(activa=True)
            .order_by("nombre")
            .values_list("nombre", flat=True)
        )
    except Exception:
        return []


# ============================================================
# COBERTURAS — Normalización + alias
# ============================================================

COBERTURAS_CANONICAS: List[str] = [
    "A", "A + GRUA", "B", "B1", "C", "C1", "C TOTAL", "C FRANQUICIA",
]

_ALIAS_COBERTURAS: Dict[str, str] = {
    "a": "A", "a + grua": "A + GRUA", "a+grua": "A + GRUA", "a grua": "A + GRUA",
    "b": "B", "b1": "B1", "b 1": "B1",
    "c": "C", "c1": "C1", "c 1": "C1",
    "c total": "C TOTAL", "ctotal": "C TOTAL", "c. total": "C TOTAL",
    "c franquicia": "C FRANQUICIA", "c franquiscia": "C FRANQUICIA", "cfranquicia": "C FRANQUICIA",
}


def normalizar_cobertura(nombre: str) -> str:
    """
    Devuelve el nombre de cobertura canónico para matchear con TipoCobertura.
    Si no la reconoce, la limpia y la deja pasar.
    """
    if not nombre:
        return ""

    key = _normalize_key(nombre)

    for canon in COBERTURAS_CANONICAS:
        if _normalize_key(canon) == key:
            return canon

    compact = key.replace(" ", "")
    if key in _ALIAS_COBERTURAS:
        return _ALIAS_COBERTURAS[key]
    if compact in _ALIAS_COBERTURAS:
        return _ALIAS_COBERTURAS[compact]

    return _limpiar_texto(nombre)


def list_coberturas() -> List[str]:
    return list(COBERTURAS_CANONICAS)


COBERTURAS: List[str] = COBERTURAS_CANONICAS


# ============================================================
# 🪦 FUNCIONES DEPRECADAS — TIRAN ERROR CLARO SI ALGUIEN LAS USA
# ============================================================
# Estas funciones eran del sistema viejo (cuotas hardcodeadas por compañía).
# Ahora todo se gestiona desde el Admin (TipoCobertura).
# Si algún archivo todavía las importa, va a fallar con un mensaje claro
# que dice exactamente qué usar en su lugar.

class _DeprecatedSymbolError(RuntimeError):
    """Error que aparece cuando se usa código viejo eliminado."""
    pass


def _deprecated_msg(simbolo: str, reemplazo: str) -> str:
    return (
        f"\n"
        f"❌ '{simbolo}' fue ELIMINADO de polizas/utils/constants.py.\n"
        f"   La gestión de cuotas y cuponeras ahora se hace desde el Admin "
        f"(cotizaciones.TipoCobertura).\n"
        f"   Reemplazá esta llamada por:\n"
        f"   👉 {reemplazo}\n"
    )


def get_cuotas_por_compania(nombre: str = "") -> int:
    raise _DeprecatedSymbolError(_deprecated_msg(
        "get_cuotas_por_compania()",
        "TipoCobertura.objects.filter(compania__nombre=..., nombre=...).first().cuotas_a_generar"
    ))


def compania_tiene_cuponeras_robo(nombre: str = "") -> bool:
    raise _DeprecatedSymbolError(_deprecated_msg(
        "compania_tiene_cuponeras_robo()",
        "TipoCobertura.objects.filter(compania__nombre=..., nombre=...).first().genera_cupones_robo"
    ))


def list_companias_con_cuponeras_robo() -> List[str]:
    raise _DeprecatedSymbolError(_deprecated_msg(
        "list_companias_con_cuponeras_robo()",
        "CompaniaSeguro.objects.filter(coberturas__genera_cupones_robo=True).distinct()"
    ))


def get_vigencia_meses(nombre: str = "") -> int:
    raise _DeprecatedSymbolError(_deprecated_msg(
        "get_vigencia_meses()",
        "TipoCobertura.cuotas_a_generar (la vigencia es igual a la cantidad de cuotas)"
    ))


def get_refacturacion_meses(nombre: str = "") -> int:
    raise _DeprecatedSymbolError(_deprecated_msg(
        "get_refacturacion_meses()",
        "TipoCobertura.cuotas_a_generar (la refacturación es igual a la cantidad de cuotas)"
    ))


# Diccionarios viejos: cualquier acceso tira error claro
class _DeprecatedDict(dict):
    def __init__(self, simbolo: str, reemplazo: str):
        super().__init__()
        self._simbolo = simbolo
        self._reemplazo = reemplazo

    def _fail(self, *args, **kwargs):
        raise _DeprecatedSymbolError(_deprecated_msg(self._simbolo, self._reemplazo))

    __getitem__ = _fail
    __contains__ = _fail
    get = _fail
    keys = _fail
    values = _fail
    items = _fail


MAPEADO_COMPANIAS = _DeprecatedDict(
    "MAPEADO_COMPANIAS",
    "CompaniaSeguro.objects.all() (el catálogo dinámico del Admin)"
)

CANTIDAD_CUOTAS_POR_COMPANIA = _DeprecatedDict(
    "CANTIDAD_CUOTAS_POR_COMPANIA",
    "TipoCobertura.cuotas_a_generar"
)

COMPANIAS_CON_CUPONERAS_ROBO = _DeprecatedDict(
    "COMPANIAS_CON_CUPONERAS_ROBO",
    "TipoCobertura.objects.filter(genera_cupones_robo=True)"
)