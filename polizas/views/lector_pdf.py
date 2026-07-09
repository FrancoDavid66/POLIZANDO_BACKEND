# polizas/views/lector_pdf.py
#
# 🆕 LECTOR DE PDF (alta de póliza)
# Recibe uno o varios PDF (cuponera AMCA, certificado Antártida, etc.),
# detecta de qué documento se trata y devuelve los datos extraídos en JSON.
# NO crea nada: solo extrae para que el alta se autocomplete y el operador revise.
#
# Requiere: pip install pdfplumber  (agregar a requirements.txt)
#
# Ruta (se registra en polizas/urls.py):
#   POST /api/polizas/lector-pdf/   (multipart, campo "archivos" — uno o varios)

import re
from datetime import date

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser

# ───────────────────────── helpers de texto ─────────────────────────

_RE_PATENTE = re.compile(r"\b([A-Z]{3}\d{3}|[A-Z]{2}\d{3}[A-Z]{2})\b")


def _extraer_texto(archivo) -> str:
    """Saca todo el texto de un PDF (requiere pdfplumber)."""
    import pdfplumber
    texto = ""
    with pdfplumber.open(archivo) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                texto += t + "\n"
    return texto


def _monto_a_numero(s: str):
    """'71.020,00' -> 71020.00"""
    try:
        return float((s or "").strip().replace(".", "").replace(",", "."))
    except Exception:
        return None


def _fecha_iso(s: str):
    """'27/05/2026' -> '2026-05-27'.

    Descarta fechas con anio imposible para una poliza. Todas las fechas de un
    certificado (emision, vigencia, cupones) caen cerca del presente; si la regex
    llegara a agarrar por error una fecha lejana -tipicamente una fecha de
    nacimiento como 10/06/1965- la ignoramos para que NO se use como base de las
    cuotas. Al quedar vacia, el asistente de carga rapida pide la fecha a mano.
    """
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", (s or "").strip())
    if not m:
        return None
    d, mth, y = m.groups()
    # Validacion basica de dia/mes.
    if not (1 <= int(mth) <= 12) or not (1 <= int(d) <= 31):
        return None
    # Anio plausible: entre 5 anios atras y 6 adelante del anio actual.
    anio = int(y)
    anio_actual = date.today().year
    if anio < anio_actual - 5 or anio > anio_actual + 6:
        return None
    return f"{y}-{mth}-{d}"


def _buscar(pat, texto, g=1, flags=0):
    m = re.search(pat, texto, flags)
    return m.group(g).strip() if m else ""


def _split_nombre(completo: str):
    """Separa apellido y nombre.
    Con coma: 'LEIVA ARMOA, MARTIN' -> ('LEIVA ARMOA', 'MARTIN') [seguro].
    Sin coma: 'CHAMORRO AQUINO WALTER' -> ('CHAMORRO AQUINO', 'WALTER') [última palabra = nombre].
    """
    completo = (completo or "").strip()
    if "," in completo:
        ap, no = completo.split(",", 1)
        return ap.strip(), no.strip()
    partes = completo.split()
    if len(partes) >= 2:
        return " ".join(partes[:-1]), partes[-1]
    return "", completo


def _cia_desde_texto(texto: str) -> str:
    """Detecta la compañía REAL leyendo nombres conocidos (robusto)."""
    up = texto.upper()
    if "NRE SEGUROS" in up or "NRE.COM" in up:
        return "NRE"
    if "ANTARTIDA" in up or "ANTÁRTIDA" in up:
        return "Antártida"
    if "ASOCIACION MUTUAL" in up or "A.M.C.A" in up or "AMCA" in up:
        return "AMCA"
    if "EQUIDAD" in up:
        return "La Equidad"
    return ""


def _canonizar_compania(nombre: str) -> str:
    """Mapea la compañía detectada al nombre que se usa en la app:
       NRE SEGUROS → NRE · LA EQUIDAD → Equidad · FEDERACION* → FEDERACION PATRONAL
       AMCA / ANTÁRTIDA → AMCA. Otras se dejan igual."""
    up = (nombre or "").upper()
    if not up:
        return nombre or ""
    if "NRE" in up:
        return "NRE"
    if "EQUIDAD" in up:
        return "Equidad"
    if "FEDERAC" in up:
        return "FEDERACION PATRONAL"
    if ("ANTARTIDA" in up or "ANTÁRTIDA" in up or "AMCA" in up or "ASOCIACION MUTUAL" in up):
        return "AMCA"
    return nombre


def _ordenar_motor_chasis(motor, chasis):
    """Algunos PDFs (Antártida) cruzan motor y chasis. El chasis (VIN) suele tener
    ~17 caracteres y el motor menos. Si vienen al revés, los corrige."""
    a = (motor or "").strip()
    b = (chasis or "").strip()
    if a and b and len(a) >= 16 and len(b) < 16:
        return b, a  # estaban cruzados
    return a, b


def _normalizar_tipo_vehiculo(raw: str) -> str:
    """Mapea el 'tipo' crudo del PDF a las categorías del modelo Poliza:
    Auto / Camioneta / Camion / Moto / Trailer.

    Es clave para el precio NRE: un camión debe quedar como "Camion" (no "Auto"),
    si no, se cobra el precio de auto. Sin dato -> "" (que lo complete el revisor).
    OJO con el orden: "camion" es substring de "camioneta", así que Camioneta se
    chequea ANTES que Camion.
    """
    t = (raw or "").strip().lower()
    if not t:
        return ""
    # Moto
    if any(k in t for k in ("moto", "ciclomotor", "scooter")):
        return "Moto"
    # Trailer / acoplado
    if any(k in t for k in ("trailer", "tráiler", "acoplado", "remolque", "casa rodante", "semirremolque")):
        return "Trailer"
    # Camioneta / pick-up / furgón / utilitario  (ANTES que Camion)
    if any(k in t for k in ("camioneta", "pick", "furg", "utilitar")):
        return "Camioneta"
    # Camión (carga pesada)
    if any(k in t for k in ("camion", "camión", "tractor", "carga")):
        return "Camion"
    # Auto y derivados (sedán, hatch, coupé, suv, rural, familiar...) y todo lo demás
    return "Auto"


# ───────────────────────── detección de documento ─────────────────────────

def _aplica_cuponera_amca(texto: str) -> bool:
    up = texto.upper()
    return ("ASOCIACION MUTUAL" in up or "RAPIPAGO" in up) and "CUOTA NRO" in up


def _aplica_certificado_antartida(texto: str) -> bool:
    up = texto.upper()
    tiene_cert = "CONSTANCIA DE COBERTURA" in up or "CERTIFICADO DE COBERTURA" in up
    tiene_datos = ("DATOS ASEGURADO" in up or "DATOS DEL VEHÍCULO" in up
                   or "DATOS DEL VEHICULO" in up or "EMITE LA POLIZA" in up)
    es_mercosur = "MERCOSUR" in up or "MERCOSUL" in up
    return tiene_cert and tiene_datos and not es_mercosur


def _aplica_equidad(texto: str) -> bool:
    return "EQUIDAD" in texto.upper()


def _aplica_mercosur(texto: str) -> bool:
    up = texto.upper()
    return "MERCOSUR" in up or "MERCOSUL" in up


def _aplica_certificado_nre(texto: str) -> bool:
    up = texto.upper()
    return "NRE SEGUROS" in up and "CERTIFICADO DE COBERTURA" in up and "MARCA Y MODELO" in up


# ───────────────────────── parsers por documento ─────────────────────────

def _parse_cuponera_amca(texto: str) -> dict:
    """Cupones (lo confiable) + datos del cliente (nombre, dni, tel, domicilio...)."""
    cupones = []
    for nro, vto, imp in re.findall(
        r"Cuota\s*Nro\.?\s*(\d+)\s*VTO\.?:?\s*(\d{2}/\d{2}/\d{4})\s*IMPORTE:?\s*([\d.,]+)", texto, re.IGNORECASE
    ):
        cupones.append({
            "numero": int(nro),
            "vencimiento": _fecha_iso(vto),
            "importe": _monto_a_numero(imp),
        })

    # En la cuponera, el valor de cada dato está en la línea SIGUIENTE a su etiqueta.
    lineas = [l.strip() for l in texto.split("\n")]

    def _despues(label):
        for i, l in enumerate(lineas):
            if label.lower() in l.lower():
                return lineas[i + 1] if i + 1 < len(lineas) else ""
        return ""

    # Nombre: priorizar "APELLIDO, NOMBRE" en una sola línea (lo más confiable en AMCA).
    # En PDFs multipágina el "_despues" agarra cualquier cosa, por eso vamos primero por la coma.
    apellido, nombre = "", ""
    m_coma = re.search(
        r"(?m)^\s*([A-ZÁÉÍÓÚÑ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ]+)*)\s*,\s*([A-ZÁÉÍÓÚÑ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ]+)*)\s*$",
        texto,
    )
    if m_coma:
        apellido, nombre = m_coma.group(1).strip(), m_coma.group(2).strip()
    else:
        nom_linea = _despues("Apellido y Nombre")
        if "," in nom_linea:
            ap, no = nom_linea.split(",", 1)
            apellido, nombre = ap.strip(), no.strip()
        elif nom_linea:
            apellido = nom_linea.strip()
    # Descartar basura accidental (labels que se cuelan por el layout)
    _bad = ("CLAVE", "PAGO", "CUENTA", "DOMICILIO", "LOCALIDAD", "ASOCIACION", "MUTUAL", "DOCUMENTO")
    if any(b in (apellido + " " + nombre).upper() for b in _bad):
        apellido, nombre = "", ""

    # Domicilio + DNI: "JOVELLANOS Y PUCCINI 1200 94767958"
    dom_linea = _despues("Domicilio")
    m_dni = re.search(r"(\d{7,8})\s*$", dom_linea)
    dni = m_dni.group(1) if m_dni else ""
    direccion = re.sub(r"\s*\d{7,8}\s*$", "", dom_linea).strip()

    # Localidad + CP + Teléfono: "VIRREY DEL PINO 1763 1135858428"
    loc_linea = _despues("Localidad")
    m_tel = re.search(r"(\d{10,})\s*$", loc_linea)
    telefono = m_tel.group(1) if m_tel else ""
    if not telefono:
        telefono = _buscar(r"Tel[eé]fonos?\s*:?\s*(\d{8,})", texto) or ""
    resto = re.sub(r"\s*\d{10,}\s*$", "", loc_linea).strip()
    m_cp = re.search(r"(\d{4})\s*$", resto)
    localidad = re.sub(r"\s*\d{4}\s*$", "", resto).strip() if m_cp else resto

    patente = _buscar(_RE_PATENTE.pattern, texto)
    certificado = _buscar(r"Certificado de Cobertura Nro\.?:\s*([\d\s\-]+?)\n", texto)
    # 🆕 Cobertura (código, ej "C9"): "Cobertura: C9- Robo..." / "Descripción Cobertura: C9-..."
    cobertura = _buscar(r"[Cc]obertura:?\s*([A-Z]{1,2}\d{0,2})\s*[-–]", texto) or ""
    # 🆕 Chasis (el PDF lo etiqueta "Carroceria" o "Chasis") + Motor. Claves iguales al resto.
    chasis = _buscar(r"(?:Chasis|Carroceria):\s*([A-Z0-9]{6,})", texto) or ""
    motor = _buscar(r"Motor:\s*([A-Z0-9]{4,})", texto) or ""

    return {
        "cupones": cupones,
        "cliente": {"nombre": nombre, "apellido": apellido, "dni": dni,
                    "telefono": telefono, "direccion": direccion, "localidad": localidad},
        "vehiculo": {"patente": patente, "chasis": chasis, "motor": motor},
        "poliza": {"compania": "AMCA", "certificado": certificado, "cobertura": cobertura},
    }


def _parse_certificado_antartida(texto: str) -> dict:
    """Datos de la póliza/cliente/vehículo (lo confiable de este documento)."""
    numero = _buscar(r"emite la poliza Nº\s*(\d+)", texto)
    asegurado = _buscar(r"datos asegurado:\s*([A-ZÁÉÍÓÚÑ]+(?:\s+[A-ZÁÉÍÓÚÑ]+){1,4})", texto) or \
                _buscar(r"Asegurado:\s*([A-ZÁÉÍÓÚÑ]+(?:\s+[A-ZÁÉÍÓÚÑ]+){1,4})", texto)
    dni = _buscar(r"documento:\s*[A-Z]{0,3}\s*(\d{6,})", texto) or \
          _buscar(r"DNI\s*:?\s*(\d{6,})", texto)

    # Vehículo: probar tabla "<MODELO> <PATENTE> <AÑO>", luego tarjeta "Marca XXX" + "Año:"
    veh = re.search(r"\n([A-ZÁÉÍÓÚÑ0-9 ./]+?)\s+([A-Z]{3}\d{3}|[A-Z]{2}\d{3}[A-Z]{2})\s+(\d{4})\b", texto)
    marca_modelo = veh.group(1).strip() if veh else _buscar(r"(?m)^Marca\s+([A-Z].+)$", texto)
    patente = (veh.group(2) if veh else "") or _buscar(r"Dominio:\s*([A-Z0-9]+)", texto) or _buscar(_RE_PATENTE.pattern, texto)
    anio = int(veh.group(3)) if veh else None
    if not anio:
        _a = _buscar(r"A:?ño:\s*(\d{4})", texto)
        anio = int(_a) if _a else None

    # Marca = 1ª palabra, Modelo = el resto
    marca, modelo = "", ""
    if marca_modelo:
        _t = marca_modelo.split()
        marca, modelo = _t[0], " ".join(_t[1:])

    motor = _buscar(r"Motor:\s*([A-Z0-9]+)", texto)
    chasis = _buscar(r"Chasis:\s*([A-Z0-9]+)", texto)

    vig = re.search(r"desde las 12:00 del (\d{2}/\d{2}/\d{4}) hasta las 12:00 del (\d{2}/\d{2}/\d{4})", texto)
    vig_desde = _fecha_iso(vig.group(1)) if vig else ""
    vig_hasta = _fecha_iso(vig.group(2)) if vig else ""

    return {
        "cupones": [],
        "cliente": {"nombre": asegurado, "dni": dni},
        "vehiculo": {"marca_modelo": marca_modelo, "marca": marca, "modelo": modelo,
                     "patente": patente, "anio": anio, "motor": motor, "chasis": chasis},
        "poliza": {"numero": numero, "compania": "Antártida",
                   "vigencia_desde": vig_desde, "vigencia_hasta": vig_hasta},
    }


def _parse_poliza_equidad(texto: str) -> dict:
    """La Equidad: frente de póliza + factura. Trae cliente, vehículo y cuotas completos."""
    g = lambda pat, fl=0: _buscar(pat, texto, 1, fl)

    nombre    = g(r"ASEGURADO:\s*(.+?)\s+Cod\. Aseg\.")
    domicilio = g(r"Domicilio:\s*(.+?)\s+Tel\.")
    telefono  = g(r"Tel\.:\s*(\d{6,})")
    localidad = g(r"Localidad:\s*\(?\d*\)?\s*(.+?)\s+CUIL")
    cuit      = g(r"CUIL/CUIT\s*:?\s*(\d+)")
    numero    = g(r"P\u00f3liza:\s*\d+\s*-\s*0*(\d+)") or g(r"AUTOMOTORES\s+(\d{5,})\s+\d")
    cobertura = g(r"COBERTURA:\s*(.+)")

    tipo = g(r"TIPO:\s*(.+?)\s+MARCA")
    marca_modelo = g(r"MARCA/MODELO:\s*(.+)")
    anio   = g(r"A\u00d1O:\s*(\d{4})")
    patente = g(r"PATENTE:\s*([A-Z0-9]+)")
    motor  = g(r"MOTOR:\s*([A-Z0-9]+)")
    chasis = g(r"CHASIS:\s*([A-Z0-9]+)")

    vig_d = g(r"Desde las 12:00 Hs\. del (\d{2}/\d{2}/\d{4})")
    vig_h = g(r"Hasta las 12:00 Hs\. del (\d{2}/\d{2}/\d{4})")

    cupones = []
    for n, f, i in re.findall(r"(?m)^\s*(\d+)\s+(\d{2}/\d{2}/\d{4})\s+([\d.]+,\d{2})", texto):
        cupones.append({"numero": int(n), "vencimiento": _fecha_iso(f), "importe": _monto_a_numero(i)})

    return {
        "cupones": cupones,
        "cliente": {"nombre": nombre, "dni": cuit, "telefono": telefono,
                    "direccion": domicilio, "localidad": localidad},
        "vehiculo": {"marca_modelo": marca_modelo, "patente": patente,
                     "anio": int(anio) if anio else None, "motor": motor, "chasis": chasis,
                     "tipo": tipo},
        "poliza": {"numero": numero, "compania": "La Equidad", "cobertura": cobertura,
                   "vigencia_desde": _fecha_iso(vig_d), "vigencia_hasta": _fecha_iso(vig_h)},
    }


def _parse_mercosur(texto: str) -> dict:
    """Certificado MERCOSUR. Soporta 2 formatos:
       - NRE: tarjeta con 'Marca:/Tipo:/Dominio:/Motor:/Chasis:'.
       - Antártida: 'Marca/Marca - Modelo/Modelo : ... Ano/Año :' + carnet 'Patente:/Año:'.
    """
    g = lambda pat, fl=0: _buscar(pat, texto, 1, fl)
    compania = _cia_desde_texto(texto)

    marca_modelo = (
        g(r"Marca/Marca\s*-\s*Modelo/Modelo\s*:\s*(.+?)\s+Ano/Año\s*:")
        or g(r"(?m)^Vehiculo\s*:\s*(.+?)\s+(?:Vial|Endoso)")
        or g(r"(?m)^Vehiculo\s*:\s*(.+)$")
        or g(r"(?m)^Marca:\s*([A-Z0-9][A-Z0-9 ./]*)")  # NRE: solo MAYÚSC/números (corta texto legal)
    )

    anio_s = (
        g(r"Ano/Año\s*:\s*(\d{4})")
        or g(r"(?m)^Año:\s*(\d{4})")
        or g(r"-\s*(\d{4})\s+[A-Z0-9]{8,}")
    )
    anio = int(anio_s) if anio_s else None

    patente = (
        g(r"Placa/Matricula:\s*([A-Z0-9]+)")
        or g(r"(?m)^Patente:\s*([A-Z0-9]+)")
        or g(r"Dominio:\s*([A-Z0-9]+)")
        or _buscar(_RE_PATENTE.pattern, texto)
    )

    motor = g(r"(?m)^Motor:\s*([A-Z0-9]+)")
    chasis = g(r"Chassi/Chasis\s*:\s*([A-Z0-9]+)") or g(r"Chasis:\s*([A-Z0-9]+)")
    tipo = g(r"(?m)^Tipo:\s*(.+?)\s*(?:Dominio:|$)")

    marca, modelo = "", ""
    if marca_modelo:
        _t = marca_modelo.split()
        marca, modelo = _t[0], " ".join(_t[1:])

    numero = (
        g(r"Poliza Nro\.?:\s*(\d+)")
        or g(r"Póliza N[°ºo]?\s*:?\s*(\d+)")
        or g(r"Número:\s*(\d+)")
    )

    m_vig = re.search(r"(\d{2}/\d{2}/\d{4})\s*(?:-|Hasta:?)\s*(\d{2}/\d{2}/\d{4})", texto)
    vig_d = _fecha_iso(m_vig.group(1)) if m_vig else ""
    vig_h = _fecha_iso(m_vig.group(2)) if m_vig else ""

    # Cliente (palabras de >=2 letras MAYÚSC, así no se cuela "Nota", "N", etc.)
    asegurado = (
        g(r"(?m)^Asegurado:\s*([A-ZÁÉÍÓÚÑ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ]{2,})*)")
        or g(r"Raz[oó]n Social\s*:\s*([A-ZÁÉÍÓÚÑ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ]{2,})*)")
    )
    dni = g(r"DNI\s*:?\s*(\d{6,})") or g(r"Documento\s*:?\s*[A-Z]{0,3}\s*(\d{6,})")

    return {
        "cupones": [],
        "cliente": {"nombre": asegurado, "dni": dni},
        "vehiculo": {
            "marca_modelo": marca_modelo, "marca": marca, "modelo": modelo,
            "patente": patente, "anio": anio, "motor": motor, "chasis": chasis, "tipo": tipo,
        },
        "poliza": {
            "numero": numero, "compania": compania,
            "vigencia_desde": vig_d, "vigencia_hasta": vig_h,
        },
    }


def _parse_certificado_nre(texto: str) -> dict:
    """Certificado de Cobertura NRE (formato 'Label: Valor', el más completo).
    Trae cliente con DNI, domicilio, localidad/provincia y vehículo con carrocería."""
    g = lambda pat, fl=0: _buscar(pat, texto, 1, fl)

    asegurado = g(r"Aser?gurado:\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ]+)")
    dni = g(r"CUIT\s*/\s*DNI:\s*([\d\-]+)")
    domicilio = g(r"(?m)^Domicilio:\s*(.+?)\s+Secci[oó]n:") or g(r"(?m)^Domicilio:\s*(.+)$")
    localidad = g(r"Localidad:\s*(.+?)\s+Propuesta:") or g(r"Localidad:\s*([A-Za-zÁÉÍÓÚÑ ]+)")
    cp = g(r"C\.P\.:\s*(\d+)")
    provincia = g(r"Provincia:\s*(.+?)\s+Endoso:") or g(r"Provincia:\s*([A-Za-zÁÉÍÓÚÑ ]+)")

    numero = g(r"Propuesta:\s*(\d+)")
    cobertura = g(r"(?m)^COBERTURA:\s*([A-Z0-9+ ]+?)\s*$")

    marca_modelo = g(r"Marca y Modelo:\s*([A-Z0-9][A-Z0-9 ./]*)")
    tipo = g(r"Tipo de Veh[ií]culo:\s*(.+?)\s+Accesorios:") or g(r"Tipo de Veh[ií]culo:\s*([A-Za-zÁÉÍÓÚÑ ]+)")
    carroceria = g(r"Carroceria:\s*([A-Za-zÁÉÍÓÚÑ]+)")
    _anio = g(r"(?m)Año:\s*(\d{4})")
    anio = int(_anio) if _anio else None
    patente = g(r"Patente:\s*([A-Z0-9]+)")
    motor = g(r"Motor:\s*([A-Z0-9]+)")
    chasis = g(r"Chasis:\s*([A-Z0-9]+)")

    m_vig = re.search(r"Vigencia:\s*(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})", texto)
    vig_d = _fecha_iso(m_vig.group(1)) if m_vig else ""
    vig_h = _fecha_iso(m_vig.group(2)) if m_vig else ""

    marca, modelo = "", ""
    if marca_modelo:
        _t = marca_modelo.split()
        marca, modelo = _t[0], " ".join(_t[1:])

    return {
        "cupones": [],
        "cliente": {"nombre": asegurado, "dni": dni, "direccion": domicilio,
                    "localidad": localidad, "provincia": provincia, "cp": cp},
        "vehiculo": {"marca_modelo": marca_modelo, "marca": marca, "modelo": modelo,
                     "patente": patente, "anio": anio, "motor": motor, "chasis": chasis,
                     "tipo": tipo, "carroceria": carroceria},
        "poliza": {"numero": numero, "compania": "NRE", "cobertura": cobertura,
                   "vigencia_desde": vig_d, "vigencia_hasta": vig_h},
    }


def _parse_generico(texto: str) -> dict:
    """Respaldo: junta lo que pueda para que el operador confirme."""
    cupones = []
    for nro, vto, imp in re.findall(
        r"Cuota[^\d]*(\d+).*?(\d{2}/\d{2}/\d{4}).*?([\d.]{2,}[,]\d{2})", texto, re.IGNORECASE
    ):
        cupones.append({"numero": int(nro), "vencimiento": _fecha_iso(vto), "importe": _monto_a_numero(imp)})
    return {
        "cupones": cupones,
        "cliente": {},
        "vehiculo": {"patente": _buscar(_RE_PATENTE.pattern, texto)},
        "poliza": {},
    }


# ───────────────────────── merge (no pisar con vacío) ─────────────────────────

def _merge(acc: dict, nuevo: dict):
    for seccion in ("cliente", "vehiculo", "poliza"):
        for k, v in (nuevo.get(seccion) or {}).items():
            if v and not acc[seccion].get(k):
                acc[seccion][k] = v
    if nuevo.get("cupones") and not acc["cupones"]:
        acc["cupones"] = nuevo["cupones"]


# ───────────────────────── endpoint ─────────────────────────

class LectorPdfView(APIView):
    """Recibe PDF(s) y devuelve los datos extraídos (sin crear nada)."""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        archivos = request.FILES.getlist("archivos") or list(request.FILES.values())
        if not archivos:
            return Response({"ok": False, "error": "No se recibió ningún PDF."},
                            status=status.HTTP_400_BAD_REQUEST)

        acc = {"cliente": {}, "vehiculo": {}, "poliza": {}, "cupones": []}
        detectados, avisos = [], []

        for f in archivos:
            nombre = getattr(f, "name", "archivo.pdf")
            try:
                texto = _extraer_texto(f)
            except Exception:
                avisos.append(f"No se pudo leer '{nombre}' (¿es un PDF escaneado/imagen?).")
                continue

            if not texto.strip():
                avisos.append(f"'{nombre}' no tiene texto legible (parece escaneado).")
                continue

            # 🆕 MULTI-PARSER: corremos TODOS los parsers que apliquen y mergeamos.
            # Orden = prioridad de merge (el primero gana en campos repetidos).
            # cuponera_amca va primero para que la compañía quede "AMCA" en combos AMCA+Antártida.
            aplicados = []
            if _aplica_cuponera_amca(texto):
                _merge(acc, _parse_cuponera_amca(texto)); aplicados.append("cuponera_amca")
            if _aplica_certificado_antartida(texto):
                _merge(acc, _parse_certificado_antartida(texto)); aplicados.append("certificado_antartida")
            if _aplica_certificado_nre(texto):
                _merge(acc, _parse_certificado_nre(texto)); aplicados.append("certificado_nre")
            if _aplica_equidad(texto):
                _merge(acc, _parse_poliza_equidad(texto)); aplicados.append("poliza_equidad")
            if _aplica_mercosur(texto):
                _merge(acc, _parse_mercosur(texto)); aplicados.append("mercosur")
            if not aplicados:
                _merge(acc, _parse_generico(texto))
                avisos.append(f"'{nombre}': compañía no reconocida, revisá los datos extraídos.")
            detectados.extend(aplicados or ["desconocido"])

        # Normalizar apellido / nombre
        cli = acc["cliente"]
        nombre_full = (cli.get("nombre") or "").strip()
        apellido = (cli.get("apellido") or "").strip()
        if apellido and nombre_full.upper().startswith(apellido.upper()):
            # El nombre trae el apellido adelante (vino el nombre completo) -> lo quitamos
            resto = nombre_full[len(apellido):].strip()
            if resto:
                cli["nombre"] = resto
        elif nombre_full and not apellido:
            ap, no = _split_nombre(nombre_full)
            if ap:
                cli["apellido"], cli["nombre"] = ap, no

        # 🆕 Corregir motor/chasis cruzados (Antártida los invierte)
        _v = acc["vehiculo"]
        _m, _ch = _ordenar_motor_chasis(_v.get("motor"), _v.get("chasis"))
        if _m:
            _v["motor"] = _m
        if _ch:
            _v["chasis"] = _ch

        # 🆕 Normalizar el tipo de vehículo a las categorías del modelo
        # (Auto/Camioneta/Camion/Moto/Trailer) para que el precio NRE salga bien.
        if _v.get("tipo"):
            _v["tipo"] = _normalizar_tipo_vehiculo(_v["tipo"])

        # 🆕 Canonizar el nombre de compañía como lo usa la app (NRE/Equidad/FEDERACION PATRONAL/AMCA)
        if acc["poliza"].get("compania"):
            acc["poliza"]["compania"] = _canonizar_compania(acc["poliza"]["compania"])

        if not acc["cupones"]:
            avisos.append("No se detectaron cupones. Cargalos a mano o subí la cuponera.")
        if not acc["cliente"].get("nombre"):
            avisos.append("No se detectó el nombre del asegurado, revisalo.")

        return Response({
            "ok": True,
            "documentos_detectados": detectados,
            "datos": acc,
            "avisos": avisos,
        })