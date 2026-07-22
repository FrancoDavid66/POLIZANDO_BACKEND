# pagos/views_helpers.py
#
# Funciones sueltas usadas por varios ViewSets de pagos/views.py — seguridad
# de oficina y parseo de fechas/booleanos/enteros desde query params. Sin
# estado, sin efectos secundarios: se pueden mover sin riesgo.
#
# Movido tal cual desde pagos/views.py para que ese archivo no sea un solo
# bloque de 1600 líneas.

from datetime import date

from django.db.models import Q
from django.utils.dateparse import parse_date

# Límite de filas para el export "todos" del historial de pagos — compartida
# acá (y no en views.py) para que views_historial.py la pueda importar sin
# crear un import circular con views.py.
MAX_HISTORIAL_ALL_ROWS = 50000


# -------------------------
# 🔧 Antes esto era 3 funciones que reconocían "5 esquinas / axion / km 39"
# (las 3 sucursales de Thames) por nombre, código o texto libre, con sinónimos
# y regex. Polizando no tiene sucursales — Poliza.oficina es un ForeignKey real
# a Oficina, así que alcanza con filtrar por su id. Se mantienen los mismos
# nombres de función y el mismo contrato de retorno (lista de ids, o
# ["BLOQUEADO"] si no hay acceso, o [] si no hay que filtrar) para no tener
# que tocar cada lugar que las llama.
# -------------------------
def _get_seguridad_oficina_brute(request, requested_oficina=""):
    user = request.user
    if not user.is_authenticated:
        return ["BLOQUEADO"]

    es_admin = user.is_superuser or (hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN')

    if es_admin:
        val = str(requested_oficina or "").strip()
        if not val or val.upper() == "ALL":
            return []  # sin filtro: admin ve todo
        return [val]

    ofi_id = getattr(user, 'perfil', None) and getattr(user.perfil, 'oficina_id', None)
    if ofi_id:
        return [str(ofi_id)]
    return ["BLOQUEADO"]


def _build_oficina_q_from_keys(keys):
    if not keys:
        return Q()
    if "BLOQUEADO" in keys:
        return Q(pk__isnull=True)
    ids = [k for k in keys if str(k).strip().isdigit()]
    if not ids:
        return Q(pk__isnull=True)
    return Q(poliza__oficina_id__in=ids)


def _parse_mes_yyyy_mm(raw: str):
    s = str(raw or "").strip()
    if not s:
        return None, None
    try:
        parts = s.split("-")
        if len(parts) != 2:
            return None, None
        y = int(parts[0])
        m = int(parts[1])
        if m < 1 or m > 12:
            return None, None
        first = date(y, m, 1)
        if m == 12:
            nxt = date(y + 1, 1, 1)
        else:
            nxt = date(y, m + 1, 1)
        return first, nxt
    except Exception:
        return None, None


def _parse_ymd(raw: str):
    s = str(raw or "").strip()
    if not s:
        return None
    return parse_date(s)


def _to_bool(v):
    s = str(v or "").strip().lower()
    return s in {"1", "true", "t", "yes", "y", "on", "si", "sí"}


def _to_int(v, default=None):
    try:
        if v is None or v == "":
            return default
        return int(str(v).strip())
    except Exception:
        return default


def _only_digits(s: str) -> str:
    return "".join([c for c in str(s or "") if c.isdigit()])


def _compania_nombre_robusto(poliza):
    try:
        if not poliza:
            return ""
        comp = getattr(poliza, "compania", None)
        if comp is None:
            cn = getattr(poliza, "compania_nombre", None)
            return str(cn or "").strip()
        if hasattr(comp, "nombre"):
            return str(getattr(comp, "nombre", "") or "").strip()
        return str(comp).strip()
    except Exception:
        return ""