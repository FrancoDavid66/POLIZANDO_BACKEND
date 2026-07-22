# bajas/services.py
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import Count, Min, Q
from django.utils import timezone

from polizas.models import Poliza
from .models import BajaPoliza, CorreoCompaniaBaja

logger = logging.getLogger(__name__)


# ─── DTOs ────────────────────────────────────────────────────────────────────

@dataclass
class PolizaMoraInfo:
    id: int
    numero_poliza: str
    patente: str
    asegurado: str
    mora_dias: int
    impagas_count: int


@dataclass
class DigestCompania:
    compania: str
    email_destino: str
    polizas: list = field(default_factory=list)
    estado: str = "PENDIENTE_ENVIO"
    email_enviado_en: Optional[str] = None


@dataclass
class DigestDia:
    fecha: date
    total_polizas: int
    grupos: list = field(default_factory=list)


# ─── Detección de mora ────────────────────────────────────────────────────────

def detectar_polizas_en_mora(
    oficina_id: Optional[int] = None,
) -> list:
    """
    Devuelve pólizas con mora >= dias_gracia configurados por compañía.
    Solo incluye compañías con correo configurado en CorreoCompaniaBaja.
    Excluye pólizas con BajaPoliza en estado REALIZADA.
    """
    hoy = timezone.localdate()

    correos_map = {
        c.compania.strip().lower(): c
        for c in CorreoCompaniaBaja.objects.all()
    }

    if not correos_map:
        logger.warning("[bajas.services] No hay correos configurados en CorreoCompaniaBaja.")
        return []

    qs = (
        Poliza.objects
        .exclude(estado__iexact="cancelada")
        .exclude(estado__iexact="finalizada")
        .exclude(baja_operativa__estado=BajaPoliza.Estado.REALIZADA)
        .annotate(
            impagas_count=Count(
                "cuotas",
                filter=Q(cuotas__pagado=False, cuotas__fecha_vencimiento__lt=hoy),
                distinct=True,
            ),
            min_vto_impaga=Min(
                "cuotas__fecha_vencimiento",
                filter=Q(cuotas__pagado=False, cuotas__fecha_vencimiento__lt=hoy),
            ),
        )
        .filter(min_vto_impaga__isnull=False)
        .select_related("cliente", "baja_operativa")
    )

    if oficina_id:
        qs = qs.filter(oficina_id=oficina_id)

    resultados = []
    for poliza in qs:
        mora_dias    = (hoy - poliza.min_vto_impaga).days
        compania_key = (poliza.compania or "").strip().lower()
        correo_obj   = correos_map.get(compania_key)

        if not correo_obj:
            continue
        if mora_dias < correo_obj.dias_gracia:
            continue

        cli = getattr(poliza, "cliente", None)
        asegurado = (
            f"{getattr(cli, 'apellido', '')} {getattr(cli, 'nombre', '')}".strip()
            if cli else "—"
        )

        baja_op = getattr(poliza, "baja_operativa", None)

        resultados.append({
            "id":            poliza.id,
            "numero_poliza": poliza.numero_poliza or "S/N",
            "patente":       poliza.patente or "—",
            "asegurado":     asegurado,
            "compania":      poliza.compania or "",
            "email_destino": correo_obj.email,
            "dias_gracia":   correo_obj.dias_gracia,
            "mora_dias":     mora_dias,
            "impagas_count": poliza.impagas_count,
            "baja_estado":   getattr(baja_op, "estado", None),
        })

    return resultados


# ─── Creación de BajaPoliza ───────────────────────────────────────────────────

@transaction.atomic
def crear_bajas_pendientes(
    oficina_id: Optional[int] = None,
) -> int:
    """
    Crea registros BajaPoliza en PENDIENTE_ENVIO para las pólizas en mora
    que aún no tienen uno. Retorna la cantidad de registros nuevos creados.
    """
    polizas_mora = detectar_polizas_en_mora(oficina_id)
    creadas = 0

    for p in polizas_mora:
        if p["baja_estado"] is None:
            BajaPoliza.objects.get_or_create(
                poliza_id=p["id"],
                defaults={
                    "estado":        BajaPoliza.Estado.PENDIENTE_ENVIO,
                    "email_destino": p["email_destino"],
                },
            )
            creadas += 1

    logger.info(f"[bajas.services] crear_bajas_pendientes: {creadas} nuevas BajaPoliza creadas.")
    return creadas


# ─── Digest del día ───────────────────────────────────────────────────────────

def construir_digest(
    oficina_id: Optional[int] = None,
) -> DigestDia:
    """
    Construye el digest del día agrupado por compañía.
    Primero asegura que existan los registros BajaPoliza.
    """
    hoy = timezone.localdate()
    crear_bajas_pendientes(oficina_id)

    polizas = detectar_polizas_en_mora(oficina_id)

    grupos_map: dict = {}
    for p in polizas:
        cia = p["compania"]
        if cia not in grupos_map:
            grupos_map[cia] = DigestCompania(
                compania=cia,
                email_destino=p["email_destino"],
            )
        grupos_map[cia].polizas.append(
            PolizaMoraInfo(
                id=p["id"],
                numero_poliza=p["numero_poliza"],
                patente=p["patente"],
                asegurado=p["asegurado"],
                mora_dias=p["mora_dias"],
                impagas_count=p["impagas_count"],
            )
        )

    for grupo in grupos_map.values():
        ids   = [pol.id for pol in grupo.polizas]
        bajas = BajaPoliza.objects.filter(poliza_id__in=ids)
        estados = set(b.estado for b in bajas)

        if estados == {BajaPoliza.Estado.ENVIADA}:
            grupo.estado = "ENVIADA"
        elif BajaPoliza.Estado.ENVIADA in estados:
            grupo.estado = "PARCIAL"
        else:
            grupo.estado = "PENDIENTE_ENVIO"

        ultima = bajas.filter(enviada_en__isnull=False).order_by("-enviada_en").first()
        if ultima:
            grupo.email_enviado_en = ultima.enviada_en.strftime("%H:%M hs")

    grupos = sorted(grupos_map.values(), key=lambda g: g.compania)

    return DigestDia(
        fecha=hoy,
        total_polizas=sum(len(g.polizas) for g in grupos),
        grupos=grupos,
    )


# ─── Construcción del email ───────────────────────────────────────────────────

def _construir_asunto(compania: str, cantidad: int, fecha: date) -> str:
    plural = "s" if cantidad != 1 else ""
    return (
        f"Solicitud de baja — {cantidad} póliza{plural} "
        f"por falta de pago · {fecha.strftime('%d/%m/%Y')}"
    )


def _construir_cuerpo_html(
    compania: str,
    polizas: list,
    fecha: date,
    remitente_nombre: str = "Polizando",
) -> str:
    filas_html = ""
    for p in polizas:
        color = "#dc2626" if p.mora_dias > 30 else "#d97706" if p.mora_dias > 10 else "#6b7280"
        filas_html += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-family:monospace;font-size:13px">{p.numero_poliza}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:13px">{p.asegurado}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-family:monospace;font-size:13px;font-weight:600">{p.patente}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;color:{color};font-weight:600">{p.mora_dias} días</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;color:#6b7280">{p.impagas_count}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f9fafb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f9fafb;padding:40px 20px">
    <tr><td>
      <table width="600" cellpadding="0" cellspacing="0" align="center"
             style="background:#ffffff;border-radius:8px;border:1px solid #e5e7eb;overflow:hidden">

        <tr>
          <td style="background:#18181b;padding:24px 32px">
            <p style="margin:0;color:#f4f4f5;font-size:18px;font-weight:500">{remitente_nombre}</p>
            <p style="margin:4px 0 0;color:#71717a;font-size:13px">Sistema de gestión de seguros</p>
          </td>
        </tr>

        <tr>
          <td style="padding:32px">
            <p style="margin:0 0 8px;font-size:14px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;font-weight:500">
              {fecha.strftime('%d de %B de %Y')}
            </p>
            <h1 style="margin:0 0 20px;font-size:20px;font-weight:500;color:#111827">
              Solicitud de baja por falta de pago
            </h1>
            <p style="margin:0 0 24px;font-size:14px;color:#4b5563;line-height:1.6">
              Estimado equipo de <strong>{compania}</strong>,<br><br>
              Por medio de la presente solicitamos la baja de las siguientes
              pólizas por incumplimiento en el pago de cuotas:
            </p>

            <table width="100%" cellpadding="0" cellspacing="0"
                   style="border:1px solid #e5e7eb;border-radius:6px;overflow:hidden;border-collapse:collapse">
              <thead>
                <tr style="background:#f3f4f6">
                  <th style="padding:10px 12px;text-align:left;font-size:11px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:.05em">N° Póliza</th>
                  <th style="padding:10px 12px;text-align:left;font-size:11px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:.05em">Asegurado</th>
                  <th style="padding:10px 12px;text-align:left;font-size:11px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:.05em">Patente</th>
                  <th style="padding:10px 12px;text-align:left;font-size:11px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:.05em">Mora</th>
                  <th style="padding:10px 12px;text-align:left;font-size:11px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:.05em">Cuotas</th>
                </tr>
              </thead>
              <tbody>{filas_html}</tbody>
            </table>

            <p style="margin:24px 0 0;font-size:14px;color:#4b5563;line-height:1.6">
              Quedamos a disposición para cualquier consulta o documentación adicional.
            </p>
          </td>
        </tr>

        <tr>
          <td style="background:#f9fafb;padding:20px 32px;border-top:1px solid #e5e7eb">
            <p style="margin:0;font-size:12px;color:#9ca3af">
              {remitente_nombre} · Generado el {fecha.strftime('%d/%m/%Y')}
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


# ─── Envío ────────────────────────────────────────────────────────────────────

def enviar_digest_compania(
    compania: str,
    oficina_id: Optional[int] = None,
) -> dict:
    """
    Construye y envía el email de baja para una compañía.
    Guarda el cuerpo del email en BajaPoliza para auditoría.
    Marca las pólizas como ENVIADA si el envío fue exitoso.
    """
    hoy = timezone.localdate()

    try:
        correo_obj = CorreoCompaniaBaja.objects.get(compania__iexact=compania)
    except CorreoCompaniaBaja.DoesNotExist:
        return {
            "ok":       False,
            "compania": compania,
            "error":    f"No hay correo configurado para '{compania}'.",
        }

    polizas_raw = detectar_polizas_en_mora(oficina_id=oficina_id)
    polizas_cia = [
        p for p in polizas_raw
        if p["compania"].strip().lower() == compania.strip().lower()
    ]

    if not polizas_cia:
        return {
            "ok":       False,
            "compania": compania,
            "error":    "Sin pólizas pendientes para esta compañía.",
        }

    polizas_info = [
        PolizaMoraInfo(
            id=p["id"],
            numero_poliza=p["numero_poliza"],
            patente=p["patente"],
            asegurado=p["asegurado"],
            mora_dias=p["mora_dias"],
            impagas_count=p["impagas_count"],
        )
        for p in polizas_cia
    ]

    asunto = _construir_asunto(compania, len(polizas_info), hoy)
    cuerpo = _construir_cuerpo_html(
        compania=compania,
        polizas=polizas_info,
        fecha=hoy,
        remitente_nombre=getattr(settings, "EMAIL_REMITENTE_NOMBRE", "Polizando"),
    )

    email_ok    = False
    email_error = ""
    try:
        destinatarios = (
            correo_obj.emails_lista()
            if hasattr(correo_obj, "emails_lista")
            else [correo_obj.email]
        ) or [correo_obj.email]
        msg = EmailMessage(
            subject=asunto,
            body=cuerpo,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=destinatarios,
        )
        msg.content_subtype = "html"
        msg.send(fail_silently=False)
        email_ok = True
        logger.info(
            f"[bajas.services] Email enviado a {correo_obj.email} "
            f"({len(polizas_info)} pólizas de {compania})"
        )
    except Exception as exc:
        email_error = str(exc)
        logger.error(f"[bajas.services] Error al enviar a {correo_obj.email}: {exc}")

    with transaction.atomic():
        ids   = [p["id"] for p in polizas_cia]
        bajas = list(BajaPoliza.objects.filter(poliza_id__in=ids))
        now   = timezone.now()

        for baja in bajas:
            baja.email_asunto = asunto
            baja.email_cuerpo = cuerpo
            baja.email_ok     = email_ok
            baja.email_error  = email_error
            if email_ok:
                baja.estado     = BajaPoliza.Estado.ENVIADA
                baja.enviada_en = now

        BajaPoliza.objects.bulk_update(
            bajas,
            ["email_asunto", "email_cuerpo", "email_ok",
             "email_error", "estado", "enviada_en"],
        )

    return {
        "ok":            email_ok,
        "compania":      compania,
        "polizas_count": len(polizas_info),
        "email_destino": correo_obj.email,
        "error":         email_error or None,
    }


def enviar_todas_del_dia(
    oficina_id: Optional[int] = None,
) -> list:
    """
    Envía el digest a todas las compañías con bajas PENDIENTE_ENVIO.
    Retorna una lista de resultados por compañía.
    """
    crear_bajas_pendientes(oficina_id)

    polizas = detectar_polizas_en_mora(oficina_id)
    companias_pendientes = {
        p["compania"]
        for p in polizas
        if p["baja_estado"] != BajaPoliza.Estado.ENVIADA
    }

    return [
        enviar_digest_compania(cia, oficina_id)
        for cia in sorted(companias_pendientes)
    ]