# polizas/domain/oficinas.py

from django.db.models import Q


def split_csv(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return []
    if "," in raw:
        return [v.strip() for v in raw.split(",") if v.strip()]
    return [raw]


def apply_oficina_filter(qs, model_cls, oficina_raw: str, field_name: str = "oficina"):
    """
    Filtro robusto + soporta "1,2,3" / "Axion,39"
    Funciona si model.<field_name> es FK o campo plano.

    - qs: queryset del modelo (ej: Poliza.objects.all())
    - model_cls: clase del modelo (ej: Poliza)
    - oficina_raw: string recibido en query param
    - field_name: nombre del campo (default: "oficina")
    """
    vals = split_csv(oficina_raw)
    if not vals:
        return qs

    try:
        f = model_cls._meta.get_field(field_name)
        is_rel = getattr(f, "is_relation", False)

        if is_rel:
            id_vals = [int(v) for v in vals if str(v).isdigit()]
            name_vals = [v for v in vals if not str(v).isdigit()]

            q = Q()
            if id_vals:
                q |= Q(**{f"{field_name}_id__in": id_vals})

            if name_vals:
                rel = getattr(f, "remote_field", None)
                rel_model = getattr(rel, "model", None)
                if rel_model is not None and hasattr(rel_model, "nombre"):
                    q |= Q(**{f"{field_name}__nombre__in": name_vals}) | Q(
                        **{f"{field_name}__nombre__iexact": name_vals[0]}
                    )
                else:
                    q |= Q(**{f"{field_name}__pk__in": name_vals})

            return qs.filter(q) if q else qs

        # campo plano (int o str)
        if all(str(v).isdigit() for v in vals):
            return qs.filter(**{f"{field_name}__in": [int(v) for v in vals]})
        return qs.filter(**{f"{field_name}__in": vals})

    except Exception:
        # fallback final
        if all(str(v).isdigit() for v in vals):
            return qs.filter(**{f"{field_name}__in": [int(v) for v in vals]})
        return qs.filter(**{f"{field_name}__in": vals})
