# tareas/management/commands/seed_tareas_basicas.py
#
# Carga TODAS las tareas básicas del Control diario, con los horarios reales de
# cada sucursal (y el cierre distinto de los sábados).
#
#   python manage.py seed_tareas_basicas
#
# Es idempotente: si lo corrés de nuevo, actualiza (no duplica).
#
# Días: lunes=0, martes=1, miércoles=2, jueves=3, viernes=4, sábado=5
#   Lun-Vie="0,1,2,3,4"  Lun-Sáb="0,1,2,3,4,5"  Sáb="5"
#   Limpieza (mar/jue/sáb)="1,3,5"   Basura (mar/vie)="1,4"

from django.core.management.base import BaseCommand
from usuarios.models import Oficina
from tareas.models_fijas import TareaFija

# keyword para encontrar la oficina (búsqueda flexible) + horarios
CONFIG = [
    {"key": "talita",   "abrir": "09:00", "carteles": "09:15", "cerrar_lv": "18:00", "cerrar_sab": "17:00"},
    {"key": "kilometro", "abrir": "09:00", "carteles": "09:15", "cerrar_lv": "18:00", "cerrar_sab": "17:00"},
    {"key": "axion",    "abrir": "09:00", "carteles": "09:15", "cerrar_lv": "18:00", "cerrar_sab": "17:00"},
    {"key": "esquinas", "abrir": "08:00", "carteles": "08:15", "cerrar_lv": "19:00", "cerrar_sab": "19:00"},
]

LUN_SAB = "0,1,2,3,4,5"
LUN_VIE = "0,1,2,3,4"
SABADO = "5"
LIMPIEZA = "1,3,5"   # martes, jueves, sábado
BASURA = "1,4"       # martes, viernes


class Command(BaseCommand):
    help = "Crea las tareas básicas del Control diario con los horarios de cada oficina."

    def _crear(self, oficina, nombre, hora, dias, orden, premia_demora=False, foto="la oficina", margen=15, fotos_min=1, fotos_max=1):
        TareaFija.objects.update_or_create(
            nombre=nombre,
            oficina=oficina,
            defaults={
                "frecuencia": "semanal",
                "dias_semana": dias,
                "hora_esperada": hora,
                "margen_alerta": margen,
                "requiere_foto": True,
                "instruccion_foto": foto,
                "premia_demora": premia_demora,
                "activa": True,
                "orden": orden,
                "fotos_min": fotos_min,
                "fotos_max": fotos_max,
            },
        )

    def handle(self, *args, **options):
        creadas = 0
        for cfg in CONFIG:
            ofi = Oficina.objects.filter(nombre__icontains=cfg["key"]).first()
            if not ofi:
                self.stdout.write(self.style.WARNING(f"  ⚠ No encontré oficina '{cfg['key']}'"))
                continue

            mismo_cierre = cfg["cerrar_lv"] == cfg["cerrar_sab"]

            # 1) Abrir (lun a sáb)
            self._crear(ofi, "Abrir la oficina", cfg["abrir"], LUN_SAB, 0,
                        premia_demora=False, foto="la cortina/persiana abierta")
            creadas += 1

            # 1b) Apagar los reflectores (al abrir)
            self._crear(ofi, "Apagar los reflectores", cfg["abrir"], LUN_SAB, 2,
                        premia_demora=False,
                        foto="los reflectores apagados y la llave de luz apagada", margen=30)
            creadas += 1

            # 2) Sacar los carteles a la ruta (15 min después de abrir)
            self._crear(ofi, "Sacar los carteles a la ruta", cfg["carteles"], LUN_SAB, 1,
                        premia_demora=False, foto="los 3 carteles (uno por foto)", margen=15,
                        fotos_min=3, fotos_max=3)
            creadas += 1

            # 3) Limpiar la oficina (martes, jueves y sábados, 10 a 12)
            self._crear(ofi, "Limpiar la oficina", "10:00", LIMPIEZA, 5,
                        premia_demora=False, foto="baño, pisos, escritorios y vidriera", margen=120,
                        fotos_min=4, fotos_max=10)
            creadas += 1

            # 4) Encender reflectores (todos los días que cierran, a la hora de cierre)
            if mismo_cierre:
                self._crear(ofi, "Encender reflectores", cfg["cerrar_lv"], LUN_SAB, 8,
                            premia_demora=False, foto="los reflectores encendidos", margen=60)
                creadas += 1
            else:
                self._crear(ofi, "Encender reflectores (Lun a Vie)", cfg["cerrar_lv"], LUN_VIE, 8,
                            premia_demora=False, foto="los reflectores encendidos", margen=60)
                self._crear(ofi, "Encender reflectores (Sábado)", cfg["cerrar_sab"], SABADO, 9,
                            premia_demora=False, foto="los reflectores encendidos", margen=60)
                creadas += 2

            # 5) Cerrar la oficina (a su hora; cerrar tarde = horas extra)
            if mismo_cierre:
                self._crear(ofi, "Cerrar la oficina", cfg["cerrar_lv"], LUN_SAB, 10,
                            premia_demora=True, foto="la oficina cerrada")
                creadas += 1
            else:
                self._crear(ofi, "Cerrar la oficina (Lun a Vie)", cfg["cerrar_lv"], LUN_VIE, 10,
                            premia_demora=True, foto="la oficina cerrada")
                self._crear(ofi, "Cerrar la oficina (Sábado)", cfg["cerrar_sab"], SABADO, 11,
                            premia_demora=True, foto="la oficina cerrada")
                creadas += 2

            # 6) Cambiar la basura de los tachos (martes y viernes, al cerrar)
            self._crear(ofi, "Cambiar la basura de los tachos", cfg["cerrar_lv"], BASURA, 12,
                        premia_demora=False, foto="los tachos vacíos", margen=60)
            creadas += 1

            self.stdout.write(f"  · {ofi.nombre}: tareas cargadas")

        self.stdout.write(self.style.SUCCESS(f"Listo. {creadas} tareas creadas/actualizadas."))