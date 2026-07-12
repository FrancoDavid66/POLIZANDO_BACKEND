# polizas/management/commands/renovar_automaticas.py
#
# Renueva AUTOMÁTICAMENTE las pólizas que:
#   - Están 100% al día (sin ninguna cuota impaga).
#   - Su última cuota ya venció (finalizadas) o vence dentro de los próximos 3 días.
#   - No tienen una renovación previa (no se renueva dos veces).
#   - No tienen una baja en curso ni están canceladas.
#   - No están marcadas como "no renueva" (si ese campo existe).
#
# Reusa el MISMO motor de renovación del botón manual (handle_renovar_poliza),
# así que la lógica de fechas, cuotas en $0 y empalme es idéntica.
#
# Pensado para correr 1 vez al día por cron (Railway):
#     python manage.py renovar_automaticas
#
# Para probar sin crear nada:
#     python manage.py renovar_automaticas --dry-run

import os
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import OuterRef, Subquery, DateField, Exists
from django.utils import timezone

from polizas.models import Poliza
from pagos.models import Cuota
from polizas.handlers.renovacion import handle_renovar_poliza
from polizas.domain.robo import ensure_cupones_robo_for_poliza
from notificaciones.utils.mensajeria import enviar_whatsapp

logger = logging.getLogger(__name__)

# Renovar las que vencen dentro de estos días (anticipación: hasta hoy + 3).
DIAS_ANTICIPO = 3
# Y también las que vencieron hace hasta estos días (tolerancia: hasta hoy - 3).
DIAS_GRACIA = 3

# Color verde del header del email de aviso (en el sistema = OK / hecho).
VERDE = "#047857"

# Destinatarios del aviso de renovaciones.
# Email:    override con env EMAIL_AVISO_RENOVACIONES (separados por coma).
_EMAILS_DEFAULT = "francodavid_dev@outlook.com"
EMAILS_AVISO = [e.strip() for e in os.environ.get("EMAIL_AVISO_RENOVACIONES", _EMAILS_DEFAULT).split(",") if e.strip()]
# WhatsApp: override con env WHATSAPP_AVISO_RENOVACIONES (separados por coma).
_WHATSAPP_DEFAULT = "1164235336"
WHATSAPP_NUMEROS = [n.strip() for n in os.environ.get("WHATSAPP_AVISO_RENOVACIONES", _WHATSAPP_DEFAULT).split(",") if n.strip()]
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


def _fmt_fecha(d):
    try:
        return d.strftime("%d/%m/%Y")
    except Exception:
        return "—"


def _cuerpo_renovaciones_html(renovadas, hoy):
    """Email prolijo: header + mensaje + tabla (Cliente/Patente/Marca/Modelo/Nueva vigencia)."""
    filas = ""
    for r in renovadas:
        filas += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:13px">{r['nombre_apellido']}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-family:monospace;font-size:13px;font-weight:600">{r['patente']}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:13px">{r['marca']}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:13px">{r['modelo']}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:13px">{r['vigencia']}</td>
        </tr>"""

    n = len(renovadas)
    plural = "s" if n != 1 else ""
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f9fafb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f9fafb;padding:40px 20px">
    <tr><td>
      <table width="620" cellpadding="0" cellspacing="0" align="center"
             style="background:#ffffff;border-radius:8px;border:1px solid #e5e7eb;overflow:hidden">
        <tr>
          <td style="background:{VERDE};padding:24px 32px">
            <p style="margin:0;color:#ffffff;font-size:18px;font-weight:500">Pólizas renovadas</p>
            <p style="margin:4px 0 0;color:#bbf7d0;font-size:13px">{settings.EMAIL_REMITENTE_NOMBRE} · {_fmt_fecha(hoy)}</p>
          </td>
        </tr>
        <tr>
          <td style="padding:32px">
            <p style="margin:0 0 20px;font-size:14px;color:#4b5563;line-height:1.6">
              Se renovaron automáticamente <strong>{n} póliza{plural}</strong>. El detalle es el siguiente:
            </p>
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="border:1px solid #e5e7eb;border-radius:6px;overflow:hidden;border-collapse:collapse">
              <thead>
                <tr style="background:#f3f4f6">
                  <th style="padding:10px 12px;text-align:left;font-size:11px;font-weight:600;color:#6b7280">Cliente</th>
                  <th style="padding:10px 12px;text-align:left;font-size:11px;font-weight:600;color:#6b7280">Patente</th>
                  <th style="padding:10px 12px;text-align:left;font-size:11px;font-weight:600;color:#6b7280">Marca</th>
                  <th style="padding:10px 12px;text-align:left;font-size:11px;font-weight:600;color:#6b7280">Modelo</th>
                  <th style="padding:10px 12px;text-align:left;font-size:11px;font-weight:600;color:#6b7280">Nueva vigencia</th>
                </tr>
              </thead>
              <tbody>{filas}</tbody>
            </table>
          </td>
        </tr>
        <tr>
          <td style="background:#f9fafb;padding:20px 32px;border-top:1px solid #e5e7eb">
            <p style="margin:0;font-size:12px;color:#9ca3af">{settings.EMAIL_REMITENTE_NOMBRE} · Generado el {_fmt_fecha(hoy)}</p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def _mensaje_whatsapp_renovaciones(renovadas, hoy):
    """Texto corto para WhatsApp con las pólizas renovadas."""
    n = len(renovadas)
    plural = "s" if n != 1 else ""
    partes = [
        f"♻️ *Pólizas renovadas* — {_fmt_fecha(hoy)}",
        f"Se renovaron automáticamente {n} póliza{plural}:",
        "",
    ]
    for r in renovadas:
        partes.append(f"   • {r['nombre_apellido']} ({r['patente']})")
    return "\n".join(partes)


def _enviar_aviso_renovaciones(renovadas, hoy):
    """Manda el aviso (email + WhatsApp a los destinatarios de control)."""
    if not renovadas:
        return
    n = len(renovadas)

    # ── Email ──
    if EMAILS_AVISO:
        asunto = f"♻️ Pólizas renovadas — {_fmt_fecha(hoy)} ({n})"
        cuerpo = _cuerpo_renovaciones_html(renovadas, hoy)
        try:
            msg = EmailMessage(
                subject=asunto, body=cuerpo,
                from_email=settings.DEFAULT_FROM_EMAIL, to=EMAILS_AVISO,
            )
            msg.content_subtype = "html"
            msg.send(fail_silently=False)
            logger.info(f"[renovar_automaticas] Email enviado a {EMAILS_AVISO} ({n} renovadas)")
        except Exception as e:
            logger.error(f"[renovar_automaticas] Error al enviar email: {e}")

    # ── WhatsApp ──
    msg_wa = _mensaje_whatsapp_renovaciones(renovadas, hoy)
    ofi_wa = _oficina_con_whatsapp()
    for numero in WHATSAPP_NUMEROS:
        try:
            ok, info = enviar_whatsapp(numero, msg_wa, oficina=ofi_wa)
            if not ok:
                logger.error(f"[renovar_automaticas] WhatsApp a {numero} no se envió: {info}")
        except Exception as e:
            logger.error(f"[renovar_automaticas] WhatsApp a {numero} excepción: {e}")


class _FakeRequest:
    """
    Request mínimo para poder reusar el handler de renovación sin pasar por HTTP.
    El handler lee `request.data`, usa `request.user` para el historial y
    `request.build_absolute_uri` al serializar la respuesta.
    """

    def __init__(self, data=None, user=None):
        self.data = data or {}
        self.user = user
        self.query_params = {}
        self.method = "POST"

    def build_absolute_uri(self, location=None):
        return location or ""


class Command(BaseCommand):
    help = (
        "Renueva automáticamente las pólizas 100% al día que finalizaron "
        "o vencen en los próximos 3 días."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="No crea nada. Solo muestra qué pólizas se renovarían.",
        )
        parser.add_argument(
            "--test-email",
            action="store_true",
            help="Manda el aviso con datos de ejemplo (no renueva nada). Para probar el formato.",
        )

    def handle(self, *args, **options):
        dry = bool(options.get("dry_run"))
        hoy = timezone.localdate()

        # Modo prueba: manda el aviso con datos de ejemplo y termina (no renueva nada).
        if options.get("test_email"):
            ejemplo = [
                {"nombre_apellido": "Juan Pérez", "patente": "ABC123",
                 "marca": "Toyota", "modelo": "Corolla",
                 "vigencia": _fmt_fecha(hoy + timedelta(days=1))},
                {"nombre_apellido": "María López", "patente": "DEF456",
                 "marca": "Volkswagen", "modelo": "Gol Trend",
                 "vigencia": _fmt_fecha(hoy + timedelta(days=1))},
            ]
            _enviar_aviso_renovaciones(ejemplo, hoy)
            self.stdout.write(self.style.SUCCESS(f"✓ Aviso de prueba enviado a {EMAILS_AVISO} + WhatsApp"))
            return

        # 1) Refrescar estados: marca como 'finalizada' las que terminaron su ciclo.
        #    (Resuelve el problema del timing: no dependemos de que alguien abra una pantalla.)
        try:
            from polizas.views.poliza import auto_marcar_vencidas
            auto_marcar_vencidas()
        except Exception as e:
            logger.warning(f"[renovar_automaticas] No se pudo refrescar estados: {e}")

        # 2) Anotaciones para filtrar.
        # Última cuota (la de fecha de vencimiento más alta) → el "fin de vida" de la póliza.
        ult_vto_sq = Subquery(
            Cuota.objects.filter(poliza_id=OuterRef("pk"))
            .exclude(fecha_vencimiento__isnull=True)
            .order_by("-fecha_vencimiento", "-cuota_nro", "-id")
            .values("fecha_vencimiento")[:1],
            output_field=DateField(),
        )
        # ¿Tiene alguna cuota impaga? (cualquiera, vencida o futura)
        impaga_sq = Cuota.objects.filter(poliza_id=OuterRef("pk"), pagado=False)
        # ¿Ya tiene una póliza hija (renovación previa)?
        hija_sq = Poliza.objects.filter(poliza_origen=OuterRef("pk"))

        desde = hoy - timedelta(days=DIAS_GRACIA)
        hasta = hoy + timedelta(days=DIAS_ANTICIPO)

        qs = (
            Poliza.objects.all()
            .annotate(
                ult_vto=ult_vto_sq,
                tiene_impaga=Exists(impaga_sq),
                tiene_hija=Exists(hija_sq),
            )
            .filter(
                ult_vto__isnull=False,
                ult_vto__gte=desde,
                ult_vto__lte=hasta,
                tiene_impaga=False,   # 100% al día
                tiene_hija=False,     # sin renovación previa
            )
            .exclude(estado__in=["cancelada", "en_verificacion"])
        )

        # 2b) Excluir las que tienen una baja en curso (si la app bajas existe).
        try:
            from bajas.models import BajaPoliza
            baja_sq = BajaPoliza.objects.filter(
                poliza=OuterRef("pk"),
                estado__in=[
                    BajaPoliza.Estado.PENDIENTE_ENVIO,
                    BajaPoliza.Estado.ENVIADA,
                    BajaPoliza.Estado.REALIZADA,
                ],
            )
            qs = qs.annotate(tiene_baja=Exists(baja_sq)).filter(tiene_baja=False)
        except Exception as e:
            logger.warning(f"[renovar_automaticas] No se pudo aplicar filtro de bajas: {e}")

        # 2c) Excluir las marcadas como "no renueva" (solo si el campo existe en el modelo).
        campos = {f.name for f in Poliza._meta.get_fields()}
        if "renovacion_descartada" in campos:
            qs = qs.exclude(renovacion_descartada=True)

        total = qs.count()
        self.stdout.write(f"[renovar_automaticas] Candidatas: {total} (ventana {desde} → {hasta})")

        renovadas = 0
        errores = 0
        renovadas_info = []

        for pol in qs.iterator():
            etiqueta = f"#{pol.id} {pol.patente or 's/patente'} (últ. vto {pol.ult_vto})"

            if dry:
                self.stdout.write(f"  [DRY] Renovaría {etiqueta}")
                renovadas += 1
                continue

            try:
                with transaction.atomic():
                    # Renovación rápida: sin fecha (usa el empalme automático) y
                    # conservando el día de vencimiento histórico.
                    req = _FakeRequest(data={"mantener_dia_vencimiento": True})
                    resp = handle_renovar_poliza(req, pol)

                    if getattr(resp, "status_code", None) not in (200, 201):
                        errores += 1
                        logger.error(f"[renovar_automaticas] {etiqueta}: handler devolvió {getattr(resp, 'status_code', '?')}")
                        continue

                    nueva_id = (getattr(resp, "data", None) or {}).get("id")
                    if nueva_id:
                        nueva = Poliza.objects.get(id=nueva_id)
                        nueva.es_renovacion = True
                        nueva.poliza_origen = pol
                        nueva.save(update_fields=["es_renovacion", "poliza_origen"])
                        try:
                            ensure_cupones_robo_for_poliza(nueva)
                        except Exception:
                            pass

                    # Renovación ANTICIPADA: si la vieja todavía no venció, el handler
                    # la marcó 'finalizada' de más. La devolvemos a 'activa' para que
                    # siga vigente hasta su vencimiento real; el recálculo la finaliza sola.
                    if pol.ult_vto and pol.ult_vto > hoy:
                        pol.refresh_from_db(fields=["estado"])
                        if pol.estado == "finalizada":
                            pol.estado = "activa"
                            pol.save(update_fields=["estado"])

                    cli = getattr(pol, "cliente", None)
                    nom = (getattr(cli, "nombre", "") or "").strip()
                    ape = (getattr(cli, "apellido", "") or "").strip()
                    vig = None
                    if nueva_id:
                        vig = getattr(nueva, "inicio_vigencia", None) or getattr(nueva, "fecha_emision", None)
                    renovadas_info.append({
                        "nombre_apellido": f"{nom} {ape}".strip() or "—",
                        "patente": pol.patente or "—",
                        "marca": (getattr(pol, "marca", "") or "").strip() or "—",
                        "modelo": (getattr(pol, "modelo", "") or "").strip() or "—",
                        "vigencia": _fmt_fecha(vig) if vig else "—",
                    })

                    renovadas += 1
                    self.stdout.write(self.style.SUCCESS(f"  ✓ Renovada {etiqueta} → hija #{nueva_id}"))

            except Exception as e:
                errores += 1
                logger.error(f"[renovar_automaticas] Error renovando {etiqueta}: {e}")

        # Aviso (email + WhatsApp) al dueño (solo en modo real y si hubo renovaciones).
        if not dry and renovadas_info:
            _enviar_aviso_renovaciones(renovadas_info, hoy)
            self.stdout.write(self.style.SUCCESS(f"✓ Aviso enviado a {EMAILS_AVISO} + WhatsApp"))

        resumen = f"[renovar_automaticas] Renovadas={renovadas} Errores={errores} dry={dry}"
        self.stdout.write(self.style.SUCCESS(resumen))
        logger.info(resumen)