# C:\mesa_ayuda\admin.py
import sqlite3
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash

DB_PATH = r"C:\mesa_ayuda\instance\ticket_app.db"

username = "admin"
plain_password = "admin123"   # cámbiala luego en la app
display_name = "Administrador"
role = "admin"

created_iso_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
pwd_hash = generate_password_hash(plain_password, method="pbkdf2:sha256")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# ¿Existe ya el usuario?
cur.execute("SELECT id FROM users WHERE username = ?", (username,))
row = cur.fetchone()

if row:
    # Actualizar contraseña, y opcionalmente display_name/role
    cur.execute("""
        UPDATE users
        SET password_hash = ?, display_name = ?, role = ?
        WHERE username = ?
    """, (pwd_hash, display_name, role, username))
    print(f"Contraseña ACTUALIZADA para '{username}'.")
else:
    # Insertar nuevo admin
    cur.execute("""
        INSERT INTO users (username, display_name, password_hash, role, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (username, display_name, pwd_hash, role, created_iso_utc))
    print(f"Usuario '{username}' CREADO.")

conn.commit()
conn.close()

print("Listo. Puedes iniciar sesión con:", username, "/", plain_password)