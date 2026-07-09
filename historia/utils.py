from django.db import transaction
from historia.models import PolizaEvento

def _actor_name(actor):
    if not actor:
        return "sistema"
    fn = getattr(actor, "first_name", "") or ""
    ln = getattr(actor, "last_name", "") or ""
    nm = (fn + " " + ln).strip() or getattr(actor, "username", "")
    return nm or "usuario"

def create_event(
    *,
    poliza,
    tipo,
    mensaje,
    data=None,
    categoria=None,
    severidad="INFO",
    actor=None,
    subject=None,
    source="USER",
    idempotency_key=""
):
    """Crea el evento al commit de la transacción para evitar fantasmas."""
    def _do():
        ev = PolizaEvento(
            poliza=poliza,
            tipo=tipo,
            mensaje=mensaje,
            data=data or {},
            categoria=categoria or PolizaEvento.Categoria.POLIZA,
            severidad=severidad,
            actor=actor,
            actor_name=_actor_name(actor),
            source=source,
            idempotency_key=idempotency_key or "",
        )
        if subject is not None:
            ev.subject_type = subject.__class__.__name__
            ev.subject_id = getattr(subject, "pk", None)
        ev.save()
    transaction.on_commit(_do)
