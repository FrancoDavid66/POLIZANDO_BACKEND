# clientes/fusion.py
# ──────────────────────────────────────────────────────────────────────────
# Fusión (merge) de clientes duplicados. Dos modos:
#
#   1) MANUAL  → FusionarClientesView   (POST /api/clientes/fusionar/)
#      Vos elegís el principal y qué fichas se fusionan en él. Para los casos
#      dudosos (teléfono/email compartido).
#
#   2) MASIVA por DNI → FusionMasivaDNIView (POST /api/clientes/fusionar-dni/)
#      Junta automáticamente TODOS los clientes que comparten el mismo DNI.
#      Gana la ficha más antigua (menor ID). Tiene modo "simular" que NO toca
#      nada y solo te dice cuántos fusionaría.
#
# En ambos modos: las pólizas/siniestros/avisos se MUEVEN al principal (no se
# pierden), se completan los datos vacíos del principal, y se borran las copias.
# Todo dentro de una transacción (si algo falla, no se toca nada).
#
# Seguridad: solo ADMIN.
# ──────────────────────────────────────────────────────────────────────────
from django.db import transaction, IntegrityError
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from .models import Cliente


# Campos que se "rellenan" en el principal SOLO si están vacíos.
CAMPOS_COMPLETABLES = [
    "email", "direccion", "localidad", "fecha_nacimiento",
    "dni_cuit_cuil",
    "archivo_dni", "archivo_dni_frente", "archivo_dni_dorso",
    "archivo_pasaporte_frente", "archivo_pasaporte_dorso",
]

# Campos de contacto que se toman de la ficha MÁS RECIENTE (mayor ID) que los
# tenga cargados. Ej: el teléfono que queda es el último que cargó el cliente,
# no el más viejo.
CAMPOS_MAS_RECIENTE = ["telefono"]


def _es_admin(user) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    perfil = getattr(user, "perfil", None)
    return bool(perfil and getattr(perfil, "rol", "") == "ADMIN")


def _vacio(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _norm_dni(v) -> str:
    """Deja solo los dígitos del DNI/CUIT (ej: '20-12.345.678-3' -> '20123456783')."""
    return "".join(ch for ch in str(v or "") if ch.isdigit())


def _relaciones_cliente():
    """Relaciones que apuntan a Cliente (pólizas, siniestros, logs, etc.)."""
    return [r for r in Cliente._meta.related_objects if (r.one_to_many or r.one_to_one)]


def _mover_relacion(Model, fk_name, dup, principal):
    """
    Mueve todas las filas de `dup` hacia `principal`.
    Intenta primero un UPDATE masivo (rápido). Si choca con una restricción de
    unicidad (ej: el principal ya tiene un aviso con el mismo número+fecha), pasa
    a mover fila por fila y DESCARTA las que ya existen en el principal (registros
    duplicados que no aportan nada). Devuelve cuántas filas movió.
    Usa savepoints para que un choque NO rompa la transacción principal.
    """
    base = Model.objects.filter(**{fk_name: dup})
    try:
        with transaction.atomic():  # savepoint
            n = base.count()
            if n:
                base.update(**{fk_name: principal})
            return n
    except IntegrityError:
        movidas = 0
        for obj in Model.objects.filter(**{fk_name: dup}):
            try:
                with transaction.atomic():  # savepoint por fila
                    setattr(obj, fk_name, principal)
                    obj.save()
                    movidas += 1
            except IntegrityError:
                # Ya existe el equivalente en el principal → descartamos el duplicado
                obj.delete()
        return movidas


def _fusionar_grupo(principal, duplicados):
    """
    Mueve todo lo que cuelga de cada duplicado hacia `principal`, completa los
    vacíos del principal y borra los duplicados. Devuelve cuántas relaciones movió.
    Debe llamarse dentro de una transacción.
    """
    rels = _relaciones_cliente()
    movidas = 0
    for dup in duplicados:
        for r in rels:
            movidas += _mover_relacion(r.related_model, r.field.name, dup, principal)
        for campo in CAMPOS_COMPLETABLES:
            if _vacio(getattr(principal, campo, None)):
                val = getattr(dup, campo, None)
                if not _vacio(val):
                    setattr(principal, campo, val)
    # Campos de contacto (teléfono): tomar el de la ficha MÁS NUEVA que lo tenga.
    todas = sorted(list(duplicados) + [principal], key=lambda c: (c.id or 0), reverse=True)
    for campo in CAMPOS_MAS_RECIENTE:
        for ficha in todas:  # de la más nueva a la más vieja
            val = getattr(ficha, campo, None)
            if not _vacio(val):
                setattr(principal, campo, val)
                break
    principal.save()
    Cliente.objects.filter(pk__in=[d.id for d in duplicados]).delete()
    return movidas


# ══════════════════════════════════════════════════════════════════════════
# 1) FUSIÓN MANUAL (un grupo elegido por el usuario)
# ══════════════════════════════════════════════════════════════════════════
class FusionarClientesView(APIView):
    """
    POST /api/clientes/fusionar/
    Body: { "principal_id": 199, "duplicados_ids": [850, 851] }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        if not _es_admin(request.user):
            return Response({"error": "Solo un administrador puede fusionar clientes."}, status=403)

        data = request.data or {}
        try:
            principal_id = int(data.get("principal_id"))
        except (TypeError, ValueError):
            return Response({"error": "Falta 'principal_id' válido."}, status=400)

        ids = []
        for x in (data.get("duplicados_ids") or []):
            try:
                xi = int(x)
            except (TypeError, ValueError):
                continue
            if xi != principal_id:
                ids.append(xi)
        ids = list(dict.fromkeys(ids))
        if not ids:
            return Response({"error": "No hay clientes duplicados para fusionar."}, status=400)

        try:
            principal = Cliente.objects.get(pk=principal_id)
        except Cliente.DoesNotExist:
            return Response({"error": "El cliente principal no existe."}, status=404)

        duplicados = list(Cliente.objects.filter(pk__in=ids))
        if not duplicados:
            return Response({"error": "Los clientes a fusionar no existen."}, status=404)

        try:
            with transaction.atomic():
                movidas = _fusionar_grupo(principal, duplicados)
        except Exception as e:
            return Response({"error": f"No se pudo completar la fusión: {e}"}, status=400)

        return Response(
            {
                "ok": True,
                "principal_id": principal.id,
                "fusionados": [d.id for d in duplicados],
                "relaciones_movidas": movidas,
            },
            status=status.HTTP_200_OK,
        )


# ══════════════════════════════════════════════════════════════════════════
# 2) FUSIÓN MASIVA AUTOMÁTICA POR DNI
# ══════════════════════════════════════════════════════════════════════════
class FusionMasivaDNIView(APIView):
    """
    POST /api/clientes/fusionar-dni/
    Body:
        { "simular": true }   # (por defecto) NO toca nada, solo informa
        { "simular": false }  # EJECUTA la fusión de verdad
        { "oficina": 2 }      # (opcional) limita a una oficina

    Junta todos los clientes con el mismo DNI. Gana el de menor ID (más antiguo).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        if not _es_admin(request.user):
            return Response({"error": "Solo un administrador puede fusionar clientes."}, status=403)

        data = request.data or {}
        # Por seguridad, si no mandan 'simular', asumimos simulación (no toca nada).
        simular = bool(data.get("simular", True))

        qs = Cliente.objects.all()
        ofi = data.get("oficina")
        if ofi not in (None, "", "ALL"):
            try:
                qs = qs.filter(oficina_id=int(ofi))
            except (TypeError, ValueError):
                pass

        # Agrupar por DNI normalizado
        grupos = {}
        for row in qs.values("id", "dni_cuit_cuil"):
            k = _norm_dni(row["dni_cuit_cuil"])
            if not k:
                continue
            grupos.setdefault(k, []).append(row["id"])
        grupos = {k: ids for k, ids in grupos.items() if len(ids) > 1}

        total_grupos = len(grupos)
        total_involucrados = sum(len(v) for v in grupos.values())
        se_borrarian = total_involucrados - total_grupos  # uno queda por grupo

        # ── MODO SIMULACIÓN ─────────────────────────────────────────────────
        if simular:
            muestra = []
            for dni, ids in list(grupos.items())[:10]:
                muestra.append({"dni": dni, "fichas": len(ids), "ids": sorted(ids)})
            return Response(
                {
                    "simulacion": True,
                    "grupos": total_grupos,
                    "clientes_involucrados": total_involucrados,
                    "se_borrarian": se_borrarian,
                    "se_conservan": total_grupos,
                    "muestra": muestra,
                },
                status=status.HTTP_200_OK,
            )

        # ── EJECUCIÓN REAL ──────────────────────────────────────────────────
        if total_grupos == 0:
            return Response(
                {"ok": True, "grupos_fusionados": 0, "clientes_borrados": 0, "relaciones_movidas": 0},
                status=200,
            )

        grupos_ok = 0
        borrados = 0
        relaciones = 0
        try:
            with transaction.atomic():
                for dni, ids in grupos.items():
                    ids_ord = sorted(ids)  # menor id = más antiguo = principal
                    principal = Cliente.objects.get(pk=ids_ord[0])
                    duplicados = list(Cliente.objects.filter(pk__in=ids_ord[1:]))
                    if not duplicados:
                        continue
                    relaciones += _fusionar_grupo(principal, duplicados)
                    borrados += len(duplicados)
                    grupos_ok += 1
        except Exception as e:
            return Response({"error": f"No se pudo completar la fusión masiva: {e}"}, status=400)

        return Response(
            {
                "ok": True,
                "simulacion": False,
                "grupos_fusionados": grupos_ok,
                "clientes_borrados": borrados,
                "relaciones_movidas": relaciones,
            },
            status=status.HTTP_200_OK,
        )