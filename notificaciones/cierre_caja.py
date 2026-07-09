# notificaciones/cierre_caja.py
#
# Aviso automático del CIERRE DE CAJA.
# Se dispara cuando se crea un CierreCaja (desde recaudacion/views.py → perform_create).
# Manda por WhatsApp (a los números de control) y por email un resumen del día/oficina:
#   - Ingresos, egresos, neto
#   - Efectivo vs transferencias que entraron
#   - Cuántas personas pagaron
#   - Ingresos extraordinarios (sin póliza) y egresos extraordinarios (todos)
#   - Altas nuevas, renovaciones y bajas del día
#   - Si la caja dio bien o mal (estado de auditoría + diferencia)
#
# Toda la función está blindada con try/except: si el aviso falla por lo que sea,
# NUNCA rompe el cierre del empleado.

import os
import re
import logging
from decimal import Decimal

from django.conf import settings
from django.core.mail import EmailMessage
from django.db.models import Sum
from django.utils import timezone

from balanzes.models import Ingreso, Egreso
from polizas.models import Poliza
from notificaciones.utils.mensajeria import enviar_whatsapp

logger = logging.getLogger(__name__)

# Destinatarios del aviso
WHATSAPP_NUMEROS = ["1164235336", "1161332173"]
def _oficina_con_whatsapp():
    """
    Id de una oficina activa que tenga credenciales de UltraMsg cargadas (o None).
    Se usa para los avisos internos al dueño: no importa de qué oficina salgan,
    solo que tengan credenciales válidas. Sin hardcodear: se detecta desde la DB.
    """
    try:
        from usuarios.models import Oficina
        ofi = (
            Oficina.objects.filter(activa=True)
            .exclude(ultramsg_instance_id__isnull=True).exclude(ultramsg_instance_id="")
            .exclude(ultramsg_token__isnull=True).exclude(ultramsg_token="")
            .order_by("id")
            .first()
        )
        return ofi.id if ofi else None
    except Exception:
        return None
# Emails (override con env EMAIL_AVISO_CIERRE, separados por coma).
_EMAILS_DEFAULT = "francodavid_dev@outlook.com,gomezdamianricardo284@gmail.com"
EMAILS_AVISO = [e.strip() for e in os.environ.get("EMAIL_AVISO_CIERRE", _EMAILS_DEFAULT).split(",") if e.strip()]

# Un ingreso es "de seguros" si su descripción menciona una póliza.
RE_POLIZA = re.compile(r"p[oó]liza", re.IGNORECASE)


def _money(v):
    """Formatea como $1.234,56 (formato argentino)."""
    try:
        n = float(v or 0)
    except Exception:
        n = 0.0
    s = f"{n:,.2f}"  # 1,234.56
    return "$" + s.replace(",", "X").replace(".", ",").replace("X", ".")


def _resumen_dia(fecha, ofi_id, desde=None, hasta=None):
    """Calcula los números del día para esa oficina.
    Si se pasa desde/hasta (datetimes), acota por la hora real del movimiento
    (created_at), para que el cierre de la NOCHE cuente solo lo posterior al
    cierre del mediodía (sin duplicar la mañana)."""
    ing_qs = Ingreso.objects.filter(fecha=fecha)
    egr_qs = Egreso.objects.filter(fecha=fecha)
    if ofi_id:
        ing_qs = ing_qs.filter(oficina_id=ofi_id)
        egr_qs = egr_qs.filter(oficina_id=ofi_id)
    if desde is not None:
        ing_qs = ing_qs.filter(created_at__gt=desde)
        egr_qs = egr_qs.filter(created_at__gt=desde)
    if hasta is not None:
        ing_qs = ing_qs.filter(created_at__lte=hasta)
        egr_qs = egr_qs.filter(created_at__lte=hasta)

    total_ing = ing_qs.aggregate(s=Sum("monto"))["s"] or Decimal("0")
    total_egr = egr_qs.aggregate(s=Sum("monto"))["s"] or Decimal("0")
    neto = total_ing - total_egr

    ing_efectivo = ing_qs.filter(forma_pago__iexact="EFECTIVO").aggregate(s=Sum("monto"))["s"] or Decimal("0")
    ing_transfer = ing_qs.filter(forma_pago__iexact="TRANSFERENCIA").aggregate(s=Sum("monto"))["s"] or Decimal("0")

    pagadores = (
        ing_qs.exclude(pagado_por__isnull=True)
        .exclude(pagado_por__exact="")
        .values("pagado_por")
        .distinct()
        .count()
    )

    # Ingresos extraordinarios = los que NO mencionan póliza
    ingresos_dia = list(ing_qs.values("descripcion", "monto"))
    extra_ing = [
        i for i in ingresos_dia
        if not RE_POLIZA.search(i["descripcion"] or "")
    ]
    extra_ing_total = sum((i["monto"] or Decimal("0")) for i in extra_ing)

    # Egresos extraordinarios = TODOS los egresos
    extra_egr = list(egr_qs.values("descripcion", "monto"))
    extra_egr_total = sum((e["monto"] or Decimal("0")) for e in extra_egr)

    return {
        "total_ing": total_ing,
        "total_egr": total_egr,
        "neto": neto,
        "ing_efectivo": ing_efectivo,
        "ing_transfer": ing_transfer,
        "pagadores": pagadores,
        "extra_ing": extra_ing,
        "extra_ing_total": extra_ing_total,
        "extra_egr": extra_egr,
        "extra_egr_total": extra_egr_total,
    }


def _polizas_dia(fecha, ofi_id):
    """
    Altas nuevas, renovaciones y bajas del día para esa oficina.
      - Altas / renovaciones: por creado_en (fecha real de carga en el sistema).
      - Bajas: por fecha_baja (= hoy) + estado cancelada.
    Devuelve listas de {nombre, patente}.
    """
    base = Poliza.objects.all()
    if ofi_id:
        base = base.filter(oficina_id=ofi_id)

    def _fmt(qs):
        out = []
        for row in qs.values("patente", "cliente__nombre", "cliente__apellido"):
            nombre = f"{(row['cliente__nombre'] or '').strip()} {(row['cliente__apellido'] or '').strip()}".strip() or "—"
            patente = (row["patente"] or "").strip() or "—"
            out.append({"nombre": nombre, "patente": patente})
        return out

    altas = _fmt(base.filter(creado_en__date=fecha, es_renovacion=False))
    renovaciones = _fmt(base.filter(creado_en__date=fecha, es_renovacion=True))
    bajas = _fmt(base.filter(fecha_baja=fecha, estado="cancelada"))

    return {"altas": altas, "renovaciones": renovaciones, "bajas": bajas}


def _estado_texto(cierre):
    """Devuelve (etiqueta, color_hex) según el estado de auditoría del cierre."""
    estado = (cierre.estado_auditoria or "PENDIENTE").upper()
    dif = cierre.diferencia if cierre.diferencia is not None else Decimal("0")
    if estado == "OK":
        return f"Caja OK (sin diferencia)", "#047857"
    if estado == "FALTANTE":
        return f"FALTANTE de {_money(abs(dif))}", "#b91c1c"
    if estado == "SOBRANTE":
        return f"SOBRANTE de {_money(abs(dif))}", "#b45309"
    return "Sin declarar (pendiente)", "#475569"


def _alerta_cartera(r_pol):
    """
    Termómetro del día según el movimiento de cartera (altas + renovaciones vs bajas).
    Devuelve una línea de alerta (str) o None si no aplica.

      🚨 Crítico → las bajas superan POR SEPARADO a las altas y a las renovaciones.
      ⚠️ Flojo   → las bajas igualan o superan al total que entró (altas + renovaciones).
      ✅ Bueno   → entró más de lo que se fue.
    """
    a  = len(r_pol["altas"])
    rn = len(r_pol["renovaciones"])
    b  = len(r_pol["bajas"])
    entra = a + rn

    # 🚨 Crítico: bajas mayores que las altas Y que las renovaciones.
    if b > 0 and b > a and b > rn:
        return "🚨 *ALERTA:* hubo más bajas que altas y que renovaciones. La cartera se achicó hoy."

    # ⚠️ Flojo: las bajas empataron o le ganaron a todo lo que entró.
    if b > 0 and b >= entra:
        return "⚠️ Ojo: las bajas igualaron o superaron a las altas + renovaciones."

    # ✅ Bueno: entró más de lo que se fue.
    if entra > b and entra > 0:
        return "✅ Buen día: las altas + renovaciones le ganaron a las bajas."

    # Sin movimiento relevante de cartera → sin alerta.
    return None


def _mensaje_whatsapp(cierre, r, r_pol, oficina_nombre, quien, fecha_txt):
    estado_txt, _ = _estado_texto(cierre)
    partes = [
        f"🧾 *Cierre de caja* — {oficina_nombre} · {fecha_txt}",
        f"👤 Cerró: {quien}",
        "",
        f"💰 Ingresos: {_money(r['total_ing'])}",
        f"💸 Egresos: {_money(r['total_egr'])}",
        f"📊 Neto: {_money(r['neto'])}",
        f"🔎 {estado_txt}",
        "",
        f"💵 Efectivo: {_money(r['ing_efectivo'])}",
        f"🏦 Transferencias: {_money(r['ing_transfer'])}",
        f"👥 Pagaron hoy: {r['pagadores']} persona{'s' if r['pagadores'] != 1 else ''}",
    ]
    if r["extra_ing"]:
        partes.append(f"⭐ Ingresos extraordinarios: {len(r['extra_ing'])} ({_money(r['extra_ing_total'])})")
    if r["extra_egr"]:
        partes.append(f"⚠️ Egresos extraordinarios: {len(r['extra_egr'])} ({_money(r['extra_egr_total'])})")

    # Pólizas del día — SOLO cantidades (el detalle con nombres va al email).
    partes.append("")
    partes.append(f"📄 Altas nuevas: {len(r_pol['altas'])}")
    partes.append(f"🔄 Renovaciones: {len(r_pol['renovaciones'])}")
    partes.append(f"📉 Bajas: {len(r_pol['bajas'])}")

    # Termómetro del día según el balance de cartera.
    alerta = _alerta_cartera(r_pol)
    if alerta:
        partes.append("")
        partes.append(alerta)

    return "\n".join(partes)


def _enviar_whatsapp_control(numero, mensaje, ofi_id):
    """
    Manda el WhatsApp a un número de control.
    Intenta con las credenciales de la oficina; si esa oficina no las tiene
    (o fallan), reintenta con las credenciales globales (las que usan los buchones).
    enviar_whatsapp NO lanza excepción: devuelve (ok, info), así que lo chequeamos.
    """
    try:
        ok, info = enviar_whatsapp(numero, mensaje, oficina=ofi_id)
        if not ok:
            # La oficina puede no tener credenciales de WhatsApp → reintento con una oficina válida.
            ok, info = enviar_whatsapp(numero, mensaje, oficina=_oficina_con_whatsapp())
        if not ok:
            logger.error(f"[cierre_caja] WhatsApp a {numero} no se envió: {info}")
        return ok
    except Exception as e:
        logger.error(f"[cierre_caja] WhatsApp a {numero} excepción: {e}")
        return False


def _fila_metrica(label, valor, color="#111827"):
    return f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;color:#6b7280">{label}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;font-weight:600;text-align:right;color:{color}">{valor}</td>
        </tr>"""


def _lista_extra_html(titulo, items):
    if not items:
        return ""
    filas = ""
    for it in items:
        filas += f"""
        <tr>
          <td style="padding:6px 12px;border-bottom:1px solid #f3f4f6;font-size:12.5px">{(it['descripcion'] or '—')}</td>
          <td style="padding:6px 12px;border-bottom:1px solid #f3f4f6;font-size:12.5px;text-align:right">{_money(it['monto'])}</td>
        </tr>"""
    return f"""
      <p style="margin:20px 0 6px;font-size:13px;font-weight:600;color:#374151">{titulo}</p>
      <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e7eb;border-radius:6px;overflow:hidden;border-collapse:collapse">
        <tbody>{filas}</tbody>
      </table>"""


def _lista_polizas_html(titulo, items, color="#374151"):
    if not items:
        return ""
    filas = ""
    for it in items:
        filas += f"""
        <tr>
          <td style="padding:6px 12px;border-bottom:1px solid #f3f4f6;font-size:12.5px">{it['nombre']}</td>
          <td style="padding:6px 12px;border-bottom:1px solid #f3f4f6;font-size:12.5px;font-family:monospace;font-weight:600;text-align:right">{it['patente']}</td>
        </tr>"""
    return f"""
      <p style="margin:20px 0 6px;font-size:13px;font-weight:600;color:{color}">{titulo} ({len(items)})</p>
      <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e7eb;border-radius:6px;overflow:hidden;border-collapse:collapse">
        <tbody>{filas}</tbody>
      </table>"""


def _email_html(cierre, r, r_pol, oficina_nombre, quien, fecha_txt):
    estado_txt, color = _estado_texto(cierre)
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f9fafb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f9fafb;padding:40px 20px">
    <tr><td>
      <table width="600" cellpadding="0" cellspacing="0" align="center"
             style="background:#ffffff;border-radius:8px;border:1px solid #e5e7eb;overflow:hidden">
        <tr>
          <td style="background:{color};padding:24px 32px">
            <p style="margin:0;color:#ffffff;font-size:18px;font-weight:500">Cierre de caja</p>
            <p style="margin:4px 0 0;color:#ffffff;opacity:.85;font-size:13px">{oficina_nombre} · {fecha_txt}</p>
          </td>
        </tr>
        <tr>
          <td style="padding:28px 32px">
            <p style="margin:0 0 4px;font-size:13px;color:#6b7280">Cerró: <strong>{quien}</strong></p>
            <p style="margin:0 0 20px;font-size:15px;font-weight:600;color:{color}">🔎 {estado_txt}</p>

            <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e7eb;border-radius:6px;overflow:hidden;border-collapse:collapse">
              <tbody>
                {_fila_metrica("Ingresos", _money(r['total_ing']))}
                {_fila_metrica("Egresos", _money(r['total_egr']))}
                {_fila_metrica("Neto", _money(r['neto']))}
                {_fila_metrica("Efectivo que entró", _money(r['ing_efectivo']))}
                {_fila_metrica("Transferencias", _money(r['ing_transfer']))}
                {_fila_metrica("Personas que pagaron", str(r['pagadores']))}
              </tbody>
            </table>

            {_lista_extra_html("⭐ Ingresos extraordinarios (no son de seguros)", r["extra_ing"])}
            {_lista_extra_html("⚠️ Egresos extraordinarios", r["extra_egr"])}

            {_lista_polizas_html("📄 Altas nuevas del día", r_pol["altas"], "#047857")}
            {_lista_polizas_html("🔄 Renovaciones del día", r_pol["renovaciones"], "#4338ca")}
            {_lista_polizas_html("📉 Bajas del día", r_pol["bajas"], "#b91c1c")}
          </td>
        </tr>
        <tr>
          <td style="background:#f9fafb;padding:20px 32px;border-top:1px solid #e5e7eb">
            <p style="margin:0;font-size:12px;color:#9ca3af">Thames Seguros · Cierre generado el {fecha_txt}</p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def notificar_cierre_caja(cierre):
    """Punto de entrada: arma y manda el aviso del cierre por WhatsApp + email."""
    try:
        try:
            fecha = timezone.localtime(cierre.creado_en).date()
        except Exception:
            fecha = timezone.localdate()
        fecha_txt = fecha.strftime("%d/%m/%Y")

        ofi_id = cierre.oficina_id
        oficina_nombre = cierre.oficina.nombre if cierre.oficina else "Sin sucursal"

        quien = "—"
        if getattr(cierre, "empleado", None) and getattr(cierre.empleado, "nombre", None):
            quien = cierre.empleado.nombre
        elif getattr(cierre, "usuario", None):
            u = cierre.usuario
            quien = f"{u.first_name} {u.last_name}".strip() or u.username

        # 🔧 Rango del turno: el cierre de la NOCHE cuenta SOLO desde el cierre
        # del mediodía (si lo hubo). Así no se duplica lo de la mañana.
        desde_turno = None
        hasta_turno = getattr(cierre, "creado_en", None)
        if getattr(cierre, "turno", "") == "noche" and ofi_id:
            try:
                from recaudacion.models import CierreCaja
                cierre_med = (
                    CierreCaja.objects.filter(
                        oficina_id=ofi_id, turno="mediodia", creado_en__date=fecha
                    )
                    .exclude(pk=getattr(cierre, "pk", None))
                    .order_by("-creado_en")
                    .first()
                )
                if cierre_med:
                    desde_turno = cierre_med.creado_en
            except Exception:
                desde_turno = None

        r = _resumen_dia(fecha, ofi_id, desde=desde_turno, hasta=hasta_turno)
        r_pol = _polizas_dia(fecha, ofi_id)

        # WhatsApp a los números de control (oficina con fallback global + chequeo de resultado)
        msg_wa = _mensaje_whatsapp(cierre, r, r_pol, oficina_nombre, quien, fecha_txt)
        for numero in WHATSAPP_NUMEROS:
            _enviar_whatsapp_control(numero, msg_wa, ofi_id)

        # Email
        if EMAILS_AVISO:
            try:
                estado_txt, _ = _estado_texto(cierre)
                asunto = f"🧾 Cierre de caja — {oficina_nombre} · {fecha_txt} ({estado_txt})"
                cuerpo = _email_html(cierre, r, r_pol, oficina_nombre, quien, fecha_txt)
                em = EmailMessage(
                    subject=asunto, body=cuerpo,
                    from_email=settings.DEFAULT_FROM_EMAIL, to=EMAILS_AVISO,
                )
                em.content_subtype = "html"
                em.send(fail_silently=False)
            except Exception as e:
                logger.error(f"[cierre_caja] Email falló: {e}")

        logger.info(f"[cierre_caja] Aviso enviado (cierre #{getattr(cierre, 'id', '?')}, {oficina_nombre})")

    except Exception as e:
        # Blindaje total: nunca romper el cierre.
        logger.error(f"[cierre_caja] Error general en el aviso: {e}")