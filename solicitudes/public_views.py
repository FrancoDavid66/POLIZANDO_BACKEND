from django.http import HttpResponse
from django.utils import timezone
from django.shortcuts import get_object_or_404
from .models import SolicitudSeguro, EstadoSolicitud

# 🔧 Cambios sobre el original:
#  1) Bug de CSS: "Ubuntu,...ns-serif" -> "Ubuntu,sans-serif" (el "..." rompía
#     la cadena de fuentes; el navegador la ignoraba y caía directo al default).
#  2) Colores de marca Polizando en vez de la paleta genérica (verde/ámbar/rojo
#     sin relación con la marca) — misma idea que ya aplicamos al PNG del
#     comprobante, porque esta página también la ve el cliente.
HTML = """
<!doctype html>
<meta charset="utf-8">
<title>Verificación de Solicitud — Polizando</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Baloo+2:wght@600;700&family=Nunito:wght@400;600&display=swap" rel="stylesheet">
<style>
body{{font-family:'Nunito',system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,sans-serif;background:#3D322A;color:#F4EFE6;margin:0;padding:40px}}
.card{{max-width:720px;margin:0 auto;background:rgba(244,239,230,.06);backdrop-filter:saturate(180%) blur(10px);
border:1px solid rgba(244,239,230,.12);border-radius:16px;padding:24px}}
.brand{{font-family:'Baloo 2',system-ui,sans-serif;font-weight:700;font-size:15px;color:#BCD7C9;letter-spacing:.02em;margin-bottom:10px}}
.badge{{display:inline-block;padding:6px 10px;border-radius:8px;border:1px solid rgba(244,239,230,.15);font-size:12px}}
.ok{{background:rgba(31,122,76,.22);color:#BCD7C9}}
.warn{{background:rgba(226,98,44,.20);color:#F5C8B5}}
.err{{background:rgba(220,38,38,.20);color:#fecaca}}
.row{{margin:.25rem 0;color:#F4EFE6}}
.h1{{font-family:'Baloo 2',system-ui,sans-serif;font-weight:700;font-size:20px;margin-bottom:.3rem;color:#F4EFE6}}
.small{{color:#BCB2A6;font-size:12px}}
</style>
<div class="card">
  <div class="brand">POLIZANDO</div>
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