from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db, login_manager

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(100))
    role = db.Column(db.String(20), default='user')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    tasks = db.relationship('Task', backref='owner', lazy=True)
    commissions = db.relationship('Commission', backref='user', lazy=True)
    deals = db.relationship('Deal', backref='seller', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def total_commission(self):
        return sum(c.amount for c in self.commissions if c.status == 'odenmedi')

    @property
    def paid_commission(self):
        return sum(c.amount for c in self.commissions if c.status == 'odendi')

    def __repr__(self):
        return f'<User {self.username}>'

class Commission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    deal_id = db.Column(db.Integer, db.ForeignKey('deal.id'), nullable=False)
    sale_amount = db.Column(db.Float, nullable=False)
    rate = db.Column(db.Float, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    customer_type = db.Column(db.String(20))
    status = db.Column(db.String(20), default='odenmedi')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime)
    manual_rate = db.Column(db.Float, nullable=True)  # Manuel olarak ayarlanan oran
    
    deal = db.relationship('Deal', backref='commissions')

    def __repr__(self):
        return f'<Commission {self.amount}>'

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50))
    last_name = db.Column(db.String(50))
    email = db.Column(db.String(120), unique=True, nullable=True)
    __table_args__ = (db.UniqueConstraint('first_name', 'last_name', name='unique_customer_name'),)
    phone = db.Column(db.String(20))
    
    company_name = db.Column(db.String(200))
    tax_office = db.Column(db.String(100))
    tax_id = db.Column(db.String(20))
    trade_registry = db.Column(db.String(50))
    company_phone = db.Column(db.String(20))
    company_address = db.Column(db.Text)
    company_email = db.Column(db.String(120))
    company_website = db.Column(db.String(200))
    
    contact_person = db.Column(db.String(100))
    contact_title = db.Column(db.String(50))
    contact_phone = db.Column(db.String(20))
    contact_email = db.Column(db.String(120))
    
    address = db.Column(db.Text)
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default='aktif')
    siparis_dongusu_gun = db.Column(db.Integer, default=120, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    deals = db.relationship('Deal', backref='customer', lazy=True)
    statements = db.relationship('CustomerStatement', backref='customer', lazy=True)

    @property
    def display_name(self):
        name = ' '.join(filter(None, [self.first_name, self.last_name]))
        if self.company_name:
            return f"{self.company_name} - {name}" if name else self.company_name
        return name or 'İsimsiz Müşteri'

    @property
    def is_new_customer(self):
        return Deal.query.filter_by(customer_id=self.id, stage='kazanilan').count() <= 1

    def __repr__(self):
        return f'<Customer {self.display_name}>'

class Deal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    deal_no = db.Column(db.Integer, unique=True, nullable=True)
    title = db.Column(db.String(100), nullable=False)
    subtotal = db.Column(db.Float, nullable=False, default=0)
    vat_rate = db.Column(db.Float, nullable=False, default=20)
    vat_amount = db.Column(db.Float, nullable=False, default=0)
    value = db.Column(db.Float, nullable=False, default=0)
    stage = db.Column(db.String(30), default='yeni')
    probability = db.Column(db.Integer, default=0)
    deal_date = db.Column(db.Date, default=datetime.utcnow)
    expected_close = db.Column(db.Date)
    valid_until = db.Column(db.Date)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
    items = db.relationship('DealItem', backref='deal', lazy=True, cascade='all, delete-orphan')
    production = db.relationship('Production', backref='deal', uselist=False)
    statements = db.relationship('CustomerStatement', backref='deal', lazy=True)
    invoices = db.relationship('Invoice', backref='deal', lazy=True)

    @property
    def display_no(self):
        if self.deal_no:
            return f'TKL-{self.deal_no:05d}'
        return f'TKL-{self.id:05d}'

    def calculate_totals(self):
        self.subtotal = sum(item.total_price for item in self.items)
        self.vat_amount = self.subtotal * (self.vat_rate / 100)
        self.value = self.subtotal + self.vat_amount

    @property
    def is_expiring_soon(self):
        if self.valid_until and self.stage not in ['kazanilan', 'kaybedilen', 'revize']:
            days_left = (self.valid_until - datetime.now().date()).days
            return 0 <= days_left <= 2
        return False

    @property
    def is_expired(self):
        if self.valid_until and self.stage not in ['kazanilan', 'kaybedilen', 'revize']:
            return self.valid_until < datetime.now().date()
        return False

    @property
    def days_until_expire(self):
        if self.valid_until:
            return (self.valid_until - datetime.now().date()).days
        return None

    def __repr__(self):
        return f'<Deal {self.title}>'

class DealItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(20), default='adet')
    unit_price = db.Column(db.Float, nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    deal_id = db.Column(db.Integer, db.ForeignKey('deal.id'), nullable=False)

# Uretim asama akisi: sirali liste, ileri/geri butonlari bu sirayi takip eder.
# 'iptal' bilincli olarak bu akisin disinda tutulur (sadece edit_production'dan elle secilir).
PRODUCTION_STAGES = [
    ('beklemede', 'Bekleyen'),
    ('kesme', 'Kesme'),
    ('baski', 'Baskı'),
    ('yapistirma', 'Yapıştırma'),
    ('kontrol', 'Kontrol'),
    ('hazir', 'Hazır'),
    ('sevkiyat', 'Sevkiyat'),
]
PRODUCTION_STAGE_KEYS = [key for key, _ in PRODUCTION_STAGES]
PRODUCTION_STAGE_LABELS = dict(PRODUCTION_STAGES)

# Her asamanin tahmini suresi (gun). Teslim tarihi tahmini, mevcut asamadan
# itibaren kalan asamalarin sureleri toplanarak hesaplanir (basit/sabit tahmin,
# gecmis uretim verisi biriktikce Kapasite Planlama maddesinde iyilestirilebilir).
PRODUCTION_STAGE_ESTIMATED_DAYS = {
    'beklemede': 0,
    'kesme': 1,
    'baski': 2,
    'yapistirma': 1,
    'kontrol': 1,
    'hazir': 0,
    'sevkiyat': 1,
}

class Production(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deal.id'), unique=True, nullable=False)
    status = db.Column(db.String(30), default='beklemede')
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    due_date = db.Column(db.Date, nullable=True)  # teslim tarihi - teklifteki beklenen kapanistan gelir, elle degistirilebilir
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship('ProductionItem', backref='production', lazy=True, cascade='all, delete-orphan')
    shipments = db.relationship('Shipment', backref='production', lazy=True, cascade='all, delete-orphan')
    status_logs = db.relationship('ProductionStatusLog', backref='production', lazy=True,
                                   cascade='all, delete-orphan', order_by='ProductionStatusLog.changed_at')

    @property
    def all_items_produced(self):
        return all(item.is_produced for item in self.items)

    @property
    def produced_items_count(self):
        return sum(1 for item in self.items if item.is_produced)

    @property
    def total_items_count(self):
        return len(self.items)

    @property
    def stage_index(self):
        try:
            return PRODUCTION_STAGE_KEYS.index(self.status)
        except ValueError:
            return None

    @property
    def stage_label(self):
        return PRODUCTION_STAGE_LABELS.get(self.status, self.status)

    @property
    def next_stage(self):
        idx = self.stage_index
        if idx is None or idx >= len(PRODUCTION_STAGES) - 1:
            return None
        return PRODUCTION_STAGES[idx + 1]

    @property
    def prev_stage(self):
        idx = self.stage_index
        if not idx:
            return None
        return PRODUCTION_STAGES[idx - 1]

    @property
    def estimated_due_date(self):
        idx = self.stage_index
        if idx is None or self.status == 'sevkiyat':
            return None
        remaining_days = sum(PRODUCTION_STAGE_ESTIMATED_DAYS.get(key, 0) for key, _ in PRODUCTION_STAGES[idx:])
        return datetime.utcnow().date() + timedelta(days=remaining_days)

class ProductionStatusLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    production_id = db.Column(db.Integer, db.ForeignKey('production.id'), nullable=False, index=True)
    from_status = db.Column(db.String(30))
    to_status = db.Column(db.String(30), nullable=False)
    changed_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    changed_at = db.Column(db.DateTime, default=datetime.utcnow)

    changed_by = db.relationship('User')

    @property
    def from_label(self):
        return PRODUCTION_STAGE_LABELS.get(self.from_status, self.from_status or '-')

    @property
    def to_label(self):
        return PRODUCTION_STAGE_LABELS.get(self.to_status, self.to_status)

class ProductionItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    production_id = db.Column(db.Integer, db.ForeignKey('production.id'), nullable=False)
    deal_item_id = db.Column(db.Integer, db.ForeignKey('deal_item.id'), nullable=True)
    description = db.Column(db.String(200), nullable=False)
    planned_quantity = db.Column(db.Float, nullable=False)
    produced_quantity = db.Column(db.Float, default=0)
    unit = db.Column(db.String(20), default='adet')
    status = db.Column(db.String(30), default='bekleniyor')
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def is_produced(self):
        return self.produced_quantity >= self.planned_quantity

class Shipment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    production_id = db.Column(db.Integer, db.ForeignKey('production.id'), nullable=False)
    ship_date = db.Column(db.Date)
    tracking_number = db.Column(db.String(100))
    carrier = db.Column(db.String(100))
    status = db.Column(db.String(30), default='hazirlaniyor')
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    items = db.relationship('ShipmentItem', backref='shipment', lazy=True, cascade='all, delete-orphan')

class ShipmentItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey('shipment.id'), nullable=False)
    production_item_id = db.Column(db.Integer, db.ForeignKey('production_item.id'), nullable=True)
    description = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(20), default='adet')
    weight_kg = db.Column(db.Float)
    unit_price = db.Column(db.Float, default=0)
    total_price = db.Column(db.Float, default=0)

class CustomerStatement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    deal_id = db.Column(db.Integer, db.ForeignKey('deal.id'), nullable=True)
    type = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_no = db.Column(db.Integer, unique=True, nullable=True)
    type = db.Column(db.String(20), nullable=False, default='fatura')  # fatura / irsaliye
    deal_id = db.Column(db.Integer, db.ForeignKey('deal.id'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    date = db.Column(db.Date, default=datetime.utcnow)
    subtotal = db.Column(db.Float, nullable=False, default=0)
    vat_rate = db.Column(db.Float, nullable=False, default=20)
    vat_amount = db.Column(db.Float, nullable=False, default=0)
    total = db.Column(db.Float, nullable=False, default=0)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    customer = db.relationship('Customer', backref='invoices')
    items = db.relationship('InvoiceItem', backref='invoice', lazy=True, cascade='all, delete-orphan')

    @property
    def display_no(self):
        prefix = 'FAT-' if self.type == 'fatura' else 'IRS-'
        if self.invoice_no:
            return f'{prefix}{self.invoice_no:05d}'
        return f'{prefix}{self.id:05d}'

    def calculate_totals(self):
        self.subtotal = sum(item.total_price for item in self.items)
        self.vat_amount = self.subtotal * (self.vat_rate / 100)
        self.total = self.subtotal + self.vat_amount

class InvoiceItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False)
    description = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(20), default='adet')
    unit_price = db.Column(db.Float, nullable=False)
    total_price = db.Column(db.Float, nullable=False)

class Reminder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deal.id'), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text)
    remind_date = db.Column(db.Date, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    customer = db.relationship('Customer', backref='reminders')
    deal = db.relationship('Deal', backref='reminders')

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    sku = db.Column(db.String(50), unique=True)
    description = db.Column(db.Text)
    unit = db.Column(db.String(20), default='adet')
    stock_quantity = db.Column(db.Float, default=0)
    min_stock = db.Column(db.Float, default=0)
    cost_price = db.Column(db.Float, default=0)
    sell_price = db.Column(db.Float, default=0)
    category = db.Column(db.String(100))
    status = db.Column(db.String(20), default='aktif')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def is_low_stock(self):
        return self.stock_quantity <= self.min_stock

    def __repr__(self):
        return f'<Product {self.name}>'

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    due_date = db.Column(db.Date)
    due_time = db.Column(db.Time)
    priority = db.Column(db.String(20), default='orta')
    status = db.Column(db.String(20), default='yapilacak')
    category = db.Column(db.String(50))
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deal.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    
    customer = db.relationship('Customer', backref='tasks')
    deal = db.relationship('Deal', backref='tasks')

    def __repr__(self):
        return f'<Task {self.title}>'

class CustomerVisit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    visit_date = db.Column(db.Date, default=datetime.utcnow)
    notes = db.Column(db.Text)
    visit_type = db.Column(db.String(50), default='ziyaret')  # ziyaret, gorisme, telefon
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    customer = db.relationship('Customer', backref='visits')
    user = db.relationship('User', backref='visits')

    def __repr__(self):
        return f'<CustomerVisit {self.customer_id} - {self.visit_date}>'

class DailyReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    report_date = db.Column(db.Date, default=datetime.utcnow, nullable=False)
    customer_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default='takip_edilecek')  # tamamlandi, fiyat_verilecek, takip_edilecek
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
    
    user = db.relationship('User', backref='daily_reports')
    customer = db.relationship('Customer', backref='daily_reports')

    def __repr__(self):
        return f'<DailyReport {self.customer_name} - {self.report_date}>'

class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=True)
    amount = db.Column(db.Float, nullable=False)
    payment_date = db.Column(db.Date, default=datetime.utcnow)
    payment_method = db.Column(db.String(50))  # nakit, kredi_karti, havale, cek
    reference_no = db.Column(db.String(100))  # ödeme referans no
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default='beklemede')  # beklemede, odendi, iptal
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    customer = db.relationship('Customer', backref='payments')
    invoice = db.relationship('Invoice', backref='payments')
    user = db.relationship('User', backref='payments')

    def __repr__(self):
        return f'<Payment {self.amount} ₺ - {self.customer.display_name}>'

class PotentialCustomer(db.Model):
    SECTORS = ['Dönerci', 'Restoran', 'Market', 'Bakkal', 'Kuruyemişçi', 'Burgerci',
               'Tekstil', 'Çay-Kahve', 'Fırın-Pastane', 'Baharatçı', 'Şekerci', 'Diğer']
    PRODUCTS = ['Kare Dipli Kese Kağıdı', 'Dürüm-Sarma Kağıdı', 'Tepsi Altı Ambalaj Kağıdı',
                'Taşıma Çantası', 'Baskılı Atlet Poşet', 'Market Poşeti', 'Baskılı Doypack']
    SOURCES = ['Elle', 'Otomatik']
    STATUSES = ['Aranacak', 'Arandı-İlgilenmedi', 'Arandı-Fiyat İstedi', 'Müşteriye Dönüştürüldü']

    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    city = db.Column(db.String(100))
    sector = db.Column(db.String(50))
    interested_products = db.Column(db.String(500))  # virgulle ayrilmis liste
    source = db.Column(db.String(20), default='Elle')
    status = db.Column(db.String(30), default='Aranacak')
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    converted_customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)

    converted_customer = db.relationship('Customer', backref='converted_from')

    @property
    def product_list(self):
        return [p for p in (self.interested_products or '').split(',') if p]

    def __repr__(self):
        return f'<PotentialCustomer {self.company_name}>'

class PlacesSearchConfig(db.Model):
    """Tekil satir (id=1) - Google Places otomatik arama ayarlari."""
    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, default=False, nullable=False)
    last_combo_index = db.Column(db.Integer, default=0, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class PlacesSearchLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    run_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    city = db.Column(db.String(100))
    sector = db.Column(db.String(50))
    search_query = db.Column(db.String(300))
    request_count = db.Column(db.Integer, default=0)
    results_found = db.Column(db.Integer, default=0)
    new_companies = db.Column(db.Integer, default=0)
    triggered_by = db.Column(db.String(20), default='otomatik')  # otomatik / manuel
    error = db.Column(db.String(500))

    def __repr__(self):
        return f'<PlacesSearchLog {self.city}/{self.sector} - {self.run_at}>'
