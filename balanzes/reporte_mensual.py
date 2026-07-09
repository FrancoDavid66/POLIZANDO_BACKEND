# balanzes/reporte_mensual.py
# 🚀 Reporte Gerencial MENSUAL en Excel — tablas reales, estilos y gráficos.
# Archivo independiente para no tocar el views.py grande.
# Se enchufa con una sola línea en balanzes/urls.py.

import io
import calendar
import traceback
from datetime import date, datetime

import xlsxwriter

from django.http import HttpResponse
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Ingreso, Egreso

# Reutilizamos el helper de seguridad que YA existe en views.py
# (traduce "ALL" / código / nombre de oficina a una lista de IDs reales).
from .views import _get_todas_las_llaves_oficina


# ══════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════
def _num(v):
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def _fmt_dt(obj):
    """Devuelve 'DD/MM/YYYY HH:MM' usando created_at; si no, 'DD/MM/YYYY' con fecha."""
    dt = getattr(obj, "created_at", None)
    if dt:
        try:
            dt = timezone.localtime(dt)
        except Exception:
            pass
        return dt.strftime("%d/%m/%Y %H:%M")
    f = getattr(obj, "fecha", None)
    return f.strftime("%d/%m/%Y") if f else "—"


def _ofi_nombre(obj):
    ofi = getattr(obj, "oficina", None)
    return getattr(ofi, "nombre", None) or "Sin sucursal" if ofi else "Sin sucursal"


# ══════════════════════════════════════════════════════════════════
# Motor de armado del workbook (puro xlsxwriter, sin Django)
# ══════════════════════════════════════════════════════════════════
def construir_workbook(output, *, desde_txt, hasta_txt, generado_txt, ingresos, egresos):
    """
    ingresos / egresos: listas de dicts con keys:
      oficina, fecha, descripcion, pagado_por, forma_pago, categoria, monto
    """
    wb = xlsxwriter.Workbook(output, {"in_memory": True})

    # ── Formatos ────────────────────────────────────────────
    f_title = wb.add_format({"bold": True, "font_size": 16, "bg_color": "#0F172A", "font_color": "#FFFFFF", "align": "center", "valign": "vcenter"})
    f_sub = wb.add_format({"italic": True, "font_size": 10, "bg_color": "#0F172A", "font_color": "#94A3B8", "align": "center", "valign": "vcenter"})
    f_section = wb.add_format({"bold": True, "font_size": 12, "bg_color": "#1E293B", "font_color": "#FFFFFF", "align": "left", "valign": "vcenter"})
    f_header = wb.add_format({"bold": True, "bg_color": "#334155", "font_color": "#FFFFFF", "border": 1, "border_color": "#CBD5E1", "align": "center"})
    f_cell = wb.add_format({"border": 1, "border_color": "#E2E8F0"})
    f_cell_alt = wb.add_format({"border": 1, "border_color": "#E2E8F0", "bg_color": "#F1F5F9"})
    f_money = wb.add_format({"border": 1, "border_color": "#E2E8F0", "num_format": "$#,##0.00"})
    f_money_alt = wb.add_format({"border": 1, "border_color": "#E2E8F0", "num_format": "$#,##0.00", "bg_color": "#F1F5F9"})
    money_fmt = wb.add_format({"num_format": "$#,##0.00"})

    # ── Totales y agregados ─────────────────────────────────
    total_in = sum(_num(i["monto"]) for i in ingresos)
    total_eg = sum(_num(e["monto"]) for e in egresos)
    balance = total_in - total_eg

    # 🚦 Semáforo de salud: cuánto se gastó respecto de lo que entró
    def salud(ing_m, eg_m):
        if ing_m <= 0:
            if eg_m > 0:
                return ("🔴 Riesgo (sin ingresos)", "#FEE2E2", "#991B1B")
            return ("⚪ Sin datos", "#F1F5F9", "#475569")
        ratio = eg_m / ing_m * 100
        if ratio <= 70:
            return (f"🟢 Sana ({ratio:.0f}% gastado)", "#DCFCE7", "#166534")
        if ratio <= 100:
            return (f"🟡 Atención ({ratio:.0f}% gastado)", "#FEF9C3", "#854D0E")
        return (f"🔴 Riesgo ({ratio:.0f}% gastado)", "#FEE2E2", "#991B1B")

    def agrupar(rows, key):
        acc = {}
        for r in rows:
            k = r.get(key) or "—"
            if k not in acc:
                acc[k] = {"monto": 0.0, "cant": 0}
            acc[k]["monto"] += _num(r["monto"])
            acc[k]["cant"] += 1
        return sorted(acc.items(), key=lambda kv: kv[1]["monto"], reverse=True)

    pagos = agrupar(ingresos, "forma_pago")
    sucursales = agrupar(ingresos, "oficina")
    categorias = agrupar(egresos, "categoria")

    # 🥧 Para las tortas: dejamos el TOP 8 y juntamos el resto en "Otros"
    #    (así la torta no queda con 15 tajaditas ilegibles).
    def top_con_otros(items, n=8):
        if len(items) <= n:
            return items
        top = items[:n]
        resto_monto = sum(v["monto"] for _, v in items[n:])
        resto_cant = sum(v["cant"] for _, v in items[n:])
        return top + [("Otros", {"monto": resto_monto, "cant": resto_cant})]

    # ════════════════════════════════════════════════════════
    # HOJA 1 — RESUMEN
    # ════════════════════════════════════════════════════════
    ws = wb.add_worksheet("Resumen")
    ws.hide_gridlines(2)
    ws.set_column("A:A", 34)
    ws.set_column("B:B", 18)
    ws.set_column("C:C", 16)

    ws.merge_range("A1:C1", "REPORTE GERENCIAL DE BALANCE", f_title)
    ws.set_row(0, 26)
    ws.merge_range("A2:C2", f"Período: {desde_txt} a {hasta_txt}   ·   Generado: {generado_txt}", f_sub)

    chart_col = 4  # columna E
    chart_anchor = 2
    CHART_GAP = 18

    def write_table(r, title, headers, rows, value_cols=()):
        ws.merge_range(r, 0, r, len(headers) - 1, title, f_section)
        r += 1
        for c, h in enumerate(headers):
            ws.write(r, c, h, f_header)
        r += 1
        data_start = r
        for ri, row in enumerate(rows):
            alt = ri % 2 == 1
            for c, val in enumerate(row):
                if c in value_cols:
                    ws.write_number(r, c, _num(val), f_money_alt if alt else f_money)
                else:
                    ws.write(r, c, val if val is not None else "", f_cell_alt if alt else f_cell)
            r += 1
        data_end = r - 1
        return r, data_start, data_end

    # Balance general + gráfico de columnas
    r = 3
    bal_lbl = "Balance Positivo ▲" if balance >= 0 else "Balance Negativo ▼"
    r, bs, be = write_table(
        r,
        "BALANCE GENERAL",
        ["Concepto", "Monto", "Cant. Operaciones"],
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
    chart_anchor += CHART_GAP

    # Ingresos por medio de pago + torta
    r += 1
    rows = [[fp, d["monto"], d["cant"]] for fp, d in pagos]
    r, ps, pe = write_table(r, "INGRESOS POR MEDIO DE PAGO", ["Medio de pago", "Monto total", "Operaciones"], rows, value_cols=(1,))
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
        chart_anchor += CHART_GAP

    # Recaudación por sucursal + barras
    r += 1
    rows = [[ofi, d["monto"], d["cant"]] for ofi, d in sucursales]
    r, ss, se = write_table(r, "RECAUDACIÓN POR SUCURSAL", ["Sucursal", "Monto recaudado", "Ingresos"], rows, value_cols=(1,))
    if rows:
        col = wb.add_chart({"type": "bar"})
        col.add_series({
            "name": "Recaudación",
            "categories": ["Resumen", ss, 0, se, 0],
            "values": ["Resumen", ss, 1, se, 1],
            "fill": {"color": "#0EA5E9"},
            "data_labels": {"value": True, "num_format": "$#,##0"},
        })
        col.set_title({"name": "Recaudación por sucursal"})
        col.set_legend({"none": True})
        ws.insert_chart(chart_anchor, chart_col, col, {"x_scale": 1.15, "y_scale": 1.0})
        chart_anchor += CHART_GAP

    # Top de gastos por categoría + torta
    r += 1
    rows = [[cat, d["monto"], d["cant"]] for cat, d in top_con_otros(categorias)]
    r, cs, ce = write_table(r, "TOP DE GASTOS POR CATEGORÍA", ["Categoría", "Monto gastado", "Egresos"], rows, value_cols=(1,))
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
        chart_anchor += CHART_GAP

    # ════════════════════════════════════════════════════════
    # HOJA 2 — INGRESOS (tabla real con filtros nativos)
    # ════════════════════════════════════════════════════════
    wsI = wb.add_worksheet("Ingresos")
    wsI.set_column("A:A", 16)
    wsI.set_column("B:B", 18)
    wsI.set_column("C:C", 40)
    wsI.set_column("D:D", 24)
    wsI.set_column("E:E", 16)
    wsI.set_column("F:F", 18)
    wsI.set_column("G:G", 16)
    ing_headers = ["Sucursal", "Fecha y hora", "Descripción", "Enviado por", "Forma de pago", "Categoría", "Monto"]
    ing_data = [[i["oficina"], i["fecha"], i["descripcion"], i["pagado_por"], i["forma_pago"], i["categoria"], _num(i["monto"])] for i in ingresos]
    if ing_data:
        wsI.add_table(0, 0, len(ing_data) + 1, len(ing_headers) - 1, {
            "name": "TablaIngresos",
            "style": "Table Style Medium 9",
            "total_row": True,
            "columns": [
                {"header": "Sucursal"},
                {"header": "Fecha y hora"},
                {"header": "Descripción", "total_string": "TOTAL"},
                {"header": "Enviado por"},
                {"header": "Forma de pago"},
                {"header": "Categoría"},
                {"header": "Monto", "total_function": "sum", "format": money_fmt},
            ],
            "data": ing_data,
        })
    else:
        for c, h in enumerate(ing_headers):
            wsI.write(0, c, h, f_header)
        wsI.write(1, 0, "Sin ingresos en el período", f_cell)

    # ════════════════════════════════════════════════════════
    # HOJA 3 — EGRESOS (tabla real con filtros nativos)
    # ════════════════════════════════════════════════════════
    wsE = wb.add_worksheet("Egresos")
    wsE.set_column("A:A", 16)
    wsE.set_column("B:B", 18)
    wsE.set_column("C:C", 20)
    wsE.set_column("D:D", 40)
    wsE.set_column("E:E", 16)
    wsE.set_column("F:F", 12)
    wsE.set_column("G:G", 16)
    eg_headers = ["Sucursal", "Fecha y hora", "Categoría", "Descripción", "Forma de pago", "Tipo", "Monto"]
    eg_data = [[e["oficina"], e["fecha"], e["categoria"], e["descripcion"], e["forma_pago"],
                ("Fijo" if e.get("es_fijo") else "Manual"), _num(e["monto"])] for e in egresos]
    if eg_data:
        wsE.add_table(0, 0, len(eg_data) + 1, len(eg_headers) - 1, {
            "name": "TablaEgresos",
            "style": "Table Style Medium 5",
            "total_row": True,
            "columns": [
                {"header": "Sucursal"},
                {"header": "Fecha y hora"},
                {"header": "Categoría"},
                {"header": "Descripción", "total_string": "TOTAL"},
                {"header": "Forma de pago"},
                {"header": "Tipo"},
                {"header": "Monto", "total_function": "sum", "format": money_fmt},
            ],
            "data": eg_data,
        })
    else:
        for c, h in enumerate(eg_headers):
            wsE.write(0, c, h, f_header)
        wsE.write(1, 0, "Sin egresos en el período", f_cell)

    # ════════════════════════════════════════════════════════
    # HOJA "POR SUCURSAL" — comparativa de todas las oficinas
    # ════════════════════════════════════════════════════════
    # Junta ingresos y egresos por oficina: cantidad y monto de cada uno + balance.
    resumen_ofi = {}  # nombre -> {ing_cant, ing_monto, eg_cant, eg_monto, fijo_cant, fijo_monto}
    for i in ingresos:
        k = i.get("oficina") or "Sin sucursal"
        d = resumen_ofi.setdefault(k, {"ing_cant": 0, "ing_monto": 0.0, "eg_cant": 0, "eg_monto": 0.0, "fijo_cant": 0, "fijo_monto": 0.0})
        d["ing_cant"] += 1
        d["ing_monto"] += _num(i["monto"])
    for e in egresos:
        k = e.get("oficina") or "Sin sucursal"
        d = resumen_ofi.setdefault(k, {"ing_cant": 0, "ing_monto": 0.0, "eg_cant": 0, "eg_monto": 0.0, "fijo_cant": 0, "fijo_monto": 0.0})
        d["eg_cant"] += 1
        d["eg_monto"] += _num(e["monto"])
        if e.get("es_fijo"):
            d["fijo_cant"] += 1
            d["fijo_monto"] += _num(e["monto"])

    # Orden por balance (de mayor a menor)
    filas_ofi = sorted(
        resumen_ofi.items(),
        key=lambda kv: (kv[1]["ing_monto"] - kv[1]["eg_monto"]),
        reverse=True,
    )

    wsS = wb.add_worksheet("Por Sucursal")
    wsS.set_column("A:A", 24)
    wsS.set_column("B:G", 16)
    wsS.set_column("H:H", 26)
    wsS.merge_range(0, 0, 0, 7, "RESUMEN POR SUCURSAL", f_title)
    wsS.merge_range(1, 0, 1, 7, f"{desde_txt} al {hasta_txt}", f_sub)

    headers_s = ["Sucursal", "Cant. ingresos", "Total ingresos", "Cant. egresos", "Total egresos", "Egresos fijos ($)", "Balance", "Estado"]
    hr = 3
    for c, h in enumerate(headers_s):
        wsS.write(hr, c, h, f_header)
    rr = hr + 1
    for idx, (nombre, d) in enumerate(filas_ofi):
        bal = d["ing_monto"] - d["eg_monto"]
        alt = idx % 2 == 1
        fc = f_cell_alt if alt else f_cell
        fm = f_money_alt if alt else f_money
        wsS.write(rr, 0, nombre, fc)
        wsS.write_number(rr, 1, d["ing_cant"], fc)
        wsS.write_number(rr, 2, d["ing_monto"], fm)
        wsS.write_number(rr, 3, d["eg_cant"], fc)
        wsS.write_number(rr, 4, d["eg_monto"], fm)
        wsS.write_number(rr, 5, d["fijo_monto"], fm)
        wsS.write_number(rr, 6, bal, fm)
        et, ebg, efg = salud(d["ing_monto"], d["eg_monto"])
        wsS.write(rr, 7, et, wb.add_format({
            "border": 1, "border_color": "#E2E8F0", "bg_color": ebg,
            "font_color": efg, "bold": True, "align": "center",
        }))
        rr += 1
    if not filas_ofi:
        wsS.write(rr, 0, "Sin movimientos en el período", f_cell)
    else:
        # 🏆 Gráfico comparativo: balance de todas las sucursales
        comp = wb.add_chart({"type": "bar"})
        comp.add_series({
            "name": "Balance",
            "categories": [wsS.name, hr + 1, 0, rr - 1, 0],
            "values":     [wsS.name, hr + 1, 6, rr - 1, 6],
            "data_labels": {"value": True, "num_format": "$#,##0"},
            "fill": {"color": "#0EA5E9"},
        })
        comp.set_title({"name": "Balance por sucursal"})
        comp.set_legend({"none": True})
        comp.set_size({"width": 520, "height": max(220, 70 + 32 * len(filas_ofi))})
        wsS.insert_chart(rr + 2, 0, comp)

    # ════════════════════════════════════════════════════════
    # UNA HOJA POR CADA SUCURSAL (balance individual + detalle)
    # ════════════════════════════════════════════════════════
    usados = set()  # para no repetir nombres de hoja (límite Excel: 31 chars)

    def nombre_hoja(base):
        # Excel no permite estos caracteres en nombres de hoja: [ ] : * ? / \
        limpio = "".join(ch for ch in str(base) if ch not in "[]:*?/\\")[:28] or "Sucursal"
        cand = limpio
        n = 2
        while cand.lower() in usados:
            cand = f"{limpio[:25]}_{n}"
            n += 1
        usados.add(cand.lower())
        return cand

    for nombre, d in filas_ofi:
        ws = wb.add_worksheet(nombre_hoja(nombre))
        # Izquierda = Ingresos (A-E) · separador F · Derecha = Egresos (G-L)
        ws.set_column("A:A", 17)  # fecha
        ws.set_column("B:B", 30)  # descripción
        ws.set_column("C:C", 14)
        ws.set_column("D:D", 18)
        ws.set_column("E:E", 14)
        ws.set_column("F:F", 3)   # separador
        ws.set_column("G:G", 17)
        ws.set_column("H:H", 30)
        ws.set_column("I:I", 14)
        ws.set_column("J:J", 18)
        ws.set_column("K:K", 10)
        ws.set_column("L:L", 14)

        ws.merge_range(0, 0, 0, 11, f"SUCURSAL: {nombre}", f_title)
        ws.merge_range(1, 0, 1, 11, f"{desde_txt} al {hasta_txt}", f_sub)

        bal = d["ing_monto"] - d["eg_monto"]

        # ── Tarjeta de balance (A4:C8) ──
        ws.write(3, 0, "Balance de la sucursal", f_section)
        ws.write(4, 0, "Concepto", f_header)
        ws.write(4, 1, "Cantidad", f_header)
        ws.write(4, 2, "Monto", f_header)
        ws.write(5, 0, "Ingresos", f_cell)
        ws.write_number(5, 1, d["ing_cant"], f_cell)
        ws.write_number(5, 2, d["ing_monto"], f_money)
        ws.write(6, 0, "Egresos", f_cell_alt)
        ws.write_number(6, 1, d["eg_cant"], f_cell_alt)
        ws.write_number(6, 2, d["eg_monto"], f_money_alt)
        ws.write(7, 0, "BALANCE", f_header)
        ws.write(7, 1, "", f_header)
        ws.write_number(7, 2, bal, wb.add_format({
            "border": 1, "border_color": "#E2E8F0", "num_format": "$#,##0.00",
            "bold": True, "bg_color": "#DCFCE7" if bal >= 0 else "#FEE2E2",
        }))
        # 🚦 Semáforo (debajo del balance)
        et, ebg, efg = salud(d["ing_monto"], d["eg_monto"])
        ws.write(8, 0, "Estado", f_header)
        ws.merge_range(8, 1, 8, 2, et, wb.add_format({
            "bold": True, "border": 1, "border_color": "#E2E8F0",
            "bg_color": ebg, "font_color": efg, "align": "center",
        }))

        # 📊 Gráfico Ingresos vs Egresos (arriba a la derecha, sobre la zona de egresos)
        chart = wb.add_chart({"type": "column"})
        chart.add_series({
            "name": "Monto",
            "categories": [ws.name, 5, 0, 6, 0],
            "values":     [ws.name, 5, 2, 6, 2],
            "points": [{"fill": {"color": "#10B981"}}, {"fill": {"color": "#EF4444"}}],
            "data_labels": {"value": True, "num_format": "$#,##0"},
        })
        chart.set_title({"name": "Ingresos vs Egresos"})
        chart.set_legend({"none": True})
        chart.set_size({"width": 300, "height": 170})
        ws.insert_chart(3, 6, chart)  # G4

        ing_ofi = [i for i in ingresos if (i.get("oficina") or "Sin sucursal") == nombre]
        eg_ofi = [e for e in egresos if (e.get("oficina") or "Sin sucursal") == nombre]

        # ── Detalle: las dos tablas EMPIEZAN EN LA MISMA FILA (lado a lado) ──
        FILA_DETALLE = 11  # debajo de la tarjeta y de los charts superiores

        # INGRESOS (izquierda, columnas A-E = 0..4)
        ri = FILA_DETALLE
        ws.merge_range(ri, 0, ri, 4, "INGRESOS", f_section)
        ri += 1
        for c, h in enumerate(["Fecha y hora", "Descripción", "Forma de pago", "Categoría", "Monto"]):
            ws.write(ri, c, h, f_header)
        ri += 1
        for idx, i in enumerate(ing_ofi):
            alt = idx % 2 == 1
            fc = f_cell_alt if alt else f_cell
            fm = f_money_alt if alt else f_money
            ws.write(ri, 0, i["fecha"], fc)
            ws.write(ri, 1, i["descripcion"], fc)
            ws.write(ri, 2, i["forma_pago"], fc)
            ws.write(ri, 3, i["categoria"], fc)
            ws.write_number(ri, 4, _num(i["monto"]), fm)
            ri += 1
        if not ing_ofi:
            ws.write(ri, 0, "Sin ingresos", f_cell)
            ri += 1

        # EGRESOS (derecha, columnas G-L = 6..11)
        re_ = FILA_DETALLE
        ws.merge_range(re_, 6, re_, 11, "EGRESOS", f_section)
        re_ += 1
        for c, h in enumerate(["Fecha y hora", "Descripción", "Forma de pago", "Categoría", "Tipo", "Monto"]):
            ws.write(re_, 6 + c, h, f_header)
        re_ += 1
        for idx, e in enumerate(eg_ofi):
            alt = idx % 2 == 1
            fc = f_cell_alt if alt else f_cell
            fm = f_money_alt if alt else f_money
            ws.write(re_, 6, e["fecha"], fc)
            ws.write(re_, 7, e["descripcion"], fc)
            ws.write(re_, 8, e["forma_pago"], fc)
            ws.write(re_, 9, e["categoria"], fc)
            ws.write(re_, 10, "Fijo" if e.get("es_fijo") else "Manual", fc)
            ws.write_number(re_, 11, _num(e["monto"]), fm)
            re_ += 1
        if not eg_ofi:
            ws.write(re_, 6, "Sin egresos", f_cell)
            re_ += 1

        # ── Torta de gastos por categoría (debajo de las tablas) ──
        cat_acc = {}
        for e in eg_ofi:
            k = e.get("categoria") or "—"
            cat_acc[k] = cat_acc.get(k, 0) + _num(e["monto"])
        cat_rows = sorted(cat_acc.items(), key=lambda kv: kv[1], reverse=True)
        # agrupar chicas en "Otros" para que la torta sea legible
        if len(cat_rows) > 8:
            top = cat_rows[:8]
            resto = sum(m for _, m in cat_rows[8:])
            cat_rows = top + [("Otros", resto)]

        if cat_rows:
            base = max(ri, re_) + 2  # debajo de la tabla más larga
            ws.write(base, 0, "GASTOS POR CATEGORÍA", f_section)
            hrow = base + 1
            ws.write(hrow, 0, "Categoría", f_header)
            ws.write(hrow, 1, "Monto", f_header)
            cat_first = hrow + 1
            rr2 = cat_first
            for idx, (cat, monto) in enumerate(cat_rows):
                alt = idx % 2 == 1
                ws.write(rr2, 0, cat, f_cell_alt if alt else f_cell)
                ws.write_number(rr2, 1, monto, f_money_alt if alt else f_money)
                rr2 += 1
            cat_last = rr2 - 1
            pie = wb.add_chart({"type": "pie"})
            pie.add_series({
                "name": "Gastos por categoría",
                "categories": [ws.name, cat_first, 0, cat_last, 0],
                "values":     [ws.name, cat_first, 1, cat_last, 1],
                "data_labels": {"percentage": True},
            })
            pie.set_title({"name": "¿En qué se gasta?"})
            pie.set_legend({"position": "right", "font": {"size": 8}})
            pie.set_size({"width": 380, "height": 260})
            ws.insert_chart(base, 3, pie)  # a la derecha de la tablita

    wb.close()


# ══════════════════════════════════════════════════════════════════
# Vista (endpoint)
# ══════════════════════════════════════════════════════════════════
class ReporteMensualExcelView(APIView):
    """
    GET /api/balanzes/balance-mensual/exportar/?mes=YYYY-MM&oficina=<ALL|id|nombre>
    También acepta ?desde=YYYY-MM-DD&hasta=YYYY-MM-DD.
    Devuelve un .xlsx con tablas, estilos y gráficos.
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
        mes = (request.query_params.get("mes") or "").strip()
        desde_raw = (request.query_params.get("desde") or "").strip()
        hasta_raw = (request.query_params.get("hasta") or "").strip()
        if mes:
            try:
                y, m = mes.split("-")[:2]
                y, m = int(y), int(m)
                return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
            except Exception:
                pass
        if desde_raw and hasta_raw:
            try:
                return datetime.fromisoformat(desde_raw).date(), datetime.fromisoformat(hasta_raw).date()
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
                      .select_related("oficina")
                      .order_by("fecha", "id"))
            eg_qs = (Egreso.objects
                     .filter(fecha__gte=desde, fecha__lte=hasta)
                     .select_related("oficina")
                     .order_by("fecha", "id"))

            if keys:
                ing_qs = ing_qs.filter(oficina_id__in=keys)
                eg_qs = eg_qs.filter(oficina_id__in=keys)

            # 🚀 Detectar qué egresos vienen de un SERVICIO FIJO.
            #    Lo más confiable: los pagos de servicio guardan un FK al egreso.
            #    Si por algún motivo falla, caemos a detectar por las observaciones.
            eg_list = list(eg_qs)
            ids_fijos = set()
            try:
                from servicios.models import PagoServicio
                ids_fijos = set(
                    PagoServicio.objects
                    .filter(egreso_id__in=[e.id for e in eg_list])
                    .values_list("egreso_id", flat=True)
                )
            except Exception:
                ids_fijos = set()

            def _es_fijo(e):
                if e.id in ids_fijos:
                    return True
                obs = (getattr(e, "observaciones", "") or "").lower()
                return "servicio fijo" in obs

            ingresos = [{
                "oficina": _ofi_nombre(i),
                "fecha": _fmt_dt(i),
                "descripcion": i.descripcion or "—",
                "pagado_por": i.pagado_por or "—",
                "forma_pago": (i.forma_pago or "EFECTIVO"),
                "categoria": i.categoria or "—",
                "monto": i.monto,
            } for i in ing_qs]

            egresos = [{
                "oficina": _ofi_nombre(e),
                "fecha": _fmt_dt(e),
                "categoria": e.categoria or "—",
                "descripcion": e.descripcion or "—",
                "forma_pago": (e.forma_pago or "EFECTIVO"),
                "monto": e.monto,
                "es_fijo": _es_fijo(e),
            } for e in eg_list]

            output = io.BytesIO()
            construir_workbook(
                output,
                desde_txt=desde.strftime("%d/%m/%Y"),
                hasta_txt=hasta.strftime("%d/%m/%Y"),
                generado_txt=timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M"),
                ingresos=ingresos,
                egresos=egresos,
            )
            output.seek(0)

            filename = f"Reporte_Mensual_{desde.strftime('%Y-%m')}.xlsx"
            resp = HttpResponse(
                output.read(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            resp["Content-Disposition"] = f'attachment; filename="{filename}"'
            return resp

        except Exception as e:
            traceback.print_exc()
            return Response({"error": str(e)}, status=500)