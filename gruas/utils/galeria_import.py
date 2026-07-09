from django.apps import apps
from django.core.exceptions import ValidationError
from ..models import AdhesionFoto, TipoFotoAdhesion


def _foto_url(f):
    for a in ("url", "secure_url", "image_url"):
        v = getattr(f, a, None)
        if v:
            return v
    try:
        return f.get("url")
    except Exception:
        return None


def _foto_tipo(f):
    t = getattr(f, "tipo", None) or getattr(f, "categoria", None) or ""
    t = (str(t).upper().strip() or "OTRA")
    if t not in getattr(TipoFotoAdhesion, "values", []):
        t = "OTRA"
    return t


def importar_fotos_adhesion_desde_galeria(*, poliza, adhesion, foto_ids=None, minimo_patente=0):
    """
    Copia fotos desde polizas.FotoVehiculo hacia gruas.AdhesionFoto (adjunta a la adhesión),
    de forma **idempotente** (no duplica). Devuelve un resumen:
        {"creadas": int, "omitidas": int, "objetos": [AdhesionFoto, ...]}
    """
    FotoVehiculo = apps.get_model("polizas", "FotoVehiculo")
    qs = FotoVehiculo.objects.filter(poliza=poliza).order_by("-id")
    if foto_ids:
        qs = qs.filter(id__in=foto_ids)

    creadas = []
    creadas_count = 0
    omitidas_count = 0

    # 1) Importación general (por IDs o todas)
    for fv in qs:
        url = _foto_url(fv)
        if not url:
            continue
        tipo = _foto_tipo(fv)
        public_id = getattr(fv, "public_id", "") or ""

        obj, created = AdhesionFoto.objects.get_or_create(
            adhesion=adhesion,
            url=url,
            defaults={"tipo": tipo, "public_id": public_id},
        )
        if created:
            creadas.append(obj)
            creadas_count += 1
        else:
            # merge defensivo: completar public_id/tipo si viene mejor
            to_update = []
            if public_id and not obj.public_id:
                obj.public_id = public_id
                to_update.append("public_id")
            if tipo and obj.tipo == "OTRA" and tipo != "OTRA":
                obj.tipo = tipo
                to_update.append("tipo")
            if to_update:
                obj.save(update_fields=to_update)
            omitidas_count += 1

    # 2) Asegurar mínimo de PATENTE
    if minimo_patente:
        actuales_patente = adhesion.fotos_adhesion.filter(tipo="PATENTE").count()
        faltan = max(0, minimo_patente - actuales_patente)
        if faltan > 0:
            extra_qs = FotoVehiculo.objects.filter(
                poliza=poliza, tipo__iexact="PATENTE"
            ).order_by("-id")
            # Intentamos hasta satisfacer 'faltan', confiando en get_or_create para no duplicar
            for fv in extra_qs:
                if faltan <= 0:
                    break
                url = _foto_url(fv)
                if not url:
                    continue
                public_id = getattr(fv, "public_id", "") or ""
                obj, created = AdhesionFoto.objects.get_or_create(
                    adhesion=adhesion,
                    url=url,
                    defaults={"tipo": "PATENTE", "public_id": public_id},
                )
                if created:
                    creadas.append(obj)
                    creadas_count += 1
                    faltan -= 1
                else:
                    # merge defensivo
                    to_update = []
                    if public_id and not obj.public_id:
                        obj.public_id = public_id
                        to_update.append("public_id")
                    if obj.tipo == "OTRA":
                        obj.tipo = "PATENTE"
                        to_update.append("tipo")
                    if to_update:
                        obj.save(update_fields=to_update)
                    omitidas_count += 1

    # No consideramos "error" que no se creen nuevas; devolvemos resumen para UX.
    return {"creadas": creadas_count, "omitidas": omitidas_count, "objetos": creadas}
