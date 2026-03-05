import os
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from extensions import db, login_manager

# Carrega variáveis do .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def create_app():
    app = Flask(__name__)

    # ── Banco de dados ─────────────────────────────────────────────────────────
    # Em desenvolvimento usa SQLite por padrão.
    # Em produção defina DATABASE_URL no .env com a string do PostgreSQL.
    database_url = os.environ.get('DATABASE_URL', 'sqlite:///taskmanager.db')

    # Compatibilidade com URLs "postgres://" geradas por alguns provedores
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)

    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Upload de fotos — pasta-raiz; subpastas criadas por save_photo() em utils.py
    app.config['UPLOAD_FOLDER']      = os.path.join(app.root_path, 'static', 'uploads')
    app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Pool de conexões — aplicado apenas quando usar PostgreSQL
    if database_url.startswith('postgresql'):
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'pool_size':     10,
            'pool_timeout':  30,
            'pool_recycle':  1800,
            'pool_pre_ping': True,
        }

    # Segurança de sessão em produção
    if os.environ.get('FLASK_ENV') == 'production':
        app.config['SESSION_COOKIE_SECURE']      = True
        app.config['SESSION_COOKIE_HTTPONLY']     = True
        app.config['SESSION_COOKIE_SAMESITE']     = 'Lax'
        app.config['PERMANENT_SESSION_LIFETIME']  = 86400  # 1 dia

    # ── Extensions ────────────────────────────────────────────────────────────
    # ProxyFix: faz request.scheme refletir o protocolo real (HTTP/HTTPS)
    # quando a app está atrás do Nginx. Necessário para SESSION_COOKIE_SECURE
    # e para que url_for() gere URLs com https://.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view             = 'auth.login'
    login_manager.login_message          = 'Por favor, faça login para acessar esta página.'
    login_manager.login_message_category = 'info'

    # ── Blueprints ────────────────────────────────────────────────────────────
    from blueprints.auth      import auth_bp
    from blueprints.admin     import admin_bp
    from blueprints.user      import user_bp
    from blueprints.equipment import equipment_bp
    from blueprints.lab       import lab_bp
    from blueprints.reports   import reports_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(lab_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(user_bp)
    app.register_blueprint(equipment_bp)
    app.register_blueprint(reports_bp)

    # ── Banco de dados + seed ─────────────────────────────────────────────────
    with app.app_context():
        db.create_all()
        _seed_admin()

    return app


def _seed_admin():
    from models import User
    if not User.query.filter_by(role='admin').first():
        admin = User(name='Administrador', email='admin@taskmanager.com', role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print('✅ Admin padrão criado: admin@taskmanager.com / admin123')


if __name__ == '__main__':
    app = create_app()
    debug = os.environ.get('FLASK_DEBUG', '1') == '1'  # debug ON por padrao em dev
    app.run(debug=debug, host='0.0.0.0', port=5000)