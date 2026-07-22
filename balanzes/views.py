# balanzes/views.py
from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Sum, Count, Q
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.dateparse import parse_date

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from seguros_project.pagination import LargeResultsSetPagination

from .models import Ingreso, Egreso, Categoria
from .serializers import IngresoSerializer, EgresoSerializer, CategoriaSerializer
from notificaciones.services_balanzes import enviar_balance_por_whatsapp
from usuarios.mixins import MultiTenantMixin

# 🚀 IMPORTAMOS EL MODELO OFICIAL DE OFICINAS
from usuarios.models import Oficina

def _d_to_str(v):
    if v is None: return "0"
    try: return str(v)
    except Exception: return "0"

# ==========================================
# 🚀 HELPER OPTIMIZADO (Devuelve IDs reales)
# ==========================================
def _get_todas_las_llaves_oficina(raw_or_obj):
    keys = []
    
    if isinstance(raw_or_obj, str) and raw_or_obj.strip().upper() == "ALL":
        return list(Oficina.objects.values_list('id', flat=True))

    if hasattr(raw_or_obj, 'id') and raw_or_obj.id:
        keys.append(raw_or_obj.id)
        
    if isinstance(raw_or_obj, str) and raw_or_obj.strip():
        val = raw_or_obj.strip()
        if val.isdigit():
            ofi = Oficina.objects.filter(Q(codigo=val) | Q(id=val)).first()
        else:
            ofi = Oficina.objects.filter(nombre__icontains=val).first()
        if ofi:
            keys.append(ofi.id)
            
    return list(set(k for k in keys if k))


# ==========================================
# 🚀 HELPERS DE EXPORT (compartidos por Ingresos y Egresos)
# ==========================================
def _parse_ymd(s):
    if not s:
        return None
    return parse_date(str(s).strip())


class CategoriaViewSet(viewsets.ModelViewSet):
    queryset = Categoria.objects.all()
    serializer_class = CategoriaSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        tipo = self.request.query_params.get('tipo')
        if tipo:
            qs = qs.filter(tipo__in=[tipo.upper(), "AMBOS"])
        return qs

class IngresoViewSet(MultiTenantMixin, viewsets.ModelViewSet):
    queryset = Ingreso.objects.all().order_by("-fecha", "-id")
    serializer_class = IngresoSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = LargeResultsSetPagination

    def get_queryset(self):
        user = self.request.user
        es_admin = user.is_superuser or (hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN')

        qs = Ingreso.objects.all().order_by("-fecha", "-id")

        # ── Filtro de oficina ────────────────────────────────────────
        if es_admin:
            oficina_param = self.request.query_params.get('oficina')
            if oficina_param and str(oficina_param).upper() not in ["ALL", ""]:
                keys = _get_todas_las_llaves_oficina(oficina_param)
                qs = qs.filter(oficina_id__in=keys)
        elif hasattr(user, 'perfil') and user.perfil.oficina:
            keys = _get_todas_las_llaves_oficina(user.perfil.oficina)
            qs = qs.filter(oficina_id__in=keys)
        else:
            return Ingreso.objects.none()

        # ── Filtros de historial ─────────────────────────────────────
        desde = self.request.query_params.get('fecha__gte')
        hasta  = self.request.query_params.get('fecha__lte')
        forma  = self.request.query_params.get('forma_pago')
        q      = self.request.query_params.get('search')

        if desde:
            qs = qs.filter(fecha__gte=desde)
        if hasta:
            qs = qs.filter(fecha__lte=hasta)
        if forma and forma.lower() not in ('todas', ''):
            qs = qs.filter(forma_pago__iexact=forma)
        if q:
            qs = qs.filter(
                Q(descripcion__icontains=q) |
                Q(pagado_por__icontains=q) |
                Q(categoria__icontains=q)
            )

        return qs

    def perform_create(self, serializer):
        user = self.request.user
        es_admin = user.is_superuser or (hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN')
        if not es_admin and hasattr(user, 'perfil') and user.perfil.oficina:
            serializer.save(usuario=user, oficina=user.perfil.oficina)
        else:
            serializer.save(usuario=user)

    @action(detail=True, methods=["patch"], url_path="verificar")
    def verificar(self, request, pk=None):
        """
        PATCH /api/balanzes/ingresos/{id}/verificar/
        Marca una transferencia como verificada o no verificada.
        Body: { "verificada": true/false, "nota_verificacion": "..." }
        """
        ingreso = self.get_object()
        verificada = request.data.get("verificada", True)
        nota = request.data.get("nota_verificacion", "")

        if verificada:
            ingreso.verificada = True
            ingreso.verificada_por = request.user
            ingreso.verificada_en = timezone.now()
            ingreso.nota_verificacion = nota or ""
        else:
            # Desmarcar
            ingreso.verificada = False
            ingreso.verificada_por = None
            ingreso.verificada_en = None
            ingreso.nota_verificacion = ""

        ingreso.save(update_fields=["verificada", "verificada_por", "verificada_en", "nota_verificacion"])
        from .serializers import IngresoSerializer
        return Response(IngresoSerializer(ingreso).data)

    @action(detail=False, methods=["get"], url_path="transferencias")
    def transferencias(self, request):
        """
        GET /api/balanzes/ingresos/transferencias/
        Lista solo las transferencias (forma_pago != EFECTIVO) con filtros.
        """
        qs = self.get_queryset().exclude(forma_pago="EFECTIVO").exclude(forma_pago__isnull=True)

        verificada = request.query_params.get("verificada")
        if verificada == "true":
            qs = qs.filter(verificada=True)
        elif verificada == "false":
            qs = qs.filter(verificada=False)

        page = self.paginate_queryset(qs)
        if page is not None:
            from .serializers import IngresoSerializer
            return self.get_paginated_response(IngresoSerializer(page, many=True).data)
        from .serializers import IngresoSerializer
        return Response(IngresoSerializer(qs, many=True).data)

    # ============================================================
    # 🚀 HISTORIAL (lista JSON paginada)
    # ============================================================
    @action(detail=False, methods=["get"], url_path="historial")
    def historial(self, request):
        """
        GET /api/balanzes/ingresos/historial/
        Params:
          desde, hasta (YYYY-MM-DD)
          oficina (id, "ALL" o vacío)
          forma_pago ("EFECTIVO", "TRANSFERENCIA", "TODAS")
          search
          page, page_size
          export = "xlsx" | "pdf" (si está, ignora paginación y devuelve archivo)
          all = 1 (sin paginar, devuelve hasta 50k items)
        """
        user = request.user
        es_admin = user.is_superuser or (hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN')

        qs = Ingreso.objects.all().select_related("oficina", "usuario").order_by("-fecha", "-id")

        if es_admin:
            oficina_param = request.query_params.get('oficina')
            if oficina_param and str(oficina_param).upper() not in ["ALL", ""]:
                keys = _get_todas_las_llaves_oficina(oficina_param)
                qs = qs.filter(oficina_id__in=keys)
        elif hasattr(user, 'perfil') and user.perfil.oficina:
            keys = _get_todas_las_llaves_oficina(user.perfil.oficina)
            qs = qs.filter(oficina_id__in=keys)
        else:
            qs = Ingreso.objects.none()

        desde_raw = request.query_params.get('desde') or request.query_params.get('fecha__gte')
        hasta_raw = request.query_params.get('hasta') or request.query_params.get('fecha__lte')
        forma = request.query_params.get('forma_pago')
        q = request.query_params.get('search') or request.query_params.get('q')

        d_desde = _parse_ymd(desde_raw) if desde_raw else None
        d_hasta = _parse_ymd(hasta_raw) if hasta_raw else None

        if d_desde:
            qs = qs.filter(fecha__gte=d_desde)
        if d_hasta:
            qs = qs.filter(fecha__lte=d_hasta)
        if forma and forma.lower() not in ('todas', ''):
            qs = qs.filter(forma_pago__iexact=forma)
        if q:
            qs = qs.filter(
                Q(descripcion__icontains=q) |
                Q(pagado_por__icontains=q) |
                Q(categoria__icontains=q) |
                Q(billetera__icontains=q)
            )

        # Respuesta JSON normal con paginación
        all_flag = str(request.query_params.get('all') or '').strip().lower() in ("1", "true", "yes", "y")
        if all_flag:
            items = list(qs[:50000])
            from .serializers import IngresoSerializer
            ser = IngresoSerializer(items, many=True)
            return Response({"count": len(items), "results": ser.data, "all": True}, status=200)

        page = self.paginate_queryset(qs)
        if page is not None:
            from .serializers import IngresoSerializer
            return self.get_paginated_response(IngresoSerializer(page, many=True).data)

        from .serializers import IngresoSerializer
        return Response(IngresoSerializer(qs, many=True).data)



class EgresoViewSet(MultiTenantMixin, viewsets.ModelViewSet): 
    queryset = Egreso.objects.all().order_by("-fecha", "-id")
    serializer_class = EgresoSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = LargeResultsSetPagination

    def get_queryset(self):
        user = self.request.user
        es_admin = user.is_superuser or (hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN')
        
        qs = Egreso.objects.all().order_by("-fecha", "-id")

        if es_admin:
            oficina_param = self.request.query_params.get('oficina')
            if oficina_param and str(oficina_param).upper() not in ["ALL", ""]:
                keys = _get_todas_las_llaves_oficina(oficina_param)
                qs = qs.filter(oficina_id__in=keys)
        elif hasattr(user, 'perfil') and user.perfil.oficina:
            keys = _get_todas_las_llaves_oficina(user.perfil.oficina)
            qs = qs.filter(oficina_id__in=keys)
        else:
            return Egreso.objects.none()

        # Filtros de fecha
        desde = self.request.query_params.get('fecha__gte')
        hasta  = self.request.query_params.get('fecha__lte')
        if desde: qs = qs.filter(fecha__gte=desde)
        if hasta:  qs = qs.filter(fecha__lte=hasta)

        return qs
        
    def perform_create(self, serializer):
        user = self.request.user
        es_admin = user.is_superuser or (hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN')
        
        if not es_admin and hasattr(user, 'perfil') and user.perfil.oficina:
            serializer.save(usuario=user, oficina=user.perfil.oficina)
        else:
            serializer.save(usuario=user)

    # ============================================================
    # 🚀 NUEVO: HISTORIAL UNIFICADO DE EGRESOS
    # ============================================================
    @action(detail=False, methods=["get"], url_path="historial")
    def historial(self, request):
        """
        GET /api/balanzes/egresos/historial/
        Params: desde, hasta, oficina, forma_pago, search, page, page_size,
                export = "xlsx" | "pdf", all = 1
        """
        user = request.user
        es_admin = user.is_superuser or (hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN')

        qs = Egreso.objects.all().select_related("oficina", "usuario").order_by("-fecha", "-id")

        if es_admin:
            oficina_param = request.query_params.get('oficina')
            if oficina_param and str(oficina_param).upper() not in ["ALL", ""]:
                keys = _get_todas_las_llaves_oficina(oficina_param)
                qs = qs.filter(oficina_id__in=keys)
        elif hasattr(user, 'perfil') and user.perfil.oficina:
            keys = _get_todas_las_llaves_oficina(user.perfil.oficina)
            qs = qs.filter(oficina_id__in=keys)
        else:
            qs = Egreso.objects.none()

        desde_raw = request.query_params.get('desde') or request.query_params.get('fecha__gte')
        hasta_raw = request.query_params.get('hasta') or request.query_params.get('fecha__lte')
        forma = request.query_params.get('forma_pago')
        q = request.query_params.get('search') or request.query_params.get('q')

        d_desde = _parse_ymd(desde_raw) if desde_raw else None
        d_hasta = _parse_ymd(hasta_raw) if hasta_raw else None

        if d_desde:
            qs = qs.filter(fecha__gte=d_desde)
        if d_hasta:
            qs = qs.filter(fecha__lte=d_hasta)
        if forma and forma.lower() not in ('todas', ''):
            qs = qs.filter(forma_pago__iexact=forma)
        if q:
            qs = qs.filter(
                Q(descripcion__icontains=q) |
                Q(categoria__icontains=q)
            )

        all_flag = str(request.query_params.get('all') or '').strip().lower() in ("1", "true", "yes", "y")
        if all_flag:
            items = list(qs[:50000])
            from .serializers import EgresoSerializer
            ser = EgresoSerializer(items, many=True)
            return Response({"count": len(items), "results": ser.data, "all": True}, status=200)

        page = self.paginate_queryset(qs)
        if page is not None:
            from .serializers import EgresoSerializer
            return self.get_paginated_response(EgresoSerializer(page, many=True).data)

        from .serializers import EgresoSerializer
        return Response(EgresoSerializer(qs, many=True).data)


class BalanceViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated] 

    def _parse_fecha(self, request):
        raw = request.query_params.get("fecha") or (request.data.get("fecha") if hasattr(request, "data") else None)
        if raw:
            try: return datetime.fromisoformat(raw).date()
            except Exception: return None
        return timezone.localdate()

    def _get_seguridad_oficina(self, request, requested_oficina):
        user = request.user
        es_admin = user.is_superuser or (hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN')
        
        if es_admin:
            if not requested_oficina or str(requested_oficina).upper() in ["ALL", "NULL", "UNDEFINED", ""]:
                return None
            return _get_todas_las_llaves_oficina(requested_oficina)
            
        if hasattr(user, 'perfil') and user.perfil.oficina:
            return _get_todas_las_llaves_oficina(user.perfil.oficina)
            
        return "BLOQUEADO"


    def _desde_ultimo_cierre_hoy(self, fecha, oficina_id):
        """
        Si ya hubo un cierre de caja HOY en esta oficina (ej: el de mediodía),
        devuelve la fecha/hora exacta de ese cierre. Sirve para que "Efectivo
        esperado" NO repita la plata que ya se contó y se cerró en ese cierre
        anterior — mismo criterio que usa recaudacion/views.py al armar el
        cierre de la noche. Para fechas que no son HOY no aplica (ya cerraron
        todo ese día, mostrar el total completo es lo correcto ahí).
        """
        if not oficina_id or fecha != timezone.localdate():
            return None
        try:
            from recaudacion.models import CierreCaja
            ultimo = (
                CierreCaja.objects.filter(oficina_id=oficina_id, creado_en__date=fecha)
                .order_by("-creado_en")
                .first()
            )
            return ultimo.creado_en if ultimo else None
        except Exception:
            return None
    def _build_balance_from_qs(self, fecha, ingresos_qs, egresos_qs):
        total_ingresos = ingresos_qs.aggregate(t=Coalesce(Sum("monto"), Decimal("0")))["t"]
        total_egresos = egresos_qs.aggregate(t=Coalesce(Sum("monto"), Decimal("0")))["t"]
        ingresos_cantidad = ingresos_qs.aggregate(c=Coalesce(Count("id"), 0))["c"]
        egresos_cantidad = egresos_qs.aggregate(c=Coalesce(Count("id"), 0))["c"]

        try:
            pagadores_distintos = ingresos_qs.exclude(pagado_por__isnull=True).exclude(pagado_por__exact="").values("pagado_por").distinct().count()
        except Exception:
            pagadores_distintos = 0

        ingresos_por_forma_dict = {}
        for item in ingresos_qs.values("forma_pago", "monto"):
            forma_key = (item.get("forma_pago") or "SIN FORMA").upper()
            monto = item.get("monto") or Decimal("0")
            if forma_key not in ingresos_por_forma_dict:
                ingresos_por_forma_dict[forma_key] = {"forma_pago": forma_key, "total": Decimal("0"), "cantidad": 0}
            ingresos_por_forma_dict[forma_key]["total"] += monto
            ingresos_por_forma_dict[forma_key]["cantidad"] += 1

        ingresos_por_forma_out = [
            {"forma_pago": it["forma_pago"], "total": _d_to_str(it["total"]), "cantidad": it["cantidad"]} 
            for it in sorted(ingresos_por_forma_dict.values(), key=lambda x: x["forma_pago"])
        ]
            
        egresos_por_forma_dict = {}
        for item in egresos_qs.values("forma_pago", "monto"):
            forma_key = (item.get("forma_pago") or "EFECTIVO").upper()
            monto = item.get("monto") or Decimal("0")
            if forma_key not in egresos_por_forma_dict:
                egresos_por_forma_dict[forma_key] = {"forma_pago": forma_key, "total": Decimal("0"), "cantidad": 0}
            egresos_por_forma_dict[forma_key]["total"] += monto
            egresos_por_forma_dict[forma_key]["cantidad"] += 1
            
        egresos_por_forma_out = [
            {"forma_pago": it["forma_pago"], "total": _d_to_str(it["total"]), "cantidad": it["cantidad"]} 
            for it in sorted(egresos_por_forma_dict.values(), key=lambda x: x["forma_pago"])
        ]

        ingresos_efectivo = ingresos_por_forma_dict.get("EFECTIVO", {}).get("total", Decimal("0"))
        egresos_efectivo = egresos_por_forma_dict.get("EFECTIVO", {}).get("total", Decimal("0"))
        saldo_caja_chica = ingresos_efectivo - egresos_efectivo

        # 🚀 DETALLE de ingresos EN EFECTIVO (para el ticket de cierre): nombre, monto y hora exacta.
        detalle_efectivo = []
        try:
            ef_qs = (
                ingresos_qs.filter(forma_pago__iexact="EFECTIVO")
                .order_by("created_at", "id")
                .values("pagado_por", "monto", "created_at")
            )
            for ing in ef_qs:
                ca = ing.get("created_at")
                hora = ""
                if ca:
                    try:
                        hora = timezone.localtime(ca).strftime("%H:%M")
                    except Exception:
                        try:
                            hora = ca.strftime("%H:%M")
                        except Exception:
                            hora = ""
                detalle_efectivo.append({
                    "pagado_por": (ing.get("pagado_por") or "").strip(),
                    "monto": _d_to_str(ing.get("monto") or Decimal("0")),
                    "hora": hora,
                })
        except Exception:
            detalle_efectivo = []

        return {
            "fecha_iso": fecha.isoformat(),
            "fecha_hum": fecha.strftime("%d/%m/%Y"),
            "totales": {
                "ingresos": _d_to_str(total_ingresos),
                "egresos": _d_to_str(total_egresos),
                "balance": _d_to_str((total_ingresos or 0) - (total_egresos or 0)),
                "saldo_caja_chica": _d_to_str(saldo_caja_chica), 
                "ingresos_cantidad": int(ingresos_cantidad or 0),
                "egresos_cantidad": int(egresos_cantidad or 0),
                "pagadores_distintos": int(pagadores_distintos or 0),
            },
            "ingresos": {"por_forma_pago": ingresos_por_forma_out, "detalle_efectivo": detalle_efectivo},
            "egresos": {"por_forma_pago": egresos_por_forma_out}
        }

    def _build_balance(self, fecha, oficina_keys=None):
        if oficina_keys:
            ingresos_qs = Ingreso.objects.filter(fecha=fecha, oficina_id__in=oficina_keys)
            egresos_qs = Egreso.objects.filter(fecha=fecha, oficina_id__in=oficina_keys)

            # 🆕 No repetir la plata ya contada en un cierre anterior de HOY (ej: mediodía).
            if len(oficina_keys) == 1:
                desde = self._desde_ultimo_cierre_hoy(fecha, oficina_keys[0])
                if desde:
                    ingresos_qs = ingresos_qs.filter(created_at__gt=desde)
                    egresos_qs = egresos_qs.filter(created_at__gt=desde)

            ofi_obj = Oficina.objects.filter(id=oficina_keys[0]).first() if oficina_keys else None
            ofi_label = ofi_obj.nombre if ofi_obj else "Tu Sucursal"
            
            payload = self._build_balance_from_qs(fecha, ingresos_qs, egresos_qs)
            payload["scope"] = {"oficina": oficina_keys[0], "oficina_nombre": ofi_label}
            return payload

        ingresos_all = Ingreso.objects.filter(fecha=fecha)
        egresos_all = Egreso.objects.filter(fecha=fecha)
        general = self._build_balance_from_qs(fecha, ingresos_all, egresos_all)

        por_oficina = []
        for ofi in Oficina.objects.all():
            ing_ofi = ingresos_all.filter(oficina=ofi)
            egr_ofi = egresos_all.filter(oficina=ofi)

            # 🆕 Mismo criterio, por sucursal: no repetir lo ya cerrado hoy.
            desde = self._desde_ultimo_cierre_hoy(fecha, ofi.id)
            if desde:
                ing_ofi = ing_ofi.filter(created_at__gt=desde)
                egr_ofi = egr_ofi.filter(created_at__gt=desde)

            block = self._build_balance_from_qs(fecha, ing_ofi, egr_ofi)
            block["scope"] = {"oficina": ofi.id, "oficina_nombre": ofi.nombre}
            por_oficina.append(block)

        sin_oficina = None
        iq_none = ingresos_all.filter(oficina__isnull=True)
        eq_none = egresos_all.filter(oficina__isnull=True)
        if iq_none.exists() or eq_none.exists():
            sin_oficina = self._build_balance_from_qs(fecha, iq_none, eq_none)
            sin_oficina["scope"] = {"oficina": None, "oficina_nombre": "SIN OFICINA"}

        general["por_oficina"] = por_oficina
        if sin_oficina:
            general["sin_oficina"] = sin_oficina

        return general

    @action(detail=False, methods=["get"])
    def balance_diario(self, request):
        try:
            fecha = self._parse_fecha(request)
            if fecha is None: return Response({"detail": "Fecha inválida."}, status=400)

            req_ofi = request.query_params.get("oficina")
            keys = self._get_seguridad_oficina(request, req_ofi)
            if keys == "BLOQUEADO": return Response({"detail": "No autorizado."}, status=403)

            return Response(self._build_balance(fecha, oficina_keys=keys), status=200)
        except Exception as e:
            return Response({"error": str(e)}, status=500)

    def _build_balance_rango(self, desde, hasta, oficina_keys=None):
        """
        Igual que _build_balance pero sumando un RANGO de fechas (mes completo),
        no un solo día. Reutiliza _build_balance_from_qs (suma en el backend).
        """
        rango = Q(fecha__gte=desde, fecha__lte=hasta)

        if oficina_keys:
            ingresos_qs = Ingreso.objects.filter(rango, oficina_id__in=oficina_keys)
            egresos_qs = Egreso.objects.filter(rango, oficina_id__in=oficina_keys)

            ofi_obj = Oficina.objects.filter(id=oficina_keys[0]).first() if oficina_keys else None
            ofi_label = ofi_obj.nombre if ofi_obj else "Tu Sucursal"

            payload = self._build_balance_from_qs(desde, ingresos_qs, egresos_qs)
            payload["scope"] = {"oficina": oficina_keys[0], "oficina_nombre": ofi_label}
            payload["rango"] = {"desde": desde.isoformat(), "hasta": hasta.isoformat()}
            return payload

        ingresos_all = Ingreso.objects.filter(rango)
        egresos_all = Egreso.objects.filter(rango)
        general = self._build_balance_from_qs(desde, ingresos_all, egresos_all)

        por_oficina = []
        for ofi in Oficina.objects.all():
            block = self._build_balance_from_qs(
                desde,
                ingresos_all.filter(oficina=ofi),
                egresos_all.filter(oficina=ofi),
            )
            block["scope"] = {"oficina": ofi.id, "oficina_nombre": ofi.nombre}
            por_oficina.append(block)

        sin_oficina = None
        iq_none = ingresos_all.filter(oficina__isnull=True)
        eq_none = egresos_all.filter(oficina__isnull=True)
        if iq_none.exists() or eq_none.exists():
            sin_oficina = self._build_balance_from_qs(desde, iq_none, eq_none)
            sin_oficina["scope"] = {"oficina": None, "oficina_nombre": "SIN OFICINA"}

        general["por_oficina"] = por_oficina
        if sin_oficina:
            general["sin_oficina"] = sin_oficina
        general["rango"] = {"desde": desde.isoformat(), "hasta": hasta.isoformat()}
        return general

    @action(detail=False, methods=["get"], url_path="balance-mensual")
    def balance_mensual(self, request):
        """
        Totales sumados de TODO un mes (o un rango), calculados en el backend.
        Params:
          ?mes=YYYY-MM           (default: mes actual)
          ?desde=&hasta=         (opcional, rango explícito YYYY-MM-DD)
          ?oficina=<id|ALL>      (respeta el escudo de sucursal)
        Misma estructura que balance-diario (totales, por_forma_pago, por_oficina).
        """
        try:
            hoy = timezone.localdate()
            mes_raw   = (request.query_params.get("mes")   or "").strip()
            desde_raw = (request.query_params.get("desde") or "").strip()
            hasta_raw = (request.query_params.get("hasta") or "").strip()

            if desde_raw and hasta_raw:
                desde = parse_date(desde_raw)
                hasta = parse_date(hasta_raw)
            else:
                if mes_raw:
                    try:
                        y, m = mes_raw.split("-")[:2]
                        y, m = int(y), int(m)
                    except Exception:
                        y, m = hoy.year, hoy.month
                else:
                    y, m = hoy.year, hoy.month
                desde = datetime(y, m, 1).date()
                if m == 12:
                    hasta = datetime(y, 12, 31).date()
                else:
                    hasta = (datetime(y, m + 1, 1) - timedelta(days=1)).date()

            if not desde or not hasta:
                return Response({"detail": "Rango inválido."}, status=400)

            req_ofi = request.query_params.get("oficina")
            keys = self._get_seguridad_oficina(request, req_ofi)
            if keys == "BLOQUEADO":
                return Response({"detail": "No autorizado."}, status=403)

            return Response(self._build_balance_rango(desde, hasta, oficina_keys=keys), status=200)
        except Exception as e:
            return Response({"error": str(e)}, status=500)

    @action(detail=False, methods=["post"])
    def enviar_balance(self, request):
        try:
            fecha = self._parse_fecha(request)
            keys = self._get_seguridad_oficina(request, request.data.get("oficina"))
            if keys == "BLOQUEADO": return Response({"detail": "No autorizado."}, status=403)

            data = self._build_balance(fecha, oficina_keys=keys)
            destinatarios = ["1164235336"]
            resultados = []
            all_ok = True

            for numero in destinatarios:
                ok, info = enviar_balance_por_whatsapp(fecha=fecha, data=data, destinatario=numero)
                resultados.append({"numero": numero, "ok": bool(ok), "info": info})
                if not ok: all_ok = False

            status_code = 200 if all_ok else 502
            return Response({"detail": "Envío procesado", "resultados": resultados}, status=status_code)
        except Exception as e:
            return Response({"error": str(e)}, status=500)