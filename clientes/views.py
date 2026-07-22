# clientes/views.py  ✅ BLINDADO MULTI-TENANT (ESTRICTO POR SUCURSAL)

from decimal import Decimal

from django.db import connection, models
from django.db.models import (
    Q, Count, Sum, Max, Value, IntegerField, DecimalField, F,
    Case, When, ExpressionWrapper, FloatField, Func, DurationField, DateTimeField
)
from django.db.models.functions import (
    Coalesce, Now, TruncDate, Greatest, Cast, ExtractDay,
    Lower, Trim, Replace, Concat
)

from rest_framework import viewsets, status, filters
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from .models import Cliente, EstadoCliente
from .serializers import ClienteSerializer, ClienteBasicSerializer, ClienteDetailSerializer

from siniestros.models import Siniestro
from siniestros.serializers import SiniestroSerializer

from pagos.models import Pago, Cuota
from pagos.serializers import PagoSerializer


def _to_bool(v) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"1", "true", "t", "yes", "y", "on", "si", "sí"}


def _norm_digits_expr(expr):
    if connection.vendor != "sqlite":
        return Func(expr, Value(r"\D"), Value(""), Value("g"), function="REGEXP_REPLACE")

    x = Coalesce(expr, Value(""))
    for ch in [" ", "-", "(", ")", "+", ".", "/"]:
        x = Replace(x, Value(ch), Value(""))
    return x


# ============================================================
# 🚀 CALIDAD DE DATOS: chequeos centralizados de "dato faltante"
# ------------------------------------------------------------
# Una sola fuente de verdad: el resumen (KPIs) y el filtro de
# la lista usan EXACTAMENTE los mismos criterios. Si mañana querés
# agregar un dato nuevo (ej: "partido"), lo sumás acá y aparece
# automáticamente en los KPIs y en los filtros, sin tocar más nada.
# El front manda ?sin_<clave>=1 para filtrar la lista.
# ============================================================
CAMPOS_CALIDAD_CLIENTE = [
    "telefono", "email", "dni", "fecha_nacimiento",
    "direccion", "localidad", "dni_frente", "dni_dorso",
]


def _q_dato_faltante(campo: str):
    """Devuelve el Q() que matchea clientes a los que les FALTA ese dato."""
    if campo == "telefono":
        return Q(telefono__isnull=True) | Q(telefono="")
    if campo == "email":
        return Q(email__isnull=True) | Q(email="")
    if campo == "dni":
        return Q(dni_cuit_cuil__isnull=True) | Q(dni_cuit_cuil="")
    if campo == "fecha_nacimiento":
        # DateField: solo puede faltar como NULL (no existe "" en fechas)
        return Q(fecha_nacimiento__isnull=True)
    if campo == "direccion":
        return Q(direccion__isnull=True) | Q(direccion="")
    if campo == "localidad":
        return Q(localidad__isnull=True) | Q(localidad="")
    if campo == "dni_frente":
        # Falta si no hay frente nuevo NI el legacy archivo_dni
        return (
            (Q(archivo_dni_frente__isnull=True) | Q(archivo_dni_frente="")) &
            (Q(archivo_dni__isnull=True) | Q(archivo_dni=""))
        )
    if campo == "dni_dorso":
        return Q(archivo_dni_dorso__isnull=True) | Q(archivo_dni_dorso="")
    return None


def _q_incompleto():
    """Q() que matchea clientes a los que les falta AL MENOS UN dato (OR de todo)."""
    total = Q()
    for campo in CAMPOS_CALIDAD_CLIENTE:
        q = _q_dato_faltante(campo)
        if q is not None:
            total |= q
    return total


def _dup_key_expr(por: str):
    """Expresión de clave para agrupar duplicados según ?por= (dni|email|telefono|nombre)."""
    if por == "email":
        return Lower(Trim(Coalesce(F("email"), Value(""))))
    if por == "telefono":
        return _norm_digits_expr(Trim(Coalesce(F("telefono"), Value(""))))
    if por in {"nombre_nacimiento", "nombre"}:
        return Concat(
            Lower(Trim(Coalesce(F("apellido"), Value("")))), Value("|"),
            Lower(Trim(Coalesce(F("nombre"), Value("")))), Value("|"),
            Cast(F("fecha_nacimiento"), output_field=models.CharField()),
        )
    return _norm_digits_expr(Trim(Coalesce(F("dni_cuit_cuil"), Value(""))))


class ClienteViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ("nombre", "apellido", "dni_cuit_cuil", "telefono", "email")

    ordering_fields = (
        "id", "nombre", "apellido", "dni_cuit_cuil", "telefono",
        "estado", "polizas_total", "polizas_activas", "deuda",
        "ultima_fecha_vencimiento", "ultima_mora_dias",
    )

    def get_serializer_class(self):
        if self.action == "list":
            return ClienteBasicSerializer
        if self.action in ("retrieve", "update", "partial_update"):
            return ClienteDetailSerializer
        return ClienteSerializer

    def _apply_estado_filter(self, qs):
        raw = (self.request.query_params.get("estado") or "").strip()
        if not raw:
            return qs

        s = raw.lower()
        if s in ("activos", "activo", "completos", "completo"):
            return qs.filter(estado=EstadoCliente.COMPLETO)
        if s in ("inactivos", "inactivo", "borradores", "borrador"):
            return qs.filter(estado=EstadoCliente.BORRADOR)

        up = raw.upper()
        if up in (EstadoCliente.COMPLETO, EstadoCliente.BORRADOR):
            return qs.filter(estado=up)

        return qs

    def _apply_oficina_filter(self, qs):
        """
        🚀 ESCUDO MULTI-TENANT ESTRICTO
        Solo los administradores pueden ver todos o filtrar.
        Los empleados SOLO ven los clientes de su propia oficina.
        """
        # 🔓 ABIERTO: admin y empleados de oficina ven/operan con TODOS los clientes.
        #    Un cliente sigue perteneciendo a su oficina original, pero cualquier
        #    sucursal puede verlo y operar (circula entre oficinas). La plata se
        #    separa por oficina en recaudación/métricas, no acá.
        #    Igual respetamos el filtro opcional ?oficina= si lo mandan a propósito.
        v = (self.request.query_params.get("oficina") or "").strip()
        if not v or v.upper() == "ALL":
            return qs
        return qs.filter(oficina_id=v) if v.isdigit() else qs.filter(oficina__codigo__iexact=v)

    def get_queryset(self):
        qs = Cliente.objects.all().select_related('oficina').order_by("-id")
        qs = self._apply_estado_filter(qs)
        
        # 🚀 Aplicamos el escudo estricto
        qs = self._apply_oficina_filter(qs)

        # 🚀 FILTROS DE CALIDAD DE DATOS (todos los campos del cliente)
        # Se aplican según ?sin_<campo>=1. Usan la misma lógica que el resumen.
        algun_filtro_calidad = False
        for campo in CAMPOS_CALIDAD_CLIENTE:
            if _to_bool(self.request.query_params.get(f"sin_{campo}")):
                q = _q_dato_faltante(campo)
                if q is not None:
                    qs = qs.filter(q)
                    algun_filtro_calidad = True

        # Optimización: en el módulo de calidad devolvemos directo sin calcular deudas
        if algun_filtro_calidad and self.action == "list":
            return qs.order_by("-id")

        # 🚀 FILTRO "INCOMPLETO": clientes a los que les falta AL MENOS UN dato
        if _to_bool(self.request.query_params.get("incompleto")):
            qs = qs.filter(_q_incompleto())
            if self.action == "list":
                return qs.order_by("-id")

        if self.action == "list":
            money_field = DecimalField(max_digits=14, decimal_places=2)
            zero_money = Value(Decimal("0.00"), output_field=money_field)
            zero_int = Value(0, output_field=IntegerField())

            cuota_amount_field = None
            try:
                cuota_fields = {f.name for f in Cuota._meta.get_fields()}
                for cand in ("monto", "importe", "monto_cuota", "precio", "precio_cuota"):
                    if cand in cuota_fields:
                        cuota_amount_field = cand
                        break
            except Exception:
                cuota_amount_field = None

            cuota_amount_path = f"polizas__cuotas__{cuota_amount_field}" if cuota_amount_field else None

            qs = qs.annotate(
                polizas_total=Coalesce(Count("polizas", distinct=True), zero_int),
                polizas_activas=Coalesce(
                    Count("polizas", filter=Q(polizas__estado__in=["ACTIVA", "VIGENTE", "ACTIVO"]), distinct=True),
                    zero_int,
                ),
                deuda=Coalesce(
                    Sum(cuota_amount_path, filter=Q(polizas__cuotas__pagado=False), output_field=money_field)
                    if cuota_amount_path else zero_money,
                    zero_money,
                ),
                ultima_fecha_vencimiento=Max(
                    "polizas__cuotas__fecha_vencimiento",
                    filter=Q(polizas__cuotas__pagado=False),
                ),
            )

            if connection.vendor == "sqlite":
                now_jd = Func(TruncDate(Now()), function="JULIANDAY", output_field=FloatField())
                venc_jd = Func(F("ultima_fecha_vencimiento"), function="JULIANDAY", output_field=FloatField())
                diff_days = ExpressionWrapper(now_jd - venc_jd, output_field=FloatField())
                mora_int = Cast(diff_days, IntegerField())

                qs = qs.annotate(
                    ultima_mora_dias=Case(
                        When(ultima_fecha_vencimiento__isnull=True, then=zero_int),
                        default=Greatest(zero_int, Coalesce(mora_int, zero_int)),
                        output_field=IntegerField(),
                    )
                )
            else:
                dur = ExpressionWrapper(
                    Now() - Cast(F("ultima_fecha_vencimiento"), DateTimeField()),
                    output_field=DurationField(),
                )
                mora_days = ExtractDay(dur)

                qs = qs.annotate(
                    ultima_mora_dias=Case(
                        When(ultima_fecha_vencimiento__isnull=True, then=zero_int),
                        default=Greatest(zero_int, Coalesce(mora_days, zero_int)),
                        output_field=IntegerField(),
                    )
                )

            return qs

        return qs.prefetch_related("polizas", "polizas__cuotas")

    def perform_create(self, serializer):
        user = self.request.user
        es_admin = user.is_superuser or (hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN')
        
        oficina_id = self.request.data.get('oficina')
        
        if es_admin and oficina_id:
            serializer.save(oficina_id=oficina_id)
        else:
            serializer.save(oficina=user.perfil.oficina if hasattr(user, 'perfil') else None)

    # 🚀 FIX: AGREGAMOS PERFORM_UPDATE PARA DESTRABAR LA EDICIÓN
    def perform_update(self, serializer):
        user = self.request.user
        es_admin = user.is_superuser or (hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN')
        
        oficina_id = self.request.data.get('oficina')
        
        if es_admin and oficina_id:
            serializer.save(oficina_id=oficina_id)
        else:
            # Si no es admin o no pasa oficina, que guarde los datos normalmente sin tocar la oficina
            serializer.save()

    # 🚀 ENDPOINT MAESTRO DE CALIDAD (cuenta TODOS los datos faltantes)
    @action(detail=False, methods=["get"], url_path="calidad/resumen")
    def calidad_resumen(self, request):
        # Base filtrada solo por oficina/estado (sin los filtros de calidad)
        qs_base = Cliente.objects.all().select_related('oficina')
        qs_base = self._apply_estado_filter(qs_base)
        qs = self._apply_oficina_filter(qs_base)

        resumen = {"total": qs.count()}
        for campo in CAMPOS_CALIDAD_CLIENTE:
            q = _q_dato_faltante(campo)
            resumen[f"sin_{campo}"] = qs.filter(q).count() if q is not None else 0
        # Clientes con AL MENOS UN dato faltante
        resumen["incompletos"] = qs.filter(_q_incompleto()).count()
        # Devuelve: total, incompletos, sin_telefono, sin_email, sin_dni,
        # sin_fecha_nacimiento, sin_direccion, sin_localidad, sin_dni_frente, sin_dni_dorso
        return Response(resumen)

    def _dup_base_qs(self):
        base = self.get_queryset()
        for backend in self.filter_backends:
            if backend is filters.OrderingFilter:
                continue
            base = backend().filter_queryset(self.request, base, self)
        return base

    @action(detail=False, methods=["get"], url_path="duplicados/resumen")
    def duplicados_resumen(self, request):
        por = (request.query_params.get("por") or "dni").strip().lower()
        qs = self._dup_base_qs()

        key_expr = _dup_key_expr(por)

        qs2 = qs.annotate(_dup_key=key_expr).exclude(_dup_key__isnull=True).exclude(_dup_key__exact="")
        groups = qs2.values("_dup_key").annotate(c=Count("id")).filter(c__gt=1)

        total_grupos = groups.count()
        total_registros = groups.aggregate(total=Coalesce(Sum("c"), Value(0, output_field=IntegerField())))["total"]

        return Response({"por": por, "grupos": int(total_grupos), "registros_en_grupos": int(total_registros or 0)})

    @action(detail=False, methods=["get"], url_path="duplicados")
    def duplicados(self, request):
        por = (request.query_params.get("por") or "dni").strip().lower()
        qs = self._dup_base_qs()

        key_expr = _dup_key_expr(por)

        qs2 = qs.annotate(_dup_key=key_expr).exclude(_dup_key__isnull=True).exclude(_dup_key__exact="")
        groups_qs = qs2.values("_dup_key").annotate(count=Count("id")).filter(count__gt=1).order_by("-count", "_dup_key")

        page = self.paginate_queryset(groups_qs)
        groups_page = page if page is not None else list(groups_qs[:50])

        results = []
        for g in groups_page:
            key_val = g["_dup_key"]
            count_val = int(g["count"])
            items = qs2.filter(_dup_key=key_val).only("id", "nombre", "apellido", "telefono", "email", "dni_cuit_cuil", "estado").order_by("-id")[:50]
            
            clientes = [{"id": c.id, "apellido": c.apellido, "nombre": c.nombre, "dni_cuit_cuil": c.dni_cuit_cuil, "telefono": c.telefono, "email": c.email, "estado": c.estado} for c in items]
            results.append({"key": key_val, "count": count_val, "clientes": clientes})

        payload = {"por": por, "results": results}
        if page is not None:
            return self.get_paginated_response(payload)
        return Response(payload, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"])
    def siniestros(self, request, pk=None):
        cliente = self.get_object()
        siniestros = Siniestro.objects.filter(cliente=cliente).order_by("-id")
        serializer = SiniestroSerializer(siniestros, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def pagos(self, request, pk=None):
        cliente = self.get_object()
        pagos = Pago.objects.filter(poliza__cliente=cliente).order_by("-id")
        serializer = PagoSerializer(pagos, many=True)
        return Response(serializer.data)