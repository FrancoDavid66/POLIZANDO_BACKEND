# polizas/precios_nre.py
# ──────────────────────────────────────────────────────────────────────────
# LISTA DE PRECIOS — SOLO compañía NRE.
#
# Única fuente de verdad del plan de aumentos escalonado.
# El precio de cada categoría se determina por la FECHA: como los escalones y
# las renovaciones son los dos cada 3 meses, no hace falta llevar la cuenta de
# "en qué escalón va cada póliza" — se mira la fecha y listo.
#
# Cómo se usa:
#   - Renovación  → precio_cuotas_renovacion(tipo, fecha, oficina)
#   - Alta nueva  → precio_cuotas_alta_nueva(tipo, fecha, oficina)
#   - Portal      → precio_vigente / precio_cuotas_renovacion para mostrar
#
# 🔧 Se sacó la excepción de "El Talita": Polizando no tiene sucursales, así
# que no hay lugar para una tabla de precios distinta por oficina. El
# parámetro `oficina` se mantiene en las firmas de las funciones solo para
# no romper a quien ya las llama con ese argumento — no se usa para nada.
#
# Para CAMBIAR un precio: editás la tabla de abajo y deployás.
# ──────────────────────────────────────────────────────────────────────────
from datetime import date

# Cada categoría: lista de (fecha_desde, precio_cuota), ordenada de vieja a nueva.
# La fila 1900-01-01 es el precio VIEJO (sólo se usa como gancho/promo de la 1ra
# cuota en altas nuevas). El aumento ya está VIGENTE desde el 29/06/2026.
PRECIOS_NRE = {
    "Auto": [
        (date(1900, 1, 1), 30000),
        (date(2026, 6, 29), 36000),
        (date(2026, 10, 1), 39500),
        (date(2027, 1, 1), 44500),
    ],
    "Moto": [
        (date(1900, 1, 1), 15000),
        (date(2026, 6, 29), 18000),
        (date(2027, 1, 1), 20500),
    ],
    "Camioneta": [
        (date(1900, 1, 1), 35000),
        (date(2026, 6, 29), 41000),
        (date(2026, 10, 1), 47000),
        (date(2027, 1, 1), 55000),
    ],
    "Camion": [
        (date(1900, 1, 1), 75000),
    ],
    # Trailer: fijo, sin escalones hasta tener el costo NRE.
    "Trailer": [
        (date(1900, 1, 1), 15000),
    ],
}


def _norm_tipo(tipo):
    """Normaliza el tipo de vehículo. Tolera minúsculas, acentos y SINÓNIMOS
    (automovil→Auto, motocicleta→Moto, pick-up/furgón/utilitario→Camioneta,
    acoplado→Trailer). Devuelve None si no lo reconoce."""
    t = (tipo or "").strip().lower()
    if not t:
        return None
    mapa = {
        "auto": "Auto", "automovil": "Auto", "automóvil": "Auto",
        "sedan": "Auto", "sedán": "Auto", "hatchback": "Auto",
        "coupe": "Auto", "coupé": "Auto", "familiar": "Auto",
        "moto": "Moto", "motocicleta": "Moto", "ciclomotor": "Moto", "scooter": "Moto",
        "camioneta": "Camioneta", "pickup": "Camioneta", "pick-up": "Camioneta",
        "pick up": "Camioneta", "furgon": "Camioneta", "furgón": "Camioneta",
        "furgoneta": "Camioneta", "utilitario": "Camioneta",
        "camion": "Camion", "camión": "Camion",
        "trailer": "Trailer", "tráiler": "Trailer", "trailler": "Trailer",
        "acoplado": "Trailer",
    }
    if t in mapa:
        return mapa[t]
    # Coincidencia parcial (ej: "automovil nacional", "pick-up 4x4").
    # OJO con el orden: "camioneta" contiene "camion", por eso va primero.
    if "moto" in t or "ciclomotor" in t:
        return "Moto"
    if "camioneta" in t or "pick" in t or "furg" in t or "utilitar" in t:
        return "Camioneta"
    if "camion" in t or "camión" in t:
        return "Camion"
    if "acoplad" in t or "trailer" in t or "tráiler" in t:
        return "Trailer"
    if "auto" in t:
        return "Auto"
    return None


# ──────────────────────────────────────────────────────────────────────────
# 🧠 INFERENCIA DE TIPO POR MODELO (red de seguridad)
# Si alguien carga mal el tipo (ej: una moto como "Auto"), esto lo detecta
# mirando la marca/modelo y lo corrige, así se cobra bien. Sólo actúa cuando
# la señal es FUERTE; si duda, no toca nada (respeta lo declarado).
# ──────────────────────────────────────────────────────────────────────────

# Marcas que en Argentina son SÓLO motos (señal fuerte, sin ambigüedad).
_MARCAS_MOTO = (
    "gilera", "zanella", "motomel", "corven", "keller", "guerrero", "mondial",
    "benelli", "bajaj", "royal enfield", "ktm", "beta", "jawa", "brava",
    "kymco", "tvs", "hero", "appia", "yumbo", "cerro", "vespa", "husqvarna",
    "sym", "okinoi",
)

# Nombres de pick-up / furgón conocidos (→ Camioneta).
_MODELOS_CAMIONETA = (
    "hilux", "ranger", "amarok", "frontier", "s10", "s-10", "l200", "dmax",
    "d-max", "kangoo", "partner", "berlingo", "fiorino", "combo", "doblo",
    "saveiro", "strada", "montana", "oroch", "toro", "hiace", "ducato",
    "master", "sprinter", "transit", "daily", "jumper", "boxer", "trafic",
    "expert", "scudo", "h100", "ram", "gladiator", "kombi",
)


def inferir_tipo(marca=None, modelo=None):
    """Adivina el tipo mirando marca + modelo. Devuelve "Moto"/"Camioneta" si
    hay señal FUERTE, o None si no está seguro (ahí se respeta lo declarado).
    Ej: inferir_tipo("GILERA", "150 VC VS")       -> "Moto"
        inferir_tipo("RENAULT", "KANGOO CONFORT") -> "Camioneta"
    """
    blob = f"{marca or ''} {modelo or ''}".strip().lower()
    if not blob:
        return None
    for m in _MODELOS_CAMIONETA:
        if m in blob:
            return "Camioneta"
    for mk in _MARCAS_MOTO:
        if mk in blob:
            return "Moto"
    return None


def resolver_tipo(tipo_declarado=None, marca=None, modelo=None):
    """Decide el tipo FINAL con el que se cobra:
      1) Si el modelo tiene señal fuerte (GILERA->Moto, KANGOO->Camioneta),
         gana esa (corrige cargas mal hechas).
      2) Si no, usa el tipo declarado (normalizado con sinónimos).
      3) Si nada sirve, "Auto" por defecto.
    Llamala al CREAR/RENOVAR la póliza, antes de pedir el precio.
    """
    inferido = inferir_tipo(marca, modelo)
    if inferido:
        return inferido
    return _norm_tipo(tipo_declarado) or "Auto"


def es_nre(compania):
    """True si la póliza es de la compañía NRE (tolerante a mayúsculas/variantes)."""
    return "nre" in (compania or "").strip().lower()


def precio_vigente(tipo, fecha=None, oficina=None):
    """Precio de la categoría a una fecha (el que pagan las cuotas 2 en adelante,
    y el que muestra una póliza activa). Devuelve None si no está en la lista.

    `oficina` no se usa (Polizando no tiene sucursales) — queda en la firma
    solo por compatibilidad con quien ya la llama con ese argumento.
    """
    fecha = fecha or date.today()
    clave = _norm_tipo(tipo)
    if clave is None:
        return None
    precio = None
    for desde, monto in PRECIOS_NRE.get(clave, []):
        if desde <= fecha:
            precio = monto
    return precio


def precio_anterior(tipo, fecha=None, oficina=None):
    """El gancho de la 1ra cuota (escalón previo / lo que venía pagando)."""
    fecha = fecha or date.today()
    clave = _norm_tipo(tipo)
    if clave is None:
        return None
    vigentes = [monto for (desde, monto) in PRECIOS_NRE.get(clave, []) if desde <= fecha]
    if len(vigentes) >= 2:
        return vigentes[-2]
    if vigentes:
        return vigentes[-1]
    return None


def es_primer_aumento(tipo, fecha=None, oficina=None):
    """True si la fecha cae en el PRIMER escalón del plan (el primer salto).
    Ese aumento, al renovar, va FIJO (sin oferta).
    """
    fecha = fecha or date.today()
    clave = _norm_tipo(tipo)
    if clave is None:
        return False
    escalones = PRECIOS_NRE.get(clave, [])
    idx = -1
    for i, (desde, _monto) in enumerate(escalones):
        if desde <= fecha:
            idx = i
    return idx == 1


def precio_cuotas_renovacion(tipo, fecha=None, oficina=None):
    """Precios de las cuotas al RENOVAR. Devuelve (precio_primera, precio_resto).
    Primer aumento sin oferta; aumentos siguientes con oferta.
    """
    fecha = fecha or date.today()
    vig = precio_vigente(tipo, fecha, oficina)
    if vig is None:
        return (None, None)
    if es_primer_aumento(tipo, fecha, oficina):
        return (vig, vig)
    return (precio_anterior(tipo, fecha, oficina), vig)


def precio_cuotas_alta_nueva(tipo, fecha=None, oficina=None):
    """Precios de las cuotas en un ALTA NUEVA (cliente nuevo).
    Sin promo → todas las cuotas al precio vigente.
    """
    fecha = fecha or date.today()
    vig = precio_vigente(tipo, fecha, oficina)
    if vig is None:
        return (None, None)
    return (vig, vig)


# ──────────────────────────────────────────────────────────────────────────
# DESCUENTO MULTI-VEHÍCULO
# Se aplica según cuántas pólizas ACTIVAS ya tiene el cliente.
#   1er vehículo  → precio normal (sin descuento)
#   2do vehículo  → ~8% menos
#   3ro o más     → ~12% menos
# Números fijos acordados (no porcentaje exacto). Si cambia el precio base,
# actualizar también estas tablas.
# ──────────────────────────────────────────────────────────────────────────
DESCUENTO_MULTIVEHICULO = {
    # tipo: { nivel: precio_cuota }   (nivel 2 = 2do vehículo, 3 = 3ro o más)
    "Auto":      {2: 33000, 3: 31500},
    "Moto":      {2: 16500, 3: 16000},
    "Camioneta": {2: 37500, 3: 36000},
    "Camion":    {2: 69000, 3: 66000},
    "Trailer":   {2: 13800, 3: 13200},
}


def precio_multivehiculo(tipo, oficina, polizas_activas):
    """
    Devuelve el precio de cuota con descuento por multi-vehículo, o None si
    no corresponde descuento (en ese caso se usa el precio normal de siempre).

    `polizas_activas` = cantidad de pólizas ACTIVAS que el cliente YA tiene
    ANTES de crear la nueva. O sea:
        0 activas  → la nueva es el 1er vehículo  → None (precio normal)
        1 activa   → la nueva es el 2do vehículo  → nivel 2 (~8% menos)
        2 o más    → la nueva es el 3ro o más     → nivel 3 (~12% menos)

    `oficina` no se usa (Polizando no tiene sucursales) — queda en la firma
    solo por compatibilidad con quien ya la llama con ese argumento.
    """
    try:
        n = int(polizas_activas or 0)
    except (TypeError, ValueError):
        n = 0

    nivel = n + 1            # qué número de vehículo es la nueva póliza
    if nivel < 2:
        return None          # 1er vehículo: sin descuento
    nivel = 3 if nivel >= 3 else 2

    tn = _norm_tipo(tipo)
    tabla = DESCUENTO_MULTIVEHICULO.get(tn) or DESCUENTO_MULTIVEHICULO.get(tipo)
    return tabla.get(nivel) if tabla else None