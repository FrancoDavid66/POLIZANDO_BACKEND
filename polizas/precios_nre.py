# polizas/precios_nre.py
# ──────────────────────────────────────────────────────────────────────────
# LISTA DE PRECIOS — SOLO compañía NRE.
#
# Única fuente de verdad del plan de aumentos escalonado.
# El precio de cada categoría se determina por la FECHA: como los escalones y
# las renovaciones son los dos cada 3 meses, no hace falta llevar la cuenta de
# "en qué escalón va cada póliza" — se mira la fecha y listo.
#
# 🏢 EXCEPCIÓN El Talita (oficina OFI-05): SOLO el AUTO va distinto.
#    - El cliente NUEVO entra más barato ($25.000) y lo mantiene todo el
#      trimestre. Recién el 01/10 sube (1ra cuota gancho $30.000, resto $35.000).
#    - El que RENUEVA paga un escalón más: hoy $30.000 (sin descuento, es el
#      primer salto). Desde el 01/10 sube con descuento en la 1ra cuota, igual
#      que las otras oficinas.
#    El resto de los tipos (moto, camioneta, etc.) son iguales en todas lados.
#
# Cómo se usa:
#   - Renovación  → precio_cuotas_renovacion(tipo, fecha, oficina)
#   - Alta nueva  → precio_cuotas_alta_nueva(tipo, fecha, oficina)
#   - Portal      → precio_vigente / precio_cuotas_renovacion para mostrar
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

# 🏢 El Talita (OFI-05) — SOLO auto. Formato: (fecha_desde, gancho, vigente)
#    gancho  = precio de la 1ra cuota (suaviza el salto).
#    vigente = precio del resto de las cuotas.
#
# ALTA NUEVA (cliente nuevo): arranca a $25.000 todo el trimestre.
PRECIOS_NRE_TALITA_AUTO = [
    (date(1900, 1, 1),  25000, 25000),
    (date(2026, 10, 1), 30000, 35000),
    (date(2027, 1, 1),  35000, 39500),
    (date(2027, 4, 1),  39500, 44500),
]
# RENOVACIÓN: un escalón más. Hoy $30.000 sin descuento (primer salto);
#             desde el 01/10, con descuento en la 1ra cuota.
PRECIOS_NRE_TALITA_AUTO_RENOV = [
    (date(1900, 1, 1),  30000, 30000),
    (date(2026, 10, 1), 30000, 35000),
    (date(2027, 1, 1),  35000, 39500),
    (date(2027, 4, 1),  39500, 44500),
]


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


def es_talita(oficina):
    """True si la oficina es El Talita (OFI-05).
    Tolera: objeto Oficina (usa .codigo / .nombre), texto plano o id.
    """
    if oficina is None:
        return False
    cod = str(getattr(oficina, "codigo", "") or "").strip().lower()
    nom = str(getattr(oficina, "nombre", "") or "").strip().lower()
    txt = str(oficina).strip().lower()
    blob = " ".join([cod, nom, txt])
    return "talita" in blob or "ofi-05" in blob or "ofi-5" in blob


def _es_talita_auto(tipo, oficina):
    """El Talita SOLO tiene precio especial para el auto."""
    return _norm_tipo(tipo) == "Auto" and es_talita(oficina)


def _talita_periodo(tabla, fecha):
    """(gancho, vigente) del período vigente de una tabla Talita a una fecha."""
    gancho, vigente = tabla[0][1], tabla[0][2]
    for desde, g, v in tabla:
        if desde <= fecha:
            gancho, vigente = g, v
    return gancho, vigente


def precio_vigente(tipo, fecha=None, oficina=None):
    """Precio de la categoría a una fecha (el que pagan las cuotas 2 en adelante,
    y el que muestra una póliza activa). Devuelve None si no está en la lista.
    En El Talita auto, es el precio "actual" del cliente (tabla de alta).
    """
    fecha = fecha or date.today()
    if _es_talita_auto(tipo, oficina):
        _, vig = _talita_periodo(PRECIOS_NRE_TALITA_AUTO, fecha)
        return vig
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
    if _es_talita_auto(tipo, oficina):
        gancho, _ = _talita_periodo(PRECIOS_NRE_TALITA_AUTO, fecha)
        return gancho
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
    if _es_talita_auto(tipo, oficina):
        # En El Talita auto la renovación se maneja con su propia tabla, así que
        # esta función no decide ahí; devolvemos False por compatibilidad.
        return False
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
    - El Talita auto: tabla propia (hoy $30.000 fijo; desde 01/10 con descuento).
    - Resto: primer aumento sin oferta; aumentos siguientes con oferta.
    """
    fecha = fecha or date.today()
    if _es_talita_auto(tipo, oficina):
        return _talita_periodo(PRECIOS_NRE_TALITA_AUTO_RENOV, fecha)
    vig = precio_vigente(tipo, fecha, oficina)
    if vig is None:
        return (None, None)
    if es_primer_aumento(tipo, fecha, oficina):
        return (vig, vig)
    return (precio_anterior(tipo, fecha, oficina), vig)


def precio_cuotas_alta_nueva(tipo, fecha=None, oficina=None):
    """Precios de las cuotas en un ALTA NUEVA (cliente nuevo).
    - El Talita auto: tabla propia (hoy $25.000; desde 01/10 con gancho).
    - Resto: SIN promo → todas las cuotas al precio vigente.
    """
    fecha = fecha or date.today()
    if _es_talita_auto(tipo, oficina):
        return _talita_periodo(PRECIOS_NRE_TALITA_AUTO, fecha)
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
# Aplica en TODAS las oficinas. El Talita usa su propia base para el auto
# (el resto de los tipos en El Talita usan la tabla general).
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

# El Talita: solo el AUTO tiene base propia ($25.000).
DESCUENTO_MULTIVEHICULO_TALITA_AUTO = {2: 23000, 3: 22000}


def precio_multivehiculo(tipo, oficina, polizas_activas):
    """
    Devuelve el precio de cuota con descuento por multi-vehículo, o None si
    no corresponde descuento (en ese caso se usa el precio normal de siempre).

    `polizas_activas` = cantidad de pólizas ACTIVAS que el cliente YA tiene
    ANTES de crear la nueva. O sea:
        0 activas  → la nueva es el 1er vehículo  → None (precio normal)
        1 activa   → la nueva es el 2do vehículo  → nivel 2 (~8% menos)
        2 o más    → la nueva es el 3ro o más     → nivel 3 (~12% menos)
    """
    try:
        n = int(polizas_activas or 0)
    except (TypeError, ValueError):
        n = 0

    nivel = n + 1            # qué número de vehículo es la nueva póliza
    if nivel < 2:
        return None          # 1er vehículo: sin descuento
    nivel = 3 if nivel >= 3 else 2

    if _es_talita_auto(tipo, oficina):
        return DESCUENTO_MULTIVEHICULO_TALITA_AUTO.get(nivel)

    tn = _norm_tipo(tipo)
    tabla = DESCUENTO_MULTIVEHICULO.get(tn) or DESCUENTO_MULTIVEHICULO.get(tipo)
    return tabla.get(nivel) if tabla else None