# notificaciones/management/commands/enviar_recordatorios_cuotas.py
#
# Envía recordatorios de cuotas + oferta de 14 días por WhatsApp a TODAS las
# oficinas con credenciales de UltraMsg (modelo usuarios.Oficina). Al terminar
# manda un EMAIL con, por oficina: los mensajes enviados y los NO enviados
# (con el motivo).
#
# Uso:
#   python manage.py enviar_recordatorios_cuotas
#   python manage.py enviar_recordatorios_cuotas --oficina 1
#   python manage.py enviar_recordatorios_cuotas --no-email
#
# Cron Railway (9:00 Argentina = 12:00 UTC):  0 12 * * *

import os
import logging

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand
from django.utils import timezone

from notificaciones.services_cuotas import enviar_todo
from notificaciones.utils.mensajeria import enviar_whatsapp

logger = logging.getLogger(__name__)

# Email del resumen (override: env EMAIL_RESUMEN_RECORDATORIOS, separado por coma)
_EMAILS_DEFAULT = "francodavid_dev@outlook.com,gomezdamianricardo284@gmail.com"
EMAILS_RESUMEN = [e.strip() for e in os.environ.get("EMAIL_RESUMEN_RECORDATORIOS", _EMAILS_DEFAULT).split(",") if e.strip()]

OFICINA_NOMBRES = {"1": "5 Esquinas", "2": "Axion", "3": "Km 39", "4": "Talita"}

# Números que reciben el resumen por WhatsApp (vos + Damián).
# Override: env WHATSAPP_RESUMEN_NUMEROS (separado por coma).
_WA_DEFAULT = "1164235336,1161332173"
WHATSAPP_RESUMEN_NUMEROS = [n.strip() for n in os.environ.get("WHATSAPP_RESUMEN_NUMEROS", _WA_DEFAULT).split(",") if n.strip()]


def _oficinas_con_whatsapp():
    from usuarios.models import Oficina
    return list(
        Oficina.objects.filter(activa=True)
        .exclude(ultramsg_instance_id__isnull=True).exclude(ultramsg_instance_id="")
        .exclude(ultramsg_token__isnull=True).exclude(ultramsg_token="")
        .order_by("id")
        .values_list("id", flat=True)
    )


def _nombre_oficina(ofi_id, oficinas_map):
    return oficinas_map.get(str(ofi_id)) or OFICINA_NOMBRES.get(str(ofi_id)) or f"Oficina {ofi_id}"


def _tabla_enviados(detalles):
    if not detalles:
        return '<tr><td colspan="3" style="padding:10px 12px;font-size:13px;color:#94a3b8">Sin envíos.</td></tr>'
    out = ""
    for d in detalles:
        color = "#4f46e5" if d.get("tipo") == "Recordatorio" else "#0891b2"
        out += (
            f'<tr><td style="padding:7px 12px;border-bottom:1px solid #f1f5f9;font-size:13px;color:#111827">{d.get("cliente","—")}</td>'
            f'<td style="padding:7px 12px;border-bottom:1px solid #f1f5f9;font-size:13px;color:#475569;font-family:monospace">{d.get("telefono","—")}</td>'
            f'<td style="padding:7px 12px;border-bottom:1px solid #f1f5f9;font-size:12px;color:{color};font-weight:bold">{d.get("situacion","—")}</td></tr>'
        )
    return out


def _tabla_no_enviados(ne):
    if not ne:
        return ""
    filas = ""
    for d in ne:
        filas += (
            f'<tr><td style="padding:7px 12px;border-bottom:1px solid #fef2f2;font-size:13px;color:#111827">{d.get("cliente","—")}</td>'
            f'<td style="padding:7px 12px;border-bottom:1px solid #fef2f2;font-size:13px;color:#475569;font-family:monospace">{d.get("telefono","—")}</td>'
            f'<td style="padding:7px 12px;border-bottom:1px solid #fef2f2;font-size:12px;color:#dc2626;font-weight:bold">{d.get("motivo","—")}</td></tr>'
        )
    return (
        f'<p style="margin:12px 0 6px;font-size:13px;font-weight:bold;color:#b91c1c">⚠️ No se pudo enviar ({len(ne)})</p>'
        '<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #fecaca;border-radius:8px;border-collapse:collapse;overflow:hidden">'
        '<thead><tr style="background:#fef2f2">'
        '<th style="padding:8px 12px;text-align:left;font-size:11px;color:#b91c1c;text-transform:uppercase">Cliente</th>'
        '<th style="padding:8px 12px;text-align:left;font-size:11px;color:#b91c1c;text-transform:uppercase">Teléfono</th>'
        '<th style="padding:8px 12px;text-align:left;font-size:11px;color:#b91c1c;text-transform:uppercase">Motivo</th>'
        f'</tr></thead><tbody>{filas}</tbody></table>'
    )


def _mensaje_whatsapp_resumen(fecha_txt, por_oficina, total, total_no):
    lineas = [
        f"📲 *Recordatorios* — {fecha_txt}",
        "",
        f"*TOTAL:* {total} enviados · {total_no} sin enviar",
        "",
    ]
    for ofi, info in por_oficina.items():
        ne = len(info.get("no_enviados", []))
        lineas.append(f"🏢 *{info['nombre']}:* {info['enviados']} ✅ · {ne} ⚠️")
    return "\n".join(lineas)


def _email_html(fecha_txt, por_oficina, total):
    bloques = ""
    for ofi, info in por_oficina.items():
        enviados_tabla = _tabla_enviados(info.get("detalles", []))
        no_env_tabla = _tabla_no_enviados(info.get("no_enviados", []))
        bloques += (
            '<div style="margin:0 0 24px">'
            f'<p style="margin:0 0 8px;font-size:15px;font-weight:bold;color:#1e293b">🏢 {info["nombre"]} '
            f'<span style="font-size:12px;color:#64748b;font-weight:normal">— {info["enviados"]} enviados · {len(info.get("no_enviados", []))} no enviados</span></p>'
            '<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e2e8f0;border-radius:8px;border-collapse:collapse;overflow:hidden">'
            '<thead><tr style="background:#f8fafc">'
            '<th style="padding:8px 12px;text-align:left;font-size:11px;color:#64748b;text-transform:uppercase">Cliente</th>'
            '<th style="padding:8px 12px;text-align:left;font-size:11px;color:#64748b;text-transform:uppercase">Teléfono</th>'
            '<th style="padding:8px 12px;text-align:left;font-size:11px;color:#64748b;text-transform:uppercase">Situación</th>'
            f'</tr></thead><tbody>{enviados_tabla}</tbody></table>'
            f'{no_env_tabla}'
            '</div>'
        )

    # Consolidado de clientes sin teléfono (de todas las oficinas)
    sin_tel = []
    for ofi, info in por_oficina.items():
        for d in info.get("no_enviados", []):
            if "Sin WhatsApp" in d.get("motivo", "") or d.get("telefono") in ("—", "", None):
                sin_tel.append({"cliente": d.get("cliente", "—"), "oficina": info["nombre"], "situacion": d.get("situacion", "—")})

    sin_tel_html = ""
    if sin_tel:
        filas = ""
        for d in sin_tel:
            filas += (
                f'<tr><td style="padding:7px 12px;border-bottom:1px solid #fffbeb;font-size:13px;color:#111827">{d["cliente"]}</td>'
                f'<td style="padding:7px 12px;border-bottom:1px solid #fffbeb;font-size:13px;color:#475569">{d["oficina"]}</td>'
                f'<td style="padding:7px 12px;border-bottom:1px solid #fffbeb;font-size:12px;color:#b45309">{d["situacion"]}</td></tr>'
            )
        sin_tel_html = (
            '<div style="margin:8px 0 0;padding:18px;background:#fffbeb;border:1px solid #fde68a;border-radius:10px">'
            f'<p style="margin:0 0 8px;font-size:15px;font-weight:bold;color:#b45309">📵 Clientes sin teléfono — completar ({len(sin_tel)})</p>'
            '<p style="margin:0 0 12px;font-size:12px;color:#92400e">No se les pudo avisar porque no tienen WhatsApp cargado. Cargales el número en su ficha.</p>'
            '<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #fde68a;border-radius:8px;border-collapse:collapse;overflow:hidden;background:#fff">'
            '<thead><tr style="background:#fef3c7">'
            '<th style="padding:8px 12px;text-align:left;font-size:11px;color:#b45309;text-transform:uppercase">Cliente</th>'
            '<th style="padding:8px 12px;text-align:left;font-size:11px;color:#b45309;text-transform:uppercase">Oficina</th>'
            '<th style="padding:8px 12px;text-align:left;font-size:11px;color:#b45309;text-transform:uppercase">Situación</th>'
            f'</tr></thead><tbody>{filas}</tbody></table></div>'
        )

    return (
        '<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"></head>'
        '<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif">'
        '<table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:32px 16px"><tr><td>'
        '<table width="640" cellpadding="0" cellspacing="0" align="center" style="background:#fff;border-radius:10px;border:1px solid #e2e8f0;overflow:hidden">'
        '<tr><td style="background:#4f46e5;padding:22px 28px">'
        '<p style="margin:0;color:#fff;font-size:18px;font-weight:600">Recordatorios enviados</p>'
        f'<p style="margin:4px 0 0;color:#c7d2fe;font-size:13px">Thames Seguros · {fecha_txt} · {total} mensajes en total</p>'
        '</td></tr>'
        f'<tr><td style="padding:24px 28px">{bloques}{sin_tel_html}</td></tr>'
        '<tr><td style="background:#f8fafc;padding:16px 28px;border-top:1px solid #e2e8f0">'
        f'<p style="margin:0;font-size:12px;color:#94a3b8">Envío automático diario · {fecha_txt}</p>'
        '</td></tr></table></td></tr></table></body></html>'
    )


class Command(BaseCommand):
    help = "Envía recordatorios + oferta a todas las oficinas con credenciales y manda email-resumen."

    def add_arguments(self, parser):
        parser.add_argument("--oficina", default=None, help="Forzar una sola oficina (id).")
        parser.add_argument("--alias", default=None, help="Alias/CBU a mostrar en el mensaje.")
        parser.add_argument("--medio-cobro-id", type=int, default=None, help="ID de MedioCobro.")
        parser.add_argument("--no-email", action="store_true", help="No enviar el email-resumen.")

    def handle(self, *args, **opts):
        hoy = timezone.localdate()
        fecha_txt = hoy.strftime("%d/%m/%Y")

        if opts.get("oficina"):
            oficinas = [str(opts["oficina"])]
        else:
            oficinas = [str(o) for o in _oficinas_con_whatsapp()]

        if not oficinas:
            self.stdout.write(self.style.WARNING("No hay oficinas con credenciales de UltraMsg."))
            return

        oficinas_map = {}
        try:
            from usuarios.models import Oficina
            for o in Oficina.objects.all():
                oficinas_map[str(o.id)] = o.nombre
        except Exception:
            pass

        self.stdout.write(f"Oficinas a procesar: {oficinas}")
        por_oficina = {}
        total = 0

        for ofi in oficinas:
            self.stdout.write(f"▶ Oficina {ofi}...")
            try:
                res = enviar_todo(
                    hoy=hoy,
                    alias_transferencia=opts.get("alias"),
                    medio_cobro_id=opts.get("medio_cobro_id"),
                    oficina=ofi,
                )
                rec = res["recordatorios"]["enviados"]
                ofe = res.get("ofertas", {}).get("enviados", 0)
                por_oficina[ofi] = {
                    "nombre": _nombre_oficina(ofi, oficinas_map),
                    "enviados": rec + ofe,
                    "recordatorios": rec,
                    "ofertas": ofe,
                    "detalles": res.get("detalles", []),
                    "no_enviados": res.get("no_enviados", []),
                }
                ne = len(res.get("no_enviados", []))
                self.stdout.write(f"   recordatorios={rec} · ofertas(14d)={ofe} · no_enviados={ne}")
                total += rec + ofe
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"   ❌ Oficina {ofi} falló: {exc}"))
                por_oficina[ofi] = {
                    "nombre": _nombre_oficina(ofi, oficinas_map),
                    "enviados": 0, "recordatorios": 0, "ofertas": 0,
                    "detalles": [], "no_enviados": [],
                }

        self.stdout.write(self.style.SUCCESS(f"✓ Total enviados: {total}"))

        if not opts.get("no_email") and EMAILS_RESUMEN:
            try:
                em = EmailMessage(
                    subject=f"📲 Recordatorios enviados — {fecha_txt} ({total})",
                    body=_email_html(fecha_txt, por_oficina, total),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=EMAILS_RESUMEN,
                )
                em.content_subtype = "html"
                em.send(fail_silently=False)
                self.stdout.write(self.style.SUCCESS(f"✉️  Email enviado a: {', '.join(EMAILS_RESUMEN)}"))
            except Exception as e:
                logger.error(f"[recordatorios] Email-resumen falló: {e}")
                self.stdout.write(self.style.ERROR(f"✉️  Email falló: {e}"))

        # ── Resumen corto por WhatsApp (vos + Damián) ──────────────────
        if WHATSAPP_RESUMEN_NUMEROS:
            total_no = sum(len(i.get("no_enviados", [])) for i in por_oficina.values())
            msg_wa = _mensaje_whatsapp_resumen(fecha_txt, por_oficina, total, total_no)
            ofi_emisora = oficinas[0] if oficinas else None
            for numero in WHATSAPP_RESUMEN_NUMEROS:
                try:
                    ok, info = enviar_whatsapp(numero, msg_wa, oficina=ofi_emisora)
                    if ok:
                        self.stdout.write(self.style.SUCCESS(f"📲 Resumen WhatsApp a {numero}"))
                    else:
                        self.stdout.write(self.style.ERROR(f"📲 WhatsApp a {numero} no salió: {info}"))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"📲 WhatsApp a {numero} excepción: {e}"))