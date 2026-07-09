# pagos/views_duplicados.py
# ============================================================================
# 🕵️  PAGOS DUPLICADOS — Detección de cobros repetidos
# ============================================================================
#
# Endpoint NUEVO, no toca nada existente.
#
# Detecta:
#   1) MISMA_CUOTA   → 2+ pagos para la misma póliza + cuota_nro (la más grave)
#   2) CASI_IDENTICO → misma póliza + mismo monto registrados con < 5 min de diferencia
#
# ----------------------------------------------------------------------------
# CÓMO INTEGRARLO — en pagos/urls.py, ANTES del router:
#
#     from .views_duplicados import PagosDuplicadosAPIView
#     path("auditoria/duplicados/", PagosDuplicadosAPIView.as_view(), name="auditoria-duplicados"),
#
# URL final:  GET /api/pagos/auditoria/duplicados/
# ============================================================================

from collections import defaultdict

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from .models import Pago


# Ventana (en segundos) para considerar dos pagos "casi idénticos" por cercanía de tiempo
VENTANA_SEGUNDOS = 5 * 60  # 5 minutos


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _oficina_nombre(ofi):
    if not ofi:
        return ""
    if hasattr(ofi, "nombre"):
        return str(ofi.nombre)
    return str(ofi)


def _oficina_id(ofi):
    if not ofi:
        return None
    return getattr(ofi, "id", None)


class PagosDuplicadosAPIView(APIView):
    """
    GET /api/pagos/auditoria/duplicados/?oficina=<id>

    Devuelve pagos sospechosos de estar duplicados, en 2 grupos.
    Admin ve todas las oficinas; no-admin solo la suya.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        perfil = getattr(user, "perfil", None)
        rol = getattr(perfil, "rol", None) if perfil else None
        es_admin = bool(getattr(user, "is_superuser", False) or rol == "ADMIN")

        qs = Pago.objects.select_related("poliza", "poliza__cliente", "poliza__oficina")

        # Escudo de oficina
        oficina_param = (request.query_params.get("oficina") or "").strip()
        if not es_admin:
            ofi_propia = getattr(perfil, "oficina_id", None) if perfil else None
            if ofi_propia:
                qs = qs.filter(poliza__oficina_id=ofi_propia)
        elif oficina_param and oficina_param.upper() != "ALL":
            qs = qs.filter(poliza__oficina_id=oficina_param)

        pagos = list(qs.order_by("registrado_en"))

        def base_dict(p):
            pol = getattr(p, "poliza", None)
            cli = getattr(pol, "cliente", None) if pol else None
            return {
                "pago_id": p.id,
                "poliza_id": p.poliza_id,
                "numero_poliza": getattr(pol, "numero_poliza", "") or "" if pol else "",
                "patente": getattr(pol, "patente", "") or "" if pol else "",
                "cuota_nro": p.cuota_nro,
                "monto": _to_float(p.monto),
                "fecha": p.fecha.isoformat() if p.fecha else None,
                "registrado_en": p.registrado_en.isoformat() if p.registrado_en else None,
                "metodo": p.metodo or "",
                "cliente": (
                    f"{getattr(cli, 'apellido', '') or ''} {getattr(cli, 'nombre', '') or ''}".strip()
                    if cli else ""
                ),
                "oficina_id": _oficina_id(getattr(pol, "oficina", None)) if pol else None,
                "oficina_nombre": _oficina_nombre(getattr(pol, "oficina", None)) if pol else "",
            }

        # ── 1) Misma cuota cobrada 2+ veces (poliza + cuota_nro) ──
        por_cuota = defaultdict(list)
        for p in pagos:
            if p.poliza_id is None or p.cuota_nro is None:
                continue
            por_cuota[(p.poliza_id, p.cuota_nro)].append(p)

        misma_cuota = []
        for (pol_id, cuota_nro), lista in por_cuota.items():
            if len(lista) >= 2:
                grupo = [base_dict(p) for p in lista]
                total = sum((d["monto"] or 0) for d in grupo)
                misma_cuota.append({
                    "poliza_id": pol_id,
                    "cuota_nro": cuota_nro,
                    "veces": len(lista),
                    "monto_total": round(total, 2),
                    "patente": grupo[0]["patente"],
                    "cliente": grupo[0]["cliente"],
                    "oficina_nombre": grupo[0]["oficina_nombre"],
                    "pagos": grupo,
                })

        misma_cuota.sort(key=lambda g: g["veces"], reverse=True)

        # ── 2) Casi idénticos: misma póliza + mismo monto, < ventana de tiempo ──
        casi_identico = []
        por_pol_monto = defaultdict(list)
        for p in pagos:
            monto = _to_float(p.monto)
            if p.poliza_id is None or monto is None or p.registrado_en is None:
                continue
            por_pol_monto[(p.poliza_id, round(monto, 2))].append(p)

        for (pol_id, monto), lista in por_pol_monto.items():
            if len(lista) < 2:
                continue
            lista.sort(key=lambda x: x.registrado_en)
            for i in range(1, len(lista)):
                anterior = lista[i - 1]
                actual = lista[i]
                # Si son la misma cuota ya lo agarró el grupo 1, no repetimos
                if anterior.cuota_nro == actual.cuota_nro:
                    continue
                delta = (actual.registrado_en - anterior.registrado_en).total_seconds()
                if 0 <= delta <= VENTANA_SEGUNDOS:
                    casi_identico.append({
                        "segundos_entre": int(delta),
                        "monto": monto,
                        "patente": base_dict(actual)["patente"],
                        "cliente": base_dict(actual)["cliente"],
                        "oficina_nombre": base_dict(actual)["oficina_nombre"],
                        "pagos": [base_dict(anterior), base_dict(actual)],
                    })

        casi_identico.sort(key=lambda g: g["segundos_entre"])

        return Response(
            {
                "ventana_segundos": VENTANA_SEGUNDOS,
                "resumen": {
                    "misma_cuota": len(misma_cuota),
                    "casi_identico": len(casi_identico),
                    "total": len(misma_cuota) + len(casi_identico),
                },
                "misma_cuota": misma_cuota,
                "casi_identico": casi_identico,
            },
            status=status.HTTP_200_OK,
        )