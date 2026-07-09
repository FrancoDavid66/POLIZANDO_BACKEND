# tareas/papeles_sistema.py
#
# Endpoint que recibe los papeles de una póliza (típicamente RENOVADA) y los
# carga al sistema:
#   1) Guarda los PDFs como documentos de la póliza (póliza, Mercosur, cuponera).
#   2) Autocompleta lo que el papel SÍ trae y a la póliza le falta: número y compañía.
#      → NUNCA toca las fechas de la póliza ni de las cuotas (se respeta la renovación).
#   3) Si vino una cuponera (cupones leídos):
#      - ajusta las fechas de los cupones de ROBO (si la póliza es con robo), y
#      - sincroniza las CUOTAS con la cuponera: cantidad + fechas + importes.
#
# El front sube los PDFs a Cloudinary y los lee con el LectorPdfView; después
# llama acá con: poliza_id + documentos (urls) + datos extraídos.

from datetime import datetime, date

from dateutil.relativedelta import relativedelta
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from polizas.models import Poliza, PolizaDocumento, CuponRobo
from pagos.models import Cuota
from .models import TareaCompletada


def _es_admin(user) -> bool:
    return bool(
        getattr(user, "is_superuser", False)
        or (hasattr(user, "perfil") and getattr(user.perfil, "rol", None) == "ADMIN")
    )


def _oficina_del_user(user):
    return getattr(getattr(user, "perfil", None), "oficina_id", None)


def _to_date(v):
    """Acepta 'YYYY-MM-DD' (lo que devuelve el lector) o date; None si no se puede."""
    if not v:
        return None
    if isinstance(v, date):
        return v
    try:
        return datetime.fromisoformat(str(v)[:10]).date()
    except Exception:
        return None


class SubirPapelesSistemaView(APIView):
    """
    POST /api/tareas/subir-papeles-sistema/
    body: {
      "poliza_id": 123,
      "documentos": [
        {"tipo": "POLIZA",   "url": "...", "public_id": "...", "nombre": "...", "mime": "application/pdf"},
        {"tipo": "MERCOSUR", "url": "...", ...},
        {"tipo": "CUPONERA", "url": "...", ...}
      ],
      "datos": {
        "numero": "11912360",
        "compania": "NRE",
        "cupones": [ {"numero": 1, "vencimiento": "2026-08-23"}, ... ]   # opcional
      }
    }
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        poliza_id = request.data.get("poliza_id")
        documentos = request.data.get("documentos") or []
        datos = request.data.get("datos") or {}

        if not poliza_id:
            return Response({"detail": "Falta poliza_id."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            poliza = Poliza.objects.get(id=poliza_id)
        except Poliza.DoesNotExist:
            return Response({"detail": "Póliza no encontrada."}, status=status.HTTP_404_NOT_FOUND)

        # Permiso por oficina (igual que el resto de tareas)
        user = request.user
        if not _es_admin(user):
            ofi_id = _oficina_del_user(user)
            if poliza.oficina_id and ofi_id and poliza.oficina_id != ofi_id:
                return Response(
                    {"detail": "No podés modificar pólizas de otra oficina."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        resumen = {"documentos_guardados": 0, "autocompletado": [], "cupones_actualizados": 0, "cuotas_actualizadas": 0}

        # ── 1) Guardar los PDFs como documentos de la póliza ──────────────
        for d in documentos:
            url = (d.get("url") or "").strip()
            if not url:
                continue
            PolizaDocumento.objects.create(
                poliza=poliza,
                tipo=(d.get("tipo") or "OTRO"),
                url=url,
                public_id=(d.get("public_id") or ""),
                nombre=(d.get("nombre") or ""),
                mime=(d.get("mime") or ""),
            )
            resumen["documentos_guardados"] += 1

        # ── 2) Autocompletar SOLO lo que falta (número y compañía) ────────
        #     Nunca tocamos fechas de póliza ni de cuotas.
        cambios = []
        numero_pdf = (str(datos.get("numero") or "")).strip()
        if numero_pdf and (poliza.sin_numero or not (poliza.numero_poliza or "").strip()):
            poliza.numero_poliza = numero_pdf
            poliza.sin_numero = False
            cambios += ["numero_poliza", "sin_numero"]
            resumen["autocompletado"].append("número de póliza")

        compania_pdf = (str(datos.get("compania") or "")).strip()
        if compania_pdf and not (poliza.compania or "").strip():
            poliza.compania = compania_pdf
            cambios.append("compania")
            resumen["autocompletado"].append("compañía")

        # ── 2b) Correcciones que el usuario eligió "usar la del PDF" ───────
        #     (cuando un dato no coincidía: patente / DNI / nombre)
        correcciones = request.data.get("correcciones") or {}
        cliente = getattr(poliza, "cliente", None)
        campos_cli = []

        if (correcciones.get("patente") or "").strip():
            poliza.patente = str(correcciones["patente"]).strip().upper()
            cambios.append("patente")
            resumen["autocompletado"].append("patente (corregida)")

        if cliente:
            if (correcciones.get("dni") or "").strip():
                cliente.dni_cuit_cuil = str(correcciones["dni"]).strip()
                campos_cli.append("dni_cuit_cuil")
                resumen["autocompletado"].append("DNI (corregido)")
            if (correcciones.get("nombre") or "").strip():
                cliente.nombre = str(correcciones["nombre"]).strip()
                campos_cli.append("nombre")
            if (correcciones.get("apellido") or "").strip():
                cliente.apellido = str(correcciones["apellido"]).strip()
                campos_cli.append("apellido")
            if campos_cli:
                cliente.save(update_fields=list(set(campos_cli)))
                if "nombre" in campos_cli or "apellido" in campos_cli:
                    resumen["autocompletado"].append("titular (corregido)")

        if cambios:
            poliza.save(update_fields=list(set(cambios)))

        # ── 3) Cupones de robo: SOLO si vino cuponera y la póliza es con robo ─
        cupones_pdf = datos.get("cupones") or []
        cupones_robo = list(
            CuponRobo.objects.filter(poliza=poliza).order_by("fecha_vencimiento", "id")
        )
        if cupones_pdf and cupones_robo:
            # Ordenamos los del PDF por número y los emparejamos por orden con los de la póliza.
            cupones_pdf_ord = sorted(
                cupones_pdf, key=lambda c: int(c.get("numero") or 0)
            )
            for cp_pdf, cup in zip(cupones_pdf_ord, cupones_robo):
                vto = _to_date(cp_pdf.get("vencimiento"))
                if not vto:
                    continue
                cup.fecha_vencimiento = vto
                cup.periodo_desde = vto
                cup.periodo_hasta = vto + relativedelta(months=1)
                cup.save(update_fields=["fecha_vencimiento", "periodo_desde", "periodo_hasta"])
                resumen["cupones_actualizados"] += 1

        # ── 3a) Con cuponera: las CUOTAS se sincronizan EXACTO con la cuponera.
        #        El cliente tiene los cupones en la mano, así que las cuotas del
        #        portal deben coincidir 1 a 1: misma CANTIDAD, mismas FECHAS y
        #        mismos IMPORTES. Las cuotas ya PAGADAS no se tocan (son historial).
        if cupones_pdf:
            cuotas = list(Cuota.objects.filter(poliza=poliza).order_by("cuota_nro", "id"))
            cupones_ord = sorted(
                cupones_pdf, key=lambda c: (_to_date(c.get("vencimiento")) or date.max)
            )
            total_cup = len(cupones_ord)
            actualizadas = 0

            # (a) Emparejar por orden: cupón i ↔ cuota i → copiar fecha + importe.
            for i, cup in enumerate(cupones_ord):
                vto = _to_date(cup.get("vencimiento"))
                try:
                    imp = float(cup.get("importe") or 0)
                except (TypeError, ValueError):
                    imp = 0.0

                if i < len(cuotas):
                    c = cuotas[i]
                    if c.pagado:
                        continue  # cuota ya pagada: se conserva como historial
                    campos = []
                    if vto:
                        c.fecha_vencimiento = vto
                        campos.append("fecha_vencimiento")
                    if imp > 0:
                        c.monto = imp
                        campos.append("monto")
                    if campos:
                        c.save(update_fields=campos)
                        actualizadas += 1
                else:
                    # (b) Faltan cuotas en el portal: las creamos según la cuponera.
                    Cuota.objects.create(
                        poliza=poliza,
                        cuota_nro=i + 1,
                        fecha_vencimiento=vto,
                        monto=imp,
                        pagado=False,
                    )
                    actualizadas += 1

            # (c) Sobran cuotas (más que cupones): borramos las de más,
            #     pero SOLO las impagas (las pagadas quedan como historial).
            if len(cuotas) > total_cup:
                for c in cuotas[total_cup:]:
                    if not c.pagado:
                        c.delete()

            resumen["cuotas_actualizadas"] = actualizadas

        # ── 3b) Sin cuponera: el usuario puede fijar la fecha de la 1ª cuota.
        #        Cuota 1 = esa fecha; cada cuota siguiente, +1 mes.
        fecha_ini = _to_date(request.data.get("fecha_inicial_cuotas"))
        if fecha_ini and not cupones_pdf:
            cuotas = list(Cuota.objects.filter(poliza=poliza).order_by("cuota_nro", "id"))
            for idx, c in enumerate(cuotas):
                c.fecha_vencimiento = fecha_ini + relativedelta(months=idx)
                c.save(update_fields=["fecha_vencimiento"])
            resumen["cuotas_actualizadas"] = len(cuotas)

        # ── 4) Registrar la tarea completada (para el reporte diario) ─────
        TareaCompletada.objects.create(
            tipo="datos_poliza",
            oficina_id=poliza.oficina_id or _oficina_del_user(user),
            usuario=user if getattr(user, "is_authenticated", False) else None,
            poliza_id=poliza.id,
        )

        return Response({"ok": True, "poliza_id": poliza.id, "resumen": resumen})