from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
import os
from dotenv import load_dotenv

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
app = None


def create_app():
    global app
    app = Flask(__name__)

    app.config['SECRET_KEY'] = 'crm-gizli-anahtar-2024-degisken'

    # DEBUG sadece FLASK_DEBUG=true ortam degiskeni acikca verilirse
    # acilir; production'da (Render vb.) varsayilan olarak kapali.
    app.config['DEBUG'] = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'

    # Uygulama artik sadece Neon PostgreSQL kullanir. DATABASE_URL yoksa
    # sessizce yerel SQLite'a dusmek yerine acikca hata verir.
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL ortam degiskeni tanimli degil. Bu uygulama artik "
            "sadece Neon PostgreSQL uzerinde calisir ve yerel SQLite'a "
            "otomatik gecis yapmaz. .env dosyasina DATABASE_URL ekleyin."
        )
    if database_url.startswith('postgresql://'):
        database_url = database_url.replace('postgresql://', 'postgresql+psycopg2://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['MAIL_SERVER'] = 'smtp.gmail.com'
    app.config['MAIL_PORT'] = 587
    app.config['MAIL_USE_TLS'] = True
    app.config['MAIL_USERNAME'] = ''
    app.config['MAIL_PASSWORD'] = ''

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    login_manager.login_view = 'login'
    login_manager.login_message = 'Lütfen giriş yapın.'

    from app.routes import register_routes
    register_routes(app)

    with app.app_context():
        db.create_all()
        from app.models import User
        if not User.query.first():
            admin = User(username='admin', email='admin@crm.com', full_name='Yönetici', role='admin')
            admin.set_password('1234')
            db.session.add(admin)
            db.session.commit()

    return app