# polizas/domain/bool.py

def to_bool(v):
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"1", "true", "t", "yes", "y", "on", "si", "sí"}
