# tareas/services.py
#
# Lógica del panel "Tareas del día".
#   1) Enviar póliza al cliente   → aparece cuando poliza_enviada=False
#      (lo activa automáticamente el pago de una cuota; ver signals.py).
#   2) Completar datos de la póliza (falta número o compañía)
#   3) Completar datos del cliente  (falta fecha de nacimiento)
#   4) Subir fotos de DNI           (falta frente o dorso)
#   5) Subir fotos de la póliza      (la póliza no tiene fotos del vehículo)
#
# (2)-(5) miran solo lo RECIENTE (últimos `dias` días) para no arrastrar backlog.
# (1) NO filtra por fecha: una póliza vieja que se acaba de pagar también cuenta.

from datetime import timedelta

from django.db.models import Q, Count
from django.utils import timezone

from polizas.models import Poliza, PolizaDocumento, CuponRobo
from clientes.models import Cliente

DIAS_DEFAULT = 30


def _nombre_cli(cliente) -> str:
    if not cliente:
        return "—"
    nom = getattr(cliente, "nombre_completo", None)
    if nom:
        return nom
    return f"{getattr(cliente, 'nombre', '')} {getattr(cliente, 'apellido', '')}".strip() or "—"


def armar_tareas_dia(oficina_id=None, dias: int = DIAS_DEFAULT) -> dict:
    """Arma las 5 listas de tareas para una oficina (o todas si oficina_id es None)."""
    hoy = timezone.localdate()
    limite = hoy - timedelta(days=int(dias))

    # ── 1) Enviar póliza ────────────────────────────────────────────────
    # Sin filtro de fecha: lo dispara el pago (poliza_enviada se pone en False).
    env_base = (
        Poliza.objects.select_related("cliente")
        .exclude(estado="cancelada")
        .filter(poliza_enviada=False, creado_en__date=hoy)
    )
    if oficina_id:
        env_base = env_base.filter(oficina_id=oficina_id)

    enviar_poliza = []
    for p in env_base:
        enviar_poliza.append({
            "poliza_id": p.id,
            "cliente": _nombre_cli(p.cliente),
            "patente": (p.patente or "—"),
            "vehiculo": f"{p.marca or ''} {p.modelo or ''}".strip() or "—",
            "compania": (p.compania or ""),
        })

    # ── Base para el resto (solo lo reciente) ───────────────────────────
    # Solo lo de HOY: pólizas renovadas o dadas de alta hoy. Así las tareas son
    # diarias y no se amontonan con las de días anteriores.
    pol_base = (
        Poliza.objects.select_related("cliente")
        .exclude(estado="cancelada")
        .filter(creado_en__date=hoy)
    )
    if oficina_id:
        pol_base = pol_base.filter(oficina_id=oficina_id)

    # ── 2) Datos de la póliza ───────────────────────────────────────────
    datos_poliza = []
    for p in pol_base.filter(Q(sin_numero=True) | Q(compania__isnull=True) | Q(compania="")):
        faltan = []
        if p.sin_numero:
            faltan.append("número de póliza")
        if not (p.compania or "").strip():
            faltan.append("compañía")
        if not faltan:
            continue
        datos_poliza.append({
            "poliza_id": p.id,
            "cliente": _nombre_cli(p.cliente),
            "patente": (p.patente or "—"),
            "detalle": "falta " + " y ".join(faltan),
            "compania": (p.compania or ""),
            "numero_poliza": "" if p.sin_numero else (getattr(p, "numero_poliza", "") or ""),
        })

    # Clientes con póliza reciente
    cliente_ids = list(pol_base.values_list("cliente_id", flat=True).distinct())
    cli_base = Cliente.objects.filter(id__in=cliente_ids)
    if oficina_id:
        cli_base = cli_base.filter(oficina_id=oficina_id)

    # ── 3) Datos del cliente ────────────────────────────────────────────
    datos_cliente = []
    for c in cli_base.filter(fecha_nacimiento__isnull=True):
        datos_cliente.append({
            "cliente_id": c.id,
            "cliente": _nombre_cli(c),
            "detalle": "falta fecha de nacimiento",
        })

    # ── 4) Fotos de DNI ─────────────────────────────────────────────────
    fotos_dni = []
    for c in cli_base.filter(
        Q(archivo_dni_frente__isnull=True) | Q(archivo_dni_frente="")
        | Q(archivo_dni_dorso__isnull=True) | Q(archivo_dni_dorso="")
    ):
        falta_f = not (c.archivo_dni_frente or "").strip()
        falta_d = not (c.archivo_dni_dorso or "").strip()
        if falta_f and falta_d:
            det = "falta frente y dorso del DNI"
        elif falta_f:
            det = "falta frente del DNI"
        else:
            det = "falta dorso del DNI"
        fotos_dni.append({
            "cliente_id": c.id,
            "cliente": _nombre_cli(c),
            "detalle": det,
        })

    # ── 5) Fotos de la póliza ───────────────────────────────────────────
    fotos_poliza = []
    for p in pol_base.annotate(n_fotos=Count("fotos_vehiculo")).filter(n_fotos=0):
        fotos_poliza.append({
            "poliza_id": p.id,
            "cliente": _nombre_cli(p.cliente),
            "patente": (p.patente or "—"),
            "vehiculo": f"{p.marca or ''} {p.modelo or ''}".strip() or "—",
        })

    # ── 6) Subir póliza a sistema (póliza, cuponera, Mercosur) ──────────
    # Aparece cuando una póliza reciente NO tiene cargados sus papeles.
    # Caso típico: pólizas RENOVADAS (la renovación ya no arrastra esos papeles).
    pol_ids = list(pol_base.values_list("id", flat=True))

    docs_por_poliza = {}
    for d in PolizaDocumento.objects.filter(poliza_id__in=pol_ids).values("poliza_id", "tipo", "nombre"):
        blob = (str(d["tipo"] or "") + " " + str(d["nombre"] or "")).lower()
        docs_por_poliza.setdefault(d["poliza_id"], []).append(blob)

    con_cupones = set(
        CuponRobo.objects.filter(poliza_id__in=pol_ids)
        .values_list("poliza_id", flat=True).distinct()
    )

    def _tiene(blobs, kws):
        return any(any(kw in b for kw in kws) for b in blobs)

    subir_poliza = []
    for p in pol_base:
        blobs = docs_por_poliza.get(p.id, [])
        falta = []
        if not _tiene(blobs, ["prp", "propuesta", "frente", "poliza"]):
            falta.append("póliza")
        if not _tiene(blobs, ["merco"]):
            falta.append("Mercosur")
        if (p.id in con_cupones) and not _tiene(blobs, ["cupon"]):
            falta.append("cuponera")
        if not falta:
            continue
        subir_poliza.append({
            "poliza_id": p.id,
            "cliente": _nombre_cli(p.cliente),
            "cliente_dni": getattr(p.cliente, "dni_cuit_cuil", "") or "",
            "patente": (p.patente or "—"),
            "patente_real": (p.patente or ""),
            "vehiculo": f"{p.marca or ''} {p.modelo or ''}".strip() or "—",
            "detalle": "falta " + ", ".join(falta),
            "compania": (p.compania or ""),
        })

    total = (
        len(enviar_poliza) + len(datos_poliza) + len(datos_cliente)
        + len(fotos_dni) + len(fotos_poliza) + len(subir_poliza)
    )

    return {
        "oficina": str(oficina_id) if oficina_id else "Todas",
        "fecha": hoy.strftime("%d/%m/%Y"),
        "dias": int(dias),
        "total": total,
        "enviar_poliza": enviar_poliza,
        "datos_poliza": datos_poliza,
        "datos_cliente": datos_cliente,
        "fotos_dni": fotos_dni,
        "fotos_poliza": fotos_poliza,
        "subir_poliza": subir_poliza,
    }