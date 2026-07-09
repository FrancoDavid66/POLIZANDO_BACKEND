# scripts/seed_recordatorios_test.py
from datetime import timedelta
from decimal import Decimal
from django.apps import apps
from django.utils import timezone
from django.db import transaction

PHONE = "1164235336"
N = 5
DELTAS = [3, 0, -3, -7, -14, -30]
HOY = timezone.localdate()

Poliza = apps.get_model("polizas", "Poliza")
Cuota = apps.get_model("pagos", "Cuota")
Cliente = Poliza._meta.get_field("cliente").related_model


def set_if_exists(d, model, field, value):
    if any(f.name == field for f in model._meta.fields):
        d[field] = value


def clone_model_fields(instance, model, exclude=()):
    data = {}
    for f in model._meta.fields:
        if f.primary_key:
            continue
        if f.name in exclude:
            continue
        data[f.name] = getattr(instance, f.name)
    return data


@transaction.atomic
def seed():
    created = {"clientes": 0, "polizas": 0, "cuotas": 0}

    # Limpieza previa (solo TEST)
    if any(f.name == "patente" for f in Poliza._meta.fields):
        test_polizas = Poliza.objects.filter(patente__startswith="TEST")
        Cuota.objects.filter(poliza__in=test_polizas).delete()
        test_polizas.delete()

    if any(f.name == "nombre" for f in Cliente._meta.fields):
        Cliente.objects.filter(nombre__startswith="Cliente Test").delete()

    template_poliza = Poliza.objects.order_by("-id").first()
    template_cuota = Cuota.objects.order_by("-id").first()

    if not template_poliza:
        raise RuntimeError(
            "No encontré ninguna Póliza existente para clonar. Creá 1 póliza real y reintentá."
        )
    if not template_cuota:
        raise RuntimeError(
            "No encontré ninguna Cuota existente para clonar. Creá 1 cuota real y reintentá."
        )

    for i in range(1, N + 1):
        # --- Cliente
        cli_data = {}
        set_if_exists(cli_data, Cliente, "nombre", f"Cliente Test {i}")
        set_if_exists(cli_data, Cliente, "apellido", f"WhatsApp {i}")
        set_if_exists(cli_data, Cliente, "whatsapp", PHONE)
        set_if_exists(cli_data, Cliente, "telefono", PHONE)
        set_if_exists(cli_data, Cliente, "telefono_alt", PHONE)
        set_if_exists(cli_data, Cliente, "celular", PHONE)

        # Completar campos requeridos mínimos si existieran
        for f in Cliente._meta.fields:
            if f.primary_key:
                continue
            if f.name in cli_data:
                continue
            if f.has_default() or f.default is not None or getattr(f, "null", False) or getattr(f, "blank", False):
                continue
            t = f.get_internal_type()
            if t in ("CharField", "TextField", "EmailField"):
                val = f"TEST_{f.name}_{i}"
                maxlen = getattr(f, "max_length", None)
                cli_data[f.name] = val[:maxlen] if maxlen else val
            elif t == "BooleanField":
                cli_data[f.name] = False
            elif t in ("IntegerField", "BigIntegerField", "SmallIntegerField", "PositiveIntegerField", "PositiveSmallIntegerField"):
                cli_data[f.name] = 1

        cliente = Cliente.objects.create(**cli_data)
        created["clientes"] += 1

        # --- Póliza (clonamos para cumplir campos requeridos)
        pol_data = clone_model_fields(template_poliza, Poliza, exclude=("id", "pk", "cliente"))
        pol_data["cliente"] = cliente

        set_if_exists(pol_data, Poliza, "patente", f"TEST{i:02d}AAA")
        set_if_exists(pol_data, Poliza, "numero_poliza", f"TEST-POL-{HOY.strftime('%Y%m%d')}-{i:02d}")
        set_if_exists(pol_data, Poliza, "oficina", "1")  # cambiá a "2"/"3" si querés probar por oficina

        poliza = Poliza.objects.create(**pol_data)
        created["polizas"] += 1

        # --- Cuotas (una por delta exacto)
        for d in DELTAS:
            vto = HOY + timedelta(days=d)
            cu_data = clone_model_fields(
                template_cuota,
                Cuota,
                exclude=("id", "pk", "poliza", "fecha_vencimiento", "pagado", "importe"),
            )

            cu_data["poliza"] = poliza
            set_if_exists(cu_data, Cuota, "pagado", False)
            set_if_exists(cu_data, Cuota, "fecha_vencimiento", vto)
            set_if_exists(cu_data, Cuota, "importe", Decimal("1234.56") + Decimal(i))

            Cuota.objects.create(**cu_data)
            created["cuotas"] += 1

    return created


res = seed()
print("OK:", res)
print("HOY:", HOY)
print("Deltas:", DELTAS)
print("Fechas:", [(d, (HOY + timedelta(days=d)).isoformat()) for d in DELTAS])
