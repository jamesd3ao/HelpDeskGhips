
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import check_password_hash
from mesa.db import get_db

auth_bp = Blueprint('auth', __name__)

def get_user_by_username(username):
    db = get_db()
    return db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()

@auth_bp.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        u = get_user_by_username(username)
        if u and check_password_hash(u['password_hash'], password):
            session['user_id'] = u['id']
            session['role'] = u['role']
            flash(f"Bienvenido, {u['display_name'] or u['username']}!", 'success')
            return redirect(url_for('tickets.dashboard'))
        flash('Credenciales inválidas.', 'danger')
    return render_template('auth/login.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('Sesión cerrada.', 'info')
    return redirect(url_for('auth.login'))
