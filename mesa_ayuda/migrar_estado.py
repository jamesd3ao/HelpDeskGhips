# migrar_estado.py
import sqlite3

DB_PATH = r"d:/mesa_ayuda/instance/ticket_app.db"

def run():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Ver columnas actuales
    cur.execute("PRAGMA table_info(tickets)")
    cols = {row[1] for row in cur.fetchall()}

    # Agregar 'estado' si no existe
    if "estado" not in cols:
        cur.execute("ALTER TABLE tickets ADD COLUMN estado TEXT DEFAULT 'abierto';")
        print("✅ Columna 'estado' creada.")
    else:
        print("ℹ️ 'estado' ya existía.")

    # Agregar 'finalizado_at' si no existe
    if "finalizado_at" not in cols:
        cur.execute("ALTER TABLE tickets ADD COLUMN finalizado_at TEXT;")
        print("✅ Columna 'finalizado_at' creada.")
    else:
        print("ℹ️ 'finalizado_at' ya existía.")

    # Asegurar que los registros viejos tengan estado 'abierto'
    cur.execute("UPDATE tickets SET estado='abierto' WHERE estado IS NULL;")
    print("✅ Tickets antiguos con estado NULL → 'abierto'.")

    conn.commit()
    conn.close()
    print("🎉 Migración terminada sin errores.")

if __name__ == "__main__":
    run()