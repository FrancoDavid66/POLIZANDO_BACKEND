import calendar as _calendar
from datetime import date

from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.db.models import Sum, Count, Q
from decimal import Decimal

from .models import CierreCaja
from .serializers import CierreCajaSerializer
from balanzes.models import Ingreso, Egreso

class CierreCajaViewSet(viewsets.ModelViewSet):
    # 🚀 Agregamos 'empleado' al select_related para evitar el problema N+1
    queryset = CierreCaja.objects.all().select_related('usuario', 'oficina', 'empleado')
    serializer_class = CierreCajaSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    ordering_fields = ['creado_en']
    ordering = ['-creado_en']

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user

        es_admin = user.is_superuser or (hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN')
        if not es_admin:
            ofi_id = getattr(user.perfil, 'oficina_id', None)
            if ofi_id:
                qs = qs.filter(oficina_id=ofi_id)
            else:
                return qs.none()

        oficina = self.request.query_params.get('oficina')
        fecha = self.request.query_params.get('fecha')

        if es_admin and oficina:
            qs = qs.filter(oficina_id=oficina)

        if fecha:
            parsed_date = parse_date(fecha)
            if parsed_date:
                qs = qs.filter(creado_en__date=parsed_date)

        return qs

    def perform_create(self, serializer):
        user = self.request.user
        ofi_id = getattr(user.perfil, 'oficina_id', None) if hasattr(user, 'perfil') else None

        fecha_hoy = timezone.localdate()

        # Turno automático por hora: corte a las 17:00 (cerrar a las 15:00 aunque
        # sea un poco más tarde sigue contando como mediodía).
        ahora = timezone.localtime()
        turno = "mediodia" if ahora.hour < 17 else "noche"

        monto_sistema = Decimal('0.00')

        # 🔧 Rango del turno: si es el cierre de la NOCHE, el sistema cuenta SOLO
        #    lo que entró DESPUÉS del cierre del mediodía (si lo hubo). Así no se
        #    duplica la plata de la mañana (ya contada al mediodía) y la auditoría
        #    declarado-vs-sistema da bien. Si no hubo cierre de mediodía, cuenta
        #    todo el día (correcto, porque no hay nada contado antes).
        desde_turno = None
        if turno == "noche" and ofi_id:
            cierre_med = (
                CierreCaja.objects.filter(
                    oficina_id=ofi_id, turno="mediodia", creado_en__date=fecha_hoy
                )
                .order_by("-creado_en")
                .first()
            )
            if cierre_med:
                desde_turno = cierre_med.creado_en

        # 🛡️ FIX: filtramos por el ID real de la sucursal (oficina_id), no por el código.
        #         Además envolvemos el cálculo en try/except para que un error acá
        #         NUNCA bloquee el cierre del empleado (a lo sumo queda monto_sistema = 0).
        try:
            if ofi_id:
                ing_qs = Ingreso.objects.filter(
                    fecha=fecha_hoy, oficina_id=ofi_id, forma_pago__iexact="EFECTIVO"
                )
                egr_qs = Egreso.objects.filter(
                    fecha=fecha_hoy, oficina_id=ofi_id, forma_pago__iexact="EFECTIVO"
                )
                # Acota al turno por la hora real del movimiento (created_at).
                if desde_turno is not None:
                    ing_qs = ing_qs.filter(created_at__gt=desde_turno)
                    egr_qs = egr_qs.filter(created_at__gt=desde_turno)

                ingresos = ing_qs.aggregate(tot=Sum('monto'))['tot'] or Decimal('0.00')
                egresos = egr_qs.aggregate(tot=Sum('monto'))['tot'] or Decimal('0.00')
                monto_sistema = ingresos - egresos
        except Exception:
            # Si el cálculo falla por cualquier motivo, no rompemos el cierre.
            monto_sistema = Decimal('0.00')

        monto_declarado = serializer.validated_data.get('monto_declarado')
        diferencia = Decimal('0.00')
        estado_auditoria = "PENDIENTE"

        if monto_declarado is not None:
            try:
                diferencia = Decimal(str(monto_declarado)) - monto_sistema
                if diferencia == 0:
                    estado_auditoria = "OK"
                elif diferencia > 0:
                    estado_auditoria = "SOBRANTE"
                else:
                    estado_auditoria = "FALTANTE"
            except Exception:
                diferencia = Decimal('0.00')
                estado_auditoria = "PENDIENTE"

        # 🚀 Guardamos el empleado (lo saca automáticamente del payload)
        cierre = serializer.save(
            usuario=user,
            oficina_id=ofi_id,
            turno=turno,
            monto_sistema=monto_sistema,
            diferencia=diferencia,
            estado_auditoria=estado_auditoria
        )

        # 🏆 Puntos al ranking: OK +3, FALTANTE -1 (sobrante = 0). Blindado.
        try:
            puntos_cierre = {"OK": 3, "FALTANTE": -1}.get(estado_auditoria, 0)
            if puntos_cierre and getattr(user, "is_authenticated", False):
                from ranking.services import otorgar_puntos
                otorgar_puntos(
                    usuario=user,
                    puntos=puntos_cierre,
                    categoria="pago",
                    oficina=ofi_id,
                    detalle=f"Cierre {turno} ({estado_auditoria})",
                    fecha=fecha_hoy,
                    ref=f"cierre:{ofi_id}:{fecha_hoy.isoformat()}:{turno}",
                )
        except Exception:
            pass

        # 🔔 Aviso automático del cierre (WhatsApp + email). Blindado: NO rompe el cierre.
        try:
            from notificaciones.cierre_caja import notificar_cierre_caja
            notificar_cierre_caja(cierre)
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════
    # 🚀 Estadísticas de cierres por oficina
    #     GET /api/recaudacion/estadisticas/
    #     Opcionales: ?desde=YYYY-MM-DD&hasta=YYYY-MM-DD&oficina=<id>
    # ══════════════════════════════════════════════════════════════
    @action(detail=False, methods=['get'])
    def estadisticas(self, request):
        qs = self.get_queryset()

        desde = request.query_params.get('desde')
        hasta = request.query_params.get('hasta')
        d1 = parse_date(desde) if desde else None
        d2 = parse_date(hasta) if hasta else None
        if d1:
            qs = qs.filter(creado_en__date__gte=d1)
        if d2:
            qs = qs.filter(creado_en__date__lte=d2)

        filas = (
            qs.values('oficina_id', 'oficina__nombre')
            .annotate(
                total=Count('id'),
                ok=Count('id', filter=Q(estado_auditoria='OK')),
                sobrante=Count('id', filter=Q(estado_auditoria='SOBRANTE')),
                faltante=Count('id', filter=Q(estado_auditoria='FALTANTE')),
                pendiente=Count('id', filter=Q(estado_auditoria='PENDIENTE')),
            )
            .order_by('-total')
        )

        por_oficina = []
        for f in filas:
            total = f['total'] or 0
            ok = f['ok'] or 0
            por_oficina.append({
                'oficina_id': f['oficina_id'],
                'oficina_nombre': f['oficina__nombre'] or 'Sin sucursal',
                'total': total,
                'ok': ok,
                'sobrante': f['sobrante'] or 0,
                'faltante': f['faltante'] or 0,
                'pendiente': f['pendiente'] or 0,
                'pct_coincidencia': round((ok / total) * 100, 1) if total else 0.0,
            })

        totales = {
            'total': sum(r['total'] for r in por_oficina),
            'ok': sum(r['ok'] for r in por_oficina),
            'sobrante': sum(r['sobrante'] for r in por_oficina),
            'faltante': sum(r['faltante'] for r in por_oficina),
            'pendiente': sum(r['pendiente'] for r in por_oficina),
        }
        totales['pct_coincidencia'] = (
            round((totales['ok'] / totales['total']) * 100, 1) if totales['total'] else 0.0
        )

        return Response({'por_oficina': por_oficina, 'totales': totales})

    # ══════════════════════════════════════════════════════════════
    # 🚀 NUEVO: Calendario de cierres (estado de cada día del mes)
    #     GET /api/recaudacion/calendario/?mes=YYYY-MM&oficina=<id>
    #     Devuelve SOLO los días que tuvieron cierre (con su estado).
    #     Los días que no aparecen = no se cerró caja ese día.
    # ══════════════════════════════════════════════════════════════
    @action(detail=False, methods=['get'])
    def calendario(self, request):
        qs = self.get_queryset()

        # Mes solicitado (YYYY-MM). Si no viene, usamos el mes actual.
        mes = (request.query_params.get('mes') or '').strip()
        hoy = timezone.localdate()
        try:
            y, m = mes.split('-')[:2]
            y, m = int(y), int(m)
        except Exception:
            y, m = hoy.year, hoy.month

        d1 = date(y, m, 1)
        d2 = date(y, m, _calendar.monthrange(y, m)[1])

        qs = qs.filter(creado_en__date__gte=d1, creado_en__date__lte=d2).order_by('creado_en')

        dias = {}
        for c in qs:
            try:
                fkey = timezone.localtime(c.creado_en).date().isoformat()
            except Exception:
                fkey = c.creado_en.date().isoformat()
            prev = dias.get(fkey)
            cnt = (prev['count'] + 1) if prev else 1
            # Como el queryset viene ordenado ascendente, nos quedamos con el ÚLTIMO cierre del día
            dias[fkey] = {
                'estado': c.estado_auditoria or 'PENDIENTE',
                'diferencia': str(c.diferencia if c.diferencia is not None else '0.00'),
                'count': cnt,
            }

        return Response({
            'mes': f"{y:04d}-{m:02d}",
            'desde': d1.isoformat(),
            'hasta': d2.isoformat(),
            'dias': dias,
        })

    # ══════════════════════════════════════════════════════════════
    # 🚀 NUEVO: Quién cerró / NO cerró en un día (todas las sucursales)
    #     GET /api/recaudacion/estado-dia/?fecha=YYYY-MM-DD  (default: hoy)
    #     Incluye TODAS las oficinas, hasta las que nunca cerraron.
    # ══════════════════════════════════════════════════════════════
    @action(detail=False, methods=['get'], url_path='estado-dia')
    def estado_dia(self, request):
        from usuarios.models import Oficina

        fecha = parse_date(request.query_params.get('fecha') or '') or timezone.localdate()

        # Cierres de ese día (respeta permisos por get_queryset)
        cerradas = {}
        for c in self.get_queryset().filter(creado_en__date=fecha):
            if c.oficina_id and c.oficina_id not in cerradas:
                cerradas[c.oficina_id] = c.estado_auditoria or 'PENDIENTE'

        # Lista de oficinas (admin = todas, empleado = solo la suya)
        user = request.user
        es_admin = user.is_superuser or (hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN')
        oficinas = Oficina.objects.all().order_by('nombre')
        if not es_admin:
            ofi_id = getattr(user.perfil, 'oficina_id', None) if hasattr(user, 'perfil') else None
            oficinas = oficinas.filter(id=ofi_id) if ofi_id else Oficina.objects.none()

        data = []
        for o in oficinas:
            data.append({
                'oficina_id': o.id,
                'oficina_nombre': o.nombre,
                'cerro': o.id in cerradas,
                'estado': cerradas.get(o.id),
            })

        pendientes = [d['oficina_nombre'] for d in data if not d['cerro']]
        return Response({
            'fecha': fecha.isoformat(),
            'oficinas': data,
            'cerraron': sum(1 for d in data if d['cerro']),
            'total': len(data),
            'pendientes': pendientes,
        })

    # ══════════════════════════════════════════════════════════════
    # 🚀 NUEVO: Ranking de cumplimiento por oficina (días cerrados del mes)
    #     GET /api/recaudacion/ranking/?mes=YYYY-MM
    #     Devuelve, por oficina, la lista de DÍAS DISTINTOS que cerró.
    #     El front calcula "debía/faltó/%" según Lun-Vie / Lun-Sáb / Todos.
    # ══════════════════════════════════════════════════════════════
    @action(detail=False, methods=['get'])
    def ranking(self, request):
        from usuarios.models import Oficina

        mes = (request.query_params.get('mes') or '').strip()
        hoy = timezone.localdate()
        try:
            y, m = mes.split('-')[:2]
            y, m = int(y), int(m)
        except Exception:
            y, m = hoy.year, hoy.month

        d1 = date(y, m, 1)
        d2 = date(y, m, _calendar.monthrange(y, m)[1])

        qs = self.get_queryset().filter(creado_en__date__gte=d1, creado_en__date__lte=d2)

        # Días distintos cerrados por oficina
        cerrados = {}
        for c in qs:
            if not c.oficina_id:
                continue
            try:
                fkey = timezone.localtime(c.creado_en).date().isoformat()
            except Exception:
                fkey = c.creado_en.date().isoformat()
            cerrados.setdefault(c.oficina_id, set()).add(fkey)

        user = request.user
        es_admin = user.is_superuser or (hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN')
        oficinas = Oficina.objects.all().order_by('nombre')
        if not es_admin:
            ofi_id = getattr(user.perfil, 'oficina_id', None) if hasattr(user, 'perfil') else None
            oficinas = oficinas.filter(id=ofi_id) if ofi_id else Oficina.objects.none()

        data = []
        for o in oficinas:
            data.append({
                'oficina_id': o.id,
                'oficina_nombre': o.nombre,
                'dias_cerrados': sorted(cerrados.get(o.id, set())),
            })

        return Response({'mes': f"{y:04d}-{m:02d}", 'oficinas': data})

# ══════════════════════════════════════════════════════════════
# 🕒 Horarios de cierre de caja por oficina (2 turnos)
# ══════════════════════════════════════════════════════════════
from rest_framework.views import APIView
from .models import HorarioCierreCaja
from .serializers import HorarioCierreCajaSerializer


def _es_admin_user(user):
    return bool(user and (user.is_superuser or (
        hasattr(user, 'perfil') and user.perfil.rol == 'ADMIN'
    )))


class HorariosCierreView(APIView):
    """
    GET  /api/recaudacion/horarios-cierre/        → lista todos (admin)
    POST /api/recaudacion/horarios-cierre/        → crea/actualiza el de una oficina (admin)
         body: {oficina, mediodia, noche, aviso_min, tolerancia_min, activo}
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not _es_admin_user(request.user):
            return Response({"detail": "Solo admin."}, status=403)
        qs = HorarioCierreCaja.objects.select_related('oficina').all()
        return Response(HorarioCierreCajaSerializer(qs, many=True).data)

    def post(self, request):
        if not _es_admin_user(request.user):
            return Response({"detail": "Solo admin."}, status=403)
        oficina_id = request.data.get('oficina')
        if not oficina_id:
            return Response({"detail": "Falta la oficina."}, status=400)

        def _hora(v):
            v = (v or "").strip()
            return v or None

        obj, _ = HorarioCierreCaja.objects.update_or_create(
            oficina_id=oficina_id,
            defaults={
                "mediodia": _hora(request.data.get('mediodia')),
                "noche": _hora(request.data.get('noche')),
                "aviso_min": int(request.data.get('aviso_min') or 30),
                "tolerancia_min": int(request.data.get('tolerancia_min') or 5),
                "activo": bool(request.data.get('activo', True)),
            },
        )
        return Response(HorarioCierreCajaSerializer(obj).data)


class MiHorarioCierreView(APIView):
    """
    GET /api/recaudacion/mi-horario-cierre/
    Devuelve el horario de cierre de la oficina del usuario logueado
    + si ya cerró cada turno hoy (para que el pop-up sepa si avisar).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        ofi_id = getattr(user.perfil, 'oficina_id', None) if hasattr(user, 'perfil') else None
        if not ofi_id:
            return Response({"tiene": False})

        try:
            h = HorarioCierreCaja.objects.get(oficina_id=ofi_id, activo=True)
        except HorarioCierreCaja.DoesNotExist:
            return Response({"tiene": False})
        except Exception:
            # La tabla/campo todavía no migró (u otro problema de BD):
            # no rompemos el front, simplemente no hay horario.
            return Response({"tiene": False})

        try:
            hoy = timezone.localdate()
            turnos_cerrados = list(
                CierreCaja.objects.filter(oficina_id=ofi_id, creado_en__date=hoy)
                .exclude(turno="").values_list('turno', flat=True)
            )
        except Exception:
            # Si el campo 'turno' aún no existe en la BD, seguimos sin romper.
            turnos_cerrados = []

        return Response({
            "tiene": True,
            "oficina_id": ofi_id,
            "mediodia": h.mediodia.strftime("%H:%M") if h.mediodia else None,
            "noche": h.noche.strftime("%H:%M") if h.noche else None,
            "aviso_min": getattr(h, "aviso_min", 30),
            "tolerancia_min": getattr(h, "tolerancia_min", 5),
            "cerrados_hoy": turnos_cerrados,  # ej: ["mediodia"]
        })