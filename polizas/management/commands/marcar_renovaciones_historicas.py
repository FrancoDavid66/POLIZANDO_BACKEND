# polizas/management/commands/marcar_renovaciones_historicas.py
#
# 🚀 Uso:
#   python manage.py marcar_renovaciones_historicas              # dry-run (no toca nada)
#   python manage.py marcar_renovaciones_historicas --apply      # aplica los cambios
#   python manage.py marcar_renovaciones_historicas --apply --solo-poliza-origen  # solo las que ya tienen FK
#
# Estrategia:
#   1) Marca como es_renovacion=True a toda póliza que tenga poliza_origen seteado.
#   2) Detecta renovaciones encubiertas por PATENTE REPETIDA del mismo cliente:
#      si el cliente tiene 2+ pólizas con la misma patente normalizada, la más
#      antigua queda como alta y las posteriores se marcan como renovación
#      (y se linkea poliza_origen hacia la inmediata anterior).

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from polizas.models import Poliza


def _norm_patente(p: str) -> str:
    if not p:
        return ""
    return "".join(c for c in p.upper() if c.isalnum())


class Command(BaseCommand):
    help = "Marca pólizas históricas como es_renovacion=True usando poliza_origen y patente repetida."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Aplicar los cambios. Sin esta flag corre en dry-run.",
        )
        parser.add_argument(
            "--solo-poliza-origen",
            action="store_true",
            help="Solo marcar las que ya tienen poliza_origen seteado (no detectar por patente).",
        )

    def handle(self, *args, **opts):
        apply_changes = bool(opts.get("apply"))
        solo_fk = bool(opts.get("solo_poliza_origen"))

        modo = "APLICANDO CAMBIOS" if apply_changes else "DRY-RUN (no toca nada)"
        self.stdout.write(self.style.WARNING(f"\n=== {modo} ===\n"))

        # ─────────────────────────────────────────────────────────
        # 1) Por poliza_origen (las que ya están linkeadas)
        # ─────────────────────────────────────────────────────────
        qs_con_origen = Poliza.objects.filter(
            poliza_origen__isnull=False,
            es_renovacion=False,
        )
        count_origen = qs_con_origen.count()
        self.stdout.write(f"[1/2] Pólizas con poliza_origen pero es_renovacion=False: {count_origen}")

        if apply_changes and count_origen > 0:
            with transaction.atomic():
                qs_con_origen.update(es_renovacion=True)
            self.stdout.write(self.style.SUCCESS(f"   ✅ {count_origen} pólizas marcadas como renovación."))

        if solo_fk:
            self.stdout.write(self.style.NOTICE("\n--solo-poliza-origen activado, salteo detección por patente."))
            return

        # ─────────────────────────────────────────────────────────
        # 2) Detección por patente repetida del mismo cliente
        # ─────────────────────────────────────────────────────────
        self.stdout.write("\n[2/2] Detectando renovaciones encubiertas por patente repetida del mismo cliente...")

        # Agrupamos por (cliente_id, patente_normalizada) y vemos cuáles tienen 2+
        grupos = {}
        polizas_con_patente = (
            Poliza.objects
            .exclude(patente__isnull=True)
            .exclude(patente__exact="")
            .exclude(patente__exact="-")
            .values("id", "cliente_id", "patente", "fecha_emision", "es_renovacion", "poliza_origen_id")
            .order_by("cliente_id", "fecha_emision", "id")
        )

        for p in polizas_con_patente:
            key = (p["cliente_id"], _norm_patente(p["patente"]))
            grupos.setdefault(key, []).append(p)

        candidatas = []  # lista de (poliza_id, origen_id)
        for key, items in grupos.items():
            if len(items) < 2:
                continue
            # La más vieja queda como alta, el resto como renovaciones
            # encadenadas (cada una apunta a la inmediata anterior).
            for i in range(1, len(items)):
                actual = items[i]
                anterior = items[i - 1]
                # Si ya está marcada y linkeada, salteamos
                if actual["es_renovacion"] and actual["poliza_origen_id"]:
                    continue
                candidatas.append({
                    "id": actual["id"],
                    "origen_id": anterior["id"],
                    "ya_marcada": actual["es_renovacion"],
                    "ya_linkeada": bool(actual["poliza_origen_id"]),
                    "cliente_id": actual["cliente_id"],
                    "patente": actual["patente"],
                })

        self.stdout.write(f"   Candidatas detectadas: {len(candidatas)}")

        if not candidatas:
            self.stdout.write(self.style.SUCCESS("\n✅ Sin cambios adicionales por patente."))
            return

        # Mostrar primeras 10 como sample
        self.stdout.write("\n   Muestra (primeras 10):")
        for c in candidatas[:10]:
            self.stdout.write(
                f"     · Póliza #{c['id']} (cliente={c['cliente_id']}, patente={c['patente']}) "
                f"→ origen=#{c['origen_id']}"
            )

        if not apply_changes:
            self.stdout.write(self.style.NOTICE(
                f"\n⚠️  DRY-RUN. Re-ejecutá con --apply para aplicar {len(candidatas)} cambios."
            ))
            return

        # Aplicar
        marcadas = 0
        linkeadas = 0
        with transaction.atomic():
            for c in candidatas:
                update_fields = []
                pol = Poliza.objects.get(id=c["id"])
                if not pol.es_renovacion:
                    pol.es_renovacion = True
                    update_fields.append("es_renovacion")
                    marcadas += 1
                if not pol.poliza_origen_id:
                    pol.poliza_origen_id = c["origen_id"]
                    update_fields.append("poliza_origen")
                    linkeadas += 1
                if update_fields:
                    pol.save(update_fields=update_fields)

        self.stdout.write(self.style.SUCCESS(
            f"\n✅ Marcadas como renovación: {marcadas}"
            f"\n✅ Linkeadas con poliza_origen: {linkeadas}"
        ))