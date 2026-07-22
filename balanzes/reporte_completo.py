# balanzes/reporte_completo.py
# 🚀 UN SOLO Excel con TODO: Resumen (con gráficos) + Ingresos + Egresos.
# Rango de fechas a elección. La hoja Ingresos trae TODAS las columnas del pago
# (incluida la auditoría de transferencias). Archivo aparte para no tocar views.py.
# Se enchufa con una línea en balanzes/urls.py.

import io
import re
import calendar
import traceback
from datetime import datetime, date

import xlsxwriter

from django.http import HttpResponse
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Ingreso, Egreso
# Reutilizamos el helper de seguridad que YA vive en views.py
from .views import _get_todas_las_llaves_oficina


# ══════════════════════════════════════════════════════════════════
# Helpers de armado
# ══════════════════════════════════════════════════════════════════
def _num(v):
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def _safe_sheet_name(base):
    return "".join(ch for ch in str(base) if ch not in "[]:*?/\\")[:28] or "Hoja"


def _safe_table_name(base):
    name = re.sub(r"[^A-Za-z0-9]", "", str(base)) or "Tabla"
    if not name[0].isalpha():
        name = "T" + name
    return name[:30]


# Columnas de cada hoja: (clave, encabezado, ancho)
INGRESOS_COLS = [
    ("fecha", "Fecha", 12),
    ("hora", "Hora", 8),
    ("oficina", "Sucursal", 18),
    ("descripcion", "Descripción", 38),
    ("patente", "Patente", 12),
    ("categoria", "Categoría", 18),
    ("forma_pago", "Forma de pago", 15),
    ("pagado_por", "Pagado por", 22),
    ("billetera", "Cuenta destino", 22),
    ("cuit_remitente", "CUIT remitente", 16),
    ("nro_operacion", "N° operación", 16),
    ("verificada", "Verificada", 11),
    ("verificada_por", "Verificada por", 18),
    ("verificada_en", "Verificada en", 16),
    ("nota_verificacion", "Nota verif.", 20),
    ("observaciones", "Observaciones", 30),
    ("usuario", "Cargado por", 18),
    ("monto", "Monto", 14),
]

EGRESOS_COLS = [
    ("fecha", "Fecha", 12),
    ("hora", "Hora", 8),
    ("oficina", "Sucursal", 18),
    ("descripcion", "Descripción", 38),
    ("categoria", "Categoría", 18),
    ("forma_pago", "Forma de pago", 15),
    ("observaciones", "Observaciones", 30),
    ("usuario", "Cargado por", 18),
    ("monto", "Monto", 14),
]


def _agrupar(rows, key):
    acc = {}
    for r in rows:
        k = (r.get(key) or "—")
        d = acc.setdefault(k, {"monto": 0.0, "cant": 0})
        d["monto"] += _num(r.get("monto"))
        d["cant"] += 1
    return sorted(acc.items(), key=lambda kv: kv[1]["monto"], reverse=True)


def _top_con_otros(items, n=8):
    if len(items) <= n:
        return items
    top = items[:n]
    resto_m = sum(v["monto"] for _, v in items[n:])
    resto_c = sum(v["cant"] for _, v in items[n:])
    return top + [("Otros", {"monto": resto_m, "cant": resto_c})]


def _hoja_tabla(wb, nombre, cols, rows, f_money, f_header, f_cell):
    ws = wb.add_worksheet(_safe_sheet_name(nombre))
    keys = [c[0] for c in cols]
    n = len(cols)
    for i, (_, _, w) in enumerate(cols):
        ws.set_column(i, i, w)

    data = []
    for r in rows:
        fila = []
        for k in keys:
            v = r.get(k, "")
            if k == "monto":
                v = _num(v)
            fila.append("" if v is None else v)
        data.append(fila)

    if data:
        columns = []
        for i, (k, h, _) in enumerate(cols):
            col = {"header": h}
            if k == "monto":
                col["total_function"] = "sum"
                col["format"] = f_money
            elif i == 0:
                col["total_string"] = "TOTAL"
            columns.append(col)
        ws.add_table(0, 0, len(data) + 1, n - 1, {
            "name": _safe_table_name(nombre),
            "style": "Table Style Medium 2",
            "total_row": True,
            "columns": columns,
            "data": data,
        })
    else:
        for i, (_, h, _w) in enumerate(cols):
            ws.write(0, i, h, f_header)
        ws.write(1, 0, f"Sin {nombre.lower()} en el período", f_cell)

    ws.freeze_panes(1, 0)


def construir_reporte_completo(output, *, desde_txt, hasta_txt, generado_txt, ingresos, egresos):
    """
    ingresos / egresos: listas de dicts con las claves de INGRESOS_COLS / EGRESOS_COLS.
    Genera UN workbook con 3 hojas: Resumen (con gráficos) + Ingresos + Egresos.
    """
    wb = xlsxwriter.Workbook(output, {"in_memory": True})

    f_title = wb.add_format({"bold": True, "font_size": 16, "bg_color": "#0F172A", "font_color": "#FFFFFF", "align": "center", "valign": "vcenter"})
    f_sub = wb.add_format({"italic": True, "font_size": 10, "bg_color": "#0F172A", "font_color": "#94A3B8", "align": "center", "valign": "vcenter"})
    f_section = wb.add_format({"bold": True, "font_size": 12, "bg_color": "#1E293B", "font_color": "#FFFFFF", "align": "left", "valign": "vcenter"})
    f_header = wb.add_format({"bold": True, "bg_color": "#334155", "font_color": "#FFFFFF", "border": 1, "border_color": "#CBD5E1", "align": "center"})
    f_cell = wb.add_format({"border": 1, "border_color": "#E2E8F0"})
    f_cell_alt = wb.add_format({"border": 1, "border_color": "#E2E8F0", "bg_color": "#F1F5F9"})
    f_money = wb.add_format({"border": 1, "border_color": "#E2E8F0", "num_format": "$#,##0.00"})
    f_money_alt = wb.add_format({"border": 1, "border_color": "#E2E8F0", "num_format": "$#,##0.00", "bg_color": "#F1F5F9"})
    f_money_table = wb.add_format({"num_format": "$#,##0.00"})

    total_in = sum(_num(i["monto"]) for i in ingresos)
    total_eg = sum(_num(e["monto"]) for e in egresos)
    balance = total_in - total_eg

    pagos = _agrupar(ingresos, "forma_pago")
    categorias = _agrupar(egresos, "categoria")

    # por sucursal: ingresos y egresos juntos
    suc = {}
    for i in ingresos:
        k = i.get("oficina") or "Sin sucursal"
        suc.setdefault(k, {"ing": 0.0, "eg": 0.0})["ing"] += _num(i["monto"])
    for e in egresos:
        k = e.get("oficina") or "Sin sucursal"
        suc.setdefault(k, {"ing": 0.0, "eg": 0.0})["eg"] += _num(e["monto"])
    filas_suc = sorted(suc.items(), key=lambda kv: (kv[1]["ing"] - kv[1]["eg"]), reverse=True)

    # ── HOJA RESUMEN ──────────────────────────────────────────────
    ws = wb.add_worksheet("Resumen")
    ws.hide_gridlines(2)
    ws.set_column("A:A", 30)
    ws.set_column("B:B", 18)
    ws.set_column("C:C", 16)
    ws.set_column("D:D", 16)

    ws.merge_range("A1:D1", "REPORTE DE BALANCE — COMPLETO", f_title)
    ws.set_row(0, 26)
    ws.merge_range("A2:D2", f"Período: {desde_txt} a {hasta_txt}   ·   Generado: {generado_txt}", f_sub)

    chart_col = 5  # columna F
    chart_anchor = 2
    GAP = 18

    def write_table(r, title, headers, rows, value_cols=()):
        ws.merge_range(r, 0, r, len(headers) - 1, title, f_section)
        r += 1
        for c, h in enumerate(headers):
            ws.write(r, c, h, f_header)
        r += 1
        start = r
        for ri, row in enumerate(rows):
            alt = ri % 2 == 1
            for c, val in enumerate(row):
                if c in value_cols:
                    ws.write_number(r, c, _num(val), f_money_alt if alt else f_money)
                else:
                    ws.write(r, c, val if val is not None else "", f_cell_alt if alt else f_cell)
            r += 1
        return r, start, r - 1

    # Balance general + gráfico columnas
    r = 3
    bal_lbl = "Balance Positivo ▲" if balance >= 0 else "Balance Negativo ▼"
    r, bs, be = write_table(
        r, "BALANCE GENERAL",
        ["Concepto", "Monto", "Cantidad"],
        [
            ["Total Ingresos", total_in, len(ingresos)],
            ["Total Egresos", total_eg, len(egresos)],
            [bal_lbl, balance, ""],
        ],
        value_cols=(1,),
    )
    ch = wb.add_chart({"type": "column"})
    ch.add_series({
        "name": "Monto",
        "categories": ["Resumen", bs, 0, bs + 1, 0],
        "values": ["Resumen", bs, 1, bs + 1, 1],
        "points": [{"fill": {"color": "#10B981"}}, {"fill": {"color": "#EF4444"}}],
        "data_labels": {"value": True, "num_format": "$#,##0"},
    })
    ch.set_title({"name": "Ingresos vs Egresos"})
    ch.set_legend({"none": True})
    ws.insert_chart(chart_anchor, chart_col, ch, {"x_scale": 1.15, "y_scale": 1.0})
    chart_anchor += GAP

    # Ingresos por medio de pago + torta
    r += 1
    rows = [[fp, d["monto"], d["cant"]] for fp, d in pagos]
    r, ps, pe = write_table(r, "INGRESOS POR MEDIO DE PAGO", ["Medio de pago", "Monto", "Operaciones"], rows, value_cols=(1,))
    if rows:
        pie = wb.add_chart({"type": "pie"})
        pie.add_series({
            "name": "Medios de pago",
            "categories": ["Resumen", ps, 0, pe, 0],
            "values": ["Resumen", ps, 1, pe, 1],
            "data_labels": {"percentage": True},
        })
        pie.set_title({"name": "Distribución de ingresos"})
        pie.set_legend({"position": "right", "font": {"size": 8}})
        ws.insert_chart(chart_anchor, chart_col, pie, {"x_scale": 1.15, "y_scale": 1.0})
        chart_anchor += GAP

    # Balance por sucursal + barras
    r += 1
    rows = [[nom, d["ing"], d["eg"], d["ing"] - d["eg"]] for nom, d in filas_suc]
    r, ss, se = write_table(r, "BALANCE POR SUCURSAL", ["Sucursal", "Ingresos", "Egresos", "Balance"], rows, value_cols=(1, 2, 3))
    if rows:
        col = wb.add_chart({"type": "bar"})
        col.add_series({
            "name": "Balance",
            "categories": ["Resumen", ss, 0, se, 0],
            "values": ["Resumen", ss, 3, se, 3],
            "fill": {"color": "#0EA5E9"},
            "data_labels": {"value": True, "num_format": "$#,##0"},
        })
        col.set_title({"name": "Balance por sucursal"})
        col.set_legend({"none": True})
        ws.insert_chart(chart_anchor, chart_col, col, {"x_scale": 1.15, "y_scale": 1.0})
        chart_anchor += GAP

    # Top gastos por categoría + torta
    r += 1
    rows = [[cat, d["monto"], d["cant"]] for cat, d in _top_con_otros(categorias)]
    r, cs, ce = write_table(r, "TOP DE GASTOS POR CATEGORÍA", ["Categoría", "Monto", "Egresos"], rows, value_cols=(1,))
    if rows:
        pie2 = wb.add_chart({"type": "pie"})
        pie2.add_series({
            "name": "Gastos",
            "categories": ["Resumen", cs, 0, ce, 0],
            "values": ["Resumen", cs, 1, ce, 1],
            "data_labels": {"percentage": True},
        })
        pie2.set_title({"name": "Distribución de gastos"})
        pie2.set_legend({"position": "right", "font": {"size": 8}})
        ws.insert_chart(chart_anchor, chart_col, pie2, {"x_scale": 1.15, "y_scale": 1.0})

    # ── HOJAS DE DETALLE ──────────────────────────────────────────
    _hoja_tabla(wb, "Ingresos", INGRESOS_COLS, ingresos, f_money_table, f_header, f_cell)
    _hoja_tabla(wb, "Egresos", EGRESOS_COLS, egresos, f_money_table, f_header, f_cell)

    wb.close()


# ══════════════════════════════════════════════════════════════════
# Helpers de datos (fila → dict)
# ══════════════════════════════════════════════════════════════════
_RE_POLIZA = re.compile(r'P[oó]liza\s+(.+?)\s*$', re.IGNORECASE)


def _patente_de(desc, cache):
    """Deduce la patente del N° de póliza escrito en la descripción (con cache)."""
    m = _RE_POLIZA.search(desc or "")
    if not m:
        return ""
    numero = (m.group(1) or "").strip()
    if not numero:
        return ""
    if numero in cache:
        return cache[numero]
    pat = ""
    try:
        from polizas.models import Poliza
        pol = Poliza.objects.filter(numero_poliza=numero).only("patente").first()
        if pol and pol.patente:
            pat = str(pol.patente).strip().upper()
    except Exception:
        pat = ""
    cache[numero] = pat
    return pat


def _hora(obj):
    ca = getattr(obj, "created_at", None)
    if not ca:
        return ""
    try:
        return timezone.localtime(ca).strftime("%H:%M")
    except Exception:
        try:
            return ca.strftime("%H:%M")
        except Exception:
            return ""


def _fecha(obj):
    f = getattr(obj, "fecha", None)
    return f.strftime("%d/%m/%Y") if f else "—"


def _ofi(obj):
    ofi = getattr(obj, "oficina", None)
    return (getattr(ofi, "nombre", None) or "Sin sucursal") if ofi else "Sin sucursal"


def _uname(u):
    if not u:
        return "Sistema"
    return (f"{u.first_name} {u.last_name}".strip() or u.username)


def _dt(dt):
    if not dt:
        return ""
    try:
        return timezone.localtime(dt).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════════
# Vista (endpoint)
# ══════════════════════════════════════════════════════════════════
class ReporteCompletoExcelView(APIView):
    """
    GET /api/balanzes/reporte-completo/?desde=YYYY-MM-DD&hasta=YYYY-MM-DD&oficina=<ALL|id>
    (también acepta ?mes=YYYY-MM). Devuelve UN .xlsx con Resumen + Ingresos + Egresos.
    """
    permission_classes = [IsAuthenticated]

    def _resolver_keys(self, request, requested):
        user = request.user
        es_admin = user.is_superuser or (hasattr(user, "perfil") and getattr(user.perfil, "rol", None) == "ADMIN")
        if es_admin:
            if not requested or str(requested).upper() in ["ALL", "NULL", "UNDEFINED", ""]:
                return None  # todas las sucursales
            return _get_todas_las_llaves_oficina(requested)
        if hasattr(user, "perfil") and getattr(user.perfil, "oficina", None):
            return _get_todas_las_llaves_oficina(user.perfil.oficina)
        return "BLOQUEADO"

    def _rango(self, request):
        desde_raw = (request.query_params.get("desde") or "").strip()
        hasta_raw = (request.query_params.get("hasta") or "").strip()
        mes = (request.query_params.get("mes") or "").strip()
        if desde_raw and hasta_raw:
            try:
                return datetime.fromisoformat(desde_raw).date(), datetime.fromisoformat(hasta_raw).date()
            except Exception:
                pass
        if mes:
            try:
                y, m = mes.split("-")[:2]
                y, m = int(y), int(m)
                return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
            except Exception:
                pass
        hoy = timezone.localdate()
        return hoy.replace(day=1), date(hoy.year, hoy.month, calendar.monthrange(hoy.year, hoy.month)[1])

    def get(self, request):
        try:
            keys = self._resolver_keys(request, request.query_params.get("oficina"))
            if keys == "BLOQUEADO":
                return Response({"detail": "No autorizado."}, status=403)

            desde, hasta = self._rango(request)

            ing_qs = (Ingreso.objects
                      .filter(fecha__gte=desde, fecha__lte=hasta)
                      .select_related("oficina", "usuario", "verificada_por")
                      .order_by("fecha", "id"))
            eg_qs = (Egreso.objects
                     .filter(fecha__gte=desde, fecha__lte=hasta)
                     .select_related("oficina", "usuario")
                     .order_by("fecha", "id"))

            if keys:
                ing_qs = ing_qs.filter(oficina_id__in=keys)
                eg_qs = eg_qs.filter(oficina_id__in=keys)

            pat_cache = {}
            ingresos = [{
                "fecha": _fecha(i),
                "hora": _hora(i),
                "oficina": _ofi(i),
                "descripcion": i.descripcion or "—",
                "patente": _patente_de(i.descripcion, pat_cache),
                "categoria": i.categoria or "—",
                "forma_pago": (i.forma_pago or "EFECTIVO").upper(),
                "pagado_por": i.pagado_por or "—",
                "billetera": i.billetera or "—",
                "cuit_remitente": i.cuit_remitente or "—",
                "nro_operacion": i.nro_operacion or "—",
                "verificada": "Sí" if i.verificada else "No",
                "verificada_por": _uname(i.verificada_por) if i.verificada_por else "—",
                "verificada_en": _dt(i.verificada_en),
                "nota_verificacion": i.nota_verificacion or "",
                "observaciones": i.observaciones or "",
                "usuario": _uname(i.usuario),
                "monto": i.monto,
            } for i in ing_qs]

            egresos = [{
                "fecha": _fecha(e),
                "hora": _hora(e),
                "oficina": _ofi(e),
                "descripcion": e.descripcion or "—",
                "categoria": e.categoria or "—",
                "forma_pago": (e.forma_pago or "EFECTIVO").upper(),
                "observaciones": e.observaciones or "",
                "usuario": _uname(e.usuario),
                "monto": e.monto,
            } for e in eg_qs]

            output = io.BytesIO()
            construir_reporte_completo(
                output,
                desde_txt=desde.strftime("%d/%m/%Y"),
                hasta_txt=hasta.strftime("%d/%m/%Y"),
                generado_txt=timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M"),
                ingresos=ingresos,
                egresos=egresos,
            )
            output.seek(0)

            filename = f"Balance_Completo_{desde.strftime('%Y-%m-%d')}_a_{hasta.strftime('%Y-%m-%d')}.xlsx"
            resp = HttpResponse(
                output.read(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            resp["Content-Disposition"] = f'attachment; filename="{filename}"'
            resp["Access-Control-Expose-Headers"] = "Content-Disposition"
            return resp

        except Exception as e:
            traceback.print_exc()
            return Response({"error": str(e)}, status=500)