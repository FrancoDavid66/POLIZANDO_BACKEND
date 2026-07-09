# tareas/views_fijas.py
from datetime import datetime, timedelta

from django.db.models import Q, Sum, Count
from django.utils import timezone
from rest_framework import viewsets, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .models_fijas import TareaFija, CumplimientoTareaFija, Feriado, FotoCumplimiento
from .serializers_fijas import TareaFijaSerializer, FeriadoSerializer
from .services_fijas import armar_tareas_fijas_dia
from .buchon_fijas import enviar_foto_cumplimiento, avisar_tarea_cumplida_whatsapp
from usuarios.models import Oficina


# ── helpers de rol / oficina ────────────────────────────────────────────
def _perfil(user):
    return getattr(user, "perfil", None)


def _es_admin(user):
    p = _perfil(user)
    return bool(p and getattr(p, "rol", "") == "ADMIN")


def _oficina_del_user(user):
    p = _perfil(user)
    return getattr(p, "oficina_id", None) if p else None


def _parse_fecha(v):
    if not v:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(v).strip(), fmt).date()
        except Exception:
            continue
    return None


# ── CRUD de tareas fijas (admin las crea/edita) ─────────────────────────
class TareaFijaViewSet(viewsets.ModelViewSet):
    serializer_class = TareaFijaSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = TareaFija.objects.select_related("oficina", "responsable").all()
        u = self.request.user
        if _es_admin(u):
            return qs
        ofi = _oficina_del_user(u)
        # Una oficina ve sus tareas + las globales (sin oficina)
        return qs.filter(Q(oficina_id=ofi) | Q(oficina__isnull=True))


# ── CRUD de feriados ────────────────────────────────────────────────────
class FeriadoViewSet(viewsets.ModelViewSet):
    serializer_class = FeriadoSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = Feriado.objects.all()


# ── Panel del día (empleado: su oficina · admin: todas o ?oficina=) ─────
class TareasFijasDiaView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        u = request.user
        fecha = _parse_fecha(request.query_params.get("fecha")) or timezone.localdate()
        if _es_admin(u):
            oficina_id = request.query_params.get("oficina") or None
        else:
            oficina_id = _oficina_del_user(u)
        data = armar_tareas_fijas_dia(oficina_id=oficina_id, fecha=fecha)
        return Response(data)


# ── Cumplir una tarea (subiendo la foto) ────────────────────────────────
class CumplirTareaFijaView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        u = request.user
        tarea_id = request.data.get("tarea_id")
        if not tarea_id:
            return Response({"detail": "Falta tarea_id."}, status=400)

        tarea = TareaFija.objects.filter(id=tarea_id, activa=True).first()
        if not tarea:
            return Response({"detail": "Tarea no encontrada."}, status=404)

        oficina_id = request.data.get("oficina_id") or _oficina_del_user(u)
        if not oficina_id:
            return Response({"detail": "No se pudo determinar la oficina."}, status=400)

        foto_url = (request.data.get("foto_url") or "").strip()
        if tarea.requiere_foto and not foto_url:
            return Response({"detail": "Esta tarea requiere una foto."}, status=400)

        hoy = timezone.localdate()
        ahora = timezone.localtime()

        # Puntaje según la hora: adelantado +2, a tiempo +1, tarde -1, sin hora +1
        estado_tiempo, puntos = "sin_hora", 1
        if tarea.hora_esperada:
            margen = tarea.margen_alerta or 15
            hora_obj = datetime.combine(hoy, tarea.hora_esperada)
            if timezone.is_naive(hora_obj):
                hora_obj = timezone.make_aware(hora_obj, timezone.get_current_timezone())
            if getattr(tarea, "premia_demora", False):
                # Tarea de cierre: cerrar más tarde = horas extra = más puntos.
                # <30 min → +1 · 30 min a 1h → +1 · 1h → +2 · cada hora más → +1
                demora_min = max(0, int((ahora - hora_obj).total_seconds() // 60))
                if demora_min < 30:
                    estado_tiempo, puntos = "a_tiempo", 1
                else:
                    estado_tiempo, puntos = "extra", (demora_min // 60) + 1
            else:
                limite = hora_obj + timedelta(minutes=margen)
                if ahora <= hora_obj:
                    estado_tiempo, puntos = "adelantado", 2
                elif ahora <= limite:
                    estado_tiempo, puntos = "a_tiempo", 1
                else:
                    estado_tiempo, puntos = "tarde", -1

        # 🆕 Responsable elegido en los chips (un Empleado de la oficina).
        emp_obj = None
        emp_nombre = ""
        emp_id = request.data.get("responsable_empleado_id") or request.data.get("empleado_id")
        if emp_id:
            try:
                from solicitudes.models import Empleado
                emp_obj = Empleado.objects.filter(id=emp_id).first()
                if emp_obj:
                    emp_nombre = emp_obj.nombre
            except Exception:
                emp_obj = None

        # ¿Lo cargó un admin en nombre del responsable, o la persona misma?
        es_admin = _es_admin(u)
        # Si es admin y eligió un empleado distinto, se marca como "cargado por admin".
        cargado_por_admin = bool(es_admin and emp_obj is not None)

        fotos_min = getattr(tarea, "fotos_min", 1) or 1
        fotos_max = getattr(tarea, "fotos_max", 1) or 1

        # El "álbum" del día (uno por tarea/oficina/fecha). Si ya existe, lo reusamos.
        cumpl, _creado = CumplimientoTareaFija.objects.get_or_create(
            tarea=tarea, oficina_id=oficina_id, fecha=hoy,
            defaults={
                "usuario": u if getattr(u, "is_authenticated", False) else None,
                "responsable_empleado": emp_obj,
                "responsable_nombre": emp_nombre,
                "cargado_por_admin": cargado_por_admin,
                "foto_url": foto_url,
                "foto_public_id": (request.data.get("foto_public_id") or "").strip(),
                "estado_tiempo": estado_tiempo,
                "puntos": puntos,
            },
        )

        # El responsable se elige UNA vez (en la primera foto). Si ya estaba, se respeta.
        if _creado:
            pass
        elif emp_obj and not cumpl.responsable_empleado_id:
            cumpl.responsable_empleado = emp_obj
            cumpl.responsable_nombre = emp_nombre
            cumpl.cargado_por_admin = cargado_por_admin
            cumpl.save(update_fields=["responsable_empleado", "responsable_nombre", "cargado_por_admin"])

        # ¿Cuántas fotos lleva ya? (no contar la foto_url vieja para no duplicar)
        n_actual = cumpl.fotos.count()
        if n_actual >= fotos_max:
            return Response({"detail": f"Esta tarea admite hasta {fotos_max} foto(s)."}, status=400)

        # Agregar la foto nueva al álbum.
        FotoCumplimiento.objects.create(
            cumplimiento=cumpl,
            foto_url=foto_url,
            foto_public_id=(request.data.get("foto_public_id") or "").strip(),
            responsable_nombre=emp_nombre or cumpl.responsable_nombre or "",
            cargado_por_admin=cargado_por_admin,
        )
        # Reflejar la primera foto en el cumplimiento (compatibilidad).
        if not cumpl.foto_url:
            cumpl.foto_url = foto_url
            cumpl.save(update_fields=["foto_url"])

        n_fotos = cumpl.fotos.count()
        completa = n_fotos >= fotos_min
        # Los puntos se otorgan UNA sola vez: cuando se alcanza el mínimo.
        otorga_puntos = completa and (n_fotos == fotos_min or (fotos_min == 1 and n_fotos == 1))

        # 🏆 Sumar al ranking global (monedero central de puntos) — solo al completar el mínimo
        if getattr(u, "is_authenticated", False) and puntos and otorga_puntos:
            try:
                from ranking.services import otorgar_puntos
                otorgar_puntos(
                    usuario=u,
                    puntos=puntos,
                    categoria="control_diario",
                    oficina=oficina_id,
                    detalle=f"{tarea.nombre} ({estado_tiempo})",
                    fecha=hoy,
                    ref=f"cd:{tarea.id}:{oficina_id}:{hoy.isoformat()}",
                )
            except Exception:
                pass
        # 🆕 Mandar la foto por email a los 2 destinatarios de siempre
        if foto_url:
            try:
                ofi = Oficina.objects.filter(id=oficina_id).first()
                # Quién la hizo: el responsable elegido; si no, la cuenta que subió.
                cuenta = ""
                if getattr(u, "is_authenticated", False):
                    cuenta = (u.get_full_name() or u.username or "")
                quien = emp_nombre or cuenta or "Alguien"
                # Aclaración si lo cargó el admin en nombre de la persona.
                if cargado_por_admin:
                    quien = f"{quien} (cargado por Admin)"
                hora_txt = timezone.localtime().strftime("%H:%M")
                enviar_foto_cumplimiento(
                    tarea_nombre=tarea.nombre,
                    oficina_nombre=(ofi.nombre if ofi else str(oficina_id)),
                    usuario=quien,
                    foto_url=foto_url,
                    fecha_txt=hoy.strftime("%d/%m/%Y"),
                    hora_txt=hora_txt,
                )
                avisar_tarea_cumplida_whatsapp(
                    tarea_nombre=tarea.nombre,
                    oficina_nombre=(ofi.nombre if ofi else str(oficina_id)),
                    usuario=quien,
                    hora_txt=timezone.localtime().strftime("%d/%m a las %H:%M"),
                    estado_tiempo=estado_tiempo,
                    puntos=puntos,
                )
            except Exception:
                pass

        return Response({
            "ok": True,
            "cumplida": completa,
            "fotos_subidas": n_fotos,
            "fotos_min": fotos_min,
            "fotos_max": fotos_max,
            "puede_sumar": n_fotos < fotos_max,
            "estado_tiempo": estado_tiempo,
            "puntos": puntos if otorga_puntos else 0,
        })


# ── Ranking de puntos por empleado (hoy / semana / mes) ─────────────────
class RankingControlDiarioView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        rango = (request.query_params.get("rango") or "mes").lower()
        hoy = timezone.localdate()
        if rango == "hoy":
            desde = hoy
        elif rango == "semana":
            desde = hoy - timedelta(days=7)
        else:
            rango, desde = "mes", hoy - timedelta(days=30)

        # Ranking global: lo ven todos (todas las oficinas)
        qs = CumplimientoTareaFija.objects.filter(fecha__gte=desde, usuario__isnull=False)

        agg = (qs.values("usuario_id")
                 .annotate(puntos=Sum("puntos"), tareas=Count("id"))
                 .order_by("-puntos"))

        from django.contrib.auth import get_user_model
        User = get_user_model()
        ids = [a["usuario_id"] for a in agg]
        nombres = {
            x.id: (x.get_full_name() or x.username)
            for x in User.objects.filter(id__in=ids)
        }
        ranking = [
            {"usuario": nombres.get(a["usuario_id"], "—"),
             "puntos": a["puntos"] or 0, "tareas": a["tareas"]}
            for a in agg
        ]
        return Response({"rango": rango, "ranking": ranking})