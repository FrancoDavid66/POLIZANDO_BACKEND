# polizas/domain/exports.py

from __future__ import annotations

from typing import Iterable, Tuple, List, Dict, Any

from polizas.models import Poliza


def _get_oficina_nombre_robusto(poliza: Poliza) -> str:
    """
    Soporta:
    - Poliza.oficina como FK a modelo con .nombre
    - Poliza.oficina como string / int
    """
    try:
        oficina = getattr(poliza, "oficina", None)
        if oficina is None:
            return ""
        # FK
        if hasattr(oficina, "nombre"):
            return str(oficina.nombre or "").strip()
        return str(oficina).strip()
    except Exception:
        return ""


def _get_cliente_field(poliza: Poliza, field: str) -> str:
    try:
        c = getattr(poliza, "cliente", None)
        if not c:
            return ""
        v = getattr(c, field, "") or ""
        return str(v).strip()
    except Exception:
        return ""


def build_asegurados_rows(qs: Iterable[Poliza]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Devuelve:
      - rows: lista de dicts con claves = headers
      - headers: lista de columnas

    Se usa para export CSV/XLSX desde el mixin PolizaExportsMixin.
    """
    headers = [
        "poliza_id",
        "numero_poliza",
        "compania",
        "oficina",
        "estado",
        "fase",
        "patente",
        "marca",
        "modelo",
        "fecha_emision",
        "fecha_vencimiento",
        "cliente_id",
        "cliente_nombre",
        "cliente_apellido",
        "cliente_dni",
        "cliente_telefono",
        "cliente_email",
    ]

    rows: List[Dict[str, Any]] = []

    for p in qs:
        row = {
            "poliza_id": getattr(p, "id", None),
            "numero_poliza": getattr(p, "numero_poliza", "") or "",
            "compania": getattr(p, "compania", "") or "",
            "oficina": _get_oficina_nombre_robusto(p),
            "estado": getattr(p, "estado", "") or "",
            "fase": getattr(p, "fase", "") or "",
            "patente": getattr(p, "patente", "") or "",
            "marca": getattr(p, "marca", "") or "",
            "modelo": getattr(p, "modelo", "") or "",
            "fecha_emision": getattr(p, "fecha_emision", None),
            "fecha_vencimiento": getattr(p, "fecha_vencimiento", None),
            "cliente_id": getattr(p, "cliente_id", None),
            "cliente_nombre": _get_cliente_field(p, "nombre"),
            "cliente_apellido": _get_cliente_field(p, "apellido"),
            "cliente_dni": _get_cliente_field(p, "dni_cuit_cuil"),
            "cliente_telefono": _get_cliente_field(p, "telefono"),
            "cliente_email": _get_cliente_field(p, "email"),
        }
        rows.append(row)

    return rows, headers
