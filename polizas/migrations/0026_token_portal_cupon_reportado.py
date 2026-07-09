# polizas/migrations/XXXX_token_portal_cupon_reportado.py
#
# Agrega:
#  - token_portal (UUID único) en Poliza  → para el link público /cupon/<token>
#  - estado REPORTADO + campo reportado_en en CuponRobo
#
# ⚠️ ANTES DE CORRER: cambiá "REEMPLAZAR_ULTIMA_MIGRACION" (abajo) por el nombre
#    del último archivo de polizas/migrations/ (el de número más alto, sin el .py).
#    Ej: si el último es "0042_algo.py", poné "0042_algo".

import uuid
from django.db import migrations, models


def poblar_tokens(apps, schema_editor):
    """Le da un token único a cada póliza que ya existe (sin colisiones)."""
    Poliza = apps.get_model("polizas", "Poliza")
    for p in Poliza.objects.filter(token_portal__isnull=True).iterator():
        p.token_portal = uuid.uuid4()
        p.save(update_fields=["token_portal"])


class Migration(migrations.Migration):

    dependencies = [
        ("polizas", "0025_poliza_poliza_enviada_poliza_poliza_enviada_en"),
    ]

    operations = [
        # 1) Token primero NULLABLE (para poder poblar sin chocar con unique)
        migrations.AddField(
            model_name="poliza",
            name="token_portal",
            field=models.UUIDField(null=True, editable=False, db_index=True),
        ),
        # 2) Genera un UUID distinto por cada póliza existente
        migrations.RunPython(poblar_tokens, migrations.RunPython.noop),
        # 3) Ahora sí: unique + default para las nuevas
        migrations.AlterField(
            model_name="poliza",
            name="token_portal",
            field=models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True),
        ),
        # 4) CuponRobo: nuevo estado REPORTADO
        migrations.AlterField(
            model_name="cuponrobo",
            name="estado",
            field=models.CharField(
                max_length=10,
                choices=[
                    ("PENDIENTE", "Pendiente"),
                    ("REPORTADO", "Reportado por el cliente"),
                    ("PAGADA", "Pagada"),
                    ("VENCIDA", "Vencida"),
                ],
                default="PENDIENTE",
                db_index=True,
            ),
        ),
        # 5) CuponRobo: campo reportado_en
        migrations.AddField(
            model_name="cuponrobo",
            name="reportado_en",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]