from flask import render_template, request, redirect, url_for, flash, send_file, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User, Customer, Deal, DealItem, Production, ProductionItem, PRODUCTION_STAGES, TICARET_STAGES, TICARET_STAGE_KEYS, TICARET_STAGE_LABELS, Shipment, ShipmentItem, ManualIrsaliye, ManualIrsaliyeItem, CARRIER_OPTIONS, SHIPMENT_STATUSES, CustomerStatement, Reminder, Product, Task, Commission, Invoice, InvoiceItem, CustomerVisit, DailyReport, Payment, PotentialCustomer, PlacesSearchConfig, PlacesSearchLog, CompanySettings, ManualPlanningEntry, ManualTedarikEntry, DailyProductionOutput, DailyProductionPhoto
from app.pdf_utils import generate_deal_pdf, generate_statement_pdf, generate_irsaliye_pdf, generate_manual_irsaliye_pdf, generate_is_emri_pdf, generate_invoice_pdf, generate_production_list_pdf, generate_gunluk_uretim_form_pdf, generate_cari_hesap_pdf, _clean_for_pdf
from app.statement_pdf_import import parse_statement_pdf
from app import db, places_search, limiter
from app.tcmb import fetch_tcmb_rate
from datetime import datetime, timedelta, date
from functools import wraps
from io import BytesIO
from werkzeug.utils import secure_filename
import openpyxl
import os
import re
import time
import uuid
from urllib.parse import quote as _url_quote
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from flask_wtf.csrf import generate_csrf

def calculate_customer_balance(customer):
    """Cari Hesap Birlestirme: Faturalanmis + Faturalanmamis Kazanilan
    Teklif - Tahsilat = Toplam Bakiye kirilimini dondurur. Customer.
    total_invoiced/total_uninvoiced_won/total_collected/balance
    property'leriyle (app/models.py) AYNI mantigi sarar - customer_detail()
    ve Cari Hesap Ozeti'nin bulk GROUP BY hesaplamasi (cari_hesap_ozeti())
    hep bu tek tanima dayanir, ikinci/farkli bir hesaplama yolu yok.
    customer: zaten yuklenmis bir Customer instance'i (tekrar sorgu atmaz)."""
    return {
        'invoiced': customer.total_invoiced,
        'uninvoiced_won': customer.total_uninvoiced_won,
        'collected': customer.total_collected,
        'balance': customer.balance,
    }

def _customers_with_activity_subquery():
    """'Islem yapilmis' musteri id'lerinin birlesimi - sadece Deal (teklif)
    degil, DailyReport (gorusme/rapor), Payment, Invoice, CustomerVisit
    kayitlarindan herhangi biri de gercek bir islem sayilir. Onceden sadece
    Deal kontrol ediliyordu, bu yuzden cok sayida musterinin gorusme/odeme
    kaydi olmasina ragmen 'hic islem yapilmamis' listesinde kaliyordu."""
    return db.session.query(Deal.customer_id).union(
        db.session.query(Invoice.customer_id),
        db.session.query(Payment.customer_id),
        db.session.query(CustomerVisit.customer_id),
        db.session.query(DailyReport.customer_id).filter(DailyReport.customer_id.isnot(None)),
    )

TAKIP_GEREKEN_GUN = 60

def _last_contact_subquery():
    """Musteri basina 'son irtibat tarihi' - Gunluk Rapor/Teklif/Odeme
    kaynaklarindan EN SON olani (musteri takip donguleri icin). Hicbir
    kaynakta kaydi olmayan musteriler bu subquery'de hic gorunmez -
    cagiran taraf bunu outerjoin+NULL kontrolu ile 'hic irtibat yok'
    olarak ele almali."""
    deal_sub = db.session.query(
        Deal.customer_id.label('customer_id'),
        db.func.max(db.cast(Deal.created_at, db.Date)).label('last_contact')
    ).group_by(Deal.customer_id)
    report_sub = db.session.query(
        DailyReport.customer_id.label('customer_id'),
        db.func.max(DailyReport.report_date).label('last_contact')
    ).filter(DailyReport.customer_id.isnot(None)).group_by(DailyReport.customer_id)
    payment_sub = db.session.query(
        Payment.customer_id.label('customer_id'),
        db.func.max(Payment.payment_date).label('last_contact')
    ).group_by(Payment.customer_id)

    combined = deal_sub.union_all(report_sub, payment_sub).subquery()
    return db.session.query(
        combined.c.customer_id.label('customer_id'),
        db.func.max(combined.c.last_contact).label('last_contact')
    ).group_by(combined.c.customer_id).subquery()

def _takip_gerekiyor_query():
    """60 gunluk takip dongusu: son irtibatin (Gunluk Rapor/Teklif/Odeme)
    uzerinden TAKIP_GEREKEN_GUN gunden fazla gecmis (veya hic irtibat
    kaydi olmayan) musterileri dondurur. Gercek zamanli hesaplanir,
    onbelleklenmez - her cagrida guncel veriye gore calisir.
    Is 1 madde 3: admin olmayan kullanicilar SADECE kendi musterilerini
    (owner_user_id == current_user.id) gorur; admin TUMUNU gorur. Sahipsiz
    (owner_user_id IS NULL) musteriler 'kimsenin musterisi degil' sayilir,
    normal kullaniciya gosterilmez (ama admin'in gordugu tum listede yer alir)."""
    cutoff = date.today() - timedelta(days=TAKIP_GEREKEN_GUN)
    last_contact = _last_contact_subquery()
    query = db.session.query(Customer, last_contact.c.last_contact).outerjoin(
        last_contact, Customer.id == last_contact.c.customer_id
    ).filter(
        Customer.status != 'musteri_degil',
        db.or_(
            last_contact.c.last_contact.is_(None),
            last_contact.c.last_contact < cutoff
        )
    )
    if not current_user.is_admin:
        query = query.filter(Customer.owner_user_id == current_user.id)
    return query.order_by(last_contact.c.last_contact.asc().nullsfirst())

def _get_company_settings():
    """Tekil satir (id=1) - yoksa varsayilan degerlerle olusturur."""
    settings = CompanySettings.query.get(1)
    if not settings:
        settings = CompanySettings(id=1, company_name='Lema Ambalaj')
        db.session.add(settings)
        db.session.commit()
    return settings

def _save_uploaded_image(file_storage, subfolder):
    """Yuklenen gorseli static/uploads/<subfolder>/ altina guvenli/benzersiz
    bir isimle kaydeder, static/ koku itibariyle goreli yolu dondurur
    (Customer.tasarim_gorseli / Production.tasarim_gorseli_override icin).
    Gecersiz gorsel (PIL dogrulamasi) veya cok buyuk dosya durumunda None
    dondurur ve hata mesaji ile birlikte (None, hata_mesaji) verir."""
    if not file_storage or not file_storage.filename:
        return None, None
    data = file_storage.read()
    if len(data) > 2 * 1024 * 1024:
        return None, 'Görsel dosyası çok büyük (maks. 2 MB).'
    try:
        from PIL import Image as PILImage
        PILImage.open(BytesIO(data)).verify()
    except Exception:
        return None, 'Geçerli bir görsel dosyası değil (JPG/PNG olmalı).'

    ext = os.path.splitext(secure_filename(file_storage.filename))[1].lower()
    if ext not in ('.jpg', '.jpeg', '.png'):
        return None, 'Sadece JPG/PNG dosyaları desteklenir.'

    upload_dir = os.path.join(os.path.dirname(__file__), 'static', 'uploads', subfolder)
    os.makedirs(upload_dir, exist_ok=True)
    filename = f'{uuid.uuid4().hex}{ext}'
    with open(os.path.join(upload_dir, filename), 'wb') as f:
        f.write(data)
    return f'uploads/{subfolder}/{filename}', None

_TR_FILENAME_MAP = str.maketrans({
    'ı': 'i', 'İ': 'I', 'ğ': 'g', 'Ğ': 'G', 'ü': 'u', 'Ü': 'U',
    'ş': 's', 'Ş': 'S', 'ö': 'o', 'Ö': 'O', 'ç': 'c', 'Ç': 'C', ' ': '_',
})

def _safe_filename_part(text):
    """Turkce karakterleri/bosluklari dosya adi icin guvenli ASCII'ye
    cevirir (orn. IsEmri_{musteri_adi}_{no}.pdf dosya adlarinda kullanilir)."""
    if not text:
        return 'Musteri'
    return text.translate(_TR_FILENAME_MAP)

def _normalize_phone_for_whatsapp(phone):
    """Turkce telefon formatlarini ('+90 533 721 83 26', '05397203547',
    '0 549 265 44 49', '5395171392' gibi) wa.me'nin bekledigi ulke kodlu,
    ayracsiz haline ('905397203547') cevirir (Is 5)."""
    if not phone:
        return None
    digits = re.sub(r'\D', '', phone)
    if digits.startswith('90') and len(digits) == 12:
        return digits
    if digits.startswith('0') and len(digits) == 11:
        return '90' + digits[1:]
    if len(digits) == 10:
        return '90' + digits
    return digits or None

# Is 2 - Sehir Bazli Hizli Iletisim: 81 il (Konya/Aksaray haric, onlar
# ilceleriyle birlikte asagida ayrica taniliyor - Yakin Bolge grubu).
_IL_LISTESI = [
    'Adana', 'Adıyaman', 'Afyonkarahisar', 'Ağrı', 'Amasya', 'Ankara', 'Antalya',
    'Artvin', 'Aydın', 'Balıkesir', 'Bilecik', 'Bingöl', 'Bitlis', 'Bolu', 'Burdur',
    'Bursa', 'Çanakkale', 'Çankırı', 'Çorum', 'Denizli', 'Diyarbakır', 'Edirne',
    'Elazığ', 'Erzincan', 'Erzurum', 'Eskişehir', 'Gaziantep', 'Giresun', 'Gümüşhane',
    'Hakkari', 'Hatay', 'Isparta', 'Mersin', 'İstanbul', 'İzmir', 'Kars', 'Kastamonu',
    'Kayseri', 'Kırklareli', 'Kırşehir', 'Kocaeli', 'Kütahya', 'Malatya', 'Manisa',
    'Kahramanmaraş', 'Mardin', 'Muğla', 'Muş', 'Nevşehir', 'Niğde', 'Ordu', 'Rize',
    'Sakarya', 'Samsun', 'Siirt', 'Sinop', 'Sivas', 'Tekirdağ', 'Tokat', 'Trabzon',
    'Tunceli', 'Şanlıurfa', 'Uşak', 'Van', 'Yozgat', 'Zonguldak', 'Bayburt', 'Karaman',
    'Kırıkkale', 'Batman', 'Şırnak', 'Bartın', 'Ardahan', 'Iğdır', 'Yalova', 'Karabük',
    'Kilis', 'Osmaniye', 'Düzce',
]

_KONYA_ILCELERI = [
    'Akşehir', 'Akören', 'Altınekin', 'Beyşehir', 'Bozkır', 'Cihanbeyli', 'Çeltik',
    'Derbent', 'Derebucak', 'Doğanhisar', 'Emirgazi', 'Ereğli', 'Güneysınır', 'Hadim',
    'Halkapınar', 'Hüyük', 'Ilgın', 'Kadınhanı', 'Karapınar', 'Karatay', 'Kulu',
    'Meram', 'Sarayönü', 'Selçuklu', 'Seydişehir', 'Taşkent', 'Tuzlukçu', 'Yalıhüyük',
    'Yunak',
]

_AKSARAY_ILCELERI = ['Ağaçören', 'Eskil', 'Gülağaç', 'Güzelyurt', 'Ortaköy', 'Sarıyahşi', 'Sultanhanı']

_TR_NORMALIZE_MAP = str.maketrans({'İ': 'i', 'I': 'ı', 'Ğ': 'ğ', 'Ü': 'ü', 'Ş': 'ş', 'Ö': 'ö', 'Ç': 'ç'})

def _tr_normalize(text):
    """Standart str.lower() Turkce 'İ'yi dogru kucultemedigi (i-nokta
    sorunu) icin once Turkce buyuk harfleri elle kucultup sonra lower()
    uyguluyoruz - il/ilce adi eslestirmesinde buyuk/kucuk harf farkini
    guvenilir sekilde yok etmek icin (Is 2)."""
    return text.translate(_TR_NORMALIZE_MAP).lower()

def _build_city_matchers():
    """(derlenmis regex, il adi) ciftlerini, en uzun/spesifik isim once
    denensin diye uzunluga gore azalan sirada hazirlar - orn. 'Kahramanmaras'
    'Mus' ile karismasin, 'Aksaray' ilceleri 'Aksaray' ilinden once denenebilir
    (ikisi de ayni degeri dondurdugunden sira onemli degil ama tutarlilik icin)."""
    entries = []
    for ilce in _KONYA_ILCELERI:
        entries.append((ilce, 'Konya'))
    entries.append(('Konya', 'Konya'))
    for ilce in _AKSARAY_ILCELERI:
        entries.append((ilce, 'Aksaray'))
    entries.append(('Aksaray', 'Aksaray'))
    for il in _IL_LISTESI:
        entries.append((il, il))
    entries.sort(key=lambda e: -len(e[0]))
    return [(re.compile(r'\b' + re.escape(_tr_normalize(name)) + r'\b'), value) for name, value in entries]

_CITY_MATCHERS = _build_city_matchers()

def extract_customer_city(customer):
    """Musteri metin alanlarindan (first_name/last_name/company_name/
    address/company_address birlestirilmis) il/ilce adi gecirerek il
    cikarir (Is 2). Bu CRM'de cogu musterinin address/company_address
    alani BOS - sehir bilgisi genelde last_name/company_name icine serbest
    metin olarak girilmis (orn. 'Ambalaj Aksaray', 'Kutahya Yasin'), bu
    yuzden TUM metin alanlari birlikte taranir, sadece adres degil. Konya/
    Aksaray ilceleri de ilgili ile eslenir (Yakin Bolge grubu icin).
    Bulunamazsa None doner (Diger Iller grubuna da girmez)."""
    text = ' '.join(filter(None, [
        customer.first_name, customer.last_name, customer.company_name,
        customer.address, customer.company_address,
    ]))
    if not text:
        return None
    normalized = _tr_normalize(text)
    for pattern, value in _CITY_MATCHERS:
        if pattern.search(normalized):
            return value
    return None

def _admin_deals_own_only():
    """Is 3: admin'in oturum bazli 'Sadece Benim Tekliflerim' tercihi.
    Normal kullanicilar icin bu ayarin hicbir etkisi yok - onlar zaten her
    zaman sadece kendi tekliflerini gorur."""
    return bool(session.get('admin_deals_own_only'))

_INVALID_PHONE_RAW = re.compile(r'^0*$|^-+$')

def _duplicate_phone_groups():
    """Is 8: telefon numarasini normalize ederek (_normalize_phone_for_whatsapp
    ile AYNI fonksiyon - tek kaynak) ayni numaraya sahip musteri gruplarini
    bulur. Gecersiz (bos/10 haneden kisa/sadece '0'-'-' gibi) numaralar
    atlanir; 5'ten fazla musteride gecen numaralar (muhtemelen ortak sabit
    hat/sahte numara) MUKERRER sayilmaz, ayri 'suspicious' listesinde
    donulur. Musteriler sag panelindeki sayac VE /customers/mukerrer
    sayfasi AYNI bu fonksiyonu kullanir (tek kaynak, modul cakismasi yok)."""
    customers = Customer.query.filter(Customer.phone.isnot(None)).all()
    groups_map = {}
    for c in customers:
        raw = (c.phone or '').strip()
        if not raw or _INVALID_PHONE_RAW.match(raw):
            continue
        digits = re.sub(r'\D', '', raw)
        if len(digits) < 10:
            continue
        norm = _normalize_phone_for_whatsapp(raw)
        if not norm:
            continue
        groups_map.setdefault(norm, []).append(c)
    duplicate_groups, suspicious_groups = [], []
    for norm, custs in groups_map.items():
        if len(custs) <= 1:
            continue
        (suspicious_groups if len(custs) > 5 else duplicate_groups).append({'phone': norm, 'customers': custs})
    duplicate_groups.sort(key=lambda g: -len(g['customers']))
    suspicious_groups.sort(key=lambda g: -len(g['customers']))
    return duplicate_groups, suspicious_groups

def _deal_visibility_user_id():
    """Bu istekte teklif gorunurlugunun kime kisitlanacagini dondurur:
    normal kullanici icin HER ZAMAN kendi id'si; admin icin varsayilan
    olarak None (kisitlama yok - herkesin teklifi gorunur), ama Is 3'teki
    gecis anahtari 'sadece benim tekliflerim' konumundaysa admin icin de
    kendi id'si. Is 1: teklif gorunurlugunun TUM route/istatistiklerde
    (Dashboard, /deals, /deals/export/excel, /calendar, /reports dahil)
    TEK bu fonksiyondan beslenmesini saglar - onceden bu kontrol bazi
    yerlerde hic yapilmiyordu, bu da ayni kullaniciya gore tutarsiz
    teklif sayilari/listeleri gorunmesine yol aciyordu."""
    if not current_user.is_admin:
        return current_user.id
    if _admin_deals_own_only():
        return current_user.id
    return None

def _apply_deal_visibility(query):
    """Deal.query veya Deal uzerinden kurulmus bir db.session.query(...)'a
    _deal_visibility_user_id()'nin dondurdugu kisitlamayi uygular."""
    scope_user_id = _deal_visibility_user_id()
    if scope_user_id is not None:
        query = query.filter(Deal.user_id == scope_user_id)
    return query

def _customer_full_name(customer):
    """Musterinin tam adini (kisaltmadan), gundelik hitaplardan (Abi/Amca/
    Abla/Baba/Dayi) temizlenmis halde dondurur. Teklif title'i olarak
    kullanilir (Is 3) - eskiden 'MEHMET-01.07-1' gibi kisaltilmis/karisik
    otomatik basliklar kullaniliyordu."""
    person = f"{_clean_for_pdf(customer.first_name) or ''} {_clean_for_pdf(customer.last_name) or ''}".strip()
    if customer.company_name:
        return f"{customer.company_name} - {person}" if person else customer.company_name
    return person or 'İsimsiz Müşteri'

def _apply_customer_updates_from_form(customer, form):
    """Fatura/teklif formlarinda 'eksik bilgi tamamlama' alanlarindan
    (customer_company_name, customer_tax_id, customer_phone,
    customer_address) gelen degerleri musteri kaydina yazar - bos
    birakilanlara dokunmaz."""
    company_name = form.get('customer_company_name', '').strip()
    tax_id = form.get('customer_tax_id', '').strip()
    phone = form.get('customer_phone', '').strip()
    address = form.get('customer_address', '').strip()
    if company_name:
        customer.company_name = company_name
    if tax_id:
        customer.tax_id = tax_id
    if phone:
        customer.phone = phone
    if address:
        customer.address = address

def _next_deal_no():
    """Bir sonraki teklif numarasini dondurur. MAX() SQL agregasyonu NULL
    degerleri otomatik yok sayar - Deal.query.order_by(deal_no.desc())
    kullanimi, deal_no NULL olan bir kayit varsa Postgres'in DESC'te
    NULL'lari basa koymasi yuzunden yanlislikla 1'e donup mevcut bir
    numarayla cakisabiliyordu (bkz. deal id=27 / revise_deal bug'i)."""
    max_no = db.session.query(db.func.max(Deal.deal_no)).scalar()
    return (max_no or 0) + 1

def _next_invoice_no():
    """Bir sonraki fatura/irsaliye numarasini dondurur. _next_deal_no() ile
    ayni NULL-guvenli mantik: db.func.max() NULL degerleri otomatik yok
    sayar, oysa Invoice.query.order_by(invoice_no.desc()) kullanimi,
    invoice_no NULL olan bir kayit varsa Postgres'in DESC'te NULL'lari
    basa koymasi yuzunden numaralamayi yanlislikla 1'e dondurup mevcut
    bir numarayla cakisabiliyordu (bkz. deal_no / revise_deal bug'i)."""
    max_no = db.session.query(db.func.max(Invoice.invoice_no)).scalar()
    return (max_no or 0) + 1

def _create_prepayment_if_requested(invoice, form, user_id):
    """Is 2: fatura olusturma formunda 'On Odeme Alindi' isaretlenmisse,
    faturaya bagli ilk Payment kaydini ('Ön Ödeme' etiketiyle) otomatik
    olusturur - add_payment() route'undaki 'odendi' -> CustomerStatement
    'alacak' otomasyonuyla AYNI mantik burada tekrarlanir (ayri/ikinci bir
    hesaplama kaynagi olusturmamak icin invoice_detail'deki bakiye tablosu
    da dogrudan Payment kayitlarindan besleniyor)."""
    if form.get('on_odeme_alindi') != 'on':
        return
    amount_raw = (form.get('on_odeme_tutari') or '').strip()
    if not amount_raw:
        return
    amount = float(amount_raw)
    if amount <= 0:
        return
    payment_date = datetime.strptime(form['on_odeme_tarihi'], '%Y-%m-%d').date() if form.get('on_odeme_tarihi') else datetime.now().date()
    payment = Payment(
        customer_id=invoice.customer_id,
        invoice_id=invoice.id,
        amount=amount,
        payment_date=payment_date,
        payment_method=form.get('on_odeme_yontemi') or None,
        notes='Ön Ödeme',
        status='odendi',
        user_id=user_id
    )
    db.session.add(payment)
    db.session.flush()
    statement = CustomerStatement(
        customer_id=payment.customer_id, payment_id=payment.id, type='alacak',
        amount=payment.amount, description=f'Tahsilat: {invoice.display_no} (Ön Ödeme)'
    )
    db.session.add(statement)

def _musteri_no_max():
    """Mevcut en buyuk musteri_no'nun sayisal kismini dondurur (Is 2).
    String siralama yerine SQL tarafinda gercek int max hesaplar - 4 haneyi
    astiginda (9999+) string siralamanin bozulmasindan etkilenmez.
    Performans: onceden TUM musteri_no degerlerini (1800+ satir) Python'a
    cekip dongude max hesapliyordu (Neon'a uzak RTT + veri transferi
    yuzunden tek basina ~900ms'e mal oluyordu) - artik MAX() SQL tarafinda,
    tek skaler deger olarak donuyor."""
    max_n = db.session.query(
        db.func.max(db.cast(db.func.substr(Customer.musteri_no, 3), db.Integer))
    ).filter(Customer.musteri_no.op('~')(r'^M-\d+$')).scalar()
    return max_n or 0

def _next_musteri_no():
    """Tekil musteri olusturma noktalari icin - toplu ice aktarimda (CSV/
    Excel/VCF) bunun yerine _musteri_no_max() bir kez cagrilip donen int
    dongude elle artirilmali (ayni flush icinde tekrar tekrar DB sorgulamak,
    hicbiri henuz commit olmadigi icin hep ayni degeri dondurur)."""
    return f'M-{_musteri_no_max() + 1:04d}'

_TR_LOWER_MAP = str.maketrans({
    'ş': 's', 'Ş': 's', 'ğ': 'g', 'Ğ': 'g', 'ı': 'i', 'I': 'i', 'İ': 'i',
    'ö': 'o', 'Ö': 'o', 'ü': 'u', 'Ü': 'u', 'ç': 'c', 'Ç': 'c',
})

def _normalize_tr(s):
    """Turkce karakterleri ASCII esdegerlerine indirger ve kucuk harfe cevirir.
    Postgres'in ILIKE'i 'saroglu' -> 'Şaroğlu' gibi diyakritiksiz aramalari
    yakalamiyordu (ş != s karakter bazinda), musteri aramasinda bazi
    isimlerin hic bulunamamasina sebep oluyordu."""
    if not s:
        return ''
    return s.translate(_TR_LOWER_MAP).lower()


def _login_rate_limit_key():
    """IP + kullanici adi birlesimi - sadece IP bazli limit, ayni ag/ofis
    arkasindaki farkli kullanicilari birbirini etkileyerek gereksiz yere
    kilitleyebilirdi; IP+kullanici adi kombinasyonu tek bir hesaba yonelik
    kaba kuvvet denemesini hedefler."""
    from flask_limiter.util import get_remote_address
    username = (request.form.get('username') or '').strip().lower()
    return f'{get_remote_address()}:{username}'

def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            flash('Bu işlem için yönetici yetkisi gereklidir.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def register_routes(app):

    # Is 1 (mega menu): sayfa-genelinde (kullaniciya ozel OLMAYAN) navbar
    # canli sayilari - her istekte DB'ye gitmek yerine 60 saniyelik basit
    # process-ici onbellek. Tek process'li (Render web servisi) bir kurulum
    # icin yeterli; birden fazla worker/instance'a olceklenirse paylasimli
    # bir cache (Redis vb.) gerekir.
    _navbar_cache = {'data': None, 'ts': 0}
    NAVBAR_CACHE_TTL = 60

    def _navbar_summary():
        now = time.time()
        if _navbar_cache['data'] is not None and (now - _navbar_cache['ts']) < NAVBAR_CACHE_TTL:
            return _navbar_cache['data']
        yesterday = date.today() - timedelta(days=1)
        row = db.session.query(
            db.session.query(db.func.count(Production.id)).filter_by(status='uretimde').scalar_subquery().label('uretimde_count'),
            db.session.query(db.func.count(Shipment.id)).filter(Shipment.status.notin_(['teslim_edildi'])).scalar_subquery().label('pending_shipments'),
            db.session.query(db.func.sum(DailyProductionOutput.toplam_kg)).filter(DailyProductionOutput.tarih == yesterday).scalar_subquery().label('yesterday_kg'),
            db.session.query(db.func.count(Product.id)).filter(Product.stock_quantity <= Product.min_stock).scalar_subquery().label('low_stock'),
            db.session.query(db.func.count(Commission.id)).filter_by(status='odenmedi').scalar_subquery().label('pending_commissions'),
            db.session.query(db.func.count(Reminder.id)).filter_by(is_read=False).scalar_subquery().label('unread_reminders'),
        ).one()
        data = {
            'uretimde_count': row.uretimde_count or 0,
            'pending_shipments': row.pending_shipments or 0,
            'yesterday_kg': row.yesterday_kg or 0,
            'low_stock': row.low_stock or 0,
            'pending_commissions': row.pending_commissions or 0,
            'unread_reminders': row.unread_reminders or 0,
        }
        _navbar_cache['data'] = data
        _navbar_cache['ts'] = now
        return data

    @app.context_processor
    def _inject_navbar_summary():
        """Her sablona (base.html mega menude kullanilir) navbar_summary
        dict'ini + kullaniciya ozel takip_gerekiyor sayisini enjekte eder -
        her route'un kendi render_template cagrisina ayni degiskeni elle
        eklemesine gerek kalmaz. Giris yapilmamissa (login sayfasi) bos
        deger donup DB'ye hic gitmez."""
        if not current_user.is_authenticated:
            return {'navbar_summary': {}, 'navbar_takip_gerekiyor_count': 0}
        summary = dict(_navbar_summary())
        summary['takip_gerekiyor_count'] = _takip_gerekiyor_query().count()
        return {'navbar_summary': summary, 'navbar_takip_gerekiyor_count': summary['takip_gerekiyor_count']}

    @app.errorhandler(429)
    def _rate_limit_exceeded(e):
        flash('Çok fazla giriş denemesi yaptınız. Lütfen bir dakika bekleyip tekrar deneyin.', 'danger')
        return render_template('login.html'), 429

    @app.route('/login', methods=['GET', 'POST'])
    @limiter.limit('5 per minute', key_func=_login_rate_limit_key, methods=['POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            remember = request.form.get('remember')
            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password):
                login_user(user, remember=bool(remember))
                user.last_login = datetime.utcnow()
                db.session.commit()
                flash('Hoş geldiniz!', 'success')
                return redirect(request.args.get('next') or url_for('index'))
            flash('Kullanıcı adı veya şifre hatalı.', 'danger')
        return render_template('login.html')

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        flash('Çıkış yapıldı.', 'info')
        return redirect(url_for('login'))

    @app.route('/users')
    @admin_required
    def users():
        users = User.query.order_by(User.created_at.desc()).all()
        return render_template('users.html', users=users)

    @app.route('/users/add', methods=['GET', 'POST'])
    @admin_required
    def add_user():
        if request.method == 'POST':
            user = User(
                username=request.form['username'],
                email=request.form['email'],
                full_name=request.form.get('full_name'),
                role=request.form.get('role', 'user')
            )
            user.set_password(request.form['password'])
            db.session.add(user)
            db.session.commit()
            flash('Kullanıcı eklendi.', 'success')
            return redirect(url_for('users'))
        return render_template('add_user.html')

    @app.route('/users/<int:id>/edit', methods=['GET', 'POST'])
    @admin_required
    def edit_user(id):
        user = User.query.get_or_404(id)
        if request.method == 'POST':
            user.username = request.form['username']
            user.email = request.form['email']
            user.full_name = request.form.get('full_name')
            user.role = request.form.get('role', 'user')
            user.is_active = 'is_active' in request.form
            if request.form.get('password'):
                user.set_password(request.form['password'])
            db.session.commit()
            flash('Kullanıcı güncellendi.', 'success')
            return redirect(url_for('users'))
        return render_template('edit_user.html', user=user)

    @app.route('/')
    @login_required
    def index():
        today = datetime.now().date()

        # Performans: asagidaki 10 bagimsiz COUNT/SUM sorgusu Neon'a (uzak,
        # yuksek RTT'li) ayri ayri 10 round-trip yerine TEK bir sorguda
        # (her biri scalar_subquery olarak) calistirilir - dashboard'daki
        # olcumde bu sorgular RTT basina ~400-900ms'e mal oluyordu.
        # Is 1: deals/total_value/active_deals/customers_with_orders - hepsi
        # teklif gorunurluk kuralina tabi (_apply_deal_visibility) - eskiden
        # bu 4'u HICBIR kisitlama uygulamiyordu, normal bir kullanici
        # Dashboard'da "73 teklif" gorup /deals'ta sadece 12 tanesini
        # gorebiliyordu (tutarsizlik).
        stats = db.session.query(
            db.session.query(db.func.count(Customer.id)).scalar_subquery().label('customers'),
            _apply_deal_visibility(db.session.query(db.func.count(Deal.id))).scalar_subquery().label('deals'),
            _apply_deal_visibility(db.session.query(db.func.sum(Deal.value))).scalar_subquery().label('total_value'),
            _apply_deal_visibility(db.session.query(db.func.count(Deal.id)).filter(
                Deal.stage.notin_(['kazanilan', 'kaybedilen'])
            )).scalar_subquery().label('active_deals'),
            db.session.query(db.func.count(Production.id)).scalar_subquery().label('production_count'),
            db.session.query(db.func.count(Shipment.id)).filter(
                Shipment.status.notin_(['teslim_edildi'])
            ).scalar_subquery().label('pending_shipments'),
            db.session.query(db.func.count(Product.id)).scalar_subquery().label('product_count'),
            db.session.query(db.func.count(Reminder.id)).filter(
                Reminder.is_read == False
            ).scalar_subquery().label('unread_reminders'),
            db.session.query(db.func.count(Customer.id)).filter(
                Customer.company_name.isnot(None)
            ).scalar_subquery().label('customer_types'),
            db.session.query(db.func.count(CustomerVisit.id)).scalar_subquery().label('total_visits'),
            _apply_deal_visibility(
                db.session.query(db.func.count(db.distinct(Customer.id))).select_from(Customer).join(
                    Deal, Deal.customer_id == Customer.id
                ).filter(Deal.stage == 'kazanilan')
            ).scalar_subquery().label('customers_with_orders'),
        ).one()

        customers = stats.customers
        deals = stats.deals
        total_value = stats.total_value or 0
        active_deals = stats.active_deals
        production_count = stats.production_count
        pending_shipments = stats.pending_shipments
        product_count = stats.product_count
        unread_reminders = stats.unread_reminders
        customer_types = stats.customer_types
        total_visits = stats.total_visits
        customers_with_orders = stats.customers_with_orders

        low_stock_products = Product.query.filter(Product.stock_quantity <= Product.min_stock).order_by(Product.stock_quantity).all()
        low_stock = len(low_stock_products)

        pending_price_reports = DailyReport.query.filter_by(status='fiyat_verilecek').order_by(DailyReport.report_date.asc()).all()
        pending_price_list = [(r, (today - r.report_date).days) for r in pending_price_reports]

        expiring_deals = _apply_deal_visibility(Deal.query.filter(
            Deal.valid_until <= today + timedelta(days=2),
            Deal.valid_until >= today,
            Deal.stage.notin_(['kazanilan', 'kaybedilen', 'revize'])
        )).all()

        expired_deals = _apply_deal_visibility(Deal.query.filter(
            Deal.valid_until < today,
            Deal.stage.notin_(['kazanilan', 'kaybedilen', 'revize'])
        )).all()

        recent_deals = _apply_deal_visibility(Deal.query).order_by(Deal.created_at.desc()).limit(5).all()
        recent_customers = Customer.query.order_by(Customer.created_at.desc()).limit(5).all()
        
        upcoming_tasks = Task.query.filter(
            Task.due_date >= today,
            Task.status.notin_(['tamamlandi'])
        ).order_by(Task.due_date).limit(5).all()
        
        today_tasks = Task.query.filter(
            Task.due_date == today,
            Task.status.notin_(['tamamlandi'])
        ).all()
        
        monthly_sales_rows = _apply_deal_visibility(db.session.query(
            db.func.to_char(Deal.created_at, 'YYYY-MM').label('month'),
            db.func.sum(Deal.value).label('total')
        ).filter(Deal.stage == 'kazanilan')).group_by(db.func.to_char(Deal.created_at, 'YYYY-MM')).order_by(db.text('1 DESC')).limit(6).all()
        monthly_sales = [(r.month, r.total) for r in monthly_sales_rows]

        stage_stats = _apply_deal_visibility(db.session.query(
            Deal.stage,
            db.func.count(Deal.id)
        )).group_by(Deal.stage).all()
        
        individual_customers = customers - customer_types

        # Yeni müşteri istatistikleri
        recent_visits = CustomerVisit.query.order_by(CustomerVisit.visit_date.desc()).limit(5).all()
        
        # Ortalama sipariş dönüşümü (ilk siparişi olan müşteri / toplam müşteri)
        conversion_rate = (customers_with_orders / customers * 100) if customers > 0 else 0
        
        # Müşteri ortalama yaşı (ilk müşterinin eklenme tarihinden bugüne)
        first_customer = Customer.query.order_by(Customer.created_at.asc()).first()
        avg_customer_days = 0
        if first_customer:
            avg_customer_days = (today - first_customer.created_at.date()).days

        # Müşteri Takip Döngüsü: son siparişten itibaren siparis_dongusu_gun
        # kadar süre sonra yeni bir siparişin beklendiği, ve bu tarihe 30 gün
        # veya daha az kaldığı (ya da geçtiği) müşteriler.
        last_order_subq = db.session.query(
            Deal.customer_id,
            db.func.max(Deal.deal_date).label('last_order_date')
        ).filter(Deal.stage == 'kazanilan').group_by(Deal.customer_id).subquery()

        production_cycle_rows = db.session.query(Customer, last_order_subq.c.last_order_date).join(
            last_order_subq, Customer.id == last_order_subq.c.customer_id
        ).filter(Customer.status != 'musteri_degil').all()

        production_cycle_customers = []
        for cust, last_order_date in production_cycle_rows:
            if not last_order_date:
                continue
            next_expected = last_order_date + timedelta(days=cust.siparis_dongusu_gun)
            days_remaining = (next_expected - today).days
            if days_remaining <= 30:
                production_cycle_customers.append({
                    'customer': cust,
                    'last_order_date': last_order_date,
                    'next_expected': next_expected,
                    'days_remaining': days_remaining,
                })
        production_cycle_customers.sort(key=lambda x: x['days_remaining'])
        production_cycle_customers = production_cycle_customers[:10]

        # 60 gunluk takip dongusu (bkz. _takip_gerekiyor_query) - gercek
        # zamanli hesaplanir, her istekte guncel veriye gore calisir.
        takip_gerekiyor_count = _takip_gerekiyor_query().count()

        # Is 6: Dashboard sag panel - Prim ozeti (admin TUMUNU, normal
        # kullanici SADECE kendi odenmemis primini gorur - Commission.user_id).
        commission_query = Commission.query.filter_by(status='odenmedi')
        if not current_user.is_admin:
            commission_query = commission_query.filter_by(user_id=current_user.id)
        pending_commissions = commission_query.all()
        pending_commission_total = sum(c.amount for c in pending_commissions)
        pending_commission_count = len(pending_commissions)

        # Is 2 (sag panel): Gorevler (acik sayisi) + Uretim Raporu (Uretim
        # Listesi'yle AYNI _production_report_data() fonksiyonu - tek kaynak).
        open_tasks_count = Task.query.filter(Task.status != 'tamamlandi').count()
        production_report = _production_report_data()

        return render_template('index.html',
                             pending_commission_total=pending_commission_total,
                             pending_commission_count=pending_commission_count,
                             takip_gerekiyor_count=takip_gerekiyor_count,
                             open_tasks_count=open_tasks_count,
                             production_report=production_report,
                             customers=customers, 
                             deals=deals,
                             total_value=total_value,
                             active_deals=active_deals,
                             production_count=production_count,
                             pending_shipments=pending_shipments,
                             product_count=product_count,
                             low_stock=low_stock,
                             low_stock_products=low_stock_products,
                             pending_price_reports=pending_price_reports,
                             pending_price_list=pending_price_list,
                             expiring_deals=expiring_deals,
                             expired_deals=expired_deals,
                             unread_reminders=unread_reminders,
                             recent_deals=recent_deals,
                             recent_customers=recent_customers,
                             upcoming_tasks=upcoming_tasks,
                             today_tasks=today_tasks,
                             monthly_sales=monthly_sales,
                             stage_stats=stage_stats,
                             customer_types=customer_types,
                             individual_customers=individual_customers,
                             total_visits=total_visits,
                             recent_visits=recent_visits,
                             conversion_rate=conversion_rate,
                             avg_customer_days=avg_customer_days,
                             production_cycle_customers=production_cycle_customers)

    @app.route('/reminders')
    @login_required
    def reminders():
        reminders = Reminder.query.order_by(Reminder.remind_date.desc()).all()
        return render_template('reminders.html', reminders=reminders)

    @app.route('/reminders/<int:id>/read', methods=['POST'])
    @login_required
    def mark_reminder_read(id):
        reminder = Reminder.query.get_or_404(id)
        reminder.is_read = True
        db.session.commit()
        flash('Hatırlatma okundu.', 'success')
        return redirect(url_for('reminders'))

    @app.route('/customers')
    @login_required
    def customers():
        search = request.args.get('search', '')
        page = request.args.get('page', 1, type=int)
        query = _apply_customers_search_filter(
            Customer.query.filter(Customer.status != 'musteri_degil'), search
        )
        pagination = query.order_by(Customer.created_at.desc()).paginate(page=page, per_page=200, error_out=False)
        customers = pagination.items

        dormant_cutoff = datetime.utcnow() - timedelta(days=90)
        last_deal_subq2 = db.session.query(
            Deal.customer_id,
            db.func.max(Deal.created_at).label('last_deal_at')
        ).group_by(Deal.customer_id).subquery()

        # Performans: bu 3 bagimsiz COUNT sorgusu (once ayri ayri 3
        # round-trip) tek sorguda (scalar_subquery) birlestirildi - bkz.
        # dashboard'daki (index()) ayni desen.
        list_stats = db.session.query(
            db.session.query(db.func.count(Customer.id)).filter_by(
                status='musteri_degil'
            ).scalar_subquery().label('not_customer_count'),
            db.session.query(db.func.count(Customer.id)).filter(
                Customer.status != 'musteri_degil',
                ~Customer.id.in_(_customers_with_activity_subquery())
            ).scalar_subquery().label('never_transacted_count'),
            db.session.query(db.func.count(Customer.id)).select_from(Customer).join(
                last_deal_subq2, Customer.id == last_deal_subq2.c.customer_id
            ).filter(
                Customer.status != 'musteri_degil',
                last_deal_subq2.c.last_deal_at < dormant_cutoff
            ).scalar_subquery().label('dormant_count'),
        ).one()
        not_customer_count = list_stats.not_customer_count
        never_transacted_count = list_stats.never_transacted_count
        dormant_count = list_stats.dormant_count

        takip_gerekiyor_count = _takip_gerekiyor_query().count()

        # Is 2 (sag panel): bu hafta eklenen + mukerrer kayit sayisi
        # (/customers/mukerrer ile AYNI _duplicate_phone_groups() - tek kaynak).
        week_start = (datetime.utcnow() - timedelta(days=datetime.utcnow().weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        this_week_count = Customer.query.filter(Customer.created_at >= week_start).count()
        duplicate_groups, suspicious_groups = _duplicate_phone_groups()
        duplicate_group_count = len(duplicate_groups)

        # Is 3: 'Secilenleri su kullaniciya ata' dropdown'u SADECE admin
        # icin - normal kullaniciya ekstra sorgu yapilmaz.
        all_users = User.query.order_by(User.username).all() if current_user.is_admin else []

        return render_template('customers.html', customers=customers, search=search, pagination=pagination,
                                not_customer_count=not_customer_count, never_transacted_count=never_transacted_count,
                                dormant_count=dormant_count, takip_gerekiyor_count=takip_gerekiyor_count,
                                this_week_count=this_week_count, duplicate_group_count=duplicate_group_count,
                                all_users=all_users)

    def _customers_return_url():
        """Is 6: musteri listesindeki satir-ici islem formlari (sil/musteri
        degil/birlestir) sayfa/arama parametrelerini gizli alan olarak
        tasir - boylece islem sonrasi kullanici hep sayfa 1'e degil,
        islem yaptigi sayfaya geri doner."""
        page = request.form.get('page', '').strip()
        search = request.form.get('search', '').strip()
        kwargs = {}
        if page.isdigit():
            kwargs['page'] = int(page)
        if search:
            kwargs['search'] = search
        return url_for('customers', **kwargs)

    def _apply_customers_search_filter(query, search):
        """customers() ve toplu islem route'u (bulk_mark_not_customer) AYNI
        arama mantigini paylasir - 'Tumunu Sec (Filtrelenmis Tumu)' modunda
        toplu islemin GERCEKTEN ekrandaki filtreyle ayni satirlari
        kapsadigindan emin olmak icin (Is 1)."""
        if search:
            query = query.filter(
                db.or_(
                    Customer.first_name.ilike(f'%{search}%'),
                    Customer.last_name.ilike(f'%{search}%'),
                    Customer.company_name.ilike(f'%{search}%'),
                    Customer.email.ilike(f'%{search}%'),
                    Customer.tax_id.ilike(f'%{search}%'),
                    Customer.phone.ilike(f'%{search}%')
                )
            )
        return query

    @app.route('/customers/bulk/mark-not-customer', methods=['POST'])
    @login_required
    def bulk_mark_not_customer():
        """Is 1: 'Tumunu Sec' iki modu destekler - (a) sadece o an ekrandaki
        sayfa (customer_ids[] ile acik liste) veya (b) 'Filtrelenmis TUMU'
        (select_all_filtered=1 + search). (b) modunda 1716+ satir icin
        tek tek ID gondermek/Python'da donmek yerine, AYNI filtre kriteriyle
        TEK bir bulk UPDATE calistirilir - performans (zaman asimi riski
        olmadan) ve dogruluk (customers() ile ayni kaynak) birlikte saglanir."""
        select_all_filtered = request.form.get('select_all_filtered') == '1'
        search = request.form.get('search', '').strip()

        if select_all_filtered:
            query = _apply_customers_search_filter(
                Customer.query.filter(Customer.status != 'musteri_degil'), search
            )
            count = query.update({'status': 'musteri_degil'}, synchronize_session=False)
            db.session.commit()
            flash(f'{count} müşteri "Müşteri Değil" olarak işaretlendi.', 'success')
        else:
            ids = request.form.getlist('customer_ids')
            if not ids:
                flash('Hiçbir kayıt seçmediniz.', 'warning')
                return redirect(_customers_return_url())
            count = Customer.query.filter(Customer.id.in_(ids)).update(
                {'status': 'musteri_degil'}, synchronize_session=False
            )
            db.session.commit()
            flash(f'{count} müşteri "Müşteri Değil" olarak işaretlendi.', 'success')

        return redirect(_customers_return_url())

    @app.route('/customers/bulk/assign-owner', methods=['POST'])
    @login_required
    @admin_required
    def bulk_assign_owner():
        """Is 3: 'Secilenleri su kullaniciya ata' - bulk_mark_not_customer
        ile AYNI iki mod (secili ID'ler / filtrelenmis TUMU, tek UPDATE).
        SADECE admin - route seviyesinde de korunuyor (sadece sablonda
        butonu gizlemek yetmez)."""
        owner_id = request.form.get('owner_user_id', type=int)
        if not owner_id or not User.query.get(owner_id):
            flash('Geçerli bir kullanıcı seçmelisiniz.', 'danger')
            return redirect(_customers_return_url())

        select_all_filtered = request.form.get('select_all_filtered') == '1'
        search = request.form.get('search', '').strip()

        if select_all_filtered:
            query = _apply_customers_search_filter(
                Customer.query.filter(Customer.status != 'musteri_degil'), search
            )
            count = query.update({'owner_user_id': owner_id}, synchronize_session=False)
        else:
            ids = request.form.getlist('customer_ids')
            if not ids:
                flash('Hiçbir kayıt seçmediniz.', 'warning')
                return redirect(_customers_return_url())
            count = Customer.query.filter(Customer.id.in_(ids)).update(
                {'owner_user_id': owner_id}, synchronize_session=False
            )
        db.session.commit()
        owner = User.query.get(owner_id)
        flash(f'{count} müşteri "{owner.username}" kullanıcısına atandı.', 'success')
        return redirect(_customers_return_url())

    @app.route('/customers/<int:id>/mark-not-customer', methods=['POST'])
    @login_required
    def mark_not_customer(id):
        customer = Customer.query.get_or_404(id)
        customer.status = 'musteri_degil'
        db.session.commit()
        flash(f'"{customer.display_name}" "Müşteri Değil" olarak işaretlendi ve listeden gizlendi.', 'success')
        return redirect(_customers_return_url())

    @app.route('/customers/not-customer')
    @login_required
    def not_customer_list():
        items = Customer.query.filter_by(status='musteri_degil').order_by(Customer.updated_at.desc()).all()
        return render_template('customers_not_customer.html', customers=items)

    @app.route('/customers/not-customer/restore', methods=['POST'])
    @login_required
    def restore_not_customer():
        ids = request.form.getlist('customer_ids')
        if not ids:
            flash('Hiçbir kayıt seçmediniz.', 'warning')
            return redirect(url_for('not_customer_list'))
        customers = Customer.query.filter(Customer.id.in_(ids), Customer.status == 'musteri_degil').all()
        for c in customers:
            c.status = 'aktif'
        db.session.commit()
        flash(f'{len(customers)} kayıt geri alındı, tekrar normal müşteri listesinde görünecek.', 'success')
        return redirect(url_for('not_customer_list'))

    @app.route('/customers/not-customer/delete', methods=['POST'])
    @login_required
    def delete_not_customer():
        ids = request.form.getlist('customer_ids')
        if not ids:
            flash('Hiçbir kayıt seçmediniz.', 'warning')
            return redirect(url_for('not_customer_list'))

        customers = Customer.query.filter(Customer.id.in_(ids), Customer.status == 'musteri_degil').all()
        deleted = 0
        blocked = []
        for c in customers:
            has_deps = (Deal.query.filter_by(customer_id=c.id).first()
                        or Payment.query.filter_by(customer_id=c.id).first()
                        or CustomerStatement.query.filter_by(customer_id=c.id).first())
            if has_deps:
                blocked.append(c.display_name)
                continue
            db.session.delete(c)
            deleted += 1
        db.session.commit()

        msg = f'{deleted} kayıt kalıcı olarak silindi.'
        if blocked:
            msg += f' {len(blocked)} kayıt bağlı teklif/ödeme/ekstre kaydı olduğu için silinemedi: {", ".join(blocked[:5])}'
            if len(blocked) > 5:
                msg += ' ...'
        flash(msg, 'warning' if blocked else 'success')
        return redirect(url_for('not_customer_list'))

    @app.route('/customers/never-transacted')
    @login_required
    def never_transacted_customers():
        page = request.args.get('page', 1, type=int)
        query = Customer.query.filter(
            Customer.status != 'musteri_degil',
            ~Customer.id.in_(_customers_with_activity_subquery())
        ).order_by(Customer.created_at.desc())
        pagination = query.paginate(page=page, per_page=50, error_out=False)
        return render_template('customers_never_transacted.html', customers=pagination.items, pagination=pagination)

    @app.route('/customers/dormant')
    @login_required
    def dormant_customers():
        page = request.args.get('page', 1, type=int)
        cutoff = datetime.utcnow() - timedelta(days=90)

        last_deal_subq = db.session.query(
            Deal.customer_id,
            db.func.max(Deal.created_at).label('last_deal_at')
        ).group_by(Deal.customer_id).subquery()

        query = db.session.query(Customer, last_deal_subq.c.last_deal_at).join(
            last_deal_subq, Customer.id == last_deal_subq.c.customer_id
        ).filter(
            Customer.status != 'musteri_degil',
            last_deal_subq.c.last_deal_at < cutoff
        ).order_by(last_deal_subq.c.last_deal_at.asc())

        pagination = query.paginate(page=page, per_page=50, error_out=False)
        rows = [{'customer': c, 'last_deal_at': d, 'days_inactive': (datetime.utcnow() - d).days}
                for c, d in pagination.items]
        return render_template('customers_dormant.html', rows=rows, pagination=pagination)

    @app.route('/customers/takip-gerekiyor')
    @login_required
    def takip_gerekiyor_customers():
        """60 gunluk takip dongusu (bkz. _takip_gerekiyor_query) - Gunluk
        Rapor/Teklif/Odeme'den hicbirinde son TAKIP_GEREKEN_GUN gun icinde
        irtibat kaydi olmayan musteriler. Hic irtibat kaydi olmayanlar en
        basta (NULL'lar once), sonra en eski irtibat once siralanir."""
        page = request.args.get('page', 1, type=int)
        today = date.today()
        pagination = _takip_gerekiyor_query().paginate(page=page, per_page=50, error_out=False)
        rows = [{
            'customer': customer,
            'last_contact': last_contact,
            'days_since': (today - last_contact).days if last_contact else None,
        } for customer, last_contact in pagination.items]
        return render_template('customers_takip_gerekiyor.html', rows=rows, pagination=pagination,
                                takip_gereken_gun=TAKIP_GEREKEN_GUN)

    @app.route('/customers/mukerrer')
    @login_required
    def duplicate_customers():
        """Is 8 (bu oturumda asagida doldurulacak): telefon numarasi
        normalize edilerek aynı numaraya sahip musteri gruplarini bulur.
        Simdilik placeholder - Is 8'de tam doldurulacak."""
        return render_template('customers_duplicate.html', groups=[])

    @app.route('/hizli-iletisim')
    @login_required
    def hizli_iletisim():
        """Is 2: Sehir bazli hizli iletisim - kullanicinin (admin icin
        TUMUNUN) 60+ gun sessiz musterilerini Yakin Bolge (Konya+Aksaray,
        ilceler dahil - tek grup) ve Diger Iller (il bazinda ayri gruplu)
        olarak gosterir. Telefonu olmayan musteriler WhatsApp gonderilemedigi
        icin listelenmez. Sehri cikarilamayan musteriler (adres/isimde il adi
        gecmeyen) hicbir gruba girmez - bu CRM'de musterilerin buyuk kismi
        boyle (bkz. extract_customer_city docstring)."""
        rows = _takip_gerekiyor_query().all()
        today = date.today()
        near_region = []
        other_cities = {}
        for customer, last_contact in rows:
            if not customer.phone:
                continue
            city = extract_customer_city(customer)
            item = {
                'customer': customer,
                'last_contact': last_contact,
                'days_since': (today - last_contact).days if last_contact else None,
            }
            if city in ('Konya', 'Aksaray'):
                near_region.append(item)
            elif city:
                other_cities.setdefault(city, []).append(item)
        other_cities_sorted = sorted(other_cities.items(), key=lambda kv: kv[0])
        return render_template('hizli_iletisim.html', near_region=near_region,
                                other_cities=other_cities_sorted,
                                takip_gereken_gun=TAKIP_GEREKEN_GUN)

    @app.route('/cari-hesap-ozeti')
    @login_required
    def cari_hesap_ozeti():
        """Is F: musteri bazli cari hesap ozeti. Performans icin (1600+ musteri)
        Customer.total_invoiced/total_uninvoiced_won/total_collected
        property'lerini tek tek her musteride cagirmak yerine (N+1 sorgu),
        toplam tutarlari 3 GROUP BY sorgusuyla topluca cekip Python
        tarafinda esler - sonuc matematiksel olarak Customer property'leriyle
        (ve dolayisiyla Musteri Detayi sayfasiyla) birebir ayni (ayni Invoice/
        Deal/Payment kayitlarindan, canli hesaplanir, onbelleklenmez).

        Cari Hesap Birlestirme duzeltmesi: Bakiye artik sadece faturalanmis
        tutarlari degil, kazanilmis (stage='kazanilan') ama HENUZ fatura
        kesilmemis tekliflerin degerini de iceriyor - onceden bu tutar hic
        gorunmuyordu, oysa canli veride kazanilan tekliflerin buyuk kismi
        henuz faturalanmamisti (bkz. Customer.total_uninvoiced_won).

        Is 7: profesyonel gelistirmeler - borc yaslandirma (en eski acik
        fatura/faturalanmamis kazanilan teklif tarihinden bugune gun sayisi),
        sehir/temsilci filtresi + Benim Musterilerim/Tumu (admin), son
        WhatsApp mesaji bilgisi. Hepsi TOPLU sorgularla (N+1 YOK - RTT-bound
        Neon'da 1700+ musteri icin tek tek sorgu pratik degil)."""
        filter_type = request.args.get('filter', '')
        city_filter = request.args.get('city', '')
        owner_filter = request.args.get('owner', type=int)
        sort = request.args.get('sort', '')

        rows, available_cities, cari_own_only = _cari_hesap_rows()

        if city_filter:
            rows = [r for r in rows if r['city'] == city_filter]
        if owner_filter:
            rows = [r for r in rows if r['customer'].owner_user_id == owner_filter]

        if filter_type == 'borclu':
            rows = [r for r in rows if r['balance'] > 0.01]
        elif filter_type == 'alacakli':
            rows = [r for r in rows if r['balance'] < -0.01]
        elif filter_type == 'sifir':
            rows = [r for r in rows if -0.01 <= r['balance'] <= 0.01]

        if sort == 'balance_asc':
            rows.sort(key=lambda r: r['balance'])
        elif sort == 'balance_desc':
            rows.sort(key=lambda r: r['balance'], reverse=True)
        else:
            rows.sort(key=lambda r: abs(r['balance']), reverse=True)

        all_users = User.query.order_by(User.username).all()

        return render_template('cari_hesap_ozeti.html', rows=rows, filter_type=filter_type,
                                city_filter=city_filter, owner_filter=owner_filter, sort=sort,
                                available_cities=available_cities, all_users=all_users,
                                cari_own_only=cari_own_only)

    def _cari_hesap_rows():
        """Cari Hesap Ozeti'nin TUM satir verisini (bakiye + Is 7 ek
        alanlari: sehir, borc yasi, son whatsapp mesaji) toplu sorgularla
        hazirlar - /cari-hesap-ozeti, Excel/PDF disa aktarim route'lari
        ayni fonksiyonu kullanir (ekranda gorunenle disa aktarilan HER ZAMAN
        birebir ayni satirlari icerir, bkz. Uretim Listesi'ndeki ayni desen).
        Admin icin oturum bazli 'Sadece Benim Musterilerim' tercihini de
        uygular (_admin_deals_own_only ile ayni desen)."""
        invoiced_rows = db.session.query(
            Invoice.customer_id, db.func.sum(Invoice.total)
        ).filter(Invoice.type == 'fatura').group_by(Invoice.customer_id).all()
        invoiced_map = {cid: total or 0 for cid, total in invoiced_rows}

        oldest_invoice_rows = db.session.query(
            Invoice.customer_id, db.func.min(Invoice.created_at)
        ).filter(Invoice.type == 'fatura').group_by(Invoice.customer_id).all()
        oldest_invoice_map = dict(oldest_invoice_rows)

        invoiced_deal_ids_subq = db.session.query(Invoice.deal_id).filter(
            Invoice.type == 'fatura', Invoice.deal_id.isnot(None)
        )
        # Is 5A: Customer.total_uninvoiced_won ile AYNI kural (tek kaynak) -
        # sadece Production'i 'hazir'/'sevkiyat' asamasina gelmis tekliflerin
        # degeri "faturalanmamis kazanilan" bakiyesine dahil edilir.
        uninvoiced_won_rows = db.session.query(
            Deal.customer_id, db.func.sum(Deal.value)
        ).join(Production, Production.deal_id == Deal.id).filter(
            Deal.stage == 'kazanilan', ~Deal.id.in_(invoiced_deal_ids_subq),
            Production.status.in_(['hazir', 'sevkiyat'])
        ).group_by(Deal.customer_id).all()
        uninvoiced_won_map = {cid: total or 0 for cid, total in uninvoiced_won_rows}

        oldest_uninvoiced_deal_rows = db.session.query(
            Deal.customer_id, db.func.min(Deal.created_at)
        ).join(Production, Production.deal_id == Deal.id).filter(
            Deal.stage == 'kazanilan', ~Deal.id.in_(invoiced_deal_ids_subq),
            Production.status.in_(['hazir', 'sevkiyat'])
        ).group_by(Deal.customer_id).all()
        oldest_uninvoiced_deal_map = dict(oldest_uninvoiced_deal_rows)

        collected_rows = db.session.query(
            Payment.customer_id, db.func.sum(Payment.amount)
        ).filter(Payment.status == 'odendi').group_by(Payment.customer_id).all()
        collected_map = {cid: total or 0 for cid, total in collected_rows}

        # Is 7 madde 5: son WhatsApp mesaji tarihi - musteri_whatsapp_send()
        # her gonderimde 'WhatsApp mesajı gönderildi:' notuyla bir DailyReport
        # olusturuyor (bkz. customer_whatsapp_send), o yuzden bu kayitlarin
        # customer_id bazinda EN SON report_date'i yeterli.
        last_whatsapp_rows = db.session.query(
            DailyReport.customer_id, db.func.max(DailyReport.report_date)
        ).filter(
            DailyReport.customer_id.isnot(None),
            DailyReport.notes.ilike('WhatsApp mesajı gönderildi:%')
        ).group_by(DailyReport.customer_id).all()
        last_whatsapp_map = dict(last_whatsapp_rows)

        today = date.today()

        customers_query = Customer.query.filter(Customer.status != 'musteri_degil')
        cari_own_only = bool(session.get('cari_hesap_own_only'))
        if not current_user.is_admin:
            customers_query = customers_query.filter(Customer.owner_user_id == current_user.id)
        elif cari_own_only:
            customers_query = customers_query.filter(Customer.owner_user_id == current_user.id)
        customers = customers_query.all()

        rows = []
        cities = set()
        for c in customers:
            invoiced = invoiced_map.get(c.id, 0)
            uninvoiced_won = uninvoiced_won_map.get(c.id, 0)
            collected = collected_map.get(c.id, 0)
            balance = invoiced + uninvoiced_won - collected

            oldest_dates = [d for d in [oldest_invoice_map.get(c.id), oldest_uninvoiced_deal_map.get(c.id)] if d]
            debt_age_days = (today - min(oldest_dates).date()).days if (oldest_dates and balance > 0.01) else None

            last_whatsapp_date = last_whatsapp_map.get(c.id)
            last_whatsapp_days = (today - last_whatsapp_date).days if last_whatsapp_date else None

            city = extract_customer_city(c)
            if city:
                cities.add(city)

            rows.append({
                'customer': c, 'invoiced': invoiced, 'uninvoiced_won': uninvoiced_won,
                'collected': collected, 'balance': balance, 'debt_age_days': debt_age_days,
                'last_whatsapp_days': last_whatsapp_days, 'city': city,
            })
        return rows, sorted(cities), cari_own_only

    @app.route('/cari-hesap-ozeti/view-toggle', methods=['POST'])
    @login_required
    def cari_hesap_view_toggle():
        """Is 7: SADECE admin icin - 'Tumu' / 'Benim Musterilerim' gecis
        anahtari (deals_view_toggle ile AYNI desen), oturum boyunca
        hatirlanir."""
        if current_user.is_admin:
            session['cari_hesap_own_only'] = request.form.get('mode') == 'own'
        return redirect(url_for('cari_hesap_ozeti'))

    @app.route('/cari-hesap-ozeti/export/excel')
    @login_required
    def cari_hesap_export_excel():
        rows, _, _ = _cari_hesap_rows()
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Cari Hesap Özeti'
        ws.append(['Müşteri', 'Şehir', 'Faturalanmış', 'Faturalanmamış Kazanılan', 'Tahsil Edilen', 'Toplam Bakiye', 'Borç Yaşı (gün)'])
        for r in rows:
            ws.append([
                r['customer'].display_name, r['city'] or '-', r['invoiced'], r['uninvoiced_won'],
                r['collected'], r['balance'], r['debt_age_days'] if r['debt_age_days'] is not None else '-',
            ])
        buffer = BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return send_file(buffer, as_attachment=True, download_name=f'cari_hesap_ozeti_{datetime.now().strftime("%Y%m%d")}.xlsx',
                          mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    @app.route('/cari-hesap-ozeti/export/pdf')
    @login_required
    def cari_hesap_export_pdf():
        rows, _, _ = _cari_hesap_rows()
        pdf = generate_cari_hesap_pdf(rows)
        return send_file(pdf, as_attachment=True, download_name=f'cari_hesap_ozeti_{datetime.now().strftime("%Y%m%d")}.pdf')

    @app.route('/customers/add', methods=['GET', 'POST'])
    @login_required
    def add_customer():
        if request.method == 'POST':
            first_name = request.form.get('first_name') or ''
            last_name = request.form.get('last_name') or ''
            
            # Aynı isimden varsa engelle
            existing = Customer.query.filter_by(first_name=first_name, last_name=last_name).first()
            if existing:
                flash(f'"{first_name} {last_name}" adında bir müşteri zaten kayıtlı!', 'danger')
                return render_template('add_customer.html')
            
            customer = Customer(
                musteri_no=_next_musteri_no(),
                first_name=first_name or None,
                last_name=last_name or None,
                email=request.form.get('email') or None,
                phone=request.form.get('phone'),
                company_name=request.form.get('company_name'),
                tax_office=request.form.get('tax_office'),
                tax_id=request.form.get('tax_id'),
                trade_registry=request.form.get('trade_registry'),
                company_phone=request.form.get('company_phone'),
                company_address=request.form.get('company_address'),
                company_email=request.form.get('company_email'),
                company_website=request.form.get('company_website'),
                contact_person=request.form.get('contact_person'),
                contact_title=request.form.get('contact_title'),
                contact_phone=request.form.get('contact_phone'),
                contact_email=request.form.get('contact_email'),
                address=request.form.get('address'),
                notes=request.form.get('notes'),
                owner_user_id=current_user.id
            )
            db.session.add(customer)
            db.session.commit()
            flash('Müşteri eklendi!', 'success')
            return redirect(url_for('customers'))
        return render_template('add_customer.html')

    @app.route('/customers/import', methods=['GET', 'POST'])
    @login_required
    def import_customers():
        if request.method == 'POST':
            file = request.files.get('file')
            if not file or file.filename == '':
                flash('Lütfen bir dosya seçin.', 'danger')
                return render_template('import_customers.html')
            
            added = 0
            skipped = 0
            errors = []
            
            if file.filename.endswith('.csv'):
                import csv
                import io
                stream = io.StringIO(file.stream.read().decode('utf-8-sig'))
                reader = csv.DictReader(stream)
                next_musteri_n = _musteri_no_max()
                for i, row in enumerate(reader, 1):
                    try:
                        first_name = (row.get('Ad') or row.get('ad') or row.get('first_name') or '').strip()
                        last_name = (row.get('Soyad') or row.get('soyad') or row.get('last_name') or '').strip()
                        phone = (row.get('Telefon') or row.get('telefon') or row.get('phone') or row.get('GSM') or '').strip()

                        if not first_name and not last_name and not phone:
                            continue

                        existing = Customer.query.filter_by(first_name=first_name, last_name=last_name).first()
                        if existing:
                            skipped += 1
                            continue

                        next_musteri_n += 1
                        customer = Customer(
                            musteri_no=f'M-{next_musteri_n:04d}',
                            first_name=first_name or None,
                            last_name=last_name or None,
                            phone=phone or None,
                            email=(row.get('E-posta') or row.get('email') or row.get('Mail') or '').strip() or None,
                            owner_user_id=current_user.id
                        )
                        db.session.add(customer)
                        added += 1
                    except Exception as e:
                        errors.append(f'Satır {i}: {str(e)}')
                
                db.session.commit()
                msg = f'{added} müşteri eklendi.'
                if skipped:
                    msg += f' {skipped} kayıt (aynı isim) atlandı.'
                if errors:
                    msg += f' {len(errors)} hata oluştu.'
                flash(msg, 'success' if added > 0 else 'info')
                if errors:
                    for e in errors[:5]:
                        flash(e, 'warning')
                        
            elif file.filename.endswith(('.xls', '.xlsx')):
                import openpyxl
                wb = openpyxl.load_workbook(file)
                ws = wb.active
                headers = [cell.value for cell in ws[1]]
                next_musteri_n = _musteri_no_max()
                for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
                    try:
                        row_dict = dict(zip(headers, [str(v or '') for v in row]))
                        first_name = (row_dict.get('Ad') or row_dict.get('ad') or row_dict.get('first_name') or '').strip()
                        last_name = (row_dict.get('Soyad') or row_dict.get('soyad') or row_dict.get('last_name') or '').strip()
                        phone = (row_dict.get('Telefon') or row_dict.get('telefon') or row_dict.get('phone') or row_dict.get('GSM') or '').strip()

                        if not first_name and not last_name and not phone:
                            continue

                        existing = Customer.query.filter_by(first_name=first_name, last_name=last_name).first()
                        if existing:
                            skipped += 1
                            continue

                        next_musteri_n += 1
                        customer = Customer(
                            musteri_no=f'M-{next_musteri_n:04d}',
                            first_name=first_name or None,
                            last_name=last_name or None,
                            phone=phone or None,
                            email=(row_dict.get('E-posta') or row_dict.get('email') or row_dict.get('Mail') or '').strip() or None,
                            owner_user_id=current_user.id
                        )
                        db.session.add(customer)
                        added += 1
                    except Exception as e:
                        errors.append(f'Satır {i}: {str(e)}')
                
                db.session.commit()
                msg = f'{added} müşteri eklendi.'
                if skipped:
                    msg += f' {skipped} kayıt (aynı isim) atlandı.'
                if errors:
                    msg += f' {len(errors)} hata oluştu.'
                flash(msg, 'success' if added > 0 else 'info')
                if errors:
                    for e in errors[:5]:
                        flash(e, 'warning')
            else:
                flash('Yalnızca CSV veya Excel (.xls/.xlsx) dosyaları desteklenir.', 'danger')
                return render_template('import_customers.html')
            
            return redirect(url_for('customers'))
        
        return render_template('import_customers.html')

    @app.route('/customers/<int:id>/whatsapp-send', methods=['POST'])
    @login_required
    def customer_whatsapp_send(id):
        """Is 5: WhatsApp modalindaki 'WhatsApp'ta Ac' butonu bu endpoint'e
        AJAX POST atar - telefonu normallestirip wa.me linkini doner VE
        AYNI ANDA otomatik bir DailyReport kaydi olusturur ('WhatsApp mesaji
        gonderildi: ...' notuyla), boylece 60 gunluk takip sayaci
        (_last_contact_subquery DailyReport.report_date'i de kaynak olarak
        kullanir) sifirlanmis olur - ayri bir 'son irtibat' alani/mantigi
        ACILMAZ, mevcut takip mekanizmasi otomatik faydalanir."""
        customer = Customer.query.get_or_404(id)
        message = request.form.get('message', '').strip()
        if not message:
            return jsonify({'error': 'Mesaj boş olamaz.'}), 400
        normalized = _normalize_phone_for_whatsapp(customer.phone)
        if not normalized:
            return jsonify({'error': 'Bu müşterinin telefon numarası kayıtlı değil.'}), 400

        report = DailyReport(
            report_date=datetime.now().date(),
            customer_name=customer.display_name,
            phone=customer.phone,
            notes=f'WhatsApp mesajı gönderildi: {message[:50]}',
            status='tamamlandi',
            user_id=current_user.id,
            customer_id=customer.id,
        )
        db.session.add(report)
        db.session.commit()

        wa_url = f'https://wa.me/{normalized}?text={_url_quote(message)}'
        return jsonify({'wa_url': wa_url})

    @app.route('/customers/<int:id>')
    @login_required
    def customer_detail(id):
        customer = Customer.query.get_or_404(id)
        balance_info = calculate_customer_balance(customer)
        deals = Deal.query.filter_by(customer_id=id).options(
            joinedload(Deal.production).joinedload(Production.shipments)
        ).order_by(Deal.created_at.desc()).all()
        statements = CustomerStatement.query.filter_by(customer_id=id).order_by(CustomerStatement.created_at.desc()).all()
        total_debit = sum(s.amount for s in statements if s.type == 'borc')
        total_credit = sum(s.amount for s in statements if s.type == 'alacak')
        
        # Günlük raporları ekle - önce customer_id ile, sonra isim/telefon ile eşleşenleri bul
        daily_reports = DailyReport.query.filter(
            db.or_(
                DailyReport.customer_id == customer.id,
                DailyReport.customer_name.ilike(f'%{customer.display_name}%'),
                DailyReport.phone == customer.phone
            )
        ).order_by(DailyReport.report_date.desc()).all()

        # Bekleyen iş emirleri: bu müşterinin tekliflerinden doğan, henüz
        # teslim edilmemiş üretim kayıtları (Madde 1 - Üretim İş Emri Otomasyonu).
        # 'sevkiyat' aşaması kargoya verilmiş ama henüz teslim edilmemiş demektir,
        # bu yuzden gercek teslimat (Shipment.status == 'teslim_edildi') olana
        # kadar hala "bekleyen" sayilir (Madde 3 - Sevkiyat Modulu).
        def _is_pending(p):
            if p.status == 'iptal':
                return False
            latest = p.latest_shipment
            return not (latest and latest.status == 'teslim_edildi')
        pending_productions = sorted(
            [d.production for d in deals if d.production and _is_pending(d.production)],
            key=lambda p: p.due_date or date.max
        )

        # Son gorusme tarihi: gunluk rapor / teklif / musteri ziyareti
        # kayitlarindan en guncel olani (Is 2).
        contact_dates = [r.report_date for r in daily_reports]
        contact_dates += [d.deal_date or d.created_at.date() for d in deals]
        contact_dates += [v.visit_date for v in customer.visits]
        last_contact_date = max(contact_dates) if contact_dates else None
        days_since_contact = (date.today() - last_contact_date).days if last_contact_date else None

        return render_template('customer_detail.html', customer=customer, deals=deals,
                             statements=statements, total_debit=total_debit, total_credit=total_credit,
                             balance_info=balance_info,
                             daily_reports=daily_reports, pending_productions=pending_productions,
                             last_contact_date=last_contact_date, days_since_contact=days_since_contact)

    @app.route('/customers/<int:id>/import-statement-pdf', methods=['POST'])
    @login_required
    def import_statement_pdf(id):
        """Is 1: eski cari ekstre PDF'ini (Tarih/Aciklama/Borc/Alacak/Bakiye
        tablosu) dogrudan CustomerStatement'a isler - onizleme ekrani yok.
        Mukerrer (ayni musteri+tarih+tutar+tur) satirlar atlanir."""
        customer = Customer.query.get_or_404(id)
        file = request.files.get('statement_pdf')
        if not file or not file.filename:
            flash('Lütfen bir PDF dosyası seçin.', 'danger')
            return redirect(url_for('customer_detail', id=id))
        if not file.filename.lower().endswith('.pdf'):
            flash('Sadece PDF dosyası yükleyebilirsiniz.', 'danger')
            return redirect(url_for('customer_detail', id=id))

        try:
            rows, pdf_last_balance = parse_statement_pdf(file.stream)
        except Exception as e:
            flash(f'PDF okunamadı: {e}', 'danger')
            return redirect(url_for('customer_detail', id=id))

        if not rows:
            flash('PDF içinde Tarih/Borç/Alacak sütunlarına sahip bir tablo bulunamadı.', 'warning')
            return redirect(url_for('customer_detail', id=id))

        added = 0
        skipped = 0
        for r in rows:
            row_dt = datetime.combine(r['date'], datetime.min.time())
            duplicate = CustomerStatement.query.filter(
                CustomerStatement.customer_id == id,
                CustomerStatement.type == r['type'],
                db.func.abs(CustomerStatement.amount - r['amount']) < 0.01,
                db.func.date(CustomerStatement.created_at) == r['date']
            ).first()
            if duplicate:
                skipped += 1
                continue
            stmt = CustomerStatement(
                customer_id=id, type=r['type'], amount=r['amount'],
                description=r['description'] or ('Borç (PDF)' if r['type'] == 'borc' else 'Alacak (PDF)'),
                created_at=row_dt, source='pdf_import'
            )
            db.session.add(stmt)
            added += 1
        db.session.commit()

        all_statements = CustomerStatement.query.filter_by(customer_id=id).all()
        total_debit = sum(s.amount for s in all_statements if s.type == 'borc')
        total_credit = sum(s.amount for s in all_statements if s.type == 'alacak')
        computed_balance = total_debit - total_credit

        flash(f'{added} satır eklendi, {skipped} satır mükerrer olduğu için atlandı.',
              'success' if added else 'info')

        if pdf_last_balance is not None and abs(computed_balance - pdf_last_balance) > 1.0:
            flash(
                f"Dikkat: PDF'teki son bakiye ({pdf_last_balance:,.2f} ₺) ile sistemin "
                f"hesapladığı bakiye ({computed_balance:,.2f} ₺) arasında fark var - "
                f"PDF formatını veya mevcut ekstre kayıtlarını kontrol edin.", 'warning'
            )

        return redirect(url_for('customer_detail', id=id))

    @app.route('/customers/<int:id>/edit', methods=['GET', 'POST'])
    @login_required
    def edit_customer(id):
        customer = Customer.query.get_or_404(id)
        if request.method == 'POST':
            for field in ['first_name', 'last_name', 'email', 'phone', 'company_name', 'tax_office', 'tax_id',
                         'trade_registry', 'company_phone', 'company_address', 'company_email', 'company_website',
                         'contact_person', 'contact_title', 'contact_phone', 'contact_email', 'address', 'notes', 'status']:
                setattr(customer, field, request.form.get(field) or getattr(customer, field))
            siparis_dongusu = request.form.get('siparis_dongusu_gun')
            if siparis_dongusu:
                customer.siparis_dongusu_gun = int(siparis_dongusu)

            tasarim_file = request.files.get('tasarim_gorseli')
            if tasarim_file and tasarim_file.filename:
                path, error = _save_uploaded_image(tasarim_file, 'tasarimlar')
                if error:
                    flash(error, 'danger')
                    return redirect(url_for('edit_customer', id=id))
                customer.tasarim_gorseli = path

            db.session.commit()
            flash('Müşteri güncellendi!', 'success')
            return redirect(url_for('customer_detail', id=id))
        return render_template('edit_customer.html', customer=customer)

    @app.route('/customers/merge-by-phone', methods=['POST'])
    @login_required
    def merge_customers_by_phone():
        """Aynı telefon numarasına sahip müşterileri birleştir"""
        phone = request.form.get('phone', '').strip()
        if not phone:
            flash('Telefon numarası gereklidir.', 'danger')
            return redirect(_customers_return_url())

        # Aynı telefona sahip tüm müşterileri bul
        customers = Customer.query.filter_by(phone=phone).all()

        if len(customers) <= 1:
            flash('Bu telefon numarası ile tekrar eden müşteri bulunamadı.', 'info')
            return redirect(_customers_return_url())
        
        # En eski müşteriyi ana müşteri olarak seç
        main_customer = sorted(customers, key=lambda x: x.id)[0]
        duplicate_customers = [c for c in customers if c.id != main_customer.id]
        
        # Tekrarlayan müşterilerin ilişkilerini ana müşteriye aktar
        try:
            for dup in duplicate_customers:
                # Teklifleri aktar
                Deal.query.filter_by(customer_id=dup.id).update({'customer_id': main_customer.id})
                # Ekstreleri aktar
                CustomerStatement.query.filter_by(customer_id=dup.id).update({'customer_id': main_customer.id})
                # Günlük raporları güncelle
                DailyReport.query.filter_by(customer_id=dup.id).update({'customer_id': main_customer.id})
                # Ziyaretleri aktar
                CustomerVisit.query.filter_by(customer_id=dup.id).update({'customer_id': main_customer.id})
                # Görevleri aktar
                Task.query.filter_by(customer_id=dup.id).update({'customer_id': main_customer.id})
                # Hatırlatıcıları aktar
                Reminder.query.filter_by(customer_id=dup.id).update({'customer_id': main_customer.id})

                # Tekrarlayan müşteriyi sil
                db.session.delete(dup)

            db.session.commit()
        except Exception:
            db.session.rollback()
            flash('Müşteriler birleştirilirken bir hata oluştu, hiçbir değişiklik kaydedilmedi.', 'danger')
            return redirect(_customers_return_url())

        flash(f'{len(duplicate_customers)} tekrar eden müşteri birleştirildi! Ana müşteri: {main_customer.display_name}', 'success')
        return redirect(_customers_return_url())

    @app.route('/customers/<int:id>/delete', methods=['POST'])
    @login_required
    def delete_customer(id):
        customer = Customer.query.get_or_404(id)
        db.session.delete(customer)
        db.session.commit()
        flash('Müşteri silindi!', 'success')
        return redirect(_customers_return_url())

    @app.route('/customers/<int:id>/statement/pdf')
    @login_required
    def customer_statement_pdf(id):
        customer = Customer.query.get_or_404(id)
        statements = CustomerStatement.query.filter_by(customer_id=id).order_by(CustomerStatement.created_at.desc()).all()
        total_debit = sum(s.amount for s in statements if s.type == 'borc')
        total_credit = sum(s.amount for s in statements if s.type == 'alacak')
        pdf = generate_statement_pdf(customer, statements, total_debit, total_credit)
        return send_file(pdf, as_attachment=True, download_name=f'ekstre_{customer.last_name}_{datetime.now().strftime("%Y%m%d")}.pdf')

    @app.route('/customers/export/excel')
    @login_required
    def customers_export_excel():
        customers = Customer.query.all()
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Müşteriler'
        headers = ['Ad', 'Soyad', 'Firma', 'E-posta', 'Telefon', 'Vergi No', 'Yetkili', 'Durum']
        ws.append(headers)
        for c in customers:
            ws.append([c.first_name, c.last_name, c.company_name or '', c.email, c.phone or '', 
                       c.tax_id or '', c.contact_person or '', c.status])
        buffer = BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return send_file(buffer, as_attachment=True, download_name=f'musteriler_{datetime.now().strftime("%Y%m%d")}.xlsx')

    @app.route('/deals')
    @login_required
    def deals():
        search = request.args.get('search', '')
        stage_filter = request.args.get('stage', '')
        tab = request.args.get('tab', 'aktif')
        page = request.args.get('page', 1, type=int)

        base_query = _apply_deal_visibility(Deal.query)

        RESOLVED_STAGES = ('kazanilan', 'kaybedilen', 'revize')

        def apply_tab(q, t):
            if t == 'aktif':
                return q.filter(~Deal.stage.in_(RESOLVED_STAGES))
            if t == 'kazanilan':
                return q.filter(Deal.stage == 'kazanilan')
            if t == 'kaybedilen':
                return q.filter(Deal.stage == 'kaybedilen')
            return q  # 'tumu'

        # Performans: 4 bagimsiz .count() sorgusu (Neon RTT'si nedeniyle 4
        # ayri round-trip) yerine scalar_subquery ile TEK sorguda (bkz.
        # dashboard/musteri listesi/uretim listesi - ayni desen).
        tab_count_filters = {
            'aktif': ~Deal.stage.in_(RESOLVED_STAGES),
            'kazanilan': Deal.stage == 'kazanilan',
            'kaybedilen': Deal.stage == 'kaybedilen',
        }

        def count_query(t):
            q = _apply_deal_visibility(db.session.query(db.func.count(Deal.id)).select_from(Deal))
            if t in tab_count_filters:
                q = q.filter(tab_count_filters[t])
            return q.scalar_subquery()

        row = db.session.query(
            count_query('aktif').label('aktif'),
            count_query('kazanilan').label('kazanilan'),
            count_query('kaybedilen').label('kaybedilen'),
            count_query('tumu').label('tumu'),
        ).one()
        tab_counts = {'aktif': row.aktif, 'kazanilan': row.kazanilan,
                      'kaybedilen': row.kaybedilen, 'tumu': row.tumu}

        query = apply_tab(base_query, tab)
        if search:
            query = query.filter(db.or_(
                Deal.title.ilike(f'%{search}%'),
                Customer.first_name.ilike(f'%{search}%'),
                Customer.last_name.ilike(f'%{search}%'),
                Customer.company_name.ilike(f'%{search}%')
            )).join(Customer)
        if stage_filter:
            query = query.filter(Deal.stage == stage_filter)
        # Is 2: sablon her satirda deal.seller (olusturan kullanici)
        # gosteriyor - joinedload olmadan N+1'e mal olurdu.
        query = query.options(joinedload(Deal.customer), joinedload(Deal.seller))
        pagination = query.order_by(Deal.created_at.desc()).paginate(page=page, per_page=50, error_out=False)
        deals = pagination.items

        # Is 6: Teklifler paneli - suresi dolan uyarisi + bu ay kazanilan toplami.
        today = datetime.now().date()
        month_start = today.replace(day=1)
        expired_deals_count = _apply_deal_visibility(db.session.query(db.func.count(Deal.id)).select_from(Deal)).filter(
            Deal.valid_until < today, ~Deal.stage.in_(RESOLVED_STAGES)
        ).scalar()
        this_month_won_total = _apply_deal_visibility(db.session.query(db.func.sum(Deal.value)).select_from(Deal)).filter(
            Deal.stage == 'kazanilan', Deal.created_at >= month_start
        ).scalar() or 0
        # Is 2 (sag panel): "suresi dolacak" - Dashboard'daki expiring_deals
        # ile AYNI pencere (2 gun).
        expiring_soon_count = _apply_deal_visibility(db.session.query(db.func.count(Deal.id)).select_from(Deal)).filter(
            Deal.valid_until <= today + timedelta(days=2), Deal.valid_until >= today,
            ~Deal.stage.in_(RESOLVED_STAGES)
        ).scalar()

        return render_template('deals.html', deals=deals, search=search, stage_filter=stage_filter,
                                tab=tab, tab_counts=tab_counts, pagination=pagination,
                                admin_deals_own_only=_admin_deals_own_only(),
                                expired_deals_count=expired_deals_count,
                                expiring_soon_count=expiring_soon_count,
                                this_month_won_total=this_month_won_total)

    @app.route('/deals/view-toggle', methods=['POST'])
    @login_required
    def deals_view_toggle():
        """Is 3: SADECE admin icin - 'Tum Teklifler' / 'Sadece Benim
        Tekliflerim' gecis anahtari, oturum (session) boyunca hatirlanir.
        Normal kullanici bu route'a POST atarsa (ornegin dogrudan URL ile)
        hicbir etkisi olmaz - _deal_visibility_user_id() zaten admin
        olmayanlar icin bu session degerini hic okumuyor, ama yine de
        yaniltici olmasin diye admin degilse sessizce yok sayilir."""
        if current_user.is_admin:
            session['admin_deals_own_only'] = request.form.get('mode') == 'own'
        return redirect(url_for('deals', tab=request.form.get('tab', 'aktif'), page=request.form.get('page', 1)))

    @app.route('/deals/add', methods=['GET', 'POST'])
    @login_required
    def add_deal():
        if request.method == 'POST':
            today = datetime.now().date()
            # Otomatik sıralı teklif numarası
            next_no = _next_deal_no()

            customer = Customer.query.get_or_404(int(request.form['customer_id']))
            _apply_customer_updates_from_form(customer, request.form)
            # Is 3: teklif basligi artik her zaman musterinin tam (temizlenmis)
            # adi - eski kisaltma+tarih+sirano mantigi (orn. "MEHMET-01.07-1")
            # tamamen kaldirildi.
            title = _customer_full_name(customer)

            # Cift-tiklama korumasi: ayni musteri icin birkac saniye once
            # zaten bir teklif olusmussa (gercek testte "Teklif Oluştur"
            # butonuna hizli cift tiklamanin mukerrer teklif actigi
            # dogrulandi) yeni kayit acmak yerine mevcut olana yonlendir.
            recent_cutoff = datetime.utcnow() - timedelta(seconds=30)
            recent_duplicate = Deal.query.filter(
                Deal.customer_id == customer.id, Deal.created_at >= recent_cutoff
            ).first()
            if recent_duplicate:
                flash(f'{recent_duplicate.display_no} az önce zaten oluşturuldu.', 'info')
                return redirect(url_for('deal_detail', id=recent_duplicate.id))

            para_birimi = request.form.get('para_birimi', 'TRY').strip().upper()
            if para_birimi not in ('TRY', 'EUR', 'USD'):
                para_birimi = 'TRY'
            kullanilan_kur_raw = request.form.get('kullanilan_kur', '').strip()
            kullanilan_kur = float(kullanilan_kur_raw) if kullanilan_kur_raw and para_birimi != 'TRY' else None

            try:
                deal = Deal(
                    deal_no=next_no,
                    title=title,
                    stage=request.form.get('stage', 'yeni'),
                    probability=int(request.form.get('probability', 0)),
                    deal_date=today,
                    expected_close=datetime.strptime(request.form['expected_close'], '%Y-%m-%d').date() if request.form.get('expected_close') else None,
                    valid_until=today + timedelta(days=7),
                    vat_rate=float(request.form.get('vat_rate', 20)),
                    notes=request.form.get('notes'),
                    vade_gun=request.form.get('vade_gun', '').strip() or None,
                    pesinat=request.form.get('pesinat', '').strip() or None,
                    bakiye_odemesi=request.form.get('bakiye_odemesi', '').strip() or None,
                    para_birimi=para_birimi,
                    kullanilan_kur=kullanilan_kur,
                    customer_id=customer.id,
                    user_id=current_user.id
                )
                db.session.add(deal)
                db.session.flush()

                i = 0
                new_items = []
                numune_errors = []
                while f'desc_{i}' in request.form:
                    qty = float(request.form[f'qty_{i}'])
                    price = float(request.form[f'price_{i}'])
                    teslim_tarihi_raw = request.form.get(f'teslim_tarihi_{i}', '').strip()
                    # Is 3: kalem bazli numune gorseli - opsiyonel, gecersiz/
                    # cok buyuk dosya yuklenirse teklifin tamamini iptal
                    # etmez, sadece o kalem icin gorsel bos kalir.
                    numune_path, numune_error = _save_uploaded_image(
                        request.files.get(f'numune_gorseli_{i}'), 'numune'
                    )
                    if numune_error:
                        numune_errors.append(f'{i + 1}. kalem: {numune_error}')
                    item = DealItem(
                        description=request.form[f'desc_{i}'],
                        quantity=qty,
                        unit=request.form.get(f'unit_{i}', 'adet'),
                        unit_price=price,
                        total_price=qty * price,
                        urun_tipi=request.form.get(f'urun_tipi_{i}', 'uretim'),
                        kagit_cinsi=request.form.get(f'kagit_cinsi_{i}', '').strip() or None,
                        boy=request.form.get(f'boy_{i}', '').strip() or None,
                        en=request.form.get(f'en_{i}', '').strip() or None,
                        korugu=request.form.get(f'korugu_{i}', '').strip() or None,
                        renk=request.form.get(f'renk_{i}', '').strip() or None,
                        teslim_tarihi=datetime.strptime(teslim_tarihi_raw, '%Y-%m-%d').date() if teslim_tarihi_raw else None,
                        numune_gorseli=numune_path,
                        deal_id=deal.id
                    )
                    db.session.add(item)
                    new_items.append(item)
                    i += 1

                db.session.flush()
                # new_items burada explicit veriliyor - deal.items (henuz
                # yuklenmemis bir iliski) okumak, Neon'a gereksiz bir
                # SELECT round-trip'i (~300-450ms) daha acardi.
                deal.calculate_totals(items=new_items)

                reminder = Reminder(
                    customer_id=deal.customer_id,
                    deal_id=deal.id,
                    title=f'Teklif Süresi Doluyor: {deal.title}',
                    message=f'{deal.display_no} teklifinin geçerlilik süresi {deal.valid_until.strftime("%d.%m.%Y")} tarihinde doluyor.',
                    remind_date=deal.valid_until - timedelta(days=1)
                )
                db.session.add(reminder)
                db.session.commit()
            except Exception:
                db.session.rollback()
                flash('Teklif oluşturulurken bir hata oluştu, hiçbir değişiklik kaydedilmedi. Girdiğiniz bilgileri kontrol edip tekrar deneyin.', 'danger')
                return redirect(url_for('add_deal'))

            flash(f'Teklif oluşturuldu! KDV dahil: {deal.value:,.2f} {deal.para_birimi_sembol}', 'success')
            if numune_errors:
                flash('Bazı numune görselleri kaydedilemedi: ' + '; '.join(numune_errors), 'warning')
            return redirect(url_for('deal_detail', id=deal.id))
        # Not: customers listesi burada kasitli olarak cekilmiyor - form
        # merkezi musteri arama bilesenini (customer-search.js) kullaniyor,
        # 1690+ satirlik bir <select> hic render edilmiyor (performans).
        return render_template('add_deal.html', today=datetime.now().date(),
                             expire_date=datetime.now().date() + timedelta(days=7))

    @app.route('/deals/<int:id>')
    @login_required
    def deal_detail(id):
        deal = Deal.query.get_or_404(id)
        if not current_user.is_admin and deal.user_id != current_user.id:
            flash('Bu teklifi görüntüleme yetkiniz yok.', 'danger')
            return redirect(url_for('deals'))
        return render_template('deal_detail.html', deal=deal)

    @app.route('/deals/<int:id>/edit', methods=['GET', 'POST'])
    @login_required
    def edit_deal(id):
        deal = Deal.query.get_or_404(id)
        if not current_user.is_admin and deal.user_id != current_user.id:
            flash('Bu teklifi düzenleme yetkiniz yok.', 'danger')
            return redirect(url_for('deals'))
        if deal.stage == 'kazanilan':
            flash('Bu teklif onaylanmış ve üretime aktarılmış, kalemleri artık düzenlenemez.', 'danger')
            return redirect(url_for('deal_detail', id=id))
        if request.method == 'POST':
            # Is 3: title artik musteri adindan otomatik geldigi icin
            # duzenleme formundan degistirilmiyor.
            deal.stage = request.form['stage']
            deal.probability = int(request.form.get('probability', 0))
            deal.vat_rate = float(request.form.get('vat_rate', 20))
            deal.expected_close = datetime.strptime(request.form['expected_close'], '%Y-%m-%d').date() if request.form.get('expected_close') else None
            deal.valid_until = datetime.strptime(request.form['valid_until'], '%Y-%m-%d').date() if request.form.get('valid_until') else None
            deal.notes = request.form.get('notes')
            deal.vade_gun = request.form.get('vade_gun', '').strip() or None
            deal.pesinat = request.form.get('pesinat', '').strip() or None
            deal.bakiye_odemesi = request.form.get('bakiye_odemesi', '').strip() or None

            para_birimi = request.form.get('para_birimi', 'TRY').strip().upper()
            if para_birimi not in ('TRY', 'EUR', 'USD'):
                para_birimi = 'TRY'
            kullanilan_kur_raw = request.form.get('kullanilan_kur', '').strip()
            deal.para_birimi = para_birimi
            deal.kullanilan_kur = float(kullanilan_kur_raw) if kullanilan_kur_raw and para_birimi != 'TRY' else None

            DealItem.query.filter_by(deal_id=id).delete()
            i = 0
            new_items = []
            numune_errors = []
            while f'desc_{i}' in request.form:
                qty = float(request.form[f'qty_{i}'])
                price = float(request.form[f'price_{i}'])
                teslim_tarihi_raw = request.form.get(f'teslim_tarihi_{i}', '').strip()
                # Is 3: yeni dosya yuklendiyse onu kullan; yuklenmediyse
                # (kalem duzenlemede daha once yuklenmis olabilir) mevcut
                # yolu (existing_numune_gorseli_i hidden alani) koru - kalemler
                # her duzenlemede silinip yeniden olusturuldugu icin bu
                # alan olmadan mevcut gorsel sessizce kaybolurdu.
                numune_path, numune_error = _save_uploaded_image(
                    request.files.get(f'numune_gorseli_{i}'), 'numune'
                )
                if numune_error:
                    numune_errors.append(f'{i + 1}. kalem: {numune_error}')
                elif not numune_path:
                    numune_path = request.form.get(f'existing_numune_gorseli_{i}', '').strip() or None
                item = DealItem(description=request.form[f'desc_{i}'], quantity=qty, unit=request.form.get(f'unit_{i}', 'adet'),
                               unit_price=price, total_price=qty * price,
                               urun_tipi=request.form.get(f'urun_tipi_{i}', 'uretim'),
                               kagit_cinsi=request.form.get(f'kagit_cinsi_{i}', '').strip() or None,
                               boy=request.form.get(f'boy_{i}', '').strip() or None,
                               en=request.form.get(f'en_{i}', '').strip() or None,
                               korugu=request.form.get(f'korugu_{i}', '').strip() or None,
                               renk=request.form.get(f'renk_{i}', '').strip() or None,
                               teslim_tarihi=datetime.strptime(teslim_tarihi_raw, '%Y-%m-%d').date() if teslim_tarihi_raw else None,
                               numune_gorseli=numune_path,
                               deal_id=deal.id)
                db.session.add(item)
                new_items.append(item)
                i += 1

            db.session.flush()
            # new_items explicit veriliyor - performans denetimi (bkz. add_deal,
            # commit 153bc85): self.items okumak gereksiz bir SELECT daha acardi.
            deal.calculate_totals(items=new_items)
            db.session.commit()
            flash('Teklif güncellendi!', 'success')
            if numune_errors:
                flash('Bazı numune görselleri kaydedilemedi: ' + '; '.join(numune_errors), 'warning')
            return redirect(url_for('deal_detail', id=id))
        return render_template('edit_deal.html', deal=deal)

    @app.route('/deals/<int:id>/delete', methods=['POST'])
    @login_required
    def delete_deal(id):
        deal = Deal.query.get_or_404(id)
        if not current_user.is_admin and deal.user_id != current_user.id:
            flash('Bu teklifi silme yetkiniz yok.', 'danger')
            return redirect(url_for('deals'))

        blockers = []
        if deal.production:
            blockers.append('üretim')
        if Commission.query.filter_by(deal_id=id).first():
            blockers.append('prim')
        if deal.invoices:
            blockers.append('fatura')
        if deal.statements:
            blockers.append('cari ekstre')

        if blockers:
            flash(
                'Bu teklife bağlı ' + ', '.join(blockers) + ' kaydı var, '
                'önce onları silin veya bu teklifi silemezsiniz.', 'danger'
            )
            return redirect(url_for('deal_detail', id=id))

        Reminder.query.filter_by(deal_id=id).delete()
        Task.query.filter_by(deal_id=id).delete()
        db.session.delete(deal)
        db.session.commit()
        flash('Teklif silindi!', 'success')
        return redirect(url_for('deals'))

    @app.route('/deals/<int:id>/pdf')
    @login_required
    def deal_pdf(id):
        deal = Deal.query.get_or_404(id)
        if not current_user.is_admin and deal.user_id != current_user.id:
            flash('Bu teklifin PDF\'ini görüntüleme yetkiniz yok.', 'danger')
            return redirect(url_for('deals'))
        pdf = generate_deal_pdf(deal)
        
        # Teklifler klasörünü oluştur (yoksa)
        teklifler_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'Teklifler')
        os.makedirs(teklifler_dir, exist_ok=True)
        
        # Dosya adını teklif başlığından oluştur (Türkçe karakterleri temizle)
        safe_title = deal.title.replace(' ', '_').replace('ı', 'i').replace('ğ', 'g').replace('ü', 'u').replace('ş', 's').replace('ö', 'o').replace('ç', 'c')
        filename = f'teklif_{safe_title}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
        filepath = os.path.join(teklifler_dir, filename)
        
        # PDF'i dosyaya kaydet
        with open(filepath, 'wb') as f:
            f.write(pdf.read())
        pdf.seek(0)
        
        # Dosyayı kullanıcıya gönder (indir)
        return send_file(filepath, as_attachment=True, download_name=filename)

    @app.route('/deals/<int:id>/revise', methods=['POST'])
    @login_required
    def revise_deal(id):
        deal = Deal.query.get_or_404(id)
        if not current_user.is_admin and deal.user_id != current_user.id:
            flash('Bu teklifi revize etme yetkiniz yok.', 'danger')
            return redirect(url_for('deals'))

        # delete_deal'daki ayni kontrol: bagli Production/Commission/Invoice/
        # CustomerStatement varken teklif revize edilirse, bu kayitlar eski
        # (artik stage='revize' olan, "kazanilan" filtresine girmeyen)
        # deal_id'ye sessizce bagli kalirdi - prim/rapor sorgularinda
        # gorunmez hale gelirlerdi. Bu durumda revizyon engellenir.
        blockers = []
        if deal.production:
            blockers.append('üretim')
        if Commission.query.filter_by(deal_id=id).first():
            blockers.append('prim')
        if deal.invoices:
            blockers.append('fatura')
        if deal.statements:
            blockers.append('cari ekstre')
        if blockers:
            flash(
                'Bu teklife bağlı ' + ', '.join(blockers) + ' kaydı var, '
                'bu yüzden revize edilemez (bağlı kayıtlar eski tekliften kopar). '
                'Gerekirse önce bu kayıtları inceleyin.', 'danger'
            )
            return redirect(url_for('deal_detail', id=id))

        today = datetime.now().date()
        # Is 3: revize teklif ayni (temizlenmis) musteri adiyla devam eder,
        # eski karisik "(Revize N)" suffix mantigi kaldirildi - tekilligi
        # artik deal_no sagliyor.
        new_deal = Deal(
            deal_no=_next_deal_no(),
            title=deal.title, stage='teklif', probability=deal.probability,
            deal_date=today, expected_close=deal.expected_close, valid_until=today + timedelta(days=7),
            vat_rate=deal.vat_rate, notes=f"Revize. Orijinal: {deal.display_no}. {deal.notes or ''}".strip(),
            para_birimi=deal.para_birimi, kullanilan_kur=deal.kullanilan_kur,
            customer_id=deal.customer_id,
            user_id=deal.user_id
        )
        db.session.add(new_deal)
        db.session.flush()
        for item in deal.items:
            db.session.add(DealItem(description=item.description, quantity=item.quantity, unit=item.unit,
                                   unit_price=item.unit_price, total_price=item.total_price,
                                   urun_tipi=item.urun_tipi,
                                   kagit_cinsi=item.kagit_cinsi, boy=item.boy, en=item.en, renk=item.renk,
                                   teslim_tarihi=item.teslim_tarihi, deal_id=new_deal.id))
        db.session.flush()
        new_deal.calculate_totals()
        deal.stage = 'revize'
        db.session.commit()
        flash(f'Revize teklif oluşturuldu! KDV dahil: {new_deal.value:,.2f} ₺', 'success')
        return redirect(url_for('deal_detail', id=new_deal.id))

    @app.route('/deals/<int:id>/approve', methods=['GET', 'POST'])
    @login_required
    def approve_deal(id):
        deal = Deal.query.get_or_404(id)
        if not current_user.is_admin and deal.user_id != current_user.id:
            flash('Bu teklifi onaylama yetkiniz yok.', 'danger')
            return redirect(url_for('deals'))

        if request.method == 'POST':
            # Is D: odeme takvimi zorunlu - pesinat orani, pesinat tarihi ve
            # bakiye tarihi girilmeden teklif uretime aktarilamaz.
            pesinat_orani_raw = request.form.get('pesinat_orani', '').strip()
            pesinat_tarihi_raw = request.form.get('pesinat_tarihi', '').strip()
            bakiye_tarihi_raw = request.form.get('bakiye_tarihi', '').strip()

            form_errors = []
            pesinat_orani = None
            if not pesinat_orani_raw:
                form_errors.append('Peşinat oranı girilmelidir.')
            else:
                try:
                    pesinat_orani = float(pesinat_orani_raw)
                    if not (0 <= pesinat_orani <= 100):
                        form_errors.append('Peşinat oranı 0-100 arasında olmalıdır.')
                except ValueError:
                    form_errors.append('Peşinat oranı geçerli bir sayı olmalıdır.')
            if not pesinat_tarihi_raw:
                form_errors.append('Peşinat ödeme tarihi girilmelidir.')
            if not bakiye_tarihi_raw:
                form_errors.append('Bakiye ödeme tarihi girilmelidir.')

            if form_errors:
                for err in form_errors:
                    flash(err, 'danger')
                prev_sales = Deal.query.filter(Deal.customer_id == deal.customer_id, Deal.stage == 'kazanilan', Deal.id != deal.id).count()
                suggested_rate = 1.5 if prev_sales == 0 else 1.0
                return render_template('approve_deal.html', deal=deal, suggested_rate=suggested_rate,
                                        form_data=request.form)

            try:
                deal.pesinat_orani = pesinat_orani
                deal.pesinat_tarihi = datetime.strptime(pesinat_tarihi_raw, '%Y-%m-%d').date()
                deal.bakiye_tarihi = datetime.strptime(bakiye_tarihi_raw, '%Y-%m-%d').date()

                deal.stage = 'kazanilan'
                deal.user_id = current_user.id

                production = Production(deal_id=deal.id, status='uretimde', start_date=datetime.now().date(),
                                         due_date=deal.expected_close)
                db.session.add(production)
                db.session.flush()

                # Teklif kalemlerinden ProductionItem'ları oluştur. Teklifte zaten
                # girilmis kagit_cinsi/boy/en/renk varsa is emrine on-doldurma
                # olarak kopyalanir (atolyenin ayni bilgiyi elden tekrar girmesi
                # gerekmesin diye) - yine de is emri sayfasindan duzenlenebilir.
                for item in deal.items:
                    olcu = None
                    if item.boy and item.en:
                        olcu = f'{item.boy}x{item.en}'
                    elif item.boy or item.en:
                        olcu = item.boy or item.en
                    prod_item = ProductionItem(
                        production_id=production.id,
                        deal_item_id=item.id,
                        description=item.description,
                        planned_quantity=item.quantity,
                        produced_quantity=0,
                        unit=item.unit,
                        status='bekleniyor',
                        urun_tipi=item.urun_tipi,
                        ticaret_durumu='siparis_edildi' if item.urun_tipi == 'ticaret' else None,
                        kagit_tipi=item.kagit_cinsi,
                        olcu=olcu,
                        baski_bilgisi=item.renk
                    )
                    db.session.add(prod_item)

                statement = CustomerStatement(customer_id=deal.customer_id, deal_id=deal.id, type='borc', amount=deal.value,
                                             description=f'Satış: {deal.title} (KDV Dahil: {deal.value:,.2f} ₺)')
                db.session.add(statement)

                # Manuel prim oranını al
                manual_rate = request.form.get('commission_rate')
                if manual_rate:
                    rate = float(manual_rate)
                    customer_type = 'manuel'
                else:
                    prev_sales = Deal.query.filter(Deal.customer_id == deal.customer_id, Deal.stage == 'kazanilan', Deal.id != deal.id).count()
                    is_new = prev_sales == 0
                    rate = 1.5 if is_new else 1.0
                    customer_type = 'yeni' if is_new else 'eski'

                commission_amount = deal.subtotal * (rate / 100)

                commission = Commission(
                    user_id=current_user.id,
                    deal_id=deal.id,
                    sale_amount=deal.subtotal,
                    rate=rate,
                    amount=commission_amount,
                    customer_type=customer_type,
                    status='odenmedi',
                    manual_rate=rate if manual_rate else None
                )
                db.session.add(commission)
                db.session.commit()
            except Exception:
                db.session.rollback()
                flash('Teklif onaylanırken bir hata oluştu, hiçbir değişiklik kaydedilmedi. Girdiğiniz bilgileri kontrol edip tekrar deneyin.', 'danger')
                return redirect(url_for('approve_deal', id=id))

            flash(f'Teklif onaylandı! Üretime aktarıldı. Prim: %{rate} = {commission_amount:,.2f} ₺', 'success')
            return redirect(url_for('production_detail', id=production.id))
        
        # GET isteği - onay formu göster
        prev_sales = Deal.query.filter(Deal.customer_id == deal.customer_id, Deal.stage == 'kazanilan', Deal.id != deal.id).count()
        is_new = prev_sales == 0
        suggested_rate = 1.5 if is_new else 1.0
        
        return render_template('approve_deal.html', deal=deal, suggested_rate=suggested_rate)

    @app.route('/api/customers/<int:customer_id>/uretim-oneri')
    @login_required
    def customer_uretim_oneri(customer_id):
        """Is 8 madde 1: musterinin AKTIF (henuz teslim edilmemis) Production
        kayitlarina bagli Gunluk Uretim (DailyProductionOutput) kayitlarinin
        TOPLAM kg'sini doner - Fatura olusturma formunda kalemin miktar
        alanina otomatik ONERI olarak doldurulur (elle degistirilebilir).
        Hic veri yoksa total=0 doner, JS bu durumda hicbir alani doldurmaz."""
        customer = Customer.query.get_or_404(customer_id)
        active_production_ids = [
            p.id for p in Production.query.join(Deal).filter(Deal.customer_id == customer.id).all()
            if not p.is_delivered
        ]
        if not active_production_ids:
            return jsonify({'total_kg': 0})
        total_kg = db.session.query(db.func.sum(DailyProductionOutput.toplam_kg)).filter(
            DailyProductionOutput.production_id.in_(active_production_ids)
        ).scalar() or 0
        return jsonify({'total_kg': total_kg})

    @app.route('/api/customers/search')
    @login_required
    def search_customers():
        """Site genelinde TEK musteri arama endpoint'i (Is 1). Turkce karakter
        normalizasyonu (_normalize_tr) kullanir, isim/telefon/firma icinde
        arar, sayisal sorguda dogrudan ID ile de eslesir."""
        query = request.args.get('q', '').strip()
        if len(query) < 2:
            return jsonify([])

        if query.isdigit():
            by_id = Customer.query.get(int(query))
            if by_id:
                return jsonify([{
                    'id': by_id.id, 'name': by_id.display_name,
                    'phone': by_id.phone or '', 'email': by_id.email or '',
                    'company_name': by_id.company_name or '',
                    'tax_id': by_id.tax_id or '',
                    'address': by_id.company_address or by_id.address or ''
                }])

        norm_q = _normalize_tr(query)
        rows = Customer.query.with_entities(
            Customer.id, Customer.first_name, Customer.last_name,
            Customer.company_name, Customer.phone, Customer.email,
            Customer.tax_id, Customer.address, Customer.company_address
        ).all()

        starts_with, contains = [], []
        for r in rows:
            haystack = _normalize_tr(' '.join(filter(None, [r.first_name, r.last_name, r.company_name, r.phone])))
            if norm_q not in haystack:
                continue
            (starts_with if haystack.startswith(norm_q) else contains).append(r)

        result = []
        for r in (starts_with + contains)[:20]:
            name = ' '.join(filter(None, [r.first_name, r.last_name]))
            name = f"{r.company_name} - {name}" if r.company_name and name else (r.company_name or name or 'İsimsiz Müşteri')
            result.append({
                'id': r.id,
                'name': name,
                'phone': r.phone or '',
                'email': r.email or '',
                'company_name': r.company_name or '',
                'tax_id': r.tax_id or '',
                'address': r.company_address or r.address or ''
            })
        return jsonify(result)

    @app.route('/api/csrf-token')
    @login_required
    def api_csrf_token():
        """Uzun sure acik kalan sayfalardaki (orn. Dashboard'daki 'Bugun
        Kiminle Gorustun?' kutusu) AJAX formlari icin taze bir CSRF token
        dondurur. WTF_CSRF_TIME_LIMIT varsayilan 1 saat - sayfa yuklendiginde
        gomulen token bu sureden sonra gecersiz kalip POST'lari sessizce
        (HTML hata sayfasi donerek) reddediyordu; submit aninda bu endpoint'ten
        taze token cekmek bu sorunu ortadan kaldirir."""
        return jsonify({'csrf_token': generate_csrf()})

    @app.route('/api/tcmb-rate')
    @login_required
    def api_tcmb_rate():
        """Coklu Para Birimi - teklif formunda para birimi EUR/USD secilince
        veya odeme formunda dovizli bir teklif/fatura secilince, o gunun
        TCMB efektif satis kurunu doner. Kullanici bu degeri elle de
        degistirebilir - burasi sadece otomatik on-doldurma icindir."""
        currency = request.args.get('currency', 'EUR').upper()
        if currency not in ('TRY', 'EUR', 'USD'):
            return jsonify({'error': 'Desteklenmeyen para birimi.'}), 400
        rate = fetch_tcmb_rate(currency)
        if rate is None:
            return jsonify({'error': 'TCMB kuru şu an alınamadı, elle girebilirsiniz.'}), 502
        return jsonify({'currency': currency, 'rate': rate})

    @app.route('/api/customers/quick-add', methods=['POST'])
    @login_required
    def quick_add_customer():
        """Musteri aramasi sonuc bulamadiginda (Is 3), ayri sayfaya gitmeden
        isim VE/VEYA telefon ile minimal bir musteri kaydi olusturur. Diger
        alanlar bos birakilir, sonra edit_customer'dan tamamlanabilir.
        Ayni telefona ya da ayni ad-soyad'a (unique_customer_name kisiti)
        sahip bir musteri zaten varsa, yeni kayit acmak yerine mevcut
        musteriyi dondurur - boylece kaza ile duplikasyon olusmaz."""
        data = request.get_json(silent=True) or request.form
        name = (data.get('name') or '').strip()
        phone = (data.get('phone') or '').strip()

        if not name and not phone:
            return jsonify({'error': 'İsim veya telefon numarasından en az biri gerekli.'}), 400

        if phone:
            existing = Customer.query.filter_by(phone=phone).first()
            if existing:
                return jsonify({
                    'id': existing.id, 'name': existing.display_name, 'phone': existing.phone or '',
                    'email': existing.email or '', 'company_name': existing.company_name or '',
                    'tax_id': existing.tax_id or '', 'address': existing.company_address or existing.address or '',
                    'reused_existing': True,
                }), 200

        first_name, last_name = None, None
        if name:
            parts = name.split(None, 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else None

        customer = Customer(musteri_no=_next_musteri_no(), first_name=first_name, last_name=last_name, phone=phone or None, status='aktif', owner_user_id=current_user.id)
        db.session.add(customer)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            existing = Customer.query.filter_by(first_name=first_name, last_name=last_name).first()
            if existing:
                return jsonify({
                    'id': existing.id, 'name': existing.display_name, 'phone': existing.phone or '',
                    'email': existing.email or '', 'company_name': existing.company_name or '',
                    'tax_id': existing.tax_id or '', 'address': existing.company_address or existing.address or '',
                    'reused_existing': True,
                }), 200
            return jsonify({'error': 'Bu isimde bir müşteri zaten var. Lütfen arayarak seçin veya telefon numarası ekleyin.'}), 409

        return jsonify({
            'id': customer.id, 'name': customer.display_name, 'phone': customer.phone or '',
            'email': '', 'company_name': '', 'tax_id': '', 'address': '',
            'reused_existing': False,
        }), 201

    @app.route('/api/daily-reports/quick-add', methods=['POST'])
    @login_required
    def quick_add_daily_report():
        """Dashboard'daki 'Bugun Kiminle Gorustun?' kutusu icin - secilen
        (veya /api/customers/quick-add ile az once olusturulan) musteri
        icin bugunun tarihiyle tek satirlik bir Gunluk Rapor kaydi acar.
        Bu kayit, TAKIP_GEREKEN_GUN dongusunde o musterinin son irtibat
        tarihini otomatik sifirlar (bkz. _last_contact_subquery)."""
        data = request.get_json(silent=True) or {}
        customer_id = data.get('customer_id')
        notes = (data.get('notes') or '').strip()

        if not customer_id:
            return jsonify({'error': 'Müşteri seçilmelidir.'}), 400
        customer = Customer.query.get(customer_id)
        if not customer:
            return jsonify({'error': 'Müşteri bulunamadı.'}), 404

        report = DailyReport(
            report_date=date.today(),
            customer_name=customer.display_name,
            phone=customer.phone,
            notes=notes,
            status='tamamlandi',
            user_id=current_user.id,
            customer_id=customer.id,
        )
        db.session.add(report)
        db.session.commit()

        return jsonify({'success': True, 'id': report.id, 'customer_name': customer.display_name}), 201

    @app.route('/deals/export/excel')
    @login_required
    def deals_export_excel():
        # Is 1: eskiden TUM tekliflerin (baskalarininkiler dahil) disa
        # aktarilmasina izin veriyordu - liste sayfasindaki gorunurluk
        # kuraliyla tutarsizdi. Artik ayni gorunurluk kaynagini kullanir.
        deals = _apply_deal_visibility(Deal.query).all()
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Teklifler'
        headers = ['Teklif No', 'Başlık', 'Müşteri', 'Ara Toplam', 'KDV Oranı', 'KDV', 'Toplam', 'Durum', 'Tarih']
        ws.append(headers)
        for d in deals:
            ws.append([d.display_no, d.title, d.customer.display_name, d.subtotal, f'%{d.vat_rate}', 
                       d.vat_amount, d.value, d.stage, d.deal_date.strftime('%d.%m.%Y') if d.deal_date else ''])
        buffer = BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return send_file(buffer, as_attachment=True, download_name=f'teklifler_{datetime.now().strftime("%Y%m%d")}.xlsx')

    def _latest_shipment_status_subq():
        """Her production_id icin EN SON Shipment'in status'unu dondurur -
        Uretim Listesi'ndeki 'Sevkiyatta' (henuz teslim edilmemis) ile
        'Tamamlandi' (teslim edilmis) sekmelerini ayirt etmek icin (Is 3)."""
        latest_at = db.session.query(
            Shipment.production_id,
            db.func.max(Shipment.created_at).label('latest_at')
        ).group_by(Shipment.production_id).subquery()
        return db.session.query(
            Shipment.production_id,
            Shipment.status.label('latest_status')
        ).join(
            latest_at,
            db.and_(
                Shipment.production_id == latest_at.c.production_id,
                Shipment.created_at == latest_at.c.latest_at
            )
        ).subquery()

    def _apply_production_tab(query, tab, latest_status_subq, joined=False):
        """query uzerinde verilen sekme filtresini uygular. joined=True ise
        query zaten latest_status_subq'ya outerjoin edilmis demektir (liste
        sorgusunda oldugu gibi - tek join, tab_counts'ta ise her sekme kendi
        bagimsiz alt sorgusunda ayri join kurar)."""
        if not joined and tab in ('sevkiyatta', 'tamamlandi'):
            query = query.outerjoin(latest_status_subq, Production.id == latest_status_subq.c.production_id)
        if tab == 'uretimde':
            return query.filter(Production.status == 'uretimde')
        if tab == 'hazir':
            return query.filter(Production.status == 'hazir')
        if tab == 'sevkiyatta':
            return query.filter(
                Production.status == 'sevkiyat',
                db.or_(
                    latest_status_subq.c.latest_status.is_(None),
                    latest_status_subq.c.latest_status != 'teslim_edildi'
                )
            )
        if tab == 'tamamlandi':
            return query.filter(
                Production.status == 'sevkiyat',
                latest_status_subq.c.latest_status == 'teslim_edildi'
            )
        return query  # 'tumu'

    def _production_tab_counts():
        """5 sekmenin sayacini TEK round-trip'te (scalar_subquery) hesaplar -
        Neon'a ayri ayri 5 COUNT sorgusu atmak yerine (bkz. dashboard'daki
        ayni performans deseni, commit 153bc85)."""
        latest_status_subq = _latest_shipment_status_subq()

        def count_subq(tab):
            q = _apply_production_tab(
                db.session.query(db.func.count(Production.id)).select_from(Production),
                tab, latest_status_subq
            )
            return q.scalar_subquery()

        row = db.session.query(
            count_subq('uretimde').label('uretimde'),
            count_subq('hazir').label('hazir'),
            count_subq('sevkiyatta').label('sevkiyatta'),
            count_subq('tamamlandi').label('tamamlandi'),
            count_subq('tumu').label('tumu'),
        ).one()
        return {'uretimde': row.uretimde, 'hazir': row.hazir, 'sevkiyatta': row.sevkiyatta,
                'tamamlandi': row.tamamlandi, 'tumu': row.tumu}

    def _filtered_productions(tab):
        """Uretim Listesi + Excel/PDF disa aktarma routelarinin UCU: ayni
        sekme filtresini paylasirlar, boylece ekranda gorunen ile
        aktarilan HER ZAMAN birebir ayni satirlari icerir (Is 2)."""
        latest_status_subq = _latest_shipment_status_subq()
        # Performans: production.items (specs_missing/uretim_items/gecen_gun
        # gibi sablon icinde HER satirda okunan property'ler icin) burada
        # joinedload edilmezse her satir kendi ayri SELECT'ini tetikliyordu
        # (N+1 - 25 satirlik bir listede +25 round-trip'e mal oluyordu).
        query = Production.query.options(
            joinedload(Production.deal).joinedload(Deal.customer),
            joinedload(Production.items),
        )
        if tab in ('sevkiyatta', 'tamamlandi'):
            query = query.outerjoin(latest_status_subq, Production.id == latest_status_subq.c.production_id)
            joined = True
        else:
            joined = False
        query = _apply_production_tab(query, tab, latest_status_subq, joined=joined)
        return query.order_by(Production.created_at.desc()).all()

    def _production_report_data():
        """Is 2 (sag panel): 'Uretim Raporu' kartinin verisi - Dashboard
        VE Uretim Listesi sayfalarinda AYNI kart/partial (_uretim_rapor_card.html)
        ile gosterilir, mantik burada TEK yerde (modul cakismasi olmasin diye)."""
        tab_counts = _production_tab_counts()
        today = datetime.now().date()
        overdue_count = Production.query.filter(
            Production.due_date < today, Production.status.in_(['uretimde', 'hazir'])
        ).count()
        today_output_total_kg = db.session.query(db.func.sum(DailyProductionOutput.toplam_kg)).filter(
            DailyProductionOutput.tarih == today
        ).scalar() or 0
        return {'tab_counts': tab_counts, 'overdue_count': overdue_count, 'today_output_total_kg': today_output_total_kg}

    @app.route('/production')
    @login_required
    def production_list():
        tab = request.args.get('tab', 'uretimde')
        if tab not in ('uretimde', 'hazir', 'sevkiyatta', 'tamamlandi', 'tumu'):
            tab = 'uretimde'
        productions = _filtered_productions(tab)
        tab_counts = _production_tab_counts()
        production_report = _production_report_data()

        return render_template('production_list.html', productions=productions, tab=tab, tab_counts=tab_counts,
                                production_report=production_report)

    @app.route('/production/export/excel')
    @login_required
    def production_export_excel():
        tab = request.args.get('tab', 'uretimde')
        if tab not in ('uretimde', 'hazir', 'sevkiyatta', 'tamamlandi', 'tumu'):
            tab = 'uretimde'
        productions = _filtered_productions(tab)

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Üretim Listesi'
        headers = ['#', 'Fırsat', 'Müşteri', 'Durum', 'Başlangıç', 'Bitiş', 'Geçen Gün', 'İş Emri']
        ws.append(headers)
        for p in productions:
            ws.append([
                p.id,
                p.deal.title if p.deal else '',
                p.deal.customer.display_name if p.deal and p.deal.customer else '',
                p.stage_label,
                p.start_date.strftime('%d.%m.%Y') if p.start_date else '',
                p.end_date.strftime('%d.%m.%Y') if p.end_date else '',
                p.gecen_gun,
                'Eksik Bilgi' if p.specs_missing else 'Tam',
            ])
        for col_idx in range(1, len(headers) + 1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = 22

        buffer = BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return send_file(buffer, as_attachment=True,
                          download_name=f'uretim_listesi_{tab}_{datetime.now().strftime("%Y%m%d")}.xlsx')

    @app.route('/production/export/pdf')
    @login_required
    def production_export_pdf():
        tab = request.args.get('tab', 'uretimde')
        if tab not in ('uretimde', 'hazir', 'sevkiyatta', 'tamamlandi', 'tumu'):
            tab = 'uretimde'
        productions = _filtered_productions(tab)
        tab_label = {'uretimde': 'Üretimde', 'hazir': 'Hazır', 'sevkiyatta': 'Sevkiyatta',
                     'tamamlandi': 'Tamamlandı', 'tumu': 'Tümü'}.get(tab, tab)
        pdf = generate_production_list_pdf(productions, tab_label)
        return send_file(pdf, as_attachment=True, download_name=f'uretim_listesi_{tab}_{datetime.now().strftime("%Y%m%d")}.pdf')

    def _planning_group_key(item):
        """Gramaj bazli gruplama - gramaj yoksa daha once elle girilmis
        taban_olcusu'ne, o da yoksa ham olcu metnine dusulur (Is 2)."""
        return item.gramaj or item.taban_olcusu or item.olcu or None

    @app.route('/uretim-planlama')
    @login_required
    def uretim_planlama():
        """Su an 'Uretimde' durumundaki TUM is emri kalemlerini (ticaret haric)
        gramaj (yoksa olcu) degerine gore gruplar; ayni gruba, sistemde
        formal bir teklifi olmayan ManuelPlanningEntry kayitlari da eklenir.
        Her grubun toplam adedi ve baski ustasina yazdirilacak bos satirlar
        gosterilir (Is 2)."""
        items = ProductionItem.query.join(Production).options(
            joinedload(ProductionItem.production).joinedload(Production.deal).joinedload(Deal.customer)
        ).filter(
            Production.status == 'uretimde',
            ProductionItem.urun_tipi != 'ticaret'
        ).all()
        manual_entries = ManualPlanningEntry.query.options(joinedload(ManualPlanningEntry.customer)) \
            .order_by(ManualPlanningEntry.created_at.asc()).all()

        groups = {}
        for item in items:
            key = _planning_group_key(item) or 'Belirtilmemiş'
            row = {
                'kind': 'production',
                'customer_name': item.production.deal.customer.display_name,
                'deal_no': item.production.deal.display_no,
                'description': item.description,
                'quantity': item.planned_quantity,
                'unit': item.unit,
                'delivery_date': item.production.due_date,
                'production_id': item.production_id,
            }
            groups.setdefault(key, []).append(row)

        for entry in manual_entries:
            key = entry.group_key or 'Belirtilmemiş'
            row = {
                'kind': 'manual',
                'customer_name': entry.customer.display_name if entry.customer else entry.customer_name,
                'deal_no': None,
                'description': entry.urun,
                'quantity': entry.quantity,
                'unit': entry.unit,
                'delivery_date': entry.delivery_date,
                'manual_id': entry.id,
            }
            groups.setdefault(key, []).append(row)

        # Belirtilmemiş her zaman en sonda, digerleri alfabetik
        sorted_keys = sorted(k for k in groups if k != 'Belirtilmemiş')
        if 'Belirtilmemiş' in groups:
            sorted_keys.append('Belirtilmemiş')

        grouped = []
        for k in sorted_keys:
            rows = groups[k]
            # Bir grup icinde birim karisik olabilir (orn. bazi kalemler kg,
            # bazilari adet) - tek bir toplamda birlestirmek yaniltici olur,
            # bu yuzden birim basina ayri toplam hesaplanir.
            totals_by_unit = {}
            for r in rows:
                totals_by_unit[r['unit']] = totals_by_unit.get(r['unit'], 0) + r['quantity']
            totals_display = ', '.join(f"{qty:,.0f} {unit}" for unit, qty in totals_by_unit.items())
            grouped.append({'key': k, 'rows': rows, 'totals_display': totals_display})

        existing_group_keys = sorted(k for k in groups if k != 'Belirtilmemiş')

        return render_template('uretim_planlama.html', grouped=grouped,
                                today=datetime.now().date(), total_items=len(items) + len(manual_entries),
                                existing_group_keys=existing_group_keys)

    @app.route('/uretim-planlama/manuel-ekle', methods=['GET', 'POST'])
    @login_required
    def add_manual_planning_entry():
        """Is 2 - sistemde formal bir teklifi olmayan (orn. telefonla gelen)
        bir siparisi elle uretim planina ekler."""
        if request.method == 'POST':
            group_key = request.form.get('group_key', '').strip()
            customer_name = request.form.get('customer_name', '').strip()
            customer_id = request.form.get('customer_id') or None
            urun = request.form.get('urun', '').strip()
            quantity_raw = request.form.get('quantity', '').strip()
            unit = request.form.get('unit', 'adet').strip() or 'adet'
            delivery_date_raw = request.form.get('delivery_date', '').strip()

            errors = []
            if not group_key:
                errors.append('Gramaj/Ölçü grubu girilmelidir.')
            if not customer_name and not customer_id:
                errors.append('Müşteri adı girilmeli veya mevcut bir müşteri seçilmelidir.')
            if not urun:
                errors.append('Ürün girilmelidir.')
            quantity = None
            if not quantity_raw:
                errors.append('Adet girilmelidir.')
            else:
                try:
                    quantity = float(quantity_raw)
                    if quantity <= 0:
                        errors.append('Adet 0\'dan büyük olmalıdır.')
                except ValueError:
                    errors.append('Adet geçerli bir sayı olmalıdır.')

            if errors:
                for err in errors:
                    flash(err, 'danger')
                return redirect(url_for('add_manual_planning_entry'))

            customer = Customer.query.get(int(customer_id)) if customer_id else None
            entry = ManualPlanningEntry(
                group_key=group_key,
                customer_name=customer.display_name if customer else customer_name,
                customer_id=customer.id if customer else None,
                urun=urun,
                quantity=quantity,
                unit=unit,
                delivery_date=datetime.strptime(delivery_date_raw, '%Y-%m-%d').date() if delivery_date_raw else None,
                notes=request.form.get('notes', '').strip() or None,
                user_id=current_user.id
            )
            db.session.add(entry)
            db.session.commit()
            flash('Manuel kayıt üretim planına eklendi!', 'success')
            return redirect(url_for('uretim_planlama'))

        existing_group_keys = sorted({
            _planning_group_key(item) for item in
            ProductionItem.query.join(Production).filter(
                Production.status == 'uretimde',
                ProductionItem.urun_tipi != 'ticaret'
            ).all() if _planning_group_key(item)
        })
        return render_template('add_manual_planning_entry.html', today=datetime.now().date(),
                                existing_group_keys=existing_group_keys)

    @app.route('/uretim-planlama/manuel/<int:id>/sil', methods=['POST'])
    @login_required
    def delete_manual_planning_entry(id):
        entry = ManualPlanningEntry.query.get_or_404(id)
        db.session.delete(entry)
        db.session.commit()
        flash('Manuel kayıt silindi!', 'success')
        return redirect(url_for('uretim_planlama'))

    @app.route('/production/<int:id>')
    @login_required
    def production_detail(id):
        production = Production.query.get_or_404(id)
        shipments = Shipment.query.filter_by(production_id=id).order_by(Shipment.created_at.desc()).all()
        # Is 3: bu uretim isine baglanmis Gunluk Uretim kayitlari (bkz.
        # DailyProductionOutput.production_id).
        daily_outputs = DailyProductionOutput.query.filter_by(production_id=id) \
            .order_by(DailyProductionOutput.tarih.desc(), DailyProductionOutput.created_at.desc()).all()
        daily_outputs_total_kg = sum(o.toplam_kg for o in daily_outputs)
        return render_template('production_detail.html', production=production, shipments=shipments,
                                today=datetime.now().date(), stages=PRODUCTION_STAGES,
                                ticaret_stages=TICARET_STAGES, daily_outputs=daily_outputs,
                                daily_outputs_total_kg=daily_outputs_total_kg)

    @app.route('/production/<int:id>/row-detail')
    @login_required
    def production_row_detail(id):
        """Is 4: Uretim Listesi'nde satira tiklaninca AJAX ile yuklenen
        acilir bolum - Siparis Bilgisi + Gunluk Uretim (AYNI
        DailyProductionOutput/add_daily_production_output() - İş 3 ile
        cakisma yok) + Hizli Islemler (mark_production_ready/edit_production
        ile AYNI route'lar, kopya mantik yok)."""
        production = Production.query.get_or_404(id)
        daily_outputs = DailyProductionOutput.query.filter_by(production_id=id) \
            .order_by(DailyProductionOutput.tarih.desc()).all()
        daily_outputs_total_kg = sum(o.toplam_kg for o in daily_outputs)
        return render_template('_production_row_detail.html', production=production,
                                daily_outputs=daily_outputs, daily_outputs_total_kg=daily_outputs_total_kg,
                                today=datetime.now().date())

    @app.route('/production/<int:id>/update-specs', methods=['POST'])
    @login_required
    def update_production_item_specs(id):
        production = Production.query.get_or_404(id)
        for item in production.items:
            item.olcu = request.form.get(f'olcu_{item.id}', '').strip() or None
            item.baski_bilgisi = request.form.get(f'baski_{item.id}', '').strip() or None
            item.kagit_tipi = request.form.get(f'kagit_{item.id}', '').strip() or None
            item.gramaj = request.form.get(f'gramaj_{item.id}', '').strip() or None
            item.kac_kg = request.form.get(f'kackg_{item.id}', '').strip() or None
            if f'taban_olcusu_{item.id}' in request.form:
                item.taban_olcusu = request.form.get(f'taban_olcusu_{item.id}', '').strip() or None
        db.session.commit()
        flash('İş emri bilgileri kaydedildi!', 'success')
        return redirect(url_for('production_detail', id=id))

    @app.route('/production/item/<int:item_id>/ticaret-durumu', methods=['POST'])
    @login_required
    def update_ticaret_durumu(item_id):
        """'ticaret' tipi kalemler icin 3 durumlu takip (Siparis Edildi ->
        Tedarik Edildi -> Teslime Hazir) - uretim is emri surecine dahil
        edilmez. Ayni TICARET_STAGE_KEYS /tedarik-takip sayfasinda da
        kullanilir, ikisi senkron kalir (tek kaynak: bu alan)."""
        item = ProductionItem.query.get_or_404(item_id)
        if item.urun_tipi != 'ticaret':
            flash('Bu kalem ticaret tipi değil.', 'danger')
            return redirect(url_for('production_detail', id=item.production_id))
        new_status = request.form.get('ticaret_durumu')
        if new_status not in TICARET_STAGE_KEYS:
            flash('Geçersiz durum.', 'danger')
            return redirect(url_for('production_detail', id=item.production_id))
        item.ticaret_durumu = new_status
        db.session.commit()
        flash('Ticaret ürünü durumu güncellendi!', 'success')
        return redirect(url_for('production_detail', id=item.production_id))

    @app.route('/tedarik-takip')
    @login_required
    def tedarik_takip():
        """Ticaret tipi (hazir alinip satilan) TUM urun kalemlerini merkezi
        bir sayfada listeler - production_detail'deki gomulu takipten farkli
        olarak tum musteri/teklifler tek yerde gorulur. Ayni ticaret_durumu
        alanini kullandigi icin durum degisiklikleri iki sayfada da senkron
        gorunur (tek kaynak - ayri bir kopya alan yok)."""
        items = ProductionItem.query.join(Production).options(
            joinedload(ProductionItem.production).joinedload(Production.deal).joinedload(Deal.customer)
        ).filter(
            ProductionItem.urun_tipi == 'ticaret'
        ).order_by(Production.created_at.desc()).all()
        manual_entries = ManualTedarikEntry.query.options(joinedload(ManualTedarikEntry.customer)) \
            .order_by(ManualTedarikEntry.created_at.desc()).all()

        def _next_stage(durum):
            try:
                idx = TICARET_STAGE_KEYS.index(durum)
            except ValueError:
                idx = -1
            if idx < 0 or idx >= len(TICARET_STAGE_KEYS) - 1:
                return None
            next_key = TICARET_STAGE_KEYS[idx + 1]
            return {'key': next_key, 'label': TICARET_STAGE_LABELS[next_key]}

        rows = []
        for item in items:
            durum = item.ticaret_durumu or 'siparis_edildi'
            rows.append({
                'kind': 'production',
                'customer_name': item.production.deal.customer.display_name,
                'deal_no': item.production.deal.display_no,
                'urun': item.description,
                'quantity': item.planned_quantity,
                'unit': item.unit,
                'delivery_date': item.production.due_date,
                'durum': durum,
                'durum_label': TICARET_STAGE_LABELS.get(durum, durum),
                'next_stage': _next_stage(durum),
                'item_id': item.id,
                'production_id': item.production_id,
            })
        for entry in manual_entries:
            rows.append({
                'kind': 'manual',
                'customer_name': entry.customer.display_name if entry.customer else entry.customer_name,
                'deal_no': None,
                'urun': entry.urun,
                'quantity': entry.quantity,
                'unit': entry.unit,
                'delivery_date': entry.delivery_date,
                'durum': entry.durum,
                'durum_label': TICARET_STAGE_LABELS.get(entry.durum, entry.durum),
                'next_stage': _next_stage(entry.durum),
                'manual_id': entry.id,
            })

        return render_template('tedarik_takip.html', rows=rows, stages=TICARET_STAGES,
                                today=datetime.now().date())

    @app.route('/tedarik-takip/manuel-ekle', methods=['GET', 'POST'])
    @login_required
    def add_manual_tedarik_entry():
        """Sistemde formal bir teklifi olmayan bir tedarik kalemini elle
        /tedarik-takip listesine ekler."""
        if request.method == 'POST':
            customer_name = request.form.get('customer_name', '').strip()
            customer_id = request.form.get('customer_id') or None
            urun = request.form.get('urun', '').strip()
            quantity_raw = request.form.get('quantity', '').strip()
            unit = request.form.get('unit', 'adet').strip() or 'adet'
            delivery_date_raw = request.form.get('delivery_date', '').strip()

            errors = []
            if not customer_name and not customer_id:
                errors.append('Müşteri adı girilmeli veya mevcut bir müşteri seçilmelidir.')
            if not urun:
                errors.append('Ürün girilmelidir.')
            quantity = None
            if not quantity_raw:
                errors.append('Adet girilmelidir.')
            else:
                try:
                    quantity = float(quantity_raw)
                    if quantity <= 0:
                        errors.append('Adet 0\'dan büyük olmalıdır.')
                except ValueError:
                    errors.append('Adet geçerli bir sayı olmalıdır.')

            if errors:
                for err in errors:
                    flash(err, 'danger')
                return redirect(url_for('add_manual_tedarik_entry'))

            customer = Customer.query.get(int(customer_id)) if customer_id else None
            entry = ManualTedarikEntry(
                customer_name=customer.display_name if customer else customer_name,
                customer_id=customer.id if customer else None,
                urun=urun,
                quantity=quantity,
                unit=unit,
                delivery_date=datetime.strptime(delivery_date_raw, '%Y-%m-%d').date() if delivery_date_raw else None,
                durum='siparis_edildi',
                notes=request.form.get('notes', '').strip() or None,
                user_id=current_user.id
            )
            db.session.add(entry)
            db.session.commit()
            flash('Manuel kayıt tedarik takibine eklendi!', 'success')
            return redirect(url_for('tedarik_takip'))

        return render_template('add_manual_tedarik_entry.html', today=datetime.now().date())

    @app.route('/tedarik-takip/manuel/<int:id>/durum', methods=['POST'])
    @login_required
    def update_manual_tedarik_durum(id):
        entry = ManualTedarikEntry.query.get_or_404(id)
        new_status = request.form.get('durum')
        if new_status not in TICARET_STAGE_KEYS:
            flash('Geçersiz durum.', 'danger')
            return redirect(url_for('tedarik_takip'))
        entry.durum = new_status
        db.session.commit()
        flash('Durum güncellendi!', 'success')
        return redirect(url_for('tedarik_takip'))

    @app.route('/tedarik-takip/manuel/<int:id>/sil', methods=['POST'])
    @login_required
    def delete_manual_tedarik_entry(id):
        entry = ManualTedarikEntry.query.get_or_404(id)
        db.session.delete(entry)
        db.session.commit()
        flash('Manuel kayıt silindi!', 'success')
        return redirect(url_for('tedarik_takip'))

    @app.route('/gunluk-uretim')
    @login_required
    def gunluk_uretim():
        """Is 3: atolyenin gun icinde elle doldurdugu uretim takip
        kagidinin dijital karsiligi - tarihe gore gruplanmis, her gunun
        altinda o gune ait TUM girisler + gun sonu TOPLAM kg. Musteri/Firma
        alani artik aktif (henuz teslim edilmemis) Production kayitlarindan
        secilen bir arama/dropdown - bkz. active_productions."""
        entries = DailyProductionOutput.query.options(
            joinedload(DailyProductionOutput.customer),
            joinedload(DailyProductionOutput.production).joinedload(Production.deal).joinedload(Deal.customer),
        ).order_by(DailyProductionOutput.tarih.desc(), DailyProductionOutput.created_at.asc()).all()
        photos = DailyProductionPhoto.query.order_by(
            DailyProductionPhoto.tarih.desc(), DailyProductionPhoto.created_at.asc()
        ).all()

        photos_by_date = {}
        for p in photos:
            photos_by_date.setdefault(p.tarih, []).append(p)

        groups = {}
        for e in entries:
            groups.setdefault(e.tarih, []).append(e)

        day_groups = []
        for d in sorted(groups.keys(), reverse=True):
            rows = groups[d]
            day_groups.append({
                'tarih': d,
                'rows': rows,
                'total_kg': sum(r.toplam_kg for r in rows),
                'photos': photos_by_date.get(d, []),
            })

        active_productions = [p for p in Production.query.options(
            joinedload(Production.deal).joinedload(Deal.customer),
            joinedload(Production.shipments),
        ).order_by(Production.created_at.desc()).all() if not p.is_delivered]

        return render_template('gunluk_uretim.html', day_groups=day_groups, today=datetime.now().date(),
                                active_productions=active_productions)

    @app.route('/gunluk-uretim/bos-form-pdf')
    @login_required
    def gunluk_uretim_bos_form_pdf():
        """Is 5: veritabanindan veri cekmeyen, atolyede elle doldurulacak
        BOS form PDF'i - her gun yeniden basilabilsin diye buradan
        indirilir."""
        pdf = generate_gunluk_uretim_form_pdf()
        return send_file(pdf, as_attachment=True,
                          download_name=f'gunluk_uretim_takip_formu_{datetime.now().strftime("%Y%m%d")}.pdf')

    @app.route('/gunluk-uretim/add', methods=['POST'])
    @login_required
    def add_daily_production_output():
        """AJAX (JSON) endpoint - sayfa yenilenmeden art arda kalem
        eklenebilsin diye fetch() ile cagrilir (Is 3), olusturulan kaydi
        JSON olarak doner; JS bunu ilgili gun grubuna ekler. Musteri/Firma
        artik serbest metin DEGIL - zorunlu olarak aktif bir Production
        kaydi secilir, musteri_adi/customer_id oradan (deal.customer)
        otomatik turetilir (eski kayitlara dokunulmaz, bu alanlar DB
        semasinda duruyor - sadece yeni giris akisi degisti)."""
        tarih_raw = request.form.get('tarih', '').strip()
        production_id_raw = request.form.get('production_id', '').strip()
        koli_basi_kg_raw = request.form.get('koli_basi_kg', '').strip()
        koli_adedi_raw = request.form.get('koli_adedi', '').strip()
        toplam_kg_raw = request.form.get('toplam_kg', '').strip()
        aciklama = request.form.get('aciklama', '').strip() or None

        if not tarih_raw:
            return jsonify({'error': 'Tarih girilmelidir.'}), 400
        if not production_id_raw:
            return jsonify({'error': 'Müşteri/Firma (üretim kaydı) seçilmelidir.'}), 400
        production = Production.query.get(int(production_id_raw))
        if not production:
            return jsonify({'error': 'Seçilen üretim kaydı bulunamadı.'}), 400
        try:
            koli_basi_kg = float(koli_basi_kg_raw)
            koli_adedi = float(koli_adedi_raw)
        except ValueError:
            return jsonify({'error': 'Koli Başı Kg ve Koli Adedi geçerli bir sayı olmalıdır.'}), 400
        if koli_basi_kg <= 0 or koli_adedi <= 0:
            return jsonify({'error': "Koli Başı Kg ve Koli Adedi 0'dan büyük olmalıdır."}), 400

        if toplam_kg_raw:
            try:
                toplam_kg = float(toplam_kg_raw)
            except ValueError:
                return jsonify({'error': 'Toplam Kg geçerli bir sayı olmalıdır.'}), 400
        else:
            toplam_kg = koli_basi_kg * koli_adedi

        customer = production.deal.customer if production.deal else None

        try:
            entry = DailyProductionOutput(
                tarih=datetime.strptime(tarih_raw, '%Y-%m-%d').date(),
                musteri_adi=customer.display_name if customer else f'Üretim #{production.id}',
                customer_id=customer.id if customer else None,
                production_id=production.id,
                koli_basi_kg=koli_basi_kg,
                koli_adedi=koli_adedi,
                toplam_kg=toplam_kg,
                aciklama=aciklama,
                user_id=current_user.id,
            )
            db.session.add(entry)
            db.session.commit()
        except Exception:
            db.session.rollback()
            return jsonify({'error': 'Kayıt eklenirken bir hata oluştu, hiçbir değişiklik kaydedilmedi.'}), 500

        return jsonify({
            'id': entry.id,
            'tarih': entry.tarih.strftime('%Y-%m-%d'),
            'tarih_display': entry.tarih.strftime('%d.%m.%Y'),
            'musteri_adi': entry.musteri_adi,
            'koli_basi_kg': entry.koli_basi_kg,
            'koli_adedi': entry.koli_adedi,
            'toplam_kg': entry.toplam_kg,
            'aciklama': entry.aciklama or '',
        }), 201

    @app.route('/gunluk-uretim/<int:id>/sil', methods=['POST'])
    @login_required
    def delete_daily_production_output(id):
        entry = DailyProductionOutput.query.get_or_404(id)
        db.session.delete(entry)
        db.session.commit()
        flash('Kayıt silindi!', 'success')
        return redirect(url_for('gunluk_uretim'))

    @app.route('/gunluk-uretim/foto-ekle', methods=['POST'])
    @login_required
    def add_daily_production_photo():
        """Is 4: SADECE arsivleme - hicbir OCR/okuma yapilmaz. foto_turu
        'form' (elle doldurulan kagidin fotografi) veya 'urun' (uretilen
        malin gorseli) olabilir, TARIHE baglidir (tekil satira degil)."""
        tarih_raw = request.form.get('tarih', '').strip()
        foto_turu = request.form.get('foto_turu', '').strip()
        photo_file = request.files.get('foto')

        if foto_turu not in ('form', 'urun'):
            flash('Geçersiz fotoğraf türü.', 'danger')
            return redirect(url_for('gunluk_uretim'))
        if not tarih_raw:
            flash('Tarih girilmelidir.', 'danger')
            return redirect(url_for('gunluk_uretim'))

        path, error = _save_uploaded_image(photo_file, 'gunluk_uretim')
        if error:
            flash(error, 'danger')
            return redirect(url_for('gunluk_uretim'))
        if not path:
            flash('Bir fotoğraf seçmediniz.', 'warning')
            return redirect(url_for('gunluk_uretim'))

        photo = DailyProductionPhoto(
            tarih=datetime.strptime(tarih_raw, '%Y-%m-%d').date(),
            foto_turu=foto_turu,
            dosya_yolu=path,
            user_id=current_user.id,
        )
        db.session.add(photo)
        db.session.commit()
        flash('Fotoğraf eklendi!', 'success')
        return redirect(url_for('gunluk_uretim'))

    @app.route('/production/<int:id>/tasarim-yukle', methods=['POST'])
    @login_required
    def upload_production_tasarim(id):
        production = Production.query.get_or_404(id)
        tasarim_file = request.files.get('tasarim_gorseli')
        path, error = _save_uploaded_image(tasarim_file, 'tasarimlar')
        if error:
            flash(error, 'danger')
        else:
            production.tasarim_gorseli_override = path
            db.session.commit()
            flash('Bu iş emri için tasarım görseli kaydedildi!', 'success')
        return redirect(url_for('production_detail', id=id))

    @app.route('/production/<int:id>/is-emri')
    @login_required
    def production_is_emri_pdf(id):
        production = Production.query.get_or_404(id)
        nusha = request.args.get('nusha')
        copy_labels = {'baski': 'Baskı Ustası', 'makine': 'Makine Ustası'}
        copy_label = copy_labels.get(nusha)
        pdf = generate_is_emri_pdf(production, copy_label=copy_label)

        customer_name = _customer_full_name(production.deal.customer)
        safe_name = _safe_filename_part(customer_name)
        filename = f'IsEmri_{safe_name}_IE{production.id:05d}.pdf'
        return send_file(pdf, as_attachment=True, download_name=filename)

    @app.route('/production/<int:id>/mark-ready', methods=['POST'])
    @login_required
    def mark_production_ready(id):
        production = Production.query.get_or_404(id)
        if production.status != 'uretimde':
            flash('Sadece "Üretimde" durumundaki iş emirleri Hazır olarak işaretlenebilir.', 'danger')
            return redirect(url_for('production_detail', id=id))

        # Her kalem icin gercek uretilen adet (fiyat/kg istenmez - Is C)
        for item in production.uretim_items:
            produced_str = request.form.get(f'produced_{item.id}', '').strip()
            if produced_str != '':
                try:
                    item.produced_quantity = float(produced_str)
                except ValueError:
                    pass
            item.status = 'uretilen' if item.produced_quantity > 0 else 'bekleniyor'

        # Is 4: karma (Uretim + Ticaret) is emirlerinde eskiden bu buton
        # TUM kalemler degil sadece uretim kalemlerini kontrol ederek
        # durumu 'hazir'a geciriyordu - Ticaret kalemleri henuz "Teslime
        # Hazir" olmasa bile genel durum degisiyor, bu da Sevkiyat'in
        # eksik/gelmemis ticaret urunuyle acilmasina izin veriyordu. Artik
        # TUM kalemler (uretim.is_produced icin gercek uretilen miktar,
        # ticaret.is_produced icin ticaret_durumu='teslime_hazir') hazir
        # olmadan durum degismiyor, kullaniciya net bir ilerleme mesaji
        # gosteriliyor.
        if not production.all_items_produced:
            flash(
                f'Tüm kalemler henüz hazır değil ({production.produced_items_count}/'
                f'{production.total_items_count} kalem hazır) - Ticaret ürünlerinin '
                f'"Teslime Hazır" durumuna gelmesini bekleyin, ya da Üretim kalemlerinin '
                f'tamamı için gerçek üretilen adedi girin.', 'danger'
            )
            db.session.commit()  # girilen uretilen adetler kaybolmasin
            return redirect(url_for('production_detail', id=id))

        production.status = 'hazir'
        production.end_date = datetime.now().date()
        db.session.commit()
        flash('Üretim "Hazır" olarak işaretlendi!', 'success')
        return redirect(url_for('production_detail', id=id))

    @app.route('/production/<int:id>/create-shipment', methods=['GET', 'POST'])
    @login_required
    def create_shipment_from_production(id):
        production = Production.query.get_or_404(id)

        if production.status != 'hazir':
            flash('Sevkiyat oluşturmak için üretim "Hazır" aşamasında olmalı.', 'danger')
            return redirect(url_for('production_detail', id=id))

        # Is D / Is 4: irsaliye HER DURUMDA zorunlu; fatura ise "Faturasiz Cikis"
        # onay kutusu isaretlenmeden atlanamaz.
        deal_id = production.deal_id
        has_invoice = Invoice.query.filter_by(deal_id=deal_id, type='fatura').first() is not None
        has_irsaliye = Invoice.query.filter_by(deal_id=deal_id, type='irsaliye').first() is not None
        if not has_irsaliye:
            flash('Sevkiyat oluşturmadan önce bu iş emrine bağlı bir irsaliye oluşturmalısınız.', 'danger')
            return redirect(url_for('deal_detail', id=deal_id))

        if request.method == 'POST':
            faturasiz_cikis_checked = request.form.get('faturasiz_cikis') == 'on'
            if not has_invoice and not faturasiz_cikis_checked:
                flash('Sevkiyat oluşturmadan önce fatura oluşturmalı ya da "Faturasız Çıkış" seçeneğini işaretlemelisiniz.', 'danger')
                return redirect(url_for('deal_detail', id=deal_id))

            # Cift-tiklama korumasi: ayni production icin birkac saniye once
            # zaten bir Shipment olusmussa (status='hazir' kontrolu, iki
            # istek DB'ye commit edilmeden once neredeyse ayni anda gelirse
            # ikisini de gecirebiliyordu - gercek veride bu sekilde mukerrer
            # sevkiyat olustugu tespit edildi) yeni kayit acmak yerine mevcut
            # olana yonlendir.
            recent_cutoff = datetime.utcnow() - timedelta(seconds=30)
            recent_duplicate = Shipment.query.filter(
                Shipment.production_id == id, Shipment.created_at >= recent_cutoff
            ).first()
            if recent_duplicate:
                flash(f'SVN-{recent_duplicate.id:05d} sevkiyatı az önce zaten oluşturuldu.', 'info')
                return redirect(url_for('shipment_detail', id=recent_duplicate.id))

            try:
                shipment = Shipment(
                    production_id=id,
                    ship_date=datetime.strptime(request.form['ship_date'], '%Y-%m-%d').date() if request.form.get('ship_date') else datetime.now().date(),
                    estimated_delivery_date=datetime.strptime(request.form['estimated_delivery_date'], '%Y-%m-%d').date() if request.form.get('estimated_delivery_date') else None,
                    carrier=request.form.get('carrier') or None,
                    tracking_number=request.form.get('tracking_number') or None,
                    status='hazirlaniyor',
                    faturasiz_cikis=not has_invoice,
                    notes=request.form.get('notes', '')
                )
                db.session.add(shipment)
                db.session.flush()

                # Sevkiyat kalemleri, uretimde kaydedilen gercek uretilen adetten
                # otomatik olusturulur - fiyat/kg tekrar sorulmaz (Is C).
                for item in production.items:
                    if item.produced_quantity and item.produced_quantity > 0:
                        db.session.add(ShipmentItem(
                            shipment_id=shipment.id,
                            production_item_id=item.id,
                            description=item.description,
                            quantity=item.produced_quantity,
                            unit=item.unit
                        ))

                production.status = 'sevkiyat'
                db.session.commit()
            except Exception:
                db.session.rollback()
                flash('Sevkiyat oluşturulurken bir hata oluştu, hiçbir değişiklik kaydedilmedi. Girdiğiniz bilgileri kontrol edip tekrar deneyin.', 'danger')
                return redirect(url_for('create_shipment_from_production', id=id))

            flash(f'SVN-{shipment.id:05d} sevkiyatı oluşturuldu!', 'success')
            return redirect(url_for('shipment_detail', id=shipment.id))

        return render_template('create_shipment_from_production.html', production=production, carriers=CARRIER_OPTIONS,
                                today=datetime.now().date(), has_invoice=has_invoice)

    @app.route('/shipments/<int:id>/mark-delivered', methods=['POST'])
    @login_required
    def mark_shipment_delivered(id):
        shipment = Shipment.query.get_or_404(id)
        shipment.actual_delivery_date = datetime.now().date()
        shipment.status = 'teslim_edildi'
        db.session.commit()
        flash('Sevkiyat "Teslim Edildi" olarak işaretlendi.', 'success')
        return redirect(url_for('shipment_detail', id=id))

    @app.route('/shipments/<int:id>/irsaliye')
    @login_required
    def shipment_irsaliye_pdf(id):
        shipment = Shipment.query.get_or_404(id)
        pdf = generate_irsaliye_pdf(shipment)
        return send_file(pdf, as_attachment=True, download_name=f'irsaliye_SVN-{shipment.id:05d}.pdf')

    @app.route('/shipments/<int:id>')
    @login_required
    def shipment_detail(id):
        shipment = Shipment.query.get_or_404(id)
        return render_template('shipment_detail.html', shipment=shipment)

    @app.route('/production/<int:id>/edit', methods=['GET', 'POST'])
    @login_required
    def edit_production(id):
        production = Production.query.get_or_404(id)
        if request.method == 'POST':
            new_status = request.form['status']
            # 'Sevkiyat' durumuna GECIS burada elle yapilamaz - bu asama
            # sadece create_shipment_from_production uzerinden, irsaliye/
            # fatura zorunlulugu kontrol edilerek gecilebilir. Aksi halde
            # (daha once tam olarak boyle bir kayitta - Production #33 -
            # gorulduugu gibi) hicbir Shipment/irsaliye kaydi olmadan
            # 'sevkiyat' durumuna gecilebiliyordu. Zaten 'sevkiyat'
            # durumundaki bir kaydin diger alanlarini (not vb.) duzenlemek
            # hala serbest - engellenen sadece YENI bir gecis.
            if new_status == 'sevkiyat' and production.status != 'sevkiyat':
                flash('Üretim durumu buradan doğrudan "Sevkiyat" olarak değiştirilemez. '
                      'Sevkiyat oluşturmak için üretim detayındaki "Sevkiyat Oluştur" akışını kullanın '
                      '(irsaliye/fatura kontrolü orada yapılır).', 'danger')
                return redirect(url_for('edit_production', id=id))
            production.status = new_status
            production.start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date() if request.form.get('start_date') else None
            production.end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d').date() if request.form.get('end_date') else None
            production.due_date = datetime.strptime(request.form['due_date'], '%Y-%m-%d').date() if request.form.get('due_date') else None
            production.notes = request.form.get('notes')
            db.session.commit()
            flash('Üretim güncellendi!', 'success')
            return redirect(url_for('production_detail', id=id))
        return render_template('edit_production.html', production=production, stages=PRODUCTION_STAGES)

    @app.route('/production/<int:id>/shipment/add', methods=['GET', 'POST'])
    @login_required
    def add_shipment(id):
        production = Production.query.get_or_404(id)
        if request.method == 'POST':
            shipment = Shipment(
                production_id=id, quantity=float(request.form['quantity']),
                unit=request.form.get('unit', 'adet'),
                weight_kg=float(request.form['weight_kg']) if request.form.get('weight_kg') else None,
                ship_date=datetime.strptime(request.form['ship_date'], '%Y-%m-%d').date() if request.form.get('ship_date') else datetime.now().date(),
                tracking_number=request.form.get('tracking_number'), carrier=request.form.get('carrier'),
                status=request.form.get('status', 'hazirlaniyor'), notes=request.form.get('notes')
            )
            db.session.add(shipment)
            db.session.commit()
            flash('Sevkiyat eklendi!', 'success')
            return redirect(url_for('production_detail', id=id))
        return render_template('add_shipment.html', production=production)

    @app.route('/shipments')
    @login_required
    def shipment_list():
        shipments = Shipment.query.options(
            joinedload(Shipment.production).joinedload(Production.deal).joinedload(Deal.customer)
        ).order_by(Shipment.created_at.desc()).all()
        for s in shipments:
            s.is_manual = False

        # Is 1: bagimsiz manuel irsaliyeler, ayri bir liste sayfasi acmadan
        # bu mevcut sevkiyat listesine "Manuel" etiketiyle karisik gosterilir.
        manual_irsaliyeler = ManualIrsaliye.query.options(
            joinedload(ManualIrsaliye.customer)
        ).order_by(ManualIrsaliye.created_at.desc()).all()
        for m in manual_irsaliyeler:
            m.is_manual = True

        rows = sorted(shipments + manual_irsaliyeler, key=lambda r: r.created_at, reverse=True)
        return render_template('shipment_list.html', rows=rows)

    @app.route('/irsaliye/manuel-olustur', methods=['GET', 'POST'])
    @login_required
    def manual_irsaliye_add():
        if request.method == 'POST':
            customer_id = request.form.get('customer_id')
            if not customer_id:
                flash('Lütfen bir müşteri seçin.', 'danger')
                return render_template('manual_irsaliye_add.html', carriers=CARRIER_OPTIONS, today=datetime.now().date())

            # Cift-tiklama korumasi: ayni musteri icin birkac saniye once
            # zaten bir ManualIrsaliye olusmussa yeni kayit acmak yerine
            # mevcut olana yonlendir.
            recent_cutoff = datetime.utcnow() - timedelta(seconds=30)
            recent_duplicate = ManualIrsaliye.query.filter(
                ManualIrsaliye.customer_id == int(customer_id), ManualIrsaliye.created_at >= recent_cutoff
            ).first()
            if recent_duplicate:
                flash(f'{recent_duplicate.display_no} irsaliyesi az önce zaten oluşturuldu.', 'info')
                return redirect(url_for('manual_irsaliye_detail', id=recent_duplicate.id))

            try:
                manual_irsaliye = ManualIrsaliye(
                    customer_id=int(customer_id),
                    ship_date=datetime.strptime(request.form['ship_date'], '%Y-%m-%d').date() if request.form.get('ship_date') else datetime.now().date(),
                    estimated_delivery_date=datetime.strptime(request.form['estimated_delivery_date'], '%Y-%m-%d').date() if request.form.get('estimated_delivery_date') else None,
                    carrier=request.form.get('carrier') or None,
                    tracking_number=request.form.get('tracking_number') or None,
                    notes=request.form.get('notes', ''),
                    user_id=current_user.id,
                    vat_rate=float(request.form.get('vat_rate', 20))
                )
                db.session.add(manual_irsaliye)
                db.session.flush()

                i = 0
                while f'desc_{i}' in request.form:
                    desc = request.form.get(f'desc_{i}', '').strip()
                    qty = request.form.get(f'qty_{i}', '').strip()
                    price_raw = request.form.get(f'price_{i}', '').strip()
                    if desc and qty:
                        db.session.add(ManualIrsaliyeItem(
                            manual_irsaliye_id=manual_irsaliye.id,
                            description=desc,
                            quantity=float(qty),
                            unit=request.form.get(f'unit_{i}', 'adet'),
                            unit_price=float(price_raw) if price_raw else 0
                        ))
                    i += 1

                db.session.flush()

                # Is 5 madde 2+4: fiyat GIRILMIS kalem varsa (en az biri)
                # otomatik dahili takip faturasi olustur, irsaliyeye bagla
                # (invoice_id) - borc bu sayede Cari Hesap'a (Invoice.
                # customer_id uzerinden, mevcut tek merkezi hesaplama)
                # otomatik duser. Hic fiyat girilmediyse (eski davranis)
                # hicbir fatura olusmaz.
                if manual_irsaliye.is_priced:
                    auto_invoice = Invoice(
                        invoice_no=_next_invoice_no(),
                        type='fatura',
                        deal_id=None,
                        customer_id=manual_irsaliye.customer_id,
                        user_id=current_user.id,
                        date=manual_irsaliye.ship_date or datetime.now().date(),
                        vat_rate=manual_irsaliye.vat_rate,
                        notes=f'{manual_irsaliye.display_no} irsaliyesinden otomatik oluşturuldu.'
                    )
                    db.session.add(auto_invoice)
                    db.session.flush()
                    for item in manual_irsaliye.items:
                        db.session.add(InvoiceItem(
                            invoice_id=auto_invoice.id,
                            description=item.description,
                            quantity=item.quantity,
                            unit=item.unit,
                            unit_price=item.unit_price or 0,
                            total_price=item.total_price
                        ))
                    db.session.flush()
                    auto_invoice.calculate_totals()
                    manual_irsaliye.invoice_id = auto_invoice.id

                db.session.commit()
            except Exception:
                db.session.rollback()
                flash('İrsaliye oluşturulurken bir hata oluştu, hiçbir değişiklik kaydedilmedi. Girdiğiniz bilgileri kontrol edip tekrar deneyin.', 'danger')
                return redirect(url_for('manual_irsaliye_add'))

            if manual_irsaliye.invoice_id:
                flash(f'{manual_irsaliye.display_no} manuel irsaliyesi oluşturuldu ve {auto_invoice.display_no} dahili fatura otomatik oluşturuldu!', 'success')
            else:
                flash(f'{manual_irsaliye.display_no} manuel irsaliyesi oluşturuldu!', 'success')
            return redirect(url_for('manual_irsaliye_detail', id=manual_irsaliye.id))

        return render_template('manual_irsaliye_add.html', carriers=CARRIER_OPTIONS, today=datetime.now().date())

    @app.route('/irsaliye/manuel/<int:id>')
    @login_required
    def manual_irsaliye_detail(id):
        manual_irsaliye = ManualIrsaliye.query.get_or_404(id)
        return render_template('manual_irsaliye_detail.html', manual_irsaliye=manual_irsaliye)

    @app.route('/irsaliye/manuel/<int:id>/pdf')
    @login_required
    def manual_irsaliye_pdf(id):
        """Is 5 madde 3: ?priced=1 ile fiyatli PDF (yalnizca irsaliye
        fiyatliysa anlamli - generate_manual_irsaliye_pdf fiyatsizsa zaten
        sessizce fiyatsiz tabloya duser), varsayilan fiyatsiz."""
        manual_irsaliye = ManualIrsaliye.query.get_or_404(id)
        show_prices = request.args.get('priced') == '1'
        pdf = generate_manual_irsaliye_pdf(manual_irsaliye, show_prices=show_prices)
        suffix = '_fiyatli' if show_prices and manual_irsaliye.is_priced else ''
        return send_file(pdf, as_attachment=True, download_name=f'irsaliye_{manual_irsaliye.display_no}{suffix}.pdf')

    @app.route('/irsaliye/manuel/<int:id>/mark-delivered', methods=['POST'])
    @login_required
    def mark_manual_irsaliye_delivered(id):
        manual_irsaliye = ManualIrsaliye.query.get_or_404(id)
        manual_irsaliye.actual_delivery_date = datetime.now().date()
        manual_irsaliye.status = 'teslim_edildi'
        db.session.commit()
        flash('İrsaliye "Teslim Edildi" olarak işaretlendi.', 'success')
        return redirect(url_for('manual_irsaliye_detail', id=id))

    @app.route('/shipments/<int:id>/edit', methods=['GET', 'POST'])
    @login_required
    def edit_shipment(id):
        shipment = Shipment.query.get_or_404(id)
        if request.method == 'POST':
            shipment.ship_date = datetime.strptime(request.form['ship_date'], '%Y-%m-%d').date() if request.form.get('ship_date') else None
            shipment.estimated_delivery_date = datetime.strptime(request.form['estimated_delivery_date'], '%Y-%m-%d').date() if request.form.get('estimated_delivery_date') else None
            shipment.tracking_number = request.form.get('tracking_number') or None
            shipment.carrier = request.form.get('carrier') or None
            shipment.status = request.form['status']
            if shipment.status == 'teslim_edildi' and not shipment.actual_delivery_date:
                shipment.actual_delivery_date = datetime.now().date()
            shipment.notes = request.form.get('notes')
            db.session.commit()
            flash('Sevkiyat güncellendi!', 'success')
            return redirect(url_for('production_detail', id=shipment.production_id))
        return render_template('edit_shipment.html', shipment=shipment, carriers=CARRIER_OPTIONS, statuses=SHIPMENT_STATUSES)

    @app.route('/products')
    @login_required
    def products():
        search = request.args.get('search', '')
        if search:
            products = Product.query.filter(db.or_(
                Product.name.ilike(f'%{search}%'), Product.sku.ilike(f'%{search}%'),
                Product.category.ilike(f'%{search}%')
            )).order_by(Product.name).all()
        else:
            products = Product.query.order_by(Product.name).all()
        return render_template('products.html', products=products, search=search)

    @app.route('/products/add', methods=['GET', 'POST'])
    @login_required
    def add_product():
        if request.method == 'POST':
            product = Product(
                name=request.form['name'], sku=request.form.get('sku'),
                description=request.form.get('description'), unit=request.form.get('unit', 'adet'),
                stock_quantity=float(request.form.get('stock_quantity', 0)),
                min_stock=float(request.form.get('min_stock', 0)),
                cost_price=float(request.form.get('cost_price', 0)),
                sell_price=float(request.form.get('sell_price', 0)),
                category=request.form.get('category')
            )
            db.session.add(product)
            db.session.commit()
            flash('Ürün eklendi!', 'success')
            return redirect(url_for('products'))
        return render_template('add_product.html')

    @app.route('/products/<int:id>')
    @login_required
    def product_detail(id):
        product = Product.query.get_or_404(id)
        return render_template('product_detail.html', product=product)

    @app.route('/products/<int:id>/edit', methods=['GET', 'POST'])
    @login_required
    def edit_product(id):
        product = Product.query.get_or_404(id)
        if request.method == 'POST':
            product.name = request.form['name']
            product.sku = request.form.get('sku')
            product.description = request.form.get('description')
            product.unit = request.form.get('unit', 'adet')
            product.stock_quantity = float(request.form.get('stock_quantity', 0))
            product.min_stock = float(request.form.get('min_stock', 0))
            product.cost_price = float(request.form.get('cost_price', 0))
            product.sell_price = float(request.form.get('sell_price', 0))
            product.category = request.form.get('category')
            product.status = request.form.get('status', 'aktif')
            db.session.commit()
            flash('Ürün güncellendi!', 'success')
            return redirect(url_for('product_detail', id=id))
        return render_template('edit_product.html', product=product)

    @app.route('/products/<int:id>/delete', methods=['POST'])
    @login_required
    def delete_product(id):
        product = Product.query.get_or_404(id)
        db.session.delete(product)
        db.session.commit()
        flash('Ürün silindi!', 'success')
        return redirect(url_for('products'))

    @app.route('/products/export/excel')
    @login_required
    def products_export_excel():
        products = Product.query.all()
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Ürünler'
        headers = ['SKU', 'Ürün Adı', 'Kategori', 'Birim', 'Stok', 'Min Stok', 'Maliyet', 'Satış Fiyatı', 'Durum']
        ws.append(headers)
        for p in products:
            ws.append([p.sku or '', p.name, p.category or '', p.unit, p.stock_quantity, p.min_stock, 
                       p.cost_price, p.sell_price, 'Düşük Stok' if p.is_low_stock else p.status])
        buffer = BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return send_file(buffer, as_attachment=True, download_name=f'urunler_{datetime.now().strftime("%Y%m%d")}.xlsx')

    @app.route('/tasks')
    @login_required
    def tasks():
        status_filter = request.args.get('status', '')
        query = Task.query
        if status_filter:
            query = query.filter(Task.status == status_filter)
        tasks = query.order_by(Task.due_date).all()
        return render_template('tasks.html', tasks=tasks, status_filter=status_filter)

    @app.route('/tasks/add', methods=['GET', 'POST'])
    @login_required
    def add_task():
        if request.method == 'POST':
            # Cift-tiklama korumasi: ayni kullanici, ayni baslikla 30 saniye
            # icinde tekrar gorev eklemeye calisirsa mevcut olana yonlendir.
            recent_cutoff = datetime.utcnow() - timedelta(seconds=30)
            recent_duplicate = Task.query.filter(
                Task.user_id == current_user.id, Task.title == request.form['title'],
                Task.created_at >= recent_cutoff
            ).first()
            if recent_duplicate:
                flash('Bu görev az önce zaten eklendi.', 'info')
                return redirect(url_for('tasks'))

            task = Task(
                title=request.form['title'], description=request.form.get('description'),
                due_date=datetime.strptime(request.form['due_date'], '%Y-%m-%d').date() if request.form.get('due_date') else None,
                due_time=datetime.strptime(request.form['due_time'], '%H:%M').time() if request.form.get('due_time') else None,
                priority=request.form.get('priority', 'orta'),
                category=request.form.get('category'),
                customer_id=int(request.form['customer_id']) if request.form.get('customer_id') else None,
                deal_id=int(request.form['deal_id']) if request.form.get('deal_id') else None,
                user_id=current_user.id
            )
            db.session.add(task)
            db.session.commit()
            flash('Görev eklendi!', 'success')
            return redirect(url_for('tasks'))
        # customers listesi kullanilmiyor - form merkezi musteri arama
        # bilesenini kullaniyor (customer-search.js), deals kucuk bir
        # <select> icin gerekli, o yuzden korundu.
        deals = Deal.query.order_by(Deal.title).all()
        return render_template('add_task.html', deals=deals)

    @app.route('/tasks/<int:id>/complete', methods=['POST'])
    @login_required
    def complete_task(id):
        task = Task.query.get_or_404(id)
        task.status = 'tamamlandi'
        task.completed_at = datetime.utcnow()
        db.session.commit()
        flash('Görev tamamlandı!', 'success')
        return redirect(url_for('tasks'))

    @app.route('/tasks/<int:id>/delete', methods=['POST'])
    @login_required
    def delete_task(id):
        task = Task.query.get_or_404(id)
        db.session.delete(task)
        db.session.commit()
        flash('Görev silindi!', 'success')
        return redirect(url_for('tasks'))

    @app.route('/calendar')
    @login_required
    def calendar():
        year = int(request.args.get('year', datetime.now().year))
        month = int(request.args.get('month', datetime.now().month))
        first_day = date(year, month, 1)
        if month == 12:
            last_day = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = date(year, month + 1, 1) - timedelta(days=1)
        
        tasks = Task.query.filter(Task.due_date.between(first_day, last_day)).all()
        deals_expiring = _apply_deal_visibility(
            Deal.query.filter(Deal.valid_until.between(first_day, last_day))
        ).all()
        
        cal_tasks = {}
        for t in tasks:
            day = t.due_date.day
            if day not in cal_tasks:
                cal_tasks[day] = []
            cal_tasks[day].append(t)
        
        cal_deals = {}
        for d in deals_expiring:
            day = d.valid_until.day
            if day not in cal_deals:
                cal_deals[day] = []
            cal_deals[day].append(d)
        
        return render_template('calendar.html', year=year, month=month, tasks=cal_tasks, deals=cal_deals, first_day=first_day, last_day=last_day, today=datetime.now().date())

    @app.route('/reports')
    @login_required
    def reports():
        # Is 1: bu 4 sorgunun tamami eskiden gorunurluk kisitlamasi hic
        # uygulamiyordu - normal bir kullanici /reports'ta baskalarinin
        # tekliflerinden turetilen istatistikleri gorebiliyordu.
        stage_stats = _apply_deal_visibility(
            db.session.query(Deal.stage, db.func.count(Deal.id), db.func.sum(Deal.value))
        ).group_by(Deal.stage).all()
        recent_deals = _apply_deal_visibility(Deal.query).order_by(Deal.created_at.desc()).limit(5).all()
        top_customers = _apply_deal_visibility(
            db.session.query(Customer, db.func.count(Deal.id).label('deal_count'),
                              db.func.sum(Deal.value).label('total_value')).join(Deal)
        ).group_by(Customer).order_by(db.text('total_value DESC')).limit(5).all()

        production_stats = db.session.query(Production.status, db.func.count(Production.id)).group_by(Production.status).all()

        monthly_sales_rows2 = _apply_deal_visibility(
            db.session.query(
                db.func.to_char(Deal.created_at, 'YYYY-MM').label('month'),
                db.func.sum(Deal.value).label('total')
            ).filter(Deal.stage == 'kazanilan')
        ).group_by(db.func.to_char(Deal.created_at, 'YYYY-MM')).order_by(db.text('1 DESC')).limit(12).all()
        monthly_sales = [(r.month, r.total) for r in monthly_sales_rows2]
        return render_template('reports.html', stage_stats=stage_stats, recent_deals=recent_deals,
                             top_customers=top_customers, production_stats=production_stats, monthly_sales=monthly_sales)

    @app.route('/api/chart-data')
    @login_required
    def chart_data():
        stage_stats = _apply_deal_visibility(
            db.session.query(Deal.stage, db.func.count(Deal.id))
        ).group_by(Deal.stage).all()
        monthly_sales = _apply_deal_visibility(
            db.session.query(
                db.func.to_char(Deal.created_at, 'YYYY-MM').label('month'),
                db.func.sum(Deal.value).label('total')
            ).filter(Deal.stage == 'kazanilan')
        ).group_by(db.func.to_char(Deal.created_at, 'YYYY-MM')).order_by(db.text('1 DESC')).limit(6).all()
        
        return jsonify({
            'stages': [{'stage': s[0], 'count': s[1]} for s in stage_stats],
            'sales': [{'month': s[0], 'total': s[1] or 0} for s in monthly_sales]
        })

    @app.route('/commissions')
    @login_required
    def commissions():
        if current_user.is_admin:
            commissions = Commission.query.order_by(Commission.created_at.desc()).all()
        else:
            commissions = Commission.query.filter_by(user_id=current_user.id).order_by(Commission.created_at.desc()).all()
        
        total_pending = sum(c.amount for c in commissions if c.status == 'odenmedi')
        total_paid = sum(c.amount for c in commissions if c.status == 'odendi')
        
        user_stats = {}
        for c in commissions:
            uid = c.user_id
            if uid not in user_stats:
                user_stats[uid] = {'pending': 0, 'paid': 0, 'count': 0}
            user_stats[uid]['count'] += 1
            if c.status == 'odenmedi':
                user_stats[uid]['pending'] += c.amount
            else:
                user_stats[uid]['paid'] += c.amount
        
        return render_template('commissions.html', commissions=commissions, 
                             total_pending=total_pending, total_paid=total_paid, user_stats=user_stats)

    @app.route('/commissions/<int:id>/pay', methods=['POST'])
    @admin_required
    def pay_commission(id):
        # Bir satiscinin KENDI primini "odendi" isaretleyebilmesi (yalnizca
        # commission.user_id == current_user.id kontroluyle) is mantigi
        # acisindan yanlis olurdu - odeme durumu bir bordro/muhasebe
        # alanidir, sahibi tarafindan degistirilmemeli. Toplu odeme
        # (pay_all_commissions) zaten @admin_required, tutarlilik icin
        # tekil odeme de ayni korumaya alindi.
        commission = Commission.query.get_or_404(id)
        commission.status = 'odendi'
        commission.paid_at = datetime.utcnow()
        db.session.commit()
        flash(f'{commission.amount:,.2f} ₺ prim ödendi olarak işaretlendi.', 'success')
        return redirect(url_for('commissions'))

    @app.route('/commissions/pay-all', methods=['POST'])
    @admin_required
    def pay_all_commissions():
        Commission.query.filter_by(status='odenmedi').update({'status': 'odendi', 'paid_at': datetime.utcnow()})
        db.session.commit()
        flash('Tüm ödenmemiş primler ödendi olarak işaretlendi.', 'success')
        return redirect(url_for('commissions'))

    @app.route('/settings')
    @admin_required
    def settings():
        db_size = db.session.execute(db.text("SELECT pg_database_size(current_database())")).scalar()

        customer_count = Customer.query.count()
        deal_count = Deal.query.count()
        places_config = places_search.get_config()
        company_settings = _get_company_settings()

        return render_template('settings.html', db_size=db_size, customer_count=customer_count,
                                deal_count=deal_count, places_config=places_config,
                                company_settings=company_settings)

    @app.route('/settings/places-toggle', methods=['POST'])
    @admin_required
    def toggle_places_search():
        config = places_search.get_config()
        config.enabled = not config.enabled
        db.session.commit()
        flash(f"Otomatik müşteri arama {'aktif' if config.enabled else 'pasif'} edildi.", 'success')
        return redirect(url_for('settings'))

    @app.route('/settings/company', methods=['POST'])
    @admin_required
    def update_company_settings():
        company_settings = _get_company_settings()
        company_settings.company_name = request.form.get('company_name', '').strip() or 'Lema Ambalaj'
        company_settings.address = request.form.get('address', '').strip() or None
        company_settings.phone = request.form.get('phone', '').strip() or None
        company_settings.fax = request.form.get('fax', '').strip() or None
        company_settings.email = request.form.get('email', '').strip() or None
        company_settings.website = request.form.get('website', '').strip() or None
        company_settings.tax_office = request.form.get('tax_office', '').strip() or None
        company_settings.tax_id = request.form.get('tax_id', '').strip() or None

        logo = request.files.get('logo')
        if logo and logo.filename:
            data = logo.read()
            if len(data) > 2 * 1024 * 1024:
                flash('Logo dosyası çok büyük (maks. 2 MB).', 'danger')
                return redirect(url_for('settings'))
            # Mimetype istemciden geldigi gibi (logo.mimetype) GUVENILMEDEN,
            # PIL'in dosya icerigine bakarak tespit ettigi gercek formattan
            # turetiliyor ve sadece image/jpeg + image/png'ye izin veriliyor -
            # aksi halde saklanip aynen geri servis edilen mimetype uzerinden
            # bir content-type confusion riski olustururdu.
            try:
                from PIL import Image as PILImage
                PILImage.open(BytesIO(data)).verify()
                detected_format = PILImage.open(BytesIO(data)).format
            except Exception:
                flash('Logo dosyası geçerli bir görsel değil.', 'danger')
                return redirect(url_for('settings'))
            mimetype = {'JPEG': 'image/jpeg', 'PNG': 'image/png'}.get(detected_format)
            if not mimetype:
                flash('Logo yalnızca JPEG veya PNG formatında olabilir.', 'danger')
                return redirect(url_for('settings'))
            company_settings.logo_data = data
            company_settings.logo_mimetype = mimetype

        db.session.commit()
        flash('Firma bilgileri güncellendi!', 'success')
        return redirect(url_for('settings'))

    @app.route('/settings/company-logo')
    @admin_required
    def company_logo():
        company_settings = _get_company_settings()
        if not company_settings.logo_data:
            return '', 404
        return send_file(BytesIO(company_settings.logo_data), mimetype=company_settings.logo_mimetype)

    @app.route('/users/<int:id>/commissions')
    @login_required
    def user_commissions(id):
        user = User.query.get_or_404(id)
        if not current_user.is_admin and current_user.id != id:
            flash('Bu sayfaya erişim yetkiniz yok.', 'danger')
            return redirect(url_for('commissions'))
        
        commissions = Commission.query.filter_by(user_id=id).order_by(Commission.created_at.desc()).all()
        total_pending = sum(c.amount for c in commissions if c.status == 'odenmedi')
        total_paid = sum(c.amount for c in commissions if c.status == 'odendi')
        
        return render_template('user_commissions.html', user=user, commissions=commissions,
                             total_pending=total_pending, total_paid=total_paid)

    # Fatura / İrsaliye Routes
    @app.route('/invoices')
    @login_required
    def invoices():
        search = request.args.get('search', '')
        type_filter = request.args.get('type', '')
        page = request.args.get('page', 1, type=int)
        query = Invoice.query
        if search:
            query = query.join(Customer).filter(db.or_(
                Customer.first_name.ilike(f'%{search}%'),
                Customer.last_name.ilike(f'%{search}%'),
                Customer.company_name.ilike(f'%{search}%')
            ))
        if type_filter:
            query = query.filter(Invoice.type == type_filter)
        # Performans: sablon her satirda inv.customer.display_name VE (fatura
        # tipi icin) inv.payment_status'u (self.payments okur) kullaniyor -
        # eager load olmadan bu, sayfa basina 2N ekstra round-trip'e mal
        # oluyordu (50 satirlik bir sayfada +~17 sorgu olculdu).
        query = query.options(joinedload(Invoice.customer), joinedload(Invoice.payments))
        pagination = query.order_by(Invoice.created_at.desc()).paginate(page=page, per_page=50, error_out=False)
        invoices = pagination.items
        return render_template('invoices.html', invoices=invoices, search=search, type_filter=type_filter, pagination=pagination)

    @app.route('/invoices/<int:id>')
    @login_required
    def invoice_detail(id):
        invoice = Invoice.query.get_or_404(id)
        owner_id = invoice.owner_id
        if owner_id is not None and not current_user.is_admin and owner_id != current_user.id:
            flash('Bu faturayı görüntüleme yetkiniz yok.', 'danger')
            return redirect(url_for('invoices'))

        # Is 3: satir satir kumulatif kalan bakiye tablosu. Ayri bir hesaplama
        # kaynagi ACILMIYOR - dogrudan invoice.total (Cari Hesap Ozeti'nin de
        # kullandigi ayni Invoice.total) ve invoice.payments'daki (status=
        # 'odendi') gercek Payment kayitlari (paid_amount/remaining_amount
        # property'leriyle AYNI kaynak) uzerinden, sirayla kumulatif olarak
        # hesaplanir.
        ledger_rows = []
        if invoice.type == 'fatura':
            running_balance = invoice.total
            ledger_rows.append({
                'date': invoice.date,
                'description': 'Fatura tutarı',
                'badge': None,
                'amount': None,
                'balance': running_balance
            })
            odenen_payments = sorted(
                [p for p in invoice.payments if p.status == 'odendi'],
                key=lambda p: (p.payment_date or invoice.date, p.created_at)
            )
            for p in odenen_payments:
                running_balance -= p.amount
                badge = 'Ön Ödeme' if (p.notes and p.notes.strip().startswith('Ön Ödeme')) else 'Kısmi Ödeme'
                ledger_rows.append({
                    'date': p.payment_date,
                    'description': badge,
                    'badge': badge,
                    'amount': p.amount,
                    'balance': running_balance
                })

        return render_template('invoice_detail.html', invoice=invoice, ledger_rows=ledger_rows)

    @app.route('/invoices/<int:id>/edit', methods=['GET', 'POST'])
    @login_required
    def edit_invoice(id):
        """Is 8 madde 2-3-4: faturanin kalemlerini sonradan degistirme.
        Musteri/teklif baglantisi degistirilemez - SADECE kalemler. Kaydedilince
        invoice.calculate_totals() ile toplam yeniden hesaplanir; Cari Hesap
        Ozeti/Musteri Detayi bakiyeleri zaten CANLI (Invoice.total'dan)
        hesaplandigi icin ayrica bir 'yeniden hesaplama' adimina gerek yok -
        bir sonraki goruntulemede otomatik guncel gorunur. 'Son duzenleyen'
        basit logu (updated_by_user_id/updated_at) burada yazilir."""
        invoice = Invoice.query.get_or_404(id)
        owner_id = invoice.owner_id
        if owner_id is not None and not current_user.is_admin and owner_id != current_user.id:
            flash('Bu faturayı düzenleme yetkiniz yok.', 'danger')
            return redirect(url_for('invoice_detail', id=id))

        if request.method == 'POST':
            if 'desc_0' not in request.form:
                flash('Fatura en az bir kalem içermelidir.', 'danger')
                return redirect(url_for('edit_invoice', id=id))
            try:
                InvoiceItem.query.filter_by(invoice_id=invoice.id).delete()
                i = 0
                while f'desc_{i}' in request.form:
                    qty = float(request.form.get(f'qty_{i}', 0))
                    price = float(request.form.get(f'price_{i}', 0))
                    item = InvoiceItem(
                        invoice_id=invoice.id,
                        description=request.form[f'desc_{i}'],
                        quantity=qty,
                        unit=request.form.get(f'unit_{i}', 'adet'),
                        unit_price=price,
                        total_price=qty * price
                    )
                    db.session.add(item)
                    i += 1
                db.session.flush()
                invoice.calculate_totals()
                invoice.updated_by_user_id = current_user.id
                invoice.updated_at = datetime.utcnow()
                db.session.commit()
            except Exception:
                db.session.rollback()
                flash('Fatura düzenlenirken bir hata oluştu, hiçbir değişiklik kaydedilmedi.', 'danger')
                return redirect(url_for('edit_invoice', id=id))

            flash(f'{invoice.display_no} güncellendi!', 'success')
            return redirect(url_for('invoice_detail', id=id))

        return render_template('edit_invoice.html', invoice=invoice)

    @app.route('/invoices/<int:id>/pdf')
    @login_required
    def invoice_pdf(id):
        invoice = Invoice.query.get_or_404(id)
        owner_id = invoice.owner_id
        if owner_id is not None and not current_user.is_admin and owner_id != current_user.id:
            flash('Bu faturayı indirme yetkiniz yok.', 'danger')
            return redirect(url_for('invoices'))
        pdf = generate_invoice_pdf(invoice)
        return send_file(pdf, as_attachment=True, download_name=f'{invoice.display_no}.pdf')

    @app.route('/deals/<int:id>/create-invoice', methods=['GET', 'POST'])
    @login_required
    def create_invoice_from_deal(id):
        deal = Deal.query.get_or_404(id)
        if not current_user.is_admin and deal.user_id != current_user.id:
            flash('Bu teklif için fatura oluşturma yetkiniz yok.', 'danger')
            return redirect(url_for('deals'))

        if request.method == 'POST':
            inv_type = request.form.get('type', 'fatura')

            # Is 3: eksik musteri bilgisi (firma unvani/vergi no) ayni formdan
            # tamamlanabiliyor - fatura olusturmadan once musteri kaydina yazilir.
            new_company_name = request.form.get('customer_company_name', '').strip()
            new_tax_id = request.form.get('customer_tax_id', '').strip()
            if new_company_name:
                deal.customer.company_name = new_company_name
            if new_tax_id:
                deal.customer.tax_id = new_tax_id

            # Cift-tiklama korumasi: ayni teklif+tur icin birkac saniye once
            # zaten bir Invoice olusmussa (gercek veride bu sekilde ayni
            # teklife 4 kez mukerrer fatura kesildigi tespit edildi) yeni
            # kayit acmak yerine mevcut olana yonlendir.
            recent_cutoff = datetime.utcnow() - timedelta(seconds=30)
            recent_duplicate = Invoice.query.filter(
                Invoice.deal_id == deal.id, Invoice.type == inv_type, Invoice.created_at >= recent_cutoff
            ).first()
            if recent_duplicate:
                flash(f'{recent_duplicate.display_no} az önce zaten oluşturuldu.', 'info')
                return redirect(url_for('invoice_detail', id=recent_duplicate.id))

            try:
                invoice = Invoice(
                    invoice_no=_next_invoice_no(),
                    type=inv_type,
                    deal_id=deal.id,
                    customer_id=deal.customer_id,
                    user_id=current_user.id,
                    date=datetime.now().date(),
                    vat_rate=deal.vat_rate,
                    notes=request.form.get('notes', '')
                )
                db.session.add(invoice)
                db.session.flush()

                # Teklif kalemlerini kopyala, manuel girilen kg/adet ile güncelle
                i = 0
                while f'desc_{i}' in request.form:
                    qty = float(request.form.get(f'qty_{i}', 0))
                    price = float(request.form.get(f'price_{i}', 0))
                    item = InvoiceItem(
                        invoice_id=invoice.id,
                        description=request.form[f'desc_{i}'],
                        quantity=qty,
                        unit=request.form.get(f'unit_{i}', 'adet'),
                        unit_price=price,
                        total_price=qty * price
                    )
                    db.session.add(item)
                    i += 1

                db.session.flush()
                invoice.calculate_totals()

                # On odeme (avans) uzlastirmasi: bu teklife bagli, henuz hicbir
                # faturaya baglanmamis Payment kayitlari isaretlenmisse, yeni
                # faturaya baglanir (artik invoice.paid_amount'a dahil olurlar).
                unlinked_payments = Payment.query.filter_by(deal_id=deal.id, invoice_id=None).all()
                for payment in unlinked_payments:
                    if request.form.get(f'link_payment_{payment.id}'):
                        payment.invoice_id = invoice.id

                # Is 2: formda "On Odeme Alindi" isaretlenmisse ilk Payment
                # otomatik olusur.
                _create_prepayment_if_requested(invoice, request.form, current_user.id)

                db.session.commit()
            except Exception:
                db.session.rollback()
                flash('Fatura/irsaliye oluşturulurken bir hata oluştu, hiçbir değişiklik kaydedilmedi. Girdiğiniz bilgileri kontrol edip tekrar deneyin.', 'danger')
                return redirect(url_for('create_invoice_from_deal', id=id))

            flash(f'{invoice.display_no} - {inv_type} başarıyla oluşturuldu!', 'success')
            return redirect(url_for('invoice_detail', id=invoice.id))

        unlinked_payments = Payment.query.filter_by(deal_id=deal.id, invoice_id=None).all()
        return render_template('create_invoice_from_deal.html', deal=deal, unlinked_payments=unlinked_payments, today=datetime.now().date())

    @app.route('/invoices/add', methods=['GET', 'POST'])
    @login_required
    def add_invoice_standalone():
        """Is 2: hicbir teklif olmadan, bagimsiz bir Fatura (dahili takip
        kaydi) olusturur. create_invoice_from_deal ile ayni kalem/on odeme
        mantigini paylasir, tek fark musteri+kalemlerin serbestce (deal'den
        kopyalanmadan) girilmesi."""
        if request.method == 'POST':
            customer_id = request.form.get('customer_id')
            if not customer_id:
                flash('Lütfen bir müşteri seçin.', 'danger')
                return render_template('add_invoice.html', today=datetime.now().date())

            new_company_name = request.form.get('customer_company_name', '').strip()
            new_tax_id = request.form.get('customer_tax_id', '').strip()
            customer = Customer.query.get_or_404(int(customer_id))
            if new_company_name:
                customer.company_name = new_company_name
            if new_tax_id:
                customer.tax_id = new_tax_id

            # Cift-tiklama korumasi: bkz. create_invoice_from_deal - ayni
            # mantik, burada deal_id olmadigi icin customer_id uzerinden.
            recent_cutoff = datetime.utcnow() - timedelta(seconds=30)
            recent_duplicate = Invoice.query.filter(
                Invoice.customer_id == customer.id, Invoice.deal_id.is_(None), Invoice.created_at >= recent_cutoff
            ).first()
            if recent_duplicate:
                flash(f'{recent_duplicate.display_no} az önce zaten oluşturuldu.', 'info')
                return redirect(url_for('invoice_detail', id=recent_duplicate.id))

            try:
                invoice = Invoice(
                    invoice_no=_next_invoice_no(),
                    type='fatura',
                    deal_id=None,
                    customer_id=customer.id,
                    user_id=current_user.id,
                    date=datetime.now().date(),
                    vat_rate=float(request.form.get('vat_rate', 20)),
                    notes=request.form.get('notes', '')
                )
                db.session.add(invoice)
                db.session.flush()

                i = 0
                while f'desc_{i}' in request.form:
                    qty = float(request.form.get(f'qty_{i}', 0))
                    price = float(request.form.get(f'price_{i}', 0))
                    item = InvoiceItem(
                        invoice_id=invoice.id,
                        description=request.form[f'desc_{i}'],
                        quantity=qty,
                        unit=request.form.get(f'unit_{i}', 'adet'),
                        unit_price=price,
                        total_price=qty * price
                    )
                    db.session.add(item)
                    i += 1

                db.session.flush()
                invoice.calculate_totals()

                _create_prepayment_if_requested(invoice, request.form, current_user.id)

                db.session.commit()
            except Exception:
                db.session.rollback()
                flash('Fatura oluşturulurken bir hata oluştu, hiçbir değişiklik kaydedilmedi. Girdiğiniz bilgileri kontrol edip tekrar deneyin.', 'danger')
                return redirect(url_for('add_invoice_standalone'))

            flash(f'{invoice.display_no} başarıyla oluşturuldu!', 'success')
            return redirect(url_for('invoice_detail', id=invoice.id))

        # Is 4: Cari Hesap Ozeti'ndeki "Fatura Olustur" butonundan geldiyse
        # musteri onceden secili gelsin diye.
        prefill_customer = None
        prefill_customer_id = request.args.get('customer_id')
        if prefill_customer_id:
            prefill_customer = Customer.query.get(int(prefill_customer_id))
        return render_template('add_invoice.html', today=datetime.now().date(), prefill_customer=prefill_customer)

    @app.route('/visits')
    @login_required
    def visits():
        visits = CustomerVisit.query.order_by(CustomerVisit.visit_date.desc()).all()
        return render_template('visits.html', visits=visits)

    @app.route('/visits/add', methods=['GET', 'POST'])
    @login_required
    def add_visit():
        if request.method == 'POST':
            customer_id = int(request.form['customer_id'])

            # Cift-tiklama korumasi: ayni musteri icin 30 saniye icinde
            # tekrar ziyaret eklemeye calisilirsa mevcut olana yonlendir.
            recent_cutoff = datetime.utcnow() - timedelta(seconds=30)
            recent_duplicate = CustomerVisit.query.filter(
                CustomerVisit.customer_id == customer_id, CustomerVisit.created_at >= recent_cutoff
            ).first()
            if recent_duplicate:
                flash('Bu ziyaret az önce zaten kaydedildi.', 'info')
                return redirect(url_for('visits'))

            visit = CustomerVisit(
                customer_id=customer_id,
                user_id=current_user.id,
                visit_date=datetime.strptime(request.form['visit_date'], '%Y-%m-%d').date() if request.form.get('visit_date') else datetime.now().date(),
                notes=request.form.get('notes'),
                visit_type=request.form.get('visit_type', 'ziyaret')
            )
            db.session.add(visit)
            db.session.commit()
            flash('Ziyaret kaydedildi!', 'success')
            return redirect(url_for('visits'))
        
        # Telefon ile hızlı müşteri bulma
        phone = request.args.get('phone', '')
        customer = None
        if phone:
            customer = Customer.query.filter_by(phone=phone).first()
        
        # Not: customers listesi kullanilmiyor - form merkezi musteri arama
        # bilesenini kullaniyor (customer-search.js).
        return render_template('add_visit.html', phone=phone, customer=customer)
    
    @app.route('/api/customers/by-phone')
    @login_required
    def get_customer_by_phone():
        phone = request.args.get('phone', '')
        customer = Customer.query.filter_by(phone=phone).first()
        if customer:
            return jsonify({
                'id': customer.id,
                'name': customer.display_name,
                'phone': customer.phone or '',
                'email': customer.email or ''
            })
        return jsonify(None)

    @app.route('/customers/import/vcf', methods=['GET', 'POST'])
    @login_required
    def import_customers_vcf():
        if request.method == 'POST':
            if 'file' not in request.files:
                flash('Dosya seçilmedi.', 'danger')
                return redirect(url_for('customers'))
            file = request.files['file']
            if file.filename == '':
                flash('Dosya seçilmedi.', 'danger')
                return redirect(url_for('customers'))
            
            try:
                content = file.read().decode('utf-8', errors='ignore')
                lines = content.split('\n')
                
                added = 0
                skipped = 0
                errors = []
                
                count = 0
                current_customer = {}
                next_musteri_n = _musteri_no_max()

                for line in lines:
                    line = line.strip()
                    if line.startswith('BEGIN:VCARD'):
                        current_customer = {}
                    elif line.startswith('END:VCARD'):
                        if current_customer.get('name') or current_customer.get('phone'):
                            name_parts = current_customer.get('name', '').split()
                            first_name = name_parts[0] if name_parts else None
                            last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else None

                            # Aynı isimde müşteri var mı kontrol et
                            existing = Customer.query.filter_by(first_name=first_name, last_name=last_name).first()
                            if existing:
                                skipped += 1
                                current_customer = {}
                                continue

                            next_musteri_n += 1
                            customer = Customer(
                                musteri_no=f'M-{next_musteri_n:04d}',
                                first_name=first_name,
                                last_name=last_name,
                                phone=current_customer.get('phone'),
                                email=current_customer.get('email'),
                                company_name=current_customer.get('org'),
                                owner_user_id=current_user.id
                            )
                            db.session.add(customer)
                            added += 1
                        current_customer = {}
                    elif line.startswith('FN:'):
                        current_customer['name'] = line[3:].strip()
                    elif line.startswith('N:'):
                        parts = line[2:].strip().split(';')
                        if len(parts) >= 2:
                            current_customer['last_name'] = parts[0].strip()
                            current_customer['first_name'] = parts[1].strip()
                    elif 'TEL' in line and ':' in line:
                        phone = line.split(':', 1)[1].strip()
                        if phone:
                            current_customer['phone'] = phone
                    elif 'EMAIL' in line and ':' in line:
                        email = line.split(':', 1)[1].strip()
                        if email:
                            current_customer['email'] = email
                    elif 'ORG' in line and ':' in line:
                        org = line.split(':', 1)[1].strip()
                        if org:
                            current_customer['org'] = org
                
                db.session.commit()
                msg = f'{added} kişi eklendi.'
                if skipped:
                    msg += f' {skipped} kişi (aynı isim) atlandı.'
                flash(msg, 'success' if added > 0 else 'info')
            except Exception as e:
                flash(f'VCF dosyası okuma hatası: {str(e)}', 'danger')
            
            return redirect(url_for('customers'))
        return render_template('import_vcf.html')

    # Günlük Rapor Routes
    @app.route('/daily-reports')
    @login_required
    def daily_reports():
        reports = DailyReport.query.order_by(DailyReport.report_date.desc(), DailyReport.created_at.desc()).all()

        dates = sorted({r.report_date for r in reports}, reverse=True)
        day_cards = []
        for d in dates:
            day_reports = [r for r in reports if r.report_date == d]

            deal_count = Deal.query.filter(Deal.deal_date == d).count()
            avg_deal_value = db.session.query(db.func.avg(Deal.value)).filter(Deal.deal_date == d).scalar() or 0
            shipment_count = Shipment.query.filter(Shipment.ship_date == d).count()

            payments_day = Payment.query.filter(Payment.payment_date == d).all()
            payment_count = len(payments_day)
            payment_total = sum(p.amount for p in payments_day)

            pending_price_count = sum(1 for r in day_reports if r.status == 'fiyat_verilecek')

            top_customer_row = db.session.query(
                Customer.first_name, Customer.last_name, Customer.company_name,
                db.func.count(Deal.id).label('cnt')
            ).join(Deal, Deal.customer_id == Customer.id).filter(Deal.deal_date == d) \
             .group_by(Customer.id, Customer.first_name, Customer.last_name, Customer.company_name) \
             .order_by(db.text('cnt DESC')).first()
            top_customer = None
            if top_customer_row:
                top_customer = top_customer_row.company_name or f"{top_customer_row.first_name} {top_customer_row.last_name}"

            day_cards.append({
                'date': d,
                'reports': day_reports,
                'deal_count': deal_count,
                'avg_deal_value': avg_deal_value,
                'shipment_count': shipment_count,
                'payment_count': payment_count,
                'payment_total': payment_total,
                'pending_price_count': pending_price_count,
                'top_customer': top_customer,
            })

        return render_template('daily_reports.html', day_cards=day_cards)

    @app.route('/daily-reports/add', methods=['GET', 'POST'])
    @login_required
    def add_daily_report():
        today = datetime.now().date()
        
        if request.method == 'POST':
            report_date_str = request.form.get('report_date', '')
            report_date = datetime.strptime(report_date_str, '%Y-%m-%d').date() if report_date_str else today
            
            customer_names = request.form.getlist('customer_name[]')
            phones = request.form.getlist('phone[]')
            notes_list = request.form.getlist('notes[]')

            if not customer_names or not any(customer_names):
                flash('En az bir müşteri adı gereklidir.', 'danger')
                return render_template('add_daily_report.html', today=today)

            # Is 4: musteri secimi artik ZORUNLU - merkezi arama bileseninden
            # (allowQuickAdd ile) gelen gercek bir customer_id olmadan hicbir
            # DailyReport olusturulmuyor. Eskiden customer_id bos birakilip
            # sadece serbest metin isimle kayit girilebiliyordu; bu kayitlar
            # _last_contact_subquery()'nin customer_id filtresi yuzunden
            # 60 gunluk takip dongusunu hic sifirlamiyordu (musteriyle
            # gorusulmus olsa bile sistemde "gorusulmemis" gorunmeye devam
            # ediyordu). Telefonla otomatik esleme/yeni musteri olusturma da
            # kaldirildi - bu artik quick-add akisinin (/api/customers/
            # quick-add) sorumlulugu, iki ayri musteri-olusturma yolu olmasin.
            customer_ids = request.form.getlist('customer_id[]')
            missing_customer_rows = []
            for i, customer_name in enumerate(customer_names):
                customer_name = customer_name.strip()
                if not customer_name:
                    continue
                customer_id_raw = customer_ids[i].strip() if i < len(customer_ids) else ''
                if not customer_id_raw:
                    missing_customer_rows.append(customer_name)
            if missing_customer_rows:
                flash(
                    'Şu müşteriler için listeden seçim yapılmamış: ' + ', '.join(missing_customer_rows) +
                    '. Lütfen arama sonuçlarından bir müşteri seçin veya "Yeni müşteri olarak ekle" ile ekleyin.',
                    'danger'
                )
                return render_template('add_daily_report.html', today=today)

            try:
                reports_added = 0
                for i, customer_name in enumerate(customer_names):
                    customer_name = customer_name.strip()
                    if not customer_name:
                        continue

                    phone = phones[i].strip() if i < len(phones) else ''
                    notes = notes_list[i].strip() if i < len(notes_list) else ''
                    statuses = request.form.getlist('status[]')
                    status = statuses[i].strip() if i < len(statuses) and statuses[i] else 'takip_edilecek'
                    customer_id = int(customer_ids[i])

                    report = DailyReport(
                        report_date=report_date,
                        customer_name=customer_name,
                        phone=phone or None,
                        notes=notes,
                        status=status,
                        user_id=current_user.id,
                        customer_id=customer_id
                    )
                    db.session.add(report)
                    reports_added += 1

                db.session.commit()
            except Exception:
                db.session.rollback()
                flash('Günlük rapor eklenirken bir hata oluştu, hiçbir değişiklik kaydedilmedi.', 'danger')
                return redirect(url_for('add_daily_report'))

            flash(f'{reports_added} adet günlük rapor eklendi!', 'success')
            return redirect(url_for('daily_reports'))
        
        return render_template('add_daily_report.html', today=today)

    @app.route('/daily-reports/by-date/<date_str>')
    @login_required
    def daily_reports_by_date(date_str):
        try:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            target_date = datetime.now().date()
        return redirect(url_for('daily_reports') + f'#gun-{target_date.strftime("%Y%m%d")}')

    @app.route('/daily-reports/<int:id>/delete', methods=['POST'])
    @login_required
    def delete_daily_report(id):
        report = DailyReport.query.get_or_404(id)
        db.session.delete(report)
        db.session.commit()
        flash('Günlük rapor silindi!', 'success')
        return redirect(url_for('daily_reports'))

    # Ödeme Routes
    @app.route('/payments')
    @login_required
    def payments():
        customer_search = request.args.get('customer_search', '')
        status_filter = request.args.get('status', '')
        
        query = Payment.query
        
        if customer_search:
            query = query.join(Customer).filter(
                db.or_(
                    Customer.first_name.ilike(f'%{customer_search}%'),
                    Customer.last_name.ilike(f'%{customer_search}%'),
                    Customer.company_name.ilike(f'%{customer_search}%')
                )
            )
        
        if status_filter:
            query = query.filter(Payment.status == status_filter)
        
        # Performans: sablon her satirda payment.customer/.invoice/.deal
        # okuyor - eager load olmadan N+1'e mal oluyordu.
        query = query.options(joinedload(Payment.customer), joinedload(Payment.invoice), joinedload(Payment.deal))
        payments = query.order_by(Payment.payment_date.desc()).all()

        # Tahsilat ozeti - sadece 'fatura' tipi belgeler uzerinden (irsaliyenin
        # tahsilati olmaz). Invoice.paid_amount/remaining_amount Payment.status
        # == 'odendi' olan kayitlar uzerinden hesaplanir (bkz. models.py).
        # Performans: paid_amount self.payments okuyor - eager load olmadan
        # her fatura icin ayri bir SELECT (N+1) tetikliyordu.
        all_invoices = Invoice.query.filter_by(type='fatura').options(joinedload(Invoice.payments)).all()
        total_invoiced = sum(inv.total for inv in all_invoices)
        total_collected = sum(inv.paid_amount for inv in all_invoices)
        total_outstanding = total_invoiced - total_collected
        pending_invoices = sorted(
            (inv for inv in all_invoices if inv.remaining_amount > 0.01),
            key=lambda inv: inv.date
        )

        # Is C: mevcut odeme kayitlarindan bagimsiz, ileriye donuk bir
        # "beklenen toplam tahsilat" ozeti - acik/bekleyen tekliflerin
        # (henuz kazanilmamis, kaybedilmemis, revize edilmemis) toplam
        # degeri + faturalarin kalan bakiyesi.
        open_deals = Deal.query.filter(Deal.stage.notin_(['kazanilan', 'kaybedilen', 'revize'])).all()
        total_open_deals_value = sum(d.value for d in open_deals)
        expected_total_receivable = total_open_deals_value + total_outstanding

        return render_template('payments.html', payments=payments,
                             customer_search=customer_search, status_filter=status_filter,
                             total_invoiced=total_invoiced, total_collected=total_collected,
                             total_outstanding=total_outstanding, pending_invoices=pending_invoices,
                             total_open_deals_value=total_open_deals_value,
                             expected_total_receivable=expected_total_receivable)

    @app.route('/payments/add', methods=['GET', 'POST'])
    @login_required
    def add_payment():
        if request.method == 'POST':
            customer_id = int(request.form['customer_id'])
            amount = float(request.form['amount'])
            payment_date = datetime.strptime(request.form['payment_date'], '%Y-%m-%d').date() if request.form.get('payment_date') else datetime.now().date()

            # Is 3: mukerrer odeme koruma - ayni musteri+tutar+tarihte, son
            # birkac saniye icinde eklenmis bir odeme varsa (kullanicinin
            # yanlislikla iki kez "Kaydet"e basmasi gibi) direkt kaydetmek
            # yerine onay istenir. confirm_duplicate=1 geldiyse kullanici
            # zaten uyariyi gorup bilerek devam etmis demektir.
            if not request.form.get('confirm_duplicate'):
                recent_cutoff = datetime.utcnow() - timedelta(seconds=30)
                recent_duplicate = Payment.query.filter(
                    Payment.customer_id == customer_id,
                    Payment.amount == amount,
                    Payment.payment_date == payment_date,
                    Payment.created_at >= recent_cutoff
                ).first()
                if recent_duplicate:
                    prefill_customer = Customer.query.get(customer_id)
                    flash(
                        f'Bu ödeme az önce eklenmiş görünüyor ({prefill_customer.display_name if prefill_customer else ""} - '
                        f'{amount:,.2f} ₺, {payment_date.strftime("%d.%m.%Y")}). Yine de eklemek istiyorsanız '
                        f'aşağıdaki "Yine de Ekle" butonuna basın.', 'warning'
                    )
                    return render_template('add_payment.html', today=datetime.now().date(),
                                            prefill_customer=prefill_customer, prefill_invoice=None,
                                            duplicate_warning=True, form_data=request.form)

            kur_orani_raw = request.form.get('kur_orani', '').strip()
            payment = Payment(
                customer_id=customer_id,
                invoice_id=int(request.form['invoice_id']) if request.form.get('invoice_id') else None,
                deal_id=int(request.form['deal_id']) if request.form.get('deal_id') else None,
                amount=amount,
                payment_date=payment_date,
                payment_method=request.form.get('payment_method'),
                reference_no=request.form.get('reference_no'),
                notes=request.form.get('notes'),
                status=request.form.get('status', 'odendi'),
                kur_orani=float(kur_orani_raw) if kur_orani_raw else None,
                user_id=current_user.id
            )
            db.session.add(payment)
            db.session.flush()

            # Odeme 'odendi' ise Cari Hesap Ekstresi'ne otomatik 'alacak' kaydi
            # dus - payment_id ile iliskili, odeme silinince bu da silinir.
            if payment.status == 'odendi':
                if payment.invoice_id:
                    ref = payment.invoice.display_no
                elif payment.deal_id:
                    ref = f'{payment.deal.display_no} (Ön Ödeme)'
                else:
                    ref = 'Genel'
                statement = CustomerStatement(
                    customer_id=payment.customer_id, payment_id=payment.id, type='alacak',
                    amount=payment.amount, description=f'Tahsilat: {ref}'
                )
                db.session.add(statement)

            db.session.commit()
            flash('Ödeme kaydedildi!', 'success')
            return redirect(url_for('payments'))

        prefill_invoice_id = request.args.get('invoice_id', type=int)
        prefill_invoice = Invoice.query.get(prefill_invoice_id) if prefill_invoice_id else None
        prefill_customer_id = request.args.get('customer_id', type=int) or (prefill_invoice.customer_id if prefill_invoice else None)
        prefill_customer = Customer.query.get(prefill_customer_id) if prefill_customer_id else None

        return render_template('add_payment.html', today=datetime.now().date(),
                             prefill_customer=prefill_customer, prefill_invoice=prefill_invoice)

    @app.route('/payments/<int:id>/delete', methods=['POST'])
    @login_required
    def delete_payment(id):
        payment = Payment.query.get_or_404(id)
        if not current_user.is_admin and payment.user_id != current_user.id:
            flash('Bu ödeme kaydını silme yetkiniz yok.', 'danger')
            return redirect(url_for('payments'))
        CustomerStatement.query.filter_by(payment_id=payment.id).delete()
        db.session.delete(payment)
        db.session.commit()
        flash('Ödeme kaydı silindi!', 'success')
        return redirect(url_for('payments'))

    @app.route('/api/customer-payments/<int:customer_id>')
    @login_required
    def get_customer_payments(customer_id):
        payments = Payment.query.filter_by(customer_id=customer_id).order_by(Payment.payment_date.desc()).all()
        result = []
        for p in payments:
            result.append({
                'id': p.id,
                'amount': p.amount,
                'date': p.payment_date.strftime('%d.%m.%Y'),
                'method': p.payment_method or '-',
                'status': p.status,
                'invoice_no': p.invoice.display_no if p.invoice else '-'
            })
        return jsonify(result)

    @app.route('/api/customers/<int:customer_id>/open-records')
    @login_required
    def customer_open_records(customer_id):
        """Odeme formunda musteri secilince, o musteriye baglanabilecek acik
        kayitlari doner: kalan bakiyesi olan faturalar ve henuz faturaya
        donusturulmemis kazanilan teklifler (on odeme/avans hedefi)."""
        invoices = Invoice.query.filter_by(customer_id=customer_id, type='fatura').all()
        open_invoices = [{
            'id': inv.id, 'display_no': inv.display_no,
            'total': inv.total, 'remaining': inv.remaining_amount,
            'para_birimi': inv.deal.para_birimi if inv.deal else 'TRY'
        } for inv in invoices if inv.remaining_amount > 0.01]

        invoiced_deal_ids = {inv.deal_id for inv in invoices}
        won_deals = Deal.query.filter_by(customer_id=customer_id, stage='kazanilan').all()
        open_deals = [{
            'id': d.id, 'display_no': d.display_no,
            'value': d.value, 'pesinat': d.pesinat or '', 'para_birimi': d.para_birimi
        } for d in won_deals if d.id not in invoiced_deal_ids]

        return jsonify({'invoices': open_invoices, 'deals': open_deals})

    @app.route('/potential-customers')
    @login_required
    def potential_customers():
        search = request.args.get('search', '')
        status_filter = request.args.get('status', '')
        city_filter = request.args.get('city', '')
        sector_filter = request.args.get('sector', '')
        product_filter = request.args.get('product', '')
        page = request.args.get('page', 1, type=int)

        query = PotentialCustomer.query
        if search:
            query = query.filter(db.or_(
                PotentialCustomer.company_name.ilike(f'%{search}%'),
                PotentialCustomer.phone.ilike(f'%{search}%')
            ))
        if status_filter:
            query = query.filter(PotentialCustomer.status == status_filter)
        if city_filter:
            query = query.filter(PotentialCustomer.city == city_filter)
        if sector_filter:
            query = query.filter(PotentialCustomer.sector == sector_filter)
        if product_filter:
            query = query.filter(PotentialCustomer.interested_products.ilike(f'%{product_filter}%'))

        pagination = query.order_by(PotentialCustomer.created_at.desc()).paginate(page=page, per_page=50, error_out=False)
        potentials = pagination.items

        cities = [c[0] for c in db.session.query(PotentialCustomer.city).filter(
            PotentialCustomer.city.isnot(None), PotentialCustomer.city != ''
        ).distinct().order_by(PotentialCustomer.city).all()]

        # Performans: eskiden 4 ayri SUM sorgusuyla hesaplanan today_used/
        # today_new/month/last_90_days artik combined_usage_stats() ile TEK
        # round-trip'te geliyor (bkz. denetim, /potential-customers 10->7 sorgu).
        places_config = places_search.get_config()
        usage = places_search.combined_usage_stats()
        places_stats = {
            'status': places_search.get_status(places_config),
            'today_used': usage['today_used'],
            'today_limit': places_search.DAILY_REQUEST_LIMIT,
            'today_new': usage['today_new'],
            'month': usage['month'],
            'last_90_days': usage['last_90_days'],
            'recent_logs': PlacesSearchLog.query.order_by(PlacesSearchLog.run_at.desc()).limit(5).all(),
        }

        return render_template('potential_customers.html', potentials=potentials, pagination=pagination,
                                search=search, status_filter=status_filter, city_filter=city_filter,
                                sector_filter=sector_filter, product_filter=product_filter, cities=cities,
                                sectors=PotentialCustomer.SECTORS, products=PotentialCustomer.PRODUCTS,
                                statuses=PotentialCustomer.STATUSES, places_stats=places_stats,
                                all_cities=places_search.ALL_CITIES, search_sectors=places_search.SEARCH_SECTORS)

    @app.route('/potential-customers/export/excel')
    @login_required
    def potential_customers_export_excel():
        from openpyxl.styles import Font, PatternFill, Alignment

        search = request.args.get('search', '')
        status_filter = request.args.get('status', '')
        city_filter = request.args.get('city', '')
        sector_filter = request.args.get('sector', '')
        product_filter = request.args.get('product', '')

        query = PotentialCustomer.query
        if search:
            query = query.filter(db.or_(
                PotentialCustomer.company_name.ilike(f'%{search}%'),
                PotentialCustomer.phone.ilike(f'%{search}%')
            ))
        if status_filter:
            query = query.filter(PotentialCustomer.status == status_filter)
        if city_filter:
            query = query.filter(PotentialCustomer.city == city_filter)
        if sector_filter:
            query = query.filter(PotentialCustomer.sector == sector_filter)
        if product_filter:
            query = query.filter(PotentialCustomer.interested_products.ilike(f'%{product_filter}%'))
        items = query.order_by(PotentialCustomer.created_at.desc()).all()

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Potansiyel Müşteriler'
        headers = ['Firma Adı', 'Telefon', 'Adres', 'Şehir', 'Sektör', 'İlgilenilen Ürünler',
                   'Durum', 'Web Sitesi', 'Kaynak', 'Eklenme Tarihi']
        ws.append(headers)
        header_fill = PatternFill(start_color='1a252f', end_color='1a252f', fill_type='solid')
        header_font = Font(bold=True, color='FFFFFF')
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal='center')

        for pc in items:
            website = ''
            if pc.notes and 'Website:' in pc.notes:
                website = pc.notes.split('Website:', 1)[1].strip()
                if website == '-':
                    website = ''
            ws.append([
                pc.company_name, pc.phone or '', pc.address or '', pc.city or '', pc.sector or '',
                ', '.join(pc.product_list), pc.status or '', website, pc.source or '',
                pc.created_at.strftime('%d.%m.%Y') if pc.created_at else ''
            ])

        for col_cells in ws.columns:
            length = max(len(str(c.value)) if c.value else 0 for c in col_cells)
            ws.column_dimensions[col_cells[0].column_letter].width = min(max(length + 2, 12), 50)

        buffer = BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return send_file(buffer, as_attachment=True,
                          download_name=f'potansiyel_musteriler_{datetime.now().strftime("%Y%m%d")}.xlsx')

    @app.route('/potential-customers/search-now', methods=['POST'])
    @login_required
    def search_places_now():
        selected_cities = request.form.getlist('cities')
        selected_sectors = request.form.getlist('sectors')
        result = places_search.run_batch_search(selected_cities, selected_sectors, triggered_by='manuel')

        if result.get('skipped'):
            flash(result.get('reason', 'Arama yapılamadı.'), 'warning')
        else:
            msg = (f"Arama tamamlandı: {result['combos_run']} kombinasyon tarandı, "
                   f"{result['total_results']} sonuç bulundu, {result['total_new']} yeni firma eklendi "
                   f"({result['total_requests']} istek kullanıldı).")
            if result['combos_skipped']:
                msg += f" {result['combos_skipped']} kombinasyon günlük kota nedeniyle atlandı."
            if result['errors']:
                msg += f" {len(result['errors'])} kombinasyonda hata oluştu."
            flash(msg, 'warning' if result['errors'] or result['combos_skipped'] else 'success')
        return redirect(url_for('potential_customers'))

    @app.route('/potential-customers/add', methods=['GET', 'POST'])
    @login_required
    def add_potential_customer():
        if request.method == 'POST':
            pc = PotentialCustomer(
                company_name=request.form.get('company_name', '').strip(),
                phone=request.form.get('phone'),
                address=request.form.get('address'),
                city=request.form.get('city'),
                sector=request.form.get('sector'),
                interested_products=','.join(request.form.getlist('products')),
                source=request.form.get('source', 'Elle'),
                status=request.form.get('status', 'Aranacak'),
                notes=request.form.get('notes'),
            )
            db.session.add(pc)
            db.session.commit()
            flash('Potansiyel müşteri eklendi!', 'success')
            return redirect(url_for('potential_customers'))
        return render_template('add_potential_customer.html', potential=None,
                                sectors=PotentialCustomer.SECTORS, products=PotentialCustomer.PRODUCTS,
                                sources=PotentialCustomer.SOURCES, statuses=PotentialCustomer.STATUSES)

    @app.route('/potential-customers/<int:id>/edit', methods=['GET', 'POST'])
    @login_required
    def edit_potential_customer(id):
        pc = PotentialCustomer.query.get_or_404(id)
        if request.method == 'POST':
            pc.company_name = request.form.get('company_name', '').strip()
            pc.phone = request.form.get('phone')
            pc.address = request.form.get('address')
            pc.city = request.form.get('city')
            pc.sector = request.form.get('sector')
            pc.interested_products = ','.join(request.form.getlist('products'))
            pc.source = request.form.get('source', 'Elle')
            pc.status = request.form.get('status', 'Aranacak')
            pc.notes = request.form.get('notes')
            db.session.commit()
            flash('Potansiyel müşteri güncellendi!', 'success')
            return redirect(url_for('potential_customers'))
        return render_template('add_potential_customer.html', potential=pc,
                                sectors=PotentialCustomer.SECTORS, products=PotentialCustomer.PRODUCTS,
                                sources=PotentialCustomer.SOURCES, statuses=PotentialCustomer.STATUSES)

    @app.route('/potential-customers/<int:id>/delete', methods=['POST'])
    @login_required
    def delete_potential_customer(id):
        pc = PotentialCustomer.query.get_or_404(id)
        db.session.delete(pc)
        db.session.commit()
        flash('Potansiyel müşteri silindi!', 'success')
        return redirect(url_for('potential_customers'))

    @app.route('/potential-customers/<int:id>/convert', methods=['POST'])
    @login_required
    def convert_potential_customer(id):
        pc = PotentialCustomer.query.get_or_404(id)
        if pc.converted_customer_id:
            flash('Bu potansiyel müşteri zaten dönüştürülmüş.', 'warning')
            return redirect(url_for('potential_customers'))

        # Customer modelinde sehir/sektor/ilgilenilen urun/kaynak icin ayri
        # alan yok - onceden bu bilgiler donusturme sirasinda sessizce
        # kayboluyordu. Customer.notes'a ekleniyor, boylece en azindan
        # okunabilir sekilde korunuyorlar.
        extra_bits = []
        if pc.city:
            extra_bits.append(f'Şehir: {pc.city}')
        if pc.sector:
            extra_bits.append(f'Sektör: {pc.sector}')
        if pc.interested_products:
            extra_bits.append(f'İlgilendiği Ürünler: {pc.interested_products}')
        if pc.source:
            extra_bits.append(f'Kaynak: {pc.source}')
        extra_info = (' | '.join(extra_bits) + '\n') if extra_bits else ''
        customer = Customer(
            musteri_no=_next_musteri_no(),
            company_name=pc.company_name,
            phone=pc.phone,
            address=pc.address,
            notes=f'Potansiyel müşteriden dönüştürüldü. {extra_info}{pc.notes or ""}'.strip(),
            status='aktif',
            owner_user_id=current_user.id,
        )
        db.session.add(customer)
        db.session.flush()

        pc.converted_customer_id = customer.id
        pc.status = 'Müşteriye Dönüştürüldü'
        db.session.commit()
        flash(f'"{pc.company_name}" müşteriye dönüştürüldü!', 'success')
        return redirect(url_for('potential_customers'))
