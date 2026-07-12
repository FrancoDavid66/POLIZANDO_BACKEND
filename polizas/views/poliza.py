# polizas/views/poliza.py

from rest_framework import viewsets, status, filters
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.generics import get_object_or_404

from django.db.models import (
    Count,
    Q,
    F,
    OuterRef,
    Subquery,
    IntegerField,
    DateField,
    BooleanField,
    Value,
    Max,
    Min,
    Case,
    When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.conf import settings

from seguros_project.pagination import LargeResultsSetPagination

try:
    from seguros_project.pagination import CursorLargeResultsSetPagination
except Exception:
    CursorLargeResultsSetPagination = None

from polizas.models import Poliza, FotoVehiculo
from polizas.serializers import (
    PolizaSerializer,
    PolizaListSerializer,
    PolizaRenovacionListSerializer,
    PolizaVencimientoListSerializer,
)
from polizas.handlers.create_poliza import handle_create_poliza
from pagos.models import Cuota

from polizas.utils.constants import normalizar_compania
from polizas.utils.viewtools import (
    hist_log as _hist_log,
    apply_financial_bucket,
    apply_vencimiento_filters,
    apply_poliza_filters,  
)

from polizas.domain.bool import to_bool as _to_bool
from polizas.domain.oficinas import apply_oficina_filter as _apply_oficina_filter_domain
from polizas.domain.robo import ensure_cupones_robo_for_poliza

# 🚀 IMPORTAMOS NUESTRO MIXIN DE SEGURIDAD
from usuarios.mixins import MultiTenantMixin

# Mixins
from .mixins import (
    PolizaCatalogosMixin,
    PolizaExportsMixin,
    PolizaVencimientosMixin,
    PolizaRenovacionesMixin,
    PolizaDuplicadosMixin,
    PolizaKpisMixin,
    PolizaDiagnosticoMixin,  # 🩺 NUEVO
)

# ==========================================
# 🚀 AUTO-ACTUALIZADOR DE ESTADOS 
# ==========================================
import unicodedata


def _normaliza_txt(s):
    """minúsculas y sin tildes, para comparar nombres de compañía"""
    return unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode("ascii").strip().lower()


def auto_marcar_vencidas():
    """
    Actualiza el estado de las pólizas según su ÚLTIMA cuota:

    - Última cuota vence en el futuro          → ACTIVA  (no tocar)
    - Última cuota venció + NO pagada          → VENCIDA
    - Todas las cuotas pagas + última venció   → FINALIZADA

    Lógica: mira solo la cuota con fecha_vencimiento más alta (la más reciente).
    Si esa cuota ya pasó y no está pagada → en mora.
    Si todas están pagas y la última ya pasó → ciclo completado → finalizada.
    """
    hoy = timezone.localdate()

    # Subqueries sobre la última cuota de cada póliza
    ultima_vto = Cuota.objects.filter(
        poliza=OuterRef("pk")
    ).order_by("-fecha_vencimiento").values("fecha_vencimiento")[:1]

    ultima_pagada = Cuota.objects.filter(
        poliza=OuterRef("pk")
    ).order_by("-fecha_vencimiento").values("pagado")[:1]

    # ¿Existe alguna cuota impaga? (para detectar finalizada vs vencida)
    tiene_impaga = Cuota.objects.filter(
        poliza=OuterRef("pk"),
        pagado=False,
    ).values("id")[:1]

    qs_activas = Poliza.objects.filter(
        estado__iexact="activa"
    ).annotate(
        ult_vto=Subquery(ultima_vto, output_field=DateField()),
        ult_pagada=Subquery(ultima_pagada, output_field=BooleanField()),
        hay_impaga=Subquery(tiene_impaga, output_field=IntegerField()),
    )

    # 1. FINALIZADA: última cuota venció + todas pagas (no hay ninguna impaga)
    qs_activas.filter(
        ult_vto__lt=hoy,
        ult_pagada=True,
        hay_impaga__isnull=True,   # no existe ninguna cuota impaga
    ).update(estado="finalizada")

    # 2. VENCIDA: última cuota venció + no está pagada
    qs_activas.filter(
        ult_vto__lt=hoy,
        ult_pagada=False,
    ).update(estado="vencida")


class PolizaViewSet(
    MultiTenantMixin,  # 🚀 INYECTAMOS EL FILTRO MAESTRO AQUÍ (siempre primero)
    PolizaCatalogosMixin,
    PolizaExportsMixin,
    PolizaVencimientosMixin,
    PolizaRenovacionesMixin,
    PolizaDuplicadosMixin,
    PolizaKpisMixin,
    PolizaDiagnosticoMixin,  # 🩺 NUEVO
    viewsets.ModelViewSet,
):
    queryset = Poliza.objects.all()
    serializer_class = PolizaSerializer
    
    # 🚀 BLOQUEAMOS EL ACCESO LIBRE (Solo usuarios logueados)
    permission_classes = [IsAuthenticated]

    filter_backends = [filters.SearchFilter, filters.OrderingFilter]

    search_fields = [
        "patente",
        "marca",
        "modelo",
        "cliente__nombre",
        "cliente__apellido",
        "cliente__dni_cuit_cuil",
        "numero_poliza",
        "compania",
        "compania_obj__nombre", # 🚀 SOPORTE NUEVO MODELO
    ]

    ordering_fields = [
        "id",
        "fecha_emision",
        "fecha_vencimiento",
        "patente",
        "compania",
        "estado",
        "fase",
        "numero_poliza",
        "vto_referencia",  
        "ultima_cuota_vencimiento", 
        "dias_para_vencer_poliza",
    ]
    ordering = ["-id"]

    # Default (count). En list() podemos switchear a Cursor para performance.
    pagination_class = LargeResultsSetPagination
    lookup_value_regex = r"\d+"

    def get_search_fields(self, view=None):
        base = list(getattr(self, "search_fields", []) or [])
        try:
            f = Poliza._meta.get_field("oficina")
            internal = getattr(f, "get_internal_type", lambda: "")()
            if internal in {"ForeignKey", "OneToOneField"}:
                return base + ["oficina__nombre", "oficina__name"]
            return base + ["oficina"]
        except Exception:
            return base

    def get_serializer_class(self):
        if getattr(self, "action", "") in {"list", "versiones_por_patente"}:
            return PolizaListSerializer
        if getattr(self, "action", "") in {"renovaciones"}:
            return PolizaRenovacionListSerializer
        if getattr(self, "action", "") in {"vencimientos"}:
            return PolizaVencimientoListSerializer
        return PolizaSerializer

    def _hist_log(self, **kwargs):
        return _hist_log(**kwargs)

    def _apply_oficina_filter(self, qs, oficina_raw: str):
        return _apply_oficina_filter_domain(qs, Poliza, oficina_raw, field_name="oficina")

    def list(self, request, *args, **kwargs):
        # 🚀 LANZAMOS EL ACTUALIZADOR JUSTO ANTES DE CARGAR LA TABLA
        auto_marcar_vencidas()

        params = request.query_params

        raw_cursor = (params.get("cursor") or "").strip()
        raw_use_cursor = (params.get("use_cursor") or params.get("cursor_mode") or "").strip()

        cursor_is_token = bool(raw_cursor) and (not _to_bool(raw_cursor))
        cursor_toggle = _to_bool(raw_cursor) or _to_bool(raw_use_cursor)

        use_cursor = (CursorLargeResultsSetPagination is not None) and (cursor_is_token or cursor_toggle)

        if use_cursor and cursor_toggle and (not cursor_is_token):
            try:
                qd = request._request.GET.copy()
                if "cursor" in qd:
                    qd.pop("cursor")
                request._request.GET = qd
            except Exception:
                pass

        if use_cursor:
            self.pagination_class = CursorLargeResultsSetPagination

        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        if page is not None:
            ser = self.get_serializer(page, many=True)
            return self.get_paginated_response(ser.data)
        ser = self.get_serializer(qs, many=True)
        return Response(ser.data, status=status.HTTP_200_OK)

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        action = getattr(self, "action", "")

        include_finalizadas = _to_bool(params.get("include_finalizadas") or params.get("incluir_finalizadas"))
        if action in {"vencimientos", "vencimientos_resumen", "renovaciones", "renovaciones_resumen"} and not include_finalizadas:
            qs = qs.exclude(estado__iexact="finalizada")

        # ========== Guard: si es LIST y NO hay filtros => no traer el universo ==========
        if action == "list":
            allow_all = _to_bool(params.get("allow_all") or params.get("traer_todo"))
            has_search = bool((params.get("search") or "").strip())
            has_filters = any(
                (params.get(k) or "").strip()
                for k in [
                    "estado",
                    "estado_financiero",
                    "compania",
                    "cliente",
                    "patente",
                    "solo_activas",
                    "fase",
                    "sin_numero",
                    "oficina",
                    "asegurado",
                    "asegurado_nombre",
                    "fecha_vencimiento_desde",
                    "fecha_vencimiento_hasta",
                    "vencidas_ultimos_dias",
                    "vencidas_mas_de_dias",
                ]
            )
            if (not allow_all) and (not has_search) and (not has_filters):
                return qs.none()

        if action in {"list", "versiones_por_patente", "renovaciones", "vencimientos", "vencimientos_resumen"}:
            qs = qs.select_related("cliente", "compania_obj")

            impagas_count_sq = (
                Cuota.objects.filter(poliza_id=OuterRef("pk"), pagado=False)
                .values("poliza_id")
                .annotate(c=Count("id"))
                .values("c")[:1]
            )

            # 🎯 Cobertura vigente = vto de la ÚLTIMA cuota PAGADA (hasta cuándo está cubierto).
            #    Como las cuotas se pagan por adelantado, esa fecha es TAMBIÉN la fecha
            #    límite en que tiene que pagar la próxima cuota.
            cobertura_hasta_sq = (
                Cuota.objects.filter(poliza_id=OuterRef("pk"), pagado=True)
                .exclude(fecha_vencimiento__isnull=True)
                .order_by("-fecha_vencimiento")
                .values("fecha_vencimiento")[:1]
            )

            # Si NUNCA pagó nada, la fecha límite es el vto de su primera cuota impaga.
            primer_vto_impaga_sq = (
                Cuota.objects.filter(poliza_id=OuterRef("pk"), pagado=False)
                .exclude(fecha_vencimiento__isnull=True)
                .order_by("fecha_vencimiento")
                .values("fecha_vencimiento")[:1]
            )

            qs = qs.annotate(
                impagas_count=Coalesce(Subquery(impagas_count_sq, output_field=IntegerField()), Value(0)),
            ).annotate(
                # proxima_vencimiento_impaga = FECHA LÍMITE DE PAGO (no el vto propio de la cuota):
                # hasta cuándo llega la cobertura ya pagada. Si esa fecha ya pasó y hay impagas => mora.
                # Queda en null si no hay cuotas impagas (para no cambiar el resto del comportamiento).
                proxima_vencimiento_impaga=Case(
                    When(impagas_count=0, then=Value(None, output_field=DateField())),
                    default=Coalesce(
                        Subquery(cobertura_hasta_sq, output_field=DateField()),
                        Subquery(primer_vto_impaga_sq, output_field=DateField()),
                    ),
                    output_field=DateField(),
                ),
            )

        if action == "retrieve":
            qs = qs.select_related("cliente", "compania_obj", "cobertura_obj").prefetch_related(
                "cuotas",
                "pagos",
                "fotos_vehiculo",
                "documentos",
                "cupones_robo",
            )

        estado = (params.get("estado") or "").strip()
        compania = (params.get("compania") or "").strip()
        cliente_id = (params.get("cliente") or "").strip()
        patente = (params.get("patente") or "").strip()
        solo_activas = (params.get("solo_activas") or "").lower() in {"1", "true", "t", "yes", "y"}
        fase = (params.get("fase") or "").strip()
        sin_numero = (params.get("sin_numero") or "").lower() in {"1", "true", "t", "yes", "y"}

        asegurado_q = (params.get("asegurado") or params.get("asegurado_nombre") or "").strip()
        if asegurado_q:
            tokens = [t for t in asegurado_q.split() if t]
            for t in tokens:
                qs = qs.filter(Q(cliente__nombre__icontains=t) | Q(cliente__apellido__icontains=t))

        if estado:
            qs = qs.filter(estado=estado)

        if compania:
            objetivo = _normaliza_txt(compania)
            try:
                objetivo = _normaliza_txt(normalizar_compania(compania)) or objetivo
            except Exception:
                pass
            if objetivo:
                ids = [
                    p.pk
                    for p in qs.select_related("compania_obj")
                    if objetivo in _normaliza_txt(getattr(p, "compania", ""))
                    or objetivo in _normaliza_txt(getattr(getattr(p, "compania_obj", None), "nombre", ""))
                ]
                qs = qs.filter(pk__in=ids)

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

    def get_object(self):
        """
        🛡️ BLINDAJE PARA DETALLE / EDICIÓN / BORRADO DE UNA PÓLIZA PUNTUAL

        get_queryset() aplica los filtros del LISTADO (estado, vencimiento,
        financiero, compañía, etc.). Si el front llega a /polizas/<id>/ con
        alguno de esos parámetros colgado en la URL, la póliza puede quedar
        fuera del queryset y DRF devuelve 404 aunque la póliza exista
        (caso típico: intentar borrar una póliza estando parado en un filtro
        como "vencidas", o con un ?oficina= residual del listado).

        Para retrieve / update / partial_update / destroy usamos SOLO el
        escudo multi-tenant (oficina) del MultiTenantMixin, sin los filtros
        operativos del listado. Mismo patrón que ya usan las verificaciones.
        """
        if getattr(self, "action", None) in {"retrieve", "update", "partial_update", "destroy"}:
            qs = MultiTenantMixin.get_queryset(self)
            lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
            obj = get_object_or_404(qs, **{self.lookup_field: self.kwargs[lookup_url_kwarg]})
            self.check_object_permissions(self.request, obj)
            return obj
        return super().get_object()

    def create(self, request, *args, **kwargs):
        """
        🚀 ASIGNACIÓN DE OFICINA EN CREACIÓN
        """
        user = self.request.user
        es_admin = user.is_superuser or (hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN')
        
        data = request.data.copy()
        target_oficina = data.get('oficina')

        # Blindaje: Si no es admin o no mandó oficina, inyectamos la suya
        if not es_admin or not target_oficina:
            if hasattr(user, 'perfil') and user.perfil.oficina:
                data['oficina'] = user.perfil.oficina.id

        try:
            serializer = self.get_serializer(data=data)
            serializer.is_valid(raise_exception=True)
            poliza = handle_create_poliza(serializer)

            try:
                ensure_cupones_robo_for_poliza(poliza)
            except Exception:
                pass

            _hist_log(
                poliza=poliza,
                tipo="POLIZA_CREAR",
                mensaje="Póliza creada",
                severidad="ACTION",
                request=request,
                subject=poliza,
                categoria="POLIZA",
            )
            return Response(self.get_serializer(poliza).data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response(
                {"error": "Error al crear la póliza", "detalle": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def destroy(self, request, *args, **kwargs):
        """
        🚀 ELIMINACIÓN RESTRINGIDA
        """
        user = self.request.user
        es_admin = user.is_superuser or (hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN')
        
        if not es_admin:
            return Response(
                {"error": "Solo un administrador puede eliminar pólizas del sistema."}, 
                status=status.HTTP_403_FORBIDDEN
            )
            
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["get"], url_path="cuotas", permission_classes=[IsAuthenticated])
    def listar_cuotas(self, request, pk=None):
        poliza = self.get_object()
        qs = Cuota.objects.filter(poliza=poliza).order_by("cuota_nro", "fecha_vencimiento", "id")
        data = [
            {
                "id": c.id,
                "cuota_nro": c.cuota_nro,
                "fecha_vencimiento": c.fecha_vencimiento,
                "pagado": bool(c.pagado),
                "fecha_pago": getattr(c, "fecha_pago", None),
                "monto": getattr(c, "monto", None),
            }
            for c in qs
        ]
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="versiones-por-patente", permission_classes=[IsAuthenticated])
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

    @action(detail=True, methods=["get"], url_path="requisitos-fotos", permission_classes=[IsAuthenticated])
    def requisitos_fotos(self, request, pk=None):
        poliza = self.get_object()
        requeridas = ["FRENTE", "LATERAL_IZQ", "LATERAL_DER", "TRASERA"]

        rows = FotoVehiculo.objects.filter(poliza=poliza, tipo__in=requeridas).values("tipo").annotate(c=Count("id"))
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

    @action(detail=True, methods=["post"], url_path="set-foto-perfil")
    def set_foto_perfil(self, request, pk=None):
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
            _hist_log(
                poliza=poliza,
                tipo="POLIZA_FOTO_PERFIL",
                mensaje="Foto de perfil limpiada",
                severidad="ACTION",
                request=request,
                subject=poliza,
                categoria="POLIZA",
            )
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

        _hist_log(
            poliza=poliza,
            tipo="POLIZA_FOTO_PERFIL",
            mensaje="Foto de perfil actualizada",
            severidad="ACTION",
            data={"url": url, "public_id": public_id},
            request=self.request,
            subject=poliza,
            categoria="POLIZA",
        )
        return Response({"ok": True, "url": url, "public_id": public_id})

    @action(detail=True, methods=["post"], url_path="set-cobertura-grua", permission_classes=[IsAuthenticated])
    def set_cobertura_grua(self, request, pk=None):
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
                _hist_log(
                    poliza=poliza,
                    tipo="POLIZA_CAMBIAR_COBERTURA",
                    mensaje="Cobertura A/Grúa actualizada",
                    severidad="ACTION",
                    data={"antes": antes, "despues": despues, "con_grua": con_grua},
                    request=request,
                    subject=poliza,
                    categoria="POLIZA",
                )

        return Response(
            {
                "ok": True,
                "poliza_id": poliza.id,
                "con_grua": con_grua,
                "cobertura_antes": antes,
                "cobertura_despues": despues,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="enviar-postventa", permission_classes=[IsAuthenticated])
    def enviar_postventa(self, request, pk=None):
        poliza = self.get_object()
        cliente = poliza.cliente

        if not cliente:
            return Response({"error": "La póliza no tiene cliente asignado"}, status=status.HTTP_400_BAD_REQUEST)

        numero = getattr(cliente, "whatsapp", "") or getattr(cliente, "telefono", "") or getattr(cliente, "celular", "")
        if not numero:
            return Response({"error": "El cliente no tiene teléfono cargado"}, status=status.HTTP_400_BAD_REQUEST)

        nombre = getattr(cliente, "nombre", "Cliente").strip()
        marca = getattr(poliza, "marca", "").strip()
        modelo = getattr(poliza, "modelo", "").strip()
        vehiculo = f"{marca} {modelo}".strip() or "tu vehículo"

        mensaje = (
            f"¡Hola {nombre}! 👋 Te escribimos de {settings.EMAIL_REMITENTE_NOMBRE}.\n\n"
            f"Pasaron unos días desde que aseguraste {vehiculo} con nosotros y queríamos "
            f"saber si recibiste bien tu póliza y si tenés alguna duda.\n\n"
            f"Estamos a tu disposición para lo que necesites. ¡Que tengas un excelente día!"
        )

        from polizas.utils.mensajeria import enviar_whatsapp

        try:
            ok, info = enviar_whatsapp(numero, mensaje, oficina=poliza.oficina)
            if ok:
                _hist_log(
                    poliza=poliza,
                    tipo="MENSAJE_POSTVENTA",
                    mensaje="Mensaje de Post-Venta enviado",
                    severidad="INFO",
                    data={"telefono": numero, "info": info},
                    request=request,
                    subject=poliza,
                    categoria="POLIZA",
                )
                return Response({"ok": True, "mensaje": "Post-Venta enviado correctamente"})
            else:
                return Response({"error": "Fallo el envío por WhatsApp", "detalle": info}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # ── Marcar póliza como No renueva ─────────────────────────────────────────
    @action(detail=True, methods=["post"], url_path="marcar-no-renueva", permission_classes=[IsAuthenticated])
    def marcar_no_renueva(self, request, pk=None):
        """
        POST /api/polizas/:id/marcar-no-renueva/
        Marca la póliza como NO_RENUEVA y la saca de la lista de renovaciones.
        """
        poliza = self.get_object()
        motivo = (request.data.get("motivo") or "").strip()

        # Cancelar la póliza — estado válido en el modelo
        poliza.estado = "cancelada"
        update_fields = ["estado"]

        # Guardar motivo en observaciones_baja si existe el campo
        motivo_guardado = f"No renueva{f': {motivo}' if motivo else ''}"
        for campo in ["observaciones_baja", "observaciones", "notas"]:
            if hasattr(poliza, campo):
                obs_actual = str(getattr(poliza, campo) or "").strip()
                nuevo = motivo_guardado
                if obs_actual:
                    nuevo = f"{nuevo} | {obs_actual}"
                setattr(poliza, campo, nuevo)
                update_fields.append(campo)
                break

        poliza.save(update_fields=update_fields)

        _hist_log(
            poliza=poliza,
            tipo="POLIZA_NO_RENUEVA",
            mensaje=f"Póliza marcada como No renueva (cancelada){f': {motivo}' if motivo else ''}",
            severidad="ACTION",
            data={"motivo": motivo},
            request=request,
            subject=poliza,
            categoria="POLIZA",
        )

        return Response(
            {
                "ok": True,
                "poliza_id": poliza.id,
                "estado": poliza.estado,
                "mensaje": f"Póliza {poliza.id} marcada como No renueva.",
            },
            status=status.HTTP_200_OK,
        )
    # ══════════════════════════════════════════════════════════════════════
    # 📅 CONTROL DE FECHAS — Emisión = Vencimiento de la 1ª cuota
    # ══════════════════════════════════════════════════════════════════════
    @action(detail=False, methods=["get"], url_path="control-fechas/emision-vto1", permission_classes=[IsAuthenticated])
    def control_fechas_emision_vto1(self, request):
        """
        GET /api/polizas/control-fechas/emision-vto1/

        Lista las pólizas donde la FECHA DE EMISIÓN coincide EXACTAMENTE con el
        vencimiento de su PRIMERA cuota (la de menor cuota_nro). Es decir: pólizas
        que se dieron de alta el mismo día que vence su 1ª cuota → cobertura de
        0 días en esa cuota, que casi siempre es un error de carga.

        Respeta el escudo de oficina (MultiTenantMixin). Acepta:
          - ?oficina=<id|nombre|csv>
          - ?page, ?page_size
        """
        # Base: SOLO el escudo de oficina. No usamos self.get_queryset() para no
        # heredar filtros de ?estado= u otros parámetros de la tabla principal.
        qs = MultiTenantMixin.get_queryset(self).select_related("cliente", "oficina")

        oficina_raw = (request.query_params.get("oficina") or "").strip()
        if oficina_raw and oficina_raw.upper() != "ALL":
            qs = self._apply_oficina_filter(qs, oficina_raw)

        # 🚀 Solo pólizas ACTIVAS: las finalizadas/canceladas/vencidas ya no impactan.
        qs = qs.filter(estado__iexact="activa")

        # Vencimiento de la PRIMERA cuota de cada póliza (cuota_nro más bajo)
        primera_vto = (
            Cuota.objects.filter(poliza=OuterRef("pk"))
            .order_by("cuota_nro", "fecha_vencimiento")
            .values("fecha_vencimiento")[:1]
        )

        qs = (
            qs.annotate(_vto1=Subquery(primera_vto, output_field=DateField()))
            .filter(_vto1__isnull=False, fecha_emision=F("_vto1"))
            .order_by("-fecha_emision", "-id")
        )

        # Paginación simple
        try:
            page = int((request.query_params.get("page") or "1").strip() or 1)
        except Exception:
            page = 1
        try:
            page_size = int((request.query_params.get("page_size") or "25").strip() or 25)
        except Exception:
            page_size = 25
        page = max(1, page)
        page_size = max(1, min(200, page_size))

        total = qs.count()
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, total_pages)
        start = (page - 1) * page_size
        rows_qs = qs[start:start + page_size]

        resultados = []
        for p in rows_qs:
            cli = getattr(p, "cliente", None)
            nombre = (
                f"{getattr(cli, 'apellido', '') or ''} {getattr(cli, 'nombre', '') or ''}".strip()
                if cli else ""
            )
            resultados.append({
                "id": p.id,
                "numero_poliza": p.numero_poliza or "",
                "patente": p.patente or "",
                "compania": p.compania or "",
                "estado": p.estado or "",
                "oficina": getattr(p, "oficina_id", None),
                "oficina_nombre": getattr(getattr(p, "oficina", None), "nombre", "") or "",
                "cliente": nombre or "—",
                "cliente_dni": str(getattr(cli, "dni_cuit_cuil", "") or "") if cli else "",
                "fecha_emision": p.fecha_emision.isoformat() if p.fecha_emision else None,
                "vto_primera_cuota": p._vto1.isoformat() if getattr(p, "_vto1", None) else None,
            })

        return Response(
            {
                "count": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "next": page + 1 if page < total_pages else None,
                "previous": page - 1 if page > 1 else None,
                "results": resultados,
            },
            status=status.HTTP_200_OK,
        )

    # ══════════════════════════════════════════════════════════════════════
    # 🏢 VERIFICACIÓN CON LA COMPAÑÍA (bandeja manual)
    # ══════════════════════════════════════════════════════════════════════
    @action(detail=False, methods=["get"], url_path="verificacion-compania", permission_classes=[IsAuthenticated])
    def verificacion_compania_listado(self, request):
        """
        GET /api/polizas/verificacion-compania/?estado=pendiente|ok|no_figura
        Lista las pólizas para la bandeja de verificación con la compañía.
        Muestra TODAS las pólizas sin verificar (estén al día o no);
        'al_dia' se devuelve como bandera informativa para la UI.
        Respeta el escudo de oficina (get_queryset ya lo aplica vía MultiTenantMixin).
        """
        from pagos.models import Cuota

        estado = (request.query_params.get("estado") or "pendiente").strip().lower()
        hoy = timezone.localdate()

        # Base: SOLO el escudo de oficina del MultiTenantMixin.
        # 🔧 FIX: NO usamos self.get_queryset() porque ese lee el parámetro
        # ?estado= y lo interpreta como el estado de la póliza
        # (filtra estado="pendiente" → 0 resultados). El MultiTenantMixin
        # solo respeta el alcance por oficina, que es lo que queremos acá.
        qs = MultiTenantMixin.get_queryset(self).select_related("cliente", "oficina")

        # Excluir pólizas dadas de baja / canceladas / anuladas
        qs = qs.exclude(estado__in=["cancelada", "anulada", "baja", "finalizada"])

        # Filtro por estado de verificación
        if estado == "ok":
            qs = qs.filter(verificacion_compania="OK")
        elif estado in ("no_figura", "nofigura"):
            qs = qs.filter(verificacion_compania="NO_FIGURA")
        else:  # pendiente (sin verificar)
            qs = qs.filter(verificacion_compania="")

        # IDs de pólizas con mora REAL → NO están al día.
        # Mora = la cobertura (vto de la última cuota PAGADA) ya venció y quedan cuotas impagas.
        # Si nunca pagó nada, la mora arranca en el vto de su primera cuota impaga.
        polizas_con_mora = set(
            Poliza.objects.annotate(
                _cobertura=Max("cuotas__fecha_vencimiento", filter=Q(cuotas__pagado=True)),
                _impagas=Count("cuotas", filter=Q(cuotas__pagado=False)),
                _primer_impaga=Min("cuotas__fecha_vencimiento", filter=Q(cuotas__pagado=False)),
            )
            .filter(_impagas__gt=0)
            .filter(Q(_cobertura__lt=hoy) | Q(_cobertura__isnull=True, _primer_impaga__lt=hoy))
            .values_list("id", flat=True)
        )

        resultados = []
        for p in qs.order_by("-fecha_emision", "-id"):
            al_dia = p.id not in polizas_con_mora
            # 🔧 FIX: ya NO se ocultan las pólizas con cuotas atrasadas.
            # Antes esto vaciaba la bandeja porque las altas nuevas suelen
            # tener la 1ª cuota impaga. 'al_dia' queda solo como bandera visual.

            cli = getattr(p, "cliente", None)
            resultados.append({
                "id": p.id,
                "numero_poliza": p.numero_poliza or "",
                "patente": p.patente or "",
                "compania": p.compania or "",
                "marca": p.marca or "",
                "modelo": p.modelo or "",
                "cliente": (
                    f"{getattr(cli, 'apellido', '') or ''} {getattr(cli, 'nombre', '') or ''}".strip()
                    if cli else ""
                ),
                "oficina_nombre": getattr(getattr(p, "oficina", None), "nombre", "") or "",
                "al_dia": al_dia,
                "verificacion_compania": p.verificacion_compania or "",
                "fecha_emision": p.fecha_emision.isoformat() if p.fecha_emision else None,
            })

        return Response(
            {"estado": estado, "total": len(resultados), "resultados": resultados},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="marcar-verificacion-compania", permission_classes=[IsAuthenticated])
    def marcar_verificacion_compania(self, request, pk=None):
        """
        POST /api/polizas/:id/marcar-verificacion-compania/
        Body: { "estado": "OK" | "NO_FIGURA" | "" }
          - "OK"        → verificada en la compañía
          - "NO_FIGURA" → no figura / datos no coinciden (bandera roja)
          - ""          → revertir a "sin verificar" (vuelve a la pila)
        """
        poliza = self.get_object()
        nuevo = (request.data.get("estado") or "").strip().upper()

        if nuevo not in ("OK", "NO_FIGURA", ""):
            return Response(
                {"detail": "estado inválido. Use 'OK', 'NO_FIGURA' o '' (revertir)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        poliza.verificacion_compania = nuevo
        poliza.verificacion_compania_en = timezone.now() if nuevo else None
        poliza.save(update_fields=["verificacion_compania", "verificacion_compania_en"])

        return Response(
            {
                "ok": True,
                "poliza_id": poliza.id,
                "verificacion_compania": poliza.verificacion_compania,
            },
            status=status.HTTP_200_OK,
        )