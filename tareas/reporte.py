# tareas/reporte.py
#
# Reporte diario de tareas ("buchón") por oficina, a las 20:00.
# Cuenta lo COMPLETADO hoy (de TareaCompletada) y lo PENDIENTE ahora
# (de armar_tareas_dia) para cada oficina, y lo manda por WhatsApp + email.
# Reutiliza el mismo envío que el aviso de cierre de caja.

import os
import logging

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone

from usuarios.models import Oficina
from notificaciones.utils.mensajeria import enviar_whatsapp

from .models import TareaCompletada
from .services import armar_tareas_dia
from .buchon_fijas import resumen_buchon_fijas, EMAILS_CONTROL_DIARIO

logger = logging.getLogger(__name__)

# Mismos destinatarios que el cierre de caja
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
EMAIL_REPORTE = os.environ.get("EMAIL_REPORTE_TAREAS", "Gomezdamianricardo284@gmail.com")

TIPO_LABEL = {
    "enviar": "Enviar póliza",
    "datos_poliza": "Datos póliza",
    "datos_cliente": "Datos cliente",
    "fotos_dni": "Fotos DNI",
    "fotos_poliza": "Fotos vehículo",
}
ORDEN = ["enviar", "datos_poliza", "datos_cliente", "fotos_dni", "fotos_poliza"]


def _datos_oficina(ofi_id, hoy):
    comp = (
        TareaCompletada.objects
        .filter(oficina_id=ofi_id, creado_en__date=hoy)
        .values_list("tipo", flat=True)
    )
    completadas = {}
    for t in comp:
        completadas[t] = completadas.get(t, 0) + 1

    pendientes = armar_tareas_dia(oficina_id=ofi_id).get("total", 0)
    return {
        "completadas": completadas,
        "total_comp": sum(completadas.values()),
        "total_pend": pendientes,
    }


def _construir(hoy):
    filas, g_comp, g_pend = [], 0, 0
    for ofi in Oficina.objects.all().order_by("id"):
        d = _datos_oficina(ofi.id, hoy)
        g_comp += d["total_comp"]
        g_pend += d["total_pend"]
        filas.append({"oficina": ofi.nombre, **d})
    return filas, g_comp, g_pend


def _mensaje_whatsapp(filas, g_comp, g_pend, fecha_txt):
    partes = [
        f"📋 *Reporte de tareas* — {fecha_txt}",
        f"✅ Hechas hoy: {g_comp}   ⏳ Pendientes: {g_pend}",
        "",
    ]
    for f in filas:
        partes.append(f"🏢 *{f['oficina']}*")
        partes.append(f"   ✅ Hechas hoy: {f['total_comp']}")
        for t in ORDEN:
            if f["completadas"].get(t):
                partes.append(f"      • {TIPO_LABEL[t]}: {f['completadas'][t]}")
        flag = "  ⚠️" if f["total_pend"] > 0 else ""
        partes.append(f"   ⏳ Pendientes: {f['total_pend']}{flag}")
        partes.append("")
    return "\n".join(partes).strip()


def _email_html(filas, g_comp, g_pend, fecha_txt):
    bloques = ""
    for f in filas:
        detalle = ""
        for t in ORDEN:
            if f["completadas"].get(t):
                detalle += f"<li style='font-size:12.5px;color:#374151'>{TIPO_LABEL[t]}: <strong>{f['completadas'][t]}</strong></li>"
        if not detalle:
            detalle = "<li style='font-size:12.5px;color:#9ca3af'>Sin tareas completadas hoy</li>"
        color_pend = "#b91c1c" if f["total_pend"] > 0 else "#047857"
        bloques += f"""
        <tr><td style="padding:16px 20px;border-bottom:1px solid #e5e7eb">
          <p style="margin:0 0 8px;font-size:15px;font-weight:600;color:#111827">🏢 {f['oficina']}</p>
          <p style="margin:0 0 4px;font-size:13px;color:#374151">✅ Completadas hoy: <strong>{f['total_comp']}</strong></p>
          <ul style="margin:4px 0 8px 18px;padding:0">{detalle}</ul>
          <p style="margin:0;font-size:13px;color:{color_pend}">⏳ Pendientes ahora: <strong>{f['total_pend']}</strong></p>
        </td></tr>"""
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f9fafb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f9fafb;padding:40px 20px"><tr><td>
    <table width="600" cellpadding="0" cellspacing="0" align="center" style="background:#fff;border-radius:8px;border:1px solid #e5e7eb;overflow:hidden">
      <tr><td style="background:#4338ca;padding:24px 32px">
        <p style="margin:0;color:#fff;font-size:18px;font-weight:500">Reporte de tareas</p>
        <p style="margin:4px 0 0;color:#fff;opacity:.85;font-size:13px">{fecha_txt}</p>
      </td></tr>
      <tr><td style="padding:20px 32px;border-bottom:1px solid #e5e7eb">
        <p style="margin:0;font-size:14px;color:#374151">✅ Completadas hoy (total): <strong>{g_comp}</strong> &nbsp;·&nbsp; ⏳ Pendientes (total): <strong>{g_pend}</strong></p>
      </td></tr>
      {bloques}
      <tr><td style="background:#f9fafb;padding:20px 32px;border-top:1px solid #e5e7eb">
        <p style="margin:0;font-size:12px;color:#9ca3af">Thames Seguros · Reporte generado el {fecha_txt}</p>
      </td></tr>
    </table>
  </td></tr></table>
</body></html>"""


def enviar_reporte_tareas(dry_run=False):
    """Arma y manda el reporte diario de tareas por WhatsApp + email."""
    try:
        hoy = timezone.localdate()
        fecha_txt = hoy.strftime("%d/%m/%Y")
        filas, g_comp, g_pend = _construir(hoy)

        msg_wa = _mensaje_whatsapp(filas, g_comp, g_pend, fecha_txt)
        html = _email_html(filas, g_comp, g_pend, fecha_txt)

        # 🆕 Sumar el buchón del Control diario (tareas fijas con foto)
        buchon = resumen_buchon_fijas(hoy)
        if buchon.get("hay_datos"):
            msg_wa = msg_wa + "\n\n" + buchon["texto_whatsapp"]
            bloque_html = (
                '<tr><td style="padding:16px 20px;border-bottom:1px solid #e5e7eb">'
                + buchon["html_email"] + '</td></tr>'
            )
            html = html.replace(
                '<tr><td style="background:#f9fafb;padding:20px 32px;border-top',
                bloque_html + '<tr><td style="background:#f9fafb;padding:20px 32px;border-top',
                1,
            )

        if dry_run:
            print(msg_wa)
            print("\n[dry-run] No se envió nada.")
            return

        ofi_wa = _oficina_con_whatsapp()
        for numero in WHATSAPP_NUMEROS:
            try:
                ok, info = enviar_whatsapp(numero, msg_wa, oficina=ofi_wa)
                if not ok:
                    logger.error(f"[reporte_tareas] WhatsApp a {numero} no se envió: {info}")
            except Exception as e:
                logger.error(f"[reporte_tareas] WhatsApp a {numero} excepción: {e}")

        destinatarios = EMAILS_CONTROL_DIARIO or ([EMAIL_REPORTE] if EMAIL_REPORTE else [])
        if destinatarios:
            try:
                em = EmailMessage(
                    subject=f"📋 Reporte de tareas — {fecha_txt}",
                    body=html,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=destinatarios,
                )
                em.content_subtype = "html"
                em.send(fail_silently=False)
            except Exception as e:
                logger.error(f"[reporte_tareas] Email falló: {e}")

        logger.info(f"[reporte_tareas] Reporte enviado ({fecha_txt})")

    except Exception as e:
        logger.error(f"[reporte_tareas] Error general: {e}")


# ════════════ management command ════════════