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

from usuarios.models import Oficina
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


def _oficina_talita():
    """
    Devuelve la Oficina real de la base que matchea "Talita" (según la misma
    regla de precios_nre.es_talita), o None si no existe ninguna.
    🔒 Antes esto era un string fijo ("EL TALITA"): siempre aparecía el bloque
    aunque esa oficina no existiera. Ahora sale de la DB, no hardcodeado.
    """
    try:
        return next((o for o in Oficina.objects.filter(activa=True) if es_talita(o)), None)
    except Exception:
        return None


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
            # El admin maneja todas: mostramos el precio general y, SOLO SI
            # existe de verdad una oficina tipo Talita en la base, ese bloque
            # aparte (es la única que cambia, y solo en auto).
            bloques.append(_bloque("Todas las oficinas", None, hoy))
            oficina_talita = _oficina_talita()
            if oficina_talita:
                nombre_talita = oficina_talita.nombre or "Talita"
                bloques.append(_bloque(f"{nombre_talita} (auto más barato)", oficina_talita, hoy))
        else:
            nombre = getattr(oficina, "nombre", None) or "Tu oficina"
            bloques.append(_bloque(nombre, oficina, hoy))

        return Response({
            "fecha": hoy.strftime("%Y-%m-%d"),
            "es_admin": is_admin,
            "bloques": bloques,
        })