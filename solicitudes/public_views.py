from django.http import HttpResponse
from django.utils import timezone
from django.shortcuts import get_object_or_404
from .models import SolicitudSeguro, EstadoSolicitud

HTML = """
<!doctype html>
<meta charset="utf-8">
<title>Verificación de Solicitud</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,...ns-serif;background:#0b0b0c;color:#f9fafb;margin:0;padding:40px}
.card{max-width:720px;margin:0 auto;background:rgba(255,255,255,.06);backdrop-filter:saturate(180%) blur(10px);
border:1px solid rgba(255,255,255,.1);border-radius:16px;padding:24px}
.badge{display:inline-block;padding:6px 10px;border-radius:8px;border:1px solid rgba(255,255,255,.15);font-size:12px}
.ok{background:rgba(16,185,129,.18);color:#d1fae5}
.warn{background:rgba(245,158,11,.18);color:#fde68a}
.err{background:rgba(239,68,68,.18);color:#fecaca}
.row{margin:.25rem 0;color:#e5e7eb}
.h1{font-weight:700;font-size:20px;margin-bottom:.3rem}
.small{color:#9ca3af;font-size:12px}
</style>
<div class="card">
  <div class="h1">Constancia de Solicitud de Seguro (12 h)</div>
  <div class="row"><b>Código:</b> {codigo}</div>
  <div class="row"><b>Cliente:</b> {cliente} — DNI {dni}</div>
  <div class="row"><b>Vehículo:</b> {vehiculo}</div>
  <div class="row"><b>Patente:</b> {patente}</div>
  <div class="row"><b>Válido desde:</b> {inicio}</div>
  <div class="row"><b>Válido hasta:</b> {fin}</div>
  <div class="row"><span class="badge {cls}">{estado}</span></div>
  <div class="small">Esta constancia no reemplaza la póliza ni garantiza cobertura hasta su emisión por la compañía.</div>
</div>
"""

def verificar(request, id: int):
    s = get_object_or_404(SolicitudSeguro, id=id)
    # Expiración "just-in-time"
    if s.estado == EstadoSolicitud.VIGENTE_24H and s.fin and s.fin <= timezone.now():
        s.estado = EstadoSolicitud.VENCIDA
        s.save(update_fields=["estado"])
    estado_legible = dict(EstadoSolicitud.choices).get(s.estado, s.estado)
    cls = "err"
    if s.estado == EstadoSolicitud.VIGENTE_24H:
        cls = "ok"
    elif s.estado in (EstadoSolicitud.BORRADOR, EstadoSolicitud.EN_REVISION):
        cls = "warn"
    elif s.estado in (EstadoSolicitud.CONVERTIDA,):
        cls = "ok"

    tz = timezone.get_current_timezone()
    fmt = "%d/%m/%Y %H:%M hs"
    inicio = s.inicio.astimezone(tz).strftime(fmt) if s.inicio else "-"
    fin = s.fin.astimezone(tz).strftime(fmt) if s.fin else "-"

    html = HTML.format(
        codigo=s.codigo or f"ID {s.id}",
        cliente=s.cliente_nombre or "-",
        dni=s.cliente_dni or "-",
        vehiculo=f"{s.vehiculo_marca or ''} {s.vehiculo_modelo or ''} {s.vehiculo_anio or ''}".strip(),
        patente=s.vehiculo_patente or "-",
        inicio=inicio,
        fin=fin,
        estado=estado_legible,
        cls=cls,
    )
    return HttpResponse(html)
