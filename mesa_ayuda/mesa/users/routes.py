# mesa/users/routes.py
from flask import Blueprint, render_template, redirect, url_for, flash, session, request
from werkzeug.security import generate_password_hash
from datetime import datetime
from mesa.db import get_db

users_bp = Blueprint('users', __name__)

# =========================
# Helpers de sesión/roles
# =========================
def current_user():
    """Devuelve el usuario logueado (Row) o None."""
    db = get_db()
    uid = session.get('user_id')
    if not uid:
        return None
    return db.execute(
        "SELECT id, username, display_name, role, firma_img FROM users WHERE id=?",
        (uid,)
    ).fetchone()

def login_required(f):
    """Redirige a login si no hay sesión."""
    from functools import wraps
    @wraps(f)
    def w(*a, **kw):
        if not current_user():
            flash('Debes iniciar sesión.', 'warning')
            return redirect(url_for('auth.login', next=request.path))
        return f(*a, **kw)
    return w

def admin_required(f):
    """Exige rol admin; si no, redirige al dashboard de tickets."""
    from functools import wraps
    @wraps(f)
    def w(*a, **kw):
        u = current_user()
        if not u or u['role'] != 'admin':
            flash('No tienes permiso.', 'danger')
            return redirect(url_for('tickets.dashboard'))
        return f(*a, **kw)
    return w

# =========================
# Usuarios: Lista
# =========================
@users_bp.route('/', methods=['GET'], endpoint='usuarios')
@login_required
@admin_required
def usuarios_index():
    db = get_db()
    usuarios = db.execute(
        "SELECT id, username, display_name, role, created_at FROM users ORDER BY id DESC"
    ).fetchall()
    return render_template('users/usuarios.html', usuarios=usuarios, user=current_user())

# =========================
# Usuarios: Crear
# =========================
@users_bp.route('/crear', methods=['GET', 'POST'], endpoint='crear_usuario')
@login_required
@admin_required
def crear_usuario():
    db = get_db()
    ROLES = ['admin', 'usuario']  # Alineado con CHECK de la BD

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        display_name = (request.form.get('display_name') or '').strip()
        password = (request.form.get('password') or '').strip()
        role = (request.form.get('role') or 'usuario').strip()

        # Validaciones básicas
        if not username or not password:
            flash('Usuario y contraseña son obligatorios.', 'warning')
            return render_template('users/crear.html', roles=ROLES, form=request.form)

        if role not in ROLES:
            flash('Rol inválido.', 'danger')
            return render_template('users/crear.html', roles=ROLES, form=request.form)

        if len(password) < 4:
            flash('La contraseña debe tener al menos 4 caracteres.', 'warning')
            return render_template('users/crear.html', roles=ROLES, form=request.form)

        # Unicidad de username
        existe = db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone()
        if existe:
            flash('El nombre de usuario ya existe.', 'danger')
            return render_template('users/crear.html', roles=ROLES, form=request.form)

        # Guardar
        pwd_hash = generate_password_hash(password)
        created_at = datetime.utcnow().isoformat()  # evita NOT NULL en created_at
        db.execute(
            "INSERT INTO users (username, password_hash, display_name, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (username, pwd_hash, display_name, role, created_at)
        )
        db.commit()
        flash('Usuario creado correctamente.', 'success')
        return redirect(url_for('users.usuarios'))

    # GET
    return render_template('users/crear.html', roles=ROLES)

# =========================
# Usuarios: Editar
# =========================
@users_bp.route('/<int:user_id>/editar', methods=['GET', 'POST'], endpoint='editar_usuario')
@login_required
@admin_required
def editar_usuario(user_id):
    db = get_db()

    # Traer usuario a editar
    usr = db.execute(
        "SELECT id, username, display_name, role FROM users WHERE id=?",
        (user_id,)
    ).fetchone()
    if not usr:
        flash('Usuario no encontrado.', 'danger')
        return redirect(url_for('users.usuarios'))

    ROLES = ['admin', 'usuario']  # Alineado con CHECK de la BD

    if request.method == 'POST':
        display_name = (request.form.get('display_name') or '').strip()
        role = (request.form.get('role') or 'usuario').strip()
        password = (request.form.get('password') or '').strip()

        # Validar rol
        if role not in ROLES:
            flash('Rol inválido.', 'danger')
            return render_template('users/editar.html', usr=usr, roles=ROLES, form=request.form)

        # No dejar el sistema sin admin
        if usr['role'] == 'admin' and role != 'admin':
            n_admins = db.execute("SELECT COUNT(*) AS c FROM users WHERE role='admin'").fetchone()['c']
            if n_admins <= 1:
                flash('No puedes quitar el rol admin al último administrador.', 'danger')
                return render_template('users/editar.html', usr=usr, roles=ROLES, form=request.form)

        # Cambio de password (opcional)
        set_password = None
        if password:
            if len(password) < 4:
                flash('La contraseña debe tener al menos 4 caracteres.', 'warning')
                return render_template('users/editar.html', usr=usr, roles=ROLES, form=request.form)
            set_password = generate_password_hash(password)

        # Actualizar
        if set_password:
            db.execute(
                "UPDATE users SET display_name=?, role=?, password_hash=? WHERE id=?",
                (display_name, role, set_password, user_id)
            )
        else:
            db.execute(
                "UPDATE users SET display_name=?, role=? WHERE id=?",
                (display_name, role, user_id)
            )
        db.commit()

        flash('Usuario actualizado correctamente.', 'success')
        return redirect(url_for('users.usuarios'))

    # GET
    return render_template('users/editar.html', usr=usr, roles=ROLES)

# =========================
# Usuarios: Eliminar
# =========================
@users_bp.route('/<int:user_id>/eliminar', methods=['POST'], endpoint='eliminar_usuario')
@login_required
@admin_required
def eliminar_usuario(user_id):
    db = get_db()
    u = current_user()

    # No puedes eliminarte a ti mismo
    if u and u['id'] == user_id:
        flash('No puedes eliminar tu propio usuario.', 'danger')
        return redirect(url_for('users.usuarios'))

    target = db.execute(
        "SELECT id, role FROM users WHERE id=?",
        (user_id,)
    ).fetchone()
    if not target:
        flash('Usuario no encontrado.', 'danger')
        return redirect(url_for('users.usuarios'))

    # No eliminar al último admin
    if target['role'] == 'admin':
        n_admins = db.execute("SELECT COUNT(*) AS c FROM users WHERE role='admin'").fetchone()['c']
        if n_admins <= 1:
            flash('No puedes eliminar al último administrador.', 'danger')
            return redirect(url_for('users.usuarios'))

    db.execute("DELETE FROM users WHERE id=?", (user_id,))
    db.commit()
    flash('Usuario eliminado correctamente.', 'success')
    return redirect(url_for('users.usuarios'))

# =========================
# Firma del usuario actual
# =========================
def _valid_sig_dataurl(s: str, min_len: int = 500) -> bool:
    """Valida que sea una dataURL de imagen con longitud mínima."""
    return isinstance(s, str) and s.startswith('data:image') and len(s) >= min_len

@users_bp.route('/perfil/firma', methods=['GET'])
@login_required
def editar_firma_form():
    u = current_user()
    return render_template('users/editar_firma.html', user=u)

@users_bp.route('/perfil/firma', methods=['POST'])
@login_required
def editar_firma_save():
    u = current_user()
    db = get_db()
    firma = (request.form.get('firma_img') or '').strip()

    if not _valid_sig_dataurl(firma):
        flash('Debes dibujar tu firma antes de guardar.', 'warning')
        return redirect(url_for('users.editar_firma_form'))

    db.execute("UPDATE users SET firma_img=? WHERE id=?", (firma, u['id']))
    db.commit()
    flash('Tu firma fue actualizada correctamente.', 'success')
    return redirect(url_for('users.editar_firma_form'))

@users_bp.route('/perfil/firma/borrar', methods=['POST'])
@login_required
def borrar_firma():
    u = current_user()
    db = get_db()
    db.execute("UPDATE users SET firma_img=NULL WHERE id=?", (u['id'],))
    db.commit()
    flash('Tu firma fue eliminada.', 'info')
    return redirect(url_for('users.editar_firma_form'))
