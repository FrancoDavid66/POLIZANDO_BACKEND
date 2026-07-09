# polizas/views/mixins/kpis.py

from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated # 🚀 CAMBIADO A IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from django.db.models import Count, Q
from django.utils import timezone

from datetime import timedelta

from polizas.models import Poliza
from polizas.utils.constants import normalizar_compania
from polizas.utils.viewtools import annotate_mora as _annotate_mora, apply_financial_bucket, apply_vencimiento_filters


class PolizaKpisMixin:
    @action(detail=False, methods=["get"], url_path="kpis", permission_classes=[IsAuthenticated])
    def kpis(self, request):
        params = self.request.query_params
        
        # 🚀 CLAVE DE SEGURIDAD: Usamos self.get_queryset() en lugar de Poliza.objects.all()
        # Esto obliga a que los gráficos pasen por el MultiTenantMixin
        base_all = self.get_queryset().order_by("id")

        estado = (params.get("estado") or "").strip()
        compania = (params.get("compania") or "").strip()
        cliente_id = (params.get("cliente") or "").strip()
        patente = (params.get("patente") or "").strip()
        solo_activas = (params.get("solo_activas") or "").lower() in {"1", "true", "t", "yes", "y"}
        fase = (params.get("fase") or "").strip()
        sin_numero = (params.get("sin_numero") or "").lower() in {"1", "true", "t", "yes", "y"}
        oficina = (params.get("oficina") or "").strip()

        asegurado_q = (params.get("asegurado") or params.get("asegurado_nombre") or "").strip()
        if asegurado_q:
            tokens = [t for t in asegurado_q.split() if t]
            for t in tokens:
                base_all = base_all.filter(Q(cliente__nombre__icontains=t) | Q(cliente__apellido__icontains=t))

        if estado:
            base_all = base_all.filter(estado=estado)

        if compania:
            try:
                compania_canon = normalizar_compania(compania)
                base_all = base_all.filter(compania__iexact=compania_canon)
            except Exception:
                base_all = base_all.filter(compania__iexact=compania)

        if cliente_id.isdigit():
            base_all = base_all.filter(cliente_id=int(cliente_id))
        if patente:
            base_all = base_all.filter(patente__iexact=patente)
        if solo_activas:
            base_all = base_all.filter(estado="activa")
        if fase:
            base_all = base_all.filter(fase=fase)
        if sin_numero:
            base_all = base_all.filter(sin_numero=True)

        # Si es admin y mandó filtro de oficina, lo aplicamos. Si no es admin, el Mixin ya lo filtró.
        if oficina:
            base_all = self._apply_oficina_filter(base_all, oficina)

        base_all = apply_financial_bucket(base_all, (params.get("estado_financiero") or ""))
        base_all = apply_vencimiento_filters(base_all, params)

        for backend in self.filter_backends:
            base_all = backend().filter_queryset(request, base_all, self)

        hoy = timezone.localdate()
        activas = _annotate_mora(base_all.filter(estado="activa"), hoy)

        por_estado = {
            "activa":          base_all.filter(estado="activa").count(),
            "vencida":         base_all.filter(estado="vencida").count(),
            "cancelada":       base_all.filter(estado="cancelada").count(),
            "finalizada":      base_all.filter(estado="finalizada").count(),
            "en_verificacion": base_all.filter(estado="en_verificacion").count(),
        }

        kpis_fin = {
            "activas_al_dia": activas.filter(overdue_exists=False).count(),
            "activas_mora_1_30": activas.filter(min_overdue__gte=hoy - timedelta(days=30), min_overdue__lt=hoy).count(),
            "activas_mora_31_60": activas.filter(min_overdue__gte=hoy - timedelta(days=60), min_overdue__lt=hoy - timedelta(days=30)).count(),
            "activas_mora_61_90": activas.filter(min_overdue__gte=hoy - timedelta(days=90), min_overdue__lt=hoy - timedelta(days=60)).count(),
            "activas_mora_90_mas": activas.filter(min_overdue__lt=hoy - timedelta(days=90)).count(),
        }

        por_compania = {row["compania"] or "—": row["c"] for row in base_all.values("compania").annotate(c=Count("id")).order_by()}

        por_cobertura = None
        if hasattr(Poliza, "cobertura"):
            por_cobertura = {row["cobertura"] or "—": row["c"] for row in base_all.values("cobertura").annotate(c=Count("id")).order_by()}

        por_tipo = None
        if hasattr(Poliza, "tipo"):
            por_tipo = {row["tipo"] or "—": row["c"] for row in base_all.values("tipo").annotate(c=Count("id")).order_by()}

        # Desglose renovaciones vs altas nuevas
        tiene_es_renovacion = hasattr(Poliza, "es_renovacion")
        renovaciones_total = base_all.filter(es_renovacion=True).count() if tiene_es_renovacion else 0
        altas_nuevas_total = base_all.filter(es_renovacion=False).count() if tiene_es_renovacion else base_all.count()

        payload = {
            **kpis_fin,
            "vencidas":          por_estado["vencida"],
            "canceladas":        por_estado["cancelada"],
            "finalizadas":       por_estado["finalizada"],
            "en_verificacion":   por_estado["en_verificacion"],
            "total":             base_all.count(),
            "renovaciones_total": renovaciones_total,
            "altas_nuevas_total": altas_nuevas_total,
            "por_estado":        por_estado,
            "por_compania":      por_compania,
            "por_cobertura":     por_cobertura,
            "por_tipo":          por_tipo,
            "total_global":      self.get_queryset().count(),
        }
        return Response(payload, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="resumen-estados", permission_classes=[IsAuthenticated])
    def resumen_estados(self, request):
        today = timezone.localdate()
        qs = self.get_queryset()

        # Mora REAL = la cobertura (vto de la última cuota PAGADA) ya venció y quedan impagas.
        # Las cuotas se pagan por adelantado, así que NO alcanza con mirar el vto propio de la impaga.
        from django.db.models import Min, Max, Count, Q as Qm, F as _F
        from django.db.models.functions import Coalesce as _Coalesce

        qs_con_cuota_info = qs.annotate(
            cobertura_hasta=Max("cuotas__fecha_vencimiento", filter=Qm(cuotas__pagado=True)),
            impagas=Count("cuotas", filter=Qm(cuotas__pagado=False)),
            primer_impaga=Min("cuotas__fecha_vencimiento", filter=Qm(cuotas__pagado=False)),
        ).annotate(
            # "corte" = hasta cuándo está cubierta (o, si nunca pagó, el vto de su 1ra cuota).
            corte=_Coalesce(_F("cobertura_hasta"), _F("primer_impaga")),
        )

        # Activas al día = sin cuotas impagas, o todavía cubiertas (corte hoy o más adelante).
        al_dia = qs_con_cuota_info.filter(estado="activa").filter(
            Qm(impagas=0) | Qm(corte__gte=today)
        ).count()

        # Activas con mora 1-7 días (la cobertura venció hace 1 a 7 días)
        mora_1_7 = qs_con_cuota_info.filter(
            estado="activa",
            impagas__gt=0,
            corte__isnull=False,
            corte__gte=today - timedelta(days=7),
            corte__lt=today,
        ).count()

        # Activas con mora 8-30 días
        mora_8_30 = qs_con_cuota_info.filter(
            estado="activa",
            impagas__gt=0,
            corte__isnull=False,
            corte__gte=today - timedelta(days=30),
            corte__lt=today - timedelta(days=7),
        ).count()

        # Vencidas (estado="vencida") — mora > 60 días
        vencidas = qs.filter(estado="vencida").count()

        # En verificación
        en_verificacion = qs.filter(estado="en_verificacion").count()

        resumen = {
            "al_dia":           al_dia,
            "mora_1_7":         mora_1_7,
            "mora_8_30":        mora_8_30,
            "vencidas":         vencidas,
            "en_verificacion":  en_verificacion,
            "canceladas":       qs.filter(estado="cancelada").count(),
            "finalizadas":      qs.filter(estado="finalizada").count(),
            "todos":            qs.count(),
            # Aliases para compatibilidad con el front existente
            "por_vencer":       mora_1_7,
            "vencida_7":        mora_1_7,
            "vencida_30":       mora_8_30,
        }
        return Response(resumen, status=status.HTTP_200_OK)