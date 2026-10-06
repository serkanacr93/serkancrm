from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db, login_manager

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def format_price_precise(value):
    """Birim fiyat gibi yuksek hassasiyetli deger gerekebilecek alanlar
    icin - eskiden HER YERDE '{:,.2f}' kullanildigi icin 0.012458 gibi
    2 ondalikten fazla girilen bir fiyat ekranda/PDF'te '0.01'e
    yuvarlanmis GORUNUYORDU (veritabaninda deger dogru duruyordu, sadece
    GORUNUM yuvarliyordu). Python'un str(float)'i IEEE754'un en kisa
    round-trip temsilini verdigi icin (sabit '.10f' formati aksine, buyuk
    tam sayili degerlerde '1234567.8899999999' gibi ikili temsil
    gurultusu ACIGA CIKARMAZ) temel alinir; en az 2 ondalik gosterilir
    (5 -> '5.00'), 2'den fazla ondalik varsa TAMAMI korunur, kirpilmaz."""
    if value is None:
        return '-'
    value = float(value)
    text = str(value)
    if 'e' in text or 'E' in text:
        text = f'{value:.10f}'.rstrip('0').rstrip('.')
    sign = ''
    if text.startswith('-'):
        sign = '-'
        text = text[1:]
    int_part, _, dec_part = text.partition('.')
    if len(dec_part) < 2:
        dec_part = dec_part.ljust(2, '0')
    return f'{sign}{int(int_part):,}.{dec_part}'

CURRENCY_SYMBOLS = {'TRY': '₺', 'EUR': '€', 'USD': '$', 'GBP': '£'}

def format_price_tr(value, currency='TRY'):
    """B6 (2026-10-06): sistem geneli (toplam/bakiye/odeme gibi - birim
    fiyat icin format_price_precise KULLANILMAYA devam eder, bu AYRI bir
    kural) para gosterimi - tam sayiysa ondalik GOSTERILMEZ (150.000₺),
    degilse 2 ondalige YUVARLANIR (354,8781 -> 354,88₺). Turkce ayrac
    (bin: nokta, ondalik: virgul), sembol sona BITISIK, para birimine
    gore (₺/€/$/£). Hesaplama/kayitli degerler DEGISMEZ - sadece gorunum."""
    if value is None:
        return '-'
    value = float(value)
    symbol = CURRENCY_SYMBOLS.get(currency, '₺')
    sign = '-' if value < 0 else ''
    value = abs(value)
    if value == int(value):
        int_with_sep = f'{int(value):,}'.replace(',', '.')
        return f'{sign}{int_with_sep}{symbol}'
    rounded = round(value, 2)
    int_part = int(rounded)
    dec_part = round((rounded - int_part) * 100)
    if dec_part == 100:
        int_part += 1
        dec_part = 0
    int_with_sep = f'{int_part:,}'.replace(',', '.')
    return f'{sign}{int_with_sep},{dec_part:02d}{symbol}'

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
    # Is 2 - otomatik, benzersiz, siral musteri numarasi (M-0001, M-0002, ...).
    # routes.py'deki _next_musteri_no()/_musteri_no_max() ile atanir - burada
    # DB-seviyesinde default YOK, cunku toplu ice aktarimlarda (CSV/Excel/VCF)
    # ayni flush icinde her satirin ayni "sonraki" degeri gormesini onlemek
    # icin Python tarafinda tek bir sayacla artiriliyor.
    musteri_no = db.Column(db.String(10), unique=True, nullable=True)
    first_name = db.Column(db.String(50))
    last_name = db.Column(db.String(50))
    email = db.Column(db.String(120), unique=True, nullable=True)
    __table_args__ = (db.UniqueConstraint('first_name', 'last_name', name='unique_customer_name'),)
    # 20 karakter gercek kullanimda cok dar kaliyordu - satis ekibi bazen
    # tek alana birden fazla telefon/vergi no yapistiriyor, bu da INSERT/UPDATE
    # aninda StringDataRightTruncation hatasiyla teklif olusturmayi tamamen
    # kirıyordu (bkz. Is A). 50/30'a genisletildi - veri kaybi olmadan.
    phone = db.Column(db.String(50), index=True)

    company_name = db.Column(db.String(200))
    tax_office = db.Column(db.String(100))
    tax_id = db.Column(db.String(30))
    trade_registry = db.Column(db.String(50))
    company_phone = db.Column(db.String(50))
    company_address = db.Column(db.Text)
    company_email = db.Column(db.String(120))
    company_website = db.Column(db.String(200))

    contact_person = db.Column(db.String(100))
    contact_title = db.Column(db.String(50))
    contact_phone = db.Column(db.String(50))
    contact_email = db.Column(db.String(120))
    
    address = db.Column(db.Text)
    notes = db.Column(db.Text)
    # Musterinin varsayilan tasarim gorseli - dosya yolu (static/uploads/tasarimlar/...),
    # is emri PDF'inde gosterilir, uretim bazinda edit_production'dan override edilebilir.
    tasarim_gorseli = db.Column(db.String(300), nullable=True)
    status = db.Column(db.String(20), default='aktif', index=True)
    siparis_dongusu_gun = db.Column(db.Integer, default=120, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Is 1 - musteri sahipligi: yeni musteri eklenirken ekleyen kullaniciya
    # otomatik atanir; eski kayitlar icin geriye donuk olarak ilk Deal/
    # DailyReport'un user_id'sinden doldurulur (bkz. backfill migration).
    # Takip Gerekiyor/60 gunluk liste gibi "benim musterilerim" gorunumlerinde
    # kullanilir - Deal'in user_id'sinden (satis sahipligi) AYRI bir kavram.
    owner_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)

    deals = db.relationship('Deal', backref='customer', lazy=True)
    owner = db.relationship('User', foreign_keys=[owner_user_id])
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

    @property
    def total_invoiced(self):
        """Cari hesap (Is F) - GERCEK Invoice kayitlarindan canli hesaplanir,
        onbellege alinmaz. Sadece 'fatura' tipi belgeler tutar sayilir
        (irsaliyenin bedeli yoktur)."""
        return sum(inv.total for inv in Invoice.query.filter_by(customer_id=self.id, type='fatura').all())

    @property
    def total_uninvoiced_won(self):
        """Cari Hesap Birlestirme duzeltmesi: kazanilmis (stage='kazanilan')
        ama bu teklif icin HENUZ hicbir fatura kesilmemis tekliflerin toplam
        (KDV dahil) degeri. Onceden bu tutar Cari Hesap Ozeti'nde HIC
        gorunmuyordu (sadece Invoice/Payment'a bakiyordu) - canli veride
        kazanilan tekliflerin buyuk kismi (30'da 22'si) henuz faturalanmamis
        oldugu icin bu, musterinin gercek borcunun onemli bir kismini
        gostermiyordu.

        Is 5A: sadece HENUZ URETIME BASLANMAMIS (Production.status='uretimde'
        ya da hic Production kaydi yok - approve_deal normalde otomatik
        olusturur ama garanti olsun diye kontrol ediliyor) tekliflerin
        bakiyeye dahil EDILMEMESI icin - musteri gercekte henuz 'Hazir'/
        'Sevkiyat' asamasina gelmemis bir siparisin borcunu gormemeli."""
        invoiced_deal_ids = db.session.query(Invoice.deal_id).filter(
            Invoice.type == 'fatura', Invoice.deal_id.isnot(None)
        )
        deals = Deal.query.filter(
            Deal.customer_id == self.id, Deal.stage == 'kazanilan',
            ~Deal.id.in_(invoiced_deal_ids)
        ).all()
        return sum(
            d.value for d in deals
            if d.production and d.production.status in ('hazir', 'sevkiyat')
        )

    @property
    def total_collected(self):
        """Musteriye ait, 'odendi' durumundaki TUM Payment kayitlarinin toplami
        (fatura/teklif baglantisindan bagimsiz - gercek tahsil edilen nakit)."""
        return sum(p.amount for p in self.payments if p.status == 'odendi')

    @property
    def balance(self):
        """Kalan Bakiye = Faturalanan + Faturalanmamis Kazanilan Teklif -
        Tahsil Edilen. Pozitif: musteriden alacagimiz var. Sifir/negatif:
        odeme tamam ya da fazla odenmis. Bu, Cari Hesap Ozeti sayfasindaki
        toplu (GROUP BY) hesaplamayla AYNI mantigi kullanir (bkz.
        cari_hesap_ozeti() route'u) - iki sayfa artik hep ayni bakiyeyi
        gosterir."""
        return self.total_invoiced + self.total_uninvoiced_won - self.total_collected

    def __repr__(self):
        return f'<Customer {self.display_name}>'

class CustomerOldName(db.Model):
    """Is 8: musteri birlestirme sirasinda silinen kaydin ad/firma bilgisi
    - ana (kalan) musteride 'eski isimler' olarak saklanir. Iki amaca
    hizmet eder: (1) Is 6 aramasinda eski isimle de bulunabilme, (2)
    kim/ne zaman birlestirdi logu (bu kayit zaten birlestirme aninda
    olusturuldugu icin created_at + merged_by_user_id bu logu tasir,
    ayri bir log tablosu gerekmiyor)."""
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False, index=True)
    eski_ad = db.Column(db.String(300), nullable=False)
    eski_musteri_no = db.Column(db.String(20), nullable=True)
    merged_from_customer_id = db.Column(db.Integer, nullable=True)  # silinen kaydin ESKI id'si (referans/iz icin, FK degil - o kayit artik yok)
    merged_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    customer = db.relationship('Customer', backref='old_names')
    merged_by = db.relationship('User')

class HistoricalClosureLog(db.Model):
    """Is 2 - Gecmis Kayit Duzeltme: program tam kullanilmadan once acik
    kalmis eski teklif/uretimler icin alinan karari + GERI ALMAK icin
    eski durumu saklar. 'kontrol_edildi' (Uretimde devam ediyor secenegi)
    de dahil - o secenekte hicbir Deal/Production alani degismez, sadece
    bu log 'bir daha listede cikma' isareti gorevi gorur."""
    id = db.Column(db.Integer, primary_key=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deal.id'), nullable=False, index=True)
    action = db.Column(db.String(20), nullable=False)  # 'tamamlandi' / 'kontrol_edildi' / 'iptal'
    eski_deal_stage = db.Column(db.String(20), nullable=True)
    eski_production_status = db.Column(db.String(20), nullable=True)
    created_invoice_id = db.Column(db.Integer, nullable=True)  # geri alinirsa silinir
    created_payment_id = db.Column(db.Integer, nullable=True)  # geri alinirsa silinir
    kalan_borc = db.Column(db.Float, nullable=True)
    neden = db.Column(db.Text, nullable=True)  # 'iptal' secenegi icin opsiyonel not
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reverted_at = db.Column(db.DateTime, nullable=True)

    deal = db.relationship('Deal')
    user = db.relationship('User')

class Deal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    deal_no = db.Column(db.Integer, unique=True, nullable=True)
    title = db.Column(db.String(100), nullable=False)
    subtotal = db.Column(db.Float, nullable=False, default=0)
    vat_rate = db.Column(db.Float, nullable=False, default=20)
    vat_amount = db.Column(db.Float, nullable=False, default=0)
    value = db.Column(db.Float, nullable=False, default=0)
    stage = db.Column(db.String(30), default='yeni', index=True)
    probability = db.Column(db.Integer, default=0)
    deal_date = db.Column(db.Date, default=datetime.utcnow)
    expected_close = db.Column(db.Date)
    valid_until = db.Column(db.Date)
    notes = db.Column(db.Text)
    # Odeme sekli - serbest metin, teklif PDF'indeki "ODEME SEKLI" kutusuna yansir
    vade_gun = db.Column(db.String(50))
    pesinat = db.Column(db.String(100))
    bakiye_odemesi = db.Column(db.String(100))
    # Odeme takvimi (Is D) - teklif onaylanip uretime aktarilirken (approve_deal)
    # zorunlu olarak istenir, yukaridaki serbest metin alanlarindan farkli
    # olarak yapisal ve zorunludur - musteriyle kesinlesmis odeme planini temsil eder.
    pesinat_orani = db.Column(db.Float, nullable=True)  # yuzde, orn. 50.0
    pesinat_tarihi = db.Column(db.Date, nullable=True)  # beklenen veya gerceklesen odeme tarihi
    bakiye_tarihi = db.Column(db.Date, nullable=True)  # bakiyenin beklenen odeme tarihi
    # Coklu Para Birimi - subtotal/vat_amount/value bu para biriminde tutulur
    # (TRY disindaki tekliflerde TL'ye cevrilmis bir deger DEGIL, dogrudan
    # doviz tutaridir). kullanilan_kur, teklif olusturulurken/guncellenirken
    # TCMB'den cekilen (veya elle girilen) GOSTERGE kurdur - sadece tutari
    # yaklasik TL karsiligiyla gostermek icin kullanilir. Gercek tahsilat
    # kurlari Payment.kur_orani'nda ayri ayri tutulur (kismi odemeler farkli
    # gunlerde farkli kurla gelebilir) - Deal'de tek bir "kesin" kur YOKTUR.
    para_birimi = db.Column(db.String(3), default='TRY', nullable=False)  # TRY / EUR / USD
    kullanilan_kur = db.Column(db.Float, nullable=True)  # 1 birim para_birimi = ? TL (gosterge)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    items = db.relationship('DealItem', backref='deal', lazy=True, cascade='all, delete-orphan')
    production = db.relationship('Production', backref='deal', uselist=False)
    statements = db.relationship('CustomerStatement', backref='deal', lazy=True)
    invoices = db.relationship('Invoice', backref='deal', lazy=True)
    # NOT: User.deals = db.relationship('Deal', backref='seller', ...) zaten
    # var (bkz. User modeli) - deal.seller ile olusturan kullaniciya erisilir,
    # ayri bir 'user' iliskisi acmaya gerek yok (Is 2).

    @property
    def display_no(self):
        if self.deal_no:
            return f'TKL-{self.deal_no:05d}'
        return f'TKL-{self.id:05d}'

    @property
    def para_birimi_sembol(self):
        return CURRENCY_SYMBOLS.get(self.para_birimi, self.para_birimi)

    @property
    def tl_karsiligi(self):
        """Doviz teklifin kullanilan_kur'a gore YAKLASIK TL karsiligi -
        sadece gosterge/bilgi amacli, gercek tahsilat Payment.kur_orani
        ile hesaplanir."""
        if self.para_birimi == 'TRY' or not self.kullanilan_kur:
            return None
        return self.value * self.kullanilan_kur

    def calculate_totals(self, items=None):
        """items verilirse (yeni olusturulan/henuz self.items'a yuklenmemis
        DealItem listesi) onlar uzerinden hesaplar - self.items'a erismek,
        henuz yuklenmemis bir iliski icin ekstra bir SELECT tetikler (bkz.
        add_deal), items parametresiyle bu onlenir."""
        source = items if items is not None else self.items
        self.subtotal = sum(item.total_price for item in source)
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

    @property
    def pesinat_tutari(self):
        """Onaylanirken girilen pesinat oranindan (yuzde) hesaplanan tutar."""
        if self.pesinat_orani is None:
            return None
        return self.value * (self.pesinat_orani / 100)

    @property
    def bakiye_tutari(self):
        if self.pesinat_orani is None:
            return None
        return self.value - self.pesinat_tutari

    @property
    def paid_amount(self):
        """Bu teklife (avans/pesinat asamasinda) baglanmis, 'odendi' durumundaki
        Payment kayitlarinin toplami - Is E'de sevkiyat oncesi odeme kontrolu icin kullanilir."""
        return sum(p.amount for p in self.payments if p.status == 'odendi')

    @property
    def outstanding_amount(self):
        return max(0, self.value - self.paid_amount)

    @property
    def payment_complete(self):
        return self.outstanding_amount <= 0.01

    def __repr__(self):
        return f'<Deal {self.title}>'

class DealItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(20), default='adet')
    unit_price = db.Column(db.Float, nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    deal_id = db.Column(db.Integer, db.ForeignKey('deal.id'), nullable=False, index=True)
    # Is 4 - 'uretim': kendi atolyemizde uretiliyor (Is Emri surecine dahil).
    # 'ticaret': hazir alinip satiliyor (uretim asama takibi atlanir).
    urun_tipi = db.Column(db.String(20), default='uretim', nullable=False)

    # Teklif PDF'indeki urun tablosu sutunlari - onceden formda hic yoktu,
    # PDF'te her zaman '-' gorunuyordu. Hepsi opsiyonel, doldurulmazsa PDF'te
    # yine '-' kalir. Boy/En, olcu/taban_olcusu ile ayni gerekce ile
    # (serbest metin, "12x20" gibi kesirli/karisik degerler de girilebilsin
    # diye) String tutuluyor - Float degil.
    kagit_cinsi = db.Column(db.String(100), nullable=True)
    # 20 karakter gercek kullanimda dar kaliyordu (orn. "145 milimetre
    # yaklasik" gibi dogal dil ifadeleri 20'yi asiyor, PDF sarma duzeltmesi
    # bu tur degerleri gostermek icin eklendi - once veri katmaninda
    # kirpilmesi engellenmeli). 50'ye genisletildi (renk ile ayni).
    boy = db.Column(db.String(50), nullable=True)
    en = db.Column(db.String(50), nullable=True)
    # Is 1 - korfez/korugu olcusu (kraft torba/poset uretiminde yan katlama
    # payi) - Boy/En ile ayni gerekce (serbest metin, opsiyonel).
    korugu = db.Column(db.String(50), nullable=True)
    renk = db.Column(db.String(50), nullable=True)
    teslim_tarihi = db.Column(db.Date, nullable=True)
    # Is 3 - kalem bazli numune gorseli (opsiyonel, static/ koku itibariyle
    # goreli yol) - Teklif PDF'inde ilgili kalemin yaninda gosterilir.
    numune_gorseli = db.Column(db.String(300), nullable=True)

# Uretim asama akisi: basit 3 durumlu siralama. 'iptal' bilincli olarak bu
# akisin disinda tutulur (sadece edit_production'dan elle secilir).
PRODUCTION_STAGES = [
    ('uretimde', 'Üretimde'),
    ('hazir', 'Hazır'),
    ('sevkiyat', 'Sevkiyat'),
]
PRODUCTION_STAGE_KEYS = [key for key, _ in PRODUCTION_STAGES]
PRODUCTION_STAGE_LABELS = dict(PRODUCTION_STAGES)

# Ticaret tipi (hazir alinip satilan) urunler icin ayri, basit 3 durumlu
# akis - uretim asama takibine (yukaridaki PRODUCTION_STAGES) hic girmez.
# ProductionItem.ticaret_durumu ve ManualTedarikEntry.durum bu anahtarlari
# kullanir - /tedarik-takip sayfasi ve production_detail'deki gomulu takip
# ayni degerleri paylasarak senkron kalir.
TICARET_STAGES = [
    ('siparis_edildi', 'Sipariş Edildi'),
    ('tedarik_edildi', 'Tedarik Edildi'),
    ('teslime_hazir', 'Teslime Hazır'),
]
TICARET_STAGE_KEYS = [key for key, _ in TICARET_STAGES]
TICARET_STAGE_LABELS = dict(TICARET_STAGES)

class Production(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deal.id'), unique=True, nullable=False)
    status = db.Column(db.String(30), default='uretimde', index=True)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    due_date = db.Column(db.Date, nullable=True)  # teslim tarihi - teklifteki beklenen kapanistan gelir, elle degistirilebilir
    # Musterinin varsayilan tasarim gorselini bu uretime ozel gecersiz kilar (opsiyonel)
    tasarim_gorseli_override = db.Column(db.String(300), nullable=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship('ProductionItem', backref='production', lazy=True, cascade='all, delete-orphan')
    shipments = db.relationship('Shipment', backref='production', lazy=True, cascade='all, delete-orphan')

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
    def tasarim_gorseli(self):
        """Uretime ozel override varsa onu, yoksa musterinin varsayilan
        tasarim gorselini dondurur (Is Emri PDF'inde kullanilir)."""
        return self.tasarim_gorseli_override or self.deal.customer.tasarim_gorseli

    @property
    def stage_label(self):
        return PRODUCTION_STAGE_LABELS.get(self.status, self.status)

    @property
    def stage_index(self):
        try:
            return PRODUCTION_STAGE_KEYS.index(self.status)
        except ValueError:
            return None

    @property
    def latest_shipment(self):
        return max(self.shipments, key=lambda s: s.created_at) if self.shipments else None

    @property
    def is_delivered(self):
        """'sevkiyat' asamasindaki bir is emrinin en son sevkiyati fiilen
        teslim edilmis mi - Uretim Listesi'ndeki 'Sevkiyatta'/'Tamamlandi'
        sekmelerini ayirt etmek icin kullanilir (Is 3)."""
        latest = self.latest_shipment
        return self.status == 'sevkiyat' and latest is not None and latest.status == 'teslim_edildi'

    @property
    def uretim_items(self):
        return [i for i in self.items if i.urun_tipi != 'ticaret']

    @property
    def ticaret_items(self):
        return [i for i in self.items if i.urun_tipi == 'ticaret']

    @property
    def specs_missing(self):
        """Kagit Cinsi/Olcu gibi is emri spesifikasyonlari teklif olusturulurken
        degil, uretim asamasinda atolye tarafindan elle giriliyor - hicbir
        yerde zorunlu tutulmuyor, bu yuzden bazi uretimlerde unutuluyor (Is B).
        Bu, o durumu goze carpar hale getirmek icin kullanilir. Is 4: 'ticaret'
        tipi kalemler atolyede uretilmedigi icin bu kontrolun disinda tutulur."""
        return any(not item.kagit_tipi or not item.olcu for item in self.uretim_items)

    @property
    def gecen_gun(self):
        """Is emrinin olusturulmasindan (Production.created_at) bugune kadar
        gecen gun sayisi - Uretim Listesi'ndeki 'Gecen Gun' sutunu."""
        return (datetime.utcnow().date() - self.created_at.date()).days

    @property
    def termin_durumu(self):
        """due_date'e gore 'kirmizi' (termin asildi), 'sari' (gecen sure,
        toplam sureye orantiyla %70'i asti), 'normal' veya None (due_date
        girilmemis) dondurur. due_date yoksa renksiz sadece Gecen Gun
        sayisi gosterilir (Uretim Listesi Is 1)."""
        if not self.due_date:
            return None
        today = datetime.utcnow().date()
        created = self.created_at.date()
        if today > self.due_date:
            return 'kirmizi'
        total_window = (self.due_date - created).days
        if total_window <= 0:
            return 'kirmizi'
        elapsed = (today - created).days
        if elapsed / total_window >= 0.7:
            return 'sari'
        return 'normal'

class ProductionItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    production_id = db.Column(db.Integer, db.ForeignKey('production.id'), nullable=False, index=True)
    deal_item_id = db.Column(db.Integer, db.ForeignKey('deal_item.id'), nullable=True)
    description = db.Column(db.String(200), nullable=False)
    planned_quantity = db.Column(db.Float, nullable=False)
    produced_quantity = db.Column(db.Float, default=0)
    unit = db.Column(db.String(20), default='adet')
    status = db.Column(db.String(30), default='bekleniyor')
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Is Emri PDF'inde gosterilen uretim spesifikasyonlari - deal olusturulurken
    # degil, uretim asamasinda atolye icin ayrica dolduruluyor.
    olcu = db.Column(db.String(100))
    baski_bilgisi = db.Column(db.String(100))
    kagit_tipi = db.Column(db.String(100))
    gramaj = db.Column(db.String(50))
    kac_kg = db.Column(db.String(50))

    # Is 4 - DealItem.urun_tipi'nden approve_deal aninda kopyalanir.
    # 'ticaret' ise atolye uretim akisina (Uretimde/Hazir spesifikasyonlari)
    # girmez, bunun yerine basit ticaret_durumu ile takip edilir.
    urun_tipi = db.Column(db.String(20), default='uretim', nullable=False)
    ticaret_durumu = db.Column(db.String(20), nullable=True)  # siparis_edildi / teslime_hazir

    # Is 5 - ayni olcudeki is emri kalemlerini gruplamak icin serbest metin
    # (orn. "12x20"). Uretim planlama altyapisi (bkz. /uretim-planlama).
    taban_olcusu = db.Column(db.String(50), nullable=True)

    @property
    def is_produced(self):
        if self.urun_tipi == 'ticaret':
            return self.ticaret_durumu == 'teslime_hazir'
        return self.produced_quantity >= self.planned_quantity

class ManualPlanningEntry(db.Model):
    """Is 2 - /uretim-planlama sayfasinda, sistemde formal bir teklifi
    olmayan (orn. telefonla gelen) siparisleri elle bir gramaj/olcu grubuna
    eklemek icin. Gercek ProductionItem kayitlarindan 'Manuel' etiketiyle
    ayirt edilir, herhangi bir Deal/Production'a bagli degildir."""
    id = db.Column(db.Integer, primary_key=True)
    group_key = db.Column(db.String(100), nullable=False)  # gramaj/olcu grup degeri - ilgili banda eklenir
    customer_name = db.Column(db.String(200), nullable=False)  # serbest metin
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)  # opsiyonel, mevcut musteri secilebilir
    urun = db.Column(db.String(200), nullable=False)  # hangi urun oldugu - /uretim-planlama tablosunda gosterilir
    quantity = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(20), default='adet')
    delivery_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    customer = db.relationship('Customer')
    user = db.relationship('User')

class ManualTedarikEntry(db.Model):
    """/tedarik-takip sayfasinda, sistemde formal bir teklifi olmayan bir
    ticaret (hazir alinip satilan) kalemini elle listeye eklemek icin.
    Gercek ProductionItem (urun_tipi='ticaret') kayitlarindan 'Manuel'
    etiketiyle ayirt edilir, herhangi bir Deal/Production'a bagli degildir."""
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(200), nullable=False)  # serbest metin
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)  # opsiyonel, mevcut musteri secilebilir
    urun = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(20), default='adet')
    delivery_date = db.Column(db.Date, nullable=True)
    durum = db.Column(db.String(20), default='siparis_edildi', nullable=False)  # TICARET_STAGE_KEYS
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    customer = db.relationship('Customer')
    user = db.relationship('User')

CARRIER_OPTIONS = ['Aras Kargo', 'MNG Kargo', 'Yurtiçi Kargo', 'UPS', 'Sürat Kargo', 'Elden Teslim', 'Diğer']

SHIPMENT_STATUSES = [
    ('hazirlaniyor', 'Hazırlanıyor'),
    ('kargoya_verildi', 'Kargoya Verildi'),
    ('yolda', 'Yolda'),
    ('teslim_edildi', 'Teslim Edildi'),
]
SHIPMENT_STATUS_LABELS = dict(SHIPMENT_STATUSES)

# Kargo firmalarinin genel takip sayfasi URL sablonlari (takip no eklenerek
# olusturulur). Elden Teslim / Diger icin harici bir takip sayfasi yok.
_CARRIER_TRACKING_URL_TEMPLATES = {
    'Aras Kargo': 'http://kargotakip.araskargo.com.tr/mainpage.aspx?code={no}',
    'MNG Kargo': 'https://kargotakip.mngkargo.com.tr/?takipNo={no}',
    'Yurtiçi Kargo': 'https://www.yurticikargo.com/tr/online-servisler/gonderi-sorgula?code={no}',
    'UPS': 'https://www.ups.com/track?loc=tr_TR&tracknum={no}',
    'Sürat Kargo': 'https://www.suratkargo.com.tr/KargoTakip/?kargotakipno={no}',
}

class Shipment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    production_id = db.Column(db.Integer, db.ForeignKey('production.id'), nullable=False)
    ship_date = db.Column(db.Date)
    tracking_number = db.Column(db.String(100))
    carrier = db.Column(db.String(100))
    estimated_delivery_date = db.Column(db.Date, nullable=True)
    actual_delivery_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(30), default='hazirlaniyor')
    faturasiz_cikis = db.Column(db.Boolean, default=False, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship('ShipmentItem', backref='shipment', lazy=True, cascade='all, delete-orphan')

    @property
    def status_label(self):
        return SHIPMENT_STATUS_LABELS.get(self.status, self.status)

    @property
    def tracking_url(self):
        if not self.tracking_number or not self.carrier:
            return None
        template = _CARRIER_TRACKING_URL_TEMPLATES.get(self.carrier)
        if not template:
            return None
        from urllib.parse import quote
        return template.format(no=quote(self.tracking_number.strip()))

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

class ManualIrsaliye(db.Model):
    """Hicbir teklif/uretim kaydi olmadan, dogrudan bir musteriye bagli
    bagimsiz irsaliye. Shipment (Production'a bagli, gercek fiziksel
    sevkiyat) ile ayni alan adlarini paylasir (ship_date/carrier/
    tracking_number/status) - boylece sevkiyat listesinde iki farkli
    kaynak tek bir tabloda, ayni sablonla gosterilebilir."""
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False, index=True)
    ship_date = db.Column(db.Date)
    tracking_number = db.Column(db.String(100))
    carrier = db.Column(db.String(100))
    estimated_delivery_date = db.Column(db.Date, nullable=True)
    actual_delivery_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(30), default='hazirlaniyor')
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # Is 5: fiyatli irsaliye icin KDV orani - kalemlerin hicbirinde fiyat
    # girilmediyse (eski davranis) None/0 kalir, otomatik fatura olusmaz.
    vat_rate = db.Column(db.Float, nullable=True, default=20)
    # Is 5: otomatik olusturulan dahili takip faturasiyla iliski - GENEL
    # KURAL: bir irsaliyeye fatura baglandiysa ikinci fatura olusturulamaz,
    # bu alan o kontrolun kaynagi.
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=True)

    customer = db.relationship('Customer', backref='manual_irsaliyeler')
    user = db.relationship('User')
    items = db.relationship('ManualIrsaliyeItem', backref='manual_irsaliye', lazy=True, cascade='all, delete-orphan')
    invoice = db.relationship('Invoice')

    @property
    def is_priced(self):
        """En az bir kalemde fiyat girilmis mi - fatura otomasyonu ve
        PDF'in 'fiyatli' secenegi bu bayrağa bakar."""
        return any((item.unit_price or 0) > 0 for item in self.items)

    @property
    def subtotal(self):
        return sum((item.unit_price or 0) * item.quantity for item in self.items)

    @property
    def vat_amount(self):
        return self.subtotal * ((self.vat_rate or 0) / 100)

    @property
    def total(self):
        return self.subtotal + self.vat_amount

    @property
    def display_no(self):
        return f'MIRS-{self.id:05d}'

    @property
    def status_label(self):
        return SHIPMENT_STATUS_LABELS.get(self.status, self.status)

    @property
    def tracking_url(self):
        if not self.tracking_number or not self.carrier:
            return None
        template = _CARRIER_TRACKING_URL_TEMPLATES.get(self.carrier)
        if not template:
            return None
        from urllib.parse import quote
        return template.format(no=quote(self.tracking_number.strip()))

class ManualIrsaliyeItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    manual_irsaliye_id = db.Column(db.Integer, db.ForeignKey('manual_irsaliye.id'), nullable=False)
    description = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(20), default='adet')
    # Is 5: opsiyonel birim fiyat - NULL/0 ise bu kalem "fiyatsiz" sayilir.
    unit_price = db.Column(db.Float, nullable=True, default=0)

    @property
    def total_price(self):
        return (self.unit_price or 0) * self.quantity

class CustomerStatement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False, index=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deal.id'), nullable=True)
    # Bu ekstre kaydi bir Payment'tan otomatik olusturulduysa iliskilendirir -
    # odeme silinince bagli ekstre kaydinin da silinebilmesi icin.
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'), nullable=True)
    type = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Is 1 (PDF cari ekstre ice aktarim) - elle/otomatik olusturulanlardan
    # ayirt etmek icin. 'pdf_import' ise created_at, PDF'teki gercek islem
    # tarihidir (import aninin degil).
    source = db.Column(db.String(20), default='manuel', nullable=False)

class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_no = db.Column(db.Integer, unique=True, nullable=True)
    type = db.Column(db.String(20), nullable=False, default='fatura')  # fatura / irsaliye
    # Bagimsiz (teklifsiz) fatura olusturulabildigi icin (Is 2) artik
    # opsiyonel - tekliften olusturulanlarda dolu, manuel olusturulanlarda NULL.
    deal_id = db.Column(db.Integer, db.ForeignKey('deal.id'), nullable=True, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False, index=True)
    # Sahiplik/yetki kontrolu icin (guvenlik duzeltmesi) - deal_id'den
    # (deal.user_id) turetilemeyen bagimsiz faturalar icin de bir sahip
    # gerekiyordu. Eski kayitlarda NULL kalir (geriye donuk erisimi
    # kapatmaz, sadece bilinen bir sahip varsa kontrol edilir).
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    date = db.Column(db.Date, default=datetime.utcnow)
    subtotal = db.Column(db.Float, nullable=False, default=0)
    vat_rate = db.Column(db.Float, nullable=False, default=20)
    vat_amount = db.Column(db.Float, nullable=False, default=0)
    total = db.Column(db.Float, nullable=False, default=0)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Is 8: kalem duzenleme sonrasi basit log - "Son duzenleyen: X, tarih: Y".
    # Hic duzenlenmemis faturalarda NULL kalir (olusturuldugundan beri
    # degismemis demektir).
    updated_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    updated_at = db.Column(db.DateTime, nullable=True)
    # B5b (2026-10-06): Invoice'ta HIC para birimi alani yoktu - dovizli
    # bir tekliften (EUR/USD/GBP) fatura olusturulunca tutarlar PDF/
    # ekranda hep "TL" etiketiyle gosteriliyordu (sayi dogru kopyalaniyordu,
    # SADECE etiket yanlisti). YENI, nullable kolon - eski faturalarda
    # NULL kalir ve TRY gibi davranilir (geriye donuk davranis degismez).
    para_birimi = db.Column(db.String(3), nullable=True)

    customer = db.relationship('Customer', backref='invoices')
    items = db.relationship('InvoiceItem', backref='invoice', lazy=True, cascade='all, delete-orphan')
    updated_by = db.relationship('User', foreign_keys=[updated_by_user_id])

    @property
    def para_birimi_sembol(self):
        return CURRENCY_SYMBOLS.get(self.para_birimi or 'TRY', self.para_birimi)

    @property
    def owner_id(self):
        """Sahiplik kontrolu icin - once kendi user_id'si, o da yoksa
        (eski kayitlar) bagli teklifin sahibine duser. Ikisi de yoksa
        (eski bagimsiz fatura) None doner - bilinen bir sahip olmadigi
        icin erisim kisitlanmaz."""
        return self.user_id or (self.deal.user_id if self.deal else None)

    @property
    def display_no(self):
        prefix = 'FAT-' if self.type == 'fatura' else 'IRS-'
        if self.invoice_no:
            return f'{prefix}{self.invoice_no:05d}'
        return f'{prefix}{self.id:05d}'

    @property
    def paid_amount(self):
        return sum(p.amount for p in self.payments if p.status == 'odendi')

    @property
    def remaining_amount(self):
        return self.total - self.paid_amount

    @property
    def payment_status(self):
        paid = self.paid_amount
        if paid <= 0:
            return 'odenmedi'
        if paid >= self.total:
            return 'odendi'
        return 'kismi_odendi'

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
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False, index=True)
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
    report_date = db.Column(db.Date, default=datetime.utcnow, nullable=False, index=True)
    customer_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(50))
    notes = db.Column(db.Text)
    # tamamlandi, fiyat_verilecek, takip_edilecek, 'ulasilamadi' (Is 1 -
    # Takip Modu: bu durum KASITLI olarak _last_contact_subquery()'den
    # HARIC tutulur - "Ulasilamadi" gercek bir irtibat sayilmaz, 60 gunluk
    # sayac sifirlanmamali).
    status = db.Column(db.String(20), default='takip_edilecek')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True, index=True)
    # Is 1 (Takip Modu) - "Tekrar ara" secenegi: bu tarihte musteri
    # otomatik olarak sirada en yukarilara gelir. NULL = tekrar arama
    # planlanmamis.
    tekrar_ara_tarihi = db.Column(db.Date, nullable=True, index=True)

    user = db.relationship('User', backref='daily_reports')
    customer = db.relationship('Customer', backref='daily_reports')

    def __repr__(self):
        return f'<DailyReport {self.customer_name} - {self.report_date}>'

class DailyOutreachCount(db.Model):
    """Is 1 - Takip Modu: kullanici bazli GUNLUK gercek-iletisim sayaci
    (WhatsApp gonder / Arandı+not SADECE - devret/musteri-degil/birlestir/
    atla/sonra-ara SAYILMAZ). Gun + kullanici basina TEK satir, her
    iletisimde +1 artirilir. Geçmis gunler SAKLANIR (silinmez) - Raporlar'da
    goruntulenebilsin diye."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    report_date = db.Column(db.Date, nullable=False, index=True)
    count = db.Column(db.Integer, default=0, nullable=False)

    user = db.relationship('User')

    __table_args__ = (db.UniqueConstraint('user_id', 'report_date', name='uq_outreach_user_date'),)

class PaymentReminder(db.Model):
    """Is 1.6 - Takip Modu odeme hatirlatma: OTOMATIK (Deal.pesinat_tarihi/
    bakiye_tarihi gelince, ayni gun icin eklenir - tekrar eklenmesin diye
    source_type+source_id+due_date benzersiz tutuluyor) veya ELLE
    (musteri detayi/fatura detayi/Takip Modu'ndaki 'Odeme Iste' butonu)
    olusturulur. Odenene kadar kapanmaz (status='odendi' olana kadar
    Takip Modu'nda gosterilmeye devam eder)."""
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False, index=True)
    source_type = db.Column(db.String(20), nullable=False)  # 'deal_pesinat' / 'deal_bakiye' / 'invoice' / 'manuel'
    source_id = db.Column(db.Integer, nullable=True)  # deal_id veya invoice_id (turune gore) - FK degil, kaynak tipi degisken
    amount = db.Column(db.Float, nullable=False)
    due_date = db.Column(db.Date, nullable=False, index=True)
    # bekliyor -> hatirlatildi -> soz_verildi -> odendi (odendi'ye sadece
    # gercek bir Payment kaydi olusunca gecilir - bkz. routes.py)
    status = db.Column(db.String(20), default='bekliyor', nullable=False)
    promised_date = db.Column(db.Date, nullable=True)  # 'Odeme sozu verdi' ile girilen yeni tarih
    notes = db.Column(db.Text, nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)

    customer = db.relationship('Customer', backref='payment_reminders')
    created_by = db.relationship('User')

class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=True)
    # Faturadan once teklif asamasinda alinan on odemeyi (avans) izlemek icin -
    # invoice_id ile birlikte de olabilir (once deal_id'li avans, sonra faturaya baglanir).
    deal_id = db.Column(db.Integer, db.ForeignKey('deal.id'), nullable=True, index=True)
    amount = db.Column(db.Float, nullable=False)
    payment_date = db.Column(db.Date, default=datetime.utcnow)
    payment_method = db.Column(db.String(50))  # nakit, kredi_karti, havale, cek
    reference_no = db.Column(db.String(100))  # ödeme referans no
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default='beklemede', index=True)  # beklemede, odendi, iptal
    # Coklu Para Birimi - bagli teklif/fatura TRY disinda bir para biriminde
    # ise (Deal.para_birimi), bu odemenin GUN'undeki TCMB kuru (veya elle
    # girilen) burada tutulur. Kismi odemeler farkli gunlerde farkli kurla
    # gelebilecegi icin kur Deal uzerinde degil, her Payment'ta ayri ayri
    # tutulur - boylece her tahsilatin gercek TL karsiligi dogru hesaplanir.
    kur_orani = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    customer = db.relationship('Customer', backref='payments')
    invoice = db.relationship('Invoice', backref='payments')
    deal = db.relationship('Deal', backref='payments')
    user = db.relationship('User', backref='payments')

    @property
    def tl_karsiligi(self):
        """kur_orani girilmisse amount * kur_orani (dovizin TL karsiligi),
        yoksa amount'un zaten TL oldugu varsayilir."""
        return self.amount * self.kur_orani if self.kur_orani else self.amount

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
    phone = db.Column(db.String(50))
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

class CompanySettings(db.Model):
    """Tekil satir (id=1) - Teklif PDF'inde gosterilen firma bilgileri.
    Logo, Render'in disk depolamasi kalici olmadigi icin dosya olarak degil
    veritabaninda (bytea) saklanir."""
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(200), default='Lema Ambalaj', nullable=False)
    address = db.Column(db.Text)
    phone = db.Column(db.String(50))
    fax = db.Column(db.String(50))
    email = db.Column(db.String(120))
    website = db.Column(db.String(200))
    tax_office = db.Column(db.String(100))
    tax_id = db.Column(db.String(30))
    logo_data = db.Column(db.LargeBinary)
    logo_mimetype = db.Column(db.String(50))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # B5e (2026-10-06): Teklif PDF'inde genel toplamin diger 3 para
    # birimindeki (bilgi amacli) karsiligini gosterip gostermeme ayari.
    pdf_doviz_karsiligi_goster = db.Column(db.Boolean, default=True, nullable=False)

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

class DailyProductionOutput(db.Model):
    """Is 3 - Gunluk Uretim Takibi: atolyenin gun icinde elle doldurdugu
    kagit formdaki her satiri (musteri, koli basi kg, koli adedi, toplam
    kg) dijital olarak kaydeder. Musteri/Firma ManualPlanningEntry ile
    AYNI desen - serbest metin + opsiyonel gercek musteri eslestirmesi."""
    id = db.Column(db.Integer, primary_key=True)
    tarih = db.Column(db.Date, default=datetime.utcnow, nullable=False, index=True)
    musteri_adi = db.Column(db.String(200), nullable=False)  # serbest metin
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)  # opsiyonel, mevcut musteri secilebilir
    # Is 3: aktif bir Production (is emri) kaydina baglanabilir - musteri
    # secimi artik bu uzerinden yapiliyor (bkz. routes.py gunluk_uretim()).
    # Eski kayitlarda (bu alan eklenmeden once girilmis) NULL kalir, geriye
    # donuk hicbir islem/otomatik tamamlanma UYGULANMAZ (kullanici talebi).
    production_id = db.Column(db.Integer, db.ForeignKey('production.id'), nullable=True, index=True)
    koli_basi_kg = db.Column(db.Float, nullable=False)
    koli_adedi = db.Column(db.Float, nullable=False)
    toplam_kg = db.Column(db.Float, nullable=False)  # varsayilan koli_basi_kg*koli_adedi, elle degistirilebilir
    aciklama = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    customer = db.relationship('Customer')
    user = db.relationship('User')
    production = db.relationship('Production', backref='daily_outputs')

class DailyProductionPhoto(db.Model):
    """Is 4 - Gunluk Uretim fotograf arsivi: bir TARIHE bagli (tekil satira
    degil - 'Uretim Formu' zaten gunluk tek bir kagit) 'form' (elle
    doldurulan kagidin fotografi) veya 'urun' (uretilen malin gorseli)
    turunde dosyalar. SADECE arsivleme icindir - hicbir OCR/okuma
    yapilmaz; foto_turu alani ileride bir AI Vision entegrasyonu
    eklendiginde ayni tabloya 'okundu_metni'/'islendi_mi' gibi kolonlar
    eklenerek genisletilebilecek sekilde ayri tutuldu."""
    id = db.Column(db.Integer, primary_key=True)
    tarih = db.Column(db.Date, nullable=False, index=True)
    foto_turu = db.Column(db.String(20), nullable=False)  # 'form' / 'urun'
    dosya_yolu = db.Column(db.String(300), nullable=False)  # static/ koku itibariyle goreli
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    user = db.relationship('User')

class SystemError(db.Model):
    """Hata yakalayici (2026-10-05 denetimi): tarayici-ici JS hatalari
    (window.onerror/unhandledrejection, bkz. base.html + /api/js-error)
    VE sunucu taraflı 500'ler (bkz. app.errorhandler(500)) AYNI tabloya
    duser. Dedup_key = source+page+message+line'in md5'i - ayni hata
    tekrar olusunca YENI SATIR ACILMAZ, mevcut satirin count'u +1 artar
    ve last_seen guncellenir (aksi halde bir dongu icindeki hata
    tablonun saniyeler icinde sismesine yol acardi)."""
    id = db.Column(db.Integer, primary_key=True)
    dedup_key = db.Column(db.String(32), nullable=False, unique=True, index=True)
    source = db.Column(db.String(10), nullable=False)  # 'js' / 'server'
    page = db.Column(db.String(300), nullable=True)
    message = db.Column(db.Text, nullable=False)
    line = db.Column(db.Integer, nullable=True)
    browser = db.Column(db.String(300), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    count = db.Column(db.Integer, default=1, nullable=False)
    first_seen = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    resolved = db.Column(db.Boolean, default=False, nullable=False, index=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolved_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    user = db.relationship('User', foreign_keys=[user_id])
    resolved_by = db.relationship('User', foreign_keys=[resolved_by_user_id])

class TeklifYardimciConfig(db.Model):
    """B3 (2026-10-06): 'Kese seç'/'Doypack seç' butonlarinin acik/kapali
    oldugu tek satirlik ayar - PlacesSearchConfig ile AYNI singleton
    desen. Kapaliyken add_deal/edit_deal.html bu butonlari hic render
    etmez, teklif ekrani eskisi gibi kalir (koklu degisiklik yasagi)."""
    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, default=True, nullable=False)

class KeseGramajKatalog(db.Model):
    """B1: 'Kese seç' panelindeki gramaj kartlari. kraft_adet_kg_min/max
    esmer VE beyaz kraft icin AYNI (katalogda ayri satir yok, kagit_cinsi
    secimi sadece Aciklama'ya yazilan metni degistirir); kuse_adet_kg_min/
    max farkli bir deger seti. aktif=False olanlar 'Diger boylar' alt
    basliginda, deger girilmemisse bos gorunur (Ayarlar'dan doldurulur)."""
    id = db.Column(db.Integer, primary_key=True)
    gramaj = db.Column(db.Integer, nullable=False, unique=True)
    olcu_en = db.Column(db.String(20), nullable=True)
    olcu_korugu = db.Column(db.String(20), nullable=True)
    olcu_boy = db.Column(db.String(20), nullable=True)
    kraft_adet_kg_min = db.Column(db.Float, nullable=True)
    kraft_adet_kg_max = db.Column(db.Float, nullable=True)
    kuse_adet_kg_min = db.Column(db.Float, nullable=True)
    kuse_adet_kg_max = db.Column(db.Float, nullable=True)
    aktif = db.Column(db.Boolean, default=True, nullable=False)
    sira = db.Column(db.Integer, default=0, nullable=False)

class DoypackKatalog(db.Model):
    """B2: 'Doypack seç' panelindeki ölçü/fiyat kartları - liste fiyatı
    01.07.2026 itibariyle, TL/adet, baskısız, kraft pencereli kilitli
    doypack. fiyat_tarihi ayrı tutulur ki fiyat listesi güncellenince
    panelde 'XX tarihli fiyat' notu gösterilebilsin."""
    id = db.Column(db.Integer, primary_key=True)
    olcu_en = db.Column(db.String(20), nullable=False)
    olcu_boy = db.Column(db.String(20), nullable=False)
    korugu = db.Column(db.String(20), nullable=True)
    koli_adedi = db.Column(db.Integer, nullable=True)
    fiyat = db.Column(db.Float, nullable=False)
    fiyat_tarihi = db.Column(db.Date, nullable=True)
    aktif = db.Column(db.Boolean, default=True, nullable=False)
    sira = db.Column(db.Integer, default=0, nullable=False)

class BaskiFiyatKatalog(db.Model):
    """B2: doypack baskı ücret tablosu (yüz × renk sayısı). Kullanıcı
    panelde fiyatı olmayan bir kombinasyon için elle bir tutar yazarsa
    (bkz. /api/teklif-yardimci/baski-fiyat), buraya upsert edilir -
    sonraki teklifte otomatik gelir."""
    id = db.Column(db.Integer, primary_key=True)
    yuz = db.Column(db.String(10), nullable=False)  # 'tek' / 'cift'
    renk_sayisi = db.Column(db.Integer, nullable=False)
    fiyat = db.Column(db.Float, nullable=True)

    __table_args__ = (db.UniqueConstraint('yuz', 'renk_sayisi', name='uq_baski_fiyat_yuz_renk'),)

class ProductionPlanOrder(db.Model):
    """B8: 'Uretim Plani' - SADECE kullanicinin surukle-birak sira ve
    (istege bagli) termin override'ini saklar. Production.status'u
    HICBIR SEKILDE degistirmez/okumaz-yazmaz - uretim akisindan
    tamamen bagimsiz, ayri bir goruntuleme/planlama katmani."""
    id = db.Column(db.Integer, primary_key=True)
    production_id = db.Column(db.Integer, db.ForeignKey('production.id'), nullable=False, unique=True)
    sira = db.Column(db.Integer, nullable=False, default=0)
    termin_override = db.Column(db.Date, nullable=True)

    production = db.relationship('Production', backref=db.backref('plan_order', uselist=False))
