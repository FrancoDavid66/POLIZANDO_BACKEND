# ranking/services.py
#
# Funciones para sumar puntos y armar el ranking.
# Cualquier módulo del sistema llama a `otorgar_puntos(...)` para premiar/penalizar.

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Sum, Count
from django.utils import timezone

from .models import MovimientoPuntos

User = get_user_model()


def otorgar_puntos(*, usuario, puntos, categoria="otro", oficina=None,
                   detalle="", fecha=None, ref=""):
    """
    Registra puntos para un empleado.
      - usuario: instancia User o su id (obligatorio)
      - puntos: int (positivo suma, negativo resta)
      - ref: si se pasa, no duplica (actualiza el existente con esa ref+categoría)
    Devuelve el MovimientoPuntos o None si faltan datos.
    """
    if not usuario or not puntos:
        return None
    fecha = fecha or timezone.localdate()
    usuario_id = getattr(usuario, "id", usuario)
    oficina_id = getattr(oficina, "id", oficina)

    base = {
        "usuario_id": usuario_id,
        "oficina_id": oficina_id,
        "fecha": fecha,
        "puntos": int(puntos),
        "categoria": categoria,
        "detalle": detalle[:200],
    }

    if ref:
        obj, _ = MovimientoPuntos.objects.update_or_create(
            categoria=categoria, ref=ref, defaults=base
        )
        return obj
    return MovimientoPuntos.objects.create(ref="", **base)


def _desde_por_rango(rango, hoy):
    if rango == "hoy":
        return hoy
    if rango == "semana":
        return hoy - timedelta(days=7)
    return hoy - timedelta(days=30)  # mes (default)


def ranking_puntos(rango="mes", categoria=None, oficina_id=None):
    """
    Devuelve la lista ordenada de empleados por puntos en el período.
    """
    hoy = timezone.localdate()
    rango = (rango or "mes").lower()
    if rango not in ("hoy", "semana", "mes"):
        rango = "mes"
    desde = _desde_por_rango(rango, hoy)

    qs = MovimientoPuntos.objects.filter(fecha__gte=desde)
    if categoria:
        qs = qs.filter(categoria=categoria)
    if oficina_id:
        qs = qs.filter(oficina_id=oficina_id)

    agg = (qs.values("usuario_id")
             .annotate(puntos=Sum("puntos"), acciones=Count("id"))
             .order_by("-puntos"))

    ids = [a["usuario_id"] for a in agg]
    nombres = {
        u.id: (u.get_full_name() or u.username)
        for u in User.objects.filter(id__in=ids)
    }
    ranking = [
        {
            "usuario": nombres.get(a["usuario_id"], "—"),
            "usuario_id": a["usuario_id"],
            "puntos": a["puntos"] or 0,
            "acciones": a["acciones"],
        }
        for a in agg
    ]
    return {"rango": rango, "ranking": ranking}