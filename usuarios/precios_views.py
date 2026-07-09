# usuarios/precios_views.py
#
# Endpoint chico para mostrar la LISTA DE PRECIOS NRE en el front (modal del header).
# Devuelve los precios de HOY según la oficina del usuario logueado, así cada
# persona ve lo que tiene que cobrar en su sucursal sin pensar.
#
# La única fuente de verdad sigue siendo polizas/precios_nre.py: acá solo se lee.

from datetime import date

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from polizas.precios_nre import (
    precio_cuotas_alta_nueva,
    precio_cuotas_renovacion,
    es_talita,
)

# Tipos que mostramos y cómo se ven en pantalla.
TIPOS = ["Auto", "Moto", "Camioneta", "Camion", "Trailer"]
TIPO_LABEL = {"Camion": "Camión"}


def _bloque(nombre, oficina, hoy):
    """Arma un bloque de precios (alta + renovación) para una oficina."""
    filas = []
    for t in TIPOS:
        n1, nr = precio_cuotas_alta_nueva(t, hoy, oficina)
        r1, rr = precio_cuotas_renovacion(t, hoy, oficina)
        if nr is None and rr is None:
            continue
        filas.append({
            "tipo": TIPO_LABEL.get(t, t),
            "nuevo_primera": n1,
            "nuevo_resto": nr,
            "reno_primera": r1,
            "reno_resto": rr,
        })
    return {
        "oficina": nombre,
        "es_talita": es_talita(oficina),
        "precios": filas,
    }


class PreciosNREView(APIView):
    """GET /api/usuarios/precios-nre/ → precios NRE de hoy según la oficina del usuario."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        hoy = date.today()
        user = request.user
        perfil = getattr(user, "perfil", None)
        is_admin = bool(user.is_superuser) or getattr(perfil, "rol", "") == "ADMIN"
        oficina = getattr(perfil, "oficina", None)

        bloques = []
        if is_admin:
            # El admin maneja todas: mostramos el precio general + El Talita aparte
            # (que es la única que cambia, y solo en auto).
            bloques.append(_bloque("Todas las oficinas", None, hoy))
            bloques.append(_bloque("El Talita (auto más barato)", "EL TALITA", hoy))
        else:
            nombre = getattr(oficina, "nombre", None) or "Tu oficina"
            bloques.append(_bloque(nombre, oficina, hoy))

        return Response({
            "fecha": hoy.strftime("%Y-%m-%d"),
            "es_admin": is_admin,
            "bloques": bloques,
        })