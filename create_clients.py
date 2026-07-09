import random
from faker import Faker
from clientes.models import Cliente

fake = Faker(['es_ES'])

# Cantidad de clientes a generar
NUM_CLIENTES = 50

estados = [True, False]  # Activo o Inactivo

for _ in range(NUM_CLIENTES):
    nombre = fake.first_name()
    apellido = fake.last_name()
    telefono = fake.phone_number()
    email = fake.email()
    dni_cuit_cuil = fake.random_number(digits=8)
    direccion = fake.address()
    fecha_nacimiento = fake.date_of_birth(minimum_age=18, maximum_age=80)
    estado = random.choice(estados)

    cliente = Cliente(
        nombre=nombre,
        apellido=apellido,
        telefono=telefono,
        email=email,
        dni_cuit_cuil=str(dni_cuit_cuil),
        direccion=direccion,
        fecha_nacimiento=fecha_nacimiento,
        estado=estado
    )
    cliente.save()
    print(f'Cliente creado: {nombre} {apellido}')

print(f'Se han creado {NUM_CLIENTES} clientes correctamente.')
