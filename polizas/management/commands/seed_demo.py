# polizas/management/commands/seed_demo.py
import random
from decimal import Decimal
from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

from faker import Faker
from dateutil.relativedelta import relativedelta

# Modelos obligatorios
from clientes.models import Cliente
from polizas.models import Poliza, PolizaDocumento, TipoDocumento
from pagos.models import Cuota
# Pago es opcional (lo manejamos con try/except)
try:
    from pagos.models import Pago
    HAS_PAGO = True
except Exception:
    Pago = None
    HAS_PAGO = False

# Constantes de cuotas por compañía (si no están, usamos fallback)
try:
    from polizas.utils.constants import CANTIDAD_CUOTAS_POR_COMPANIA
except Exception:
    CANTIDAD_CUOTAS_POR_COMPANIA = {
        "Sancor": 12, "Federación Patronal": 12, "La Segunda": 12, "Allianz": 12, "San Cristóbal": 12,
        "Mercantil Andina": 12, "RUS": 12, "Mapfre": 12
    }

FAKER = Faker("es_AR")

COMPANIAS = list(CANTIDAD_CUOTAS_POR_COMPANIA.keys()) or [
    "Sancor", "Federación Patronal", "La Segunda", "Allianz", "San Cristóbal", "Mercantil Andina", "RUS", "Mapfre"
]
COBERTURAS = ["RC", "Terceros Completo", "Todo Riesgo", "TC + Granizo"]
TIPOS = ["Auto", "Camioneta", "Camion", "Moto", "Trailer"]
OFICINAS = ["DE THAMES", "SUCURSAL CENTRO", "ONLINE"]

MARCAS_MODELOS = [
    ("Volkswagen", "Gol"), ("Volkswagen", "Amarok"), ("Chevrolet", "Onix"),
    ("Toyota", "Hilux"), ("Toyota", "Corolla"), ("Ford", "Fiesta"),
    ("Renault", "Kangoo"), ("Peugeot", "208"), ("Fiat", "Cronos"),
    ("Honda", "Wave"), ("Yamaha", "FZ"), ("Iveco", "Tector"),
]

def patente_mercosur():
    # Formato nuevo: AA123BB | viejo: ABC123
    if random.random() < 0.6:
        letras1 = FAKER.random_uppercase_letter() + FAKER.random_uppercase_letter()
        numeros = f"{random.randint(0, 999):03d}"
        letras2 = FAKER.random_uppercase_letter() + FAKER.random_uppercase_letter()
        return f"{letras1}{numeros}{letras2}"
    else:
        letras = "".join(FAKER.random_uppercase_letter() for _ in range(3))
        numeros = f"{random.randint(0, 999):03d}"
        return f"{letras}{numeros}"

def dni():
    return str(random.randint(20000000, 50000000))

def cuit_from_dni(dni_str):
    # No exacto: solo estético para demo
    return f"20-{dni_str}-{random.randint(0,9)}"

def precio_cuota_promedio(tipo):
    base = {
        "Auto": 35000, "Camioneta": 50000, "Camion": 90000, "Moto": 12000, "Trailer": 18000
    }.get(tipo, 30000)
    ruido = random.uniform(-0.2, 0.3)
    return int(base * (1 + ruido))

def monto_decimal(n):
    return Decimal(str(round(float(n), 2)))

def dias_a_vencer_desde(fecha_vto):
    hoy = timezone.localdate()
    return (fecha_vto - hoy).days

def crear_cliente():
    nombre = FAKER.first_name()
    apellido = FAKER.last_name()
    d = dni()
    return Cliente.objects.create(
        nombre=nombre,
        apellido=apellido,
        dni_cuit_cuil=cuit_from_dni(d),  # si tu modelo guarda DNI CUIT, sirve igual para demo
        email=FAKER.ascii_free_email(),
        telefono=FAKER.phone_number()[:20],
        direccion=FAKER.address(),
    )

def crear_documentos_demo(poliza: Poliza):
    # 40% VTV, 25% OBLEA_GNC, 60% Póliza PDF
    hoy = timezone.localdate()
    docs = []
    if random.random() < 0.4:
        docs.append((TipoDocumento.VTV, hoy + relativedelta(months=random.randint(-6, 14))))
    if random.random() < 0.25:
        docs.append((TipoDocumento.OBLEA_GNC, hoy + relativedelta(months=random.randint(-6, 14))))
    if random.random() < 0.6:
        docs.append((TipoDocumento.SEGURO_POLIZA, None))

    for tipo, vto in docs:
        PolizaDocumento.objects.create(
            poliza=poliza,
            tipo=tipo,
            url="https://example.com/doc.pdf",
            nombre=f"{tipo} {poliza.patente}",
            mime="application/pdf",
            vencimiento=vto,
            notas="Documento demo",
        )

def crear_poliza(cliente: Cliente, target_bucket=None) -> Poliza:
    # target_bucket: fuerza crear mora en el bucket deseado para balancear KPIs
    compania = random.choice(COMPANIAS)
    marca, modelo = random.choice(MARCAS_MODELOS)
    tipo = random.choice(TIPOS)
    anio = random.randint(2005, 2025)
    pcuota = precio_cuota_promedio(tipo)
    cant_cuotas = int(CANTIDAD_CUOTAS_POR_COMPANIA.get(compania, 12)) or 12

    # Fechas base
    hoy = timezone.localdate()
    fecha_emision = hoy - relativedelta(months=random.randint(0, 18))
    primer_pago = (fecha_emision + relativedelta(months=1)).replace(day=min(fecha_emision.day, 28))

    # Buckets: al_dia | mora_1_30 | mora_31_60 | mora_61_90 | mora_90_mas
    if target_bucket is None:
        target_bucket = random.choices(
            population=["al_dia", "mora_1_30", "mora_31_60", "mora_61_90", "mora_90_mas"],
            weights=[45, 18, 14, 12, 11],
            k=1
        )[0]

    if target_bucket == "al_dia":
        overdue_anchor = None
    elif target_bucket == "mora_1_30":
        overdue_anchor = hoy - timedelta(days=random.randint(1, 30))
    elif target_bucket == "mora_31_60":
        overdue_anchor = hoy - timedelta(days=random.randint(31, 60))
    elif target_bucket == "mora_61_90":
        overdue_anchor = hoy - timedelta(days=random.randint(61, 90))
    else:
        overdue_anchor = hoy - timedelta(days=random.randint(91, 200))

    # Crear la póliza primero (fecha_vencimiento = última cuota)
    fecha_vencimiento = primer_pago + relativedelta(months=cant_cuotas - 1)
    poliza = Poliza.objects.create(
        cliente=cliente,
        compania=compania,
        numero_poliza=f"{compania[:3].upper()}-{FAKER.unique.random_number(digits=8)}",
        cobertura=random.choice(COBERTURAS),
        oficina=random.choice(OFICINAS),
        patente=patente_mercosur(),
        marca=marca,
        modelo=modelo,
        anio=anio,
        tipo=tipo,
        precio_cuota=monto_decimal(pcuota),
        cantidad_cuotas=cant_cuotas,
        primer_pago=primer_pago,
        fecha_vencimiento=fecha_vencimiento,
        dias_a_vencer=dias_a_vencer_desde(fecha_vencimiento),
        fecha_emision=fecha_emision,
        estado="activa" if fecha_vencimiento >= hoy else "vencida",
        alertas="",
    )

    # Crear cuotas
    cuotas = []
    impaga_colocada = False
    for n in range(1, cant_cuotas + 1):
        vto = primer_pago + relativedelta(months=n - 1)
        pagado = True
        fecha_pago = None

        if overdue_anchor:
            # Si esta cuota es en/antes del anchor, dejamos al menos una impaga
            if vto <= overdue_anchor and not impaga_colocada:
                pagado = False
                impaga_colocada = True
            elif vto < hoy and random.random() < 0.25:
                pagado = False
        else:
            # al_dia: cuotas vencidas pagadas; futuras impagas
            if vto < hoy:
                pagado = random.random() < 0.95
            else:
                pagado = False

        if pagado and vto <= hoy:
            fecha_pago = vto + timedelta(days=random.randint(-3, 10))

        c = Cuota.objects.create(
            poliza=poliza,
            cuota_nro=n,
            fecha_vencimiento=vto,
            pagado=pagado,
            fecha_pago=fecha_pago,
            monto=monto_decimal(pcuota),
        )
        cuotas.append(c)

        # Crear pago (opcional) cuando está instalado y tiene sentido
        if HAS_PAGO and pagado and random.random() < 0.85:
            try:
                Pago.objects.create(
                    cuota=c,
                    monto=c.monto,
                    fecha=fecha_pago or vto,
                    medio="Transferencia",
                    registrado_en_balance=False,
                )
            except Exception:
                # Si el modelo Pago tiene otros obligatorios, lo saltamos silenciosamente
                pass

    # Ajuste de estado "cancelada" o "finalizada" pequeños porcentajes
    roll = random.random()
    if roll < 0.06:
        poliza.estado = "cancelada"
        poliza.fecha_baja = hoy - timedelta(days=random.randint(1, 120))
        poliza.motivo_baja = random.choice([
            "INCUMPLIMIENTO_PAGO", "MIGRACION_COMPANIA", "VENTA_VEHICULO", "SIN_USO", "OTRO"
        ])
        poliza.observaciones_baja = "Baja demo"
        poliza.save(update_fields=["estado", "fecha_baja", "motivo_baja", "observaciones_baja"])
    elif roll < 0.10:
        poliza.estado = "finalizada"
        poliza.save(update_fields=["estado"])

    # Algunos documentos
    crear_documentos_demo(poliza)
    return poliza

class Command(BaseCommand):
    help = "Genera datos ficticios de clientes, pólizas, cuotas y pagos (opcional) para demo/pruebas."

    def add_arguments(self, parser):
        parser.add_argument("--clientes", type=int, default=100, help="Cantidad de clientes a crear (default 100)")
        parser.add_argument("--polizas", type=int, default=200, help="Cantidad total aproximada de pólizas (default 200)")
        parser.add_argument("--min-polizas-por-cliente", type=int, default=0, help="Mínimo de pólizas por cliente (default 0)")
        parser.add_argument("--max-polizas-por-cliente", type=int, default=3, help="Máximo de pólizas por cliente (default 3)")
        parser.add_argument("--sin-pagos", action="store_true", help="No crear objetos Pago (solo cuotas)")

    def handle(self, *args, **opts):
        from django.db.models import Count, Q

        clientes_n = max(1, int(opts["clientes"]))
        polizas_target = max(0, int(opts["polizas"]))
        min_ppc = max(0, int(opts["min_polizas_por_cliente"]))
        max_ppc = max(min_ppc, int(opts["max_polizas_por_cliente"]))
        sin_pagos = bool(opts["sin_pagos"])
        global HAS_PAGO
        if sin_pagos:
            HAS_PAGO = False

        self.stdout.write(self.style.NOTICE(">>> Generando datos demo…"))

        # 1) Clientes
        clientes = []
        for _ in range(clientes_n):
            clientes.append(crear_cliente())
        self.stdout.write(self.style.SUCCESS(f"✓ Clientes creados: {len(clientes)}"))

        # 2) Pólizas distribuidas
        total_polizas = 0
        buckets = ["al_dia", "mora_1_30", "mora_31_60", "mora_61_90", "mora_90_mas"]
        bucket_idx = 0

        for cli in clientes:
            cant = random.randint(min_ppc, max_ppc)
            if polizas_target and total_polizas + cant > polizas_target:
                cant = max(0, polizas_target - total_polizas)
            for _ in range(cant):
                target_bucket = buckets[bucket_idx % len(buckets)]
                crear_poliza(cli, target_bucket=target_bucket)
                bucket_idx += 1
            total_polizas += cant
            if polizas_target and total_polizas >= polizas_target:
                break

        self.stdout.write(self.style.SUCCESS(f"✓ Pólizas creadas: {total_polizas}"))
        self.stdout.write(self.style.SUCCESS("✓ Cuotas y pagos (si aplica) generados"))
        self.stdout.write(self.style.SUCCESS("✓ Documentos de póliza creados (parcial)"))

        # ---------- RESUMEN FINAL (exacto desde la BD) ----------
        total_clientes = Cliente.objects.count()
        total_polizas_db = Poliza.objects.count()
        estados = dict(Poliza.objects.values_list("estado").annotate(c=Count("id")))

        total_cuotas = Cuota.objects.count()
        cuotas_pagadas = Cuota.objects.filter(pagado=True).count()
        cuotas_impagas = total_cuotas - cuotas_pagadas

        total_docs = PolizaDocumento.objects.count()
        docs_por_tipo = dict(PolizaDocumento.objects.values_list("tipo").annotate(c=Count("id")))

        if HAS_PAGO and Pago:
            total_pagos = Pago.objects.count()
        else:
            total_pagos = 0

        prom_cuotas_por_poliza = round(total_cuotas / total_polizas_db, 2) if total_polizas_db else 0.0

        self.stdout.write(self.style.NOTICE("\n>>> Resumen de lo generado"))
        self.stdout.write(f"  • Clientes: {total_clientes}")
        self.stdout.write(
            "  • Pólizas: {0} (por estado: {1})".format(
                total_polizas_db,
                ", ".join(f"{k or '-'}={v}" for k, v in estados.items()) or "—"
            )
        )
        self.stdout.write(
            f"  • Cuotas: {total_cuotas}  |  Pagadas: {cuotas_pagadas}  |  Impagas: {cuotas_impagas}  |  Promedio/póliza: {prom_cuotas_por_poliza}"
        )
        if HAS_PAGO and Pago:
            self.stdout.write(f"  • Pagos: {total_pagos}")
        else:
            self.stdout.write("  • Pagos: (no se crearon porque --sin-pagos o modelo no disponible)")

        self.stdout.write(f"  • Documentos: {total_docs}")
        if docs_por_tipo:
            self.stdout.write("     - Por tipo: " + ", ".join(f"{k}={v}" for k, v in docs_por_tipo.items()))
        self.stdout.write(self.style.NOTICE("\n>>> Listo. Podés probar filtros y KPIs."))
