# limpiar_db.py
import os
import django

# 1. Configuramos el entorno de Django para poder usar la base de datos
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'seguros_project.settings')
django.setup()

from django.db import connection

def limpiar_datos_huerfanos():
    print("Iniciando limpieza de base de datos antes de migrar...")
    try:
        with connection.cursor() as cursor:
            # Limpiamos las coberturas inválidas
            cursor.execute("""
                UPDATE polizas_poliza 
                SET cobertura_obj_id = NULL 
                WHERE cobertura_obj_id NOT IN (SELECT id FROM cotizaciones_tipocobertura);
            """)
            
            # Limpiamos las compañías inválidas
            cursor.execute("""
                UPDATE polizas_poliza 
                SET compania_obj_id = NULL 
                WHERE compania_obj_id NOT IN (SELECT id FROM cotizaciones_companiaseguro);
            """)
        print("¡Limpieza completada con éxito!")
    except Exception as e:
        print(f"Ocurrió un error durante la limpieza: {e}")

if __name__ == '__main__':
    limpiar_datos_huerfanos()