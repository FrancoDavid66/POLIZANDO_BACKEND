# polizas/views.py
from rest_framework import viewsets, status, filters
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny

from django.db.models import Count, Q  # 👈 agregado Q
from django.utils import timezone
from datetime import timedelta, date

from seguros_project.pagination import LargeResultsSetPagination

from polizas.models import Poliza, FotoVehiculo, PolizaDocumento
from polizas.serializers import PolizaSerializer, FotoVehiculoSerializer, PolizaDocumentoSerializer
from polizas.handlers.create_poliza import handle_create_poliza
from polizas.handlers.renovacion import handle_renovar_poliza, handle_duplicar_renovacion
from pagos.models import Cuota

# 🔁 Fuente de verdad compañías y normalización (RNE/NRE → RCE, etc.)
from polizas.utils.constants import list_companias, normalizar_compania

from polizas.utils.viewtools import (
    hist_log as _hist_log,
    annotate_mora as _annotate_mora,
    apply_financial_bucket,
    apply_vencimiento_filters,
    apply_poliza_filters,
)
from polizas.utils.mensajeria import enviar_whatsapp, construir_mensaje_estado_cuotas

# (opcional) para mostrar el número normalizado en el diagnóstico si está disponible
try:
    from polizas.utils.ultramsg import _normalizar_numero as _wa_normalize
except Exception:
    _wa_normalize = None


def _estado_cuotas_label(impagas, hoy: date):
    """
    Dado un iterable de cuotas impagas (ordenadas por fecha), devuelve un label:
    - al_dia | por_vencer | vence_hoy | vencida_7 | vencida_30 | vencidas
    """
    impagas = list(impagas)
    if not impagas:
        return "al_dia", None, 0

    primera = impagas[0]
    vto = getattr(primera, "fecha_vencimiento", None)
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


class PolizaViewSet(viewsets.ModelViewSet):
    queryset = Poliza.objects.all().order_by("id")
    serializer_class = PolizaSerializer
    permission_classes = [AllowAny]
    filter_backends = [filters.SearchFilter]
    search_fields = [
        "patente", "marca", "modelo",
        # 👇 ya permitía buscar por nombre/apellido/dni del asegurado (cliente)
        "cliente__nombre", "cliente__apellido", "cliente__dni_cuit_cuil",
        "numero_poliza", "compania",
    ]
    pagination_class = LargeResultsSetPagination
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params

        estado = (params.get("estado") or "").strip()
        compania = (params.get("compania") or "").strip()
        cliente_id = (params.get("cliente") or "").strip()
        patente = (params.get("patente") or "").strip()
        solo_activas = (params.get("solo_activas") or "").lower() in {"1", "true", "t", "yes", "y"}
        fase = (params.get("fase") or "").strip()
        sin_numero = (params.get("sin_numero") or "").lower() in {"1", "true", "t", "yes", "y"}

        # ✅ NUEVO: búsqueda directa por nombre del asegurado (además de ?search=)
        asegurado_q = (params.get("asegurado") or params.get("asegurado_nombre") or "").strip()
        if asegurado_q:
            # Split por espacios y aplica AND entre tokens en nombre/apellido
            tokens = [t for t in asegurado_q.split() if t]
            for t in tokens:
                qs = qs.filter(Q(cliente__nombre__icontains=t) | Q(cliente__apellido__icontains=t))

        if estado:
            qs = qs.filter(estado=estado)

        if compania:
            # Normaliza alias a clave canónica (RNE/NRE → RCE). Si falla, usa el valor crudo.
            try:
                compania_canon = normalizar_compania(compania)
                qs = qs.filter(compania__iexact=compania_canon)
            except Exception:
                qs = qs.filter(compania__iexact=compania)

        if cliente_id.isdigit():
            qs = qs.filter(cliente_id=int(cliente_id))
        if patente:
            qs = qs.filter(patente__iexact=patente)
        if solo_activas:
            qs = qs.filter(estado="activa")
        if fase:
            qs = qs.filter(fase=fase)
        if sin_numero:
            qs = qs.filter(sin_numero=True)

        qs = apply_financial_bucket(qs, (params.get("estado_financiero") or ""))
        qs = apply_vencimiento_filters(qs, params)

        return qs

    def create(self, request, *args, **kwargs):
        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            # ⚙️ La lógica de cuotas/fechas está en el handler y usa constants.py (fuente de verdad)
            poliza = handle_create_poliza(serializer)
            _hist_log(poliza=poliza, tipo="POLIZA_CREAR", mensaje="Póliza creada",
                      severidad="ACTION", request=request, subject=poliza, categoria="POLIZA")
            return Response(self.get_serializer(poliza).data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({"error": "Error al crear la póliza", "detalle": str(e)},
                            status=status.HTTP_400_BAD_REQUEST)

    # ---------- Catálogos para el front ----------

    @action(detail=False, methods=["get"], url_path="companias", permission_classes=[AllowAny])
    def companias(self, request):
        """
        GET /api/polizas/companias/
        - ?flat=1 para lista simple de strings.
        - por defecto devuelve [{id, nombre}, ...]
        """
        vals = list_companias()  # lista de strings (fuente de verdad)
        flat = (request.query_params.get("flat") or "").lower() in {"1", "true", "t", "yes", "y"}
        if flat:
            return Response(vals, status=status.HTTP_200_OK)
        data = [{"id": v, "nombre": v} for v in vals]
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="coberturas", permission_classes=[AllowAny])
    def coberturas(self, request):
        """
        GET /api/polizas/coberturas/
        Devuelve las coberturas distintas registradas en pólizas:
          - ?flat=1 -> ["Terceros Completo", "RC", ...]
          - default -> [{ "id": "RC", "nombre": "RC" }, ...]
        """
        vals = (
            Poliza.objects
            .values_list("cobertura", flat=True)
            .exclude(cobertura__isnull=True)
            .exclude(cobertura__exact="")
            .distinct()
            .order_by("cobertura")
        )
        flat = (request.query_params.get("flat") or "").lower() in {"1", "true", "t", "yes", "y"}
        if flat:
            return Response(list(vals), status=status.HTTP_200_OK)
        data = [{"id": v, "nombre": v} for v in vals]
        return Response(data, status=status.HTTP_200_OK)

    # ---------- Renovaciones ----------

    @action(detail=True, methods=["post"], url_path="renovar")
    def renovar_poliza(self, request, pk=None):
        poliza = self.get_object()
        resp = handle_renovar_poliza(request, poliza)
        if resp.status_code in (200, 201):
            nueva_id = None
            try:
                nueva_id = resp.data.get("id")
            except Exception:
                pass
            _hist_log(poliza=poliza, tipo="POLIZA_RENOVAR",
                      mensaje="Póliza renovada (se creó nueva versión)",
                      severidad="ACTION", data={"nueva_poliza_id": nueva_id},
                      request=request, subject=poliza, categoria="POLIZA")
        return resp

    @action(detail=True, methods=["post"], url_path="duplicar-renovacion")
    def duplicar_renovacion(self, request, pk=None):
        original = self.get_object()
        resp = handle_duplicar_renovacion(request, original)
        if resp.status_code in (200, 201):
            nueva_id = None
            try:
                nueva_id = resp.data.get("id")
            except Exception:
                pass
            _hist_log(poliza=original, tipo="POLIZA_RENOVAR",
                      mensaje="Póliza renovada (alias duplicar-renovacion)",
                      severidad="ACTION", data={"nueva_poliza_id": nueva_id},
                      request=request, subject=original, categoria="POLIZA")
        return resp

    # ---------- KPIs / Resúmenes ----------

    @action(detail=False, methods=["get"], url_path="kpis", permission_classes=[AllowAny])
    def kpis(self, request):
        params = self.request.query_params
        base_all = Poliza.objects.all().order_by("id")
        for backend in self.filter_backends:
            base_all = backend().filter_queryset(request, base_all, self)

        cliente_id = (params.get("cliente") or "").strip()
        patente = (params.get("patente") or "").strip()
        solo_activas = (params.get("solo_activas") or "").lower() in {"1", "true", "t", "yes", "y"}

        if cliente_id.isdigit():
            base_all = base_all.filter(cliente_id=int(cliente_id))
        if patente:
            base_all = base_all.filter(patente__iexact=patente)
        if solo_activas:
            base_all = base_all.filter(estado="activa")

        hoy = timezone.localdate()
        activas = _annotate_mora(base_all.filter(estado="activa"), hoy)
        por_estado = {
            "activa": base_all.filter(estado="activa").count(),
            "vencida": base_all.filter(estado="vencida").count(),
            "cancelada": base_all.filter(estado="cancelada").count(),
            "finalizada": base_all.filter(estado="finalizada").count(),
        }
        kpis_fin = {
            "activas_al_dia": activas.filter(overdue_exists=False).count(),
            "activas_mora_1_30": activas.filter(min_overdue__gte=hoy - timedelta(days=30), min_overdue__lt=hoy).count(),
            "activas_mora_31_60": activas.filter(min_overdue__gte=hoy - timedelta(days=60), min_overdue__lt=hoy - timedelta(days=30)).count(),
            "activas_mora_61_90": activas.filter(min_overdue__gte=hoy - timedelta(days=90), min_overdue__lt=hoy - timedelta(days=60)).count(),
            "activas_mora_90_mas": activas.filter(min_overdue__lt=hoy - timedelta(days=90)).count(),
        }

        por_compania_qs = Poliza.objects.all()
        for backend in self.filter_backends:
            por_compania_qs = backend().filter_queryset(request, por_compania_qs, self)
        por_compania = {
            row["compania"] or "—": row["c"]
            for row in por_compania_qs.values("compania").annotate(c=Count("id")).order_by()
        }

        por_cobertura = None
        if hasattr(Poliza, "cobertura"):
            por_cobertura = {
                row["cobertura"] or "—": row["c"]
                for row in por_compania_qs.values("cobertura").annotate(c=Count("id")).order_by()
            }
        por_tipo = None
        if hasattr(Poliza, "tipo"):
            por_tipo = {
                row["tipo"] or "—": row["c"]
                for row in por_compania_qs.values("tipo").annotate(c=Count("id")).order_by()
            }

        payload = {
            **kpis_fin,
            "vencidas": por_estado["vencida"],
            "canceladas": por_estado["cancelada"],
            "finalizadas": por_estado["finalizada"],
            "total": base_all.count(),
            "por_estado": por_estado,
            "por_compania": por_compania,
            "por_cobertura": por_cobertura,
            "por_tipo": por_tipo,
            "total_global": Poliza.objects.count(),
        }
        return Response(payload, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="resumen-estados", permission_classes=[AllowAny])
    def resumen_estados(self, request):
        """
        Buckets alineados con _estado_cuotas_label:
          - al_dia:     fecha_vencimiento > hoy + 7
          - por_vencer: hoy < fecha_vencimiento <= hoy + 7
          - vence_hoy:  fecha_vencimiento == hoy
          - vencida_7:  hoy - 7 <= fecha_vencimiento < hoy
          - vencida_30: hoy - 30 <= fecha_vencimiento < hoy - 7
          - vencidas:   fecha_vencimiento < hoy - 30
        """
        today = timezone.localdate()
        qs = Poliza.objects.all()

        qs_act = qs.filter(estado="activa").exclude(fecha_vencimiento__isnull=True)

        resumen = {
            "al_dia": qs_act.filter(fecha_vencimiento__gt=today + timedelta(days=7)).count(),
            "por_vencer": qs_act.filter(
                fecha_vencimiento__gt=today,
                fecha_vencimiento__lte=today + timedelta(days=7)
            ).count(),
            "vence_hoy": qs_act.filter(fecha_vencimiento=today).count(),
            "vencida_7": qs_act.filter(
                fecha_vencimiento__lt=today,
                fecha_vencimiento__gte=today - timedelta(days=7)
            ).count(),
            "vencida_30": qs_act.filter(
                fecha_vencimiento__lt=today - timedelta(days=7),
                fecha_vencimiento__gte=today - timedelta(days=30)
            ).count(),
            "vencidas": qs_act.filter(
                fecha_vencimiento__lt=today - timedelta(days=30)
            ).count(),
            "canceladas": qs.filter(estado="cancelada").count(),
            "todos": qs.count(),
        }
        return Response(resumen)

    # ---------- Cuotas ----------

    @action(detail=True, methods=["get"], url_path="cuotas", permission_classes=[AllowAny])
    def listar_cuotas(self, request, pk=None):
        poliza = self.get_object()
        qs = Cuota.objects.filter(poliza=poliza).order_by("cuota_nro", "fecha_vencimiento", "id")
        data = [{
            "id": c.id,
            "cuota_nro": c.cuota_nro,
            "fecha_vencimiento": c.fecha_vencimiento,
            "pagado": bool(c.pagado),
            "fecha_pago": getattr(c, "fecha_pago", None),
            "monto": getattr(c, "monto", None),
        } for c in qs]
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="versiones-por-patente", permission_classes=[AllowAny])
    def versiones_por_patente(self, request):
        patente = (request.query_params.get("patente") or "").strip()
        if not patente:
            return Response({"detail": "Falta parámetro 'patente'."}, status=status.HTTP_400_BAD_REQUEST)
        qs = self.get_queryset().filter(patente__iexact=patente).order_by("-id")
        page = self.paginate_queryset(qs)
        if page is not None:
            ser = self.get_serializer(page, many=True)
            return self.get_paginated_response(ser.data)
        ser = self.get_serializer(qs, many=True)
        return Response(ser.data, status=status.HTTP_200_OK)

    # ---------- ✅ Chequeo de fotos requeridas (solo lectura) ----------
    @action(detail=True, methods=["get"], url_path="requisitos-fotos", permission_classes=[AllowAny])
    def requisitos_fotos(self, request, pk=None):
        """
        GET /api/polizas/{id}/requisitos-fotos/
        Verifica presencia de las 4 fotos obligatorias del vehículo:
          - FRENTE, LATERAL_IZQ, LATERAL_DER y TRASERA.
        Respuesta:
          {
            "ok": bool,
            "requeridas": [...],
            "faltantes": [...],
            "encontradas": {"FRENTE": n, ...},
            "total_encontradas": n,
            "poliza_id": id
          }
        """
        poliza = self.get_object()
        requeridas = ["FRENTE", "LATERAL_IZQ", "LATERAL_DER", "TRASERA"]

        # Cantidades por tipo
        rows = (
            FotoVehiculo.objects
            .filter(poliza=poliza, tipo__in=requeridas)
            .values("tipo")
            .annotate(c=Count("id"))
        )
        encontradas = {r["tipo"]: int(r["c"]) for r in rows}
        faltantes = [t for t in requeridas if not encontradas.get(t)]

        payload = {
            "ok": len(faltantes) == 0,
            "requeridas": requeridas,
            "faltantes": faltantes,
            "encontradas": encontradas,
            "total_encontradas": sum(encontradas.values()) if encontradas else 0,
            "poliza_id": poliza.id,
        }
        return Response(payload, status=status.HTTP_200_OK)

    # ---------- Foto de perfil (utilidad) ----------
    @action(detail=True, methods=["post"], url_path="set-foto-perfil")
    def set_foto_perfil(self, request, pk=None):
        """
        Variantes de uso:
        - {"foto_id": 123} → toma url/public_id de esa FotoVehiculo
        - {"url": "...", "public_id": "..."} → setea directo
        - {"clear": true} → limpia
        """
        poliza = self.get_object()
        clear = bool(request.data.get("clear"))
        if clear:
            updates = []
            if hasattr(poliza, "foto_perfil_url"):
                poliza.foto_perfil_url = ""
                updates.append("foto_perfil_url")
            if hasattr(poliza, "foto_perfil_public_id"):
                poliza.foto_perfil_public_id = ""
                updates.append("foto_perfil_public_id")
            if updates:
                poliza.save(update_fields=updates)
            _hist_log(poliza=poliza, tipo="POLIZA_FOTO_PERFIL", mensaje="Foto de perfil limpiada",
                      severidad="ACTION", request=request, subject=poliza, categoria="POLIZA")
            return Response({"ok": True})

        foto_id = request.data.get("foto_id")
        url = (request.data.get("url") or "").strip()
        public_id = (request.data.get("public_id") or "").strip()

        if foto_id:
            try:
                foto = FotoVehiculo.objects.get(id=foto_id, poliza=poliza)
            except FotoVehiculo.DoesNotExist:
                return Response({"detail": "Foto no encontrada para esta póliza."}, status=404)
            url = foto.url
            public_id = foto.public_id or ""

        if not url:
            return Response({"detail": "Debe indicar 'foto_id' o 'url'."}, status=400)

        updates = []
        if hasattr(poliza, "foto_perfil_url"):
            poliza.foto_perfil_url = url
            updates.append("foto_perfil_url")
        if hasattr(poliza, "foto_perfil_public_id"):
            poliza.foto_perfil_public_id = public_id
            updates.append("foto_perfil_public_id")
        if updates:
            poliza.save(update_fields=updates)

        _hist_log(poliza=poliza, tipo="POLIZA_FOTO_PERFIL", mensaje="Foto de perfil actualizada",
                  severidad="ACTION", data={"url": url, "public_id": public_id}, request=request, subject=poliza, categoria="POLIZA")
        return Response({"ok": True, "url": url, "public_id": public_id})

    # ---------- ✅ NUEVO: setear cobertura A SOLO / A+ GRUA ----------
    @action(detail=True, methods=["post"], url_path="set-cobertura-grua", permission_classes=[AllowAny])
    def set_cobertura_grua(self, request, pk=None):
        """
        POST /api/polizas/{id}/set-cobertura-grua
        Body: { "con_grua": true|false }
        Regla:
          - Si la cobertura comienza con 'A':
              con_grua=true  → 'A+ GRUA'
              con_grua=false → 'A SOLO'
          - Para otras coberturas, no modifica.
        """
        poliza = self.get_object()
        raw = request.data.get("con_grua")
        con_grua = str(raw).strip().lower() in {"1", "true", "t", "yes", "y", "si", "sí"}

        antes = (poliza.cobertura or "").strip()
        despues = antes

        if antes.upper().startswith("A"):
            despues = "A+ GRUA" if con_grua else "A SOLO"
            if despues != antes:
                poliza.cobertura = despues
                poliza.save(update_fields=["cobertura"])
                _hist_log(poliza=poliza, tipo="POLIZA_CAMBIAR_COBERTURA",
                          mensaje="Cobertura A/Grúa actualizada",
                          severidad="ACTION",
                          data={"antes": antes, "despues": despues, "con_grua": con_grua},
                          request=request, subject=poliza, categoria="POLIZA")

        return Response({
            "ok": True,
            "poliza_id": poliza.id,
            "con_grua": con_grua,
            "cobertura_antes": antes,
            "cobertura_despues": despues
        }, status=status.HTTP_200_OK)

    # ---------- Envío MASIVO con DIAGNÓSTICO ----------

    @action(detail=False, methods=["post"], url_path="enviar-mensajes-cuotas")
    def enviar_mensajes_cuotas(self, request):
        """
        POST /api/polizas/enviar-mensajes-cuotas/
        Body:
          {
            "filtros": { ... },
            "incluir_diagnostico": true,      # <-- incluye estado de cuotas por póliza
            "solo_reporte": false             # <-- si true, NO envía (solo reporta)
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
        buckets = {"al_dia": 0, "por_vencer": 0, "vence_hoy": 0, "vencida_7": 0, "vencida_30": 0, "vencidas": 0}

        for p in qs.iterator():
            cli = getattr(p, "cliente", None)
            tel_raw = (getattr(cli, "telefono", "") or "").strip()

            # cuotas impagas ordenadas
            impagas_qs = Cuota.objects.filter(poliza=p, pagado=False).order_by("fecha_vencimiento", "cuota_nro", "id")
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
            if ok is True:
                enviados += 1
                _hist_log(poliza=p, tipo="MENSAJE_ENVIO_CUOTAS", mensaje="WhatsApp enviado",
                          severidad="ACTION", data={"telefono": (info.get("to") if isinstance(info, dict) else None) or telefono_e164 or tel_raw,
                          "info": info}, request=request, subject=p, categoria="POLIZA")
            elif ok is False:
                fallidos += 1
                _hist_log(poliza=p, tipo="MENSAJE_ENVIO_CUOTAS_ERROR", mensaje="Error de WhatsApp",
                          severidad="ERROR", data={"telefono": (info.get("to") if isinstance(info, dict) else None) or telefono_e164 or tel_raw,
                          "error": info}, request=request, subject=p, categoria="POLIZA")

            detalle.append({
                "poliza_id": p.id,
                "cliente_id": getattr(cli, "id", None),
                "telefono": (info.get("to") if isinstance(info, dict) else None) or telefono_e164 or tel_raw or None,
                "ok": (None if ok is None else bool(ok)),
                "info": info,
            })

            if incluir_diag:
                diagnostico.append({
                    "poliza_id": p.id,
                    "cliente": {
                        "id": getattr(cli, "id", None),
                        "nombre": getattr(cli, "nombre", ""),
                        "apellido": getattr(cli, "apellido", ""),
                    },
                    "telefono_raw": tel_raw or None,
                    "telefono_e164": (info.get("to") if isinstance(info, dict) else None) or telefono_e164,
                    "estado_cuotas": estado_label,
                    "impagas": cant_impagas,
                    "monto_total": float(monto_total or 0),
                    "primera_vto": (primera_vto.isoformat() if primera_vto else None),
                    "mensaje_preview": (msg[:240] + ("…" if len(msg) > 240 else "")),
                })

        # Truncados para no devolver payload gigante
        if len(detalle) > 100:
            detalle = detalle[:100] + [{"truncated": True, "total_items": len(detalle)}]
        if len(diagnostico) > 100:
            diagnostico = diagnostico[:100] + [{"truncated": True, "total_items": len(diagnostico)}]

        return Response({
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
        }, status=status.HTTP_200_OK)

    # ---------- Envío UNITARIO ----------

    @action(detail=True, methods=["post"], url_path="enviar-mensaje-cuotas")
    def enviar_mensaje_cuotas(self, request, pk=None):
        p = self.get_object()
        cli = getattr(p, "cliente", None)
        tel_raw = (getattr(cli, "telefono", "") or "").strip()
        if not tel_raw:
            return Response({"ok": False, "error": "sin_telefono"}, status=status.HTTP_400_BAD_REQUEST)

        hoy = timezone.localdate()
        impagas = list(Cuota.objects.filter(poliza=p, pagado=False).order_by("fecha_vencimiento", "cuota_nro", "id"))
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

        if ok:
            _hist_log(poliza=p, tipo="MENSAJE_ENVIO_CUOTAS", mensaje="WhatsApp enviado (unitario)",
                      severidad="ACTION", data={"telefono": (info.get("to") if isinstance(info, dict) else tel_raw), "info": info},
                      request=request, subject=p, categoria="POLIZA")
        else:
            _hist_log(poliza=p, tipo="MENSAJE_ENVIO_CUOTAS_ERROR", mensaje="Error WhatsApp (unitario)",
                      severidad="ERROR", data={"telefono": (info.get("to") if isinstance(info, dict) else tel_raw), "error": info},
                      request=request, subject=p, categoria="POLIZA")

        return Response({"ok": bool(ok), "info": info, "diagnostico": diag}, status=200 if ok else 502)


class FotoVehiculoViewSet(viewsets.ModelViewSet):
    queryset = FotoVehiculo.objects.select_related("poliza").all()
    serializer_class = FotoVehiculoSerializer
    permission_classes = [AllowAny]
    filter_backends = [filters.SearchFilter]
    search_fields = ["poliza__numero_poliza", "poliza__patente"]
    pagination_class = LargeResultsSetPagination

    def get_queryset(self):
        qs = super().get_queryset()
        poliza_id = self.request.query_params.get("poliza")
        tipo = self.request.query_params.get("tipo")
        origen = self.request.query_params.get("origen")
        # NUEVO: filtro por etiqueta (tag o etiqueta). Ej.: ?tag=gnc
        tag = (self.request.query_params.get("tag") or self.request.query_params.get("etiqueta") or "").strip()
        if poliza_id:
            qs = qs.filter(poliza_id=poliza_id)
        if tipo:
            qs = qs.filter(tipo=tipo)
        if origen:
            qs = qs.filter(origen=origen)
        if tag:
            # JSONField contiene ese valor en la lista
            qs = qs.filter(etiquetas__contains=[tag])
        return qs

    def perform_create(self, serializer):
        instance = serializer.save()
        _hist_log(poliza=instance.poliza, tipo="FOTO_SUBIR", mensaje=f"Subida foto {instance.tipo}",
                  severidad="INFO", data={"foto_id": instance.id, "tipo": instance.tipo,
                  "origen": instance.origen, "url": instance.url, "public_id": instance.public_id,
                  "etiquetas": instance.etiquetas},
                  request=self.request, subject=instance, categoria="FOTO")

    def perform_destroy(self, instance):
        _hist_log(poliza=instance.poliza, tipo="FOTO_BORRAR", mensaje=f"Eliminada foto {instance.tipo}",
                  severidad="WARNING", data={"foto_id": instance.id, "tipo": instance.tipo,
                  "origen": instance.origen, "url": instance.url, "public_id": instance.public_id,
                  "etiquetas": instance.etiquetas},
                  request=self.request, subject=instance, categoria="FOTO")
        return super().perform_destroy(instance)


class PolizaDocumentoViewSet(viewsets.ModelViewSet):
    queryset = PolizaDocumento.objects.select_related("poliza").all()
    serializer_class = PolizaDocumentoSerializer
    permission_classes = [AllowAny]
    filter_backends = [filters.SearchFilter]
    search_fields = ["poliza__numero_poliza", "poliza__patente"]
    pagination_class = LargeResultsSetPagination

    def get_queryset(self):
        qs = super().get_queryset()
        poliza_id = self.request.query_params.get("poliza")
        tipo = self.request.query_params.get("tipo")
        lado = self.request.query_params.get("lado")  # ← nuevo filtro por lado para cédulas
        if poliza_id:
            qs = qs.filter(poliza_id=poliza_id)
        if tipo:
            qs = qs.filter(tipo=tipo)
        if lado:
            qs = qs.filter(lado=lado)
        return qs

    def perform_create(self, serializer):
        instance = serializer.save()
        _hist_log(poliza=instance.poliza, tipo="DOC_SUBIR", mensaje=f"Subido {instance.tipo}",
                  severidad="INFO", data={"documento_id": instance.id, "tipo": instance.tipo,
                  "nombre": instance.nombre, "mime": instance.mime,
                  "vencimiento": instance.vencimiento.isoformat() if instance.vencimiento else None,
                  "url": instance.url, "public_id": instance.public_id},
                  request=self.request, subject=instance, categoria="DOC")

    def perform_destroy(self, instance):
        _hist_log(poliza=instance.poliza, tipo="DOC_BORRAR", mensaje=f"Eliminado {instance.tipo}",
                  severidad="WARNING", data={"documento_id": instance.id, "tipo": instance.tipo,
                  "nombre": instance.nombre, "url": instance.url, "public_id": instance.public_id},
                  request=self.request, subject=instance, categoria="DOC")
        return super().perform_destroy(instance)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        old_vto = instance.vencimiento
        resp = super().update(request, *args, **kwargs)
        instance.refresh_from_db()
        new_vto = instance.vencimiento
        if old_vto != new_vto:
            _hist_log(poliza=instance.poliza, tipo="DOC_CAMBIAR_VTO", mensaje=f"Cambio de vencimiento en {instance.tipo}",
                      severidad="ACTION", data={"documento_id": instance.id, "tipo": instance.tipo,
                      "antes": old_vto.isoformat() if old_vto else None, "despues": new_vto.isoformat() if new_vto else None,
                      "nombre": instance.nombre}, request=self.request, subject=instance, categoria="DOC")
        return resp

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        old_vto = instance.vencimiento
        resp = super().partial_update(request, *args, **kwargs)
        instance.refresh_from_db()
        new_vto = instance.vencimiento
        if old_vto != new_vto:
            _hist_log(poliza=instance.poliza, tipo="DOC_CAMBIAR_VTO", mensaje=f"Cambio de vencimiento en {instance.tipo}",
                      severidad="ACTION", data={"documento_id": instance.id, "tipo": instance.tipo,
                      "antes": old_vto.isoformat() if old_vto else None, "despues": new_vto.isoformat() if new_vto else None,
                      "nombre": instance.nombre}, request=self.request, subject=instance, categoria="DOC")
        return resp
