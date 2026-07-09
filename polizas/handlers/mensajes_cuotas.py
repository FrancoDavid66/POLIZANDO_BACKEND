# polizas/handlers/mensajes_cuotas.py
from datetime import date

from django.utils import timezone
from rest_framework.response import Response
from rest_framework import status

from pagos.models import Cuota
from polizas.models import Poliza
from polizas.utils.viewtools import hist_log as _hist_log, apply_poliza_filters
from polizas.utils.mensajeria import enviar_whatsapp, construir_mensaje_estado_cuotas

try:
    from polizas.utils.ultramsg import _normalizar_numero as _wa_normalize
except Exception:
    _wa_normalize = None


def _estado_cuotas_label(impagas, hoy: date):
    """
    Dado un iterable de cuotas impagas ORDENADAS por fecha_vencimiento ASC,
    devuelve un label basado en la PRÓXIMA cuota a vencer (la primera del listado).

    🎯 REGLA UNIFICADA con services_cuotas.py:
       En una póliza las cuotas se pagan en orden (no podés pagar la 3 antes
       que la 2), así que "próxima cuota impaga" = "cuota impaga más antigua".
       Es la cuota que el cliente tiene que pagar AHORA.

    Labels posibles:
    - al_dia      : sin impagas, o próxima vence en +7d o más
    - por_vencer  : próxima vence en 1-7 días
    - vence_hoy   : próxima vence HOY
    - vencida_7   : próxima venció hace 1-7 días
    - vencida_30  : próxima venció hace 8-30 días
    - vencidas    : próxima venció hace más de 30 días
    """
    impagas = list(impagas)
    if not impagas:
        return "al_dia", None, 0

    proxima = impagas[0]  # la próxima cuota impaga a vencer
    vto = getattr(proxima, "fecha_vencimiento", None)
    if not vto:
        return "vencidas", None, len(impagas)

    if vto == hoy:
        return "vence_hoy", vto, len(impagas)
    if vto < hoy:
        diff = (hoy - vto).days
        if diff <= 7:
            return "vencida_7", vto, len(impagas)
        if diff <= 30:
            return "vencida_30", vto, len(impagas)
        return "vencidas", vto, len(impagas)
    # vto > hoy
    if (vto - hoy).days <= 7:
        return "por_vencer", vto, len(impagas)
    return "al_dia", vto, len(impagas)


def handle_enviar_mensajes_cuotas(request):
    """
    POST /api/polizas/enviar-mensajes-cuotas/
    Body:
      {
        "filtros": { ... },
        "incluir_diagnostico": true,
        "solo_reporte": false
      }
    """
    body = request.data or {}
    filtros = body.get("filtros") or {}
    incluir_diag = bool(body.get("incluir_diagnostico"))
    solo_reporte = bool(body.get("solo_reporte") or body.get("preview"))

    qs = apply_poliza_filters(Poliza.objects.all().order_by("id"), filtros)

    hoy = timezone.localdate()
    total_sel = qs.count()
    enviados = fallidos = sin_tel = invalidos = simulados = procesadas = 0
    detalle = []
    diagnostico = []
    buckets = {
        "al_dia": 0,
        "por_vencer": 0,
        "vence_hoy": 0,
        "vencida_7": 0,
        "vencida_30": 0,
        "vencidas": 0,
    }

    for p in qs.iterator():
        cli = getattr(p, "cliente", None)
        tel_raw = (getattr(cli, "telefono", "") or "").strip()

        # cuotas impagas ordenadas
        impagas_qs = Cuota.objects.filter(
            poliza=p, pagado=False
        ).order_by("fecha_vencimiento", "cuota_nro", "id")
        impagas = list(impagas_qs)
        estado_label, primera_vto, cant_impagas = _estado_cuotas_label(impagas, hoy)
        buckets[estado_label] = buckets.get(estado_label, 0) + 1

        # monto total
        try:
            monto_total = sum([(c.monto or 0) for c in impagas])
        except Exception:
            monto_total = 0

        # número normalizado (si podemos calcularlo sin enviar)
        telefono_e164 = None
        if _wa_normalize and tel_raw:
            try:
                telefono_e164 = _wa_normalize(tel_raw)
            except Exception:
                telefono_e164 = None

        msg = construir_mensaje_estado_cuotas(p)

        if not tel_raw:
            sin_tel += 1
            fallidos += 1
            info = {"error": "sin_telefono"}
            ok = False
        elif solo_reporte:
            ok = None  # ni éxito ni error: no se envió
            info = {"skipped": "solo_reporte"}
            procesadas += 1
        else:
            ok, info = enviar_whatsapp(tel_raw, msg)
            procesadas += 1
            if isinstance(info, dict) and info.get("simulate"):
                simulados += 1
            if not ok and isinstance(info, dict) and info.get("error") == "invalid_number":
                invalidos += 1

        # logs de historia
        telefono_log = (
            (info.get("to") if isinstance(info, dict) else None)
            or telefono_e164
            or tel_raw
        )

        if ok is True:
            enviados += 1
            _hist_log(
                poliza=p,
                tipo="MENSAJE_ENVIO_CUOTAS",
                mensaje="WhatsApp enviado",
                severidad="ACTION",
                data={"telefono": telefono_log, "info": info},
                request=request,
                subject=p,
                categoria="POLIZA",
            )
        elif ok is False:
            fallidos += 1
            _hist_log(
                poliza=p,
                tipo="MENSAJE_ENVIO_CUOTAS_ERROR",
                mensaje="Error de WhatsApp",
                severidad="ERROR",
                data={"telefono": telefono_log, "error": info},
                request=request,
                subject=p,
                categoria="POLIZA",
            )

        detalle.append(
            {
                "poliza_id": p.id,
                "cliente_id": getattr(cli, "id", None),
                "telefono": telefono_log or None,
                "ok": (None if ok is None else bool(ok)),
                "info": info,
            }
        )

        if incluir_diag:
            diagnostico.append(
                {
                    "poliza_id": p.id,
                    "cliente": {
                        "id": getattr(cli, "id", None),
                        "nombre": getattr(cli, "nombre", ""),
                        "apellido": getattr(cli, "apellido", ""),
                    },
                    "telefono_raw": tel_raw or None,
                    "telefono_e164": telefono_log if telefono_log != tel_raw else None,
                    "estado_cuotas": estado_label,
                    "impagas": cant_impagas,
                    "monto_total": float(monto_total or 0),
                    "primera_vto": (
                        primera_vto.isoformat() if primera_vto else None
                    ),
                    "mensaje_preview": (
                        msg[:240] + ("…" if len(msg) > 240 else "")
                    ),
                }
            )

    # Truncados para no devolver payload gigante
    if len(detalle) > 100:
        detalle = detalle[:100] + [
            {"truncated": True, "total_items": len(detalle)}
        ]
    if len(diagnostico) > 100:
        diagnostico = diagnostico[:100] + [
            {"truncated": True, "total_items": len(diagnostico)}
        ]

    return Response(
        {
            "filtros": filtros,
            "seleccionadas": total_sel,
            "procesadas": procesadas,
            "enviados": enviados,
            "fallidos": fallidos,
            "sin_telefono": sin_tel,
            "invalidos": invalidos,
            "simulados": simulados,
            "buckets": buckets,
            "detalle": detalle,
            "diagnostico": diagnostico if incluir_diag else None,
        },
        status=status.HTTP_200_OK,
    )


def handle_enviar_mensaje_cuotas(request, poliza: Poliza):
    """
    Lógica de /polizas/{id}/enviar-mensaje-cuotas extraída del ViewSet.
    """
    p = poliza
    cli = getattr(p, "cliente", None)
    tel_raw = (getattr(cli, "telefono", "") or "").strip()
    if not tel_raw:
        return Response(
            {"ok": False, "error": "sin_telefono"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    hoy = timezone.localdate()
    impagas = list(
        Cuota.objects.filter(poliza=p, pagado=False).order_by(
            "fecha_vencimiento", "cuota_nro", "id"
        )
    )
    estado_label, primera_vto, cant_impagas = _estado_cuotas_label(impagas, hoy)
    try:
        monto_total = sum([(c.monto or 0) for c in impagas])
    except Exception:
        monto_total = 0

    msg = construir_mensaje_estado_cuotas(p)
    ok, info = enviar_whatsapp(tel_raw, msg)

    diag = {
        "estado_cuotas": estado_label,
        "impagas": cant_impagas,
        "monto_total": float(monto_total or 0),
        "primera_vto": (primera_vto.isoformat() if primera_vto else None),
        "mensaje_preview": (msg[:240] + ("…" if len(msg) > 240 else "")),
    }

    telefono_log = (info.get("to") if isinstance(info, dict) else tel_raw)

    if ok:
        _hist_log(
            poliza=p,
            tipo="MENSAJE_ENVIO_CUOTAS",
            mensaje="WhatsApp enviado (unitario)",
            severidad="ACTION",
            data={"telefono": telefono_log, "info": info},
            request=request,
            subject=p,
            categoria="POLIZA",
        )
    else:
        _hist_log(
            poliza=p,
            tipo="MENSAJE_ENVIO_CUOTAS_ERROR",
            mensaje="Error WhatsApp (unitario)",
            severidad="ERROR",
            data={"telefono": telefono_log, "error": info},
            request=request,
            subject=p,
            categoria="POLIZA",
        )

    return Response(
        {"ok": bool(ok), "info": info, "diagnostico": diag},
        status=status.HTTP_200_OK if ok else status.HTTP_502_BAD_GATEWAY,
    )