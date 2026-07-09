# solicitudes/signals.py
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

# Modelos de Solicitudes
from .models import SolicitudDocumento, SolicitudSeguro

# Modelos de Pólizas (tipos actualizados: SIN VIN y SIN ENTORNO)
from polizas.models import (
    Poliza,
    FotoVehiculo,
    OrigenFotoVehiculo,
    TipoFotoVehiculo,
    PolizaDocumento,
    TipoDocumento,
)

# Cliente (opcional: si la app está disponible)
try:
    from clientes.models import Cliente  # noqa
except Exception:  # pragma: no cover
    Cliente = None


# --------------------------------------------------------------------------------------
# Helpers de mapeo (seguros ante tipos desconocidos y SIN referenciar VIN/ENTORNO)
# --------------------------------------------------------------------------------------

# Conjunto de tipos que consideramos "fotos" (coinciden con Polizas.TipoFotoVehiculo)
_FOTO_TIPOS = {
    "PATENTE",
    "FRENTE",
    "LATERAL_IZQ",
    "LATERAL_DER",
    "TRASERA",
    "INTERIOR",
    "EQUIPO_GNC",
    "OBLEA_GNC",
    "OTRA",
    # NOTA: VIN y ENTORNO se eliminaron del modelo de Pólizas. Si llegaran de legacy, los tratamos como "OTRA".
}

# Mapeo de documentos de cliente (DNI/Pasaporte) -> campos del modelo Cliente
_CLIENTE_DOC_FLAGS = {
    "DNI_FRENTE": "archivo_dni_frente",
    "DNI_DORSO": "archivo_dni_dorso",
    "PASAPORTE_FRENTE": "archivo_pasaporte_frente",
    "PASAPORTE_DORSO": "archivo_pasaporte_dorso",
}


def _map_foto_tipo(valor: str) -> str:
    """Devuelve un miembro válido de TipoFotoVehiculo o OTRA si no existe."""
    valor = (valor or "").strip().upper()
    try:
        return getattr(TipoFotoVehiculo, valor)
    except AttributeError:
        return getattr(TipoFotoVehiculo, "OTRA", "OTRA")


def _map_doc_tipo(valor: str):
    """
    Devuelve un miembro de TipoDocumento o None para omitir.
    Regla:
      - VTV: no se usa más → omitimos
      - REGISTRO / REGISTRO_CONDUCIR: no se usa más → omitimos
      - OBLEA_GNC: si existe el enum en Póliza, se replica; si no existe, cae a OTRO
    """
    valor = (valor or "").strip().upper()
    if valor in {"VTV", "REGISTRO", "REGISTRO_CONDUCIR"}:
        return None  # ya no se replica
    # 🆕 PDFs de la carga rápida (póliza / cupones / certificado): conservamos un
    #    tipo legible aunque no esté en el enum (PolizaDocumento.tipo es texto libre).
    #    Normalizamos el sufijo numérico (CUPONERA_1 → CUPONERA) para que queden prolijos.
    if valor.startswith("POLIZA"):
        return "POLIZA"
    if valor.startswith("CUPONERA"):
        return "CUPONERA"
    if valor.startswith("CERTIFICADO"):
        return "CERTIFICADO"
    try:
        return getattr(TipoDocumento, valor)
    except AttributeError:
        # Si el tipo no existe en el enum actual del modelo, degradamos a OTRO
        return getattr(TipoDocumento, "OTRO", None)


def _get_attr(obj, *names, default=None):
    """Obtiene el primer atributo existente en obj de la lista names."""
    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    return default


# 🚀 FIX MAGISTRAL: Leemos el sello "ES_FOTO" que manda el Frontend
def _is_foto_tipo(instance, valor: str) -> bool:
    if getattr(instance, "notas", "") == "ES_FOTO":
        return True
    return (valor or "").strip().upper() in _FOTO_TIPOS


def _auto_set_foto_perfil(poliza: Poliza, url: str, preferida: str):
    """
    Setea foto de perfil si está habilitado y conviene.
    preferida: 'FRENTE' o 'PATENTE' normalmente.
    """
    if not getattr(settings, "SOLICITUDES_AUTO_SET_FOTO_PERFIL", True):
        return
    if not url:
        return
    # Si ya hay foto y NO se permite sobreescribir, salir.
    if getattr(poliza, "foto_perfil_url", "") and not getattr(settings, "SOLICITUDES_SOBREESCRIBIR_FOTO_PERFIL", False):
        return
    # Guardar
    poliza.foto_perfil_url = url
    fields = ["foto_perfil_url"]
    # si existe el public_id en el modelo, lo limpiamos (o podríamos setearlo si llega)
    if hasattr(poliza, "foto_perfil_public_id"):
        # poliza.foto_perfil_public_id = ""
        fields.append("foto_perfil_public_id")
    poliza.save(update_fields=fields)


def _try_copy_to_cliente_from_doc(solicitud: SolicitudSeguro, tipo_str: str, url: str):
    """
    Copia automáticamente DNI/Pasaporte al Cliente si:
      - existe Póliza asociada y, por ende, Cliente,
      - el tipo es uno de los aceptados,
      - y está habilitado por settings (SOLICITUDES_SOBREESCRIBIR_DOCS_CLIENTE=True).
    """
    if not url or not Cliente:
        return

    if not getattr(settings, "SOLICITUDES_SOBREESCRIBIR_DOCS_CLIENTE", True):
        return

    # Buscar la póliza y cliente relacionados
    poliza_id = getattr(solicitud, "poliza_id", None)
    if not poliza_id:
        return
    try:
        poliza = Poliza.objects.select_related("cliente").only("id", "cliente").get(id=poliza_id)
    except Poliza.DoesNotExist:
        return

    cli = getattr(poliza, "cliente", None)
    if not cli:
        return

    field = _CLIENTE_DOC_FLAGS.get(tipo_str)
    if not field or not hasattr(cli, field):
        return

    # Si ya hay valor y no queremos sobreescribir, salir
    current = getattr(cli, field, "") or ""
    if current and not getattr(settings, "SOLICITUDES_SOBREESCRIBIR_DOCS_CLIENTE", True):
        return

    setattr(cli, field, url)
    # Guardamos SOLO ese campo; el save() del modelo reajustará "estado", pero update_fields limitará columnas.
    try:
        cli.save(update_fields=[field])
    except Exception:
        # Si hubiera un save override que requiera todo, hacemos un save completo como fallback.
        cli.save()


# --------------------------------------------------------------------------------------
# Réplica automática de documentos/fotos de la Solicitud hacia la Póliza asociada
# y copia opcional a Cliente (DNI/Pasaporte).
# --------------------------------------------------------------------------------------

@receiver(post_save, sender=SolicitudDocumento)
def solicitudes__replicar_documento_a_poliza(sender, instance: SolicitudDocumento, created, **kwargs):
    """
    Cuando se crea/actualiza un documento de Solicitud:
    - Si la Solicitud está asociada a una Póliza, replicamos:
        * Fotos → polizas.FotoVehiculo (mapeando tipo; VIN/ENTORNO se transforman en OTRA)
          ⮕ Copiamos 'etiquetas' si existen; agregamos etiquetas por defecto según tipo.
        * Documentos → polizas.PolizaDocumento (omitimos VTV y REGISTRO/REGISTRO_CONDUCIR)
    - Además (nuevo):
        * Si el tipo es DNI/PASAPORTE (frente/dorso), copiamos la URL al perfil del Cliente.
    """
    # ¿Tenemos activada la réplica automática?
    if not getattr(settings, "SOLICITUDES_AUTO_REPLICAR", True):
        return

    solicitud = _get_attr(instance, "solicitud")
    if not solicitud or not isinstance(solicitud, SolicitudSeguro):
        return

    poliza_id = _get_attr(solicitud, "poliza_id")
    if not poliza_id:
        return

    # Campos comunes (tolerantes a nombres distintos)
    tipo_str = str(_get_attr(instance, "tipo", default="OTRO") or "OTRO").strip().upper()
    url = _get_attr(instance, "url", "archivo_url", default=None)
    if not url:
        return  # Nada que replicar

    public_id = _get_attr(instance, "public_id", default="") or ""
    nombre = _get_attr(instance, "nombre", "filename", default="") or ""
    mime = _get_attr(instance, "mime", "content_type", default="") or ""
    # Negocio actual: no exigimos vencimiento para ningún documento
    vencimiento = _get_attr(instance, "vencimiento", "fecha_vencimiento", default=None)

    # --- FOTOS ---
    # 🚀 FIX: Pasamos 'instance' para leer las 'notas'
    if _is_foto_tipo(instance, tipo_str):
        foto_tipo = _map_foto_tipo(tipo_str)

        # ====== etiquetas ======
        etiquetas = []
        inst_tags = getattr(instance, "etiquetas", None)
        if isinstance(inst_tags, (list, tuple)):
            for x in inst_tags:
                if x is None:
                    continue
                s = str(x).strip()
                if s:
                    etiquetas.append(s.lower())

        if tipo_str == "EQUIPO_GNC":
            etiquetas += ["gnc", "tubo"]
        elif tipo_str == "OBLEA_GNC":
            etiquetas += ["gnc", "oblea"]
        elif tipo_str == "INTERIOR":
            etiquetas += ["interior"]
        elif tipo_str in {"FRENTE", "TRASERA", "LATERAL_IZQ", "LATERAL_DER"}:
            etiquetas += ["carroceria"]
        elif tipo_str == "PATENTE":
            etiquetas += ["patente"]

        if etiquetas:
            seen = set()
            etiquetas = [e for e in etiquetas if not (e in seen or seen.add(e))]

        existente = FotoVehiculo.objects.filter(poliza_id=poliza_id, tipo=foto_tipo, url=url).first()
        if not existente:
            FotoVehiculo.objects.create(
                poliza_id=poliza_id,
                tipo=foto_tipo,
                url=url,
                public_id=public_id,
                origen=getattr(OrigenFotoVehiculo, "ONBOARDING", "ONBOARDING"),
                etiquetas=etiquetas or [],
            )
        else:
            if etiquetas:
                nuevas = list(dict.fromkeys((existente.etiquetas or []) + etiquetas))
                if nuevas != (existente.etiquetas or []):
                    existente.etiquetas = nuevas
                    existente.save(update_fields=["etiquetas"])

        # Set foto de perfil si corresponde
        if tipo_str in {"FRENTE", "PATENTE"}:
            try:
                poliza = Poliza.objects.only("id", "foto_perfil_url").get(id=poliza_id)
                _auto_set_foto_perfil(poliza, url, preferida=tipo_str)
            except Poliza.DoesNotExist:
                pass

        return

    # --- DOCUMENTOS ---
    doc_tipo = _map_doc_tipo(tipo_str)
    if doc_tipo:
        PolizaDocumento.objects.update_or_create(
            poliza_id=poliza_id,
            tipo=doc_tipo,
            url=url,
            defaults={
                "public_id": public_id,
                "nombre": nombre or tipo_str,
                "mime": mime,
                "vencimiento": vencimiento or None,
            },
        )

    # --- NUEVO: Copia al Cliente si es DNI/Pasaporte ---
    if tipo_str in _CLIENTE_DOC_FLAGS:
        _try_copy_to_cliente_from_doc(solicitud, tipo_str, url)