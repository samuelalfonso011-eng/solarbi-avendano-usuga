import psycopg2
import os

try:
    conn = psycopg2.connect(
        host="localhost",
        port="5432",
        dbname="postgres",
        user="postgres",
        password="Samuel1304"
    )
    conn.autocommit = True
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM pg_database WHERE datname = 'solarbi'")
    if not cursor.fetchone():
        cursor.execute("CREATE DATABASE solarbi")
        print("Base de datos 'solarbi' creada exitosamente.")
    else:
        print("La base de datos 'solarbi' ya existe.")
    
    cursor.close()
    conn.close()

    conn_solar = psycopg2.connect(
        host="localhost",
        port="5432",
        dbname="solarbi",
        user="postgres",
        password="Samuel1304"
    )
    conn_solar.autocommit = True
    cursor_solar = conn_solar.cursor()
    with open("sql/tables.sql", "rb") as f:
        sql = f.read().decode('cp1252', errors='ignore')
    cursor_solar.execute(sql)
    print("Tablas creadas exitosamente.")
    cursor_solar.close()
    conn_solar.close()

except Exception as e:
    print(f"Error: {e}")
