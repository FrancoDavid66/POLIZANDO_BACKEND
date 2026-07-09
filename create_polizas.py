import random
from faker import Faker
from clientes.models import Cliente, Poliza
from datetime import datetime, timedelta

fake = Faker(['es_ES'])

# Parámetros de generación
NUM_POLIZAS = 70
CANTIDAD_CUOTAS_POR_COMPANIA = {
    'Agrosalta': 6,
    'Equidad': 3,
    'Federacion Patronal': 4,
    'Providencia': 3,
}

# Obtener todos los clientes
clientes = list(Cliente.objects.all())
if not clientes:
    print("No hay clientes en la base de datos.")

# Función para generar fecha de vencimiento según el estado
def generar_fecha_vencimiento(estado):
    hoy = datetime.now()
    if estado == "Al día":
        return hoy + timedelta(days=random.randint(8, 30))
    elif estado == "Por vencer":
        return hoy + timedelta(days=random.randint(1, 7))
    elif estado == "Vence hoy":
        return hoy
    elif estado == "Vencida":
        return hoy - timedelta(days=random.randint(1, 30))

for _ in range(NUM_POLIZAS):
    cliente = random.choice(clientes)
    compania = random.choice(list(CANTIDAD_CUOTAS_POR_COMPANIA.keys()))
    numero_poliza = fake.unique.bothify(text='POL-#####-????')
    cobertura = random.choice(['Todo Riesgo', 'Responsabilidad Civil', 'Terceros Completo'])
    oficina = fake.city()
    patente = fake.bothify(text='???###')
    marca = random.choice(['Toyota', 'Ford', 'Chevrolet', 'Honda', 'Fiat'])
    modelo = random.choice(['Corolla', 'Focus', 'Cruze', 'Civic', 'Punto'])
    anio = random.randint(2000, 2025)
    tipo = random.choice(['auto', 'camioneta', 'camion', 'moto'])
    precio_cuota = round(random.uniform(5000, 20000), 2)
    cantidad_cuotas = CANTIDAD_CUOTAS_POR_COMPANIA[compania]
    primer_pago = fake.date_this_decade()
    fecha_pago = primer_pago + timedelta(days=30)
    estado_pago = random.choice(["Al día", "Por vencer", "Vence hoy", "Vencida"])
    fecha_vencimiento = generar_fecha_vencimiento(estado_pago)
    dias_a_vencer = (fecha_vencimiento - datetime.now()).days
    fecha_emision = primer_pago
    estado = random.choice(['activa', 'vencida', 'cancelada'])

    try:
        poliza = Poliza.objects.create(
            cliente=cliente,
            compania=compania,
            numero_poliza=numero_poliza,
            cobertura=cobertura,
            oficina=oficina,
            patente=patente,
            marca=marca,
            modelo=modelo,
            anio=anio,
            tipo=tipo,
            precio_cuota=precio_cuota,
            cantidad_cuotas=cantidad_cuotas,
            primer_pago=primer_pago,
            fecha_pago=fecha_pago,
            fecha_vencimiento=fecha_vencimiento,
            dias_a_vencer=dias_a_vencer,
            fecha_emision=fecha_emision,
            estado=estado
        )
        print(f'✅ Póliza creada: {numero_poliza} para {cliente.nombre} {cliente.apellido} - Estado: {estado_pago}')
    except Exception as e:
        print(f'❌ Error al crear póliza {numero_poliza}: {str(e)}')

print(f'🚀 Se han creado {NUM_POLIZAS} pólizas correctamente.')
