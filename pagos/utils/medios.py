# pagos/utils/medios.py

import os
import re
from dataclasses import dataclass
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from pagos.models import MedioCobro


@dataclass
class MedioCobroLite:
    """Fallback cuando no hay registros en BD."""
    proveedor: str
    tipo: str
    valor: str
    titular_nombre: str

    @property
    def resumen_para_mensaje(self) -> str:
        base = ""
        t = self.tipo
        if t == "alias":
            base = f"alias: *{self.valor}*"
        elif t == "cbu":
            base = f"CBU: *{self.valor}*"
        elif t == "cvu":
            base = f"CVU: *{self.valor}*"
        else:
            # link u otro
            base = f"link de pago: {self.valor}"
        prov = self.proveedor or "Config"
        titular = self.titular_nombre or "Estudio Thames"
        return f"{base} (a nombre de {titular} — {prov})"


def _fallback_from_settings() -> MedioCobroLite:
    """
    Fallback si no hay medios activos en BD.
    - ALIAS_CBU_LIST: CSV de valores (asumimos tipo 'alias', proveedor 'Config')
    - ALIAS_CBU: string único
    - COBRO_TITULAR_NOMBRE: nombre del titular (opcional)
    """
    titular = getattr(settings, "COBRO_TITULAR_NOMBRE", os.getenv("COBRO_TITULAR_NOMBRE", "Estudio Thames"))
    lista_csv = getattr(settings, "ALIAS_CBU_LIST", os.getenv("ALIAS_CBU_LIST", "")).strip()
    if lista_csv:
        items = [x.strip() for x in lista_csv.split(",") if x.strip()]
        if items:
            idx = timezone.localdate().toordinal() % len(items)
            return MedioCobroLite(proveedor="Config", tipo="alias", valor=items[idx], titular_nombre=titular)

    valor = getattr(settings, "ALIAS_CBU", os.getenv("ALIAS_CBU", "starkeseguros.mp"))
    return MedioCobroLite(proveedor="Config", tipo="alias", valor=valor, titular_nombre=titular)


def _from_db_round_robin() -> Optional[MedioCobro]:
    """
    Devuelve el medio activo menos recientemente usado y actualiza su último uso atomícamente.
    Si no hay en BD, retorna None.
    """
    with transaction.atomic():
        medio = (
            MedioCobro.objects
            .select_for_update(skip_locked=True)
            .filter(activo=True)
            .order_by('ultimo_uso', 'id')
            .first()
        )
        if not medio:
            return None
        # marca uso
        medio.ultimo_uso = timezone.now()
        medio.usos_totales = (medio.usos_totales or 0) + 1
        medio.save(update_fields=['ultimo_uso', 'usos_totales'])
        return medio


def obtener_medio_cobro(force_valor: Optional[str] = None):
    """
    Devuelve el medio de cobro a usar:
      1) Si force_valor viene, retorna un MedioCobroLite con tipo inferido.
      2) Si hay en BD, retorna MedioCobro (rotado por último uso).
      3) Fallback a settings (ALIAS_CBU_LIST o ALIAS_CBU) como MedioCobroLite.

    Para mantener una interfaz común, tanto MedioCobro como MedioCobroLite
    exponen la propiedad `resumen_para_mensaje`.
    """
    if force_valor:
        valor = force_valor.strip()

        # Inferencia simple del tipo por patrón
        lower = valor.lower()
        if lower.startswith("http://") or lower.startswith("https://"):
            tipo = "link"
            proveedor = "Link"
        elif re.fullmatch(r"\d{22}", valor):  # 22 dígitos típicos CBU
            tipo = "cbu"
            proveedor = "Banco"
        elif re.fullmatch(r"\d{13}", valor):  # longitudes CVU pueden variar, heurística
            tipo = "cvu"
            proveedor = "Billetera"
        else:
            tipo = "alias"
            proveedor = "Billetera"

        titular = getattr(settings, "COBRO_TITULAR_NOMBRE", os.getenv("COBRO_TITULAR_NOMBRE", "Estudio Thames"))
        return MedioCobroLite(proveedor=proveedor, tipo=tipo, valor=valor, titular_nombre=titular)

    medio_db = _from_db_round_robin()
    if medio_db:
        # Añadimos la misma API que Lite
        if not hasattr(medio_db, "resumen_para_mensaje"):
            def _resumen(m=medio_db):
                base = ""
                t = m.tipo
                if t == "alias":
                    base = f"alias: *{m.valor}*"
                elif t == "cbu":
                    base = f"CBU: *{m.valor}*"
                elif t == "cvu":
                    base = f"CVU: *{m.valor}*"
                else:
                    base = f"link de pago: {m.valor}"
                return f"{base} (a nombre de {m.titular_nombre} — {m.get_proveedor_display()})"
            setattr(medio_db, "resumen_para_mensaje", property(lambda self: _resumen()))
        return medio_db

    return _fallback_from_settings()
