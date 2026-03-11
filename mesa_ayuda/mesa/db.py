
import sqlite3, os
from flask import current_app, g
from werkzeug.security import generate_password_hash
from datetime import datetime

SCHEMA_USERS = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  display_name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('admin','usuario')),
  created_at TEXT NOT NULL,
  firma_img TEXT
);
"""

SCHEMA_TICKETS = """
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    fecha_inicio TEXT, fecha_final TEXT, hora_inicio TEXT, hora_final TEXT,
    sede TEXT, ubicacion TEXT,
    soporte_hardware INTEGER DEFAULT 0,
    soporte_Software INTEGER DEFAULT 0,
    soporte_redes INTEGER DEFAULT 0,
    equipo_equipo TEXT, equipo_marca TEXT, equipo_modelo TEXT, equipo_cod_inventario TEXT,
    equipo_coin TEXT, equipo_disco TEXT, equipo_ram TEXT, equipo_procesador TEXT,
    servicio_tipo TEXT, servicio_otro TEXT, falla_asociada TEXT,
    descripcion_solicitud TEXT, descripcion_trabajo TEXT,
    eval_calidad_servicio INTEGER, eval_calidad_informacion INTEGER,
    eval_oportunidad_respuesta INTEGER, eval_actitud_tecnico INTEGER,
    firma_usuario_gestiona_img TEXT, firma_tecnico_mantenimiento_img TEXT,
    firma_logistica_img TEXT, firma_supervisor_img TEXT,
    firma_usuario_gestiona_nombre TEXT, firma_tecnico_mantenimiento_nombre TEXT,
    firma_logistica_nombre TEXT, firma_supervisor_nombre TEXT,
    FOREIGN KEY(created_by) REFERENCES users(id)
);
"""

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
    return g.db

def close_db(_=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def migrate_tickets_columns():
    db = get_db()
    cols = {r['name'] for r in db.execute("PRAGMA table_info('tickets')")}
    defs = {
        'created_by':'INTEGER','created_at':'TEXT',
        'fecha_inicio':'TEXT','fecha_final':'TEXT','hora_inicio':'TEXT','hora_final':'TEXT',
        'sede':'TEXT','ubicacion':'TEXT',
        'soporte_hardware':'INTEGER','soporte_Software':'INTEGER','soporte_redes':'INTEGER',
        'equipo_equipo':'TEXT','equipo_marca':'TEXT','equipo_modelo':'TEXT','equipo_cod_inventario':'TEXT','equipo_coin':'TEXT','equipo_disco':'TEXT','equipo_ram':'TEXT','equipo_procesador':'TEXT',
        'servicio_tipo':'TEXT','servicio_otro':'TEXT','falla_asociada':'TEXT',
        'descripcion_solicitud':'TEXT','descripcion_trabajo':'TEXT',
        'eval_calidad_servicio':'INTEGER','eval_calidad_informacion':'INTEGER','eval_oportunidad_respuesta':'INTEGER','eval_actitud_tecnico':'INTEGER',
        'firma_usuario_gestiona_img':'TEXT','firma_tecnico_mantenimiento_img':'TEXT','firma_logistica_img':'TEXT','firma_supervisor_img':'TEXT',
        'firma_usuario_gestiona_nombre':'TEXT','firma_tecnico_mantenimiento_nombre':'TEXT','firma_logistica_nombre':'TEXT','firma_supervisor_nombre':'TEXT'
    }
    for c, t in defs.items():
        if c not in cols:
            db.execute(f"ALTER TABLE tickets ADD COLUMN {c} {t}")
    db.commit()

def migrate_users():
    db = get_db()
    cols = {r['name'] for r in db.execute("PRAGMA table_info('users')")}
    if 'firma_img' not in cols:
        db.execute("ALTER TABLE users ADD COLUMN firma_img TEXT")
    if 'display_name' not in cols:
        db.execute("ALTER TABLE users ADD COLUMN display_name TEXT")
        db.execute("UPDATE users SET display_name = COALESCE(display_name, username)")
    db.commit()

def init_db():
    os.makedirs(os.path.dirname(current_app.config['DATABASE']), exist_ok=True)
    db = get_db()
    db.executescript(SCHEMA_USERS)
    db.executescript(SCHEMA_TICKETS)
    migrate_tickets_columns()
    migrate_users()
    if db.execute("SELECT COUNT(*) c FROM users").fetchone()['c'] == 0:
        db.execute(
            "INSERT INTO users (username, display_name, password_hash, role, created_at) VALUES (?,?,?,?,?)",
            ('admin','Administrador', generate_password_hash('admin123'),'admin', datetime.utcnow().isoformat())
        )
        db.commit()
