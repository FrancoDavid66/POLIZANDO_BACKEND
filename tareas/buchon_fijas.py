# tareas/buchon_fijas.py
#
# Arma el "buchón" del Control diario: resumen de qué oficina cumplió sus
# tareas fijas y cuáles faltaron (con el responsable). Devuelve listo para:
#   - WhatsApp (texto plano)
#   - Email (HTML)
#
# Pensado para sumarse al reporte diario de las 20:00 (no manda nada por sí solo;
# solo arma el contenido para que el reporte existente lo incluya).

from django.utils import timezone

from .services_fijas import armar_tareas_fijas_dia


def resumen_buchon_fijas(fecha=None) -> dict:
    """
    Devuelve:
      {
        "hay_datos": bool,        # False si no hay tareas fijas cargadas
        "feriado": bool,
        "texto_whatsapp": str,    # para sumar al WhatsApp del reporte
        "html_email": str,        # para sumar al email del reporte
        "todo_ok": bool,          # True si todas las oficinas cumplieron todo
      }
    """
    fecha = fecha or timezone.localdate()
    data = armar_tareas_fijas_dia(oficina_id=None, fecha=fecha)
    fecha_txt = data.get("fecha", "")

    # ── Feriado ────────────────────────────────────────────────
    if data.get("feriado"):
        nombre = data.get("feriado_nombre", "")
        return {
            "hay_datos": True,
            "feriado": True,
            "todo_ok": True,
            "texto_whatsapp": f"📋 *Control diario* ({fecha_txt})\n🎌 Feriado ({nombre}): no se esperan tareas.",
            "html_email": (
                f"<h3 style='margin:0 0 6px'>📋 Control diario ({fecha_txt})</h3>"
                f"<p style='margin:0;color:#b45309'>🎌 Feriado ({nombre}): no se esperan tareas.</p>"
            ),
        }

    oficinas = [o for o in data.get("oficinas", []) if o.get("total", 0) > 0]

    # ── Sin tareas cargadas ────────────────────────────────────
    if not oficinas:
        return {
            "hay_datos": False, "feriado": False, "todo_ok": True,
            "texto_whatsapp": "", "html_email": "",
        }

    # ── Armar resumen ──────────────────────────────────────────
    lineas_wsp = [f"📋 *Control diario* ({fecha_txt})"]
    filas_html = []
    todo_ok = True

    for ofi in oficinas:
        nombre = ofi["oficina_nombre"]
        cumplidas = ofi["cumplidas"]
        total = ofi["total"]
        faltantes = [t for t in ofi["tareas"] if not t["cumplida"]]

        if faltantes:
            todo_ok = False
            icono = "⚠️"
            color = "#b45309"
        else:
            icono = "✅"
            color = "#047857"

        lineas_wsp.append(f"{icono} {nombre}: {cumplidas}/{total}")
        for t in faltantes:
            resp = f" — {t['responsable']}" if t.get("responsable") else ""
            lineas_wsp.append(f"   ❌ {t['nombre']}{resp}")

        # HTML
        detalle_html = ""
        if faltantes:
            items = "".join(
                f"<li>❌ {t['nombre']}"
                + (f" <span style='color:#64748b'>— {t['responsable']}</span>" if t.get('responsable') else "")
                + "</li>"
                for t in faltantes
            )
            detalle_html = f"<ul style='margin:4px 0 0 18px;padding:0;color:#334155'>{items}</ul>"

        filas_html.append(
            f"<div style='margin:0 0 8px'>"
            f"<span style='font-weight:600;color:{color}'>{icono} {nombre}</span> "
            f"<span style='color:#64748b'>· {cumplidas}/{total}</span>"
            f"{detalle_html}</div>"
        )

    texto_whatsapp = "\n".join(lineas_wsp)
    html_email = (
        f"<h3 style='margin:0 0 8px'>📋 Control diario ({fecha_txt})</h3>"
        + "".join(filas_html)
    )

    return {
        "hay_datos": True,
        "feriado": False,
        "todo_ok": todo_ok,
        "texto_whatsapp": texto_whatsapp,
        "html_email": html_email,
    }


# ════════════════════════════════════════════════════════════════════
#  Envío de la FOTO de cada cumplimiento por email (al instante)
# ════════════════════════════════════════════════════════════════════
import os
from django.conf import settings
from django.core.mail import EmailMessage

# Los 2 emails de siempre (mismos que el cierre de caja). Override con env.
EMAILS_CONTROL_DIARIO = [
    e.strip() for e in os.environ.get(
        "EMAIL_CONTROL_DIARIO",
        "francodavid_dev@outlook.com,gomezdamianricardo284@gmail.com",
    ).split(",") if e.strip()
]


# Los 2 números de siempre (mismos que el reporte de las 20:00). Override con env.
WHATSAPP_CONTROL_DIARIO = [
    n.strip() for n in os.environ.get(
        "WHATSAPP_CONTROL_DIARIO", "1164235336,1161332173"
    ).split(",") if n.strip()
]


def _oficina_con_whatsapp():
    """Id de una oficina activa con credenciales de UltraMsg (para mandar el aviso)."""
    try:
        from usuarios.models import Oficina
        ofi = (
            Oficina.objects.filter(activa=True)
            .exclude(ultramsg_instance_id__isnull=True).exclude(ultramsg_instance_id="")
            .exclude(ultramsg_token__isnull=True).exclude(ultramsg_token="")
            .order_by("id").first()
        )
        return ofi.id if ofi else None
    except Exception:
        return None


def avisar_tarea_cumplida_whatsapp(*, tarea_nombre, oficina_nombre, usuario, hora_txt="", estado_tiempo="", puntos=0):
    """Manda un WhatsApp corto avisando quién completó la tarea (sin foto)."""
    if not WHATSAPP_CONTROL_DIARIO:
        return
    try:
        from notificaciones.utils.mensajeria import enviar_whatsapp
    except Exception:
        return
    quien = usuario or "Alguien"
    extra = f"\n🕐 {hora_txt}" if hora_txt else ""
    sello = {
        "adelantado": "⭐ Adelantado",
        "a_tiempo": "✅ A tiempo",
        "tarde": "⚠️ Tarde",
        "extra": "💪 Horas extra",
    }.get(estado_tiempo, "")
    pts = f" ({'+' if puntos >= 0 else ''}{puntos} pts)" if puntos else ""
    estado_line = f"\n{sello}{pts}" if sello else ""
    msg = (
        f"✅ *Control diario* — {oficina_nombre}\n"
        f"{quien} completó: *{tarea_nombre}*{extra}{estado_line}"
    )
    ofi_wa = _oficina_con_whatsapp()
    for numero in WHATSAPP_CONTROL_DIARIO:
        try:
            enviar_whatsapp(numero, msg, oficina=ofi_wa)
        except Exception:
            pass


def enviar_foto_cumplimiento(*, tarea_nombre, oficina_nombre, usuario, foto_url, fecha_txt, hora_txt=""):
    """Manda un email con la foto de la tarea recién cumplida a los 2 mails."""
    if not foto_url or not EMAILS_CONTROL_DIARIO:
        return
    html = f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:24px;background:#f9fafb;font-family:-apple-system,Segoe UI,sans-serif">
  <table width="520" cellpadding="0" cellspacing="0" align="center" style="background:#fff;border-radius:8px;border:1px solid #e5e7eb;overflow:hidden">
    <tr><td style="background:#4338ca;padding:18px 24px">
      <p style="margin:0;color:#fff;font-size:16px;font-weight:600">📸 Control diario — tarea cumplida</p>
    </td></tr>
    <tr><td style="padding:18px 24px">
      <p style="margin:0 0 4px;font-size:16px;font-weight:600;color:#111827">{tarea_nombre}</p>
      <p style="margin:0 0 14px;font-size:13px;color:#6b7280">{oficina_nombre} · {usuario or '—'}</p>
      <p style="margin:0 0 14px;font-size:14px;font-weight:600;color:#047857">🕐 Cumplida a las {hora_txt or '—'} del {fecha_txt}</p>
      <img src="{foto_url}" alt="Foto" style="max-width:100%;border-radius:8px;border:1px solid #e5e7eb" />
      <p style="margin:14px 0 0;font-size:13px"><a href="{foto_url}" style="color:#4338ca">Ver foto en grande</a></p>
    </td></tr>
  </table>
</body></html>"""
    try:
        em = EmailMessage(
            subject=f"📸 {tarea_nombre} — {oficina_nombre} ({fecha_txt})",
            body=html,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=EMAILS_CONTROL_DIARIO,
        )
        em.content_subtype = "html"
        em.send(fail_silently=True)
    except Exception:
        pass