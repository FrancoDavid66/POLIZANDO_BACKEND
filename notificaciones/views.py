# notificaciones/views.py
import threading
import time
import uuid
from collections import defaultdict

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status
from django.utils import timezone
from django.http import HttpResponse

# ✅ IMPORTACIÓN PARA NOTIFICACIONES DE BAJAS
from bajas.models import BajaPoliza 

from .services_cuotas import (
    enviar_recordatorios_cuotas,
    TRIGGER_DELTAS,
    obtener_cuotas_candidatas,
    _resolver_alias_transferencia,
    _build_mensaje_cliente,
    _get_numero_whatsapp,
    _fecha_pago_objetivo,
)
from .services_reporte_contactos import (
    recolectar_filas,
    generar_excel,
    generar_pdf,
    REPORT_DELTAS,
)
from notificaciones.models import EnvioRecordatoriosCuotas


def _parse_int(v):
    try:
        return int(v) if v not in (None, "", []) else None
    except (TypeError, ValueError):
        return None


def _parse_bool(v, default=False):
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "true", "t", "yes", "y", "on", "si", "sí"):
        return True
    if s in ("0", "false", "f", "no", "n", "off"):
        return False
    return default


def _build_result_payload(resultado):
    hoy = getattr(resultado, "hoy", None)
    return {
        "hoy": str(hoy) if hoy is not None else None,
        "cuotas_procesadas": getattr(resultado, "procesadas", 0),
        "mensajes_enviados": getattr(resultado, "enviados", 0),
        "errores": getattr(resultado, "errores", []) or [],
        "trigger_deltas": getattr(resultado, "trigger_deltas", []),
        "candidatas_por_delta": getattr(resultado, "candidatas_por_delta", {}),
        "seleccionadas_por_delta": getattr(resultado, "seleccionadas_por_delta", {}),
        "detalles_enviados": getattr(resultado, "detalles_enviados", []),
    }


def _preview_recordatorios(*, hoy, oficina_norm, alias, medio_cobro_id_int):
    trigger_deltas = sorted(set(int(x) for x in TRIGGER_DELTAS))
    candidatas_por_delta = defaultdict(int)
    seleccionadas_por_delta = defaultdict(int)

    alias_resuelto, titular_billetera = _resolver_alias_transferencia(
        alias, medio_cobro_id_int
    )

    cuotas = list(obtener_cuotas_candidatas(hoy, oficina=oficina_norm))
    procesadas = len(cuotas)

    por_cliente = {}

    for cuota in cuotas:
        # 🎯 Mismo criterio que el envío real: la fecha que cuenta es CUÁNDO hay
        # que pagar la cuota = fin de cobertura de la cuota anterior.
        fecha_objetivo = _fecha_pago_objetivo(cuota)
        if not fecha_objetivo:
            continue

        delta = (fecha_objetivo - hoy).days
        candidatas_por_delta[int(delta)] += 1

        if int(delta) not in TRIGGER_DELTAS:
            continue

        seleccionadas_por_delta[int(delta)] += 1

        numero = _get_numero_whatsapp(cuota)
        if not numero:
            continue

        poliza = getattr(cuota, "poliza", None)
        cliente = getattr(poliza, "cliente", None) if poliza else None
        if not cliente:
            continue

        key = (cliente.id, numero)
        if key not in por_cliente:
            por_cliente[key] = {"cliente": cliente, "numero": numero, "items": []}
        por_cliente[key]["items"].append((cuota, int(delta), fecha_objetivo))

    would_send = len(por_cliente)

    examples = []
    for (cliente_id, numero), data in list(por_cliente.items())[:3]:
        cliente = data["cliente"]
        items = data["items"]
        try:
            msg = _build_mensaje_cliente(
                cliente,
                items,
                alias_transferencia=alias_resuelto,
                titular_billetera=titular_billetera,
            )
        except Exception as exc:
            msg = f"(error armando mensaje: {exc})"

        examples.append(
            {
                "cliente_id": cliente_id,
                "numero": numero,
                "cuotas_en_mensaje": len(items),
                "deltas": sorted({d for (_c, d, _f) in items}),
                "mensaje_preview": msg,
            }
        )

    return {
        "ok": True,
        "preview": True,
        "hoy": str(hoy),
        "oficina": oficina_norm,
        "cuotas_procesadas": procesadas,
        "mensajes_enviados": would_send,
        "errores": [],
        "trigger_deltas": trigger_deltas,
        "candidatas_por_delta": dict(candidatas_por_delta),
        "seleccionadas_por_delta": dict(seleccionadas_por_delta),
        "alias_resuelto": alias_resuelto,
        "titular_billetera": titular_billetera,
        "examples": examples,
    }


class EnviarRecorditoriosCuotasView(APIView):
    """Alias con typo histórico para compatibilidad con urls.py."""
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        view = EnviarRecordatoriosCuotasView.as_view()
        return view(request, *args, **kwargs)


class EnviarRecordatoriosCuotasView(APIView):
    """
    POST /api/notificaciones/cuotas/enviar-recordatorios/
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        t0 = time.time()

        alias = request.data.get("alias") or request.data.get("alias_transferencia")
        medio_cobro_id_int = _parse_int(request.data.get("medio_cobro_id"))
        oficina = (request.data.get("oficina") or "").strip()

        if not oficina:
            return Response(
                {
                    "ok": False,
                    "error": "Falta 'oficina'. En producción no se permite enviar recordatorios sin oficina.",
                    "hint": "Enviar body: { oficina: '1' } (o '2' o '3')",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        oficina_norm = str(oficina).strip()
        hoy = timezone.localdate()

        preview = _parse_bool(request.data.get("preview"), default=False)
        force   = _parse_bool(request.data.get("force"),   default=False)

        if preview:
            payload = _preview_recordatorios(
                hoy=hoy,
                oficina_norm=oficina_norm,
                alias=alias or None,
                medio_cobro_id_int=medio_cobro_id_int,
            )
            payload["async"]  = False
            payload["job_id"] = str(uuid.uuid4())
            payload["t_ms"]   = int((time.time() - t0) * 1000)
            return Response(payload, status=status.HTTP_200_OK)

        if force:
            try:
                EnvioRecordatoriosCuotas.objects.filter(
                    fecha=hoy, oficina=oficina_norm
                ).delete()
            except Exception:
                pass

        run_async = _parse_bool(request.data.get("async"), default=False)
        job_id    = str(uuid.uuid4())

        def _runner():
            try:
                enviar_recordatorios_cuotas(
                    alias_transferencia=alias or None,
                    medio_cobro_id=medio_cobro_id_int,
                    oficina=oficina_norm,
                )
            except Exception:
                return

        if run_async:
            th = threading.Thread(target=_runner, daemon=True)
            th.start()
            return Response(
                {
                    "ok": True,
                    "async": True,
                    "job_id": job_id,
                    "oficina": oficina_norm,
                    "nota": "Envío de recordatorios en proceso (async).",
                    "hoy": str(hoy),
                    "cuotas_procesadas": 0,
                    "mensajes_enviados": 0,
                    "errores": [],
                    "trigger_deltas": sorted(list(TRIGGER_DELTAS)),
                    "candidatas_por_delta": {},
                    "seleccionadas_por_delta": {},
                    "t_ms": int((time.time() - t0) * 1000),
                },
                status=status.HTTP_202_ACCEPTED,
            )

        # Síncrono: corre los recordatorios de cuotas y devuelve el resultado detallado.
        resultado = enviar_recordatorios_cuotas(
            alias_transferencia=alias or None,
            medio_cobro_id=medio_cobro_id_int,
            oficina=oficina_norm,
        )

        payload = _build_result_payload(resultado)
        payload["ok"]     = True
        payload["async"]  = False
        payload["job_id"] = job_id
        payload["oficina"] = oficina_norm
        payload["force"]  = bool(force)
        payload["t_ms"]   = int((time.time() - t0) * 1000)
        return Response(payload, status=status.HTTP_200_OK)


class CuotasRecordatoriosView(EnviarRecordatoriosCuotasView):
    """POST /api/notificaciones/cuotas/recordatorios/"""
    pass


class CuotasAlertasView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        return Response(
            {
                "ok": True,
                "accion": "alertas",
                "mensajes_enviados": 0,
                "nota": "Endpoint de compatibilidad.",
            },
            status=status.HTTP_200_OK,
        )


class CuotasHistorialView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, *args, **kwargs):
        try:
            from notificaciones.models import NotificacionCuotaLog
        except Exception as exc:
            return Response(
                {"ok": False, "error": "No se pudo importar NotificacionCuotaLog", "detail": str(exc)},
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )
        qs   = NotificacionCuotaLog.objects.all().order_by("-id")[:200]
        data = list(qs.values("id", "fecha", "cliente_id", "numero"))
        return Response({"count": len(data), "results": data})


class SidebarBadgesView(APIView):
    """
    GET /api/notificaciones/sidebar-badges/
    Devuelve conteos de tareas pendientes para el menú lateral.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, *args, **kwargs):
        bajas_pendientes = BajaPoliza.objects.filter(estado="PENDIENTE_ENVIO").count()
        return Response({
            "bajas":        bajas_pendientes,
            "renovaciones": 1,
            "solicitudes":  0,
        }, status=status.HTTP_200_OK)


# ── ENVÍO A TODAS LAS OFICINAS EN PARALELO ────────────────────────────────────
class EnviarTodasOficinasView(APIView):
    """
    POST /api/notificaciones/cuotas/enviar-todas-oficinas/

    Lanza un thread por cada oficina activa. Las 4 oficinas envían
    en simultáneo (cada una desde su propia instancia UltraMsg).
    Responde inmediato; el frontend hace polling al historial para
    ver el progreso.

    Body (todos opcionales):
      - alias / alias_transferencia
      - medio_cobro_id
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        # Solo admin puede enviar a todas las oficinas
        user     = request.user
        es_admin = user.is_superuser or (
            hasattr(user, "perfil") and user.perfil.rol == "ADMIN"
        )
        if not es_admin:
            return Response(
                {"ok": False, "error": "Solo el administrador puede enviar a todas las oficinas."},
                status=status.HTTP_403_FORBIDDEN,
            )

        alias          = request.data.get("alias") or request.data.get("alias_transferencia")
        medio_cobro_id = _parse_int(request.data.get("medio_cobro_id"))
        job_id         = str(uuid.uuid4())

        # Obtener todas las oficinas activas desde la BD
        try:
            from usuarios.models import Oficina
            oficinas = list(
                Oficina.objects.filter(activo=True)
                .values_list("id", flat=True)
                .order_by("id")
            )
            if not oficinas:
                oficinas = [1, 2, 3, 4]
        except Exception:
            oficinas = [1, 2, 3, 4]

        oficinas_str = [str(o) for o in oficinas]
        hoy          = timezone.localdate()

        # Un thread por oficina, todos arrancan al mismo tiempo.
        def _runner_oficina(ofi):
            print(f"[EnviarTodas] ▶ Oficina {ofi} iniciada (job={job_id})")
            try:
                resultado = enviar_recordatorios_cuotas(
                    hoy=hoy,
                    alias_transferencia=alias or None,
                    medio_cobro_id=medio_cobro_id,
                    oficina=ofi,
                )
                rec_enviados = resultado.enviados
                print(
                    f"[EnviarTodas] ✅ Oficina {ofi} completada — "
                    f"recordatorios={rec_enviados}"
                )
            except Exception as exc:
                print(f"[EnviarTodas] ❌ Oficina {ofi} error: {exc}")

        threads_lanzados = 0
        for ofi in oficinas_str:
            th = threading.Thread(
                target=_runner_oficina,
                args=(ofi,),
                name=f"recordatorios_ofi_{ofi}",
                daemon=True,
            )
            th.start()
            threads_lanzados += 1

        print(
            f"[EnviarTodas] 🚀 job={job_id} — {threads_lanzados} threads "
            f"lanzados en paralelo: {oficinas_str}"
        )

        return Response(
            {
                "ok":       True,
                "async":    True,
                "job_id":   job_id,
                "oficinas": oficinas_str,
                "modo":     "paralelo",
                "nota": (
                    f"Envío iniciado en paralelo para {threads_lanzados} oficinas. "
                    "Cada una manda desde su propio celular UltraMsg."
                ),
                "hoy": str(hoy),
            },
            status=status.HTTP_202_ACCEPTED,
        )

# ── REPORTE DE CONTACTOS PENDIENTES (PDF / EXCEL) ─────────────────────────────
class ReporteContactosView(APIView):
    """
    GET /api/notificaciones/cuotas/reporte-contactos/
    
    Query params:
      - formato:        'pdf' o 'excel' (default: 'pdf')
      - oficina:        filtro por oficina (ej: '1', '2', '3'). Default: todas.
      - alias:          alias de transferencia a mostrar en el reporte (opcional)
      - medio_cobro_id: ID del medio de cobro (opcional)
    
    Devuelve el archivo binario con los clientes que tienen cuotas
    en los deltas -7, -3, 0, +3, +7 días, para gestión manual.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, *args, **kwargs):
        formato        = (request.query_params.get("formato") or "pdf").strip().lower()
        oficina        = (request.query_params.get("oficina") or "").strip() or None
        alias          = request.query_params.get("alias") or request.query_params.get("alias_transferencia")
        medio_cobro_id = _parse_int(request.query_params.get("medio_cobro_id"))

        if formato not in ("pdf", "excel", "xlsx"):
            return Response(
                {"ok": False, "error": "Formato inválido. Usar 'pdf' o 'excel'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        hoy = timezone.localdate()
        filas, meta = recolectar_filas(
            hoy=hoy,
            oficina=oficina,
            alias_transferencia=alias,
            medio_cobro_id=medio_cobro_id,
        )

        ofi_label = (oficina or "todas").replace(" ", "_")
        fecha_label = hoy.strftime("%Y-%m-%d")

        if formato == "pdf":
            try:
                contenido = generar_pdf(filas, meta)
            except Exception as exc:
                return Response(
                    {"ok": False, "error": f"Error generando PDF: {exc}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            resp = HttpResponse(contenido, content_type="application/pdf")
            resp["Content-Disposition"] = (
                f'attachment; filename="contactos_pendientes_{ofi_label}_{fecha_label}.pdf"'
            )
            return resp

        # excel / xlsx
        try:
            contenido = generar_excel(filas, meta)
        except Exception as exc:
            return Response(
                {"ok": False, "error": f"Error generando Excel: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        resp = HttpResponse(
            contenido,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        resp["Content-Disposition"] = (
            f'attachment; filename="contactos_pendientes_{ofi_label}_{fecha_label}.xlsx"'
        )
        return resp