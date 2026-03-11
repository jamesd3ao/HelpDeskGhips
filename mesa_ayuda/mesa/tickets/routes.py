# -*- coding: utf-8 -*-
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, session, send_file, abort, current_app, jsonify
)
from datetime import datetime, timezone
from io import BytesIO, StringIO
import zipfile
import csv
import re
import os
from zoneinfo import ZoneInfo

from mesa.db import get_db
from mesa.pdf_utils import render_ticket_pdf
from utils.mail import send_mail_with_pdf

# ------------------ Zona horaria ------------------
DEFAULT_TZ = ZoneInfo("America/Bogota")

def iso_to_bogota_str(iso_str: str, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Convierte ISO (UTC o naive) a string local Bogotá."""
    if not iso_str:
        return "-"
    try:
        s = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(DEFAULT_TZ).strftime(fmt)
    except Exception:
        return iso_str[:19].replace('T', ' ')

# =====================================================
# Helpers de firmas (SignaturePad)
# =====================================================
def _valid_sig_dataurl(s: str, min_len: int = 500) -> bool:
    """True si es una firma dibujada tipo dataURL."""
    return isinstance(s, str) and s.strip().startswith('data:image') and len(s.strip()) >= min_len

def _valid_sig_any(s: str, min_len: int = 500) -> bool:
    """
    True si hay firma válida:
      - dataURL de SignaturePad (data:image..., largo mínimo), o
      - archivo subido servido desde /static (ruta 'static/...').
    """
    if not isinstance(s, str):
        return False
    s = s.strip()
    return (s.startswith('data:image') and len(s) >= min_len) or s.startswith('static/')

def _has_any_signature_of_interest(ticket_like: dict) -> bool:
    """True si hay al menos UNA firma válida (usuario, técnico o logística)."""
    imgs = [
        (ticket_like.get("firma_usuario_gestiona_img") or "").strip(),
        (ticket_like.get("firma_tecnico_mantenimiento_img") or "").strip(),
        (ticket_like.get("firma_logistica_img") or "").strip(),
    ]
    return any(_valid_sig_any(x) for x in imgs)

def _signatures_changed(prev_imgs: dict, new_imgs_raw: dict) -> bool:
    """True si alguna firma válida se agregó o cambió respecto a lo previo (solo dataURL para detectar “nuevo dibujo”)."""
    def _changed(prev: str, new: str) -> bool:
        return _valid_sig_dataurl(new) and (new or "").strip() != (prev or "").strip()
    return (
        _changed((prev_imgs.get('usuario') or ''),   (new_imgs_raw.get('usuario') or '')) or
        _changed((prev_imgs.get('tecnico') or ''),   (new_imgs_raw.get('tecnico') or '')) or
        _changed((prev_imgs.get('logistica') or ''), (new_imgs_raw.get('logistica') or ''))
    )

# =====================================================
# Blueprint
# =====================================================
tickets_bp = Blueprint('tickets', __name__)  # sin url_prefix

# =====================================================
# Helpers auth / usuario
# =====================================================
def current_user():
    db = get_db()
    uid = session.get('user_id')
    if not uid:
        return None
    return db.execute(
        "SELECT id, username, display_name, role, firma_img FROM users WHERE id=?",
        (uid,)
    ).fetchone()

def login_required(f):
    from functools import wraps
    @wraps(f)
    def _wrap(*a, **kw):
        if not current_user():
            flash('Debes iniciar sesión.', 'warning')
            return redirect(url_for('auth.login', next=request.path))
        return f(*a, **kw)
    return _wrap

# =====================================================
# Helpers tickets
# =====================================================
def row_get(row, key, default=None):
    """Acceso seguro a sqlite3.Row (no tiene .get())."""
    try:
        return row[key] if key in row.keys() else default
    except Exception:
        return default

def load_ticket(ticket_id: int):
    db = get_db()
    return db.execute("""
        SELECT t.*, u.display_name AS creador
        FROM tickets t
        JOIN users u ON t.created_by = u.id
        WHERE t.id=?
    """, (ticket_id,)).fetchone()

def update_ticket(ticket_id: int, fields: dict):
    if not fields:
        return
    db = get_db()
    cols = ", ".join([f"{k}=?" for k in fields.keys()])
    vals = list(fields.values()) + [ticket_id]
    db.execute(f"UPDATE tickets SET {cols} WHERE id=?", vals)
    db.commit()

# =====================================================
# Dashboard (por defecto HOY, zona Bogotá)
# =====================================================
@tickets_bp.route('/', methods=['GET'], endpoint='dashboard')
@login_required
def tickets_dashboard():
    db = get_db()
    u = current_user()

    def _today_local_str():
        return datetime.now(DEFAULT_TZ).strftime("%Y-%m-%d")

    f1 = (request.args.get('f1') or '').strip()
    f2 = (request.args.get('f2') or '').strip()

    if not f1 and not f2:
        f1 = f2 = _today_local_str()
    elif f1 and not f2:
        f2 = f1
    elif f2 and not f1:
        f1 = f2

    ok = lambda s: bool(re.match(r'^\d{4}-\d{2}-\d{2}$', s or ''))
    if not (ok(f1) and ok(f2)):
        f1 = f2 = _today_local_str()

    f_inicio, f_fin = sorted([f1, f2])

    try:
        page = max(1, int(request.args.get('page', 1)))
    except Exception:
        page = 1
    try:
        per_page = min(200, max(10, int(request.args.get('per_page', 50))))
    except Exception:
        per_page = 50
    offset = (page - 1) * per_page

    where = "substr(t.created_at, 1, 10) BETWEEN ? AND ?"
    params = [f_inicio, f_fin]

    if u['role'] != 'admin':
        where += " AND t.created_by = ?"
        params.append(u['id'])

    rows = db.execute(f"""
        SELECT t.*, u.display_name AS creador
        FROM tickets t
        JOIN users u ON t.created_by = u.id
        WHERE {where}
        ORDER BY t.created_at DESC
        LIMIT ? OFFSET ?
    """, params + [per_page, offset]).fetchall()

    total = db.execute(f"""
        SELECT COUNT(*) AS c
        FROM tickets t
        WHERE {where}
    """, params).fetchone()['c']

    pages = (total + per_page - 1) // per_page

    tickets_local = []
    for r in rows:
        d = dict(r)
        d['created_local'] = iso_to_bogota_str(d.get('created_at'))
        tickets_local.append(d)

    return render_template(
        'tickets/dashboard.html',
        tickets=tickets_local, user=u,
        f1=f_inicio, f2=f_fin,
        page=page, pages=pages, per_page=per_page, total=total
    )

# =====================================================
# Crear
# =====================================================
@tickets_bp.route('/crear', methods=['GET', 'POST'], endpoint='crear_ticket')
@login_required
def tickets_crear():
    db = get_db()
    u = current_user()
    MAX_DESC_SOLICITUD = 600
    MAX_DESC_TRABAJO = 600

    def _limit_text(s, max_len):
        s = (s or '').strip()
        return (s[:max_len], True) if len(s) > max_len else (s, False)

    if request.method == 'POST':
        def to_bool(n): return 1 if request.form.get(n) == '1' else 0
        def to_int_1_5(v):
            try:
                i = int(v);  return i if 1 <= i <= 5 else None
            except Exception:
                return None

        # Fechas y horas
        fecha_inicio = request.form.get('fecha_inicio', '')
        fecha_final  = request.form.get('fecha_final', '')
        hora_inicio  = request.form.get('hora_inicio', '')
        hora_final   = request.form.get('hora_final', '')

        # Sede/Ubicación
        sede = (request.form.get('sede') or '').strip()
        ubicacion = (request.form.get('ubicacion') or '').strip()

        # Soporte
        soporte_hardware = to_bool('soporte_hardware')
        soporte_Software = to_bool('soporte_Software')
        soporte_redes    = to_bool('soporte_redes')

        # Equipo
        equipo_equipo = (request.form.get('equipo_equipo') or '').strip()
        equipo_marca = (request.form.get('equipo_marca') or '').strip()
        equipo_modelo = (request.form.get('equipo_modelo') or '').strip()
        equipo_cod_inventario = (request.form.get('equipo_cod_inventario') or '').strip()
        equipo_coin = (request.form.get('equipo_coin') or '').strip()
        equipo_disco = (request.form.get('equipo_disco') or '').strip()
        equipo_ram = (request.form.get('equipo_ram') or '').strip()
        equipo_procesador = (request.form.get('equipo_procesador') or '').strip()

        # Servicio
        servicio_tipo = (request.form.get('servicio_tipo') or '').strip()
        servicio_otro = (request.form.get('servicio_otro') or '').strip()
        falla_asociada = (request.form.get('falla_asociada') or '').strip()

        # Descripciones
        descripcion_solicitud, _ = _limit_text(request.form.get('descripcion_solicitud',''), MAX_DESC_SOLICITUD)
        descripcion_trabajo, _   = _limit_text(request.form.get('descripcion_trabajo',''),   MAX_DESC_TRABAJO)

        # Validación: descripcion_solicitud obligatorio
        if not descripcion_solicitud.strip():
            flash('La descripción del servicio es obligatoria.', 'danger')
            return render_template('tickets/crear.html', t=request.form, mode='create', submit_token=request.form.get('submit_token', ''))

        # Evaluaciones
        eval_calidad_servicio      = to_int_1_5(request.form.get('eval_calidad_servicio'))
        eval_calidad_informacion   = to_int_1_5(request.form.get('eval_calidad_informacion'))
        eval_oportunidad_respuesta = to_int_1_5(request.form.get('eval_oportunidad_respuesta'))
        eval_actitud_tecnico       = to_int_1_5(request.form.get('eval_actitud_tecnico'))

        # Blindaje: técnico (desde perfil)
        firma_tecnico_mantenimiento_nombre = (u['display_name'] or u['username'])
        firma_tecnico_mantenimiento_img = (u['firma_img'] or '')

        # Otras firmas (dataURL o PNG)
        firma_usuario_gestiona_img = (request.form.get('firma_usuario_gestiona_img') or '').strip()
        firma_logistica_img        = (request.form.get('firma_logistica_img') or '').strip()
        firma_supervisor_img       = (request.form.get('firma_supervisor_img') or '').strip()

        # Nombres de firmas (no obligatorios para considerar “firmó”)
        firma_usuario_gestiona_nombre = (request.form.get('firma_usuario_gestiona_nombre') or '').strip()
        # Nombre de logística: fijo si no llega
        firma_logistica_nombre        = (request.form.get('firma_logistica_nombre') or '').strip() or "Logística"
        firma_supervisor_nombre       = (request.form.get('firma_supervisor_nombre') or '').strip()

        # SELLAR EN CREAR SOLO SI HAY FIRMA (imagen)
        if (not fecha_final) and (not hora_final):
            if any(_valid_sig_any(x) for x in [
                firma_usuario_gestiona_img,
                firma_tecnico_mantenimiento_img,
                firma_logistica_img
            ]):
                now = datetime.now(DEFAULT_TZ)
                fecha_final = now.strftime("%Y-%m-%d")
                hora_final  = now.strftime("%H:%M")

        # INSERT
        columns = [
            'created_by','created_at',
            'fecha_inicio','fecha_final','hora_inicio','hora_final',
            'sede','ubicacion',
            'soporte_hardware','soporte_Software','soporte_redes',
            'equipo_equipo','equipo_marca','equipo_modelo','equipo_cod_inventario','equipo_coin','equipo_disco','equipo_ram','equipo_procesador',
            'servicio_tipo','servicio_otro','falla_asociada',
            'descripcion_solicitud','descripcion_trabajo',
            'eval_calidad_servicio','eval_calidad_informacion','eval_oportunidad_respuesta','eval_actitud_tecnico',
            'firma_usuario_gestiona_img','firma_tecnico_mantenimiento_img','firma_logistica_img','firma_supervisor_img',
            'firma_usuario_gestiona_nombre','firma_tecnico_mantenimiento_nombre','firma_logistica_nombre','firma_supervisor_nombre',
            'estado'
        ]

        values = (
            u['id'], datetime.now(DEFAULT_TZ).isoformat(),
            fecha_inicio, fecha_final, hora_inicio, hora_final,
            sede, ubicacion,
            soporte_hardware, soporte_Software, soporte_redes,
            equipo_equipo, equipo_marca, equipo_modelo, equipo_cod_inventario, equipo_coin, equipo_disco, equipo_ram, equipo_procesador,
            servicio_tipo, servicio_otro, falla_asociada,
            descripcion_solicitud, descripcion_trabajo,
            eval_calidad_servicio, eval_calidad_informacion, eval_oportunidad_respuesta, eval_actitud_tecnico,
            firma_usuario_gestiona_img, firma_tecnico_mantenimiento_img, firma_logistica_img, firma_supervisor_img,
            firma_usuario_gestiona_nombre, firma_tecnico_mantenimiento_nombre, firma_logistica_nombre, firma_supervisor_nombre,
            'abierto'
        )

        placeholders = ','.join(['?'] * len(columns))
        db.execute(f"INSERT INTO tickets ({', '.join(columns)}) VALUES ({placeholders})", values)
        db.commit()
        tid = db.execute('SELECT last_insert_rowid() AS id').fetchone()['id']

        flash('Ticket creado correctamente.', 'success')
        return redirect(url_for('tickets.ver_ticket', ticket_id=tid))

    # GET
    user_firma_img = (u['firma_img'] if u and 'firma_img' in u.keys() else None)
    return render_template(
        'tickets/crear.html',
        mode='create', user=u, user_firma_img=user_firma_img,
        MAX_DESC_SOLICITUD=MAX_DESC_SOLICITUD, MAX_DESC_TRABAJO=MAX_DESC_TRABAJO
    )

# =====================================================
# Editar
# =====================================================
@tickets_bp.route('/<int:ticket_id>/editar', methods=['GET', 'POST'], endpoint='editar_ticket')
@login_required
def tickets_editar(ticket_id):
    db = get_db()
    u = current_user()
    t = db.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
    if not t:
        flash('Ticket no encontrado.', 'danger')
        return redirect(url_for('tickets.dashboard'))

    if u['role'] != 'admin' and t['created_by'] != u['id']:
        flash('No tienes permisos para editar este ticket.', 'danger')
        return redirect(url_for('tickets.dashboard'))

    if t['estado'] == 'finalizado':
        flash('Este ticket está finalizado y no puede editarse.', 'warning')
        return redirect(url_for('tickets.ver_ticket', ticket_id=ticket_id))

    MAX_DESC_SOLICITUD = 600
    MAX_DESC_TRABAJO = 600

    def _limit_text(s, max_len):
        s = (s or '').strip()
        return (s[:max_len], True) if len(s) > max_len else (s, False)

    def to_bool(n): return 1 if request.form.get(n) == '1' else 0
    def to_int_1_5(v):
        try:
            i = int(v);  return i if 1 <= i <= 5 else None
        except Exception:
            return None

    if request.method == 'POST':
        # Fechas/horas
        fecha_inicio = request.form.get('fecha_inicio', '')
        fecha_final  = request.form.get('fecha_final', '')
        hora_inicio  = request.form.get('hora_inicio', '')
        hora_final   = request.form.get('hora_final', '')

        # Sede/ubicación
        sede = (request.form.get('sede') or '').strip()
        ubicacion = (request.form.get('ubicacion') or '').strip()

        # Soporte
        soporte_hardware = to_bool('soporte_hardware')
        soporte_Software = to_bool('soporte_Software')
        soporte_redes    = to_bool('soporte_redes')

        # Equipo
        equipo_equipo = (request.form.get('equipo_equipo') or '').strip()
        equipo_marca = (request.form.get('equipo_marca') or '').strip()
        equipo_modelo = (request.form.get('equipo_modelo') or '').strip()
        equipo_cod_inventario = (request.form.get('equipo_cod_inventario') or '').strip()
        equipo_coin = (request.form.get('equipo_coin') or '').strip()
        equipo_disco = (request.form.get('equipo_disco') or '').strip()
        equipo_ram = (request.form.get('equipo_ram') or '').strip()
        equipo_procesador = (request.form.get('equipo_procesador') or '').strip()

        # Servicio
        servicio_tipo = (request.form.get('servicio_tipo') or '').strip()
        servicio_otro = (request.form.get('servicio_otro') or '').strip()
        falla_asociada = (request.form.get('falla_asociada') or '').strip()

        # Descripciones
        descripcion_solicitud, _ = _limit_text(request.form.get('descripcion_solicitud',''), MAX_DESC_SOLICITUD)
        descripcion_trabajo, _   = _limit_text(request.form.get('descripcion_trabajo',''),   MAX_DESC_TRABAJO)

        # Evaluación
        eval_calidad_servicio      = to_int_1_5(request.form.get('eval_calidad_servicio'))
        eval_calidad_informacion   = to_int_1_5(request.form.get('eval_calidad_informacion'))
        eval_oportunidad_respuesta = to_int_1_5(request.form.get('eval_oportunidad_respuesta'))
        eval_actitud_tecnico       = to_int_1_5(request.form.get('eval_actitud_tecnico'))

        # Firmas nuevas (RAW: lo que viene del form)
        firma_tecnico_mantenimiento_img_new = (request.form.get('firma_tecnico_mantenimiento_img') or '').strip()
        firma_usuario_gestiona_img_new      = (request.form.get('firma_usuario_gestiona_img') or '').strip()
        firma_logistica_img_new             = (request.form.get('firma_logistica_img') or '').strip()
        firma_supervisor_img_new            = (request.form.get('firma_supervisor_img') or '').strip()

        # Nombres (con defecto para logística)
        firma_tecnico_mantenimiento_nombre = (request.form.get('firma_tecnico_mantenimiento_nombre') or '').strip()
        firma_usuario_gestiona_nombre      = (request.form.get('firma_usuario_gestiona_nombre') or '').strip()
        firma_logistica_nombre             = (request.form.get('firma_logistica_nombre') or '').strip() or "Logística"
        firma_supervisor_nombre            = (request.form.get('firma_supervisor_nombre') or '').strip()

        # Firmas actuales (en DB antes del POST)
        t_curr = db.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()

        # Si NO es admin, no cambia firma de técnico
        if u['role'] != 'admin':
            firma_tecnico_mantenimiento_nombre = t_curr['firma_tecnico_mantenimiento_nombre']
            firma_tecnico_mantenimiento_img = t_curr['firma_tecnico_mantenimiento_img']
        else:
            firma_tecnico_mantenimiento_img = (
                firma_tecnico_mantenimiento_img_new
                if _valid_sig_any(firma_tecnico_mantenimiento_img_new)
                else t_curr['firma_tecnico_mantenimiento_img']
            )
            if not firma_tecnico_mantenimiento_nombre:
                firma_tecnico_mantenimiento_nombre = t_curr['firma_tecnico_mantenimiento_nombre']

        # Otras firmas (conserva si no es válida)
        firma_usuario_gestiona_img = (
            firma_usuario_gestiona_img_new if _valid_sig_any(firma_usuario_gestiona_img_new)
            else t_curr['firma_usuario_gestiona_img']
        )
        firma_logistica_img = (
            firma_logistica_img_new if _valid_sig_any(firma_logistica_img_new)
            else t_curr['firma_logistica_img']
        )
        firma_supervisor_img = (
            firma_supervisor_img_new if _valid_sig_any(firma_supervisor_img_new)
            else t_curr['firma_supervisor_img']
        )

        # Si alguna firma válida (dataURL nueva) se agrega o cambia -> sellar fecha/hora final
        prev_imgs = {
            'usuario':   row_get(t_curr, 'firma_usuario_gestiona_img', ''),
            'tecnico':   row_get(t_curr, 'firma_tecnico_mantenimiento_img', ''),
            'logistica': row_get(t_curr, 'firma_logistica_img', ''),
        }
        new_imgs_raw = {
            'usuario':   firma_usuario_gestiona_img_new,
            'tecnico':   firma_tecnico_mantenimiento_img_new,
            'logistica': firma_logistica_img_new,
        }
        if _signatures_changed(prev_imgs, new_imgs_raw):
            now = datetime.now(DEFAULT_TZ)
            fecha_final = now.strftime("%Y-%m-%d")
            hora_final  = now.strftime("%H:%M")

        # Persistir cambios
        db.execute(
            """
            UPDATE tickets SET
              fecha_inicio=?, fecha_final=?, hora_inicio=?, hora_final=?,
              sede=?, ubicacion=?,
              soporte_hardware=?, soporte_Software=?, soporte_redes=?,
              equipo_equipo=?, equipo_marca=?, equipo_modelo=?, equipo_cod_inventario=?, equipo_coin=?, equipo_disco=?, equipo_ram=?, equipo_procesador=?,
              servicio_tipo=?, servicio_otro=?, falla_asociada=?,
              descripcion_solicitud=?, descripcion_trabajo=?,
              eval_calidad_servicio=?, eval_calidad_informacion=?, eval_oportunidad_respuesta=?, eval_actitud_tecnico=?,
              firma_usuario_gestiona_img=?, firma_tecnico_mantenimiento_img=?, firma_logistica_img=?, firma_supervisor_img=?,
              firma_usuario_gestiona_nombre=?, firma_tecnico_mantenimiento_nombre=?, firma_logistica_nombre=?, firma_supervisor_nombre=?
            WHERE id=?
            """,
            (
              fecha_inicio, fecha_final, hora_inicio, hora_final,
              sede, ubicacion,
              soporte_hardware, soporte_Software, soporte_redes,
              equipo_equipo, equipo_marca, equipo_modelo, equipo_cod_inventario, equipo_coin, equipo_disco, equipo_ram, equipo_procesador,
              servicio_tipo, servicio_otro, falla_asociada,
              descripcion_solicitud, descripcion_trabajo,
              eval_calidad_servicio, eval_calidad_informacion, eval_oportunidad_respuesta, eval_actitud_tecnico,
              firma_usuario_gestiona_img, firma_tecnico_mantenimiento_img, firma_logistica_img, firma_supervisor_img,
              firma_usuario_gestiona_nombre, firma_tecnico_mantenimiento_nombre, firma_logistica_nombre, firma_supervisor_nombre,
              ticket_id
            )
        )
        db.commit()
        flash('Ticket actualizado correctamente.', 'success')
        return redirect(url_for('tickets.ver_ticket', ticket_id=ticket_id))

    # GET
    user_firma_img = (u['firma_img'] if u and 'firma_img' in u.keys() else None)
    return render_template(
        'tickets/crear.html',
        mode='edit', t=t, user=u, user_firma_img=user_firma_img,
        MAX_DESC_SOLICITUD=MAX_DESC_SOLICITUD, MAX_DESC_TRABAJO=MAX_DESC_TRABAJO
    )

# =====================================================
# Ver / Eliminar
# =====================================================
@tickets_bp.route('/<int:ticket_id>', methods=['GET'], endpoint='ver_ticket')
@login_required
def tickets_ver(ticket_id):
    u = current_user()
    t = load_ticket(ticket_id)
    if not t:
        flash('Ticket no encontrado.', 'danger')
        return redirect(url_for('tickets.dashboard'))
    if u['role'] != 'admin' and t['created_by'] != u['id']:
        flash('No tienes permisos para ver este ticket.', 'danger')
        return redirect(url_for('tickets.dashboard'))
    return render_template('tickets/ver.html', t=t, user=u)

@tickets_bp.route('/<int:ticket_id>/eliminar', methods=['POST'], endpoint='eliminar_ticket')
@login_required
def tickets_eliminar(ticket_id):
    db = get_db()
    u = current_user()

    t = db.execute("SELECT id, created_by, estado FROM tickets WHERE id=?",
                   (ticket_id,)).fetchone()
    if not t:
        flash('Ticket no encontrado.', 'danger')
        return redirect(request.referrer or url_for('tickets.dashboard'))

    es_admin = (u and u['role'] == 'admin')
    es_creador = (u and t['created_by'] == u['id'])
    esta_finalizado = (t['estado'] == 'finalizado')

    if not es_admin:
        if not es_creador:
            flash('Solo el creador puede eliminar este ticket.', 'danger')
            return redirect(request.referrer or url_for('tickets.dashboard'))
        if esta_finalizado:
            flash('No puedes eliminar un ticket finalizado.', 'warning')
            return redirect(request.referrer or url_for('tickets.dashboard'))

    db.execute("DELETE FROM tickets WHERE id=?", (ticket_id,))
    db.commit()

    flash('Ticket eliminado correctamente.', 'success')
    return redirect(request.referrer or url_for('tickets.dashboard'))

# =====================================================
# PDF
# =====================================================
@tickets_bp.route('/<int:ticket_id>/pdf', methods=['GET'], endpoint='pdf_ticket')
@login_required
def tickets_pdf(ticket_id):
    u = current_user()
    t = load_ticket(ticket_id)
    if not t:
        abort(404)
    if u['role'] != 'admin' and t['created_by'] != u['id']:
        abort(403)

    t_dict = dict(t)
    if _has_any_signature_of_interest(t_dict) and (not row_get(t, "fecha_final", "")) and (not row_get(t, "hora_final", "")):
        now = datetime.now(DEFAULT_TZ)
        t_dict["fecha_final"] = now.strftime("%Y-%m-%d")
        t_dict["hora_final"]  = now.strftime("%H:%M")
        update_ticket(ticket_id, {"fecha_final": t_dict["fecha_final"], "hora_final":  t_dict["hora_final"]})

    estado_val = row_get(t, 'estado', 'abierto')

    pdf_buf = render_ticket_pdf(t_dict, {'LOGO_PATH': 'static/img/logo.png','ESTADO': estado_val})
    if not pdf_buf:
        abort(500, description="No se pudo generar el PDF")
    try:
        pdf_buf.seek(0)
    except Exception:
        pass
    return send_file(pdf_buf, mimetype='application/pdf', as_attachment=True,
                     download_name=f"ticket_{t['id']}.pdf")

# =====================================================
# Reportes (formulario/resultados/ZIP/CSV)
# =====================================================
@tickets_bp.route('/reportes', methods=['GET', 'POST'], endpoint='reportes_fechas')
@login_required
def tickets_reportes_fechas():
    u = current_user()
    if not u or u['role'] != 'admin':
        flash("No tienes permiso.", "danger")
        return redirect(url_for('tickets.dashboard'))

    if request.method == 'POST':
        f1 = (request.form.get('fecha_inicio') or '').strip()
        f2 = (request.form.get('fecha_final')  or '').strip()
        ok = lambda s: bool(re.match(r'^\d{4}-\d{2}-\d{2}$', s or ''))
        if not (ok(f1) and ok(f2)):
            flash("Debes seleccionar ambas fechas (YYYY-MM-DD).", "danger")
            return render_template('tickets/reportes_fechas.html', f1=f1, f2=f2)
        return redirect(url_for('tickets.resultados_fechas', f1=f1, f2=f2))

    f1 = (request.args.get('f1') or '').strip()
    f2 = (request.args.get('f2') or '').strip()
    return render_template('tickets/reportes_fechas.html', f1=f1, f2=f2)

@tickets_bp.route('/reportes/resultados', methods=['GET'], endpoint='resultados_fechas')
@login_required
def tickets_resultados_fechas():
    u = current_user()
    if not u or u['role'] != 'admin':
        flash("No tienes permiso.", "danger")
        return redirect(url_for('tickets.dashboard'))

    f1 = (request.args.get('f1') or '').strip()
    f2 = (request.args.get('f2') or '').strip()
    ok = lambda s: bool(re.match(r'^\d{4}-\d{2}-\d{2}$', s or ''))
    if not (ok(f1) and ok(f2)):
        flash("Rango de fechas inválido.", "danger")
        return redirect(url_for('tickets.reportes_fechas'))

    f_inicio, f_fin = sorted([f1, f2])
    try:
        db = get_db()
        q = ("""
            SELECT t.*, u.display_name AS creador
            FROM tickets t
            JOIN users u ON t.created_by = u.id
            WHERE substr(t.created_at, 1, 10) BETWEEN ? AND ?
            ORDER BY t.created_at DESC
        """)
        rows = db.execute(q, (f_inicio, f_fin)).fetchall()
    except Exception:
        current_app.logger.exception("Error en resultados_fechas")
        flash("Ocurrió un error consultando el reporte.", "danger")
        return redirect(url_for('tickets.reportes_fechas'))

    return render_template('tickets/resultados_fechas.html',
                           f1=f_inicio, f2=f_fin, tickets=rows, user=u)

@tickets_bp.route('/reportes/zip', methods=['GET'], endpoint='descargar_zip')
@login_required
def tickets_descargar_zip():
    u = current_user()
    if not u or u['role'] != 'admin':
        flash("No tienes permiso.", "danger")
        return redirect(url_for('tickets.dashboard'))

    f1 = (request.args.get('f1') or '').strip()
    f2 = (request.args.get('f2') or '').strip()
    ok = lambda s: bool(re.match(r'^\d{4}-\d{2}-\d{2}$', s or ''))
    if not (ok(f1) and ok(f2)):
        flash("Rango de fechas inválido.", "danger")
        return redirect(url_for('tickets.reportes_fechas'))

    f_inicio, f_fin = sorted([f1, f2])

    db = get_db()
    rows = db.execute("""
        SELECT t.*, u.display_name AS creador
        FROM tickets t
        JOIN users u ON t.created_by = u.id
        WHERE t.estado = 'finalizado'
          AND substr(COALESCE(t.finalizado_at, t.created_at), 1, 10) BETWEEN ? AND ?
        ORDER BY 
          CASE WHEN t.finalizado_at IS NULL THEN 1 ELSE 0 END,
          COALESCE(t.finalizado_at, t.created_at) DESC
    """, (f_inicio, f_fin)).fetchall()

    if not rows:
        flash("No hay tickets FINALIZADOS en ese rango para descargar.", "info")
        return redirect(url_for('tickets.resultados_fechas', f1=f_inicio, f2=f_fin))

    mem_zip = BytesIO()
    with zipfile.ZipFile(mem_zip, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
        index_csv = StringIO(newline='')
        idx = csv.writer(index_csv)
        idx.writerow(["id", "creado_por", "created_at", "fecha_final", "hora_final", "estado"])

        for r in rows:
            estado_val = row_get(r, 'estado', 'abierto')
            r_dict = dict(r)

            if _has_any_signature_of_interest(r_dict) and (not row_get(r, "fecha_final", "")) and (not row_get(r, "hora_final", "")):
                now = datetime.now(DEFAULT_TZ)
                r_dict["fecha_final"] = now.strftime("%Y-%m-%d")
                r_dict["hora_final"]  = now.strftime("%H:%M")

            pdf_buf = render_ticket_pdf(r_dict, {'LOGO_PATH': 'static/img/logo.png', 'ESTADO': estado_val})
            try:
                pdf_buf.seek(0)
            except Exception:
                pass
            zf.writestr(f"ticket_{r['id']}.pdf", pdf_buf.read())

            idx.writerow([
                r['id'], r['creador'], r['created_at'],
                row_get(r, 'fecha_final', ''), row_get(r, 'hora_final', ''), row_get(r, 'estado', '')
            ])

        zf.writestr("index.csv", ('\ufeff' + index_csv.getvalue()).encode('utf-8'))

    mem_zip.seek(0)
    zip_name = f"tickets_finalizados_{f_inicio}_a_{f_fin}.zip"
    return send_file(mem_zip, mimetype='application/zip',
                     as_attachment=True, download_name=zip_name)

@tickets_bp.route('/reportes/csv', methods=['GET'], endpoint='descargar_csv')
@login_required
def tickets_descargar_csv():
    u = current_user()
    if not u or u['role'] != 'admin':
        flash("No tienes permiso.", "danger")
        return redirect(url_for('tickets.dashboard'))

    f1 = (request.args.get('f1') or '').strip()
    f2 = (request.args.get('f2') or '').strip()
    ok = lambda s: bool(re.match(r'^\d{4}-\d{2}-\d{2}$', s or ''))
    if not (ok(f1) and ok(f2)):
        flash("Rango de fechas inválido.", "danger")
        return redirect(url_for('tickets.reportes_fechas'))

    f_inicio, f_fin = sorted([f1, f2])

    db = get_db()
    headers = [
        'id', 'created_at', 'creador',
        'sede', 'ubicacion',
        'servicio_tipo', 'servicio_otro', 'falla_asociada',
        'fecha_inicio', 'hora_inicio', 'fecha_final', 'hora_final',
        'equipo_equipo', 'equipo_marca', 'equipo_modelo',
        'equipo_cod_inventario', 'equipo_coin', 'equipo_disco',
        'equipo_ram', 'equipo_procesador',
        'estado', 'finalizado_at'
    ]

    sio = StringIO(newline='')
    writer = csv.writer(sio)
    writer.writerow(headers)

    rows = db.execute("""
        SELECT t.*, u.display_name AS creador
        FROM tickets t
        JOIN users u ON t.created_by = u.id
        WHERE substr(t.created_at, 1, 10) BETWEEN ? AND ?
        ORDER BY t.created_at DESC
    """, (f_inicio, f_fin)).fetchall()

    for r in rows:
        writer.writerow([
            r['id'], r['created_at'], r['creador'],
            r['sede'], r['ubicacion'],
            r['servicio_tipo'], r['servicio_otro'], r['falla_asociada'],
            r['fecha_inicio'], r['hora_inicio'], r['fecha_final'], r['hora_final'],
            r['equipo_equipo'], r['equipo_marca'], r['equipo_modelo'],
            r['equipo_cod_inventario'], r['equipo_coin'], r['equipo_disco'],
            r['equipo_ram'], r['equipo_procesador'],
            row_get(r, 'estado', ''), row_get(r, 'finalizado_at', '')
        ])

    csv_text = sio.getvalue()
    data = (u'\ufeff' + csv_text).encode('utf-8')
    bio = BytesIO(data)
    bio.seek(0)

    filename = f"tickets_{f_inicio}_a_{f_fin}.csv"
    return send_file(bio, mimetype='text/csv', as_attachment=True, download_name=filename)

# =====================================================
# Finalizar / Reabrir
# =====================================================
@tickets_bp.post('/<int:ticket_id>/finalizar', endpoint='finalizar_ticket')
@login_required
def finalizar_ticket(ticket_id):
    u = current_user()
    t = load_ticket(ticket_id)
    if not t:
        abort(404)

    if u['role'] != 'admin' and t['created_by'] != u['id']:
        flash('No tienes permisos para finalizar este ticket.', 'danger')
        return redirect(url_for('tickets.ver_ticket', ticket_id=ticket_id))

    if t['estado'] == 'finalizado':
        flash('El ticket ya está finalizado.', 'info')
        return redirect(url_for('tickets.ver_ticket', ticket_id=ticket_id))

    update_ticket(ticket_id, {
        'estado': 'finalizado',
        'finalizado_at': datetime.now(DEFAULT_TZ).isoformat()
    })

    flash('Ticket finalizado correctamente.', 'success')
    return redirect(url_for('tickets.ver_ticket', ticket_id=ticket_id))

@tickets_bp.post('/<int:ticket_id>/reabrir', endpoint='reabrir_ticket')
@login_required
def reabrir_ticket(ticket_id):
    from urllib.parse import urlparse
    u = current_user()
    t = load_ticket(ticket_id)
    if not t:
        abort(404)

    if not u or u['role'] != 'admin':
        flash('No tienes permisos para reabrir este ticket.', 'danger')
        return redirect(url_for('tickets.dashboard'))

    if t['estado'] != 'finalizado':
        flash('El ticket no está finalizado.', 'info')
        return redirect(url_for('tickets.dashboard'))

    update_ticket(ticket_id, {
        'estado': 'abierto',
        'finalizado_at': None,
    })

    next_url = request.form.get('next') or request.args.get('next')
    if next_url:
        parsed = urlparse(next_url)
        if not parsed.netloc and next_url.startswith('/'):
            flash('Ticket reabierto. Ahora está ABIERTO.', 'success')
            return redirect(next_url)

    flash('Ticket reabierto. Ahora está ABIERTO.', 'success')
    return redirect(url_for('tickets.dashboard'))

# =====================================================
# Inventario (consulta SQLite externo)
# =====================================================
@tickets_bp.get('/inventario/buscar', endpoint='inventario_buscar')
@login_required
def inventario_buscar():
    """
    GET /tickets/inventario/buscar?coin=...   o   ?cod=...
    Lee C:\inventario\inventario.db y devuelve JSON.
    """
    import sqlite3
    import os
    INV_DB_PATH = r"C:\inventario\inventario.db"

    if not os.path.exists(INV_DB_PATH):
        return jsonify(ok=False, error=f"No existe la base de datos en: {INV_DB_PATH}"), 503

    coin = (request.args.get('coin') or '').strip()
    cod  = (request.args.get('cod')  or '').strip()

    if not coin and not cod:
        return jsonify(ok=False, error="Falta parámetro: coin o cod"), 400

    con = sqlite3.connect(INV_DB_PATH)
    con.row_factory = sqlite3.Row

    SELECT_BASE = """
        SELECT
            COIN                           AS coin,
            "COD INVENTARIO"               AS cod_inventario,
            TIPO                           AS equipo,
            MARCA                          AS marca,
            MODELO                         AS modelo,
            RAM                            AS ram,
            "TAMAÑO SSD"                   AS disco,
            PROCESADOR                     AS procesador,
            SEDE                           AS sede,
            "UBICACIÓN"                    AS ubicacion
        FROM inventario
        WHERE {where}
        LIMIT 1;
    """

    if coin:
        row = con.execute(
            SELECT_BASE.format(where='COIN = ? COLLATE NOCASE'),
            (coin,)
        ).fetchone()
    else:
        row = con.execute(
            SELECT_BASE.format(where='"COD INVENTARIO" = ? COLLATE NOCASE'),
            (cod,)
        ).fetchone()

    con.close()

    if not row:
        return jsonify(ok=False, error="No encontrado"), 404

    d = dict(row)
    d['ok'] = True
    return jsonify(d)

# =====================================================
# Guardar SOLO el nombre de Logística (con defecto)
# =====================================================
@tickets_bp.post('/<int:ticket_id>/set_nombre_logistica', endpoint='set_nombre_logistica')
@login_required
def set_nombre_logistica(ticket_id):
    u = current_user()
    t = load_ticket(ticket_id)
    if not t:
        abort(404)

    if u['role'] != 'admin' and t['created_by'] != u['id']:
        flash('No tienes permisos para modificar este ticket.', 'danger')
        return redirect(url_for('tickets.ver_ticket', ticket_id=ticket_id))

    nombre = (request.form.get('firma_logistica_nombre') or '').strip() or "Logística"
    update_ticket(ticket_id, {'firma_logistica_nombre': nombre})
    flash('Nombre de Logística guardado.', 'success')
    return redirect(url_for('tickets.ver_ticket', ticket_id=ticket_id))

# =====================================================
# ENVIAR A LOGÍSTICA (PDF adjunto) — nombre fijo si falta, firma obligatoria
# =====================================================
@tickets_bp.post('/<int:ticket_id>/enviar_logistica', endpoint='enviar_logistica')
@login_required
def tickets_enviar_logistica(ticket_id):
    u = current_user()
    t = load_ticket(ticket_id)
    if not t:
        flash('Ticket no encontrado.', 'danger')
        return redirect(url_for('tickets.dashboard'))

    # Permisos: admin o creador
    if u['role'] != 'admin' and t['created_by'] != u['id']:
        flash('No tienes permisos para enviar este ticket a Logística.', 'danger')
        return redirect(url_for('tickets.ver_ticket', ticket_id=ticket_id))

    # Debe estar FINALIZADO
    if row_get(t, 'estado', '') != 'finalizado':
        flash('Para enviar a Logística el ticket debe estar FINALIZADO.', 'warning')
        return redirect(url_for('tickets.ver_ticket', ticket_id=ticket_id))

    # Firma de Logística (imagen) obligatoria: dataURL o PNG en static/
    firma_img = (row_get(t, 'firma_logistica_img', '') or '').strip()
    if not _valid_sig_any(firma_img):
        flash('Falta la firma de Logística (imagen).', 'warning')
        return redirect(url_for('tickets.ver_ticket', ticket_id=ticket_id))

    # Nombre fijo / predeterminado
    firma_nom = (row_get(t, 'firma_logistica_nombre', '') or '').strip() or "Logística"

    # Sellar fecha/hora final si faltan
    fecha_final = row_get(t, 'fecha_final', '')
    hora_final  = row_get(t, 'hora_final', '')
    if not fecha_final and not hora_final:
        now_local = datetime.now(DEFAULT_TZ)
        fecha_final = now_local.strftime("%Y-%m-%d")
        hora_final  = now_local.strftime("%H:%M")
        update_ticket(ticket_id, {'fecha_final': fecha_final, 'hora_final': hora_final})

    # Generar PDF con todo
    t2 = load_ticket(ticket_id)
    t_dict = dict(t2)
    estado_val = row_get(t2, 'estado', 'abierto')

    pdf_buf = render_ticket_pdf(t_dict, {
        'LOGO_PATH': current_app.config.get('LOGO_PATH', 'static/img/logo.png'),
        'ESTADO': estado_val
    })
    if not pdf_buf:
        flash('No se pudo generar el PDF.', 'danger')
        return redirect(url_for('tickets.ver_ticket', ticket_id=ticket_id))
    try:
        pdf_buf.seek(0)
    except Exception:
        pass
    pdf_bytes = pdf_buf.read()
    pdf_name  = f"ticket_{t2['id']}.pdf"

    # Enviar correo
    to_addr = current_app.config.get('LOGISTICA_EMAIL')
    if not to_addr:
        flash('No está configurado LOGISTICA_EMAIL en la app.', 'warning')
        return redirect(url_for('tickets.ver_ticket', ticket_id=ticket_id))

    subject = f"Ticket #{t2['id']} finalizado (envío a Logística)"
    body = (
        f"Hola Logística,\n\n"
        f"El ticket #{t2['id']} está FINALIZADO y cuenta con firma de Logística.\n"
        f"Nombre (registro): {firma_nom}\n"
        f"Fecha/hora final: {fecha_final} {hora_final}\n"
        f"Sede: {row_get(t2, 'sede', '-')}\n"
        f"Ubicación: {row_get(t2, 'ubicacion', '-')}\n\n"
        f"Se adjunta el PDF.\n\n"
        f"— Mesa de Ayuda TIC"
    )

    try:
        send_mail_with_pdf(
            to_addr=to_addr,
            subject=subject,
            body=body,
            filename=pdf_name,
            pdf_bytes=pdf_bytes,
            app=current_app
        )
        flash('Notificación enviada a Logística (PDF adjunto).', 'success')
    except Exception:
        current_app.logger.exception("Error enviando correo a Logística")
        flash('El ticket está finalizado con firma, pero ocurrió un problema enviando el correo.', 'warning')

    return redirect(url_for('tickets.ver_ticket', ticket_id=ticket_id))