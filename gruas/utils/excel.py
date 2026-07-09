from io import BytesIO

try:
    import openpyxl
    OPENPYXL_OK = True
except Exception:
    OPENPYXL_OK = False


def build_solicitudes_excel(qs):
    if not OPENPYXL_OK:
        raise RuntimeError("openpyxl no disponible")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Solicitudes"
    ws.append([
        "ID", "Fecha", "Poliza", "Motivo", "Estado", "KM Totales", "KM Excedentes", "Proveedor", "Costo Prov.", "Copago Cliente"
    ])
    for s in qs:
        ws.append([
            s.id, s.fecha_solicitud, getattr(s.poliza, "numero_poliza", s.poliza_id), s.motivo, s.estado,
            float(s.km_totales or 0), float(s.km_excedentes_cliente or 0),
            getattr(getattr(s, "proveedor", None), "nombre", ""), float(s.costo_proveedor or 0), float(s.copago_cliente or 0)
        ])
    data = BytesIO()
    wb.save(data)
    data.seek(0)
    return data.getvalue()


def build_solicitudes_csv(qs):
    import csv
    from io import StringIO
    sio = StringIO()
    w = csv.writer(sio)
    w.writerow(["ID", "Fecha", "Poliza", "Motivo", "Estado", "KM Totales", "KM Excedentes", "Proveedor", "Costo Prov.", "Copago Cliente"])
    for s in qs:
        w.writerow([
            s.id, s.fecha_solicitud, getattr(s.poliza, "numero_poliza", s.poliza_id), s.motivo, s.estado,
            float(s.km_totales or 0), float(s.km_excedentes_cliente or 0),
            getattr(getattr(s, "proveedor", None), "nombre", ""), float(s.costo_proveedor or 0), float(s.copago_cliente or 0)
        ])
    return sio.getvalue().encode("utf-8")
