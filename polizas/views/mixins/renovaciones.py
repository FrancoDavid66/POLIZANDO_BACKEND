# polizas/views/mixins/renovaciones.py

from django.utils import timezone
from datetime import timedelta

from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated # 🚀 CAMBIO VITAL: Reemplazamos AllowAny por IsAuthenticated
from rest_framework.response import Response
from rest_framework import status, filters

from polizas.models import Poliza
from django.db.models import OuterRef, Subquery, DateField
from polizas.domain.renovadas import exclude_ya_renovadas
from polizas.domain.robo import ensure_cupones_robo_for_poliza
from polizas.services.renovaciones import build_renovaciones_queryset, build_renovaciones_resumen
from polizas.handlers.renovacion import handle_renovar_poliza, handle_duplicar_renovacion

# 🆕 Sistema de errores estructurados
from polizas.utils.errors import RenovacionError, ErrorCodes


class PolizaRenovacionesMixin:
    # 🚀 BLINDAJE: Solo usuarios autenticados
    @action(detail=False, methods=["get"], url_path="renovaciones", permission_classes=[IsAuthenticated])
    def renovaciones(self, request):
        base_qs = self.get_queryset()
        
        # 🚀 ESCUDO DE SUCURSAL: Garantizamos que si no es Admin, solo vea su oficina
        user = request.user
        is_admin = user.is_superuser or getattr(user.perfil, 'rol', '') == 'ADMIN'
        if not is_admin:
            ofi_id = getattr(user.perfil, 'oficina_id', None)
            if ofi_id:
                base_qs = base_qs.filter(oficina_id=ofi_id)

        for backend in self.filter_backends:
            if backend is filters.OrderingFilter:
                continue
            base_qs = backend().filter_queryset(request, base_qs, self)

        base_qs = exclude_ya_renovadas(base_qs, request, Poliza)

        qs = build_renovaciones_queryset(base_qs, request.query_params)

        if (request.query_params.get("ordering") or "").strip():
            qs = filters.OrderingFilter().filter_queryset(request, qs, self)

        page = self.paginate_queryset(qs)
        if page is not None:
            ser = self.get_serializer(page, many=True)
            return self.get_paginated_response(ser.data)

        ser = self.get_serializer(qs, many=True)
        return Response(ser.data, status=status.HTTP_200_OK)

    # 🚀 BLINDAJE: Solo usuarios autenticados
    @action(detail=False, methods=["get"], url_path="renovaciones/resumen", permission_classes=[IsAuthenticated])
    def renovaciones_resumen(self, request):
        base_qs = self.get_queryset()
        
        # 🚀 ESCUDO DE SUCURSAL PARA LOS KPIs
        user = request.user
        is_admin = user.is_superuser or getattr(user.perfil, 'rol', '') == 'ADMIN'
        if not is_admin:
            ofi_id = getattr(user.perfil, 'oficina_id', None)
            if ofi_id:
                base_qs = base_qs.filter(oficina_id=ofi_id)

        for backend in self.filter_backends:
            if backend is filters.OrderingFilter:
                continue
            base_qs = backend().filter_queryset(request, base_qs, self)

        base_qs = exclude_ya_renovadas(base_qs, request, Poliza)

        payload = build_renovaciones_resumen(base_qs, request.query_params)
        return Response(payload, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="renovaciones/recientes", permission_classes=[IsAuthenticated])
    def renovaciones_recientes(self, request):
        """
        Pólizas que YA finalizaron pero hace poco (tolerancia de 3 días) y todavía
        no se renovaron. El módulo de Renovaciones normal las esconde (porque no tienen
        cuota por vencer); acá las mostramos para que no se pierdan y se puedan renovar.
        """
        TOLERANCIA_DIAS = 3
        hoy = timezone.localdate()
        limite = hoy - timedelta(days=TOLERANCIA_DIAS)

        # 🆕 Refrescamos estados para que las vencidas-pagadas figuren ya como finalizadas.
        try:
            from polizas.views.poliza import auto_marcar_vencidas
            auto_marcar_vencidas()
        except Exception:
            pass

        # OJO: este action NO está en la lista que excluye finalizadas en get_queryset,
        # así que acá las finalizadas SÍ vienen.
        base_qs = self.get_queryset()

        # 🚀 ESCUDO DE SUCURSAL: si no es admin, solo su oficina
        user = request.user
        is_admin = user.is_superuser or getattr(user.perfil, 'rol', '') == 'ADMIN'
        if not is_admin:
            ofi_id = getattr(user.perfil, 'oficina_id', None)
            if ofi_id:
                base_qs = base_qs.filter(oficina_id=ofi_id)

        # Solo finalizadas cuya ÚLTIMA cuota venció dentro de la ventana de tolerancia.
        # (Usamos la última cuota, el mismo criterio con que el sistema las finaliza,
        #  en vez de poliza.fecha_vencimiento que puede no estar cargada.)
        from pagos.models import Cuota
        ultima_vto_sq = Subquery(
            Cuota.objects.filter(poliza_id=OuterRef("pk"))
            .order_by("-fecha_vencimiento")
            .values("fecha_vencimiento")[:1],
            output_field=DateField(),
        )

        qs = (
            base_qs.filter(estado__iexact="finalizada")
            .annotate(ult_cuota_vto=ultima_vto_sq)
            .filter(ult_cuota_vto__gte=limite, ult_cuota_vto__lte=hoy)
        )

        # Sin las que ya tienen una renovación hecha
        qs = exclude_ya_renovadas(qs, request, Poliza)

        qs = qs.select_related("cliente", "compania_obj").order_by("-ult_cuota_vto")

        page = self.paginate_queryset(qs)
        if page is not None:
            ser = self.get_serializer(page, many=True)
            return self.get_paginated_response(ser.data)

        ser = self.get_serializer(qs, many=True)
        return Response(ser.data, status=status.HTTP_200_OK)

    # 🚀 BLINDAJE: Protegemos la refacturación
    @action(detail=True, methods=["post"], url_path="refacturar", permission_classes=[IsAuthenticated])
    def refacturar(self, request, pk=None):
        original = self.get_object()

        # 🚦 Validaciones previas
        if original.estado == "finalizada":
            err = RenovacionError(ErrorCodes.POLIZA_FINALIZADA, context={"poliza_id": original.id})
            return Response(err.to_dict(), status=err.http_status)

        # 🆕 Capturar RenovacionError del handler y devolver JSON estructurado
        try:
            resp = handle_duplicar_renovacion(request, original)
        except RenovacionError as e:
            return Response(e.to_dict(), status=e.http_status)

        if resp.status_code in (200, 201):
            nueva_id = None
            try:
                nueva_id = resp.data.get("id")
            except Exception:
                nueva_id = None

            if nueva_id:
                try:
                    nueva_poliza = Poliza.objects.get(id=nueva_id)
                    # Marcar como renovación y vincular a la póliza origen
                    nueva_poliza.es_renovacion = True
                    nueva_poliza.poliza_origen = original
                    nueva_poliza.save(update_fields=["es_renovacion", "poliza_origen"])
                    try:
                        ensure_cupones_robo_for_poliza(nueva_poliza)
                    except Exception:
                        pass
                except Poliza.DoesNotExist:
                    pass

            self._hist_log(
                poliza=original,
                tipo="POLIZA_REFACTURAR",
                mensaje="Póliza refacturada (se creó nueva versión)",
                severidad="ACTION",
                data={"nueva_poliza_id": nueva_id},
                request=request,
                subject=original,
                categoria="POLIZA",
            )
        return resp

    # 🚀 BLINDAJE EXPLÍCITO
    @action(detail=True, methods=["post"], url_path="renovar", permission_classes=[IsAuthenticated])
    def renovar_poliza(self, request, pk=None):
        poliza = self.get_object()

        # 🚦 Validaciones previas
        # 1) Si ya existe una versión más nueva (la póliza ya fue renovada) → bloquear.
        #    Este es el candado real contra renovar dos veces, sirva la póliza que sirva.
        existe_renovacion = Poliza.objects.filter(
            poliza_origen=poliza
        ).order_by("-id").first()
        if existe_renovacion:
            err = RenovacionError(
                ErrorCodes.POLIZA_YA_RENOVADA,
                context={
                    "poliza_id": poliza.id,
                    "nueva_poliza_id": existe_renovacion.id,
                    "nueva_numero": existe_renovacion.numero_poliza,
                    "nueva_fecha": str(existe_renovacion.fecha_emision) if existe_renovacion.fecha_emision else None,
                }
            )
            return Response(err.to_dict(), status=err.http_status)

        # 2) Una póliza FINALIZADA por ciclo cumplido SÍ se puede renovar (cliente que volvió).
        #    Solo se bloquea si ya tenía renovación, y eso ya lo cubre el candado de arriba.

        # 🆕 Capturar RenovacionError del handler
        try:
            resp = handle_renovar_poliza(request, poliza)
        except RenovacionError as e:
            return Response(e.to_dict(), status=e.http_status)

        if resp.status_code in (200, 201):
            nueva_id = None
            try:
                nueva_id = resp.data.get("id")
            except Exception:
                nueva_id = None

            if nueva_id:
                try:
                    nueva_poliza = Poliza.objects.get(id=nueva_id)
                    # Marcar como renovación y vincular a la póliza origen
                    nueva_poliza.es_renovacion = True
                    nueva_poliza.poliza_origen = poliza
                    nueva_poliza.save(update_fields=["es_renovacion", "poliza_origen"])
                    try:
                        ensure_cupones_robo_for_poliza(nueva_poliza)
                    except Exception:
                        pass
                except Poliza.DoesNotExist:
                    pass

            self._hist_log(
                poliza=poliza,
                tipo="POLIZA_RENOVAR",
                mensaje="Póliza renovada (se creó nueva versión)",
                severidad="ACTION",
                data={"nueva_poliza_id": nueva_id},
                request=request,
                subject=poliza,
                categoria="POLIZA",
            )
        return resp

    # 🚀 BLINDAJE EXPLÍCITO
    @action(detail=True, methods=["post"], url_path="duplicar-renovacion", permission_classes=[IsAuthenticated])
    def duplicar_renovacion(self, request, pk=None):
        original = self.get_object()

        # 🚦 Validaciones previas (mismas reglas que renovar_poliza)
        existe_renovacion = Poliza.objects.filter(
            poliza_origen=original
        ).order_by("-id").first()
        if existe_renovacion:
            err = RenovacionError(
                ErrorCodes.POLIZA_YA_RENOVADA,
                context={
                    "poliza_id": original.id,
                    "nueva_poliza_id": existe_renovacion.id,
                    "nueva_numero": existe_renovacion.numero_poliza,
                    "nueva_fecha": str(existe_renovacion.fecha_emision) if existe_renovacion.fecha_emision else None,
                }
            )
            return Response(err.to_dict(), status=err.http_status)

        try:
            resp = handle_duplicar_renovacion(request, original)
        except RenovacionError as e:
            return Response(e.to_dict(), status=e.http_status)

        if resp.status_code in (200, 201):
            nueva_id = None
            try:
                nueva_id = resp.data.get("id")
            except Exception:
                nueva_id = None

            if nueva_id:
                try:
                    nueva_poliza = Poliza.objects.get(id=nueva_id)
                    # Marcar como renovación y vincular a la póliza origen
                    nueva_poliza.es_renovacion = True
                    nueva_poliza.poliza_origen = original
                    nueva_poliza.save(update_fields=["es_renovacion", "poliza_origen"])
                    try:
                        ensure_cupones_robo_for_poliza(nueva_poliza)
                    except Exception:
                        pass
                except Poliza.DoesNotExist:
                    pass

            self._hist_log(
                poliza=original,
                tipo="POLIZA_RENOVAR",
                mensaje="Póliza renovada (alias duplicar-renovacion)",
                severidad="ACTION",
                data={"nueva_poliza_id": nueva_id},
                request=request,
                subject=original,
                categoria="POLIZA",
            )
        return resp

    # ════════════════════════════════════════════════════════════════
    # 🆕 BANDEJA DE RENOVACIONES — gestión operativa
    # Estos endpoints NO tocan el estado real de la póliza.
    # Solo marcan banderas de gestión (verificada / descartada) para
    # que el operador organice su trabajo.
    # ════════════════════════════════════════════════════════════════

    # ── ✓ Verificar renovación ──
    @action(detail=True, methods=["post"], url_path="verificar-renovacion",
            permission_classes=[IsAuthenticated])
    def verificar_renovacion(self, request, pk=None):
        """Marca la póliza como verificada en la bandeja (tilde gris)."""
        poliza = self.get_object()
        poliza.renovacion_verificada = True
        poliza.renovacion_verificada_en = timezone.now()
        poliza.save(update_fields=["renovacion_verificada", "renovacion_verificada_en"])

        try:
            self._hist_log(
                poliza=poliza,
                tipo="RENOVACION_VERIFICADA",
                mensaje="Póliza marcada como verificada en bandeja de renovaciones",
                severidad="INFO",
                request=request,
                subject=poliza,
                categoria="POLIZA",
            )
        except Exception:
            pass

        return Response({
            "id": poliza.id,
            "renovacion_verificada": True,
            "renovacion_verificada_en": poliza.renovacion_verificada_en,
        }, status=status.HTTP_200_OK)

    # ── Des-verificar (deshacer) ──
    @action(detail=True, methods=["delete", "post"], url_path="des-verificar-renovacion",
            permission_classes=[IsAuthenticated])
    def des_verificar_renovacion(self, request, pk=None):
        """Deshace el 'verificada'."""
        poliza = self.get_object()
        poliza.renovacion_verificada = False
        poliza.renovacion_verificada_en = None
        poliza.save(update_fields=["renovacion_verificada", "renovacion_verificada_en"])

        try:
            self._hist_log(
                poliza=poliza,
                tipo="RENOVACION_DES_VERIFICADA",
                mensaje="Se deshizo la verificación de renovación",
                severidad="INFO",
                request=request,
                subject=poliza,
                categoria="POLIZA",
            )
        except Exception:
            pass

        return Response({
            "id": poliza.id,
            "renovacion_verificada": False,
        }, status=status.HTTP_200_OK)

    # ── ✗ Descartar (no renueva) ──
    @action(detail=True, methods=["post"], url_path="descartar-renovacion",
            permission_classes=[IsAuthenticated])
    def descartar_renovacion(self, request, pk=None):
        """
        Marca al cliente como que NO va a renovar.
        NO toca el estado real de la póliza (sigue activa hasta su vencimiento natural).

        Body: { "motivo": "CAMBIO_COMPANIA"|"VENDIO_AUTO"|"NO_QUIERE"|"NO_CONTESTA"|"NO_PAGO"|"OTRO",
                "detalle": "texto libre opcional" }
        """
        poliza = self.get_object()

        motivo = (request.data.get("motivo") or "").strip().upper()
        detalle = (request.data.get("detalle") or "").strip()

        motivos_validos = {choice[0] for choice in Poliza.MotivoNoRenueva.choices}
        if motivo and motivo not in motivos_validos:
            return Response(
                {"error": f"Motivo inválido. Válidos: {sorted(motivos_validos)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        poliza.renovacion_descartada = True
        poliza.renovacion_descartada_motivo = motivo or Poliza.MotivoNoRenueva.OTRO
        poliza.renovacion_descartada_detalle = detalle
        poliza.renovacion_descartada_en = timezone.now()
        poliza.save(update_fields=[
            "renovacion_descartada",
            "renovacion_descartada_motivo",
            "renovacion_descartada_detalle",
            "renovacion_descartada_en",
        ])

        try:
            self._hist_log(
                poliza=poliza,
                tipo="RENOVACION_DESCARTADA",
                mensaje=f"Cliente no renueva. Motivo: {poliza.renovacion_descartada_motivo}"
                        + (f" — {detalle}" if detalle else ""),
                severidad="WARNING",
                request=request,
                subject=poliza,
                categoria="POLIZA",
                data={"motivo": poliza.renovacion_descartada_motivo, "detalle": detalle},
            )
        except Exception:
            pass

        return Response({
            "id": poliza.id,
            "renovacion_descartada": True,
            "renovacion_descartada_motivo": poliza.renovacion_descartada_motivo,
            "renovacion_descartada_detalle": poliza.renovacion_descartada_detalle,
            "renovacion_descartada_en": poliza.renovacion_descartada_en,
        }, status=status.HTTP_200_OK)

    # ── Revertir descarte ──
    @action(detail=True, methods=["delete", "post"], url_path="revertir-descarte-renovacion",
            permission_classes=[IsAuthenticated])
    def revertir_descarte_renovacion(self, request, pk=None):
        """Deshace el 'no renueva'. La póliza vuelve a la lista de pendientes."""
        poliza = self.get_object()
        poliza.renovacion_descartada = False
        poliza.renovacion_descartada_motivo = None
        poliza.renovacion_descartada_detalle = ""
        poliza.renovacion_descartada_en = None
        poliza.save(update_fields=[
            "renovacion_descartada",
            "renovacion_descartada_motivo",
            "renovacion_descartada_detalle",
            "renovacion_descartada_en",
        ])

        try:
            self._hist_log(
                poliza=poliza,
                tipo="RENOVACION_REVERTIDA",
                mensaje="Se revirtió el descarte de renovación. Vuelve a pendientes.",
                severidad="INFO",
                request=request,
                subject=poliza,
                categoria="POLIZA",
            )
        except Exception:
            pass

        return Response({
            "id": poliza.id,
            "renovacion_descartada": False,
        }, status=status.HTTP_200_OK)

    # ── Aliases legacy (el slice viejo los llamaba con otra URL) ──
    # Estos hacen lo mismo que `descartar_renovacion` y `revertir_descarte_renovacion`
    # pero responden a la URL vieja que ya tenía el frontend.
    @action(detail=True, methods=["post"], url_path="marcar-no-renueva",
            permission_classes=[IsAuthenticated])
    def marcar_no_renueva_alias(self, request, pk=None):
        return self.descartar_renovacion(request, pk=pk)

    @action(detail=True, methods=["delete"], url_path="marcar-no-renueva",
            permission_classes=[IsAuthenticated])
    def desmarcar_no_renueva_alias(self, request, pk=None):
        return self.revertir_descarte_renovacion(request, pk=pk)