# pagos/utils/factura.py

from io import BytesIO
from datetime import date
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4


def _fmt_money(value):
    try:
        n = float(value or 0)
    except Exception:
        n = 0.0
    # Formato AR: separador miles ".", decimal ","
    s = f"{n:,.2f}"
    return "AR$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def _safe(val, default="—"):
    return str(val) if val not in (None, "", 0) else default


def generar_factura_pdf(cuota):
    """
    Genera un PDF (BytesIO) con el recibo de pago de la cuota.
    NOTA: Esta función devuelve un buffer listo para usar con FileResponse
    desde la vista (no devuelve el FileResponse directamente).
    """
    poliza = cuota.poliza
    cliente = getattr(poliza, "cliente", None)

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Estilo
    color_primario = colors.HexColor("#8B1E3F")
    margen = 40
    y = height - 50

    # Encabezado
    p.setFont("Helvetica-Bold", 18)
    p.setFillColor(color_primario)
    p.drawString(margen, y, "FACTURA / RECIBO DE PAGO DE CUOTA")
    p.setFillColor(colors.black)
    p.setFont("Helvetica", 10)
    p.drawRightString(width - margen, height - 40, f"Nº: {cuota.id:06d}")
    y -= 25

    # Bloque Titular
    p.setFillColor(color_primario)
    p.rect(margen, y - 85, width / 2 - 2 * margen, 80, fill=1, stroke=0)
    p.setFillColor(colors.white)
    p.setFont("Helvetica-Bold", 10)
    p.drawString(margen + 10, y - 20, "Titular")
    p.setFont("Helvetica", 9)
    nombre = f"{getattr(cliente, 'nombre', '')} {getattr(cliente, 'apellido', '')}".strip()
    p.drawString(margen + 10, y - 35, f"Nombre: {_safe(nombre)}")
    p.drawString(margen + 10, y - 50, f"Teléfono: {_safe(getattr(cliente, 'telefono', ''))}")
    p.drawString(margen + 10, y - 65, f"DNI / CUIT: {_safe(getattr(cliente, 'dni_cuit_cuil', ''))}")
    p.drawString(margen + 10, y - 80, f"Dirección: {_safe(getattr(cliente, 'direccion', ''))}")
    y -= 100

    # Bloque Póliza
    p.setFillColor(color_primario)
    p.rect(width / 2 + margen / 2, y + 15, width / 2 - 1.5 * margen, 80, fill=1, stroke=0)
    p.setFillColor(colors.white)
    p.setFont("Helvetica-Bold", 10)
    p.drawString(width / 2 + margen / 2 + 10, y + 75, "Datos de Póliza")
    p.setFont("Helvetica", 9)
    p.drawString(width / 2 + margen / 2 + 10, y + 60, f"Póliza N°: {_safe(getattr(poliza, 'numero_poliza', ''))}")
    p.drawString(width / 2 + margen / 2 + 10, y + 45, f"Patente: {_safe(getattr(poliza, 'patente', ''))}")
    p.drawString(width / 2 + margen / 2 + 10, y + 30, f"Compañía: {_safe(getattr(poliza, 'compania', ''))}")
    p.drawString(width / 2 + margen / 2 + 10, y + 15, f"Cobertura: {_safe(getattr(poliza, 'cobertura', ''))}")
    y -= 25

    # Detalle del pago
    p.setFont("Helvetica-Bold", 11)
    p.setFillColor(color_primario)
    p.drawString(margen, y, "Detalle del Pago")
    p.setFillColor(colors.black)
    y -= 20
    p.setFont("Helvetica", 10)

    p.drawString(margen, y, f"Cuota N°: {_safe(getattr(cuota, 'cuota_nro', ''))}")
    y -= 15
    p.drawString(margen, y, f"Monto: {_fmt_money(getattr(cuota, 'monto', 0))}")
    y -= 15
    venc = getattr(cuota, "fecha_vencimiento", None)
    p.drawString(margen, y, f"Vencimiento: {venc.strftime('%d/%m/%Y') if venc else '—'}")
    y -= 15
    fpago = getattr(cuota, "fecha_pago", None)
    p.drawString(margen, y, f"Fecha de pago: {fpago.strftime('%d/%m/%Y') if fpago else date.today().strftime('%d/%m/%Y')}")
    y -= 15
    forma = getattr(cuota, "forma_pago", None)
    p.drawString(margen, y, f"Forma de pago: {_safe(forma)}")
    y -= 15
    p.drawString(margen, y, f"Estado: {'Pagada' if getattr(cuota, 'pagado', False) else 'Pendiente'}")
    y -= 30

    # Footer
    p.setFont("Helvetica-Oblique", 9)
    p.drawString(margen, y, "Gracias por confiar en nosotros.")
    p.setFont("Helvetica", 8)
    p.drawCentredString(width / 2, 50, "Este documento no constituye un recibo fiscal.")
    p.drawCentredString(width / 2, 35, "STARKE | Sistema de Gestión de Seguros")

    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer
