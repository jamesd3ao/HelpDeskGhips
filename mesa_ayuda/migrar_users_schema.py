# migrar_users_schema.py
"""
Script de migración para la tabla 'users' en SQLite.
- Asegura que existan las columnas: password_hash (TEXT) y created_at (TEXT, DEFAULT CURRENT_TIMESTAMP)
- Backfill: rellena password_hash vacío con hash de '1234'
- Backfill: rellena created_at vacío con CURRENT_TIMESTAMP

Uso (PowerShell/CMD):
    python migrar_users_schema.py
"""

import os
import sqlite3
from datetime import datetime

try:
    # Si más adelante cambias la ruta en create_app(), ajusta este path:
    DB_PATH = r"D:\mesa_ayuda\instance\ticket_app.db"

    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"No se encontró la base de datos en: {DB_PATH}")

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("=== Migración de esquema: users ===")
    print(f"DB: {DB_PATH}")

    # 1) Lee columnas actuales
    cols = [r["name"] for r in cur.execute("PRAGMA table_info(users)").fetchall()]
    print("Columnas actuales:", cols)

    # 2) Agrega password_hash si falta
    added_password_hash = False
    if "password_hash" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        added_password_hash = True
        print("✔ Columna 'password_hash' creada.")
    else:
        print("✔ 'password_hash' ya existe.")

    # 3) Agrega created_at si falta (con default automático)
    added_created_at = False
    if "created_at" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP")
        added_created_at = True
        print("✔ Columna 'created_at' creada con DEFAULT CURRENT_TIMESTAMP.")
    else:
        print("✔ 'created_at' ya existe.")

    con.commit()

    # 4) Backfill: password_hash vacío -> poner hash de "1234"
    # Para no depender de Werkzeug aquí, usamos un "marcador simple".
    # RECOMENDADO: Usa el mismo hash que genera tu app con generate_password_hash("1234")
    # Pero como migración de emergencia, ponemos un valor no vacío tipo "LEGACY_1234".
    # Si prefieres el hash real de Werkzeug, comenta este bloque y usa el siguiente con werkzeug.

    # --- Opción A: marcador simple (no recomendado para producción, sí para desbloquear la restricción) ---
    legacy_value = "LEGACY_1234"  # reemplázalo luego desde la app cambiando la contraseña
    cur.execute(
        "UPDATE users SET password_hash=? WHERE password_hash IS NULL OR password_hash=''",
        (legacy_value,)
    )
    affected_pw = cur.rowcount
    con.commit()
    print(f"✔ password_hash vacío actualizado con marcador (LEGACY_1234). Filas afectadas: {affected_pw}")

    # --- Opción B: si quieres usar el hash real de Werkzeug, descomenta:
    """
    try:
        from werkzeug.security import generate_password_hash
        real_hash = generate_password_hash("1234")
        cur.execute(
            "UPDATE users SET password_hash=? WHERE password_hash IS NULL OR password_hash=''",
            (real_hash,)
        )
        affected_pw = cur.rowcount
        con.commit()
        print(f"✔ password_hash vacío actualizado con hash real de '1234'. Filas afectadas: {affected_pw}")
    except Exception as e:
        print("⚠ No se pudo importar werkzeug.security. Se usó marcador simple (LEGACY_1234).", e)
    """

    # 5) Backfill: created_at vacío -> poner CURRENT_TIMESTAMP (o isoformat)
    # Usaremos CURRENT_TIMESTAMP para mantener consistencia con DEFAULT
    cur.execute(
        "UPDATE users SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL OR created_at = ''"
    )
    affected_ca = cur.rowcount
    con.commit()
    print(f"✔ created_at vacío actualizado a CURRENT_TIMESTAMP. Filas afectadas: {affected_ca}")

    # 6) Mostrar un pequeño resumen de 5 usuarios recientes
    print("\n=== Últimos 5 usuarios (verificación) ===")
    for r in cur.execute("SELECT id, username, length(password_hash) AS l, created_at FROM users ORDER BY id DESC LIMIT 5"):
        d = dict(r)
        print(d)

    print("\n✅ Migración finalizada correctamente.")
except Exception as e:
    print("❌ Error en migración:", repr(e))
finally:
    try:
        con.close()
    except Exception:
        pass