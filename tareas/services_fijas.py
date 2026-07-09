# tareas/services_fijas.py
#
# Arma el panel de "tareas fijas del día":
#   - qué tareas corresponden hoy (según frecuencia)
#   - si cada una está cumplida (con foto) o pendiente
#   - respeta los feriados (ese día no se esperan tareas)
#
# Sirve para el empleado (su oficina) y para el admin (todas las oficinas).

from django.utils import timezone

from usuarios.models import Oficina
from .models_fijas import TareaFija, CumplimientoTareaFija, Feriado

try:
    from solicitudes.models import Empleado
except Exception:
    Empleado = None


def _nombre_user(u):
    if not u:
        return ""
    full = (getattr(u, "get_full_name", lambda: "")() or "").strip()
    return full or getattr(u, "username", "") or ""


def es_feriado(fecha):
    """Devuelve el Feriado si esa fecha lo es, o None."""
    return Feriado.objects.filter(fecha=fecha).first()


def armar_tareas_fijas_dia(oficina_id=None, fecha=None) -> dict:
    """
    Arma las tareas fijas del día.
      - oficina_id=None  → todas las oficinas (vista admin)
      - oficina_id=<id>  → solo esa oficina (vista empleado)
    """
    fecha = fecha or timezone.localdate()

    feriado = es_feriado(fecha)
    if feriado:
        return {
            "fecha": fecha.strftime("%d/%m/%Y"),
            "feriado": True,
            "feriado_nombre": feriado.nombre,
            "oficinas": [],
            "total": 0,
            "cumplidas": 0,
        }

    # Oficinas a evaluar
    if oficina_id:
        oficinas = list(Oficina.objects.filter(id=oficina_id, activa=True))
    else:
        oficinas = list(Oficina.objects.filter(activa=True))

    # Tareas activas que aplican hoy (todas; después filtramos por oficina)
    tareas_hoy = [t for t in TareaFija.objects.select_related("oficina", "responsable").filter(activa=True)
                  if t.aplica_en(fecha)]

    # Cumplimientos de hoy (para no consultar de a uno)
    cumplidos = {}
    cumpl_ids = []
    for c in CumplimientoTareaFija.objects.filter(fecha=fecha).select_related("usuario").prefetch_related("fotos"):
        cumplidos[(c.tarea_id, c.oficina_id)] = c
        cumpl_ids.append(c.id)

    data_oficinas = []
    total_global = 0
    cumplidas_global = 0

    for ofi in oficinas:
        # Tareas que le tocan a esta oficina: las suyas + las globales (oficina vacía)
        tareas_ofi = [t for t in tareas_hoy if (t.oficina_id == ofi.id or t.oficina_id is None)]
        items = []
        cumplidas = 0
        for t in sorted(tareas_ofi, key=lambda x: (x.orden, x.nombre)):
            c = cumplidos.get((t.id, ofi.id))
            fotos_min = getattr(t, "fotos_min", 1) or 1
            fotos_max = getattr(t, "fotos_max", 1) or 1

            # Galería de fotos subidas (de la tabla FotoCumplimiento; si no hay,
            # usamos la foto_url vieja del cumplimiento como única foto).
            fotos = []
            if c is not None:
                fotos = [{"url": f.foto_url, "id": f.id} for f in c.fotos.all()]
                if not fotos and c.foto_url:
                    fotos = [{"url": c.foto_url, "id": 0}]

            n_fotos = len(fotos)
            cumplida = n_fotos >= fotos_min
            if cumplida:
                cumplidas += 1

            items.append({
                "tarea_id": t.id,
                "nombre": t.nombre,
                "responsable": _nombre_user(t.responsable),
                "hora_esperada": t.hora_esperada.strftime("%H:%M") if t.hora_esperada else "",
                "requiere_foto": t.requiere_foto,
                "instruccion_foto": t.instruccion_foto,
                "frecuencia": t.frecuencia,
                "fotos_min": fotos_min,
                "fotos_max": fotos_max,
                "fotos_subidas": n_fotos,
                "fotos": fotos,
                "puede_sumar": n_fotos < fotos_max,
                "cumplida": cumplida,
                "foto_url": (fotos[0]["url"] if fotos else ""),
                "cumplido_en": (c.cumplido_en.isoformat() if c else None),
                "cumplido_por": (_nombre_user(c.usuario) if c else ""),
                "responsable_real": (getattr(c, "responsable_nombre", "") if c else ""),
                "cargado_por_admin": (bool(getattr(c, "cargado_por_admin", False)) if c else False),
            })

        # 🆕 Empleados (responsables) de esta oficina, para los chips del front.
        empleados_ofi = []
        if Empleado is not None:
            try:
                qs_emp = Empleado.objects.filter(activo=True, oficina_id=ofi.id).order_by("nombre")
                empleados_ofi = [{"id": e.id, "nombre": e.nombre} for e in qs_emp]
            except Exception:
                empleados_ofi = []

        total_global += len(items)
        cumplidas_global += cumplidas
        data_oficinas.append({
            "oficina_id": ofi.id,
            "oficina_nombre": ofi.nombre,
            "total": len(items),
            "cumplidas": cumplidas,
            "tareas": items,
            "empleados": empleados_ofi,
        })

    return {
        "fecha": fecha.strftime("%d/%m/%Y"),
        "feriado": False,
        "feriado_nombre": "",
        "oficinas": data_oficinas,
        "total": total_global,
        "cumplidas": cumplidas_global,
    }