# app.py
# -*- coding: utf-8 -*-
import os
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, redirect, url_for
from mesa.db import init_db, close_db
from mesa.auth.routes import auth_bp
from mesa.tickets.routes import tickets_bp
from mesa.users.routes import users_bp

def create_app():
    # App Flask: plantillas y estáticos
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder='mesa/templates',
        static_folder='static'
    )



    # Claves de sesión
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'Proyecto_mesa_ayuda_ticket')
    app.config['SESSION_COOKIE_NAME'] = os.environ.get('SESSION_COOKIE_NAME', 'mesa_ayuda_cookie')

    # Configuración de la app
    app.config.from_mapping(
        DATABASE=os.path.join(app.instance_path, 'ticket_app.db'),
        LOGO_PATH='static/img/logo.png',

        # === Correo (usar variables de entorno) ===
        LOGISTICA_EMAIL=os.environ.get('LOGISTICA_EMAIL', ''),

        # SMTP (Office 365 típico)
        MAIL_SERVER=os.environ.get('MAIL_SERVER', 'smtp.office365.com'),
        MAIL_PORT=int(os.environ.get('MAIL_PORT', '587')),
        MAIL_USE_TLS=os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true',
        MAIL_USERNAME=os.environ.get('MAIL_USERNAME', ''),       # desde .env
        MAIL_PASSWORD=os.environ.get('MAIL_PASSWORD', ''),       # desde .env
        MAIL_DEFAULT_SENDER=os.environ.get('MAIL_DEFAULT_SENDER', os.environ.get('MAIL_USERNAME', '')),

        # Inventario externo (opcional)
        INVENTARIO_DB=os.environ.get('INVENTARIO_DB', r'D:\inventario\inventario.db'),
    )

    # Asegurar carpeta instance
    os.makedirs(app.instance_path, exist_ok=True)

    # Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(tickets_bp, url_prefix='/tickets')
    app.register_blueprint(users_bp, url_prefix='/usuarios')

    # Inicialización/cierre de DB
    with app.app_context():
        init_db()
    app.teardown_appcontext(close_db)

    @app.route('/')
    def index():
        return redirect(url_for('tickets.dashboard'))

    return app

if __name__ == '__main__':
    app = create_app()
    # En producción, debug=False
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '5006')), debug=True)