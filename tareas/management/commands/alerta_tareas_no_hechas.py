# tareas/management/commands/alerta_tareas_no_hechas.py
#
# Vigilante "a horario": revisa las tareas fijas que ya pasaron su horario
# + margen (ej. 15 min) y todavía NO están completas, y manda un email por
# cada una a los responsables de control. No repite avisos (AlertaTareaFijaEnviada).
#
# Pensado para correr como cron cada ~5-10 min en Railway:
#     CRON_COMMAND="alerta_tareas_no_hechas"
#
from datetime import datetime, timedelta

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand
from django.utils import timezone

from usuarios.models import Oficina
from tareas.models_fijas import (
    TareaFija, CumplimientoTareaFija, Feriado, AlertaTareaFijaEnviada,
)
from tareas.buchon_fijas import EMAILS_CONTROL_DIARIO


def _fotos_subidas(cumpl):
    """Cuántas fotos tiene el álbum (compatibilidad con la foto_url vieja)."""
    if cumpl is None:
        return 0
    try:
        n = cumpl.fotos.count()
    except Exception:
        n = 0
    if n == 0 and getattr(cumpl, "foto_url", ""):
        return 1
    return n


def _enviar_email_tarea(*, tarea_nombre, oficina_nombre, hora_txt, faltan_fotos, fotos_min):
    if not EMAILS_CONTROL_DIARIO:
        return
    detalle_fotos = ""
    if fotos_min > 1:
        detalle_fotos = f"<p style='margin:0 0 10px;font-size:13px;color:#6b7280'>Faltan {faltan_fotos} de {fotos_min} fotos.</p>"
    html = f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:24px;background:#f9fafb;font-family:-apple-system,Segoe UI,sans-serif">
  <table width="520" cellpadding="0" cellspacing="0" align="center" style="background:#fff;border-radius:8px;border:1px solid #e5e7eb;overflow:hidden">
    <tr><td style="background:#b91c1c;padding:18px 24px">
      <p style="margin:0;color:#fff;font-size:16px;font-weight:600">⚠️ Tarea no hecha a horario</p>
    </td></tr>
    <tr><td style="padding:18px 24px">
      <p style="margin:0 0 4px;font-size:16px;font-weight:600;color:#111827">{tarea_nombre}</p>
      <p style="margin:0 0 10px;font-size:14px;color:#374151">{oficina_nombre}</p>
      {detalle_fotos}
      <p style="margin:0;font-size:14px;font-weight:600;color:#b91c1c">🕐 Debía hacerse a las {hora_txt} y todavía no está.</p>
    </td></tr>
  </table>
</body></html>"""
    try:
        em = EmailMessage(
            subject=f"⚠️ No hecha a horario: {tarea_nombre} — {oficina_nombre}",
            body=html,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=EMAILS_CONTROL_DIARIO,
        )
        em.content_subtype = "html"
        em.send(fail_silently=True)
        return True
    except Exception:
        return False


class Command(BaseCommand):
    help = "Avisa por email las tareas fijas no hechas a horario (pasado el margen)."

    def handle(self, *args, **options):
        hoy = timezone.localdate()
        ahora = timezone.localtime()

        # Domingo (6) no se trabaja, y feriados tampoco.
        if hoy.weekday() == 6 or Feriado.objects.filter(fecha=hoy).exists():
            self.stdout.write("Hoy no se esperan tareas (domingo/feriado).")
            return

        oficinas = list(Oficina.objects.filter(activa=True))
        # Cumplimientos de hoy indexados (tarea, oficina)
        cumpl = {}
        for c in (CumplimientoTareaFija.objects
                  .filter(fecha=hoy).prefetch_related("fotos")):
            cumpl[(c.tarea_id, c.oficina_id)] = c

        # Avisos ya enviados hoy (para no repetir)
        ya = set(
            AlertaTareaFijaEnviada.objects
            .filter(fecha=hoy).values_list("tarea_id", "oficina_id")
        )

        tareas = list(TareaFija.objects.filter(activa=True, hora_esperada__isnull=False))
        enviados = 0

        for ofi in oficinas:
            for t in tareas:
                # ¿La tarea aplica a esta oficina hoy?
                if not (t.oficina_id == ofi.id or t.oficina_id is None):
                    continue
                if not t.aplica_en(hoy):
                    continue
                if (t.id, ofi.id) in ya:
                    continue  # ya avisamos

                # Las tareas de cierre (premia_demora) NO se alertan: cerrar tarde está bien.
                if getattr(t, "premia_demora", False):
                    continue

                # Hora límite = hora_esperada + margen
                margen = t.margen_alerta or 15
                hora_obj = datetime.combine(hoy, t.hora_esperada)
                if timezone.is_naive(hora_obj):
                    hora_obj = timezone.make_aware(hora_obj, timezone.get_current_timezone())
                limite = hora_obj + timedelta(minutes=margen)

                if ahora < limite:
                    continue  # todavía está en tiempo

                # ¿Está completa? (según fotos_min)
                c = cumpl.get((t.id, ofi.id))
                n = _fotos_subidas(c)
                fmin = getattr(t, "fotos_min", 1) or 1
                if n >= fmin:
                    continue  # ya está hecha

                # → Avisar
                ok = _enviar_email_tarea(
                    tarea_nombre=t.nombre,
                    oficina_nombre=ofi.nombre,
                    hora_txt=t.hora_esperada.strftime("%H:%M"),
                    faltan_fotos=max(0, fmin - n),
                    fotos_min=fmin,
                )
                # Marcar como enviado (aunque el email falle, para no spamear en loop)
                try:
                    AlertaTareaFijaEnviada.objects.get_or_create(
                        tarea=t, oficina=ofi, fecha=hoy,
                    )
                except Exception:
                    pass
                if ok:
                    enviados += 1
                    self.stdout.write(f"  ⚠ Avisé: {t.nombre} — {ofi.nombre}")

        self.stdout.write(self.style.SUCCESS(f"Listo. {enviados} aviso(s) enviado(s)."))