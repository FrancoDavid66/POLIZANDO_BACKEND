# clientes/public_views.py
#
# Endpoints PÚBLICOS del Portal del Asegurado (sin login, acceso por token).
# El cliente entra con un link único (?token) que mandamos por WhatsApp.
# Solo lectura de SUS pólizas vigentes + un endpoint para avisar "Ya pagué".

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status
from django.utils import timezone

from .models import Cliente

# 🆕 Precios NRE: para mostrarle al cliente cuánto pagará al renovar.
from polizas.precios_nre import es_nre, precio_cuotas_renovacion


def _cliente_por_token(token):
    if not token:
        return None
    return Cliente.objects.filter(portal_token=token).select_related("oficina").first()


def _fmt(d):
    return d.strftime("%Y-%m-%d") if d else None


class PortalDataView(APIView):
    """GET /public/portal/<token>/ → cliente + pólizas vigentes (solo lectura)."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, token):
        cli = _cliente_por_token(token)
        if not cli:
            return Response({"detail": "Link inválido o vencido."}, status=status.HTTP_404_NOT_FOUND)

        from polizas.models import Poliza, CuponRobo, PolizaDocumento
        from pagos.models import Cuota

        polizas = (
            Poliza.objects.filter(cliente=cli)
            .exclude(estado__in=["cancelada", "finalizada", "en_verificacion"])
            .order_by("-id")
        )

        def _oficina_whatsapp(poliza):
            ofi = getattr(poliza, "oficina", None)
            # Oficina como relación (tiene el campo whatsapp)
            if ofi is not None and hasattr(ofi, "whatsapp"):
                return (getattr(ofi, "whatsapp", "") or "").strip()
            # Oficina como texto (código o nombre): la buscamos
            if isinstance(ofi, str) and ofi.strip():
                try:
                    from usuarios.models import Oficina
                    o = (Oficina.objects.filter(codigo__iexact=ofi.strip()).first()
                         or Oficina.objects.filter(nombre__icontains=ofi.strip()).first())
                    if o:
                        return (o.whatsapp or "").strip()
                except Exception:
                    pass
            return ""

        data_polizas = []
        hoy = timezone.localdate()
        for p in polizas:
            cuotas_qs = list(
                Cuota.objects.filter(poliza=p).order_by("fecha_vencimiento", "cuota_nro")
            )
            cuotas = [
                {
                    "cuota_nro": c.cuota_nro,
                    "fecha_vencimiento": _fmt(c.fecha_vencimiento),
                    "monto": float(c.monto) if c.monto is not None else 0,
                    "pagado": bool(c.pagado),
                    "fecha_pago": _fmt(c.fecha_pago),
                    "forma_pago": getattr(c, "forma_pago", "") or "",
                    "pago_registrado_en": (
                        c.pago_registrado_en.isoformat()
                        if getattr(c, "pago_registrado_en", None) else None
                    ),
                }
                for c in cuotas_qs
            ]
            cupones = [
                {
                    "id": cup.id,
                    "periodo_desde": _fmt(cup.periodo_desde),
                    "periodo_hasta": _fmt(cup.periodo_hasta),
                    "fecha_vencimiento": _fmt(cup.fecha_vencimiento),
                    "estado": cup.estado,
                    "reportado": cup.estado == CuponRobo.Estado.REPORTADO,
                    "pagado": cup.estado == CuponRobo.Estado.PAGADA,
                }
                for cup in CuponRobo.objects.filter(poliza=p).order_by("fecha_vencimiento")
            ]
            docs = [
                {"tipo": d.tipo, "url": d.url, "nombre": getattr(d, "nombre", "") or ""}
                for d in PolizaDocumento.objects.filter(poliza=p)
            ]

            # 🆕 Precio que paga HOY (próxima cuota impaga) y precio AL RENOVAR (solo NRE).
            proxima_impaga = next((c for c in cuotas_qs if not c.pagado), None)
            if proxima_impaga is not None and proxima_impaga.monto is not None:
                precio_actual = float(proxima_impaga.monto)
            elif getattr(p, "precio_cuota", None) is not None:
                precio_actual = float(p.precio_cuota)
            else:
                precio_actual = 0.0

            renovacion = None
            if es_nre(getattr(p, "compania", "")):
                fecha_reno = getattr(p, "fecha_vencimiento", None) or hoy
                if fecha_reno < hoy:
                    fecha_reno = hoy
                primera, resto = precio_cuotas_renovacion(getattr(p, "tipo", ""), fecha_reno, getattr(p, "oficina", None))
                if resto is not None:
                    renovacion = {
                        "fecha": _fmt(fecha_reno),
                        "primera_cuota": float(primera),
                        "resto": float(resto),
                        "con_oferta": float(primera) != float(resto),
                    }

            data_polizas.append({
                "id": p.id,
                "numero_poliza": getattr(p, "numero_poliza", "") or "",
                "compania": getattr(p, "compania_nombre", None) or getattr(p, "compania", "") or "",
                "cobertura": getattr(p, "cobertura", "") or "",
                "marca": getattr(p, "marca", "") or "",
                "modelo": getattr(p, "modelo", "") or "",
                "patente": getattr(p, "patente", "") or "",
                "anio": getattr(p, "anio", None),
                "estado": getattr(p, "estado", "") or "",
                "fecha_emision": _fmt(getattr(p, "fecha_emision", None)),
                "tipo": getattr(p, "tipo", "") or "",
                "oficina_whatsapp": _oficina_whatsapp(p),
                "cuotas": cuotas,
                "cupones_robo": cupones,
                "documentos": docs,
                "precio_actual": precio_actual,
                "renovacion": renovacion,
            })

        return Response({
            "cliente": {
                "nombre_completo": cli.nombre_completo,
                "nombre": cli.nombre,
                "apellido": cli.apellido,
                "dni": cli.dni_cuit_cuil,
                "dni_cuit_cuil": cli.dni_cuit_cuil,
                "telefono": cli.telefono,
                "email": cli.email or "",
                "direccion": cli.direccion or "",
            },
            "polizas": data_polizas,
        })


class PortalReportarPagoCuponView(APIView):
    """
    POST /public/portal/<token>/cupon/<cupon_id>/reportar-pago/
    El cliente avisa que pagó un cupón de robo. NO lo marca pagado:
    pasa a REPORTADO para que la oficina lo verifique y confirme.
    Acepta comprobante_url / comprobante_public_id opcionales.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, token, cupon_id):
        cli = _cliente_por_token(token)
        if not cli:
            return Response({"detail": "Link inválido o vencido."}, status=status.HTTP_404_NOT_FOUND)

        from polizas.models import CuponRobo
        cupon = CuponRobo.objects.filter(id=cupon_id, poliza__cliente=cli).first()
        if not cupon:
            return Response({"detail": "Cupón no encontrado."}, status=status.HTTP_404_NOT_FOUND)

        if cupon.estado == CuponRobo.Estado.PAGADA:
            return Response({"detail": "Ese cupón ya figura como pagado."}, status=status.HTTP_400_BAD_REQUEST)

        cupon.estado = CuponRobo.Estado.REPORTADO
        cupon.reportado_en = timezone.now()
        campos = ["estado", "reportado_en"]

        url = (request.data.get("comprobante_url") or "").strip()
        pid = (request.data.get("comprobante_public_id") or "").strip()
        if url:
            cupon.comprobante_url = url
            campos.append("comprobante_url")
        if pid:
            cupon.comprobante_public_id = pid
            campos.append("comprobante_public_id")

        cupon.save(update_fields=campos)

        return Response({
            "ok": True,
            "estado": cupon.estado,
            "mensaje": "¡Gracias! Recibimos tu aviso. Lo verificamos y te confirmamos.",
        })