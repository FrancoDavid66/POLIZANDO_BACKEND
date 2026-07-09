# servicios/views.py
from rest_framework import viewsets, status, filters, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.utils import timezone
from django.db.models import Q, Sum, Count
from datetime import date, timedelta
import calendar

from balanzes.models import Egreso

from .models import ServicioFijo, PagoServicio, CategoriaServicio
from .serializers import (
    ServicioFijoSerializer,
    PagoServicioSerializer,
    RegistrarPagoServicioSerializer,
    CategoriaServicioSerializer,
)


# ════════════════════════════════════════════════════════════════
# 🔒 PERMISO: Solo Admin
# ════════════════════════════════════════════════════════════════
class IsAdminRol(permissions.BasePermission):
    message = "Solo el administrador puede gestionar los servicios fijos."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN'


# ════════════════════════════════════════════════════════════════
# 🆕 CategoriaServicio ViewSet (CRUD)
# ════════════════════════════════════════════════════════════════
class CategoriaServicioViewSet(viewsets.ModelViewSet):
    queryset = CategoriaServicio.objects.all()
    serializer_class = CategoriaServicioSerializer
    permission_classes = [IsAdminRol]

    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre']
    ordering_fields = ['nombre', 'creado_en']

    def get_queryset(self):
        qs = super().get_queryset()
        activo = self.request.query_params.get('activo')
        if activo is not None:
            if str(activo).lower() in ['true', '1', 'yes']:
                qs = qs.filter(activo=True)
            elif str(activo).lower() in ['false', '0', 'no']:
                qs = qs.filter(activo=False)
        return qs

    def perform_create(self, serializer):
        serializer.save(creado_por=self.request.user)

    def destroy(self, request, *args, **kwargs):
        categoria = self.get_object()
        en_uso = ServicioFijo.objects.filter(categoria__iexact=categoria.nombre).count()
        if en_uso > 0:
            return Response(
                {'error': f'No se puede eliminar: hay {en_uso} servicio(s) usando esta categoría.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        return super().destroy(request, *args, **kwargs)


# ════════════════════════════════════════════════════════════════
# 🛠 HELPERS: Generar pagos
# ════════════════════════════════════════════════════════════════
def _generar_pagos_para_periodo(anio: int, mes: int):
    periodo = f"{anio:04d}-{mes:02d}"
    servicios_activos = ServicioFijo.objects.filter(activo=True)

    creados = 0
    omitidos = 0
    with transaction.atomic():
        for servicio in servicios_activos:
            fecha_venc = servicio.fecha_vencimiento_del_mes(anio, mes)
            _, was_created = PagoServicio.objects.get_or_create(
                servicio=servicio,
                periodo=periodo,
                defaults={
                    'fecha_vencimiento': fecha_venc,
                    'estado': 'PENDIENTE',
                }
            )
            if was_created:
                creados += 1
            else:
                omitidos += 1
    return creados, omitidos


def _generar_pagos_anticipados():
    hoy = timezone.localdate()
    cre_actual, _ = _generar_pagos_para_periodo(hoy.year, hoy.month)

    if hoy.month == 12:
        anio_sig, mes_sig = hoy.year + 1, 1
    else:
        anio_sig, mes_sig = hoy.year, hoy.month + 1

    en_7_dias = hoy + timedelta(days=7)
    servicios_activos = ServicioFijo.objects.filter(activo=True)
    necesita_proximo = False
    for s in servicios_activos:
        try:
            fecha_venc_proxima = s.fecha_vencimiento_del_mes(anio_sig, mes_sig)
        except Exception:
            continue
        if hoy <= fecha_venc_proxima <= en_7_dias:
            necesita_proximo = True
            break

    cre_proximo = 0
    if necesita_proximo:
        cre_proximo, _ = _generar_pagos_para_periodo(anio_sig, mes_sig)

    return cre_actual, cre_proximo


# ════════════════════════════════════════════════════════════════
# ServicioFijo ViewSet
# ════════════════════════════════════════════════════════════════
class ServicioFijoViewSet(viewsets.ModelViewSet):
    queryset = ServicioFijo.objects.select_related('oficina', 'creado_por').all()
    serializer_class = ServicioFijoSerializer
    permission_classes = [IsAdminRol]

    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre', 'proveedor', 'categoria']
    ordering_fields = ['nombre', 'dia_vencimiento', 'creado_en']

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params

        activo = params.get('activo')
        if activo is not None:
            if str(activo).lower() in ['true', '1', 'yes']:
                qs = qs.filter(activo=True)
            elif str(activo).lower() in ['false', '0', 'no']:
                qs = qs.filter(activo=False)

        oficina = params.get('oficina')
        if oficina and str(oficina).upper() not in ['ALL', 'NULL', '']:
            if str(oficina).isdigit():
                qs = qs.filter(oficina_id=int(oficina))

        categoria = params.get('categoria')
        if categoria:
            qs = qs.filter(categoria__iexact=categoria)

        return qs

    def perform_create(self, serializer):
        serializer.save(creado_por=self.request.user)

    @action(detail=False, methods=['post'])
    def generar_pagos_mes(self, request):
        anio_str = request.data.get('anio')
        mes_str = request.data.get('mes')

        hoy = timezone.localdate()
        try:
            anio = int(anio_str) if anio_str else hoy.year
            mes = int(mes_str) if mes_str else hoy.month
        except (TypeError, ValueError):
            return Response({'error': 'anio y mes deben ser números'}, status=400)

        if not (1 <= mes <= 12):
            return Response({'error': 'mes debe estar entre 1 y 12'}, status=400)

        creados, omitidos = _generar_pagos_para_periodo(anio, mes)
        periodo = f"{anio:04d}-{mes:02d}"

        return Response({
            'periodo': periodo,
            'creados': creados,
            'omitidos': omitidos,
            'mensaje': f'Se generaron {creados} pagos para {periodo}. {omitidos} ya existían.',
        })

    @action(detail=False, methods=['post'])
    def asegurar_pagos(self, request):
        cre_actual, cre_proximo = _generar_pagos_anticipados()
        return Response({
            'creados_mes_actual': cre_actual,
            'creados_proximo_mes': cre_proximo,
            'total': cre_actual + cre_proximo,
        })


# ════════════════════════════════════════════════════════════════
# PagoServicio ViewSet
# ════════════════════════════════════════════════════════════════
class PagoServicioViewSet(viewsets.ModelViewSet):
    queryset = PagoServicio.objects.select_related(
        'servicio', 'servicio__oficina', 'pagado_por', 'medio_cobro', 'egreso'
    ).all()
    serializer_class = PagoServicioSerializer
    permission_classes = [IsAdminRol]

    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['servicio__nombre', 'servicio__proveedor', 'observaciones']
    ordering_fields = ['fecha_vencimiento', 'estado', 'monto_real']

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params

        periodo = params.get('periodo')
        if periodo:
            qs = qs.filter(periodo=periodo)

        estado = params.get('estado')
        if estado and estado.upper() != 'TODOS':
            qs = qs.filter(estado=estado.upper())

        servicio_id = params.get('servicio')
        if servicio_id:
            qs = qs.filter(servicio_id=servicio_id)

        for pago in qs.filter(estado='PENDIENTE'):
            pago.actualizar_estado_automatico()

        return qs.order_by('estado', 'fecha_vencimiento')

    @action(detail=False, methods=['get'])
    def resumen_mes(self, request):
        params = request.query_params
        hoy = timezone.localdate()
        periodo = params.get('periodo') or f"{hoy.year:04d}-{hoy.month:02d}"

        qs = self.get_queryset().filter(periodo=periodo)

        total_estimado = sum((p.servicio.monto_estimado or 0) for p in qs)
        total_pagado = qs.filter(estado='PAGADO').aggregate(t=Sum('monto_real'))['t'] or 0

        conteo = qs.aggregate(
            total=Count('id'),
            pendientes=Count('id', filter=Q(estado='PENDIENTE')),
            pagados=Count('id', filter=Q(estado='PAGADO')),
            vencidos=Count('id', filter=Q(estado='VENCIDO')),
            omitidos=Count('id', filter=Q(estado='OMITIDO')),
        )

        por_vencer = sum(1 for p in qs if p.esta_por_vencer)

        return Response({
            'periodo': periodo,
            'total_estimado': float(total_estimado),
            'total_pagado': float(total_pagado),
            'total_pendiente': float(total_estimado) - float(total_pagado),
            'conteo': conteo,
            'por_vencer': por_vencer,
        })

    @action(detail=False, methods=['get'])
    def contadores(self, request):
        try:
            _generar_pagos_anticipados()
        except Exception:
            pass

        hoy = timezone.localdate()
        en_3_dias = hoy + timedelta(days=3)

        qs_base = self.get_queryset().filter(estado__in=['PENDIENTE', 'VENCIDO'])

        vencidos_count = qs_base.filter(fecha_vencimiento__lt=hoy).count()
        por_vencer_count = qs_base.filter(
            fecha_vencimiento__gte=hoy,
            fecha_vencimiento__lte=en_3_dias,
        ).count()

        urgentes_qs = qs_base.filter(fecha_vencimiento__lte=en_3_dias).order_by('fecha_vencimiento')[:5]

        proximos = []
        for p in urgentes_qs:
            dias = (p.fecha_vencimiento - hoy).days
            proximos.append({
                'id': p.id,
                'servicio_nombre': p.servicio.nombre,
                'fecha_vencimiento': p.fecha_vencimiento.isoformat(),
                'dias_hasta_vencimiento': dias,
                'monto_estimado': float(p.servicio.monto_estimado or 0),
                'estado': 'VENCIDO' if dias < 0 else 'POR_VENCER',
            })

        return Response({
            'vencidos': vencidos_count,
            'por_vencer': por_vencer_count,
            'total_alertas': vencidos_count + por_vencer_count,
            'proximos': proximos,
        })

    @action(detail=True, methods=['post'])
    def registrar_pago(self, request, pk=None):
        pago = self.get_object()

        if pago.estado == 'PAGADO':
            return Response({'error': 'Ya fue pagado'}, status=400)

        serializer = RegistrarPagoServicioSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        medio_cobro = None
        if data['forma_pago'] != 'EFECTIVO':
            from pagos.models import MedioCobro
            try:
                medio_cobro = MedioCobro.objects.get(id=data['medio_cobro_id'], activo=True)
            except MedioCobro.DoesNotExist:
                return Response({'medio_cobro_id': 'Billetera no encontrada'}, status=400)

        with transaction.atomic():
            descripcion = f"{pago.servicio.nombre} - {pago.periodo}"
            if pago.servicio.proveedor:
                descripcion = f"{pago.servicio.proveedor} ({pago.servicio.nombre}) - {pago.periodo}"

            billetera_str = ""
            if medio_cobro:
                billetera_str = medio_cobro.etiqueta or medio_cobro.titular_nombre or medio_cobro.valor or ""

            obs_egreso = f"[Servicio Fijo] {data.get('observaciones', '') or ''}".strip()

            egreso = Egreso.objects.create(
                descripcion=descripcion,
                monto=data['monto'],
                fecha=data['fecha'],
                oficina=pago.servicio.oficina,
                categoria=pago.servicio.categoria,
                forma_pago=data['forma_pago'],
                observaciones=obs_egreso,
                usuario=request.user,
            )

            if hasattr(egreso, 'billetera') and billetera_str:
                egreso.billetera = billetera_str
                egreso.save(update_fields=['billetera'])

            pago.estado = 'PAGADO'
            pago.monto_real = data['monto']
            pago.fecha_pago = data['fecha']
            pago.hora_pago = timezone.now()
            pago.pagado_por = request.user
            pago.forma_pago = data['forma_pago']
            pago.medio_cobro = medio_cobro
            pago.comprobante_url = data['comprobante_url']
            pago.observaciones = data.get('observaciones', '')
            pago.egreso = egreso
            pago.save()

            if medio_cobro:
                medio_cobro.marcar_uso()

        return Response(PagoServicioSerializer(pago).data, status=200)

    @action(detail=True, methods=['post'])
    def deshacer_pago(self, request, pk=None):
        pago = self.get_object()
        if pago.estado != 'PAGADO':
            return Response({'error': 'Solo se pueden deshacer pagos PAGADOS'}, status=400)

        with transaction.atomic():
            if pago.egreso:
                pago.egreso.delete()

            pago.estado = 'PENDIENTE'
            pago.monto_real = None
            pago.fecha_pago = None
            pago.hora_pago = None
            pago.pagado_por = None
            pago.forma_pago = ""
            pago.medio_cobro = None
            pago.comprobante_url = ""
            pago.egreso = None
            pago.save()

            pago.actualizar_estado_automatico()

        return Response(PagoServicioSerializer(pago).data, status=200)