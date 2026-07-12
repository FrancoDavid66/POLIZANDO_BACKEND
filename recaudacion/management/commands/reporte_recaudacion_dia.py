# recaudacion/management/commands/reporte_recaudacion_dia.py
#
# Parte de recaudación del día: ingresos, egresos y neto de cada oficina
# con movimiento, más el TOTAL GENERAL de todo el negocio.
# Corre 1 vez al día por cron (20:00 Argentina).
#
#   python manage.py reporte_recaudacion_dia
#   python manage.py reporte_recaudacion_dia --dry-run

import os
import logging
from decimal import Decimal

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.utils import timezone

from usuarios.models import Oficina
from balanzes.models import Ingreso, Egreso
from notificaciones.utils.mensajeria import enviar_whatsapp

logger = logging.getLogger(__name__)

_EMAILS_DEFAULT = "francodavid_dev@outlook.com"
EMAILS_AVISO = [e.strip() for e in os.environ.get("EMAIL_AVISO_RECAUDACION", _EMAILS_DEFAULT).split(",") if e.strip()]
_WHATSAPP_DEFAULT = "1164235336"
WHATSAPP_NUMEROS = [n.strip() for n in os.environ.get("WHATSAPP_AVISO_RECAUDACION", _WHATSAPP_DEFAULT).split(",") if n.strip()]

INDIGO = "#4338ca"


def _oficina_con_whatsapp():
    """Id de una oficina activa con credenciales de UltraMsg cargadas (o None)."""
    try:
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


def _money(v):
    try:
        n = float(v or 0)
    except Exception:
        n = 0.0
    s = f"{n:,.2f}"
    return "$" + s.replace(",", "X").replace(".", ",").replace("X", ".")


def _datos_dia(hoy):
    ing = {
        r["oficina_id"]: (r["total"] or Decimal("0"))
        for r in Ingreso.objects.filter(fecha=hoy).values("oficina_id").annotate(total=Sum("monto"))
    }
    egr = {
        r["oficina_id"]: (r["total"] or Decimal("0"))
        for r in Egreso.objects.filter(fecha=hoy).values("oficina_id").annotate(total=Sum("monto"))
    }

    ofi_ids = set(ing) | set(egr)
    nombres = {o.id: o.nombre for o in Oficina.objects.filter(id__in=[i for i in ofi_ids if i])}

    filas, tot_ing, tot_egr = [], Decimal("0"), Decimal("0")
    for oid in sorted(ofi_ids, key=lambda x: (x is None, x or 0)):
        i = ing.get(oid) or Decimal("0")
        e = egr.get(oid) or Decimal("0")
        tot_ing += i
        tot_egr += e
        filas.append({
            "oficina": nombres.get(oid, "Sin sucursal"),
            "ing": i, "egr": e, "neto": i - e,
        })
    return filas, tot_ing, tot_egr, (tot_ing - tot_egr)


def _mensaje_whatsapp(filas, t_ing, t_egr, t_neto, fecha_txt):
    partes = [
        f"💰 *RECAUDACIÓN DEL DÍA*",
        f"🗓️ {fecha_txt}",
        "",
        "*TOTAL GENERAL*",
        f"📥 Ingresos:  {_money(t_ing)}",
        f"📤 Egresos:   {_money(t_egr)}",
        f"📊 Neto:      *{_money(t_neto)}*",
        "",
        "━━━━━━━━━━━━━━",
        "*POR SUCURSAL*",
    ]
    if not filas:
        partes.append("")
        partes.append("Sin movimientos hoy.")
    for f in filas:
        partes.append("")
        partes.append(f"🏢 *{f['oficina']}*")
        partes.append(f"     📥 Ingresos:  {_money(f['ing'])}")
        partes.append(f"     📤 Egresos:   {_money(f['egr'])}")
        partes.append(f"     📊 Neto:      {_money(f['neto'])}")
    return "\n".join(partes)


def _email_html(filas, t_ing, t_egr, t_neto, fecha_txt):
    filas_html = ""
    for f in filas:
        neto_color = "#047857" if f["neto"] >= 0 else "#b91c1c"
        filas_html += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:13px">{f['oficina']}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;text-align:right">{_money(f['ing'])}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;text-align:right">{_money(f['egr'])}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;text-align:right;font-weight:600;color:{neto_color}">{_money(f['neto'])}</td>
        </tr>"""
    if not filas:
        filas_html = '<tr><td colspan="4" style="padding:14px;text-align:center;color:#9ca3af;font-size:13px">Sin movimientos hoy</td></tr>'

    neto_color = "#047857" if t_neto >= 0 else "#b91c1c"
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f9fafb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f9fafb;padding:40px 20px"><tr><td>
    <table width="620" cellpadding="0" cellspacing="0" align="center" style="background:#fff;border-radius:8px;border:1px solid #e5e7eb;overflow:hidden">
      <tr><td style="background:{INDIGO};padding:24px 32px">
        <p style="margin:0;color:#fff;font-size:18px;font-weight:500">Recaudación del día</p>
        <p style="margin:4px 0 0;color:#c7d2fe;font-size:13px">{settings.EMAIL_REMITENTE_NOMBRE} · {fecha_txt}</p>
      </td></tr>

      <tr><td style="padding:24px 32px 8px">
        <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e7eb;border-radius:6px;overflow:hidden;border-collapse:collapse">
          <tbody>
            <tr>
              <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;color:#6b7280">Ingresos totales</td>
              <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;font-size:14px;font-weight:600;text-align:right">{_money(t_ing)}</td>
            </tr>
            <tr>
              <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;color:#6b7280">Egresos totales</td>
              <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;font-size:14px;font-weight:600;text-align:right">{_money(t_egr)}</td>
            </tr>
            <tr>
              <td style="padding:10px 12px;font-size:13px;color:#6b7280">Neto general</td>
              <td style="padding:10px 12px;font-size:16px;font-weight:700;text-align:right;color:{neto_color}">{_money(t_neto)}</td>
            </tr>
          </tbody>
        </table>
      </td></tr>

      <tr><td style="padding:8px 32px 24px">
        <p style="margin:16px 0 6px;font-size:13px;font-weight:600;color:#374151">Detalle por sucursal</p>
        <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e7eb;border-radius:6px;overflow:hidden;border-collapse:collapse">
          <thead><tr style="background:#f3f4f6">
            <th style="padding:8px 12px;text-align:left;font-size:11px;color:#6b7280">Sucursal</th>
            <th style="padding:8px 12px;text-align:right;font-size:11px;color:#6b7280">Ingresos</th>
            <th style="padding:8px 12px;text-align:right;font-size:11px;color:#6b7280">Egresos</th>
            <th style="padding:8px 12px;text-align:right;font-size:11px;color:#6b7280">Neto</th>
          </tr></thead>
          <tbody>{filas_html}</tbody>
        </table>
      </td></tr>

      <tr><td style="background:#f9fafb;padding:20px 32px;border-top:1px solid #e5e7eb">
        <p style="margin:0;font-size:12px;color:#9ca3af">{settings.EMAIL_REMITENTE_NOMBRE} · Generado el {fecha_txt}</p>
      </td></tr>
    </table>
  </td></tr></table>
</body></html>"""


class Command(BaseCommand):
    help = "Parte de recaudación del día (ingresos/egresos/neto por oficina + total) por email + WhatsApp."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Muestra sin enviar.")

    def handle(self, *args, **options):
        dry = bool(options.get("dry_run"))
        hoy = timezone.localdate()
        fecha_txt = hoy.strftime("%d/%m/%Y")

        filas, t_ing, t_egr, t_neto = _datos_dia(hoy)
        msg_wa = _mensaje_whatsapp(filas, t_ing, t_egr, t_neto, fecha_txt)

        if dry:
            self.stdout.write(msg_wa)
            self.stdout.write("\n[dry-run] No se envió nada.")
            return

        # Email
        if EMAILS_AVISO:
            try:
                em = EmailMessage(
                    subject=f"💰 Recaudación del día — {fecha_txt} (neto {_money(t_neto)})",
                    body=_email_html(filas, t_ing, t_egr, t_neto, fecha_txt),
                    from_email=settings.DEFAULT_FROM_EMAIL, to=EMAILS_AVISO,
                )
                em.content_subtype = "html"
                em.send(fail_silently=False)
            except Exception as e:
                logger.error(f"[recaudacion_dia] Email falló: {e}")

        # WhatsApp
        ofi_wa = _oficina_con_whatsapp()
        for numero in WHATSAPP_NUMEROS:
            try:
                ok, info = enviar_whatsapp(numero, msg_wa, oficina=ofi_wa)
                if not ok:
                    logger.error(f"[recaudacion_dia] WhatsApp a {numero} no se envió: {info}")
            except Exception as e:
                logger.error(f"[recaudacion_dia] WhatsApp a {numero} excepción: {e}")

        self.stdout.write(self.style.SUCCESS(f"✓ Parte de recaudación enviado (neto {_money(t_neto)})"))