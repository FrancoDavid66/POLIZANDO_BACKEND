# pagos/views.py
import calendar
from datetime import timedelta, date
from decimal import Decimal, InvalidOperation

from django.db import models, transaction
from django.http import FileResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.db.models import Q
from django.db.models import Count

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.permissions import IsAuthenticated

from .models import Pago, Cuota, MedioCobro, AlertaEnviada
from polizas.models import Poliza
from balanzes.models import Ingreso as BalanceIngreso
from solicitudes.models import Empleado

from pagos.handlers.registrar_pago import registrar_pago_handler, _enviar_gracias_portal
from pagos.utils.factura import generar_factura_pdf
from pagos.views_helpers import (
    _get_seguridad_oficina_brute,
    _build_oficina_q_from_keys,
    _to_bool,
)
from pagos.views_reportes import ReporteEfectividadMixin
from pagos.views_busqueda import BusquedaMixin
from pagos.views_historial import HistorialPagosMixin

MAX_HISTORIAL_ALL_ROWS = 50000


class MedioCobroViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = MedioCobro.objects.all()

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["proveedor", "tipo", "activo"]
    search_fields = ["valor", "etiqueta", "titular_nombre"]
    ordering_fields = ["creado", "actualizado", "ultimo_uso", "usos_totales"]
    ordering = ["-activo", "etiqueta", "proveedor", "tipo"]

    def get_serializer_class(self):
        from .serializers import MedioCobroSerializer
        return MedioCobroSerializer

    @action(detail=True, methods=["post"], url_path="activar")
    def activar(self, request, pk=None):
        obj = self.get_object()
        obj.activo = True
        obj.save(update_fields=["activo"])
        return Response({"detail": "Activado"}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="desactivar")
    def desactivar(self, request, pk=None):
        obj = self.get_object()
        obj.activo = False
        obj.save(update_fields=["activo"])
        return Response({"detail": "Desactivado"}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="marcar-uso")
    def marcar_uso(self, request, pk=None):
        obj = self.get_object()
        mark = getattr(obj, "marcar_uso", None)
        if callable(mark):
            mark()
        else:
            from django.utils import timezone as _tz
            obj.ultimo_uso = _tz.now()
            obj.usos_totales = (obj.usos_totales or 0) + 1
            obj.save(update_fields=["ultimo_uso", "usos_totales"])
        return Response({"detail": "Uso registrado"}, status=status.HTTP_200_OK)


class PagoViewSet(ReporteEfectividadMixin, BusquedaMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = Pago.objects.all().select_related("poliza", "cuota")

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["poliza", "cuota", "cuota_nro", "metodo", "registrado_en_balance"]
    search_fields = ["poliza__numero_poliza"]
    ordering_fields = ["fecha", "monto"]
    ordering = ["-fecha", "poliza_id", "cuota_nro"]

    def get_serializer_class(self):
        from .serializers import PagoSerializer
        return PagoSerializer

    @action(detail=False, methods=["post"], url_path="registrar")
    def registrar_pago(self, request):
        try:
            result = registrar_pago_handler(request.data, request)
            if isinstance(result, Response):
                return result
            return Response(result, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    # ===========================================================
    # 🚀 VERIFICACIÓN DE PAGOS — endpoints
    # ===========================================================
    @action(detail=True, methods=["post"], url_path="cambiar_estado_verificacion")
    def cambiar_estado_verificacion(self, request, pk=None):
        """
        POST /api/pagos/{id}/cambiar_estado_verificacion/
        Body: {"estado_verificacion": "verificado", "nota": "opcional"}

        Estados válidos:
          - pendiente
          - verificado
          - falta_emitir
          - pago_post_baja
          - avisar_vendedor
        """
        from .models import ESTADO_VERIFICACION_CHOICES

        pago = self.get_object()
        nuevo_estado = (request.data.get("estado_verificacion") or "").strip()
        nota = (request.data.get("nota") or "").strip()

        estados_validos = {k for k, _ in ESTADO_VERIFICACION_CHOICES}
        if nuevo_estado not in estados_validos:
            return Response(
                {"detail": f"Estado inválido. Debe ser uno de: {', '.join(estados_validos)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        pago.estado_verificacion = nuevo_estado
        if nota:
            pago.verificacion_nota = nota
        pago.verificado_por = request.user if request.user.is_authenticated else None
        pago.verificado_en = timezone.now()
        pago.save(update_fields=[
            "estado_verificacion",
            "verificacion_nota",
            "verificado_por",
            "verificado_en",
            "actualizado",
        ])

        return Response({
            "id": pago.id,
            "estado_verificacion": pago.estado_verificacion,
            "verificacion_nota": pago.verificacion_nota,
            "verificado_por": getattr(pago.verificado_por, "username", None),
            "verificado_en": pago.verificado_en,
            "requiere_atencion": pago.requiere_atencion,
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="atencion_count")
    def atencion_count(self, request):
        """
        GET /api/pagos/atencion_count/?oficina=ALL
        Devuelve cantidad de pagos en estados de atención.
        Si el user no es admin, solo cuenta los de su oficina.
        """
        from .models import Pago, ESTADOS_ATENCION
        from django.db.models import Count

        qs = Pago.objects.filter(estado_verificacion__in=ESTADOS_ATENCION)

        user = request.user
        perfil = getattr(user, "perfil", None)
        rol = getattr(perfil, "rol", None) if perfil else None

        if rol != "ADMIN":
            ofi_propia = getattr(perfil, "oficina_id", None) if perfil else None
            if ofi_propia:
                qs = qs.filter(poliza__oficina_id=ofi_propia)
        else:
            oficina_param = (request.query_params.get("oficina") or "").strip()
            if oficina_param and oficina_param.upper() != "ALL":
                qs = qs.filter(poliza__oficina_id=oficina_param)

        total = qs.count()

        por_estado = dict(
            qs.values_list("estado_verificacion")
              .annotate(c=Count("id"))
              .values_list("estado_verificacion", "c")
        )

        por_oficina = {}
        if rol == "ADMIN":
            por_oficina = dict(
                qs.values_list("poliza__oficina__nombre")
                  .annotate(c=Count("id"))
                  .values_list("poliza__oficina__nombre", "c")
            )

        return Response({
            "total": total,
            "por_estado": por_estado,
            "por_oficina": por_oficina,
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="atencion_list")
    def atencion_list(self, request):
        """
        GET /api/pagos/atencion_list/
        Lista los pagos en atención (máximo 50, ordenados por más reciente).
        """
        from .models import Pago, ESTADOS_ATENCION

        qs = Pago.objects.filter(estado_verificacion__in=ESTADOS_ATENCION)
        qs = qs.select_related("poliza", "poliza__cliente").order_by("-registrado_en")

        user = request.user
        perfil = getattr(user, "perfil", None)
        rol = getattr(perfil, "rol", None) if perfil else None

        if rol != "ADMIN":
            ofi_propia = getattr(perfil, "oficina_id", None) if perfil else None
            if ofi_propia:
                qs = qs.filter(poliza__oficina_id=ofi_propia)
        else:
            oficina_param = (request.query_params.get("oficina") or "").strip()
            if oficina_param and oficina_param.upper() != "ALL":
                qs = qs.filter(poliza__oficina_id=oficina_param)

        qs = qs[:50]
        serializer = PagoSerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class CuotaViewSet(HistorialPagosMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = Cuota.objects.all().select_related("poliza", "poliza__cliente")

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["poliza", "pagado", "fecha_vencimiento"]

    search_fields = [
        "poliza__numero_poliza",
        "poliza__patente",
        "poliza__cliente__apellido",
        "poliza__cliente__nombre",
        "poliza__cliente__dni_cuit_cuil",
    ]

    ordering_fields = ["fecha_vencimiento", "cuota_nro", "monto"]
    ordering = ["poliza_id", "cuota_nro"]

    def get_serializer_class(self):
        from .serializers import CuotaSerializer, CuotaPagoHistorialSerializer
        if getattr(self, "action", "") == "historial_pagos":
            return CuotaPagoHistorialSerializer
        return CuotaSerializer

    @action(detail=True, methods=["patch"], url_path="pagar")
    def pagar(self, request, pk=None):
        cuota: Cuota = self.get_object()

        if cuota.pagado:
            return Response({"detail": "La cuota ya figura como pagada."}, status=status.HTTP_409_CONFLICT)

        ahora = timezone.now()

        fecha_pago_raw = request.data.get("fecha_pago")
        if fecha_pago_raw:
            if isinstance(fecha_pago_raw, str):
                _fecha_pago = parse_date(fecha_pago_raw)
                if not _fecha_pago:
                    return Response({"fecha_pago": "Formato inválido. Use YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)
                fecha_pago = _fecha_pago
            else:
                fecha_pago = fecha_pago_raw
        else:
            fecha_pago = ahora.date()

        forma_pago = request.data.get("forma_pago")
        if forma_pago and forma_pago not in ("efectivo", "transferencia"):
            return Response({"forma_pago": 'Valor inválido. Use "efectivo" o "transferencia".'}, status=status.HTTP_400_BAD_REQUEST)

        metodo = request.data.get("metodo")
        if metodo in ("mercado_pago", "tarjeta"):
            metodo = "transferencia"
        if metodo and metodo not in ("efectivo", "transferencia"):
            return Response({"metodo": 'Valor inválido. Use "efectivo" o "transferencia".'}, status=status.HTTP_400_BAD_REQUEST)

        if not forma_pago and metodo:
            forma_pago = "efectivo" if metodo == "efectivo" else "transferencia"

        monto_raw = request.data.get("monto")
        monto_decimal = None
        if monto_raw not in (None, ""):
            try:
                monto_decimal = Decimal(str(monto_raw))
                if monto_decimal < 0:
                    return Response({"monto": "Debe ser un número positivo."}, status=status.HTTP_400_BAD_REQUEST)
            except (InvalidOperation, TypeError, ValueError):
                return Response({"monto": "Monto inválido."}, status=status.HTTP_400_BAD_REQUEST)

        observaciones = request.data.get("observaciones", "")
        registrar_en_balance = request.data.get("registrar_en_balance", True)

        # 🆕 Quién cobró (opcional; si no lo mandan, no rompe nada).
        responsable_id = request.data.get("responsable_empleado") or request.data.get("responsable_empleado_id")
        responsable_obj = None
        if responsable_id:
            responsable_obj = Empleado.objects.filter(id=responsable_id).first()
            if not responsable_obj:
                return Response({"responsable_empleado": "Empleado no encontrado."}, status=status.HTTP_400_BAD_REQUEST)
        responsable_nombre = (request.data.get("responsable_nombre") or "").strip() or getattr(responsable_obj, "nombre", "")

        with transaction.atomic():
            txt_obs = str(observaciones or "").strip()
            if txt_obs:
                try:
                    cuota.observaciones_pago = txt_obs
                    cuota.ultima_observacion_pago = txt_obs
                except Exception:
                    pass

            cuota.pagado = True
            cuota.fecha_pago = fecha_pago
            cuota.pago_registrado_en = ahora

            if forma_pago:
                cuota.forma_pago = forma_pago
            if monto_decimal is not None:
                cuota.monto = monto_decimal

            update_fields = ["pagado", "fecha_pago", "pago_registrado_en", "forma_pago", "monto"]
            if txt_obs:
                update_fields += ["observaciones_pago", "ultima_observacion_pago"]
            if responsable_obj is not None or responsable_nombre:
                cuota.responsable_empleado = responsable_obj
                cuota.responsable_nombre = responsable_nombre
                update_fields += ["responsable_empleado", "responsable_nombre"]

            cuota.save(update_fields=update_fields)

            pago_defaults = {
                "fecha": fecha_pago,
                "monto": monto_decimal if monto_decimal is not None else cuota.monto,
                "metodo": (metodo if metodo else (forma_pago if forma_pago in ("efectivo", "transferencia") else "transferencia")),
                "observaciones": observaciones,
                # 🆕 Detalle de la transferencia — ya viajaba en el body del wizard,
                #    faltaba guardarlo en el Pago (por eso nunca llegaba a Balances).
                "destino_cuenta": request.data.get("destino_cuenta") or request.data.get("medio_cobro_valor") or "",
                "enviado_por": request.data.get("enviado_por") or "",
                "cuit_remitente": request.data.get("cuit_remitente") or "",
                "nro_operacion": request.data.get("nro_operacion") or "",
                # 🆕 Quién cobró.
                "responsable_empleado": responsable_obj,
                "responsable_nombre": responsable_nombre,
            }
            pago, creado = Pago.objects.get_or_create(
                poliza=cuota.poliza,
                cuota=cuota,
                cuota_nro=cuota.cuota_nro,
                defaults=pago_defaults,
            )
            if not creado:
                for k, v in pago_defaults.items():
                    setattr(pago, k, v)
                pago.save()

            medio_id = request.data.get("medio_cobro_id")
            medio_valor = request.data.get("medio_cobro_valor") or request.data.get("destino_cuenta")
            try:
                medio = None
                if medio_id:
                    medio = MedioCobro.objects.filter(id=medio_id).first()
                if not medio and medio_valor:
                    medio = MedioCobro.objects.filter(valor=medio_valor).first() or MedioCobro.objects.filter(etiqueta=medio_valor).first()
                if medio:
                    mark = getattr(medio, "marcar_uso", None)
                    if callable(mark):
                        mark()
                    else:
                        medio.ultimo_uso = timezone.now()
                        medio.usos_totales = (medio.usos_totales or 0) + 1
                        medio.save(update_fields=["ultimo_uso", "usos_totales"])
            except Exception:
                pass

            if registrar_en_balance and not getattr(pago, "registrado_en_balance", False):
                pago.registrado_en_balance = True
                pago.save(update_fields=["registrado_en_balance"])

                poliza_obj = cuota.poliza
                ofi_code = str(getattr(poliza_obj.oficina, 'id', poliza_obj.oficina or ""))
                
                forma_balance = "efectivo" if (pago.metodo == "efectivo") else "transferencia"

                cliente_nombre = ""
                try:
                    c = poliza_obj.cliente
                    if c:
                        nom = (getattr(c, "nombre", "") or "").strip()
                        ape = (getattr(c, "apellido", "") or "").strip()
                        if ape and nom:
                            cliente_nombre = f"{ape}, {nom}"
                        else:
                            cliente_nombre = ape or nom
                except Exception:
                    pass

                # ── Datos de transferencia del wizard ──────────────
                enviado_por    = request.data.get("enviado_por") or cliente_nombre or ""
                destino_cuenta = request.data.get("destino_cuenta") or request.data.get("medio_cobro_valor") or ""
                cuit_remitente = request.data.get("cuit_remitente") or ""
                nro_operacion  = request.data.get("nro_operacion")  or ""

                # Observaciones con trazabilidad completa
                obs_partes = []
                if str(observaciones or "").strip(): obs_partes.append(str(observaciones).strip())
                if cuit_remitente: obs_partes.append(f"CUIT: {cuit_remitente}")
                if nro_operacion:  obs_partes.append(f"Op: {nro_operacion}")
                obs_completo = " | ".join(obs_partes) or ""

                ingreso_data = {
                    "monto":          pago.monto,
                    "categoria":      "Cobro de Cuota",
                    "forma_pago":     forma_balance,
                    "pagado_por":     enviado_por,
                    "billetera":      destino_cuenta,
                    "cuit_remitente": cuit_remitente,
                    "nro_operacion":  nro_operacion,
                    "observaciones":  obs_completo,
                    "descripcion":    f"Pago cuota {pago.cuota_nro} - Póliza {poliza_obj.numero_poliza}"
                }
                
                try:
                    ingreso_data["fecha"] = fecha_pago
                except Exception: pass
                
                try:
                    # ✅ CORRECCIÓN: Le agregamos _id para que Django entienda que es el número identificador
                    ingreso_data["oficina_id"] = ofi_code
                except Exception: pass
                
                try:
                    ingreso_data["usuario"] = request.user
                except Exception: pass
                
                BalanceIngreso.objects.create(**ingreso_data)

            # 🚀===================================================
            # 🚀 LÓGICA DE REACTIVACIÓN INTELIGENTE
            # ===================================================
            poliza: Poliza = cuota.poliza
            hoy = timezone.localdate()
            hay_vencidas = poliza.cuotas.filter(pagado=False, fecha_vencimiento__lt=hoy).exists()
            
            estado_actual = str(getattr(poliza, "estado", "")).strip().upper()

            if estado_actual in ("CANCELADA", "ANULADA"):
                pass
            elif estado_actual == "VENCIDA" and not hay_vencidas:
                poliza.estado = "activa"
                poliza.save(update_fields=["estado"])
            elif not hay_vencidas and estado_actual != "ACTIVA" and estado_actual not in ("CANCELADA", "ANULADA", "BAJA"):
                poliza.estado = "activa"
                poliza.save(update_fields=["estado"])

            # Si la póliza está dada de baja y se cobró → marcar en verificación
            if estado_actual in ("BAJA", "BAJA_RECIENTE"):
                poliza.estado = "en_verificacion"
                poliza.save(update_fields=["estado"])
            # ===================================================

        # 🆕 Agradecimiento + link al portal (no rompe el pago si falla). Cubre los dos botones.
        try:
            _enviar_gracias_portal(cuota.poliza)
        except Exception as e:
            print(f"[cuota.pagar] WhatsApp de gracias falló: {e}")

        serializer = self.get_serializer(cuota)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post", "patch"], url_path="cambiar-fecha")
    def cambiar_fecha(self, request, pk=None):
        cuota = self.get_object()
        nueva_fecha_raw = request.data.get("nueva_fecha")
        
        if not nueva_fecha_raw:
            return Response({"nueva_fecha": "Este campo es requerido."}, status=status.HTTP_400_BAD_REQUEST)

        nueva_fecha = _parse_ymd(nueva_fecha_raw)
        if not nueva_fecha:
            return Response({"nueva_fecha": "Formato inválido. Use YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)

        ajustar_siguientes = _to_bool(request.data.get("ajustar_siguientes", False))

        def add_months(sourcedate, months):
            month = sourcedate.month - 1 + months
            year = sourcedate.year + month // 12
            month = month % 12 + 1
            day = min(sourcedate.day, calendar.monthrange(year, month)[1])
            return date(year, month, day)

        with transaction.atomic():
            cuota.fecha_vencimiento = nueva_fecha
            cuota.save(update_fields=["fecha_vencimiento"])
            modificadas = 1

            if ajustar_siguientes:
                siguientes = Cuota.objects.filter(
                    poliza=cuota.poliza,
                    cuota_nro__gt=cuota.cuota_nro
                ).order_by("cuota_nro")

                meses_a_sumar = 1
                for sig in siguientes:
                    sig.fecha_vencimiento = add_months(nueva_fecha, meses_a_sumar)
                    sig.save(update_fields=["fecha_vencimiento"])
                    meses_a_sumar += 1
                    modificadas += 1

        return Response({
            "detail": "Fechas actualizadas correctamente.",
            "cuotas_modificadas": modificadas
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"], url_path="factura")
    def factura(self, request, pk=None):
        cuota = self.get_object()
        
        oficina_keys = _get_seguridad_oficina_brute(request)
        if "BLOQUEADO" in oficina_keys:
            return Response({"detail": "No tienes acceso a esta factura."}, status=403)
            
        pdf_filelike = generar_factura_pdf(cuota)
        return FileResponse(
            pdf_filelike,
            as_attachment=True,
            filename=f"factura_cuota_{cuota.id}.pdf",
            content_type="application/pdf",
        )

    @action(detail=False, methods=["get"], url_path="a-vencer")
    def cuotas_a_vencer(self, request):
        hoy = timezone.localdate()
        hitos = {hoy - timedelta(days=30), hoy - timedelta(days=7), hoy - timedelta(days=3), hoy, hoy + timedelta(days=3)}
        
        oficina_keys = _get_seguridad_oficina_brute(request, request.query_params.get("oficina", ""))
        if "BLOQUEADO" in oficina_keys:
            return Response({"detail": "Acceso denegado"}, status=403)
            
        qs = Cuota.objects.filter(pagado=False, fecha_vencimiento__in=hitos).select_related("poliza", "poliza__cliente")
        
        if oficina_keys:
            qs = qs.filter(_build_oficina_q_from_keys(oficina_keys))
            
        qs = qs.order_by("fecha_vencimiento", "poliza_id", "cuota_nro")
        
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

        return Response(ser.data, status=status.HTTP_200_OK)