# pagos/views_reportes.py
#
# Mixin con la acción de reporte de efectividad de recordatorios, separada
# de pagos/views.py para que ese archivo no sea un solo bloque enorme.
# Se usa por herencia en PagoViewSet — mismo comportamiento, misma URL,
# solo cambia en qué archivo vive el código.

from datetime import date, timedelta

from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status

from .models import AlertaEnviada
from pagos.views_helpers import (
    _get_seguridad_oficina_brute,
    _build_oficina_q_from_keys,
    _parse_ymd,
)


class ReporteEfectividadMixin:
    @action(detail=False, methods=["get"], url_path="reporte-efectividad")
    def reporte_efectividad(self, request):
        oficina_keys = _get_seguridad_oficina_brute(request, request.query_params.get("oficina", ""))
        if "BLOQUEADO" in oficina_keys:
            return Response({"detail": "Acceso denegado"}, status=403)

        alertas_qs = AlertaEnviada.objects.select_related(
            "cuota",
            "cuota__poliza",
            "cuota__poliza__cliente"
        ).filter(enviada=True)

        if oficina_keys:
            alertas_qs = alertas_qs.filter(_build_oficina_q_from_keys(oficina_keys))

        # 🚀 APLICAR FILTROS DE FECHA
        desde = request.query_params.get("desde")
        hasta = request.query_params.get("hasta")
        anio = request.query_params.get("anio")
        mes = request.query_params.get("mes")

        if desde or hasta:
            d1 = _parse_ymd(desde) if desde else None
            d2 = _parse_ymd(hasta) if hasta else None
            if d1:
                alertas_qs = alertas_qs.filter(fecha__gte=d1)
            if d2:
                alertas_qs = alertas_qs.filter(fecha__lt=(d2 + timedelta(days=1)))
        elif anio and mes:
            try:
                y = int(anio)
                m = int(mes)
                first = date(y, m, 1)
                if m == 12:
                    nxt = date(y + 1, 1, 1)
                else:
                    nxt = date(y, m + 1, 1)
                alertas_qs = alertas_qs.filter(fecha__gte=first, fecha__lt=nxt)
            except Exception:
                pass
        elif anio:
             try:
                y = int(anio)
                first = date(y, 1, 1)
                nxt = date(y + 1, 1, 1)
                alertas_qs = alertas_qs.filter(fecha__gte=first, fecha__lt=nxt)
             except Exception:
                pass

        # 🚀 ORDENAR DE MÁS NUEVO A MÁS VIEJO
        alertas_qs = alertas_qs.order_by("-fecha")

        resultados_pagados = []
        resultados_pendientes = []

        horas_totales = 0
        pagos_recuperados = 0
        total_enviadas = 0

        hoy = timezone.now()

        for alerta in alertas_qs:
            total_enviadas += 1
            cli = alerta.cuota.poliza.cliente
            nombre_cliente = f"{getattr(cli, 'nombre', '')} {getattr(cli, 'apellido', '')}".strip()

            if alerta.cuota.pagado and alerta.cuota.pago_registrado_en:
                delta = alerta.cuota.pago_registrado_en - alerta.fecha
                if delta.total_seconds() >= 0:
                    horas_pasadas = delta.total_seconds() / 3600.0
                    resultados_pagados.append({
                        "alerta_id": alerta.id,
                        "tipo_mensaje": alerta.tipo,
                        "fecha_mensaje": timezone.localtime(alerta.fecha).strftime("%d/%m/%Y %H:%M"),
                        "fecha_pago": timezone.localtime(alerta.cuota.pago_registrado_en).strftime("%d/%m/%Y %H:%M"),
                        "horas_tardanza": round(horas_pasadas, 1),
                        "cuota_nro": alerta.cuota.cuota_nro,
                        "monto_recuperado": float(alerta.cuota.monto) if alerta.cuota.monto else 0.0,
                        "cliente": nombre_cliente,
                        "patente": alerta.cuota.poliza.patente
                    })
                    horas_totales += horas_pasadas
                    pagos_recuperados += 1
            else:
                delta_pendiente = hoy - alerta.fecha
                dias_pasados = delta_pendiente.total_seconds() / 86400.0
                resultados_pendientes.append({
                    "alerta_id": alerta.id,
                    "tipo_mensaje": alerta.tipo,
                    "fecha_mensaje": timezone.localtime(alerta.fecha).strftime("%d/%m/%Y %H:%M"),
                    "dias_sin_pagar": round(max(0, dias_pasados), 1),
                    "cuota_nro": alerta.cuota.cuota_nro,
                    "monto_adeudado": float(alerta.cuota.monto) if alerta.cuota.monto else 0.0,
                    "cliente": nombre_cliente,
                    "patente": alerta.cuota.poliza.patente
                })

        promedio_horas = round(horas_totales / pagos_recuperados, 1) if pagos_recuperados > 0 else 0
        tasa_conversion = round((pagos_recuperados / total_enviadas) * 100, 1) if total_enviadas > 0 else 0

        return Response({
            "kpis": {
                "total_mensajes_enviados": total_enviadas,
                "pagos_recuperados": pagos_recuperados,
                "tasa_conversion": f"{tasa_conversion}%",
                "tiempo_promedio_respuesta_horas": promedio_horas
            },
            "detalle_pagados": resultados_pagados,
            "detalle_pendientes": resultados_pendientes
        }, status=status.HTTP_200_OK)