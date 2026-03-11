# -*- coding: utf-8 -*-
"""
mesa/pdf_utils.py

Fechas -> línea -> Títulos en fila ("Tipo de servicio" | "Falla asociada") -> Valores debajo ->
hr -> Tipo de soporte (checkboxes) -> hr -> Equipo (2x4) -> Descripciones -> Evaluación -> Firmas
"""

import base64
from io import BytesIO

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth


# -------------------- Helpers --------------------
def _draw_signature_image(c, data_url, x, y, w, h):
    """Dibuja una firma desde:
       - data URL (data:image/png;base64,...)
       - ruta/URL de archivo (/static/... o http(s)://...)
       - base64 plano (último recurso)
    """
    if not data_url:
        return False
    try:
        if isinstance(data_url, str):
            s = data_url.strip()
            # 1) Data URL
            if s.startswith("data:image"):
                _, b64 = s.split(",", 1)
                img_bytes = base64.b64decode(b64)
                bio = BytesIO(img_bytes)
                c.drawImage(ImageReader(bio), x, y, width=w, height=h,
                            preserveAspectRatio=True, mask="auto")
                return True
            # 2) Ruta/URL de imagen
            if s.startswith(("http://", "https://", "/", "file:")):
                c.drawImage(s, x, y, width=w, height=h,
                            preserveAspectRatio=True, mask="auto")
                return True
            # 3) Base64 “pelado”
            try:
                img_bytes = base64.b64decode(s)
                bio = BytesIO(img_bytes)
                c.drawImage(ImageReader(bio), x, y, width=w, height=h,
                            preserveAspectRatio=True, mask="auto")
                return True
            except Exception:
                return False
        return False
    except Exception:
        return False


def draw_label_value_tight(
    c, label, value, x, y,
    font_label="Helvetica-Bold",
    font_value="Helvetica",
    size=10, padding=2
):
    """Dibuja 'Label: Valor' pegado y devuelve la x final usada."""
    c.setFont(font_label, size)
    c.drawString(x, y, label)
    w_label = stringWidth(label, font_label, size)

    c.setFont(font_value, size)
    txt = value if (value is not None and value != "") else "-"
    c.drawString(x + w_label + padding, y, txt)
    w_value = stringWidth(txt, font_value, size)
    return x + w_label + padding + w_value


def wrap_lines(c, text, max_width, font="Helvetica", size=10, max_lines=None):
    """Rompe texto por palabras respetando ancho y líneas máximas."""
    c.setFont(font, size)
    text = (text or "-").replace("\r", "")
    raw_lines = text.split("\n")
    out = []
    for raw in raw_lines:
        words = raw.split(" ")
        curr = ""
        for w in words:
            test = (curr + " " + w).strip()
            if stringWidth(test, font, size) <= max_width:
                curr = test
            else:
                if curr:
                    out.append(curr)
                curr = w
        if curr:
            out.append(curr)
    if max_lines is not None and len(out) > max_lines:
        out = out[:max_lines]
        last = out[-1]
        ell = "..."
        while last and stringWidth(last + " " + ell, font, size) > max_width:
            last = last[:-1]
        out[-1] = (last + " " + ell).strip()
    return out


def _draw_checkbox(c, x, y, checked=False, label=None, size=10):
    """Dibuja una cajita de checkbox con (opcional) una 'X' y su etiqueta."""
    c.rect(x, y, size, size, fill=0, stroke=1)
    if checked:
        c.setLineWidth(2)
        c.line(x + 2, y + 2, x + size - 2, y + size - 2)
        c.line(x + 2, y + size - 2, x + size - 2, y + 2)
        c.setLineWidth(1)
    if label:
        c.setFont("Helvetica", 10)
        c.drawString(x + size + 6, y, label)


# --- Helper para leer la primera clave disponible (con alias/fallbacks) ---
def get_first(d, *keys, default=""):
    """Devuelve el primer valor no vacío encontrado en d para las claves dadas."""
    try:
        d = dict(d)  # Row -> dict (si ya es dict no pasa nada)
    except Exception:
        pass
    for k in keys:
        try:
            v = d.get(k)
            if v not in (None, ""):
                return v
        except Exception:
            try:
                if k in d.keys() and d[k]:
                    return d[k]
            except Exception:
                pass
    return default


# -------------------- Generación del PDF --------------------
def render_ticket_pdf(t, config=None):
    """
    Layout clave:
    FECHAS -> hr -> (Títulos en fila) Tipo de servicio | Falla asociada -> (Valores debajo) -> hr
    -> Tipo de soporte (checkboxes) -> hr -> Equipo (2x4) -> Descripciones -> Evaluación -> Firmas
    """
    print("[pdf] render_ticket_pdf ACTIVO (incluye Tipo de soporte y Equipo)")

    t = dict(t or {})
    config = dict(config or {})

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    W, H = A4
    left, right = 1.6 * cm, W - 1.6 * cm
    usable_width = right - left
    top = H - 1.6 * cm

    def header():
        logo_path = config.get("LOGO_PATH")
        if not logo_path:
            return
        try:
            logo_w_cm = float(config.get("LOGO_W_CM", 5.5))
            logo_h_cm = float(config.get("LOGO_H_CM", 2.6))
            top_clear = float(config.get("LOGO_TOP_CLEAR_CM", 0.4))
            x = W - (1.6 * cm) - (logo_w_cm * cm)
            y = H - ((top_clear + logo_h_cm) * cm)
            c.drawImage(logo_path, x, y,
                        width=logo_w_cm * cm, height=logo_h_cm * cm,
                        preserveAspectRatio=True, mask="auto")
        except Exception:
            pass

    def hr(spacing=0.5 * cm):
        nonlocal top
        c.line(left, top, right, top)
        top -= spacing

    def val(key, default="-"):
        v = t.get(key)
        return v if (v is not None and v != "") else default

    # ---------- Encabezado ----------
    header()
    c.setFont("Helvetica", 11)
    creador = t.get("creador")
    c.drawString(left, top, f"Creado por: {creador or '-'}")
    # Empuje extra: espacio para logos grandes
    top -= 1.5 * cm
    hr()

    # ---------- Fechas + Horas + Sede + Ubicación ----------
    line_gap = 0.45 * cm
    min_gap_cols = 0.8 * cm
    col2_min = left + 5.0 * cm
    col3_min = left + 10.0 * cm

    x1_end = draw_label_value_tight(c, "Fecha inicio: ", val("fecha_inicio"), left, top, padding=3)
    x2 = max(col2_min, x1_end + min_gap_cols)
    x2_end = draw_label_value_tight(c, "Hora inicio: ",  val("hora_inicio"),  x2,   top, padding=3)
    x3 = max(col3_min, x2_end + min_gap_cols)
    _ = draw_label_value_tight(c, "Sede: ",            val("sede"),          x3,   top, padding=3)
    top -= line_gap

    x1_end = draw_label_value_tight(c, "Fecha final: ", val("fecha_final"), left, top, padding=3)
    x2 = max(col2_min, x1_end + min_gap_cols)
    x2_end = draw_label_value_tight(c, "Hora final: ",  val("hora_final"),  x2,   top, padding=3)
    x3 = max(col3_min, x2_end + min_gap_cols)
    _ = draw_label_value_tight(c, "Ubicación: ",       val("ubicacion"),    x3,   top, padding=3)
    top -= line_gap

    # ======= Línea tras FECHAS =======
    hr(0.5 * cm)

    # ---- Resolver tipo_servicio y falla_asociada ----
    tipo_servicio_resuelto = t.get("tipo_servicio")
    if not tipo_servicio_resuelto:
        st = (t.get("servicio_tipo") or "").strip()
        so = (t.get("servicio_otro") or "").strip()
        if st == "Otro":
            tipo_servicio_resuelto = so if so else "Otro"
        else:
            tipo_servicio_resuelto = st or "-"
    falla_asociada_resuelta = (t.get("falla_asociada") or "-")

    # ---------- Fila de TÍTULOS ----------
    c.setFont("Helvetica-Bold", 11)
    c.drawString(left, top, "Tipo de servicio")
    c.drawString(col2_min, top, "Falla asociada")
    top -= 0.35 * cm

    # ---------- Fila de VALORES (debajo) ----------
    c.setFont("Helvetica", 10)

    def single_line_ellipses(txt, max_w, font="Helvetica", size=10):
        c.setFont(font, size)
        s = (txt or "-")
        if stringWidth(s, font, size) <= max_w:
            return s
        ell = "..."
        while s and stringWidth(s + ell, font, size) > max_w:
            s = s[:-1]
        return (s + ell) if s else ell

    col_width = (right - left) / 2.0 - 1.0 * cm
    tipo_line = single_line_ellipses(tipo_servicio_resuelto, col_width, "Helvetica", 10)
    falla_line = single_line_ellipses(falla_asociada_resuelta, col_width, "Helvetica", 10)

    c.drawString(left, top, tipo_line)
    c.drawString(col2_min, top, falla_line)
    top -= 0.5 * cm

    hr()  # separa antes de Tipo de soporte

    # ---------- Tipo de soporte (Checkboxes) ----------
    c.setFont("Helvetica-Bold", 11)
    c.drawString(left, top, "Tipo de soporte")
    top -= 0.28 * cm
    hr(0.5 * cm)

    _draw_checkbox(c, left,          top - 2, checked=bool(t.get("soporte_hardware", 0)), label="Hardware")
    _draw_checkbox(c, left + 4*cm,   top - 2, checked=bool(t.get("soporte_Software", 0)), label="Software")
    _draw_checkbox(c, left + 8*cm,   top - 2, checked=bool(t.get("soporte_redes", 0)),    label="Redes")
    top -= 0.35 * cm

    hr()  # separa antes de Equipo

    # ---------- Equipo (2x4) ----------
    cols = 4
    col_w = usable_width / cols
    col_x = [left + i * col_w for i in range(cols)]
    row_gap_equipo = 0.60 * cm
    pad = 2

    draw_label_value_tight(c, "Tipo:",          val("equipo_equipo"),         col_x[0], top, size=10, padding=pad)
    draw_label_value_tight(c, "Modelo:",          val("equipo_modelo"),         col_x[1], top, size=10, padding=pad)
    draw_label_value_tight(c, "COIN:",            val("equipo_coin"),           col_x[2], top, size=10, padding=pad)
    draw_label_value_tight(c, "Cód. inventario:", val("equipo_cod_inventario"), col_x[3], top, size=10, padding=pad)
    top -= row_gap_equipo

    draw_label_value_tight(c, "Marca:",           val("equipo_marca"),          col_x[0], top, size=10, padding=pad)
    draw_label_value_tight(c, "RAM:",             val("equipo_ram"),            col_x[1], top, size=10, padding=pad)
    draw_label_value_tight(c, "D. Duro:",         val("equipo_disco"),          col_x[2], top, size=10, padding=pad)
    draw_label_value_tight(c, "Procesador:",      val("equipo_procesador"),     col_x[3], top, size=10, padding=pad)

    top -= (row_gap_equipo + 0.20 * cm)

    # ---------- Descripción del servicio ----------
    c.setFont("Helvetica-Bold", 11)
    c.drawString(left, top, "Descripción del servicio")
    top -= 0.1 * cm
    hr(0.5 * cm)
    c.setFont("Helvetica", 10)
    for ln in wrap_lines(c, val("descripcion_solicitud"), usable_width, max_lines=12):
        c.drawString(left, top, ln)
        top -= 13

    top -= 0.2 * cm

    # ---------- Descripción del trabajo realizado ----------
    c.setFont("Helvetica-Bold", 11)
    c.drawString(left, top, "Descripción del trabajo realizado")
    top -= 0.1 * cm
    hr(0.5 * cm)
    c.setFont("Helvetica", 10)
    for ln in wrap_lines(c, val("descripcion_trabajo"), usable_width, max_lines=10):
        c.drawString(left, top, ln)
        top -= 13

    # ---------- Evaluación ----------
    top -= 0.10 * cm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(left, top, "Evaluación del servicio (1 a 5)")
    top -= 0.28 * cm
    c.line(left, top, right, top)
    top -= 0.18 * cm

    def draw_eval_box_row(y, label, value,
                          left_margin=left, box_size=12,
                          box_gap=0.28 * cm, label_gap=0.60 * cm):
        c.setFont("Helvetica-Bold", 10)
        c.drawString(left_margin, y + 1, label)
        start_x = left_margin + label_gap + 6.6 * cm
        c.setFont("Helvetica-Bold", 9)
        for i in range(1, 6):
            x = start_x + (i - 1) * (box_size + box_gap)
            c.rect(x, y, box_size, box_size, fill=0, stroke=1)
            num = str(i)
            wnum = stringWidth(num, "Helvetica-Bold", 9)
            cx = x + (box_size - wnum) / 2.0
            cy = y + (box_size - 9) / 2.0 + 1
            c.drawString(cx, cy, num)
            if value == i:
                c.setLineWidth(1.2)
                c.line(x + 2, y + 2, x + box_size - 2, y + box_size - 2)
                c.line(x + 2, y + box_size - 2, x + box_size - 2, y + 2)
                c.setLineWidth(1.0)

    def _as_int_1_5(v):
        try:
            vi = int(v)
            return 1 <= vi <= 5 and vi or None
        except Exception:
            return None

    v1 = _as_int_1_5(t.get("eval_calidad_servicio"))
    v2 = _as_int_1_5(t.get("eval_calidad_informacion"))
    v3 = _as_int_1_5(t.get("eval_oportunidad_respuesta"))
    v4 = _as_int_1_5(t.get("eval_actitud_tecnico"))

    eval_row_gap = 0.90 * cm
    top -= 0.10 * cm
    draw_eval_box_row(top - 12, "Calidad del servicio:",         v1)
    top -= eval_row_gap
    draw_eval_box_row(top - 12, "Calidad de la información:",    v2)
    top -= eval_row_gap
    draw_eval_box_row(top - 12, "Oportunidad de respuesta:",     v3)
    top -= eval_row_gap
    draw_eval_box_row(top - 12, "Actitud del personal técnico:", v4)
    top -= (eval_row_gap - 0.20 * cm)

    
    # ---------- FIRMAS ----------
    firmas_top_extra_cm = float(config.get("FIRMAS_TOP_EXTRA_CM", 1.0))
    margen_sup_cm       = float(config.get("FIRMAS_MARGEN_SUP_CM", 0.1))
    row_gap_sign_cm     = float(config.get("FIRMAS_ROW_GAP_CM", 3.8))
    title_line_gap_cm   = float(config.get("FIRMAS_TITLE_LINE_GAP_CM", 0.3))

    # Título y línea
    top -= firmas_top_extra_cm * cm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(left, top, "Firmas")
    top -= (title_line_gap_cm * cm)
    c.line(left, top, right, top)

    # Coordenadas base de los slots de firma
    y_start   = top - (margen_sup_cm * cm)
    sig_w, sig_h = 5.5 * cm, 2.0 * cm
    col2_offset  = 9.2 * cm
    x1 = left
    x2 = left + col2_offset

    def slot(x0, y0, title, nombre, data):
        # Parámetros de separación configurables
        gap_titulo_nombre_cm    = float(config.get("FIRMAS_GAP_TITULO_NOMBRE_CM", 0.10))
        # Forzar que la línea vaya debajo de la imagen cuando exista
        force_line_below_image  = bool(config.get("FIRMAS_LINE_BELOW_IMAGE", True))
        # Distancia de la línea respecto al borde INFERIOR del bloque de firma
        line_below_image_gap_cm = float(config.get("FIRMAS_LINE_BELOW_IMAGE_GAP_CM", 0.10))
        etiqueta = "Nombre: "

        # Título encima del bloque de firma
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x0, y0 + sig_h + 0.5 * cm, title)

        # "Nombre: …" (encima de la firma)
        c.setFont("Helvetica", 10)
        nombre_y = y0 + sig_h + (gap_titulo_nombre_cm * cm)
        c.drawString(x0, nombre_y, f"{etiqueta}{(nombre or '-')}")

        # Dibuja la firma (si hay) dentro del bloque (x0, y0, sig_w, sig_h)
        firma_dibujada = _draw_signature_image(c, data, x0, y0, sig_w, sig_h)

        # Línea
        c.setLineWidth(1)

        if force_line_below_image and firma_dibujada:
            # Línea justo DEBAJO de la firma (a lo ancho del bloque de firma)
            x_line_start = x0
            x_line_end   = x0 + sig_w
            y_line       = y0 - (line_below_image_gap_cm * cm)
        else:
            # Sin firma: deja la línea donde estaba (debajo de "Nombre:")
            w_etiqueta   = stringWidth(etiqueta, "Helvetica", 10)
            x_line_start = x0 + w_etiqueta + 4
            x_line_end   = x0 + 6.5 * cm
            y_line       = nombre_y - 0.24 * cm

        c.line(x_line_start, y_line, x_line_end, y_line)

    # === Fallbacks de claves por rol ===
    # Soporte técnico (del perfil al CREAR)
    tec_mant_img = get_first(t, 'firma_tecnico_mantenimiento_img', 'firma_Tecnico_Mantenimiento_img', default="")
    tec_mant_nom = get_first(t, 'firma_tecnico_mantenimiento_nombre', 'firma_Tecnico_Mantenimiento_nombre', default="")

    # Usuario que gestiona (canvas) ✅ claves nuevas + fallbacks
    usr_img = get_first(
        t,
        'firma_usuario_gestiona_img',  # clave nueva
        'firma_usuario_img',           # fallback viejo
        'firma_Usuario_img',           # fallback legacy
        default=""
    )
    usr_nom = get_first(
        t,
        'firma_usuario_gestiona_nombre',  # clave nueva
        'firma_usuario_nombre',           # fallback viejo
        'firma_Usuario_nombre',           # fallback legacy
        default=""
    )

    # Logística (canvas)
    log_img = get_first(t, 'firma_logistica_img', default="")
    log_nom = get_first(t, 'firma_logistica_nombre', default="")

    # Técnico que realiza mantenimiento (en DB lo guardaste como “supervisor”)
    sup_img = get_first(t, 'firma_supervisor_img', 'firma_Técnico_Que_Realiza_Mantenimiento_img', default="")
    sup_nom = get_first(t, 'firma_supervisor_nombre', 'firma_Técnico_Que_Realiza_Mantenimiento_nombre', default="")

    # (Debug opcional)
    try:
        print("[pdf] firmas len => tec:", len(tec_mant_img or ''),
              "usr:", len(usr_img or ''),
              "log:", len(log_img or ''),
              "sup:", len(sup_img or ''))
    except Exception:
        pass

    # Fila superior
    y_sup = y_start - sig_h - 0.8 * cm
    slot(x1, y_sup, "Firma de soporte técnico",              tec_mant_nom, tec_mant_img)
    slot(x2, y_sup, "Firma del usuario que gestiona",        usr_nom,      usr_img)

    # Fila inferior
    y_inf = y_sup - (row_gap_sign_cm * cm)
    slot(x1, y_inf, "Firma de logística",                    log_nom,      log_img)
    slot(x2, y_inf, "Firma del técnico que realiza mantenimiento", sup_nom, sup_img)

    # ---------- FIN ----------
    c.showPage()
    c.save()
    buf.seek(0)
    return buf
