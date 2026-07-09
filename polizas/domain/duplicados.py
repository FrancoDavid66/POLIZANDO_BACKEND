# polizas/domain/duplicados.py

from django.db.models import Value
from django.db.models.functions import Coalesce, Upper, Trim, Replace


def dup_parse_pagination(request):
    """
    Parse robusto de page/page_size para endpoints de duplicados.
    """
    try:
        page = int((request.query_params.get("page") or "1").strip() or 1)
    except Exception:
        page = 1

    try:
        page_size = int((request.query_params.get("page_size") or "25").strip() or 25)
    except Exception:
        page_size = 25

    page = max(1, page)
    page_size = max(1, min(200, page_size))
    return page, page_size


def dup_patente_norm_expr():
    """
    Normaliza patente: trim/upper, quita espacios y guiones.
    """
    return Replace(
        Replace(Upper(Trim(Coalesce("patente", Value("")))), Value(" "), Value("")),
        Value("-"),
        Value(""),
    )


def dup_poliza_rows(qs, per_group_limit: int):
    """
    Devuelve rows livianas para mostrar dentro de un grupo duplicado.
    """
    limit = max(1, min(200, int(per_group_limit or 25)))
    rows = (
        qs.select_related("cliente")
        .order_by("-id")
        .values(
            "id",
            "numero_poliza",
            "compania",
            "patente",
            "estado",
            "fecha_emision",
            "fecha_vencimiento",
            "cliente_id",
            "cliente__nombre",
            "cliente__apellido",
            "cliente__dni_cuit_cuil",
            "oficina",
        )[:limit]
    )

    out = []
    for r in rows:
        nombre = " ".join(
            [
                (r.get("cliente__apellido") or "").strip(),
                (r.get("cliente__nombre") or "").strip(),
            ]
        ).strip()

        out.append(
            {
                "id": r.get("id"),
                "numero_poliza": r.get("numero_poliza") or "",
                "compania": r.get("compania") or "",
                "patente": r.get("patente") or "",
                "estado": r.get("estado") or "",
                "fecha_emision": r.get("fecha_emision"),
                "fecha_vencimiento": r.get("fecha_vencimiento"),
                "oficina": r.get("oficina"),
                "cliente": {
                    "id": r.get("cliente_id"),
                    "nombre": nombre or "—",
                    "dni_cuit_cuil": r.get("cliente__dni_cuit_cuil") or "",
                },
            }
        )
    return out
