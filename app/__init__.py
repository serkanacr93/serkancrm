from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
from dotenv import load_dotenv

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
csrf = CSRFProtect()
# Varsayilan depolama (bellek ici) tek instance'lik bir Render web servisi
# icin yeterli - birden fazla instance'a yatay olcekleme yapilirsa paylasimli
# bir backend (ör. Redis) gerekir, o zaman storage_uri ile ayarlanmali.
limiter = Limiter(key_func=get_remote_address)
app = None


def create_app():
    global app
    app = Flask(__name__)

    # DATABASE_URL ile ayni desen: sabit kodlanmis bir SECRET_KEY oturum
    # imzalama anahtarinin repoda duz metin olarak durmasi anlamina gelirdi -
    # artik ortam degiskeninden okunuyor, eksikse acikca hata veriyor.
    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key:
        raise RuntimeError(
            "SECRET_KEY ortam degiskeni tanimli degil. .env dosyasina "
            "(yerelde) veya Render ortam degiskenlerine (production'da) "
            "guclu, rastgele bir SECRET_KEY eklenmeli."
        )
    app.config['SECRET_KEY'] = secret_key

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
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.login_view = 'login'
    login_manager.login_message = 'Lütfen giriş yapın.'

    from app.routes import register_routes
    register_routes(app)

    @app.template_global()
    def asset_url(filename):
        """static/ altindaki bir dosya icin, dosyanin degisiklik tarihini
        (mtime) query string olarak ekleyen bir URL dondurur (orn.
        customer-search.js?v=1735...). Boylece JS/CSS'te bir duzeltme
        yapilip deploy edildiginde, tarayicinin eski (Cache-Control:
        no-cache olsa bile bazi ara katmanlarda/proxy'lerde onbelleklenmis
        olabilecek) surumu kullanmaya devam etmesi onlenir - URL degistigi
        icin tamamen YENI bir kaynak olarak ele alinir."""
        from flask import url_for
        static_path = os.path.join(app.static_folder, filename)
        try:
            version = int(os.path.getmtime(static_path))
        except OSError:
            version = 0
        return url_for('static', filename=filename) + f'?v={version}'

    with app.app_context():
        db.create_all()
        from app.models import User
        if not User.query.first():
            # Mevcut kullanicilara (ozellikle User #1'e) DOKUNMUYOR - bu blok
            # sadece User tablosu tamamen BOSSA (gercek ilk kurulum) calisir.
            # Onceden sabit kodlanmis 'serkan'/'2255' herkese acik bir
            # varsayilan sifreydi - artik DEFAULT_ADMIN_PASSWORD ortam
            # degiskeninden okunuyor; o da tanimli degilse (ör. yerel ilk
            # kurulum) rastgele guclu bir sifre uretilip sunucu loguna
            # BIR KEZ yazdiriliyor, boylece hicbir zaman bilinen/sabit bir
            # varsayilan sifre olusmuyor.
            import secrets as _secrets
            admin_password = os.environ.get('DEFAULT_ADMIN_PASSWORD')
            if not admin_password:
                admin_password = _secrets.token_urlsafe(12)
                print(
                    f"\n{'='*70}\n"
                    f"ILK KURULUM: varsayilan admin kullanicisi olusturuldu.\n"
                    f"  Kullanici adi: serkan\n"
                    f"  Sifre (bu SADECE bu ilk calistirmada gosterilir): {admin_password}\n"
                    f"Bu sifreyi hemen not alip guvenli bir yerde saklayin, "
                    f"ardindan ilk girişte degistirin.\n{'='*70}\n"
                )
            admin = User(username='serkan', email='admin@crm.com', full_name='Yönetici', role='admin')
            admin.set_password(admin_password)
            db.session.add(admin)
            db.session.commit()

    # Debug reloader'da 2 surec olustugu icin (izleyici + gercek worker),
    # zamanlayiciyi sadece gercek worker surecinde (ya da production'da,
    # reloader hic yokken) baslat - aksi halde saatlik is 2 kez tetiklenir.
    if not app.config['DEBUG'] or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        from app.scheduler import start_scheduler
        start_scheduler(app)

    return app