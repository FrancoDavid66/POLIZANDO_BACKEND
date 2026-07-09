# tareas/alertas_fijas.py
#
# Revisa las tareas fijas con HORA esperada que ya pasaron su margen (15 min
# por defecto) y NO se cumplieron, y manda un WhatsApp de alerta a los 2 números.
# Pensado para correr cada pocos minutos desde un cron (management command).

import os
from datetime import datetime, timedelta

from django.utils import timezone

from usuarios.models import Oficina
from .models_fijas import (
    TareaFija, CumplimientoTareaFija, AlertaTareaFijaEnviada, Feriado,
)
from .buchon_fijas import WHATSAPP_CONTROL_DIARIO, _oficina_con_whatsapp

# Margen en minutos después de la hora esperada (ej: 9:00 → avisa a las 9:15)
MARGEN_MIN = int(os.environ.get("MARGEN_ALERTA_CONTROL_DIARIO", "15"))


def chequear_alertas_control_diario(ahora=None) -> dict:
    ahora = ahora or timezone.localtime()
    hoy = ahora.date()

    # En feriado no se esperan tareas → no se alerta
    if Feriado.objects.filter(fecha=hoy).exists():
        return {"enviadas": 0, "feriado": True}

    # Tareas activas, que apliquen hoy y que tengan hora esperada
    tareas = [
        t for t in TareaFija.objects.filter(activa=True)
        if t.hora_esperada and t.aplica_en(hoy)
    ]
    if not tareas:
        return {"enviadas": 0}

    oficinas = list(Oficina.objects.filter(activa=True))
    cumplidos = set(
        CumplimientoTareaFija.objects.filter(fecha=hoy).values_list("tarea_id", "oficina_id")
    )
    avisadas = set(
        AlertaTareaFijaEnviada.objects.filter(fecha=hoy).values_list("tarea_id", "oficina_id")
    )

    try:
        from notificaciones.utils.mensajeria import enviar_whatsapp
    except Exception:
        enviar_whatsapp = None

    ofi_wa = _oficina_con_whatsapp()
    enviadas = 0

    for t in tareas:
        # Límite = hora esperada + margen propio de la tarea (o el global)
        margen = t.margen_alerta or MARGEN_MIN
        limite = datetime.combine(hoy, t.hora_esperada) + timedelta(minutes=margen)
        if timezone.is_naive(limite):
            limite = timezone.make_aware(limite, timezone.get_current_timezone())
        if ahora < limite:
            continue  # todavía no se pasó del margen

        # Oficinas a las que aplica (las suyas, o todas si es global)
        ofis = oficinas if t.oficina_id is None else [o for o in oficinas if o.id == t.oficina_id]
        for o in ofis:
            if (t.id, o.id) in cumplidos:
                continue  # ya la hicieron
            if (t.id, o.id) in avisadas:
                continue  # ya avisamos hoy

            hora_txt = t.hora_esperada.strftime("%H:%M")
            msg = (
                f"🚨 *Control diario* — {o.nombre}\n"
                f"No subieron la foto de: *{t.nombre}* ({hora_txt})\n"
                f"Ya pasaron {margen} min y sigue sin hacerse."
            )
            if enviar_whatsapp and WHATSAPP_CONTROL_DIARIO:
                for numero in WHATSAPP_CONTROL_DIARIO:
                    try:
                        enviar_whatsapp(numero, msg, oficina=ofi_wa)
                    except Exception:
                        pass

            AlertaTareaFijaEnviada.objects.get_or_create(tarea=t, oficina=o, fecha=hoy)
            enviadas += 1

    return {"enviadas": enviadas}