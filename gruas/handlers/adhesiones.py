# gruas/handlers/adhesiones.py
from datetime import datetime, date
from django.utils import timezone
from django.db import transaction, IntegrityError
from django.core.exceptions import ValidationError

from ..models import (
    AdhesionGrua, EstadoAdhesion, AdhesionFoto, TipoFotoAdhesion
)
from ..utils.validaciones import poliza_vigente
from ..utils.galeria_import import importar_fotos_adhesion_desde_galeria

__all__ = [
    "activar_adhesion",
    "pausar_adhesion",
    "cancelar_adhesion",
]


def _parse_fecha(fecha, default=None) -> date:
    """Acepta date o str en formatos comunes. Devuelve date o lanza ValidationError."""
    if not fecha:
        return default or timezone.localdate()
    if isinstance(fecha, date):
        return fecha
    if isinstance(fecha, str):
        txt = fecha.strip()
        # ISO: YYYY-MM-DD o YYYY-MM-DDTHH:MM:SS
        try:
            return datetime.fromisoformat(txt).date()
        except Exception:
            pass
        for fmt in ("%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(txt, fmt).date()
            except Exception:
                continue
    raise ValidationError("Formato inválido para 'fecha_activacion'. Usá YYYY-MM-DD o DD/MM/YYYY.")


@transaction.atomic
def activar_adhesion(
    *,
    poliza,
    plan,
    fecha_activacion=None,
    notas="",
    fotos=None,
    fotos_galeria_ids=None,
    auto_importar_galeria=False
):
    """
    Crea una AdhesionGrua en estado ACTIVA para la póliza indicada.

    - Valida que la póliza esté vigente.
    - Evita duplicar una adhesión ACTIVA/PAUSADA para la misma póliza.
    - Adjunta fotos nuevas (lista de dicts {url, public_id?, tipo?}) de forma idempotente.
    - Importa fotos desde la galería (polizas.FotoVehiculo) por IDs (idempotente).
    - Si auto_importar_galeria=True, trae al menos 4 fotos de tipo PATENTE desde la galería si hiciera falta.
    """
    fotos = fotos or []
    fotos_galeria_ids = fotos_galeria_ids or []

    # 1) Póliza vigente
    if not poliza_vigente(poliza):
        raise ValidationError("La póliza no está vigente o está vencida.")

    # 2) Unicidad (evita dos adhesiones operativas en paralelo)
    if AdhesionGrua.objects.filter(
        poliza=poliza, estado__in=[EstadoAdhesion.ACTIVA, EstadoAdhesion.PAUSADA]
    ).exists():
        raise ValidationError("La póliza ya tiene una adhesión activa o pausada.")

    # 3) Fecha segura
    fa = _parse_fecha(fecha_activacion, timezone.localdate())

    # 4) Crear adhesión
    try:
        adh = AdhesionGrua.objects.create(
            poliza=poliza,
            plan=plan,
            estado=EstadoAdhesion.ACTIVA,
            fecha_activacion=fa,
            notas=notas or ""
        )
    except IntegrityError as e:
        raise ValidationError(f"No se pudo crear la adhesión (integridad): {e}")

    # 5) Guardar fotos NUEVAS (idempotente: get_or_create + merge de public_id si corresponde)
    creadas_local = 0
    omitidas_local = 0
    for f in fotos:
        if not isinstance(f, dict):
            continue
        url = (f.get("url") or "").strip()
        if not url:
            continue
        tipo = (f.get("tipo") or "").upper().strip() or "OTRA"
        if hasattr(TipoFotoAdhesion, "values") and tipo not in getattr(TipoFotoAdhesion, "values", []):
            tipo = TipoFotoAdhesion.OTRA
        public_id = (f.get("public_id") or "").strip()

        obj, created = AdhesionFoto.objects.get_or_create(
            adhesion=adh,
            url=url,
            defaults={"tipo": tipo, "public_id": public_id},
        )
        if created:
            creadas_local += 1
        else:
            # Si ya existía y ahora llega un public_id no vacío, lo completamos
            to_update = []
            if public_id and not obj.public_id:
                obj.public_id = public_id
                to_update.append("public_id")
            # Si el tipo viene y el existente es OTRA, permitimos elevarlo
            if tipo and obj.tipo == TipoFotoAdhesion.OTRA and tipo != TipoFotoAdhesion.OTRA:
                obj.tipo = tipo
                to_update.append("tipo")
            if to_update:
                obj.save(update_fields=to_update)
            omitidas_local += 1

    # 6) Importar desde GALERÍA por IDs (si enviaron)
    resumen_galeria_ids = {"creadas": 0, "omitidas": 0}
    if fotos_galeria_ids:
        try:
            rg = importar_fotos_adhesion_desde_galeria(
                poliza=poliza,
                adhesion=adh,
                foto_ids=fotos_galeria_ids,
                minimo_patente=0,
            )
            if isinstance(rg, dict):
                resumen_galeria_ids.update({k: rg.get(k, resumen_galeria_ids[k]) for k in resumen_galeria_ids})
        except IntegrityError:
            # Si el importador intenta crear duplicados, la constraint de DB puede disparar.
            # Los ignoramos para mantener idempotencia y continuamos.
            pass

    # 7) Auto-importar desde galería si faltan PATENTE para llegar a 4
    resumen_auto = {"creadas": 0, "omitidas": 0}
    if auto_importar_galeria:
        cant_patente = adh.fotos_adhesion.filter(tipo="PATENTE").count()
        if cant_patente < 4:
            try:
                rg = importar_fotos_adhesion_desde_galeria(
                    poliza=poliza,
                    adhesion=adh,
                    foto_ids=None,
                    minimo_patente=4
                )
                if isinstance(rg, dict):
                    resumen_auto.update({k: rg.get(k, resumen_auto[k]) for k in resumen_auto})
            except IntegrityError:
                pass

    # (Opcional) Podríamos “adjuntar” el resumen en un atributo efímero para que la capa de vista lo lea.
    adh._resumen_import = {
        "nuevas_creadas": creadas_local,
        "nuevas_omitidas": omitidas_local,
        "galeria_por_ids": resumen_galeria_ids,
        "galeria_auto": resumen_auto,
    }

    return adh


@transaction.atomic
def pausar_adhesion(adhesion: AdhesionGrua, motivo: str = "") -> AdhesionGrua:
    """
    Pone la adhesión en estado PAUSADA. No elimina datos.
    """
    if adhesion.estado == EstadoAdhesion.PAUSADA:
        return adhesion
    if adhesion.estado == EstadoAdhesion.CANCELADA:
        raise ValidationError("No se puede pausar una adhesión cancelada.")
    adhesion.estado = EstadoAdhesion.PAUSADA
    if motivo:
        adhesion.notas = (adhesion.notas or "") + f"\n[Pausa] {motivo}"
    adhesion.save(update_fields=["estado", "notas", "actualizado_en"])
    return adhesion


@transaction.atomic
def cancelar_adhesion(adhesion: AdhesionGrua, motivo: str = "") -> AdhesionGrua:
    """
    Cancela definitivamente la adhesión (estado CANCELADA) y marca fecha_baja.
    """
    if adhesion.estado == EstadoAdhesion.CANCELADA:
        return adhesion
    adhesion.estado = EstadoAdhesion.CANCELADA
    adhesion.fecha_baja = timezone.localdate()
    if motivo:
        adhesion.notas = (adhesion.notas or "") + f"\n[Baja] {motivo}"
    adhesion.save(update_fields=["estado", "fecha_baja", "notas", "actualizado_en"])
    return adhesion
