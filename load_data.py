from clientes.models import Cliente, Poliza, Siniestro
from datetime import date, timedelta

clientes = [
    {
        "nombre": "Juan",
        "apellido": "Pérez",
        "dni": "30111222",
        "telefono": "1130001111",
        "estado": True,
        "email": "juan@gmail.com"
    },
    {
        "nombre": "María",
        "apellido": "Gómez",
        "dni": "30222333",
        "telefono": "1140002222",
        "estado": True,
        "email": "maria@gmail.com"
    },
    {
        "nombre": "Carlos",
        "apellido": "Ruiz",
        "dni": "30333444",
        "telefono": "1150003333",
        "estado": False,
        "email": "carlos@gmail.com"
    },
]

for c in clientes:
    cliente = Cliente.objects.create(
        nombre=c["nombre"],
        apellido=c["apellido"],
        telefono=c["telefono"],
        dni_cuit_cuil=c["dni"],
        email=c["email"],
        direccion="Av. Siempre Viva 123",
        fecha_nacimiento=date(1990, 1, 1),
        estado=c["estado"]
    )

    # Primera póliza
    Poliza.objects.create(
        cliente=cliente,
        compania="La Caja",
        numero_poliza=f"POL{cliente.id}XYZ",
        cobertura="Todo Riesgo",
        oficina="Oficina Central",
        patente="AA123BB",
        marca="Toyota",
        modelo="Corolla",
        anio=2020,
        precio_cuota=15000,
        cantidad_cuotas=12,
        saldo_pendiente=0 if cliente.estado else 15000,
        primer_pago=date.today() - timedelta(days=30),
        fecha_pago=date.today() - timedelta(days=1),
        fecha_vencimiento=date.today() + timedelta(days=29 if cliente.estado else -5),
        dias_a_vencer=29 if cliente.estado else -5,
        fecha_emision=date.today(),
        estado=cliente.estado
    )

    # Segunda póliza SOLO para Juan
    if cliente.nombre == "Juan":
        nueva_poliza = Poliza.objects.create(
            cliente=cliente,
            compania="ATM",
            numero_poliza=f"POL{cliente.id}NUEVA",
            cobertura="C Full",
            oficina="Oficina 2 (Axion)",
            patente="BB456CC",
            marca="Ford",
            modelo="Ranger",
            anio=2022,
            precio_cuota=18000,
            cantidad_cuotas=6,
            saldo_pendiente=0,
            primer_pago=date.today() - timedelta(days=60),
            fecha_pago=date.today() - timedelta(days=5),
            fecha_vencimiento=date.today() + timedelta(days=25),
            dias_a_vencer=25,
            fecha_emision=date.today(),
            estado=True
        )

        # Siniestro asociado a la nueva póliza
        Siniestro.objects.create(
            poliza=nueva_poliza,
            lugar="Av. Libertador y Maipú",
            localidad="San Isidro",
            hubo_heridos=True,
            denuncia_presentada=True,
            fecha_denuncia=date.today() - timedelta(days=3),
            fecha_resolucion=None,
            resolucion_final="En revisión",
            monto_pagado=0
        )

print("✅ Clientes, pólizas y siniestro agregados correctamente.")
