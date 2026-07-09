# polizas/views/mixins/exports.py

from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from django.http import HttpResponse
from django.utils import timezone

from io import BytesIO
import csv

from polizas.models import Poliza
from polizas.domain.bool import to_bool as _to_bool


class PolizaExportsMixin:
    @action(detail=False, methods=["get"], url_path="asegurados-export", permission_classes=[IsAuthenticated])
    def asegurados_export(self, request):
        params = request.query_params
        oficina = (params.get("oficina") or "").strip()
        tiene_auto = _to_bool(params.get("tiene_auto"))
        solo_activas = _to_bool(params.get("solo_activas"))
        formato = (params.get("formato") or "pdf").strip().lower()

        # 🚀 PRECARGAMOS LAS CUOTAS PARA CÁLCULOS RÁPIDOS
        qs = Poliza.objects.select_related("cliente", "oficina", "compania_obj").prefetch_related("cuotas").all()

        user = request.user
        is_admin = user.is_superuser or getattr(user.perfil, 'rol', '') == 'ADMIN'
        if not is_admin:
            ofi_id = getattr(user.perfil, 'oficina_id', None)
            if ofi_id:
                qs = qs.filter(oficina_id=ofi_id)
        elif oficina:
            qs = self._apply_oficina_filter(qs, oficina)

        if solo_activas:
            qs = qs.filter(estado="activa")
        if tiene_auto:
            qs = qs.exclude(patente__isnull=True).exclude(patente__exact="")

        # 🚀 CABECERAS SEPARADAS Y CLARAS
        headers = [
            "Cliente", "Teléfono", "Póliza", "Cía", "Patente", "Vehículo", 
            "Vto. Cuota", "Estado Pago", 
            "Corregido", "Elim.", "Baja", "Venc.", "Editar"
        ]

        rows = []
        hoy = timezone.localdate()

        for p in qs:
            cliente_nombre = f"{getattr(p.cliente, 'nombre', '')} {getattr(p.cliente, 'apellido', '')}".strip()
            tel = getattr(p.cliente, "whatsapp", "") or getattr(p.cliente, "telefono", "") or getattr(p.cliente, "celular", "")
            
            compania_nombre = getattr(p.compania_obj, "nombre", "") if getattr(p, "compania_obj", None) else getattr(p, "compania", "")
            vehiculo = f"{p.marca} {p.modelo}".strip()
            
            # 🚀 CÁLCULO DE LA FECHA LÍMITE DE PAGO (cuándo tiene que pagar la próxima cuota)
            cuotas_all = list(p.cuotas.all())
            cuotas_pendientes = [c for c in cuotas_all if not getattr(c, 'pagado', False)]
            cant_pendientes = len(cuotas_pendientes)

            vto_cuota_str = "-"

            if cant_pendientes == 0:
                estado_pago = "AL DÍA"
            else:
                # Cobertura vigente = vto de la ÚLTIMA cuota PAGADA (hasta cuándo está cubierto).
                # Esa fecha es la fecha límite en que tiene que pagar la próxima cuota.
                vtos_pagas = [c.fecha_vencimiento for c in cuotas_all
                              if getattr(c, 'pagado', False) and getattr(c, 'fecha_vencimiento', None)]
                if vtos_pagas:
                    corte = max(vtos_pagas)
                else:
                    # Nunca pagó nada: la mora arranca en el vto de su primera cuota impaga.
                    vtos_impagas = [c.fecha_vencimiento for c in cuotas_pendientes if getattr(c, 'fecha_vencimiento', None)]
                    corte = min(vtos_impagas) if vtos_impagas else None

                if corte is None:
                    estado_pago = f"MORA ({cant_pendientes})"
                else:
                    vto_cuota_str = corte.strftime("%d/%m/%y")  # fecha límite de pago
                    diff_days = (hoy - corte).days

                    if diff_days == 0:
                        estado_pago = f"VENCE HOY ({cant_pendientes})"
                    elif diff_days > 0:
                        estado_pago = f"MORA ({cant_pendientes})"
                    else:
                        if abs(diff_days) <= 7:
                            estado_pago = f"PRÓX VTO ({cant_pendientes})"
                        else:
                            estado_pago = f"AL DÍA ({cant_pendientes})"

            rows.append([
                cliente_nombre[:22],                 # 0: Cliente
                str(tel)[:15],                       # 1: Teléfono
                str(p.numero_poliza or 'S/N')[:15],  # 2: Póliza
                str(compania_nombre)[:12],           # 3: Cía
                str(p.patente)[:10],                 # 4: Patente
                vehiculo[:20],                       # 5: Vehículo
                vto_cuota_str,                       # 6: Vto. Cuota (DATO CLAVE)
                estado_pago,                         # 7: Estado Pago
                "[   ]",                             # 8: Corregido
                "[   ]",                             # 9: Eliminar
                "[   ]",                             # 10: Baja
                "[   ]",                             # 11: Vencida
                ""                                   # 12: Editar
            ])

        filename_base = f"Auditoria_Polizas_{hoy.isoformat()}"

        # --- EXPORTACIÓN PDF ---
        if formato == "pdf":
            try:
                from reportlab.lib.pagesizes import legal, landscape
                from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
                from reportlab.lib import colors
            except ImportError:
                return HttpResponse("Error: ReportLab no está instalado. Ejecutá 'pip install reportlab'", status=500)

            bio = BytesIO()
            # Hoja Legal apaisada (mucho ancho disponible)
            doc = SimpleDocTemplate(bio, pagesize=landscape(legal), leftMargin=10, rightMargin=10, topMargin=15, bottomMargin=15)
            
            # Reparto exacto del espacio en 13 columnas (Total: 978 pts)
            col_widths = [
                95,  # Cliente
                65,  # Teléfono
                65,  # Póliza
                50,  # Cía
                45,  # Patente
                90,  # Vehículo
                55,  # Vto. Cuota (un poco más ancha para que respire)
                75,  # Estado Pago
                35,  # Corregido
                30,  # Elim.
                30,  # Baja
                30,  # Venc.
                313  # Editar (espacio remanente gigante)
            ]

            data = [headers] + rows
            t = Table(data, colWidths=col_widths, repeatRows=1)
            
            t.setStyle(TableStyle([
                # Formato del encabezado
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#18181b")), 
                ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                ('ALIGN', (0,0), (-1,0), 'CENTER'),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('FONTSIZE', (0,0), (-1,0), 7),
                ('BOTTOMPADDING', (0,0), (-1,0), 6),
                ('TOPPADDING', (0,0), (-1,0), 6),
                
                # Formato de las filas
                ('BACKGROUND', (0,1), (-1,-1), colors.white),
                ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#d4d4d8")), 
                ('FONTSIZE', (0,1), (-1,-1), 6), 
                ('BOTTOMPADDING', (0,1), (-1,-1), 5),
                ('TOPPADDING', (0,1), (-1,-1), 5),
                
                # Alineaciones estratégicas
                ('ALIGN', (0,1), (7,-1), 'LEFT'),    # Datos textuales alineados a la izq
                ('ALIGN', (8,1), (11,-1), 'CENTER'), # Las columnas de los [ ] centradas
                
                # 🚀 ESTILO ESPECIAL PARA EL VENCIMIENTO DE LA CUOTA (Columna 6)
                ('FONTNAME', (6,1), (6,-1), 'Helvetica-Bold'),
                ('FONTSIZE', (6,1), (6,-1), 9), # Letra más grande (base es 6)
                ('TEXTCOLOR', (6,1), (6,-1), colors.HexColor("#09090b")), # Negro intenso
            ]))
            
            doc.build([t])
            bio.seek(0)
            resp = HttpResponse(bio.getvalue(), content_type='application/pdf')
            resp["Content-Disposition"] = f'attachment; filename="{filename_base}.pdf"'
            return resp

        # --- EXPORTACIÓN EXCEL ---
        if formato == "xlsx":
            try:
                from openpyxl import Workbook
                from openpyxl.styles import Font
                wb = Workbook()
                ws = wb.active
                ws.title = "Auditoría"
                ws.append(headers)
                for cell in ws[1]: cell.font = Font(bold=True)
                for r in rows: ws.append(r)
                bio = BytesIO()
                wb.save(bio)
                bio.seek(0)
                resp = HttpResponse(bio.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                resp["Content-Disposition"] = f'attachment; filename="{filename_base}.xlsx"'
                return resp
            except Exception:
                pass

        # --- EXPORTACIÓN CSV ---
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{filename_base}.csv"'
        writer = csv.writer(resp)
        writer.writerow(headers)
        writer.writerows(rows)
        return resp