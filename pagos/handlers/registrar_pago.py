# pagos/handlers/registrar_pago.py

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.apps import apps  
from rest_framework import status
from rest_framework.response import Response

from polizas.models import Poliza
from pagos.models import Cuota, Pago

import os

from django.core.exceptions import ImproperlyConfigured

# URL del frontend para armar el link del portal.
# 🔒 Sin default: cada proyecto (Thames / Polizando) tiene que apuntar al SUYO.
FRONTEND_URL = os.environ.get("FRONTEND_URL")
if not FRONTEND_URL:
    raise ImproperlyConfigured(
        "❌ Falta la variable de entorno FRONTEND_URL (URL del front de Polizando). "
        "Setealá en Railway antes de correr esto."
    )
FRONTEND_URL = FRONTEND_URL.rstrip("/")


def _enviar_gracias_portal(poliza):
    """Best-effort: WhatsApp de agradecimiento + link al portal del cliente.
    Se llama dentro de try/except — nunca debe romper el flujo de pago.
    Imprime diagnóstico en cada paso para poder seguirlo en los logs."""
    # ⛔ DESACTIVADO TEMPORALMENTE (a pedido). Para reactivarlo, BORRÁ estas 2 líneas.
    print("[gracias_portal] Desactivado temporalmente → no se envía nada.")
    return
    # ─────────────────────────────────────────────────────────────────────────
    cliente = getattr(poliza, "cliente", None)
    if not cliente:
        print("[gracias_portal] La póliza no tiene cliente → no se envía.")
        return
    tel = (getattr(cliente, "telefono", "") or "").strip()
    if not tel:
        print(f"[gracias_portal] Cliente {getattr(cliente, 'id', '?')} sin teléfono → no se envía.")
        return
    try:
        token = cliente.asegurar_portal_token()
    except Exception as e:
        print(f"[gracias_portal] asegurar_portal_token() falló ({e}). "
              f"¿Aplicaste la migración de 'clientes'?")
        token = getattr(cliente, "portal_token", "") or ""
    if not token:
        print("[gracias_portal] El cliente no tiene token de portal → no se envía.")
        return
    link = f"{FRONTEND_URL}/#/portal/{token}"
    nombre = ""
    n = (getattr(cliente, "nombre", "") or "").strip()
    if n:
        nombre = n.split()[0]
    saludo = f"Hola {nombre} 👋\n\n" if nombre else "Hola 👋\n\n"
    mensaje = (
        f"{saludo}"
        "¡Gracias por seguir confiando en nosotros! 💙 Registramos tu pago.\n\n"
        "Cuando quieras podés ver tus pólizas, cuotas y papeles desde tu portal:\n"
        f"{link}"
    )
    from notificaciones.utils.mensajeria import enviar_whatsapp
    oficina_id = getattr(poliza, "oficina_id", None)
    print(f"[gracias_portal] Enviando WhatsApp de gracias a {tel} (oficina={oficina_id})...")
    ok, info = enviar_whatsapp(tel, mensaje, oficina=str(oficina_id) if oficina_id else None)
    if ok:
        print(f"[gracias_portal] ✅ WhatsApp enviado a {tel}.")
    else:
        print(f"[gracias_portal] ❌ WhatsApp NO enviado a {tel}: {info}")


# 🚀 Código de caja de la oficina
def _obtener_codigo_caja(poliza):
    """Código de la oficina para el ingreso de caja: usa Oficina.codigo
    (siempre debería estar seteado); si no, cae en el id como texto."""
    ofi = getattr(poliza, 'oficina', None)
    if not ofi:
        return ""
    if hasattr(ofi, 'codigo') and ofi.codigo:
        return str(ofi.codigo).strip()
    return str(getattr(ofi, 'id', ofi)).strip()


def _puede_cobrar_poliza(request, poliza):
    # 🔓 ABIERTO: cualquier oficina puede cobrar la cuota de cualquier póliza.
    #    El cliente sigue siendo de su oficina original, pero el cobro se puede
    #    hacer desde cualquier sucursal. El INGRESO se registra en la oficina que
    #    cobra (ver _oficina_que_cobra más abajo), no en la de la póliza.
    return True


def _oficina_que_cobra(request, poliza):
    """Oficina donde entra la plata = la del usuario que registra el pago.
    Si no se puede determinar (admin sin oficina, sin request), cae en la
    oficina de la póliza para no dejar el ingreso sin sucursal."""
    try:
        if request and getattr(request, 'user', None) and request.user.is_authenticated:
            perfil = getattr(request.user, 'perfil', None)
            ofi = getattr(perfil, 'oficina', None)
            if ofi:
                return ofi
    except Exception:
        pass
    return getattr(poliza, 'oficina', None)


def registrar_pago_handler(data, request=None):
    """
    Registra el pago de una CUOTA y sincroniza todo.
    """
    try:
        poliza_id = data.get('poliza_id') or data.get('poliza')
        cuota_id = data.get('cuota_id') or data.get('cuota')

        if not poliza_id or not cuota_id:
            return Response(
                {"error": "poliza_id y cuota_id son requeridos"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        poliza = Poliza.objects.get(id=poliza_id)
        
        if not _puede_cobrar_poliza(request, poliza):
            return Response(
                {"error": "Acceso denegado: Esta póliza pertenece a otra sucursal y no podés registrar su pago."},
                status=status.HTTP_403_FORBIDDEN,
            )

        cuota = Cuota.objects.get(id=cuota_id, poliza=poliza)

        if cuota.pagado:
            return Response(
                {"error": "La cuota indicada ya figura como pagada."},
                status=status.HTTP_409_CONFLICT,
            )
        if Pago.objects.filter(poliza=poliza, cuota_nro=cuota.cuota_nro).exists():
            return Response(
                {"error": f"Ya existe un pago registrado para la cuota {cuota.cuota_nro}."},
                status=status.HTTP_409_CONFLICT,
            )

        monto_raw = data.get('monto')
        try:
            monto = Decimal(str(monto_raw))
            if monto < 0:
                return Response({"error": "El monto debe ser positivo."}, status=status.HTTP_400_BAD_REQUEST)
        except (InvalidOperation, TypeError, ValueError):
            return Response({"error": "El monto ingresado no es válido."}, status=status.HTTP_400_BAD_REQUEST)

        fecha_raw = data.get('fecha') or data.get('fecha_pago')
        if fecha_raw:
            if isinstance(fecha_raw, str):
                fecha_pago = parse_date(fecha_raw)
                if not fecha_pago:
                    return Response({"error": "Formato de fecha inválido. Use YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)
            else:
                fecha_pago = fecha_raw
        else:
            fecha_pago = timezone.localdate()

        metodo = data.get('metodo', 'efectivo')
        if metodo not in ('efectivo', 'transferencia', 'mercado_pago', 'tarjeta'):
            return Response({"error": "Método de pago inválido."}, status=status.HTTP_400_BAD_REQUEST)

        if metodo in ("mercado_pago", "tarjeta"):
            metodo_mapped = "transferencia"
        else:
            metodo_mapped = metodo

        registrar_en_balance = data.get('registrar_en_balance', True)

        with transaction.atomic():
            cuota.monto = monto
            cuota.pagado = True
            cuota.fecha_pago = fecha_pago

            cuota.forma_pago = metodo_mapped
            cuota.save(update_fields=['monto', 'pagado', 'fecha_pago', 'forma_pago'])

            pago = Pago.objects.create(
                poliza=poliza,
                cuota=cuota,
                cuota_nro=cuota.cuota_nro,
                fecha=fecha_pago,
                monto=monto,
                metodo=metodo_mapped,
                observaciones=data.get('observaciones', ''),
            )

            hoy = timezone.localdate()

            # ── Lógica nueva: miramos solo la ÚLTIMA cuota ──────────────
            # Si la última cuota vence en el futuro O ya está pagada
            # → la póliza vuelve a ACTIVA
            # Si la última cuota venció y sigue impaga → queda VENCIDA
            ultima_cuota = poliza.cuotas.order_by("-fecha_vencimiento").first()

            if ultima_cuota:
                ultima_vencio = ultima_cuota.fecha_vencimiento < hoy
                ultima_pagada = ultima_cuota.pagado  # ya actualizado arriba

                if not ultima_vencio:
                    # Última cuota todavía no vence → ACTIVA
                    nuevo_estado = "activa"
                elif ultima_pagada:
                    # Última cuota venció pero está pagada
                    # Verificamos si hay alguna impaga (para no marcar finalizada si hay deuda)
                    hay_impaga = poliza.cuotas.filter(pagado=False).exists()
                    nuevo_estado = "finalizada" if not hay_impaga else "activa"
                else:
                    # Última cuota venció y NO está pagada → VENCIDA
                    nuevo_estado = "vencida"

                if poliza.estado != nuevo_estado:
                    poliza.estado = nuevo_estado
                    poliza.save(update_fields=["estado"])

            pago.refresh_from_db(fields=['registrado_en_balance'])

            if registrar_en_balance and not pago.registrado_en_balance:
                pago.registrado_en_balance = True
                try:
                    pago.save(update_fields=['registrado_en_balance'])
                except Exception:
                    pago.save()

                forma_balance = "efectivo" if (metodo_mapped == "efectivo") else "transferencia"
                
                # 🚀 USAMOS EL TRADUCTOR INFALIBLE
                ofi_code = _obtener_codigo_caja(poliza)

                try:
                    Ingreso = apps.get_model("balances", "Ingreso")
                except LookupError:
                    Ingreso = apps.get_model("balanzes", "Ingreso")

                usuario_auditoria = request.user if (request and hasattr(request, 'user') and request.user.is_authenticated) else None

                # 🔓 La plata entra en la oficina que COBRA (no la del cliente/póliza).
                oficina_cobro = _oficina_que_cobra(request, poliza)

                # Nombre del cliente (debe ir ANTES de enviado_por)
                cliente_nombre = ""
                try:
                    c = poliza.cliente
                    if c:
                        nom = (getattr(c, "nombre", "") or "").strip()
                        ape = (getattr(c, "apellido", "") or "").strip()
                        if ape and nom:
                            cliente_nombre = f"{ape}, {nom}"
                        else:
                            cliente_nombre = ape or nom
                except Exception:
                    pass

                # Datos de la transferencia
                destino_cuenta = data.get("destino_cuenta") or data.get("billetera") or ""
                enviado_por    = data.get("enviado_por") or cliente_nombre or ""
                cuit_remitente = data.get("cuit_remitente") or ""
                nro_operacion  = data.get("nro_operacion") or ""

                # Observaciones con trazabilidad completa
                obs_partes = []
                if pago.observaciones: obs_partes.append(pago.observaciones)
                if cuit_remitente:     obs_partes.append(f"CUIT: {cuit_remitente}")
                if nro_operacion:      obs_partes.append(f"Op: {nro_operacion}")
                obs_final = " | ".join(obs_partes) or ""

                Ingreso.objects.create(
                    descripcion=f"Pago cuota {pago.cuota_nro} - Póliza {poliza.numero_poliza}",
                    monto=pago.monto,
                    fecha=fecha_pago,
                    oficina=oficina_cobro,   # ← oficina que COBRA (la del cajero), no la del cliente
                    usuario=usuario_auditoria,
                    categoria="Cobro de Cuota",
                    forma_pago=forma_balance,
                    pagado_por=enviado_por,
                    billetera=destino_cuenta,
                    cuit_remitente=cuit_remitente,
                    nro_operacion=nro_operacion,
                    observaciones=obs_final,
                )

        from pagos.serializers import PagoSerializer
        return Response(PagoSerializer(pago).data, status=status.HTTP_201_CREATED)

    except Poliza.DoesNotExist:
        return Response({"error": "Póliza no encontrada"}, status=status.HTTP_404_NOT_FOUND)
    except Cuota.DoesNotExist:
        return Response({"error": "Cuota no encontrada para esta póliza"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)