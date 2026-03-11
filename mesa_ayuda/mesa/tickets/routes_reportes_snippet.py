from flask import render_template, request, redirect, url_for, flash, send_file, abort
import io, zipfile, csv

# --- Reportes por rango de fechas (formulario) ---
@tickets_bp.route('/reportes', methods=['GET', 'POST'])
@login_required
def reportes_fechas():
    u = current_user()
    if not u or u['role'] != 'admin':
        flash("No tienes permiso para ver reportes.", "danger")
        return redirect(url_for('tickets.dashboard'))

    if request.method == 'POST':
        f1 = (request.form.get('fecha_inicio') or '').strip()
        f2 = (request.form.get('fecha_final') or '').strip()
        if not f1 or not f2:
            flash("Debes elegir las dos fechas.", "warning")
            return render_template('tickets/reportes_fechas.html', f1=f1, f2=f2)
        if f2 < f1:
            flash("La fecha final no puede ser menor a la inicial.", "warning")
            return render_template('tickets/reportes_fechas.html', f1=f1, f2=f2)
        return redirect(url_for('tickets.resultados_fechas', f1=f1, f2=f2))

    return render_template('tickets/reportes_fechas.html')


# --- Resultados del reporte ---
@tickets_bp.route('/reportes/resultados')
@login_required
def resultados_fechas():
    u = current_user()
    if not u or u['role'] != 'admin':
        flash("No tienes permiso para ver reportes.", "danger")
        return redirect(url_for('tickets.dashboard'))

    f1 = (request.args.get('f1') or '').strip()
    f2 = (request.args.get('f2') or '').strip()
    if not f1 or not f2:
        flash("Rango inválido.", "warning")
        return redirect(url_for('tickets.reportes_fechas'))

    db = get_db()
    sql = """
      SELECT t.*, u.display_name AS creador
      FROM tickets t
      JOIN users u ON u.id = t.created_by
      WHERE date(COALESCE(NULLIF(t.fecha_inicio,''), substr(t.created_at,1,10))) BETWEEN date(?) AND date(?)
      ORDER BY COALESCE(NULLIF(t.fecha_inicio,''), substr(t.created_at,1,10)) ASC, t.id ASC
    """
    tickets = db.execute(sql, (f1, f2)).fetchall()

    return render_template('tickets/resultados_fechas.html', tickets=tickets, f1=f1, f2=f2)


# --- Descargar ZIP con todos los PDFs del rango ---
@tickets_bp.route('/reportes/zip')
@login_required
def descargar_zip():
    u = current_user()
    if not u or u['role'] != 'admin':
        abort(403)

    f1 = (request.args.get('f1') or '').strip()
    f2 = (request.args.get('f2') or '').strip()
    if not f1 or not f2 or f2 < f1:
        flash("Rango inválido.", "warning")
        return redirect(url_for('tickets.reportes_fechas'))

    db = get_db()
    sql = """
      SELECT t.*, (SELECT display_name FROM users WHERE id=t.created_by) AS creador
      FROM tickets t
      WHERE date(COALESCE(NULLIF(t.fecha_inicio,''), substr(t.created_at,1,10))) BETWEEN date(?) AND date(?)
      ORDER BY COALESCE(NULLIF(t.fecha_inicio,''), substr(t.created_at,1,10)) ASC, t.id ASC
    """
    rows = db.execute(sql, (f1, f2)).fetchall()

    if not rows:
        flash("No hay tickets en ese rango.", "info")
        return redirect(url_for('tickets.reportes_fechas'))

    mem = io.BytesIO()
    with zipfile.ZipFile(mem, 'w', zipfile.ZIP_DEFLATED) as zf:
        for t in rows:
            pdf_buf = render_ticket_pdf(dict(t), {'LOGO_PATH':'static/img/logo.png'})
            try:
                pdf_buf.seek(0)
            except Exception:
                pass
            zf.writestr(f"ticket_{t['id']}.pdf", pdf_buf.read())
    mem.seek(0)

    return send_file(mem, as_attachment=True,
                     download_name=f"tickets_{f1}_a_{f2}.zip",
                     mimetype="application/zip")


# --- Descargar CSV (corregido) ---
@tickets_bp.route('/reportes/csv')
@login_required
def descargar_csv():
    u = current_user()
    if not u or u['role'] != 'admin':
        abort(403)

    f1 = (request.args.get('f1') or '').strip()
    f2 = (request.args.get('f2') or '').strip()
    if not f1 or not f2 or f2 < f1:
        flash("Rango inválido.", "warning")
        return redirect(url_for('tickets.reportes_fechas'))

    db = get_db()
    sql = """
      SELECT t.id, t.fecha_inicio, t.hora_inicio, t.fecha_final, t.hora_final,
             t.sede, t.ubicacion, t.servicio_tipo, t.falla_asociada,
             t.descripcion_solicitud, t.descripcion_trabajo,
             t.eval_calidad_servicio, t.eval_calidad_informacion,
             t.eval_oportunidad_respuesta, t.eval_actitud_tecnico,
             u.display_name AS creador, t.created_at
      FROM tickets t
      JOIN users u ON u.id = t.created_by
      WHERE date(COALESCE(NULLIF(t.fecha_inicio,''), substr(t.created_at,1,10))) BETWEEN date(?) AND date(?)
      ORDER BY COALESCE(NULLIF(t.fecha_inicio,''), substr(t.created_at,1,10)) ASC, t.id ASC
    """
    rows = db.execute(sql, (f1, f2)).fetchall()

    if not rows:
        flash("No hay tickets en ese rango.", "info")
        return redirect(url_for('tickets.reportes_fechas'))

    # Evita que Excel interprete fórmulas (=, +, -, @)
    def safe_cell(v):
        if v is None:
            return ''
        s = str(v)
        return "'" + s if s.startswith(('=', '+', '-', '@')) else s

    # Si quieres “aplanar” saltos de línea en textos largos, usa esta helper:
    def flatten(s: str) -> str:
        if not s:
            return ''
        return s.replace('\r', ' ').replace('\n', ' ').strip()

    output = io.StringIO(newline='')
    writer = csv.writer(output)

    writer.writerow([
        'id','fecha_inicio','hora_inicio','fecha_final','hora_final',
        'sede','ubicacion',
        'servicio_tipo','falla_asociada',
        'descripcion_solicitud','descripcion_trabajo',
        'eval_calidad_servicio','eval_calidad_informacion',
        'eval_oportunidad_respuesta','eval_actitud_tecnico',
        'creador','created_at'
    ])

    for r in rows:
        writer.writerow([
            r['id'],
            safe_cell(r['fecha_inicio']),
            safe_cell(r['hora_inicio']),
            safe_cell(r['fecha_final']),
            safe_cell(r['hora_final']),
            safe_cell(r['sede']),
            safe_cell(r['ubicacion']),
            safe_cell(r['servicio_tipo']),
            safe_cell(r['falla_asociada']),
            # Si prefieres mantener saltos de línea, usa directamente safe_cell(r['descripcion_*'])
            safe_cell(flatten(r['descripcion_solicitud'])),
            safe_cell(flatten(r['descripcion_trabajo'])),
            r['eval_calidad_servicio'],
            r['eval_calidad_informacion'],
            r['eval_oportunidad_respuesta'],
            r['eval_actitud_tecnico'],
            safe_cell(r['creador']),
            safe_cell(r['created_at']),
        ])

    # BOM UTF-8 para Excel
    mem = io.BytesIO(('\ufeff' + output.getvalue()).encode('utf-8'))
    mem.seek(0)
    return send_file(mem, as_attachment=True,
                     download_name=f"tickets_{f1}_a_{f2}.csv",
                     mimetype="text/csv")
