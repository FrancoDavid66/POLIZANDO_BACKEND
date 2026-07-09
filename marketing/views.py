# marketing/views.py
import os
import json
import time
import random
import logging
import base64
import threading

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import close_old_connections
from django.db.models import Q, Max, Min, Count, F
from django.db.models.functions import Coalesce
from django.utils import timezone
from datetime import timedelta

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import BasePermission, IsAuthenticated

from polizas.models import Poliza
from marketing.models import HistorialMensajeMarketing, HistorialMensajeMarketingLog
from notificaciones.utils.mensajeria import enviar_whatsapp
from usuarios.models import Oficina

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# ANTI-BLOQUEO (WhatsApp): pausa entre mensajes + pausa larga cada N envíos.
# Editá estos números si querés más/menos conservador.
# ─────────────────────────────────────────────────────────────────────────────
ANTIBAN_DELAY_MIN = 4.0     # segundos mínimos entre mensaje y mensaje
ANTIBAN_DELAY_MAX = 8.0     # segundos máximos entre mensaje y mensaje
ANTIBAN_BATCH = 25          # cada cuántos mensajes hace la pausa larga
ANTIBAN_PAUSE = 600         # duración de la pausa larga (10 minutos)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers a nivel módulo (los usa también el envío en segundo plano)
# ─────────────────────────────────────────────────────────────────────────────
def _norm_phone_ar(phone):
    if not phone:
        return None
    s = "".join(filter(str.isdigit, str(phone)))
    if not s:
        return None
    if s.startswith("00"):
        s = s[2:]
    if s.startswith("0"):
        s = s[1:]
    if s.startswith("54"):
        if len(s) > 10 and s[2] != "9":
            s = "549" + s[2:]
    else:
        if s.startswith("15"):
            s = s[2:]
        s = "549" + s
    return s


def _render_msg(template, poliza):
    msg = template or ""
    cliente = poliza.cliente
    reemplazos = {
        "{nombre}": str(cliente.nombre or "Cliente").strip().capitalize(),
        "{apellido}": str(cliente.apellido or "").strip().capitalize(),
        "{marca}": str(poliza.marca or "").strip(),
        "{modelo}": str(poliza.modelo or "").strip(),
        "{anio}": str(poliza.anio or ""),
        "{compania}": str(poliza.compania or ""),
        "{patente}": str(poliza.patente or "").upper(),
        "{oficina}": str(getattr(poliza.oficina, "nombre", poliza.oficina) or ""),
    }
    for key, val in reemplazos.items():
        msg = msg.replace(key, val)
    return msg


def _procesar_envio_masivo(historial_id, poliza_ids, msg_base, imagen_data):
    """
    Corre en un HILO aparte: envía los mensajes con pausas anti-bloqueo y va
    guardando el progreso en el historial + un log por cada envío.

    Se hace en segundo plano para que la request no se cuelgue ni la corte el
    timeout del servidor (los envíos masivos con pausas pueden durar mucho).
    """
    close_old_connections()
    try:
        historial = HistorialMensajeMarketing.objects.get(id=historial_id)
    except HistorialMensajeMarketing.DoesNotExist:
        return

    enviados = 0
    errores = 0
    total = len(poliza_ids)
    logger.info(f"[Marketing] Campaña {historial_id}: enviando a {total} clientes.")

    for i, pid in enumerate(poliza_ids, start=1):
        try:
            p = Poliza.objects.select_related("cliente", "oficina").get(id=pid)
        except Poliza.DoesNotExist:
            continue

        tel = _norm_phone_ar(getattr(p.cliente, "telefono", ""))
        if not tel:
            continue

        msg_final = _render_msg(msg_base, p)
        oficina_poliza = p.oficina.id if p.oficina else None

        try:
            ok, info = enviar_whatsapp(tel, msg_final, oficina=oficina_poliza, imagen=imagen_data)
            if ok:
                enviados += 1
            else:
                errores += 1
            HistorialMensajeMarketingLog.objects.create(
                historial=historial,
                numero=tel,
                numero_normalizado=tel,
                estado="ok" if ok else "error",
                mensaje_renderizado=msg_final,
                error="" if ok else str(info),
                cliente_id=p.cliente_id,
                poliza_id=p.id,
            )
        except Exception as e:
            errores += 1
            logger.error(f"[Marketing] Error enviando póliza {pid}: {e}")
            try:
                HistorialMensajeMarketingLog.objects.create(
                    historial=historial,
                    numero=tel,
                    numero_normalizado=tel,
                    estado="error",
                    mensaje_renderizado=msg_final,
                    error=str(e),
                    cliente_id=p.cliente_id,
                    poliza_id=p.id,
                )
            except Exception:
                pass

        # Progreso parcial (para ver el avance en el historial mientras corre)
        historial.total_enviados = enviados
        historial.total_errores = errores
        historial.save(update_fields=["total_enviados", "total_errores"])
        close_old_connections()

        # ── Anti-bloqueo ──
        if i < total:
            time.sleep(random.uniform(ANTIBAN_DELAY_MIN, ANTIBAN_DELAY_MAX))
            if i % ANTIBAN_BATCH == 0:
                logger.info(f"[Marketing] Campaña {historial_id}: pausa anti-bloqueo tras {i} envíos.")
                time.sleep(ANTIBAN_PAUSE)

    historial.total_enviados = enviados
    historial.total_errores = errores
    historial.ejecutado_at = timezone.now()
    historial.save()
    logger.info(f"[Marketing] Campaña {historial_id} finalizada. OK={enviados} Err={errores}")


class IsAdminProfile(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if hasattr(user, "perfil") and user.perfil.rol == "ADMIN":
            return True
        return False


class MarketingViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated, IsAdminProfile]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    # thin wrappers (por compatibilidad con el resto del código)
    def _normalize_phone_ar(self, phone):
        return _norm_phone_ar(phone)

    def _render_message(self, template, poliza):
        return _render_msg(template, poliza)

    def _parse_list_param(self, val):
        if not val:
            return []
        if isinstance(val, list):
            return [str(v).strip() for v in val if str(v).strip()]
        if isinstance(val, str):
            return [v.strip() for v in val.split(",") if v.strip()]
        return [str(val).strip()]

    # =========================================================================
    # 🎯 QUERYSET DE AUDIENCIA — mora medida por COBERTURA REAL
    #
    # Regla: las cuotas se pagan POR ADELANTADO, así que la cobertura de una
    # póliza llega hasta el vto de la ÚLTIMA cuota PAGADA (o, si nunca pagó, el
    # vto de su primera cuota). Esa fecha ("corte") es también cuándo hay que
    # pagar la próxima cuota. NO se usa el vto propio de la cuota impaga (eso
    # marcaba la mora ~1 mes tarde).
    # =========================================================================
    def _cobertura_annotated(self):
        return Poliza.objects.annotate(
            _cobertura_hasta=Max("cuotas__fecha_vencimiento", filter=Q(cuotas__pagado=True)),
            _impagas=Count("cuotas", filter=Q(cuotas__pagado=False)),
            _primer_impaga=Min("cuotas__fecha_vencimiento", filter=Q(cuotas__pagado=False)),
        ).annotate(
            _corte=Coalesce(F("_cobertura_hasta"), F("_primer_impaga")),
        )

    def _get_queryset_filtrado(self, params):
        qs = Poliza.objects.filter(cliente__isnull=False).select_related("cliente", "oficina")
        hoy = timezone.localdate()

        estado_raw = params.get("estado", "activa") or "activa"
        dias_condicion = params.get("dias_condicion")
        dias_cantidad = params.get("dias_cantidad")

        # Coherencia estado <-> día
        if dias_condicion in ("vencieron_hace", "vencieron_hace_mas", "vencieron_entre") and "vencid" not in estado_raw.lower():
            estado_raw = "vencida"
        elif dias_condicion == "vencen_en" and "activ" not in estado_raw.lower():
            estado_raw = "activa"

        # ── MODO RECONQUISTA: vencidos hace N días (O MÁS, o en un RANGO) ─────
        # La cobertura terminó hace X días. Incluye tanto a los que dejaron de
        # pagar como a los que terminaron la póliza y no renovaron.
        #   • "vencieron_hace_mas": hace >= N días (usa dias_cantidad).
        #   • "vencieron_entre":    entre X y Y días (usa dias_desde / dias_hasta).
        if dias_condicion in ("vencieron_hace_mas", "vencieron_entre"):
            cob = self._cobertura_annotated()

            if dias_condicion == "vencieron_hace_mas":
                dias = int(dias_cantidad) if (dias_cantidad and str(dias_cantidad).isdigit()) else 30
                cob = cob.filter(_corte__lte=hoy - timedelta(days=dias))
            else:  # vencieron_entre
                dias_desde = params.get("dias_desde")
                dias_hasta = params.get("dias_hasta")
                desde = int(dias_desde) if (dias_desde and str(dias_desde).isdigit()) else 30
                hasta = int(dias_hasta) if (dias_hasta and str(dias_hasta).isdigit()) else 40
                if desde > hasta:  # por si los carga al revés
                    desde, hasta = hasta, desde
                # "vencidos entre 30 y 40 días" → corte entre (hoy-40) y (hoy-30)
                cob = cob.filter(
                    _corte__gte=hoy - timedelta(days=hasta),
                    _corte__lte=hoy - timedelta(days=desde),
                )

            qs = qs.filter(id__in=cob.values("id"))

            # Excluir a los que YA volvieron (tienen otra póliza con cobertura vigente hoy),
            # para no escribirle "vení a contratar" a un cliente actual.
            # Si querés incluirlos igual, borrá estas 2 líneas.
            clientes_cubiertos = self._cobertura_annotated().filter(_corte__gte=hoy).values("cliente_id")
            qs = qs.exclude(cliente_id__in=clientes_cubiertos)

        else:
            # ── ESTADO por cobertura real ──
            if estado_raw and estado_raw.lower() != "todas":
                estados = [e.strip().lower() for e in estado_raw.split(",")]
                q_estados = Q()
                for e in estados:
                    if "vencid" in e:
                        # descubierta hoy: tiene impagas y la cobertura ya venció
                        q_estados |= (Q(_impagas__gt=0) & Q(_corte__lt=hoy))
                    elif "activ" in e:
                        # al día: sin impagas, o todavía cubierta (corte hoy o futuro)
                        q_estados |= (Q(_impagas=0) | Q(_corte__gte=hoy))
                    else:
                        q_estados |= Q(estado__icontains=e)
                ids_estado = self._cobertura_annotated().filter(q_estados).values("id")
                qs = qs.filter(id__in=ids_estado)

            # ── DÍAS exactos sobre la fecha de corte (= fecha de pago real) ──
            if dias_condicion and dias_cantidad and str(dias_cantidad).isdigit():
                dias = int(dias_cantidad)
                cob = self._cobertura_annotated()
                target = None
                if dias_condicion == "vencen_en":
                    target = cob.filter(_impagas__gt=0, _corte=hoy + timedelta(days=dias))
                elif dias_condicion == "vencieron_hace":
                    target = cob.filter(_impagas__gt=0, _corte=hoy - timedelta(days=dias))
                if target is not None:
                    qs = qs.filter(id__in=target.values("id"))

        # ── Resto de filtros ──
        oficina = params.get("oficina")
        if oficina:
            if str(oficina).isdigit():
                qs = qs.filter(oficina__id=oficina)
            else:
                qs = qs.filter(oficina__codigo__iexact=oficina)

        marcas = self._parse_list_param(params.get("marca"))
        if marcas:
            qs = qs.filter(marca__in=marcas)

        anios = self._parse_list_param(params.get("anio"))
        if anios:
            qs = qs.filter(anio__in=anios)

        modelos = self._parse_list_param(params.get("modelo"))
        if modelos:
            qs = qs.filter(modelo__in=modelos)

        companias = self._parse_list_param(params.get("compania"))
        if companias:
            qs = qs.filter(compania__in=companias)

        # 🆕 el front ya manda estos dos; ahora el backend los respeta
        tipos = self._parse_list_param(params.get("tipo"))
        if tipos:
            qs = qs.filter(tipo__in=tipos)

        coberturas = self._parse_list_param(params.get("cobertura"))
        if coberturas:
            qs = qs.filter(cobertura__in=coberturas)

        # 🆕 Filtros geográficos del cliente (solo aplican a quienes tengan el dato cargado)
        localidades = self._parse_list_param(params.get("localidad"))
        if localidades:
            qs = qs.filter(cliente__localidad__in=localidades)

        partidos = self._parse_list_param(params.get("partido"))
        if partidos:
            qs = qs.filter(cliente__partido__in=partidos)

        return qs.distinct()

    # =========================================================================

    @action(detail=False, methods=["get"], url_path="filtros/opciones")
    def opciones_filtros(self, request):
        qs = self._get_queryset_filtrado(request.query_params)
        oficinas_db = list(Oficina.objects.filter(activa=True).values("codigo", "nombre"))

        return Response({
            "oficinas": oficinas_db,
            "marcas": sorted(list(qs.exclude(marca="").values_list("marca", flat=True).distinct())),
            "anios": sorted(list(qs.exclude(anio__isnull=True).values_list("anio", flat=True).distinct()), reverse=True),
            "modelos": sorted(list(qs.exclude(modelo="").values_list("modelo", flat=True).distinct())),
            "companias": sorted(list(qs.exclude(compania="").values_list("compania", flat=True).distinct())),
            "tipos": sorted(list(qs.exclude(tipo="").exclude(tipo__isnull=True).values_list("tipo", flat=True).distinct())),
            "coberturas": sorted(list(qs.exclude(cobertura="").exclude(cobertura__isnull=True).values_list("cobertura", flat=True).distinct())),
            "localidades": sorted(list(qs.exclude(cliente__localidad__isnull=True).exclude(cliente__localidad="").values_list("cliente__localidad", flat=True).distinct())),
            "partidos": sorted(list(qs.exclude(cliente__partido__isnull=True).exclude(cliente__partido="").values_list("cliente__partido", flat=True).distinct())),
        })

    @action(detail=False, methods=["get"], url_path="audiencia/resumen")
    def audiencia_resumen(self, request):
        try:
            qs = self._get_queryset_filtrado(request.query_params)
            mensaje_template = request.query_params.get("mensaje", "")

            total_mensajes = 0
            total_sin_telefono = 0
            sample = []
            telefonos_vistos = set()
            clientes_vistos = set()

            for p in qs:
                tel_raw = getattr(p.cliente, "telefono", "")
                norm = self._normalize_phone_ar(tel_raw)

                if norm:
                    # dedup por cliente Y por teléfono → un mensaje por persona
                    if norm in telefonos_vistos or p.cliente_id in clientes_vistos:
                        continue
                    telefonos_vistos.add(norm)
                    clientes_vistos.add(p.cliente_id)
                    total_mensajes += 1
                    if len(sample) < 20:
                        sample.append({
                            "cliente_nombre": f"{p.cliente.nombre} {p.cliente.apellido}",
                            "numero": tel_raw,
                            "numero_normalizado": norm,
                            "mensaje_renderizado": self._render_message(mensaje_template, p),
                        })
                else:
                    total_sin_telefono += 1

            return Response({
                "count_polizas_match": qs.count(),
                "total_mensajes": total_mensajes,
                "sin_telefono": total_sin_telefono,
                "sample": sample,
            })
        except Exception as e:
            logger.error(f"Error en audiencia_resumen: {e}")
            return Response({"error": str(e)}, status=500)

    @action(detail=False, methods=["post"], url_path="enviar")
    def enviar_campana(self, request):
        msg_base = request.data.get("mensaje", "").strip()
        filtros_raw = request.data.get("filtros", "{}")

        if not msg_base:
            return Response({"error": "El mensaje no puede estar vacío."}, status=400)

        if isinstance(filtros_raw, str):
            try:
                filtros = json.loads(filtros_raw)
            except Exception:
                filtros = {}
        else:
            filtros = filtros_raw

        # Imagen opcional → base64 para UltraMsg
        imagen_data = None
        archivo = request.FILES.get("archivo_imagen")
        if archivo:
            ruta_marketing = os.path.join(settings.MEDIA_ROOT, "marketing")
            if not os.path.exists(ruta_marketing):
                os.makedirs(ruta_marketing)
            fs = FileSystemStorage(location=ruta_marketing, base_url="/media/marketing/")
            filename = fs.save(archivo.name, archivo)
            file_path = fs.path(filename)
            try:
                with open(file_path, "rb") as image_file:
                    encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
                    ext = os.path.splitext(filename)[1].lower()
                    mime_type = "image/jpeg"
                    if ext == ".png":
                        mime_type = "image/png"
                    elif ext == ".webp":
                        mime_type = "image/webp"
                    imagen_data = f"data:{mime_type};base64,{encoded_string}"
            except Exception as e:
                logger.error(f"Error codificando imagen a Base64: {e}")
                imagen_data = None

        qs = self._get_queryset_filtrado(filtros)

        # Lista final de destinatarios: 1 por cliente, con teléfono válido.
        poliza_ids = []
        telefonos = set()
        clientes = set()
        for p in qs:
            tel = self._normalize_phone_ar(getattr(p.cliente, "telefono", ""))
            if not tel or tel in telefonos or p.cliente_id in clientes:
                continue
            telefonos.add(tel)
            clientes.add(p.cliente_id)
            poliza_ids.append(p.id)

        historial = HistorialMensajeMarketing.objects.create(
            mensaje=msg_base,
            filtros=filtros,
            oficina=str(filtros.get("oficina", "Todas")),
            total_polizas_match=qs.count(),
            total_destinatarios=len(poliza_ids),
        )

        # 🚀 Envío en SEGUNDO PLANO con pausas anti-bloqueo (no bloquea la request).
        hilo = threading.Thread(
            target=_procesar_envio_masivo,
            args=(historial.id, poliza_ids, msg_base, imagen_data),
            daemon=True,
        )
        hilo.start()

        return Response({
            "ok": True,
            "en_proceso": True,
            "historial_id": historial.id,
            "total_destinatarios": len(poliza_ids),
            "mensaje": (
                f"Campaña iniciada. Enviando a {len(poliza_ids)} clientes en segundo plano "
                f"(con pausas anti-bloqueo). Mirá el avance en el historial."
            ),
        })

    @action(detail=False, methods=["get"], url_path="historial")
    def listar_historial(self, request):
        hist = HistorialMensajeMarketing.objects.all().order_by("-created_at")[:30]
        return Response([{
            "id": h.id,
            "mensaje": h.mensaje,
            "created_at": h.created_at,
            "ejecutado_at": h.ejecutado_at,
            "total_enviados": h.total_enviados,
            "total_errores": h.total_errores,
            "total_polizas_match": h.total_polizas_match,
            "total_destinatarios": h.total_destinatarios,
            "filtros": h.filtros,
        } for h in hist])

    @action(detail=True, methods=["get"], url_path="logs")
    def ver_logs(self, request, pk=None):
        logs = HistorialMensajeMarketingLog.objects.filter(historial_id=pk)
        return Response({
            "items": [{
                "id": l.id,
                "numero": l.numero,
                "estado": l.estado,
                "mensaje": l.mensaje_renderizado,
                "error": l.error,
            } for l in logs]
        })