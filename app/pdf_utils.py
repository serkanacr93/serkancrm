from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak, Flowable
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas as _PDFCanvas
from io import BytesIO
import os
import re
from datetime import datetime
from app.models import format_price_precise

# PDF ciktilarinda temizlenecek samimi/gundelik hitaplar (Bey/Usta/Hoca
# bilincli olarak HARIC tutuldu - bunlar Turkce'de resmi/saygi ifadesi
# sayilir ve is belgesinde kullanilmasi uygundur).
_INFORMAL_ADDRESS_RE = re.compile(r'\b(abi|amca|abla|baba|day[ıi])\b', re.IGNORECASE)


def _clean_for_pdf(text):
    """Musteri adi/firma adindan sadece PDF gorunumu icin samimi hitaplari
    temizler. Veritabanindaki gercek kayda dokunmaz."""
    if not text:
        return text
    cleaned = _INFORMAL_ADDRESS_RE.sub('', text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned or text

def _sanitize_pdf_free_text(text):
    """Serbest metin alanlarinda (Aciklama/Not kutulari) kullanicinin elle
    yazdigi ' TL' isareti (U+20BA) Vera fontunda glif olarak bulunmuyor -
    PDF'te bozuk/kare karakter olarak cikiyordu. PDF'in geri kalaninda zaten
    tutarli sekilde 'TL' metni kullanildigi icin (bkz. Ara Toplam/KDV/Toplam
    kutulari) ayni donusum burada da uygulanir."""
    if not text:
        return text
    return text.replace('₺', 'TL')

def _draw_watermark(canvas, doc, text):
    """Is 2 (yeniden tasarim): eskiden sayfa ortasini kaplayan buyuk kontur
    filigran KALDIRILDI - ana icerik alani artik TAMAMEN temiz. Bunun
    yerine SADECE iki noktada, dikkat cekmeyen bir marka izi birakilir:
    (1) sag ust kosede, 35 derece egik, koyu dolgu renkli kucuk bir damga/
    etiket (resmi belge/cek tarzi) - sayfanin ust kenar bosluguna (topMargin
    1.3cm) sigacak sekilde konumlandirilir, flowable icerikle (TEKLIF
    basligi vb.) CAKISMAZ. (2) sayfanin en altinda (bottomMargin 1.3cm
    bosluguna sigan), ince/soluk, tekrarlayan mikro-metin seridi.
    onFirstPage/onLaterPages callback'i olarak cagrilir - flowable icerik
    cizilmeden ONCE calisir, bu yuzden damga/serit icerigin ALTINDA kalir."""
    if not text:
        return
    stamp_color = colors.HexColor('#1a252f')

    # ---- (1) Sag ust kose damgasi ----
    canvas.saveState()
    canvas.translate(A4[0] - 2.1*cm, A4[1] - 0.7*cm)
    canvas.rotate(35)
    canvas.setFillColor(stamp_color)
    canvas.setFont('Vera-Bold', 9)
    canvas.drawCentredString(0, 0, text)
    canvas.restoreState()

    # ---- (2) Alt serit mikro-metin ----
    canvas.saveState()
    canvas.setFont('Vera', 6)
    canvas.setFillColor(colors.HexColor('#c9c9c9'))
    unit = f'{text}  •  '
    unit_w = canvas.stringWidth(unit, 'Vera', 6)
    available_w = A4[0] - 1.0*cm
    repeats = max(1, int(available_w // unit_w) + 1) if unit_w > 0 else 1
    canvas.drawString(0.5*cm, 0.5*cm, unit * repeats)
    canvas.restoreState()

def register_fonts():
    font_dir = os.path.join(os.path.dirname(__file__), 'static', 'fonts')
    pdfmetrics.registerFont(TTFont('Vera', os.path.join(font_dir, 'Vera.ttf')))
    pdfmetrics.registerFont(TTFont('Vera-Bold', os.path.join(font_dir, 'VeraBd.ttf')))
    pdfmetrics.registerFont(TTFont('Vera-Italic', os.path.join(font_dir, 'VeraIt.ttf')))
    pdfmetrics.registerFont(TTFont('Vera-BoldItalic', os.path.join(font_dir, 'VeraBI.ttf')))
    pdfmetrics.registerFontFamily(
        'Vera', normal='Vera', bold='Vera-Bold',
        italic='Vera-Italic', boldItalic='Vera-BoldItalic',
    )

register_fonts()

def _payment_method_checkboxes(text_style):
    """Nakit/KK icin cizilmis kutucuklar dondurur (Vera fontunda Unicode
    checkbox glifi (U+2610) bulunmuyor, o yuzden kucuk BOX kenarli hucreler
    kullanilir). Is 4: Cek/Senet secenekleri kaldirildi - artik kullanilmiyor."""
    labels = ['Nakit', 'KK']
    row = []
    widths = []
    for label in labels:
        row.append('')
        widths.append(0.35*cm)
        row.append(Paragraph(label, text_style))
        widths.append(1.4*cm)
    table = Table([row], colWidths=widths)
    box_cols = [i for i in range(0, len(row), 2)]
    style = [
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 1),
        ('RIGHTPADDING', (0, 0), (-1, -1), 1),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]
    for c in box_cols:
        style.append(('BOX', (c, 0), (c, 0), 0.75, colors.black))
    table.setStyle(TableStyle(style))
    return table

def _get_company_settings_for_pdf():
    """PDF ciktilari icin firma bilgilerini dondurur - CompanySettings kaydi
    yoksa (henuz Ayarlar'dan doldurulmamissa) None yerine bos/varsayilan
    degerli bir obje dondurur, boylece PDF hicbir zaman hata vermez."""
    from app.models import CompanySettings
    company = CompanySettings.query.get(1)
    if not company:
        company = CompanySettings(company_name='Lema Ambalaj')
    return company


# ===== 2026-10-13: Teklif PDF yeni tasarim - yardimci fonksiyonlar =====

_SAYI_BIRLER = ['', 'bir', 'iki', 'üç', 'dört', 'beş', 'altı', 'yedi', 'sekiz', 'dokuz']
_SAYI_ONLAR = ['', 'on', 'yirmi', 'otuz', 'kırk', 'elli', 'altmış', 'yetmiş', 'seksen', 'doksan']
_SAYI_GRUPLAR = ['', 'bin', 'milyon', 'milyar', 'trilyon']


def _uc_hane_yaziyla(num):
    """0-999 arasi bir sayiyi Turkce yaziyla - ic yardimci, disaridan
    cagrilmaz (sifir icin bos string doner, ust fonksiyon 'bir' onekini
    'bin' grubunda bastirmak icin boyle kurulmustur)."""
    yuzler, kalan = divmod(num, 100)
    onlar, birler = divmod(kalan, 10)
    parts = []
    if yuzler:
        if yuzler > 1:
            parts.append(_SAYI_BIRLER[yuzler])
        parts.append('yüz')
    if onlar:
        parts.append(_SAYI_ONLAR[onlar])
    if birler:
        parts.append(_SAYI_BIRLER[birler])
    return ' '.join(parts)


def _sayi_yaziyla_tam(n):
    """Negatif olmayan bir tam sayiyi Turkce yaziyla yazar (0 -> 'sıfır').
    '1000' -> 'bin' ('bir bin' DEGIL), '1001' -> 'bin bir' - Turkce'de 'bin'
    grubu 'bir' onekini almaz, diger gruplar (milyon/milyar) alir."""
    n = int(n)
    if n == 0:
        return 'sıfır'
    gruplar = []
    temp = n
    while temp > 0:
        gruplar.append(temp % 1000)
        temp //= 1000
    words = []
    for i in reversed(range(len(gruplar))):
        g = gruplar[i]
        if g == 0:
            continue
        scale = _SAYI_GRUPLAR[i]
        if scale == 'bin' and g == 1:
            words.append('bin')
        else:
            words.append(_uc_hane_yaziyla(g))
            if scale:
                words.append(scale)
    return ' '.join(words)


def tutar_yaziyla(value):
    """87648.0 -> 'Seksen sekiz bin Türk Lirası' gibi tam tutarlar icin
    kurus eklenmez; kurus varsa '... Türk Lirası ... Kuruş' seklinde
    eklenir. Yalniz ilk harf buyutulur (mockup: 'Seksen yedi bin ...')."""
    value = round(float(value), 2)
    tl = int(value)
    kurus = round((value - tl) * 100)
    if kurus >= 100:
        tl += 1
        kurus = 0
    text = _sayi_yaziyla_tam(tl) + ' Türk Lirası'
    if kurus:
        text += ' ' + _sayi_yaziyla_tam(kurus) + ' Kuruş'
    return text[0].upper() + text[1:]


def _money_tr(value):
    """Yeni tasarimin GENEL para formati: Turkce ayrac (bin: nokta, ondalik:
    virgul), DAIMA 2 ondalik (87648 -> '87.648,00') - klasigin
    format_price_precise()'inden FARKLI olarak kirpma/yuvarlama yapar
    (hesaplanan - kur carpimi gibi - degerlerde float gurultusunu
    gizlemek icin; klasik tasarimi ETKILEMEZ, SADECE _generate_deal_pdf_yeni
    icinde kullanilir)."""
    value = round(float(value), 2)
    sign = '-' if value < 0 else ''
    value = abs(value)
    s = f'{value:,.2f}'
    s = s.replace(',', '§').replace('.', ',').replace('§', '.')
    return sign + s


def _miktar_tr(value):
    """Is 2c (2026-10-14): miktar - tam sayiysa ondalik YOK + Turkce bin
    ayraci ('1.500 kg'), kusuratliysa virgullu + gereksiz sifirlar
    KIRPILIR ('12,5 kg' - '12,50' DEGIL)."""
    value = float(value)
    if value == int(value):
        return f'{int(value):,}'.replace(',', '.')
    s = f'{value:,.2f}'
    int_part, dec_part = s.split('.')
    dec_part = dec_part.rstrip('0') or '0'
    result = f'{int_part}.{dec_part}'
    return result.replace(',', '§').replace('.', ',').replace('§', '.')


def _birim_fiyat_tr(value):
    """Is 2c: birim fiyat - en az 2, gerekirse (yuvarlama kaybi olmadan
    tam temsil icin) en fazla 4 ondalik; fazlalik sifirlar KIRPILIR."""
    value = float(value)
    s = f'{value:.4f}'
    int_part, dec_part = s.split('.')
    while len(dec_part) > 2 and dec_part.endswith('0'):
        dec_part = dec_part[:-1]
    int_part_fmt = f'{int(int_part):,}'.replace(',', '.')
    return f'{int_part_fmt},{dec_part}'


# ===== PAKET B Is B5 (2026-10-14): Ingilizce teklif PDF'i - sayi/etiket
# yardimcilari. SADECE _generate_deal_pdf_yeni(lang='en') tarafindan
# kullanilir - TR yolunu (yukaridaki _money_tr/_miktar_tr/_birim_fiyat_tr)
# ve Klasik tasarimi HIC ETKILEMEZ. =====

def _money_en(value):
    """EN para formati: bin ayraci virgul, ondalik nokta, DAIMA 2 ondalik
    (1700 -> '1,700.00') - _money_tr ile AYNI yuvarlama, sadece ayrac ters."""
    value = round(float(value), 2)
    sign = '-' if value < 0 else ''
    return sign + f'{abs(value):,.2f}'


def _miktar_en(value):
    """EN miktar formati - _miktar_tr ile AYNI mantik (tam sayida ondalik
    yok, kusuratli olanda gereksiz sifirlar kirpilir), sadece ayraclar EN."""
    value = float(value)
    if value == int(value):
        return f'{int(value):,}'
    s = f'{value:,.2f}'
    int_part, dec_part = s.split('.')
    dec_part = dec_part.rstrip('0') or '0'
    return f'{int_part}.{dec_part}'


def _birim_fiyat_en(value):
    """EN birim fiyat formati - _birim_fiyat_tr ile AYNI hassasiyet kurali
    (en az 2, en fazla 4 ondalik), sadece ayraclar EN."""
    value = float(value)
    s = f'{value:.4f}'
    int_part, dec_part = s.split('.')
    while len(dec_part) > 2 and dec_part.endswith('0'):
        dec_part = dec_part[:-1]
    return f'{int(int_part):,}.{dec_part}'


_UNIT_LABELS_EN = {'adet': 'pcs', 'kg': 'kg', 'mt': 'm', 'lt': 'L', 'm2': 'm²', 'set': 'set'}

_PAYMENT_METHOD_LABELS_EN = {
    'havale': 'Bank transfer', 'nakit': 'Cash', 'cek': 'Cheque',
    'senet': 'Promissory note', 'kredi_karti': 'Credit card',
}


def _unit_en(unit):
    return _UNIT_LABELS_EN.get(unit, unit)


def _kagit_cinsi_farkli_mi(description, kagit_cinsi):
    """Is 2a: kagit cinsi degeri urun adiyla AYNIYSA (buyuk/kucuk harf ve
    bosluk farki haric) o satir basilmaz - tekrar olmasin diye."""
    if not kagit_cinsi:
        return False
    norm = lambda s: ' '.join((s or '').split()).casefold()
    return norm(description) != norm(kagit_cinsi)


def _iban_grupla(iban):
    """Is B1 (2026-10-14): IBAN'i 4'erli gruplar halinde gosterir
    ('TR330006...' -> 'TR33 0006 1005 1978 ...') - saklanan deger
    DEGISMEZ, sadece PDF gorunumu icin bosluklar normalize edilip
    yeniden gruplanir."""
    compact = (iban or '').replace(' ', '').upper()
    return ' '.join(compact[i:i+4] for i in range(0, len(compact), 4))


def _logo_for_pdf_yeni(logo_data):
    """Logonun neredeyse-beyaz pikselleri (R,G,B hepsi >= 244) seffaf yapar
    ve bos kenarlari kirpar - SADECE bellekte, company.logo_data'daki
    gercek veri hic degismez. Basarisiz olursa None doner (cagiran taraf
    logoyu atlar, PDF kirilmaz)."""
    try:
        from PIL import Image as PILImage
        img = PILImage.open(BytesIO(logo_data)).convert('RGBA')
        pixels = img.load()
        w, h = img.size
        for y in range(h):
            for x in range(w):
                r, g, b, a = pixels[x, y]
                if r >= 244 and g >= 244 and b >= 244:
                    pixels[x, y] = (r, g, b, 0)
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)
        out = BytesIO()
        img.save(out, format='PNG')
        out.seek(0)
        return out
    except Exception:
        return None


def _kur_adi_yeni():
    """tcmb.py fetch_tcmb_rate() ForexSelling kullaniyor -> 'döviz satış'.
    tcmb.py'nin kendi kaynagina bagli - elle ayri bir sabit TUTULMUYOR,
    burada SADECE goruntuleme amacli ayni ad tekrarlanir."""
    return 'döviz satış'


def _kur_notu_yeni(deal, kur_tarihi_str, lang='tr'):
    """Dovizli kalem varsa kur notu metnini doner, yoksa None.

    PAKET B Is B4 (Kalem bazli doviz, Asama 1) - deal.para_birimi 'TRY' olsa
    da kalemlerde (item.para_birimi) USD/EUR kullanilmis olabilir (KARAR:
    bu, teklif seviyesi dovizden (asagidaki ESKI dal) AYRI ve ONUNLA AYNI
    teklifte BIRLIKTE kullanilmaz - bkz. app/models.py Deal.calculate_totals).
    Bu durumda kullanilan para birimlerinin HEPSI icin (1 veya 2) tek notta
    listelenir. Eski (teklif seviyesi) dal DEGISTIRILMEDI.

    PAKET B Is B5 - lang='en' ise AYNI mantik, Ingilizce metin."""
    if deal.para_birimi == 'TRY':
        kullanilan = []
        if deal.kur_usd and any(i.para_birimi == 'USD' for i in deal.items):
            kullanilan.append(f"1 USD = {deal.kur_usd:,.2f} TRY" if lang == 'en' else f"1 USD = {deal.kur_usd:,.2f} TL")
        if deal.kur_eur and any(i.para_birimi == 'EUR' for i in deal.items):
            kullanilan.append(f"1 EUR = {deal.kur_eur:,.2f} TRY" if lang == 'en' else f"1 EUR = {deal.kur_eur:,.2f} TL")
        if not kullanilan:
            return None
        tarih_str = deal.kur_tarihi.strftime('%d.%m.%Y') if deal.kur_tarihi else kur_tarihi_str
        if lang == 'en':
            kaynak = 'TCMB' if deal.kur_turu == 'tcmb' else 'the stated'
            return (
                f"The TRY equivalent of foreign-currency items was calculated using the {kaynak} rate "
                f"dated {tarih_str} ({' · '.join(kullanilan)}). The grand total is in TRY."
            )
        kaynak = 'TCMB' if deal.kur_turu == 'tcmb' else 'belirtilen'
        return (
            f"Dövizli kalemlerin TL karşılığı {tarih_str} tarihli {kaynak} kur ile hesaplanmıştır "
            f"({' · '.join(kullanilan)}). Genel toplam TL'dir."
        )
    if not deal.kullanilan_kur:
        return None
    if lang == 'en':
        return (
            f"The exchange rate is the TCMB {_kur_adi_yeni()} rate dated {kur_tarihi_str} "
            f"(1 {deal.para_birimi} = {deal.kullanilan_kur:,.2f} TRY). Foreign-currency items are "
            f"converted to TRY at the TCMB rate on the payment date."
        )
    return (
        f"Döviz kuru {kur_tarihi_str} tarihli TCMB {_kur_adi_yeni()} kurudur "
        f"(1 {deal.para_birimi} = {deal.kullanilan_kur:,.2f} TL). Döviz kalemler "
        f"ödeme günü TCMB kuruyla TL'ye çevrilir."
    )


_DEFAULT_TERMS_YENI = [
    "Teklif {gecerlilik} tarihine kadar geçerlidir.",
    "{kur_notu}",
    "Üretim, numune / baskı provası onayından sonra başlar.",
    "Miktarlarda ±%10 üretim toleransı vardır.",
    "Teslim yeri: Konya fabrika teslim.",
]

# PAKET B Is B5 - varsayilan sartlarin Ingilizce karsiligi. SADECE
# company.teklif_sartlari BOS ise kullanilir (KARAR: kullanicinin kendi
# yazdigi ozel sartlar - genelde Turkce - lang='en' olsa da CEVRILMEZ,
# oldugu gibi basilir; bkz. _build_terms_yeni).
_DEFAULT_TERMS_YENI_EN = [
    "This quotation is valid until {gecerlilik}.",
    "{kur_notu}",
    "Production starts after sample / print proof approval.",
    "A ±10% production tolerance applies to quantities.",
    "Delivery point: Ex-works, Konya factory.",
]


def _build_terms_yeni(deal, company, lang='tr'):
    """Sirket ayarlarindaki teklif_sartlari (serbest metin, satir basina
    bir madde) doluysa onu, yoksa _DEFAULT_TERMS_YENI'yi kullanir.
    {gecerlilik}/{kur_notu} yer tutucularini doldurur; kur_notu yoksa
    (TRY teklif) o satiri tamamen ATAR (numaralar kayar).

    PAKET B Is B5 - lang='en' ise varsayilan sartlar _DEFAULT_TERMS_YENI_EN
    olur VE tarih biçimi degismez (dd.mm.yyyy, TR/EN farki yok). KARAR:
    company.teklif_sartlari DOLUYSA (kullanicinin kendi, genelde Turkce
    metni) lang ne olursa olsun OLDUGU GIBI basilir - otomatik ceviri
    YAPILMAZ (yanlis/riskli ceviri ihtimaline karsi guvenli varsayilan)."""
    gecerlilik_str = deal.valid_until.strftime('%d.%m.%Y') if deal.valid_until else '-'
    kur_tarihi = deal.deal_date or deal.created_at.date()
    kur_tarihi_str = kur_tarihi.strftime('%d.%m.%Y') if kur_tarihi else '-'
    kur_notu = _kur_notu_yeni(deal, kur_tarihi_str, lang=lang)

    if company.teklif_sartlari and company.teklif_sartlari.strip():
        raw_lines = [l.strip() for l in company.teklif_sartlari.splitlines() if l.strip()]
        has_kur_placeholder = any('{kur_notu}' in l for l in raw_lines)
        if kur_notu and not has_kur_placeholder:
            raw_lines.append('{kur_notu}')
    else:
        raw_lines = list(_DEFAULT_TERMS_YENI_EN if lang == 'en' else _DEFAULT_TERMS_YENI)

    result = []
    for line in raw_lines:
        if '{kur_notu}' in line:
            if not kur_notu:
                continue
            line = line.replace('{kur_notu}', kur_notu)
        line = line.replace('{gecerlilik}', gecerlilik_str)
        result.append(line)
    return result


def generate_deal_pdf(deal, lang='tr'):
    """2026-10-13 (Teklif PDF yeni tasarim): CompanySettings.teklif_pdf_tasarim
    ayarina gore 'yeni' (varsayilan, NULL dahil) veya 'klasik' tasarimi
    cagiran dispatcher. Klasik secilirse eski PDF BIREBIR AYNI cikar -
    _generate_deal_pdf_klasik() asagida, eski generate_deal_pdf() govdesinin
    degistirilmemis halidir.

    PAKET B Is B5 (2026-10-14): 'lang' parametresi - 'tr' (varsayilan,
    eski cagrilar/ default) veya 'en'. KARAR: Ingilizce SADECE yeni
    tasarimda var - Klasik tasarim hic degistirilmedi, lang='en' ile
    cagrilsa bile klasik seciliyse YOK SAYILIR (Klasik hep TR basar)."""
    company = _get_company_settings_for_pdf()
    if company.teklif_pdf_tasarim == 'klasik':
        return _generate_deal_pdf_klasik(deal)
    return _generate_deal_pdf_yeni(deal, lang=lang if lang in ('tr', 'en') else 'tr')


def _generate_deal_pdf_klasik(deal):
    """Siparis Sozlesmesi formatinda teklif PDF'i. Fiyat/urun kalemleri
    tekliften gelir. Vade/Pesinat/Bakiye Deal alanlarindan geliyor (bos ise
    noktali cizgi kalir). Kagit Cinsi/Boy/En/Renk/Teslim Tarihi sutunlari
    DealItem'dan gelir, doldurulmamis olan alanlar '-' ile gosterilir.
    AÇIKLAMA kutusu deal.notes'tan doldurulur."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.3*cm, leftMargin=1.3*cm, topMargin=1.3*cm, bottomMargin=1.3*cm)

    company = _get_company_settings_for_pdf()

    styles = getSampleStyleSheet()
    normal = ParagraphStyle('TurkishStyle', parent=styles['Normal'], fontName='Vera', fontSize=8.5, leading=11)
    small = ParagraphStyle('SmallStyle', parent=normal, fontSize=7.5, leading=10)
    box_heading = ParagraphStyle('BoxHeading', parent=normal, fontName='Vera-Bold', fontSize=8.5)
    company_name_style = ParagraphStyle('CompanyName', parent=normal, fontName='Vera-Bold', fontSize=16, leading=19)
    doc_title_style = ParagraphStyle('DocTitle', parent=normal, fontName='Vera-Bold', fontSize=20, leading=24, alignment=2, spaceAfter=3)
    doc_meta_style = ParagraphStyle('DocMeta', parent=normal, fontName='Vera-Bold', fontSize=9, leading=13, alignment=2)
    terms_style = ParagraphStyle('TermsStyle', parent=normal, fontSize=7.5, leading=10)
    table_header_style = ParagraphStyle('TableHeader', parent=normal, fontName='Vera-Bold', fontSize=7, leading=8.5,
                                         textColor=colors.white, alignment=1)

    elements = []

    # ===== UST BASLIK: firma bilgisi (sol) + TEKLIF basligi (sag) =====
    company_text_block = [Paragraph(company.company_name or 'Lema Ambalaj', company_name_style)]
    if company.address:
        company_text_block.append(Paragraph(company.address.replace('\n', '<br/>'), small))
    contact_bits = []
    if company.phone:
        contact_bits.append(f"Tel: {company.phone}")
    if company.fax:
        contact_bits.append(f"Faks: {company.fax}")
    if contact_bits:
        company_text_block.append(Paragraph(' | '.join(contact_bits), small))
    contact_bits2 = []
    if company.email:
        contact_bits2.append(company.email)
    if company.website:
        contact_bits2.append(company.website)
    if contact_bits2:
        company_text_block.append(Paragraph(' | '.join(contact_bits2), small))
    if company.tax_office or company.tax_id:
        company_text_block.append(Paragraph(f"V.D.: {company.tax_office or '-'}  V.No: {company.tax_id or '-'}", small))

    logo_img = None
    if company.logo_data:
        try:
            from PIL import Image as PILImage
            PILImage.open(BytesIO(company.logo_data)).verify()
            # Logo, firma adinin SOLUNDA, dikey ortalanmis olarak gosteriliyor
            # (eskiden ustte ayri bir kutuda, kucuk boyuttaydi). Boyut ~%45
            # buyutuldu (3.5x1.8cm -> 5.1x2.6cm) ve metin blogunun toplam
            # yuksekligine yakinlasmasi hedeflendi.
            logo_img = Image(BytesIO(company.logo_data), width=5.1*cm, height=2.6*cm, kind='proportional')
        except Exception:
            logo_img = None

    if logo_img is not None:
        logo_row_table = Table([[logo_img, company_text_block]], colWidths=[5.1*cm, 5.9*cm])
        logo_row_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (0, 0), 0),
            # logo ile metin arasinda 10-15pt bosluk
            ('RIGHTPADDING', (0, 0), (0, 0), 12),
            ('LEFTPADDING', (1, 0), (1, 0), 0),
            ('RIGHTPADDING', (1, 0), (1, 0), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        left_cell = [logo_row_table]
    else:
        left_cell = company_text_block

    right_cell = [
        Paragraph("TEKLİF", doc_title_style),
        Spacer(1, 4*mm),
        Paragraph(f"Teklif No: {deal.display_no}", doc_meta_style),
        Paragraph(f"Tarih: {deal.deal_date.strftime('%d.%m.%Y') if deal.deal_date else deal.created_at.strftime('%d.%m.%Y')}", doc_meta_style),
    ]

    header_table = Table([[left_cell, right_cell]], colWidths=[11*cm, 6.2*cm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 4*mm))
    elements.append(Table([['']], colWidths=[17.2*cm], style=[('LINEBELOW', (0, 0), (-1, -1), 1, colors.HexColor('#1a252f'))]))
    elements.append(Spacer(1, 4*mm))

    # ===== MUSTERI BILGILERI + ODEME SEKLI kutulari =====
    customer = deal.customer
    customer_person_name = f"{_clean_for_pdf(customer.first_name)} {_clean_for_pdf(customer.last_name)}".strip()

    customer_box = [
        Paragraph("MÜŞTERİYE AİT BİLGİLER", box_heading),
        Spacer(1, 1.5*mm),
        Paragraph(f"<b>Sayın:</b> {customer_person_name or '-'}", normal),
    ]
    if customer.company_name:
        customer_box.append(Paragraph(f"<b>Firma:</b> {_clean_for_pdf(customer.company_name)}", normal))
    customer_box.append(Paragraph(f"<b>Adres:</b> {customer.company_address or customer.address or '-'}", normal))
    customer_box.append(Paragraph(f"<b>V.D.:</b> {customer.tax_office or '-'}  <b>V.No:</b> {customer.tax_id or '-'}", normal))

    dots = "..................."
    payment_box = [
        Paragraph("ÖDEME ŞEKLİ", box_heading),
        Spacer(1, 1.5*mm),
        Paragraph(f"<b>Vade (Gün):</b> {deal.vade_gun_metni or dots}", normal),
        Paragraph(f"<b>Peşinat:</b> {deal.pesinat or dots}", normal),
        Paragraph(f"<b>Bakiye Ödemesi:</b> {deal.bakiye_odemesi or dots}", normal),
        Spacer(1, 2*mm),
        _payment_method_checkboxes(normal),
    ]
    # B7 (2026-10-06): isteğe bağlı Peşinat/Bakiye tarihi - sadece doluysa
    # PDF'e eklenir (boşsa eski görünüm hiç değişmez).
    if deal.pesinat_tarihi:
        payment_box.append(Paragraph(f"<b>Peşinat Tarihi:</b> {deal.pesinat_tarihi.strftime('%d.%m.%Y')}", normal))
    if deal.bakiye_tarihi:
        payment_box.append(Paragraph(f"<b>Bakiye Tarihi:</b> {deal.bakiye_tarihi.strftime('%d.%m.%Y')}", normal))

    info_table = Table([[customer_box, payment_box]], colWidths=[8.6*cm, 8.6*cm])
    info_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOX', (0, 0), (0, 0), 0.75, colors.grey),
        ('BOX', (1, 0), (1, 0), 0.75, colors.grey),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 5*mm))

    # ===== URUN TABLOSU =====
    # Kagit Cinsi/Boy/En/Renk/Teslim Tarihi DealItem'da yapisal olarak
    # tutuluyor (teklif formundan doldurulur, hepsi opsiyonel) - doluysa
    # gercek deger, bossa '-' gosterilir. Kalemin kendi teslim tarihi
    # girilmemisse teklifin genel beklenen kapanis tarihine dusulur.
    deal_delivery_fallback = deal.expected_close.strftime('%d.%m.%Y') if deal.expected_close else '-'
    # Coklu Para Birimi - TRY icin Vera fontunda ₺ glifi olmadigindan
    # (bkz. _sanitize_pdf_free_text) tutarlar hep 'TL' metniyle gosterilir;
    # EUR/USD sembolleri Vera'da mevcut, dogrudan kullanilabilir.
    para_birimi_text = 'TL' if deal.para_birimi == 'TRY' else deal.para_birimi_sembol
    if deal.items:
        table_small = ParagraphStyle('TableSmall', parent=small, fontSize=8, leading=10)
        table_header_style_normal = ParagraphStyle('TableHeaderNormal', parent=table_header_style, fontSize=8, leading=10)
        # Kagit Cinsi/Boy/En/Renk onceden DUZ METIN olarak ekleniyordu - Table
        # hucrelerinde duz metin SARMAZ (sadece Paragraph flowable'lar sarar),
        # bu yuzden uzun bir deger hucre sinirini asip yandaki sutune biniyordu.
        # Paragraph'a cevirip dar sutunlara uygun kucuk/ortali bir stil verildi.
        table_narrow = ParagraphStyle('TableNarrow', parent=small, fontSize=7.5, leading=9, alignment=1)
        col_widths = [3.8*cm, 1.9*cm, 1.6*cm, 1.6*cm, 1.4*cm, 1.3*cm, 1.6*cm, 1.3*cm, 1.8*cm, 1.8*cm]
        headers = ['Ürün Cinsi', 'Kağıt Cinsi', 'Boy', 'En', 'Körük', 'Renk', 'Miktar', 'Birim', f'Fiyat\n({para_birimi_text})', 'Teslim\nTarihi']
        data = [[Paragraph(h.replace('\n', '<br/>'), table_header_style_normal) for h in headers]]

        def _pdf_cell_text(value):
            # Paragraph icerigi (duz metnin aksine) XML/HTML olarak
            # ayristirilir - kullanicinin elle girdigi bir '<'/'>'/'&' PDF
            # olusturmayi kirmasin diye kacis karakterleri uygulanir.
            from xml.sax.saxutils import escape
            cleaned = _sanitize_pdf_free_text(value)
            return escape(cleaned) if cleaned else '-'

        for item in deal.items:
            item_delivery_str = item.teslim_tarihi.strftime('%d.%m.%Y') if item.teslim_tarihi else deal_delivery_fallback
            data.append([
                Paragraph(_pdf_cell_text(item.description), table_small),
                Paragraph(_pdf_cell_text(item.kagit_cinsi), table_narrow),
                Paragraph(_pdf_cell_text(item.boy), table_narrow),
                Paragraph(_pdf_cell_text(item.en), table_narrow),
                Paragraph(_pdf_cell_text(item.korugu), table_narrow),
                Paragraph(_pdf_cell_text(item.renk), table_narrow),
                f"{item.quantity:.2f}",
                item.unit,
                format_price_precise(item.unit_price),
                item_delivery_str
            ])
        table = Table(data, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a252f')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 1), (-1, -1), 'Vera'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
            ('TOPPADDING', (0, 0), (-1, 0), 5),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 5),
        ]))
        elements.append(table)

        elements.append(Spacer(1, 2*mm))
        totals_data = [
            ['Ara Toplam:', f"{deal.subtotal:,.2f} {para_birimi_text}"],
            [f'KDV (%{deal.vat_rate:.0f}):', f"{deal.vat_amount:,.2f} {para_birimi_text}"],
            ['TOPLAM:', f"{deal.value:,.2f} {para_birimi_text}"],
        ]
        totals_table = Table(totals_data, colWidths=[3*cm, 3*cm], hAlign='RIGHT')
        totals_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Vera'),
            ('FONTNAME', (0, -1), (-1, -1), 'Vera-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8.5),
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e8f4f8')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        elements.append(totals_table)

        # Doviz teklifte, kullanilan_kur girilmisse gosterge TL karsiligi
        if deal.para_birimi != 'TRY' and deal.kullanilan_kur:
            elements.append(Spacer(1, 1*mm))
            kur_note = ParagraphStyle('KurNote', parent=terms_style, alignment=2)
            elements.append(Paragraph(
                f"Gösterge kur: 1 {deal.para_birimi} = {deal.kullanilan_kur:,.4f} TL &nbsp;-&nbsp; "
                f"yaklaşık TL karşılığı: {deal.tl_karsiligi:,.2f} TL",
                kur_note
            ))

        # B5e (2026-10-06): Ayarlar'dan aciksa, genel toplamin DIGER 3
        # para birimindeki (bilgi amaclidir) karsiligi - teklif tarihindeki
        # TCMB kuru ile. Tek bir hatali/yavas TCMB cagrisi PDF'in tamamini
        # KIRMASIN diye try/except ile sarildi - basarisiz olursa bu satir
        # sessizce atlanir, PDF yine de olusur.
        if company.pdf_doviz_karsiligi_goster:
            try:
                from app.tcmb import fetch_tcmb_rate
                # deal.value -> TL (deal zaten TRY ise aynen, degilse kendi kuru ile)
                deal_rate_to_try = 1.0 if deal.para_birimi == 'TRY' else (
                    deal.kullanilan_kur or fetch_tcmb_rate(deal.para_birimi)
                )
                value_try = deal.value * (deal_rate_to_try or 1.0)
                other_currencies = [c for c in ('TRY', 'USD', 'EUR', 'GBP') if c != deal.para_birimi]
                parts = []
                for cur in other_currencies:
                    rate = 1.0 if cur == 'TRY' else fetch_tcmb_rate(cur)
                    if not rate:
                        continue
                    value_in_cur = value_try / rate
                    sym = {'TRY': '₺', 'USD': '$', 'EUR': '€', 'GBP': '£'}.get(cur, cur)
                    parts.append(f"{value_in_cur:,.2f} {sym}")
                if parts:
                    elements.append(Spacer(1, 1*mm))
                    doviz_note = ParagraphStyle('DovizKarsiligi', parent=terms_style, alignment=2, fontSize=6.5)
                    elements.append(Paragraph(
                        "Genel toplamın diğer para birimi karşılığı (bilgi amaçlıdır): " + " · ".join(parts),
                        doviz_note
                    ))
            except Exception:
                pass
    else:
        elements.append(Paragraph("<i>Henüz ürün eklenmemiş.</i>", normal))

    elements.append(Spacer(1, 4*mm))
    elements.append(Paragraph("<i>Fiyatlarımıza yürürlükteki K.D.V oranları ilave edilecektir.</i>", normal))
    elements.append(Spacer(1, 4*mm))

    # ===== NUMUNE GORSELLERI (Is 3, buyutulup "kart" gorunumune yeniden
    # tasarlandi) - sadece gorseli olan kalemler icin, hicbir kalemde
    # gorsel yoksa bu bolum tamamen atlanir. Bozuk/eksik bir dosya PDF'in
    # tamamini kirmasin diye her gorsel kendi try/except'inde islenir - o
    # kalem icin sadece etiket kalir, hata verilmez. =====
    items_with_numune = [item for item in deal.items if item.numune_gorseli]
    if items_with_numune:
        numune_label_style = ParagraphStyle(
            'NumuneLabel', parent=small, fontName='Vera-Bold', fontSize=8.5,
            alignment=1, textColor=colors.HexColor('#333333')
        )
        static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')

        CARD_W = 248  # points - ~250-300pt istenen araligin alt siniri, gercek
        # A4 icerik genisliginde (~521pt, 1.3cm kenar bosluklariyla) 2 karti
        # yan yana sigdirabilmek icin (cerceve/golge payi dahil ~251pt/kart).
        IMG_BOX = CARD_W - 12  # kart ic dolgusu icin gorsel kutusu biraz kucuk

        cards = []
        for item in items_with_numune:
            img_flowable = None
            try:
                img_path = os.path.join(static_dir, item.numune_gorseli)
                if os.path.isfile(img_path):
                    # Gercek dosya coz unurlugu korunur - sadece GORUNUM
                    # kutusu buyutulur, kaynak gorsele hicbir yeniden
                    # sikistirma/kucultme uygulanmaz (bulaniklasmayi onler).
                    img_flowable = Image(img_path, width=IMG_BOX, height=IMG_BOX, kind='proportional')
            except Exception:
                img_flowable = None
            if img_flowable is None:
                continue

            # Beyaz zeminli, ince gri cerceveli "kart" - gorsel
            inner = Table([[img_flowable]], colWidths=[CARD_W])
            inner.setStyle(TableStyle([
                ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#a0a0a0')),
                ('BACKGROUND', (0, 0), (-1, -1), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            # Golge efekti: karti gri zeminli bir tabloya, ust/sol dolgu
            # SIFIR, sag/alt dolgu birkac punto birakarak yerlestirmek,
            # kartin sag-alt kenarinda ince bir gri "golge" seridi birakir.
            shadow = Table([[inner]], colWidths=[CARD_W + 4])
            shadow.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#c4c4c4')),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))

            # Urun adi - gorselin altinda ayri, acik gri bir serit/kutu icinde
            label_table = Table(
                [[Paragraph(_pdf_cell_text(item.description), numune_label_style)]],
                colWidths=[CARD_W + 4]
            )
            label_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#eef0f2')),
                ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ]))

            card = Table([[shadow], [label_table]], colWidths=[CARD_W + 4])
            card.setStyle(TableStyle([
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 1), (-1, 1), 0),
                ('TOPPADDING', (0, 1), (-1, 1), 2),
            ]))
            cards.append(card)

        if cards:
            elements.append(Paragraph("NUMUNE GÖRSELLERİ", box_heading))
            elements.append(Spacer(1, 3*mm))

            # Grid: kac kartin bir satira sigacagini gercek sayfa
            # genisliginden (kenar bosluklari haric) otomatik hesaplar -
            # birden fazla kart varsa yan yana, sigmayan satira kaydirir.
            # N sutun + (N-1) aralik toplam genisligi asmadigi surece
            # sutun sayisi artirilir (onceki floor-bolme denemesi hatali
            # cikip her karti ayri sayfaya dusuruyordu - PDF->PNG render
            # ile yakalanip duzeltildi).
            gap = 8
            card_total_w = CARD_W + 4  # kart + golge tasmasi
            content_width = A4[0] - doc.leftMargin - doc.rightMargin
            max_cols = 1
            while (max_cols + 1) * card_total_w + max_cols * gap <= content_width:
                max_cols += 1
            col_w = card_total_w + gap

            grid_rows = []
            for i in range(0, len(cards), max_cols):
                row_cards = cards[i:i + max_cols]
                row_cards += [''] * (max_cols - len(row_cards))
                grid_rows.append(row_cards)
            gallery = Table(grid_rows, colWidths=[col_w] * max_cols)
            gallery.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('LEFTPADDING', (0, 0), (-1, -1), gap / 2),
                ('RIGHTPADDING', (0, 0), (-1, -1), gap / 2),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            elements.append(gallery)
            elements.append(Spacer(1, 4*mm))

    # ===== ACIKLAMA (deal.notes'tan doldurulur, bossa bos kutu kalir) =====
    elements.append(Paragraph("AÇIKLAMA", box_heading))
    if deal.notes:
        from xml.sax.saxutils import escape
        notes_paragraph = Paragraph(escape(_sanitize_pdf_free_text(deal.notes)).replace('\n', '<br/>'), normal)
        aciklama_table = Table([[notes_paragraph]], colWidths=[17.2*cm])
        aciklama_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.5, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
    else:
        aciklama_table = Table([['']], colWidths=[17.2*cm], rowHeights=[2*cm])
        aciklama_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.5, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
    elements.append(aciklama_table)
    elements.append(Spacer(1, 4*mm))

    # ===== SARTLAR / KOSULLAR =====
    company_short = company.company_name or 'Lema Ambalaj'
    terms = [
        f"Sipariş, {company_short} tarafından yazılı veya sözlü olarak onaylandığı andan itibaren geçerlilik kazanır.",
        "Teslim süresi, siparişin kesinleşmesi (onay ve varsa peşinatın alınması) tarihinden itibaren başlar.",
        "Fiyatlarımız, hammadde piyasasındaki değişiklikler nedeniyle önceden haber verilmeksizin güncellenebilir; kesinleşmiş siparişler bu durumdan etkilenmez.",
        "Ödemeler, yukarıda belirtilen vade ve tutarlara uygun şekilde yapılır; gecikme durumunda yasal faiz uygulanabilir.",
        "Üretim kapasitesine bağlı olarak kısmi teslimat yapılabilir.",
        "Mücbir sebep hallerinde (doğal afet, üretim durdurma, hammadde tedarik sorunları vb.) teslim süresi taraflarca yeniden değerlendirilir.",
        "Teslim edilen ürünler, teslim anında alıcı tarafından kontrol edilir; görünür hata ve eksiklikler ancak teslim anında bildirilirse dikkate alınır.",
        "Siparişin iptali, üretime başlanmadan önce yazılı bildirimle mümkündür; üretime başlanmış siparişlerde iptal talepleri değerlendirmeye tabidir.",
    ]
    if deal.para_birimi != 'TRY':
        # Doviz sartlar metni - odemeler ayri gunlerde farkli kurla
        # gelebilecegi icin (bkz. Payment.kur_orani), her tahsilatin
        # kendi gununun TCMB kuru uzerinden TL'ye cevrilecegi acikca belirtilir.
        terms.append(
            f"İşbu teklif {deal.para_birimi} cinsindendir; ödemeler, ödemenin yapıldığı gün geçerli olan "
            f"T.C. Merkez Bankası döviz satış kuru üzerinden Türk Lirası karşılığı olarak tahsil edilir."
        )
    for i, t in enumerate(terms, 1):
        elements.append(Paragraph(f"{i}. {t}", terms_style))
    elements.append(Spacer(1, 8*mm))

    # ===== IMZA KUTULARI =====
    signature_data = [
        [f'Firma Adına Sipariş Veren', '', f'{company_short} Adına Sipariş Alan'],
        ['', '', ''],
        ['', '', ''],
        ['Adı Soyadı:', '', 'Adı Soyadı:'],
        ['İmza:', '', 'İmza:'],
        ['Ünvanı:', '', 'Ünvanı:'],
    ]
    signature_table = Table(signature_data, colWidths=[7.5*cm, 2.2*cm, 7.5*cm])
    signature_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Vera'),
        ('FONTNAME', (0, 0), (0, 0), 'Vera-Bold'),
        ('FONTNAME', (2, 0), (2, 0), 'Vera-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('LINEBELOW', (0, 2), (0, 2), 1, colors.black),
        ('LINEBELOW', (2, 2), (2, 2), 1, colors.black),
    ]))
    elements.append(signature_table)

    watermark_text = (company.company_name or 'LEMA AMBALAJ').upper()
    _watermark_cb = lambda cnv, d: _draw_watermark(cnv, d, watermark_text)
    doc.build(elements, onFirstPage=_watermark_cb, onLaterPages=_watermark_cb)
    buffer.seek(0)
    return buffer


# ===== YENİ TASARIM (2026-10-13) renkleri - gercek logodan, KIRMIZI YOK =====
_Y_SARI = colors.HexColor('#FBC213')
_Y_ANTRASIT = colors.HexColor('#353639')
_Y_CIZGI_GRI = colors.HexColor('#D6D6D6')
_Y_IKINCIL = colors.HexColor('#666666')
_Y_TOPLAM_BG = colors.HexColor('#FAFAF8')
_Y_MIKRO = colors.HexColor('#D9C47A')
_Y_BEJ = colors.HexColor('#F5EFDC')

_URUN_TIPI_LABELS = {'uretim': 'Üretim', 'ticaret': 'Ticaret'}

# ===== 2026-10-22: "Kurumsal vitrin" urun gorseli + ince olcu cizgileri =====
_V_ZEMIN = colors.HexColor('#F7F6F2')
_V_CERCEVE = colors.HexColor('#E4E1DA')
_V_OLCU_CIZGI = colors.HexColor('#A8A8A8')
_V_OLCU_YAZI = colors.HexColor('#8A8A8A')
_V_ETIKET = colors.HexColor('#9A9A9A')
_VITRIN_KUTU = 4.0 * cm
_VITRIN_HEDEF_PX = 500  # 4 cm kutuda ~300+ dpi; daha buyukse kucultulur, daha kucuk asla buyutulmez


def _olcu_degeri(raw, lang='tr'):
    """DealItem.en/boy/korugu serbest metin - ('12,5', 12.5) / ('3,5+3,5', None)
    / (None, None) doner. Sayiysa TR (12,5) veya EN (12.5) bicimde, tam
    sayida ondaliksiz; sayi degilse metin oldugu gibi (cizgiler sadece SAYI
    olan en/boy icin cizilir). Eski kayitlardaki 'None'/'-' metni bos sayilir."""
    s = (str(raw).strip() if raw is not None else '')
    if not s or s.lower() in ('none', 'null', '-', '0'):
        return None, None
    m = re.fullmatch(r'(\d+)(?:[.,](\d+))?', s)
    if not m:
        return s, None
    val = float(f"{m.group(1)}.{m.group(2) or '0'}")
    if val == int(val):
        txt = str(int(val))
    else:
        txt = f'{val:.2f}'.rstrip('0').rstrip('.')
        if lang != 'en':
            txt = txt.replace('.', ',')
    return txt, val


def _vitrin_gorsel_yukle(path):
    """Gorseli KALITE KAYBI OLMADAN hazirlar: dondurme/kucultme gerekmiyorsa
    ORIJINAL dosya dogrudan gomulur (JPEG yeniden sikistirilmaz). Uzun kenar
    _VITRIN_HEDEF_PX'ten buyukse LANCZOS ile kucultulur; seffaf PNG -> PNG
    (seffaflik korunur), opak -> JPEG kalite 95. Telefon fotograflarindaki
    EXIF donus bilgisi uygulanir. Dosya yok/bozuk -> None (satir gorselsiz basilir)."""
    try:
        from PIL import Image as PILImage, ImageOps
        im = PILImage.open(path)
        im.load()
    except Exception:
        return None
    try:
        orientation = im.getexif().get(0x0112, 1)
    except Exception:
        orientation = 1
    w, h = im.size
    if orientation in (1, None) and max(w, h) <= _VITRIN_HEDEF_PX * 1.1:
        return ImageReader(path), w, h
    im2 = ImageOps.exif_transpose(im)
    if max(im2.size) > _VITRIN_HEDEF_PX:
        im2 = im2.copy()
        im2.thumbnail((_VITRIN_HEDEF_PX, _VITRIN_HEDEF_PX), PILImage.LANCZOS)
    has_alpha = im2.mode in ('RGBA', 'LA') or (im2.mode == 'P' and 'transparency' in im2.info)
    buf = BytesIO()
    if has_alpha:
        im2.convert('RGBA').save(buf, 'PNG')
    elif (im.format or '').upper() == 'PNG':
        im2.convert('RGB').save(buf, 'PNG')
    else:
        im2.convert('RGB').save(buf, 'JPEG', quality=95, subsampling=0)
    buf.seek(0)
    return ImageReader(buf), im2.size[0], im2.size[1]


class _VitrinGorsel(Flowable):
    """4x4 cm 'kurumsal vitrin': acik gri zemin, beyaz fotograf karti (3pt
    pay, 0,5pt cerceve + hafif golge), sol-ust/sag-alt sari L koseler, sol
    altta 'G1' etiketi; en/boy SAYI ise kartin altina/sagina ince teknik
    olcu cizgisi. Fotograf en-boy orani korunarak sigdirilir (kirpma yok)."""

    def __init__(self, reader, px_w, px_h, etiket, en_txt=None, boy_txt=None):
        Flowable.__init__(self)
        self.reader, self.px_w, self.px_h = reader, px_w, px_h
        self.etiket, self.en_txt, self.boy_txt = etiket, en_txt, boy_txt
        self.width = self.height = _VITRIN_KUTU

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        c = self.canv
        W = H = _VITRIN_KUTU
        pad, bant, pay = 6, 11, 3
        c.saveState()
        c.setFillColor(_V_ZEMIN)
        c.rect(0, 0, W, H, fill=1, stroke=0)
        alt = bant if self.en_txt else 0
        sag = bant if self.boy_txt else 0
        ax, ay = pad, pad + alt
        aw, ah = W - 2 * pad - sag, H - 2 * pad - alt
        olcek = min((aw - 2 * pay) / self.px_w, (ah - 2 * pay) / self.px_h)
        iw, ih = self.px_w * olcek, self.px_h * olcek
        cw, ch = iw + 2 * pay, ih + 2 * pay
        cx, cy = ax + (aw - cw) / 2, ay + (ah - ch) / 2
        c.setFillColor(_V_CERCEVE)
        c.rect(cx + 0.8, cy - 0.8, cw, ch, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setStrokeColor(_V_CERCEVE)
        c.setLineWidth(0.5)
        c.rect(cx, cy, cw, ch, fill=1, stroke=1)
        c.drawImage(self.reader, cx + pay, cy + pay, iw, ih, mask='auto')
        # sari L koseler
        L = min(0.5 * cm, cw / 3, ch / 3)
        c.setStrokeColor(_Y_SARI)
        c.setLineWidth(2)
        c.line(cx - 1, cy + ch, cx + L, cy + ch)
        c.line(cx, cy + ch + 1, cx, cy + ch - L)
        c.line(cx + cw + 1, cy, cx + cw - L, cy)
        c.line(cx + cw, cy - 1, cx + cw, cy + L)
        # G etiketi (sol alt, kucuk beyaz zemin uzerinde)
        c.setFont('Helvetica', 7)
        tw = c.stringWidth(self.etiket, 'Helvetica', 7)
        c.setFillColor(colors.white)
        c.rect(cx + pay, cy + pay, tw + 4, 9, fill=1, stroke=0)
        c.setFillColor(_V_ETIKET)
        c.drawString(cx + pay + 2, cy + pay + 2.2, self.etiket)
        # ince olcu cizgileri (kartin kenarina gore)
        c.setStrokeColor(_V_OLCU_CIZGI)
        c.setLineWidth(0.5)
        c.setFont('Helvetica', 6.5)
        if self.en_txt:
            y = cy - 6
            c.line(cx, y, cx + cw, y)
            c.line(cx, y - 2, cx, y + 2)
            c.line(cx + cw, y - 2, cx + cw, y + 2)
            lbl = f'{self.en_txt} cm'
            lw = c.stringWidth(lbl, 'Helvetica', 6.5)
            mx = cx + cw / 2
            c.setFillColor(_V_ZEMIN)
            c.rect(mx - lw / 2 - 1.5, y - 3, lw + 3, 6, fill=1, stroke=0)
            c.setFillColor(_V_OLCU_YAZI)
            c.drawCentredString(mx, y - 2.2, lbl)
        if self.boy_txt:
            x = cx + cw + 6
            c.line(x, cy, x, cy + ch)
            c.line(x - 2, cy, x + 2, cy)
            c.line(x - 2, cy + ch, x + 2, cy + ch)
            lbl = f'{self.boy_txt} cm'
            lw = c.stringWidth(lbl, 'Helvetica', 6.5)
            c.translate(x, cy + ch / 2)
            c.rotate(90)
            c.setFillColor(_V_ZEMIN)
            c.rect(-lw / 2 - 1.5, -3, lw + 3, 6, fill=1, stroke=0)
            c.setFillColor(_V_OLCU_YAZI)
            c.drawCentredString(0, -2.2, lbl)
        c.restoreState()


def _draw_footer_yeni(canvas_obj, doc, company, deal, page_num, total_pages, lang='tr'):
    """Sayfa dibinde SABIT alt bilgi bandi - antrasit zemin, ustunde sari
    cizgi. doc.build() canvasmaker'i uzerinden her sayfada cagirilir.
    PAKET B Is B5 - lang='en' ise 'Sayfa X/Y'/'ORİJİNAL BELGE' Ingilizce
    basilir, sirket adi/adres gibi veri alanlari degismez.

    2026-10-22 duzeltmeleri: (1) sag ust kose damgasi (_draw_watermark_yeni,
    donuk antrasit serit icinde firma adi) KALDIRILDI - TEKLİF basligina
    biniyordu. (2) Firma adi eskiden IKI KEZ basiliyordu (kalin + '· ad ·
    Karatay') ve uzun unvanlarda sagdaki 'TKL-xxxxx · Sayfa x/y' ile ust
    uste biniyordu; artik bir kez basilir, sigmazsa once kuculur sonra '…'
    ile kisaltilir - sag metne en az 0,4 cm bosluk kalir. (3) Bant eskiden
    icerik alaninin ICINE taşıyordu (ust kenari ~2,55 cm, icerik alt siniri
    2,0 cm); artik icerik alt sinirinin ALTINDA (ust kenar 1,7 cm)."""
    band_h = 0.9*cm
    y0 = 0.8*cm
    sol_x = doc.leftMargin + 0.25*cm
    sag_x = A4[0] - doc.rightMargin - 0.25*cm
    canvas_obj.saveState()
    canvas_obj.setStrokeColor(_Y_SARI)
    canvas_obj.setLineWidth(3)
    canvas_obj.line(doc.leftMargin, y0 + band_h, A4[0] - doc.rightMargin, y0 + band_h)
    canvas_obj.setFillColor(_Y_ANTRASIT)
    canvas_obj.rect(doc.leftMargin, y0, A4[0] - doc.leftMargin - doc.rightMargin, band_h, fill=1, stroke=0)
    right_text = f"{deal.display_no} · Page {page_num}/{total_pages}" if lang == 'en' else f"{deal.display_no} · Sayfa {page_num}/{total_pages}"
    canvas_obj.setFont('Vera-Bold', 9)
    canvas_obj.setFillColor(colors.white)
    canvas_obj.drawRightString(sag_x, y0 + band_h/2 - 3, right_text)
    sol_max = (sag_x - canvas_obj.stringWidth(right_text, 'Vera-Bold', 9) - 0.4*cm) - sol_x

    left_text = (company.company_name or 'LEMA AMBALAJ').upper()
    ek = ' · Karatay / KONYA'
    boyut = 9
    while boyut > 7 and canvas_obj.stringWidth(left_text, 'Vera-Bold', boyut) + canvas_obj.stringWidth(ek, 'Vera', boyut - 1) > sol_max:
        boyut -= 0.5
    if canvas_obj.stringWidth(left_text, 'Vera-Bold', boyut) + canvas_obj.stringWidth(ek, 'Vera', boyut - 1) > sol_max:
        ek = ''
    sol = left_text
    while sol and canvas_obj.stringWidth(sol + ('…' if sol != left_text else ''), 'Vera-Bold', boyut) > sol_max:
        sol = sol[:-1]
    if sol != left_text:
        sol = sol.rstrip() + '…'
    canvas_obj.setFont('Vera-Bold', boyut)
    canvas_obj.setFillColor(_Y_SARI)
    canvas_obj.drawString(sol_x, y0 + band_h/2 - 3, sol)
    if ek:
        canvas_obj.setFont('Vera', boyut - 1)
        canvas_obj.setFillColor(colors.HexColor('#cccccc'))
        canvas_obj.drawString(sol_x + canvas_obj.stringWidth(sol, 'Vera-Bold', boyut), y0 + band_h/2 - 3, ek)
    canvas_obj.restoreState()

    # mikro metin seridi - alt bandin ALTINDA (en alt kenar bosluguna sigar)
    canvas_obj.saveState()
    canvas_obj.setFont('Vera', 5.5)
    canvas_obj.setFillColor(_Y_MIKRO)
    unit = f"{left_text} · ORIGINAL DOCUMENT · {deal.display_no} · " if lang == 'en' else f"{left_text} · ORİJİNAL BELGE · {deal.display_no} · "
    unit_w = canvas_obj.stringWidth(unit, 'Vera', 5.5)
    available_w = A4[0] - 1.0*cm
    repeats = max(1, int(available_w // unit_w) + 1) if unit_w > 0 else 1
    canvas_obj.drawString(0.5*cm, 0.4*cm, unit * repeats)
    canvas_obj.restoreState()


class _DealPdfCanvasYeni(_PDFCanvas):
    """2026-10-13: 'Sayfa x/y' icin standart ReportLab iki-gecisli canvas
    deseni - once tum sayfalar uretilir (toplam sayi bilinmez), sonra
    save() asamasinda gercek toplam sayi ile her sayfanin alt bilgisi
    cizilir. Klasik tasarim bu canvas'i KULLANMAZ (SimpleDocTemplate'in
    varsayilan canvas'i ile cagrilir), bu yuzden klasik cikti etkilenmez."""

    def __init__(self, *args, **kwargs):
        self._footer_cb = kwargs.pop('footer_cb', None)
        _PDFCanvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total_pages = len(self._saved_page_states)
        for i, state in enumerate(self._saved_page_states, 1):
            self.__dict__.update(state)
            if self._footer_cb:
                self._footer_cb(self, i, total_pages)
            _PDFCanvas.showPage(self)
        _PDFCanvas.save(self)


_YENI_PDF_LABELS = {
    'tr': {
        'title': 'TEKLİF', 'teklif_no': 'Teklif No:', 'tarih': 'Tarih:', 'gecerlilik': 'Geçerlilik:',
        'hazirlayan': 'Hazırlayan:', 'vd': 'V.D.:', 'vno': 'V.No:', 'tel': 'Tel:', 'faks': 'Faks:',
        'musteri_bilgi': 'MÜŞTERİYE AİT BİLGİLER', 'odeme_sekli': 'ÖDEME ŞEKLİ', 'yetkili': 'Yetkili:',
        'telefon': 'Telefon:', 'adres': 'Adres:', 'vade': 'Vade:', 'pesin': 'Peşin', 'odeme': 'Ödeme:',
        'doviz_kuru': 'Döviz kuru:', 'banka': 'Banka:', 'alici': 'Alıcı:',
        'urun_fiyat_basligi': 'ÜRÜN VE FİYAT BİLGİLERİ', 'kdv_haric_not': 'Fiyatlar KDV hariçtir',
        'h_numune': 'Numune', 'h_urun': 'Ürün ve teknik özellikler', 'h_miktar': 'Miktar',
        'h_fiyat': 'Birim fiyat', 'h_teslim': 'Teslim', 'h_tutar': 'Tutar\n(KDV hariç)',
        'koli_baskisiz': 'Koli: Baskısız', 'gr': 'gr',
        'kagit_cinsi': 'Kağıt cinsi:', 'olcu': 'Ölçü:', 'en': 'En', 'boy': 'Boy', 'korugu': 'Körük',
        'baski': 'Baskı:', 'adet_basi': 'Adet başı ≈', 'aciklama_basligi': 'A Ç I K L A M A',
        'teklif_sartlari_basligi': 'TEKLİF ŞARTLARI', 'toplam_haric': 'Toplam (KDV hariç)',
        'kdv': 'KDV', 'genel_toplam': 'GENEL TOPLAM', 'yalniz': 'Yalnız:',
        'henuz_urun_yok': '<i>Henüz ürün eklenmemiş.</i>', 'teklifi_veren': 'Teklifi veren',
        'musteri_onayi': 'Müşteri onayı', 'kase_imza': 'Kaşe / İmza:', 'ad_soyad': 'Ad Soyad:',
        'tl': 'TL',
        'h_termin': 'Termin', 'is_gunu': 'iş günü', 'onaydan_sonra': 'onaydan sonra',
        'termin_maddesi': 'Termin süreleri sipariş ve baskı provası onayından itibaren iş günü olarak hesaplanır.',
    },
    'en': {
        'title': 'QUOTATION', 'teklif_no': 'Quotation No:', 'tarih': 'Date:', 'gecerlilik': 'Valid until:',
        'hazirlayan': 'Prepared by:', 'vd': 'Tax Office:', 'vno': 'Tax No:', 'tel': 'Tel:', 'faks': 'Fax:',
        'musteri_bilgi': 'CUSTOMER INFORMATION', 'odeme_sekli': 'PAYMENT TERMS', 'yetkili': 'Contact:',
        'telefon': 'Phone:', 'adres': 'Address:', 'vade': 'Payment due:', 'pesin': 'Immediate', 'odeme': 'Method:',
        'doviz_kuru': 'Exchange rate:', 'banka': 'Bank:', 'alici': 'Beneficiary:',
        'urun_fiyat_basligi': 'PRODUCT AND PRICE DETAILS', 'kdv_haric_not': 'Prices exclude VAT',
        'h_numune': 'Sample', 'h_urun': 'Product & specifications', 'h_miktar': 'Quantity',
        'h_fiyat': 'Unit price', 'h_teslim': 'Delivery', 'h_tutar': 'Amount\n(excl. VAT)',
        'koli_baskisiz': 'Carton: Plain (unprinted)', 'gr': 'g',
        'kagit_cinsi': 'Paper type:', 'olcu': 'Size:', 'en': 'Width', 'boy': 'Height', 'korugu': 'Gusset',
        'baski': 'Print:', 'adet_basi': 'Per piece ≈', 'aciklama_basligi': 'N O T E S',
        'teklif_sartlari_basligi': 'TERMS & CONDITIONS', 'toplam_haric': 'Subtotal (excl. VAT)',
        'kdv': 'VAT', 'genel_toplam': 'GRAND TOTAL', 'yalniz': None,
        'henuz_urun_yok': '<i>No items added yet.</i>', 'teklifi_veren': 'Issued by',
        'musteri_onayi': 'Customer approval', 'kase_imza': 'Stamp / Signature:', 'ad_soyad': 'Name:',
        'tl': 'TRY',
        'h_termin': 'Lead time', 'is_gunu': 'business days', 'onaydan_sonra': 'after approval',
        'termin_maddesi': 'Lead times are counted in business days from order and print proof approval.',
    },
}


def _generate_deal_pdf_yeni(deal, lang='tr'):
    """2026-10-13: Teklif PDF - YENİ tasarim (gercek logo renkleri: sari
    #FBC213 + antrasit #353639, kirmizi YOK). CompanySettings.teklif_pdf_tasarim
    'klasik' ise bu fonksiyon hic cagrilmaz (bkz. generate_deal_pdf
    dispatcher) - klasik _generate_deal_pdf_klasik() TAMAMEN ayri ve
    degismeden kalir. PEŞİNAT/BAKİYE/KALAN bu tasarimda HİÇ BASILMAZ.

    PAKET B Is B5 (2026-10-14): lang='tr' (varsayilan - TUM eski
    cagrilar/davranis AYNEN korunur) veya 'en'. Etiketler _YENI_PDF_LABELS
    sozlugunden (t), sayi bicimi lang='en' ise _money_en/_miktar_en/
    _birim_fiyat_en'den (money/qty/price degiskenleri) gelir. KARAR: EN
    modda tutar-yaziyla (Yalnız: ...) satiri HIC BASILMAZ (gorev tanimi
    geregi) - t['yalniz'] None oldugunda asagida atlanir."""
    t = _YENI_PDF_LABELS['en' if lang == 'en' else 'tr']
    money = _money_en if lang == 'en' else _money_tr
    qty_fmt = _miktar_en if lang == 'en' else _miktar_tr
    price_fmt = _birim_fiyat_en if lang == 'en' else _birim_fiyat_tr
    unit_label = _unit_en if lang == 'en' else (lambda u: u)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.4*cm, leftMargin=1.4*cm, topMargin=1.6*cm, bottomMargin=2.0*cm)
    content_w = A4[0] - doc.leftMargin - doc.rightMargin

    company = _get_company_settings_for_pdf()

    styles = getSampleStyleSheet()
    normal = ParagraphStyle('YNormal', parent=styles['Normal'], fontName='Vera', fontSize=8.5, leading=11, textColor=_Y_ANTRASIT)
    gray_small = ParagraphStyle('YGraySmall', parent=normal, fontSize=7, leading=9, textColor=_Y_IKINCIL)
    bold = ParagraphStyle('YBold', parent=normal, fontName='Vera-Bold')
    company_name_style = ParagraphStyle('YCompanyName', parent=normal, fontName='Vera-Bold', fontSize=13, leading=16)
    title_style = ParagraphStyle('YTitle', parent=normal, fontName='Vera-Bold', fontSize=20, leading=23, alignment=2)
    meta_style = ParagraphStyle('YMeta', parent=normal, fontSize=8.5, leading=12, alignment=2)
    meta_bold_style = ParagraphStyle('YMetaBold', parent=meta_style, fontName='Vera-Bold')
    box_title_style = ParagraphStyle('YBoxTitle', parent=normal, fontName='Vera-Bold', fontSize=8.5, textColor=colors.white)
    table_header_style = ParagraphStyle('YTableHeader', parent=normal, fontName='Vera-Bold', fontSize=7.3, leading=8.5,
                                         alignment=1)
    table_cell_style = ParagraphStyle('YTableCell', parent=normal, fontSize=7.8, leading=9.5)
    table_cell_bold_style = ParagraphStyle('YTableCellBold', parent=table_cell_style, fontName='Vera-Bold')
    table_cell_gray_style = ParagraphStyle('YTableCellGray', parent=table_cell_style, fontSize=6.8, leading=8, textColor=_Y_IKINCIL)
    table_cell_center_style = ParagraphStyle('YTableCellCenter', parent=table_cell_style, alignment=1)
    terms_style = ParagraphStyle('YTerms', parent=normal, fontSize=7.3, leading=10)
    italic_style = ParagraphStyle('YItalic', parent=normal, fontName='Vera-Italic', fontSize=8)

    elements = []

    # ===== 1) UST BLOK: logo | firma | TEKLİF basligi+meta =====
    logo_img = None
    if company.logo_data:
        try:
            cleaned = _logo_for_pdf_yeni(company.logo_data)
            if cleaned:
                logo_img = Image(cleaned, width=4.3*cm, height=4.3*cm, kind='proportional')
        except Exception:
            logo_img = None

    company_block = [Paragraph(company.company_name or 'Lema Ambalaj', company_name_style)]
    if company.address:
        company_block.append(Paragraph(company.address.replace('\n', '<br/>'), gray_small))
    contact1 = [b for b in [f"{t['tel']} {company.phone}" if company.phone else None,
                             f"{t['faks']} {company.fax}" if company.fax else None] if b]
    if contact1:
        company_block.append(Paragraph(' · '.join(contact1), gray_small))
    contact2 = [b for b in [company.email, company.website] if b]
    if contact2:
        company_block.append(Paragraph(' · '.join(contact2), gray_small))
    if company.tax_office or company.tax_id:
        company_block.append(Paragraph(f"{t['vd']} {company.tax_office or '-'} · {t['vno']} {company.tax_id or '-'}", gray_small))

    teklif_tarihi = deal.deal_date or deal.created_at.date()
    seller_name = (deal.seller.full_name or deal.seller.username) if deal.seller else '-'
    # Is B5: harf araligi (' '.join(list(...))) sadece KISA TR basligina
    # ('TEKLİF', 6 harf) uyuyordu - EN 'QUOTATION' (9 harf) ayni 6cm
    # kutuda cift satira bolunup kiriliyordu (Playwright/pypdf testiyle
    # gorulup duzeltildi). EN icin harf araligi KULLANILMAZ.
    title_text = ' '.join(list(t['title'])) if lang == 'tr' else t['title']
    right_block = [
        Paragraph(title_text, title_style),
        Spacer(1, 2*mm),
        Paragraph(f"{t['teklif_no']} {deal.display_no}", meta_bold_style),
        Paragraph(f"{t['tarih']} {teklif_tarihi.strftime('%d.%m.%Y') if teklif_tarihi else '-'}", meta_style),
        Paragraph(f"{t['gecerlilik']} {deal.valid_until.strftime('%d.%m.%Y') if deal.valid_until else '-'}", meta_bold_style),
        Paragraph(f"{t['hazirlayan']} {seller_name}", meta_style),
    ]

    logo_w = 4.6*cm
    right_w = 6.0*cm
    middle_w = content_w - logo_w - right_w
    header_table = Table([[logo_img or '', company_block, right_block]], colWidths=[logo_w, middle_w, right_w])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (1, 0), (1, 0), 8),
        # 2026-10-22: logo gorseli 4,6 cm sutunu tamamen dolduruyor, firma
        # adi bitisik basliyordu - logo 4,3 cm'e indi + firma blogu 0,3 cm iceride.
        ('LEFTPADDING', (1, 0), (1, 0), 0.3*cm),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 3*mm))

    # ===== 2) 4pt sari + 0.8pt antrasit cizgi =====
    elements.append(Table([['']], colWidths=[content_w], rowHeights=[4], style=[('BACKGROUND', (0, 0), (-1, -1), _Y_SARI)]))
    elements.append(Table([['']], colWidths=[content_w], style=[('LINEBELOW', (0, 0), (-1, -1), 0.8, _Y_ANTRASIT)]))
    elements.append(Spacer(1, 4*mm))

    # ===== 3) MÜŞTERİYE AİT BİLGİLER + ÖDEME ŞEKLİ kutulari =====
    def _box(title_text, lines, box_w):
        stripe = Table([['']], colWidths=[0.16*cm], rowHeights=[0.62*cm], style=[('BACKGROUND', (0, 0), (-1, -1), _Y_SARI)])
        title_cell = Table([[stripe, Paragraph(title_text, box_title_style)]], colWidths=[0.16*cm, box_w - 0.16*cm])
        title_cell.setStyle(TableStyle([
            ('BACKGROUND', (1, 0), (1, 0), _Y_ANTRASIT),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (1, 0), (1, 0), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        if lines:
            # Is B1 (2026-10-14): 'lines' icinde duz metin (Paragraph'a
            # sarilir) VEYA hazir bir flowable (ör. IBAN alt-kutusu) olabilir.
            content_rows = [[l if hasattr(l, 'wrap') else Paragraph(l, normal)] for l in lines]
            content_table = Table(content_rows, colWidths=[box_w - 12])
            c_style = [
                ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]
            for r in range(len(lines) - 1):
                c_style.append(('LINEBELOW', (0, r), (0, r), 0.4, _Y_CIZGI_GRI))
            content_table.setStyle(TableStyle(c_style))
        else:
            content_table = Table([[Paragraph('-', gray_small)]], colWidths=[box_w - 12])
            content_table.setStyle(TableStyle([('TOPPADDING', (0, 0), (-1, -1), 3)]))
        box = Table([[title_cell], [content_table]], colWidths=[box_w])
        box.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.75, _Y_ANTRASIT),
            ('LEFTPADDING', (0, 1), (0, 1), 6), ('RIGHTPADDING', (0, 1), (0, 1), 6),
            ('TOPPADDING', (0, 1), (0, 1), 5), ('BOTTOMPADDING', (0, 1), (0, 1), 6),
            ('LEFTPADDING', (0, 0), (0, 0), 0), ('RIGHTPADDING', (0, 0), (0, 0), 0),
            ('TOPPADDING', (0, 0), (0, 0), 0), ('BOTTOMPADDING', (0, 0), (0, 0), 0),
        ]))
        return box

    def _escape(v):
        from xml.sax.saxutils import escape
        cleaned = _sanitize_pdf_free_text(v)
        return escape(cleaned) if cleaned else ''

    customer = deal.customer
    customer_person_name = f"{_clean_for_pdf(customer.first_name) or ''} {_clean_for_pdf(customer.last_name) or ''}".strip()
    customer_lines = []
    if customer.company_name:
        customer_lines.append(f"<b>{_clean_for_pdf(customer.company_name)}</b>")
    if customer_person_name:
        customer_lines.append(f"{t['yetkili']} {customer_person_name}")
    if customer.phone:
        customer_lines.append(f"{t['telefon']} {customer.phone}")
    if customer.tax_office or customer.tax_id:
        customer_lines.append(f"{t['vd']} {customer.tax_office or '-'} · {t['vno']} {customer.tax_id or '-'}")
    adres = customer.company_address or customer.address
    if adres:
        customer_lines.append(f"{t['adres']} {adres}")

    kur_tarihi = deal.deal_date or deal.created_at.date()
    kur_tarihi_str = kur_tarihi.strftime('%d.%m.%Y') if kur_tarihi else '-'
    # PAKET B Is B5: Vade/Odeme Yontemi metinleri, deal.vade_gun_metni/
    # odeme_yontemi_listesi (TR, baska yerlerde de kullanilan PAYLASILAN
    # property'ler) DEGISTIRILMEDEN, lang='en' icin burada AYRICA turetilir.
    if lang == 'en':
        if deal.odeme_vade_gun is not None:
            vade_display = t['pesin'] if deal.odeme_vade_gun == 0 else f'{deal.odeme_vade_gun} days'
        else:
            vade_display = deal.vade_gun or t['pesin']
        odeme_codes = [c.strip() for c in (deal.odeme_yontemi or '').split(',') if c.strip()]
        odeme_labels = [_PAYMENT_METHOD_LABELS_EN[c] for c in odeme_codes if c in _PAYMENT_METHOD_LABELS_EN]
    else:
        vade_display = deal.vade_gun_metni or t['pesin']
        odeme_labels = deal.odeme_yontemi_listesi
    payment_lines = [f"{t['vade']} {vade_display}"]
    if odeme_labels:
        payment_lines.append(f"{t['odeme']} {' · '.join(odeme_labels)}")
    if deal.para_birimi != 'TRY' and deal.kullanilan_kur:
        # NOT: bu satir TARIHSEL olarak hep Python'un ':,.2f' bicimini
        # kullandi (_money_tr DEGIL) - TR davranisini AYNEN korumak icin
        # lang='tr' dalinda bu bicim DEGISTIRILMEDI, SADECE 'en' icin
        # ayraclar EN'e (zaten ayni ':,.2f') - tek fark 'TL' -> 'TRY' etiketi.
        payment_lines.append(f"{t['doviz_kuru']} 1 {deal.para_birimi} = {deal.kullanilan_kur:,.2f} {t['tl']} · TCMB {kur_tarihi_str}")

    customer_w = content_w * 0.54
    payment_w = content_w - customer_w

    # Is B1 (2026-10-14): Havale / EFT secili ise ÖDEME ŞEKLİ kutusuna acik
    # sari zeminli IBAN alt-blogu eklenir - teklif sartlarindaki eski tek
    # satirlik "BANKA · IBAN" KALDIRILDI, IBAN artik SADECE burada.
    if 'havale' in (deal.odeme_yontemi or '').split(','):
        iban_rows = []
        if company.banka_adi:
            iban_rows.append(Paragraph(f"{t['banka']} {_escape(company.banka_adi)}", table_cell_style))
        if company.iban:
            iban_rows.append(Paragraph(f"IBAN: <font face='Courier'>{_iban_grupla(company.iban)}</font>", table_cell_style))
        if deal.para_birimi == 'USD' and company.iban_usd:
            iban_rows.append(Paragraph(f"IBAN (USD): <font face='Courier'>{_iban_grupla(company.iban_usd)}</font>", table_cell_style))
        if deal.para_birimi == 'EUR' and company.iban_eur:
            iban_rows.append(Paragraph(f"IBAN (EUR): <font face='Courier'>{_iban_grupla(company.iban_eur)}</font>", table_cell_style))
        if company.company_name:
            iban_rows.append(Paragraph(f"{t['alici']} {_escape(company.company_name)}", table_cell_style))
        if iban_rows:
            iban_box = Table([[r] for r in iban_rows], colWidths=[payment_w - 24])
            iban_box.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FFF6DA')),
                ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 2.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
            ]))
            payment_lines.append(iban_box)

    customer_box = _box(t['musteri_bilgi'], customer_lines, customer_w)
    payment_box = _box(t['odeme_sekli'], payment_lines, payment_w)
    boxes_table = Table([[customer_box, payment_box]], colWidths=[customer_w, payment_w])
    boxes_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (0, 0), 6),
    ]))
    elements.append(boxes_table)
    elements.append(Spacer(1, 4*mm))

    # ===== 4) ÜRÜN VE FİYAT BİLGİLERİ basligi =====
    heading_row = Table([[Paragraph(t['urun_fiyat_basligi'], ParagraphStyle('YProdHead', parent=bold, fontSize=9.5)),
                           Paragraph(t['kdv_haric_not'], ParagraphStyle('YProdNote', parent=gray_small, alignment=2))]],
                         colWidths=[content_w * 0.6, content_w * 0.4])
    heading_row.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'BOTTOM'), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0)]))
    elements.append(heading_row)
    elements.append(Spacer(1, 2*mm))

    # ===== 5) ÜRÜN TABLOSU =====
    para_sym = t['tl'] if deal.para_birimi == 'TRY' else deal.para_birimi_sembol
    deal_delivery_fallback = deal.expected_close.strftime('%d.%m.%Y') if deal.expected_close else '-'

    if deal.items:
        # 2026-10-22 (kurumsal vitrin): ayri "Numune" sutunu KALDIRILDI - gorsel
        # artik urun hucresinin SOLUNDA 4x4 cm vitrin olarak basiliyor (iki kez
        # cizilmesin). Sutunlar her zaman eski gorselsiz yerlesimle AYNI.
        col_widths = [0.9*cm, 8.1*cm, 2.0*cm, 2.6*cm, 2.0*cm, 2.6*cm]
        headers = ['#', t['h_urun'], t['h_miktar'], t['h_fiyat'], t['h_termin'], t['h_tutar']]
        data = [[Paragraph(h.replace('\n', '<br/>'), table_header_style) for h in headers]]
        urun_ic_w = col_widths[1] - 12  # hucre ici (6pt sol + 6pt sag pay)
        olcu_style = ParagraphStyle('YOlcu', parent=table_cell_style, fontSize=8, leading=10, textColor=_V_OLCU_YAZI)
        termin_style = ParagraphStyle('YTermin', parent=table_cell_center_style, fontName='Vera-Bold', fontSize=7.3, leading=9)

        static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
        termin_var = False
        gorsel_no = 0
        for idx, item in enumerate(deal.items, 1):
            # # hucresi - antrasit kare icinde sari numara
            num_cell = Table([[str(idx)]], colWidths=[0.55*cm], rowHeights=[0.55*cm])
            num_cell.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), _Y_ANTRASIT),
                ('TEXTCOLOR', (0, 0), (-1, -1), _Y_SARI),
                ('FONTNAME', (0, 0), (-1, -1), 'Vera-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))

            # Urun ve teknik ozellikler hucresi - Is 2a: "Urun tipi" satiri
            # KALDIRILDI (ic bilgi, musteriyi ilgilendirmez). Kagit cinsi,
            # urun adiyla (harf/bosluk farki haric) AYNIYSA basilmaz.
            urun_adi = f"<b>{_escape(item.description)}</b>"
            # 2026-10-26: kese numarasi urun adinin yaninda (ad zaten
            # '1000 gr ...' iceriyorsa tekrar yazilmaz).
            _kg = getattr(item, 'kese_gramaj', None)
            if _kg and not re.search(rf'\b{int(_kg)}\s*g', item.description or '', re.IGNORECASE):
                urun_adi += f"<b> · {int(_kg)} {t['gr']}</b>"
            urun_lines = [urun_adi]
            if _kagit_cinsi_farkli_mi(item.description, item.kagit_cinsi):
                urun_lines.append(f"<font color='#666666' size=6.8>{t['kagit_cinsi']} {_escape(item.kagit_cinsi)}</font>")
            if item.renk:
                urun_lines.append(f"<font color='#666666' size=6.8>{t['baski']} {_escape(item.renk)}</font>")
            is_doviz = deal.para_birimi != 'TRY' and deal.kullanilan_kur
            if is_doviz and item.unit == 'adet':
                adet_basi_tl = item.unit_price * deal.kullanilan_kur
                urun_lines.append(f"<b>{t['adet_basi']} {money(adet_basi_tl)} {t['tl']}</b>")
            urun_flow = [Paragraph('<br/>'.join(urun_lines), table_cell_style)]
            # Olcu satiri: mevcut en/boy/korugu (serbest metin) - bos olan yazilmaz.
            en_txt, en_val = _olcu_degeri(item.en, lang)
            boy_txt, boy_val = _olcu_degeri(item.boy, lang)
            kor_txt, _ = _olcu_degeri(item.korugu, lang)
            olcu_parca = [x for x in (en_txt, boy_txt, kor_txt) if x]
            if olcu_parca:
                urun_flow.append(Spacer(1, 1.5))
                urun_flow.append(Paragraph(f"{t['olcu']} {_escape(' × '.join(olcu_parca))} cm", olcu_style))
            if getattr(item, 'koli_tipi', None) == 'baskisiz':
                urun_flow.append(Spacer(1, 1))
                urun_flow.append(Paragraph(t['koli_baskisiz'], olcu_style))

            gorsel = None
            if item.numune_gorseli:
                yuklu = _vitrin_gorsel_yukle(os.path.join(static_dir, item.numune_gorseli))
                if yuklu:
                    gorsel_no += 1
                    gorsel = _VitrinGorsel(yuklu[0], yuklu[1], yuklu[2], f'G{gorsel_no}',
                                           en_txt if en_val else None, boy_txt if boy_val else None)
            if gorsel:
                urun_cell = Table([[gorsel, urun_flow]], colWidths=[_VITRIN_KUTU, urun_ic_w - _VITRIN_KUTU])
                urun_cell.setStyle(TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (0, 0), 0), ('RIGHTPADDING', (0, 0), (0, 0), 0),
                    ('LEFTPADDING', (1, 0), (1, 0), 8), ('RIGHTPADDING', (1, 0), (1, 0), 0),
                    ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                ]))
            else:
                urun_cell = urun_flow

            # PAKET B Is B4 (Kalem bazli doviz, Asama 1) - item.para_birimi
            # SADECE deal.para_birimi 'TRY' ise anlamlidir (KARAR: iki doviz
            # mekanizmasi ayni teklifte cakismaz - bkz. app/models.py
            # Deal.calculate_totals yorumu). Eski kayitlarda item.para_birimi
            # hep None - asagidaki if/elif hic tetiklenmez, mevcut PDF
            # ciktisi DEGISMEZ.
            item_doviz_sym = {'USD': '$', 'EUR': '€'}.get(item.para_birimi) if deal.para_birimi == 'TRY' else None
            item_kur = None
            if item_doviz_sym:
                item_kur = deal.kur_usd if item.para_birimi == 'USD' else deal.kur_eur

            # Birim fiyat hucresi - Is 2c: en az 2, en fazla 4 ondalik
            item_unit_label = unit_label(item.unit)
            if item_doviz_sym:
                fiyat_text = f"{price_fmt(item.unit_price)} {item_doviz_sym}/{item_unit_label}"
                if item_kur:
                    fiyat_text += f"<br/><font color='#666666' size=6.5>≈ {money(item.unit_price * item_kur)} {t['tl']}</font>"
            elif deal.para_birimi == 'TRY':
                fiyat_text = f"{price_fmt(item.unit_price)} {t['tl']}/{item_unit_label}"
            else:
                fiyat_text = f"{price_fmt(item.unit_price)} {para_sym}"
                if deal.kullanilan_kur:
                    tl_karsilik = item.unit_price * deal.kullanilan_kur
                    fiyat_text += f"<br/><font color='#666666' size=6.5>≈ {money(tl_karsilik)} {t['tl']}</font>"
            fiyat_cell = Paragraph(fiyat_text, table_cell_center_style)

            # Termin hucresi (2026-10-22): kalem.termin_gun -> deal.varsayilan_
            # termin_gun -> eski teslim tarihi/expected_close -> '-'
            termin_gun = getattr(item, 'termin_gun', None) or getattr(deal, 'varsayilan_termin_gun', None)
            if termin_gun:
                termin_var = True
                ilk, _, kalan = t['is_gunu'].partition(' ')
                termin_cell = Paragraph(f"{termin_gun}&nbsp;{ilk} {kalan}<br/>"
                                        f"<font name='Vera' size=6.3 color='#888888'>{t['onaydan_sonra']}</font>", termin_style)
            else:
                item_delivery_str = item.teslim_tarihi.strftime('%d.%m.%Y') if item.teslim_tarihi else deal_delivery_fallback
                termin_cell = Paragraph(item_delivery_str, table_cell_center_style)

            # Tutar (KDV haric) hucresi - TL'ye cevrilebiliyorsa TL, degilse
            # kendi para biriminde (bkz. Deal.deger_tl ile AYNI mantik -
            # Komuta Merkezi'nde de bu yaklasim kullaniliyor). Kalem bazli
            # dovizli kalemler HER ZAMAN TL gosterir (alttaki Ara Toplam/
            # Genel Toplam da TL - Deal.calculate_totals ile AYNI rakam).
            if item_doviz_sym and item_kur:
                tutar_text = f"{money(item.total_price * item_kur)} {t['tl']}"
            elif item_doviz_sym:
                tutar_text = f"{money(item.total_price)} {item_doviz_sym}"
            elif deal.para_birimi == 'TRY':
                tutar_text = f"{money(item.total_price)} {t['tl']}"
            elif deal.kullanilan_kur:
                tutar_text = f"{money(item.total_price * deal.kullanilan_kur)} {t['tl']}"
            else:
                tutar_text = f"{money(item.total_price)} {para_sym}"
            tutar_cell = Paragraph(f"<b>{tutar_text}</b>", table_cell_center_style)

            data.append([num_cell, urun_cell,
                         Paragraph(f"{qty_fmt(item.quantity)} {item_unit_label}", table_cell_center_style),
                         fiyat_cell, termin_cell, tutar_cell])

        # repeatRows=1: sari baslik her sayfada tekrar eder; Platypus bir
        # tablo SATIRINI asla iki sayfaya bolmez (kalem satiri butun kalir).
        table = Table(data, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), _Y_SARI),
            ('TEXTCOLOR', (0, 0), (-1, 0), _Y_ANTRASIT),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, _Y_CIZGI_GRI),
            ('BOX', (0, 0), (-1, -1), 0.75, _Y_ANTRASIT),
            ('TOPPADDING', (0, 0), (-1, 0), 5), ('BOTTOMPADDING', (0, 0), (-1, 0), 5),
            ('TOPPADDING', (0, 1), (-1, -1), 5), ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
            ('LEFTPADDING', (1, 1), (1, -1), 6),
            ('RIGHTPADDING', (1, 1), (1, -1), 6),
            # Termin sutunu 2,0 cm: '120 iş günü' tek satira sigsin diye ic pay 3pt
            ('LEFTPADDING', (4, 1), (4, -1), 3), ('RIGHTPADDING', (4, 1), (4, -1), 3),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 4*mm))

        # ===== 5b) AÇIKLAMA (Is 1, 2026-10-13) - deal.notes doluysa, urun
        # tablosu ile sartlar/toplam arasinda tam genislik kutu. Klasik
        # tasarimdaki (zaten var olan, deal.notes'u basan) AÇIKLAMA kutusuna
        # HIC DOKUNULMADI - bu SADECE yeni tasarima ekleniyordu (bkz. rapor:
        # kok sebep, klasik zaten calisiyordu). Coklu satir/sayfa tasmasi icin
        # TEK buyuk hucre DEGIL, SATIR BASINA bir tablo satiri kullanilir -
        # Platypus Table sadece SATIRLAR ARASINDA sayfa bolebilir, tek devasa
        # bir hucre icinde BOLEMEZ (60 satirlik uzun not testiyle dogrulandi).
        if deal.notes and deal.notes.strip():
            aciklama_title_style = ParagraphStyle(
                'YAciklamaTitle', parent=normal, fontName='Vera-Bold', fontSize=8.5, textColor=_Y_ANTRASIT)
            aciklama_text_style = ParagraphStyle(
                'YAciklamaText', parent=normal, fontSize=8, leading=11)
            aciklama_stripe_w = 0.14*cm
            aciklama_content_w = content_w - aciklama_stripe_w
            aciklama_rows = [['', Paragraph(t['aciklama_basligi'], aciklama_title_style)]]
            for line in _sanitize_pdf_free_text(deal.notes).split('\n'):
                line_text = _escape(line) if line.strip() else '&nbsp;'
                aciklama_rows.append(['', Paragraph(line_text, aciklama_text_style)])
            aciklama_table = Table(aciklama_rows, colWidths=[aciklama_stripe_w, aciklama_content_w])
            aciklama_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), _Y_ANTRASIT),
                ('BACKGROUND', (1, 0), (1, -1), colors.HexColor('#FFFCF2')),
                ('BOX', (0, 0), (-1, -1), 0.75, _Y_CIZGI_GRI),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (0, -1), 0), ('RIGHTPADDING', (0, 0), (0, -1), 0),
                ('LEFTPADDING', (1, 0), (1, -1), 10), ('RIGHTPADDING', (1, 0), (1, -1), 10),
                ('TOPPADDING', (1, 0), (1, 0), 6), ('BOTTOMPADDING', (1, 0), (1, 0), 3),
                ('TOPPADDING', (1, 1), (1, -1), 1.5), ('BOTTOMPADDING', (1, 1), (1, -1), 1.5),
                ('BOTTOMPADDING', (1, -1), (1, -1), 6),
            ]))
            elements.append(aciklama_table)
            elements.append(Spacer(1, 4*mm))

        # ===== 6) ALT BÖLÜM: TEKLİF ŞARTLARI (sol) + TOPLAM (sag) =====
        terms = _build_terms_yeni(deal, company, lang=lang)
        if termin_var:
            terms = terms + [t['termin_maddesi']]
        terms_stripe_w = 0.16*cm
        terms_w = content_w * 0.55
        terms_lines = [Paragraph(f"{i}. {term}", terms_style) for i, term in enumerate(terms, 1)]
        # Is B1 (2026-10-14): eski "BANKA · IBAN" satiri BURADAN KALDIRILDI -
        # IBAN artik SADECE ÖDEME ŞEKLİ kutusunda (Havale/EFT seciliyse) basiliyor.
        terms_content = Table([[l] for l in terms_lines], colWidths=[terms_w - terms_stripe_w - 10])
        terms_content.setStyle(TableStyle([
            ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 1), ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ]))
        terms_title = Paragraph(t['teklif_sartlari_basligi'], ParagraphStyle('YTermsTitle', parent=bold, fontSize=8.5))
        terms_box_inner = Table([[terms_title], [terms_content]], colWidths=[terms_w - terms_stripe_w - 10])
        terms_box_inner.setStyle(TableStyle([
            ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (0, 0), 3),
        ]))
        terms_box = Table([['', terms_box_inner]], colWidths=[terms_stripe_w, terms_w - terms_stripe_w])
        terms_box.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BACKGROUND', (0, 0), (0, 0), _Y_SARI),
            ('LEFTPADDING', (1, 0), (1, 0), 10), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))

        # Toplam kutusu - SADECE 3 satir
        if deal.para_birimi == 'TRY':
            toplam_haric, kdv, genel_toplam, toplam_sym = deal.subtotal, deal.vat_amount, deal.value, t['tl']
            tl_for_words = genel_toplam
        elif deal.kullanilan_kur:
            k = deal.kullanilan_kur
            toplam_haric, kdv, genel_toplam, toplam_sym = deal.subtotal * k, deal.vat_amount * k, deal.value * k, t['tl']
            tl_for_words = genel_toplam
        else:
            toplam_haric, kdv, genel_toplam, toplam_sym = deal.subtotal, deal.vat_amount, deal.value, para_sym
            tl_for_words = None
        # PAKET B Is B5: EN modda tutar-yaziyla HIC BASILMAZ (gorev tanimi
        # geregi) - t['yalniz'] None oldugunda asagida atlaniyor.
        if lang == 'en':
            tl_for_words = None

        vat_rate_label = f"{t['kdv']} ({deal.vat_rate:.0f}%)" if lang == 'en' else f"{t['kdv']} (%{deal.vat_rate:.0f})"
        totals_data = [
            [Paragraph(t['toplam_haric'], ParagraphStyle('YTotLabel', parent=normal, fontSize=8)),
             Paragraph(f"{money(toplam_haric)} {toplam_sym}", ParagraphStyle('YTotVal', parent=normal, fontSize=8, alignment=2))],
            [Paragraph(vat_rate_label, ParagraphStyle('YVatLabel', parent=normal, fontSize=8)),
             Paragraph(f"{money(kdv)} {toplam_sym}", ParagraphStyle('YVatVal', parent=normal, fontSize=8, alignment=2))],
            [Paragraph(t['genel_toplam'], ParagraphStyle('YGrandLabel', parent=normal, fontName='Vera-Bold', fontSize=9.5, textColor=colors.white)),
             Paragraph(f"{money(genel_toplam)} {toplam_sym}", ParagraphStyle('YGrandVal', parent=normal, fontName='Vera-Bold', fontSize=10, alignment=2, textColor=_Y_SARI))],
        ]
        toplam_w = content_w - terms_w - 6*mm
        totals_table = Table(totals_data, colWidths=[toplam_w * 0.5, toplam_w * 0.5])
        totals_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BACKGROUND', (0, 0), (-1, 1), _Y_TOPLAM_BG),
            ('BACKGROUND', (0, 2), (-1, 2), _Y_ANTRASIT),
            ('GRID', (0, 0), (-1, -1), 0.5, _Y_CIZGI_GRI),
            ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        totals_wrapper = [totals_table]
        if tl_for_words is not None:
            totals_wrapper.append(Spacer(1, 2*mm))
            totals_wrapper.append(Paragraph(f"{t['yalniz']} {tutar_yaziyla(tl_for_words)}", italic_style))

        # 2026-10-22: dis tablo eskiden icerikten 6 mm DAR kuruluyordu (sag
        # sutun = toplam_w, ustune 6 mm sol pay) -> ortalaninca toplam kutusu
        # urun tablosunun sag kenarindan tasiyordu. Sag sutun 6 mm payi da
        # kapsayacak sekilde genisletildi: dis tablo = icerik genisligi, urun
        # tablosuyla AYNI kenarlara oturur; toplam kutusunun kendisi degismedi.
        bottom_table = Table([[terms_box, totals_wrapper]], colWidths=[terms_w, toplam_w + 6*mm])
        bottom_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('LEFTPADDING', (1, 0), (1, 0), 6*mm),
        ]))
        elements.append(bottom_table)
    else:
        elements.append(Paragraph(t['henuz_urun_yok'], normal))

    elements.append(Spacer(1, 7*mm))

    # ===== 7) İMZA KUTULARI =====
    elements.append(Table([['']], colWidths=[content_w], rowHeights=[3], style=[('BACKGROUND', (0, 0), (-1, -1), _Y_SARI)]))
    elements.append(Spacer(1, 4*mm))
    seller_company = company.company_name or 'Lema Ambalaj'
    signature_data = [
        [t['teklifi_veren'], '', t['musteri_onayi']],
        [f'{seller_name} · {seller_company}', '', ' '],
        ['', '', ''],
        [t['kase_imza'], '', t['ad_soyad']],
        ['', '', t['kase_imza']],
        ['', '', t['tarih']],
    ]
    sig_table = Table(signature_data, colWidths=[(content_w - 2.2*cm) / 2, 2.2*cm, (content_w - 2.2*cm) / 2])
    sig_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Vera'),
        ('FONTNAME', (0, 0), (0, 0), 'Vera-Bold'), ('FONTNAME', (2, 0), (2, 0), 'Vera-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TEXTCOLOR', (0, 0), (-1, -1), _Y_ANTRASIT),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
    ]))
    elements.append(sig_table)

    def _footer_cb(canvas_obj, page_num, total_pages):
        _draw_footer_yeni(canvas_obj, doc, company, deal, page_num, total_pages, lang=lang)

    doc.build(elements, canvasmaker=lambda *a, **kw: _DealPdfCanvasYeni(*a, footer_cb=_footer_cb, **kw))
    buffer.seek(0)
    return buffer


def generate_invoice_pdf(invoice):
    """Fatura (type='fatura') veya Irsaliye (type='irsaliye') kaydi icin PDF.
    Is 2: invoice_detail sayfasinda daha once hic PDF indirme secenegi
    yoktu - hem fatura hem irsaliye icin bu tek fonksiyon kullanilir."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=1.5*cm, bottomMargin=1.5*cm)

    company = _get_company_settings_for_pdf()

    styles = getSampleStyleSheet()
    normal = ParagraphStyle('TurkishStyle', parent=styles['Normal'], fontName='Vera', fontSize=9, leading=12)
    small = ParagraphStyle('SmallStyle', parent=normal, fontSize=8, leading=10)
    heading_style = ParagraphStyle('HeadingStyle', parent=normal, fontName='Vera-Bold', fontSize=11, leading=14, spaceAfter=5)
    company_name_style = ParagraphStyle('CompanyName', parent=normal, fontName='Vera-Bold', fontSize=14, leading=17)

    is_fatura = invoice.type == 'fatura'
    # ONEMLI: bu kayit RESMI bir vergi faturasi DEGIL, sadece dahili
    # takip amacli bir kayit (gercek resmi fatura ayri bir muhasebe
    # programinda kesiliyor) - baslikta "FATURA" tek basina resmi belge
    # izlenimi verebilecegi icin notr bir ifade kullaniliyor.
    if is_fatura:
        doc_title = 'FATURA / TAHSİLAT<br/>TAKİP BELGESİ'
        title_style = ParagraphStyle('TitleStyle', parent=normal, fontName='Vera-Bold', fontSize=13, leading=16)
    else:
        doc_title = 'İRSALİYE'
        title_style = ParagraphStyle('TitleStyle', parent=normal, fontName='Vera-Bold', fontSize=18, leading=22)
    customer = invoice.customer

    elements = []

    header_left = [Paragraph(company.company_name or 'Lema Ambalaj', company_name_style)]
    if company.address:
        header_left.append(Paragraph(company.address.replace('\n', '<br/>'), small))
    contact_bits = [b for b in [
        f"Tel: {company.phone}" if company.phone else None,
        company.email or None,
    ] if b]
    if contact_bits:
        header_left.append(Paragraph(' | '.join(contact_bits), small))
    if company.tax_office or company.tax_id:
        header_left.append(Paragraph(f"V.D.: {company.tax_office or '-'}  V.No: {company.tax_id or '-'}", small))

    header_right = [
        Paragraph(doc_title, title_style),
        Spacer(1, 2*mm),
        Paragraph(f"<b>{invoice.display_no}</b>", normal),
        Paragraph(f"Tarih: {invoice.date.strftime('%d.%m.%Y') if invoice.date else '-'}", normal),
    ]
    if invoice.deal:
        header_right.append(Paragraph(f"Teklif: {invoice.deal.display_no}", normal))

    header_table = Table([[header_left, header_right]], colWidths=[10.5*cm, 6.5*cm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        # Uzun (2 satirli) "FATURA / TAHSİLAT TAKİP BELGESİ" basligi eklendikten
        # sonra iki sutun arasinda hic bosluk olmamasi (RIGHTPADDING=0) sol
        # sutundaki firma adresiyle gorsel olarak neredeyse cakisiyordu -
        # sol sutuna kucuk bir sag bosluk eklendi.
        ('RIGHTPADDING', (0, 0), (0, -1), 10),
        ('RIGHTPADDING', (1, 0), (1, -1), 0),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 4*mm))
    elements.append(Table([['']], colWidths=[17*cm], style=[('LINEBELOW', (0, 0), (-1, -1), 1, colors.HexColor('#1a252f'))]))
    elements.append(Spacer(1, 5*mm))

    elements.append(Paragraph("MÜŞTERİ BİLGİLERİ", heading_style))
    person_name = f"{_clean_for_pdf(customer.first_name) or ''} {_clean_for_pdf(customer.last_name) or ''}".strip()
    elements.append(Paragraph(f"<b>Sayın:</b> {person_name or '-'}", normal))
    if customer.company_name:
        elements.append(Paragraph(f"<b>Firma:</b> {_clean_for_pdf(customer.company_name)}", normal))
    elements.append(Paragraph(f"<b>Adres:</b> {customer.company_address or customer.address or '-'}", normal))
    elements.append(Paragraph(f"<b>V.D.:</b> {customer.tax_office or '-'}  <b>V.No:</b> {customer.tax_id or '-'}", normal))
    elements.append(Spacer(1, 5*mm))

    elements.append(Paragraph("KALEMLER", heading_style))
    # B5b (2026-10-06): eskiden burada HER ZAMAN sabit 'TL' yaziliyordu -
    # Invoice'ta para birimi alani olmadigi icin dovizli bir tekliften
    # olusturulan fatura PDF'inde tutarlar (sayi dogru olsa bile) yanlis
    # etiketleniyordu. Artik faturanin kendi para_birimi'ne gore (Deal
    # PDF'indeki ayni desen - TRY ise 'TL' metni, degilse gercek sembol -
    # TL sembolu Vera fontunda glif olarak yok, bkz. _sanitize_pdf_free_text).
    invoice_para_text = 'TL' if (invoice.para_birimi or 'TRY') == 'TRY' else invoice.para_birimi_sembol
    if invoice.items:
        data = [['Açıklama', 'Miktar', 'Birim', 'Birim Fiyat', 'Toplam']]
        for item in invoice.items:
            data.append([
                Paragraph(item.description, small),
                f"{item.quantity:.2f}",
                item.unit,
                f"{format_price_precise(item.unit_price)} {invoice_para_text}",
                f"{format_price_precise(item.total_price)} {invoice_para_text}"
            ])
        data.append(['', '', '', 'Ara Toplam:', f"{invoice.subtotal:,.2f} {invoice_para_text}"])
        data.append(['', '', '', f'KDV (%{invoice.vat_rate:.0f}):', f"{invoice.vat_amount:,.2f} {invoice_para_text}"])
        data.append(['', '', '', 'TOPLAM:', f"{invoice.total:,.2f} {invoice_para_text}"])

        table = Table(data, colWidths=[6.5*cm, 2*cm, 1.5*cm, 3.5*cm, 3.5*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a252f')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Vera-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8.5),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (-1, -3), (-1, -1), colors.HexColor('#e8f4f8')),
            ('FONTNAME', (-1, -3), (-1, -1), 'Vera-Bold'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -4), [colors.white, colors.HexColor('#f8f9fa')]),
            ('ALIGN', (-1, 0), (-1, -1), 'RIGHT'),
            ('ALIGN', (-2, 0), (-2, -1), 'RIGHT'),
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("<i>Kalem bulunmuyor.</i>", normal))

    if invoice.notes:
        elements.append(Spacer(1, 5*mm))
        elements.append(Paragraph("NOTLAR", heading_style))
        elements.append(Paragraph(_sanitize_pdf_free_text(invoice.notes), normal))

    doc.build(elements)
    buffer.seek(0)
    return buffer

def generate_is_emri_pdf(production, copy_label=None):
    """Dahili uretim talimati belgesi - fatura/irsaliye ile karistirilmamali,
    fiyat bilgisi icermez. Atolyeye elden verilmek uzere tasarlandi.
    copy_label: 'Baski Ustasi' / 'Makine Ustasi' gibi nusha etiketi (opsiyonel).

    Is 1: Birden fazla uretim kalemi varsa HER KALEM KENDI AYRI SAYFASINDA
    olusturulur (atolyede kalem basina ayri kagit/is takibi yapilabilsin
    diye) - tasarim gorseli de artik cok daha buyuk (tam genislik) basiliyor."""
    from app.models import PRODUCTION_STAGES

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.3*cm, leftMargin=1.3*cm, topMargin=1.3*cm, bottomMargin=1.3*cm)

    company = _get_company_settings_for_pdf()

    normal = ParagraphStyle('TurkishStyle', fontName='Vera', fontSize=9, leading=12)
    small = ParagraphStyle('SmallStyle', parent=normal, fontSize=7.5, leading=10)
    heading_style = ParagraphStyle('HeadingStyle', parent=normal, fontName='Vera-Bold', fontSize=11, leading=14, spaceAfter=5)
    company_name_style = ParagraphStyle('CompanyName', parent=normal, fontName='Vera-Bold', fontSize=15, leading=18)
    badge_style = ParagraphStyle('BadgeStyle', parent=normal, fontName='Vera-Bold', fontSize=15, leading=18,
                                  textColor=colors.white, alignment=1)
    copy_style = ParagraphStyle('CopyStyle', parent=normal, fontName='Vera-Bold', fontSize=9, leading=11, alignment=2)
    table_header_style = ParagraphStyle('TableHeaderIE', parent=normal, fontName='Vera-Bold', fontSize=8, leading=10,
                                         textColor=colors.white, alignment=1)
    customer_name_style = ParagraphStyle('CustomerNameBig', parent=normal, fontName='Vera-Bold', fontSize=20, leading=24)

    deal = production.deal
    customer = deal.customer
    customer_name = _clean_for_pdf(customer.company_name) if customer.company_name else \
        f"{_clean_for_pdf(customer.first_name)} {_clean_for_pdf(customer.last_name)}"

    uretim_items = production.uretim_items
    # Kalem yoksa yine de tek, bilgilendirici bir sayfa uretilsin.
    pages = uretim_items if uretim_items else [None]
    total_pages = len(pages)

    elements = []

    for page_idx, item in enumerate(pages, 1):
        # ===== 1) Firma adi (buyuk) + vergi/adres (kucuk) - solda =====
        header_left = [Paragraph(company.company_name or 'Lema Ambalaj', company_name_style)]
        legal_bits = []
        if company.address:
            legal_bits.append(company.address)
        if company.tax_office or company.tax_id:
            legal_bits.append(f"V.D.: {company.tax_office or '-'} V.No: {company.tax_id or '-'}")
        if legal_bits:
            header_left.append(Paragraph(' | '.join(legal_bits), small))

        # ===== 2) Sagda koyu arka planli "IS EMRI" rozeti =====
        badge_table = Table([[Paragraph('İŞ EMRİ', badge_style)]], colWidths=[4.5*cm], rowHeights=[1*cm])
        badge_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#1a252f')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))
        header_right = [badge_table, Spacer(1, 2*mm)]
        # ===== 3) Nusha etiketi + sayfa no =====
        if copy_label:
            header_right.append(Paragraph(f"Nüsha: {copy_label}", copy_style))
        header_right.append(Paragraph(f"IE-{production.id:05d}", copy_style))
        if total_pages > 1:
            header_right.append(Paragraph(f"Sayfa {page_idx}/{total_pages}", copy_style))
        header_right.append(Paragraph(f"Tarih: {datetime.now().strftime('%d.%m.%Y')}", copy_style))

        header_table = Table([[header_left, header_right]], colWidths=[12.5*cm, 4.7*cm])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 4*mm))
        elements.append(Table([['']], colWidths=[17.2*cm], style=[('LINEBELOW', (0, 0), (-1, -1), 1, colors.HexColor('#1a252f'))]))
        elements.append(Spacer(1, 4*mm))

        # ===== Musteri adi - buyuk punto, tabloda =====
        customer_name_table = Table([[Paragraph(customer_name, customer_name_style)]], colWidths=[17.2*cm])
        customer_name_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(customer_name_table)
        elements.append(Spacer(1, 3*mm))

        elements.append(Paragraph(f"<b>Teklif No:</b> {deal.display_no}", normal))
        # ===== 5) Teslim tarihi =====
        if production.due_date:
            elements.append(Paragraph(f"<b>Teslim Tarihi:</b> {production.due_date.strftime('%d.%m.%Y')}", normal))
        elements.append(Spacer(1, 4*mm))

        # ===== 4) Durum cubugu: Uretimde -> Hazir -> Sevkiyat =====
        if production.status != 'iptal':
            try:
                active_idx = [k for k, _ in PRODUCTION_STAGES].index(production.status)
            except ValueError:
                active_idx = -1
            status_cells = []
            for i, (key, label) in enumerate(PRODUCTION_STAGES):
                if i == active_idx:
                    fg = colors.white
                elif i < active_idx:
                    fg = colors.HexColor('#1a252f')
                else:
                    fg = colors.grey
                cell_style = ParagraphStyle(f'Stage{page_idx}_{i}', parent=normal, fontName='Vera-Bold', fontSize=8,
                                             alignment=1, textColor=fg)
                status_cells.append(Paragraph(label, cell_style))
            status_table = Table([status_cells], colWidths=[5.7*cm]*3)
            style = [('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4)]
            for i, (key, label) in enumerate(PRODUCTION_STAGES):
                bg = colors.HexColor('#1a252f') if i == active_idx else (colors.HexColor('#c8e6c9') if i < active_idx else colors.HexColor('#f0f0f0'))
                style.append(('BACKGROUND', (i, 0), (i, 0), bg))
            status_table.setStyle(TableStyle(style))
            elements.append(status_table)
            elements.append(Spacer(1, 5*mm))

        # ===== 6) Tasarim gorseli (varsa) - tam genislik, orana sadik =====
        if production.tasarim_gorseli:
            try:
                import os as _os
                img_path = _os.path.join(_os.path.dirname(__file__), 'static', production.tasarim_gorseli)
                with open(img_path, 'rb') as f:
                    img_data = f.read()
                from PIL import Image as PILImage
                PILImage.open(BytesIO(img_data)).verify()
                elements.append(Paragraph("TASARIM GÖRSELİ", heading_style))
                # Genislik tam sayfa genisligine kadar kullanilir (yatay/genis
                # gorseller icin), yukseklik 7.5cm ile sinirlanir ki alttaki
                # urun tablosu/notlar/imza alani ayni sayfada tasmadan sigsin.
                elements.append(Image(BytesIO(img_data), width=17.2*cm, height=7.5*cm, kind='proportional'))
                elements.append(Spacer(1, 4*mm))
            except Exception:
                pass

        # ===== 7) Tablo: Kagit Cinsi | Kac Kg | Baski Rengi | Olcu | Planlanan | Gerceklesen =====
        # Is 4: 'ticaret' tipi kalemler atolyede uretilmedigi icin bu dahili
        # uretim talimatina dahil edilmez (ayri, basit bir durumla takip edilir).
        elements.append(Paragraph("ÜRÜN KALEMİ", heading_style))

        if item is not None:
            headers = ['Kağıt Cinsi', 'Kaç Kg', 'Baskı Rengi', 'Ölçü', 'Planlanan Adet', 'Gerçekleşen Adet']
            data = [[Paragraph(h, table_header_style) for h in headers]]
            kagit_cell = item.kagit_tipi or item.description
            if item.kagit_tipi and item.description:
                kagit_cell = f"{item.kagit_tipi}<br/><font size=6>{item.description}</font>"
            data.append([
                Paragraph(kagit_cell, small),
                item.kac_kg or '-',
                item.baski_bilgisi or '-',
                item.olcu or '-',
                f"{item.planned_quantity:.0f} {item.unit}",
                f"{item.produced_quantity:.0f} {item.unit}" if item.produced_quantity else '-'
            ])
            table = Table(data, colWidths=[4.5*cm, 2.2*cm, 3*cm, 2.5*cm, 2.5*cm, 2.5*cm], repeatRows=1)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a252f')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('FONTNAME', (0, 1), (-1, -1), 'Vera'),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
                ('TOPPADDING', (0, 0), (-1, 0), 4),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 4),
            ]))
            elements.append(table)
        else:
            elements.append(Paragraph("<i>Ürün kalemi bulunamadı.</i>", normal))

        elements.append(Spacer(1, 6*mm))
        elements.append(Paragraph("NOTLAR", heading_style))
        # Onceden bu kutu her zaman bos ciziliyordu - production.notes hic
        # okunmuyordu, dijital olarak kaydedilen not atolyeye elden verilen
        # kagitta hic gorunmuyordu. Simdi kayitli not varsa kutunun icine
        # yaziliyor, yine de elle ek not icin bosluk birakiliyor.
        notes_style = ParagraphStyle('IsEmriNotes', parent=normal, fontSize=8.5, leading=11)
        notes_content = Paragraph(_sanitize_pdf_free_text(production.notes), notes_style) if production.notes else ''
        notes_table = Table([[notes_content]], colWidths=[17.2*cm], rowHeights=[2.5*cm])
        notes_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.5, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
        ]))
        elements.append(notes_table)
        elements.append(Spacer(1, 8*mm))

        # ===== 8) UC imza alani =====
        signature_data = [
            ['Üretimi Yapan:', '', 'Kontrol Eden:', '', 'Teslim Alan:'],
            ['', '', '', '', ''],
            ['', '', '', '', ''],
            ['Adı Soyadı:', '', 'Adı Soyadı:', '', 'Adı Soyadı:'],
            ['Tarih:', '', 'Tarih:', '', 'Tarih:'],
        ]
        signature_table = Table(signature_data, colWidths=[5*cm, 1.1*cm, 5*cm, 1.1*cm, 5*cm])
        signature_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Vera'),
            ('FONTNAME', (0, 0), (0, 0), 'Vera-Bold'),
            ('FONTNAME', (2, 0), (2, 0), 'Vera-Bold'),
            ('FONTNAME', (4, 0), (4, 0), 'Vera-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8.5),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('LINEBELOW', (0, 2), (0, 2), 1, colors.black),
            ('LINEBELOW', (2, 2), (2, 2), 1, colors.black),
            ('LINEBELOW', (4, 2), (4, 2), 1, colors.black),
        ]))
        elements.append(signature_table)

        if page_idx < total_pages:
            elements.append(PageBreak())

    doc.build(elements)
    buffer.seek(0)
    return buffer

# ===== 2026-10-26: IS EMRI - YATAY (A4 landscape), KALEM BAZLI YENI TASARIM =====
# Eski generate_is_emri_pdf() SILINMEDI - /production/<id>/is-emri?klasik=1 ile
# hala alinabilir. Yeni tasarim teklif PDF'inin gorsel dilini kullanir (sari
# #FBC213 / antrasit #353639, vitrin gorsel karti, ince olcu cizgileri).

_IE_ZEMIN_UYARI = colors.HexColor('#FFF3C4')
_IE_NOT_ZEMIN = colors.HexColor('#FFFCF2')
_IE_ETIKET_GRI = colors.HexColor('#777777')
_IE_ETIKET_ZEMIN = colors.HexColor('#F7F6F2')

_KESE_ACIKLAMA_RE = re.compile(r'(\d{3,4})\s*(?:gr|g)\b', re.IGNORECASE)


def _ie_temiz(v):
    """'None', 'NonexNone', bos -> None; diger metinler kirpilmis haliyle."""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    if re.fullmatch(r'(?i)(none|null|-|nonexnone|none\s*x\s*none)', s):
        return None
    s = re.sub(r'(?i)\bnone\b', '', s).strip(' x×-')
    return s or None


def kese_gramaj_bul(deal_item, katalog=None):
    """Kalemin kese numarasini (gr) bulur: (1) kaydedilmis kese_gramaj,
    (2) urun adindaki '1000 gr ... kese' ifadesi, (3) en/boy/korugu SAYI
    olarak KeseGramajKatalog'daki bir satirla birebir esitse o gramaj.
    Bulunamazsa None - is emrinde satir gosterilmez/'-' yazilir."""
    if deal_item is None:
        return None
    g = getattr(deal_item, 'kese_gramaj', None)
    if g:
        return int(g)
    desc = (getattr(deal_item, 'description', '') or '')
    if 'kese' in desc.casefold():
        m = _KESE_ACIKLAMA_RE.search(desc)
        if m:
            return int(m.group(1))
    if katalog:
        def num(x):
            _, v = _olcu_degeri(x)
            return v
        en, boy, kor = num(deal_item.en), num(deal_item.boy), num(deal_item.korugu)
        if en and boy:
            for k in katalog:
                if (num(k.olcu_en) == en and num(k.olcu_boy) == boy
                        and (kor is None or num(k.olcu_korugu) in (None, kor))):
                    return int(k.gramaj)
    return None


_ADDAN_OLCU_RE = re.compile(
    r'(\d+(?:[.,]\d+)?)\s*[x×X*]\s*(\d+(?:[.,]\d+)?)'
    r'(?:\s*[x×X*]\s*(\d+(?:[.,]\d+)?))?'
    r'(?:\s*\(\s*(\d+(?:[.,]\d+)?(?:\s*\+\s*\d+(?:[.,]\d+)?)?)\s*\))?')
_ADDAN_MALZEME = ['gold metalize', 'gümüş metalize', 'metalize', 'şeffaf', 'esmer recycle', 'esmer virjin',
                  'beyaz kraft', 'beyaz virjin', 'kuşe', 'esmer', 'kraft', 'beyaz']
_ADDAN_OZELLIK = ['kare dipli', 'dipsiz', 'kilitli', 'pencereli', 'zipli', 'valfli', 'tabanlı', 'körüklü']


def _tr_lower(s):
    return (s or '').replace('I', 'ı').replace('İ', 'i').lower()


def _tr_baslik(s):
    return ' '.join((w[:1].replace('i', 'İ').replace('ı', 'I').upper() + w[1:]) for w in s.split())


def addan_detaylar(ad):
    """2026-10-26: urun ADINDAN olcu / malzeme / ozellik cikarir - kalemin
    kendi alanlari BOSSA is emrinde onlarin yerine yazilir (dolu alan her
    zaman onceliklidir). '... doypack 16×27 (4+4)' -> en 16, boy 27, korugu
    '4+4'; 'gold metalize' -> malzeme; 'kilitli' -> ozellik."""
    sonuc = {'en': None, 'boy': None, 'korugu': None, 'malzeme': None, 'ozellik': None}
    if not ad:
        return sonuc
    m = _ADDAN_OLCU_RE.search(ad)
    if m:
        sonuc['en'], sonuc['boy'] = m.group(1), m.group(2)
        sonuc['korugu'] = m.group(3) or (m.group(4).replace(' ', '') if m.group(4) else None)
    kucuk = _tr_lower(ad)
    desen = re.compile('|'.join(re.escape(k) for k in sorted(_ADDAN_MALZEME, key=len, reverse=True)))
    bulunan = []
    for m2 in desen.finditer(kucuk):
        if m2.group(0) not in bulunan:
            bulunan.append(m2.group(0))
    if bulunan:
        sonuc['malzeme'] = _tr_baslik(' '.join(bulunan))
    oz = [_tr_baslik(k) for k in _ADDAN_OZELLIK if k in kucuk]
    if oz:
        sonuc['ozellik'] = ' · '.join(oz)
    return sonuc


def _ayrintili_malzeme(alan, addan):
    """2026-10-27: kalemin malzeme alani dolu ama urun adindaki malzemenin
    BIR PARCASIYSA (alan 'gold', ad 'seffaf gold metalize') daha ayrintili
    olan yazilir. Alan farkli bir sey soyluyorsa ('Kraft') alan kazanir."""
    if not alan:
        return addan
    if addan and _tr_lower(alan) in _tr_lower(addan) and len(addan) > len(alan):
        return addan
    return alan


def is_emri_kalemleri(production):
    """2026-10-26 (2): is emrine giren TUM kalemler - uretim VE ticaret
    (ticaret kalemleri 'TEDARIK' is emri olarak basilir, artik atlanmaz).
    Sira = ProductionItem.id (numara IE-xxxxx-n bu siradan gelir; PDF,
    /is-emirleri ve Gunluk Uretim secicisi AYNI numarayi kullanir)."""
    items = getattr(production, 'items', None)
    if items is None:
        items = list(getattr(production, 'uretim_items', []) or [])
    return sorted(items, key=lambda i: (i.id or 0))


def _teslim_yeri(deal, company):
    """Teklif sartlarindaki 'Teslim yeri: ...' maddesinden degeri alir
    (sirket ayarlarindaki serbest metin, yoksa varsayilan sartlar)."""
    try:
        satirlar = _build_terms_yeni(deal, company)
    except Exception:
        satirlar = list(_DEFAULT_TERMS_YENI)
    for s in satirlar:
        m = re.match(r'\s*teslim\s*(yeri|şekli|sekli)\s*:\s*(.+)', s, re.IGNORECASE)
        if m:
            return m.group(2).strip().rstrip('.')
    return None


def _is_gunu_ekle(baslangic, gun):
    d = baslangic
    eklenen = 0
    from datetime import timedelta as _td
    while eklenen < gun:
        d = d + _td(days=1)
        if d.weekday() < 5:
            eklenen += 1
    return d


def is_emri_kalem_bilgisi(production, pitem, sira, toplam, katalog=None):
    """Bir uretim kaleminin is emrinde/takip ekraninda gosterilen TUM
    degerlerini tek yerde hesaplar (PDF ve /is-emirleri ayni sonucu
    gostersin diye). Veritabanina YAZMAZ."""
    deal = production.deal
    di = None
    if pitem is not None and pitem.deal_item_id:
        di = next((x for x in deal.items if x.id == pitem.deal_item_id), None)
    if di is None and pitem is not None:
        # Teklif onaydan sonra duzenlendiyse kalemler yeniden olusmus olabilir -
        # ayni aciklamali kalemle eslestir.
        di = next((x for x in deal.items if x.description == pitem.description), None)

    urun_adi = (pitem.description if pitem is not None else None) or (di.description if di else '')
    addan = addan_detaylar(urun_adi)
    en_txt, en_val = _olcu_degeri(di.en) if di else (None, None)
    boy_txt, boy_val = _olcu_degeri(di.boy) if di else (None, None)
    kor_txt, _ = _olcu_degeri(di.korugu) if di else (None, None)
    # Kalemde olcu girilmemisse urun adindaki olcu kullanilir (dolu alan oncelikli)
    if not en_txt and not boy_txt and addan['en']:
        en_txt, en_val = _olcu_degeri(addan['en'])
        boy_txt, boy_val = _olcu_degeri(addan['boy'])
        if not kor_txt and addan['korugu']:
            kor_txt, _ = _olcu_degeri(addan['korugu'])
    parca = [x for x in (en_txt, boy_txt, kor_txt) if x]
    if parca:
        olcu = ' × '.join(parca) + ' cm'
    else:
        olcu = _ie_temiz(pitem.olcu) if pitem is not None else None

    birim = (pitem.unit if pitem is not None else None) or 'adet'
    planlanan = pitem.planned_quantity if pitem is not None else 0
    gerceklesen = 0
    if pitem is not None:
        gerceklesen = pitem.produced_quantity or 0
        if birim == 'kg':
            kg = sum((o.toplam_kg or 0) for o in (pitem.daily_outputs or []))
            if len([x for x in is_emri_kalemleri(production) if (getattr(x, 'urun_tipi', None) or 'uretim') != 'ticaret']) == 1:
                kg += sum((o.toplam_kg or 0) for o in (production.daily_outputs or [])
                          if getattr(o, 'production_item_id', None) is None)
            gerceklesen = max(gerceklesen, kg)
    # 2026-10-27 (Sevk/fatura korumalari): musteriye GONDERILEN mal uretilmis
    # sayilir - gunluk uretim girilmeden acil sevk edilen koliler "Kalan"i
    # sisirmesin. Toplanmaz, en buyugu alinir (ayni koli iki kez sayilmaz).
    uretim_kaydi = gerceklesen
    gonderilen = 0
    if pitem is not None and di is not None and (not pitem.unit or not di.unit or pitem.unit == di.unit):
        try:
            from app.kalem_belge import gonderilen_haritasi
            gonderilen = (gonderilen_haritasi(production).get(di.id) or {}).get('toplam', 0) or 0
        except Exception:
            gonderilen = 0
    gerceklesen = max(gerceklesen, gonderilen)

    termin = None
    termin_gun = (getattr(di, 'termin_gun', None) if di else None) or getattr(deal, 'varsayilan_termin_gun', None)
    baslangic = production.start_date or (production.created_at.date() if production.created_at else None)
    if termin_gun and baslangic:
        termin = _is_gunu_ekle(baslangic, int(termin_gun))
    elif di is not None and di.teslim_tarihi:
        termin = di.teslim_tarihi
    elif production.due_date:
        termin = production.due_date

    tip = (getattr(pitem, 'urun_tipi', None) or 'uretim') if pitem is not None else 'uretim'
    if tip == 'ticaret':
        from app.models import TICARET_STAGE_LABELS
        gerceklesen = 0
    if production.status == 'iptal':
        durum = 'İptal'
    elif tip == 'ticaret' and production.status != 'sevkiyat':
        durum = TICARET_STAGE_LABELS.get(getattr(pitem, 'ticaret_durumu', None) or 'siparis_edildi', 'Sipariş edildi')
    elif production.status == 'sevkiyat':
        durum = 'Sevk edildi'
    elif planlanan and gerceklesen >= planlanan:
        durum = 'Hazır'
    elif gerceklesen > 0:
        durum = 'Üretimde'
    else:
        durum = 'Bekliyor'

    # Gorsel onceligi: kalemin numune gorseli -> uretimin/musterinin tasarim gorseli.
    gorsel = (di.numune_gorseli if di is not None and di.numune_gorseli else None)
    gorsel_kaynak = 'numune' if gorsel else None
    if not gorsel:
        try:
            tg = production.tasarim_gorseli
        except Exception:
            tg = None
        if tg:
            gorsel, gorsel_kaynak = tg, 'tasarim'

    return {
        'tip': tip,
        'ticaret_durumu': (getattr(pitem, 'ticaret_durumu', None) or 'siparis_edildi') if tip == 'ticaret' else None,
        'no': f'IE-{production.id:05d}-{sira}',
        'sira': sira, 'toplam': toplam,
        'deal_item': di,
        'urun': (pitem.description if pitem is not None else '-'),
        'kese_gramaj': kese_gramaj_bul(di, katalog),
        'kagit': _ayrintili_malzeme(_ie_temiz(pitem.kagit_tipi if pitem is not None else None) or _ie_temiz(di.kagit_cinsi if di else None), addan['malzeme']),
        'ozellik': addan['ozellik'],
        'gramaj': _ie_temiz(pitem.gramaj if pitem is not None else None),
        'olcu': olcu,
        'en_txt': en_txt if en_val else None, 'boy_txt': boy_txt if boy_val else None, 'kor_txt': kor_txt,
        'baski': _ie_temiz(pitem.baski_bilgisi if pitem is not None else None) or _ie_temiz(di.renk if di else None),
        'birim': birim,
        'planlanan': planlanan, 'gerceklesen': gerceklesen,
        'uretim_kaydi': uretim_kaydi if tip != 'ticaret' else 0, 'gonderilen': gonderilen,
        'gunluk_eksik': bool(tip != 'ticaret' and gonderilen > (uretim_kaydi or 0) + 0.0005),
        'kalan': max((planlanan or 0) - (gerceklesen or 0), 0),
        'termin': termin, 'durum': durum,
        'koli_baskisiz': bool(di is not None and getattr(di, 'koli_tipi', None) == 'baskisiz'),
        'gorsel': gorsel, 'gorsel_kaynak': gorsel_kaynak,
        'not': _ie_temiz(pitem.notes if pitem is not None else None),
    }


def _ie_metin_sigdir(c, text, font, size, max_w, min_size=6):
    while size > min_size and c.stringWidth(text, font, size) > max_w:
        size -= 0.5
    if c.stringWidth(text, font, size) > max_w:
        while text and c.stringWidth(text + '…', font, size) > max_w:
            text = text[:-1]
        text = text.rstrip() + '…'
    return text, size


def _ie_paragraf(c, html, x, y_top, w, h, style):
    """Paragrafi (x, y_top) sol-ust koseden w genisligine sarar; h'ye sigmazsa
    punto kucultulur (en az 6). Cizilen yuksekligi dondurur."""
    st = style
    p = Paragraph(html, st)
    _, ph = p.wrap(w, h)
    size = st.fontSize
    while ph > h and size > 6:
        size -= 0.5
        st = ParagraphStyle(st.name + 'k', parent=st, fontSize=size, leading=size * 1.25)
        p = Paragraph(html, st)
        _, ph = p.wrap(w, h)
    if ph > h:
        return 0
    p.drawOn(c, x, y_top - ph)
    return ph


def _ie_vitrin_buyuk(c, x, y, w, h, gorsel_yolu, etiket, en_txt, boy_txt):
    """Sag yari: buyuk numune gorseli - teklif vitrinine benzer (gri zemin,
    beyaz kart, sari L koseler, ince olcu cizgileri). Gorsel yoksa kesik
    cizgili 'NUMUNE YAPISTIRMA ALANI'. True = gorsel cizildi."""
    c.saveState()
    c.setFillColor(_V_ZEMIN)
    c.rect(x, y, w, h, fill=1, stroke=0)
    yuklu = _vitrin_gorsel_yukle_buyuk(gorsel_yolu) if gorsel_yolu else None
    pad = 0.45 * cm
    if not yuklu:
        c.setStrokeColor(colors.HexColor('#B8B4AA'))
        c.setLineWidth(1)
        c.setDash(5, 4)
        c.rect(x + pad, y + pad, w - 2 * pad, h - 2 * pad, fill=0, stroke=1)
        c.setDash()
        c.setFillColor(colors.HexColor('#9A9A9A'))
        c.setFont('Vera-Bold', 13)
        c.drawCentredString(x + w / 2, y + h / 2 + 4, 'NUMUNE YAPIŞTIRMA ALANI')
        c.setFont('Vera', 8)
        c.drawCentredString(x + w / 2, y + h / 2 - 12, 'Bu kalem için görsel yüklenmemiş - fiziksel numuneyi buraya iliştirin')
        c.restoreState()
        return False
    reader, pw, ph = yuklu
    bant = 14
    alt = bant if en_txt else 0
    sag = bant if boy_txt else 0
    ax, ay = x + pad, y + pad + alt
    aw, ah = w - 2 * pad - sag, h - 2 * pad - alt
    pay = 5
    olcek = min((aw - 2 * pay) / pw, (ah - 2 * pay) / ph)
    iw, ih = pw * olcek, ph * olcek
    cw, ch = iw + 2 * pay, ih + 2 * pay
    cx, cy = ax + (aw - cw) / 2, ay + (ah - ch) / 2
    c.setFillColor(_V_CERCEVE)
    c.rect(cx + 1.2, cy - 1.2, cw, ch, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setStrokeColor(_V_CERCEVE)
    c.setLineWidth(0.5)
    c.rect(cx, cy, cw, ch, fill=1, stroke=1)
    c.drawImage(reader, cx + pay, cy + pay, iw, ih, mask='auto')
    L = min(0.8 * cm, cw / 3, ch / 3)
    c.setStrokeColor(_Y_SARI)
    c.setLineWidth(3)
    c.line(cx - 1.5, cy + ch, cx + L, cy + ch)
    c.line(cx, cy + ch + 1.5, cx, cy + ch - L)
    c.line(cx + cw + 1.5, cy, cx + cw - L, cy)
    c.line(cx + cw, cy - 1.5, cx + cw, cy + L)
    c.setFont('Helvetica', 8)
    tw = c.stringWidth(etiket, 'Helvetica', 8)
    c.setFillColor(colors.white)
    c.rect(cx + pay, cy + pay, tw + 6, 11, fill=1, stroke=0)
    c.setFillColor(_V_ETIKET)
    c.drawString(cx + pay + 3, cy + pay + 3, etiket)
    c.setStrokeColor(_V_OLCU_CIZGI)
    c.setLineWidth(0.6)
    c.setFont('Helvetica', 8)
    if en_txt:
        yy = cy - 8
        c.line(cx, yy, cx + cw, yy)
        c.line(cx, yy - 3, cx, yy + 3)
        c.line(cx + cw, yy - 3, cx + cw, yy + 3)
        lbl = f'{en_txt} cm'
        lw = c.stringWidth(lbl, 'Helvetica', 8)
        mx = cx + cw / 2
        c.setFillColor(_V_ZEMIN)
        c.rect(mx - lw / 2 - 2, yy - 4, lw + 4, 8, fill=1, stroke=0)
        c.setFillColor(_V_OLCU_YAZI)
        c.drawCentredString(mx, yy - 2.8, lbl)
    if boy_txt:
        xx = cx + cw + 8
        c.line(xx, cy, xx, cy + ch)
        c.line(xx - 3, cy, xx + 3, cy)
        c.line(xx - 3, cy + ch, xx + 3, cy + ch)
        lbl = f'{boy_txt} cm'
        lw = c.stringWidth(lbl, 'Helvetica', 8)
        c.translate(xx, cy + ch / 2)
        c.rotate(90)
        c.setFillColor(_V_ZEMIN)
        c.rect(-lw / 2 - 2, -4, lw + 4, 8, fill=1, stroke=0)
        c.setFillColor(_V_OLCU_YAZI)
        c.drawCentredString(0, -2.8, lbl)
    c.restoreState()
    return True


_IE_HEDEF_PX = 1400  # ~12 cm kutuda ~300 dpi


def _ie_logo_reader(company):
    logo_buf = _logo_for_pdf_yeni(company.logo_data) if company.logo_data else None
    if not logo_buf:
        return None
    try:
        return ImageReader(logo_buf)
    except Exception:
        return None


# 2026-10-27: toplu PDF sirasinda dolu - ayni gorsel bir kez islenir, daha
# kucuk hedef cozunurluk (cikti boyutu + sure). Tekli PDF'te None (degisiklik yok).
_IE_TOPLU = None


def _vitrin_gorsel_yukle_buyuk(path_rel):
    if _IE_TOPLU is not None:
        onb = _IE_TOPLU['gorsel']
        if path_rel not in onb:
            onb[path_rel] = _toplu_gorsel_yukle(path_rel, _IE_TOPLU['px'])
        return onb[path_rel]
    return _vitrin_gorsel_yukle_buyuk_ham(path_rel, _IE_HEDEF_PX)


def _toplu_gorsel_yukle(path_rel, hedef_px):
    """Toplu PDF icin hizli/kucuk gorsel: JPEG'i dogrudan dusuk olcekte
    acar (draft), kucultur, JPEG kalite 80 ile gomer. Tekli is emri ve teklif
    PDF'i bunu KULLANMAZ (onlar tam kalite)."""
    path = path_rel
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', path_rel)
    try:
        from PIL import Image as PILImage, ImageOps
        im = PILImage.open(path)
        try:
            im.draft('RGB', (hedef_px, hedef_px))
        except Exception:
            pass
        im = ImageOps.exif_transpose(im)
        im.thumbnail((hedef_px, hedef_px), PILImage.BILINEAR)
        out = BytesIO()
        if im.mode in ('RGBA', 'LA', 'P'):
            im.convert('RGBA').save(out, 'PNG', optimize=False)
        else:
            im.convert('RGB').save(out, 'JPEG', quality=80)
        out.seek(0)
        return ImageReader(out), im.size[0], im.size[1]
    except Exception:
        return None


def _vitrin_gorsel_yukle_buyuk_ham(path_rel, hedef_px):
    """Is emri sag yarisi icin: _vitrin_gorsel_yukle ile ayni kalite kurali,
    ama daha buyuk hedef (uzun kenar en fazla ~1400 px - orijinal kucukse
    ASLA buyutulmez)."""
    path = path_rel
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', path_rel)
    global _VITRIN_HEDEF_PX
    eski = _VITRIN_HEDEF_PX
    try:
        _VITRIN_HEDEF_PX = hedef_px
        return _vitrin_gorsel_yukle(path)
    finally:
        _VITRIN_HEDEF_PX = eski


def _ie_kutu_isareti(c, x, y, boyut, isaretli):
    c.saveState()
    c.setStrokeColor(_Y_ANTRASIT)
    c.setLineWidth(0.9)
    c.rect(x, y, boyut, boyut, fill=0, stroke=1)
    if isaretli:
        c.setLineWidth(1.4)
        c.line(x + boyut * 0.2, y + boyut * 0.5, x + boyut * 0.42, y + boyut * 0.22)
        c.line(x + boyut * 0.42, y + boyut * 0.22, x + boyut * 0.82, y + boyut * 0.82)
    c.restoreState()


def _ie_uyari_ucgen(c, x, y, s):
    c.saveState()
    c.setFillColor(_Y_ANTRASIT)
    p = c.beginPath()
    p.moveTo(x, y)
    p.lineTo(x + s, y)
    p.lineTo(x + s / 2, y + s * 0.88)
    p.close()
    c.drawPath(p, fill=1, stroke=0)
    c.setFillColor(_Y_SARI)
    c.setFont('Vera-Bold', s * 0.62)
    c.drawCentredString(x + s / 2, y + s * 0.14, '!')
    c.restoreState()


def generate_is_emri_pdf_yatay(production, copy_label=None, item_ids=None, _c=None, _ortak=None):
    """YENI is emri: A4 YATAY, her uretim kalemi AYRI SAYFA (IE-00127-1, -2...).
    item_ids verilirse sadece o ProductionItem'lar basilir (tek kalem yazdirma).
    Fiyat bilgisi ICERMEZ. Veritabanina hicbir sey YAZMAZ.
    2026-10-27 (toplu hiz): _c verilirse sayfalar O canvas'a cizilir (toplu PDF
    tek canvas'ta uretilir, PDF birlestirme yok); _ortak = {'katalog','company',
    'logo_reader'} bir kez hesaplanip tum siparislerde kullanilir."""
    from reportlab.lib.pagesizes import landscape
    from app.models import KeseGramajKatalog
    if _ortak is not None:
        katalog = _ortak['katalog']
        company = _ortak['company']
    else:
        try:
            katalog = KeseGramajKatalog.query.all()
        except Exception:
            katalog = []
        company = _get_company_settings_for_pdf()
    deal = production.deal
    customer = deal.customer
    musteri = _clean_for_pdf(customer.company_name) if customer.company_name else \
        f"{_clean_for_pdf(customer.first_name) or ''} {_clean_for_pdf(customer.last_name) or ''}".strip()

    tum = is_emri_kalemleri(production)
    toplam = len(tum)
    secili = [(i, p) for i, p in enumerate(tum, 1) if not item_ids or p.id in item_ids]
    if not secili:
        secili = [(1, None)]
        toplam = max(toplam, 1)

    PW, PH = landscape(A4)
    M = 1.1 * cm
    CW = PW - 2 * M
    buf = None
    if _c is None:
        buf = BytesIO()
        c = _PDFCanvas(buf, pagesize=(PW, PH))
        c.setTitle(f'İş Emri IE-{production.id:05d}')
    else:
        c = _c

    etiket_st = ParagraphStyle('IEEt', fontName='Vera', fontSize=6.6, leading=8, textColor=_IE_ETIKET_GRI)
    deger_st = ParagraphStyle('IEDeger', fontName='Vera-Bold', fontSize=9.5, leading=11.5, textColor=_Y_ANTRASIT)
    not_st = ParagraphStyle('IENot', fontName='Vera', fontSize=8.5, leading=10.5, textColor=colors.HexColor('#333333'))

    if _ortak is not None:
        logo_reader = _ortak.get('logo_reader')
    else:
        logo_reader = _ie_logo_reader(company)

    # 2026-10-26 (2): siparis bilgileri (2. serit) - fiyat/odeme YOK (atolye kagidi)
    seller = getattr(deal, 'seller', None)
    satis = (getattr(seller, 'full_name', None) or getattr(seller, 'username', None) or '-') if seller else '-'
    teslim_sekli = _teslim_yeri(deal, company) or '-'
    n_ticaret = sum(1 for x in tum if (getattr(x, 'urun_tipi', None) or 'uretim') == 'ticaret')
    n_uretim = len(tum) - n_ticaret
    parca = []
    if n_uretim:
        parca.append(f'{n_uretim} üretim')
    if n_ticaret:
        parca.append(f'{n_ticaret} tedarik')
    siparis_ozet = f"{len(tum)} kalem" + (f" ({', '.join(parca)})" if parca and len(parca) > 1 else '')

    sayfa_sayisi = len(secili)
    for sayfa_idx, (sira, pitem) in enumerate(secili, 1):
        b = is_emri_kalem_bilgisi(production, pitem, sira, toplam, katalog)
        top = PH - M

        # ===== BASLIK: logo | IS EMRI | firma =====
        hdr_h = 1.75 * cm
        if logo_reader:
            lw, lh = logo_reader.getSize()
            olc = min(5.0 * cm / lw, hdr_h / lh)
            c.drawImage(logo_reader, M, top - lh * olc - (hdr_h - lh * olc) / 2, lw * olc, lh * olc, mask='auto')
        else:
            c.setFillColor(_Y_ANTRASIT)
            c.rect(M, top - hdr_h + 0.2 * cm, 4.2 * cm, hdr_h - 0.4 * cm, fill=1, stroke=0)
            c.setFillColor(_Y_SARI)
            ad, sz = _ie_metin_sigdir(c, (company.company_name or 'LEMA').upper(), 'Vera-Bold', 12, 3.8 * cm)
            c.setFont('Vera-Bold', sz)
            c.drawCentredString(M + 2.1 * cm, top - hdr_h / 2 - 4, ad)

        ticaret = b['tip'] == 'ticaret'
        c.setFillColor(_Y_ANTRASIT)
        c.setFont('Vera-Bold', 22)
        c.drawCentredString(PW / 2, top - 0.95 * cm, 'İ Ş   E M R İ')
        c.setFont('Vera', 9)
        c.setFillColor(colors.HexColor('#666666'))
        alt_bas = f'Kalem {sira} / {toplam}'
        alt_bas_y = top - 1.5 * cm
        if copy_label:
            alt_bas += f'   ·   Nüsha: {copy_label}'
        if ticaret:
            # tedarik: baslik ayni, alt satirda mavi "TEDARIK" etiketi (firma bloguna tasmasin)
            et = 'TEDARİK'
            tw = c.stringWidth(alt_bas, 'Vera', 9)
            ew = c.stringWidth(et, 'Vera-Bold', 8) + 10
            x0 = PW / 2 - (tw + 6 + ew) / 2
            c.drawString(x0, alt_bas_y, alt_bas)
            c.setFillColor(colors.HexColor('#1B4F8A'))
            c.roundRect(x0 + tw + 6, alt_bas_y - 3, ew, 12, 2, fill=1, stroke=0)
            c.setFillColor(colors.white)
            c.setFont('Vera-Bold', 8)
            c.drawString(x0 + tw + 11, alt_bas_y, et)
        else:
            c.drawCentredString(PW / 2, alt_bas_y, alt_bas)

        sag_x = PW - M
        firma_w = 8.6 * cm
        ad, sz = _ie_metin_sigdir(c, (company.company_name or 'Lema Ambalaj').upper(), 'Vera-Bold', 9, firma_w)
        c.setFillColor(_Y_ANTRASIT)
        c.setFont('Vera-Bold', sz)
        c.drawRightString(sag_x, top - 0.45 * cm, ad)
        satirlar = []
        if company.address:
            satirlar.append(' '.join(str(company.address).split()))
        vd = []
        if company.tax_office:
            vd.append(f'{company.tax_office}')
        if company.tax_id:
            vd.append(f'VKN {company.tax_id}')
        if company.phone:
            vd.append(f'Tel {company.phone}')
        if vd:
            satirlar.append(' · '.join(vd))
        c.setFont('Vera', 7)
        c.setFillColor(colors.HexColor('#555555'))
        yy = top - 0.85 * cm
        for s in satirlar[:3]:
            s2, sz2 = _ie_metin_sigdir(c, s, 'Vera', 7, firma_w, 5.5)
            c.setFont('Vera', sz2)
            c.drawRightString(sag_x, yy, s2)
            yy -= 0.33 * cm

        y = top - hdr_h - 0.15 * cm
        c.setStrokeColor(_Y_SARI)
        c.setLineWidth(3)
        c.line(M, y, PW - M, y)
        c.setStrokeColor(_Y_ANTRASIT)
        c.setLineWidth(1)
        c.line(M, y - 3.5, PW - M, y - 3.5)
        y -= 0.45 * cm

        # ===== BILGI SERIDI (6 kutu + siparis bilgileri satiri) =====
        strip_h = 0.95 * cm
        siparis_tarihi = production.start_date or (production.created_at.date() if production.created_at else None)
        kutular = [
            ('İŞ EMRİ NO', b['no']),
            ('TARİH', datetime.now().strftime('%d.%m.%Y')),
            ('TEKLİF NO', deal.display_no),
            ('SİPARİŞ TARİHİ', siparis_tarihi.strftime('%d.%m.%Y') if siparis_tarihi else '-'),
            ('TERMİN', b['termin'].strftime('%d.%m.%Y') if b['termin'] else '-'),
            ('DURUM', b['durum']),
        ]
        kw = CW / len(kutular)
        c.setStrokeColor(_Y_ANTRASIT)
        c.setLineWidth(1)
        c.rect(M, y - strip_h, CW, strip_h, fill=0, stroke=1)
        for i, (et, dg) in enumerate(kutular):
            kx = M + i * kw
            if i:
                c.setStrokeColor(_Y_CIZGI_GRI)
                c.setLineWidth(0.5)
                c.line(kx, y - strip_h + 3, kx, y - 3)
            c.setFillColor(_IE_ETIKET_GRI)
            c.setFont('Vera', 6.6)
            c.drawString(kx + 7, y - 0.35 * cm, et)
            dg2, dsz = _ie_metin_sigdir(c, str(dg), 'Vera-Bold', 11, kw - 14, 7)
            c.setFillColor(_Y_ANTRASIT)
            c.setFont('Vera-Bold', dsz)
            c.drawString(kx + 7, y - 0.77 * cm, dg2)
        # 2. satir: siparis bilgileri (her kutu 2 sutun genisliginde)
        y2 = y - strip_h
        c.setStrokeColor(_Y_ANTRASIT)
        c.setLineWidth(1)
        c.rect(M, y2 - strip_h, CW, strip_h, fill=0, stroke=1)
        kw2 = CW / 3
        for i, (et, dg) in enumerate([('SATIŞ TEMSİLCİSİ', satis), ('TESLİM ŞEKLİ', teslim_sekli), ('SİPARİŞTE', siparis_ozet)]):
            kx = M + i * kw2
            if i:
                c.setStrokeColor(_Y_CIZGI_GRI)
                c.setLineWidth(0.5)
                c.line(kx, y2 - strip_h + 3, kx, y2 - 3)
            c.setFillColor(_IE_ETIKET_GRI)
            c.setFont('Vera', 6.6)
            c.drawString(kx + 7, y2 - 0.35 * cm, et)
            dg2, dsz = _ie_metin_sigdir(c, str(dg), 'Vera-Bold', 10, kw2 - 14, 7)
            c.setFillColor(_Y_ANTRASIT)
            c.setFont('Vera-Bold', dsz)
            c.drawString(kx + 7, y2 - 0.77 * cm, dg2)
        y = y2 - strip_h - 0.3 * cm

        # ===== GOVDE: sol bilgiler | sag gorsel =====
        imza_h = 1.45 * cm
        footer_ust = 1.05 * cm
        govde_alt = footer_ust + imza_h + 0.35 * cm
        gap = 0.5 * cm
        sol_w = CW * 0.5 - gap / 2
        sag_w = CW - sol_w - gap
        sol_x = M
        sag_xx = M + sol_w + gap
        govde_ust = y

        # -- Musteri kutusu --
        mus_h = 1.25 * cm
        c.setFillColor(_Y_SARI)
        c.rect(sol_x, y - mus_h, 4, mus_h, fill=1, stroke=0)
        c.setFillColor(_IE_ETIKET_GRI)
        c.setFont('Vera', 6.6)
        c.drawString(sol_x + 11, y - 0.33 * cm, 'MÜŞTERİ')
        mtxt, msz = _ie_metin_sigdir(c, musteri.upper(), 'Vera-Bold', 16, sol_w - 14, 9)
        c.setFillColor(_Y_ANTRASIT)
        c.setFont('Vera-Bold', msz)
        c.drawString(sol_x + 11, y - 0.98 * cm, mtxt)
        y -= mus_h + 0.25 * cm

        # -- Urun tablosu (etiket | deger) --
        satir = [('Ürün', b['urun'])]
        satir.append(('Kese numarası', f"{b['kese_gramaj']} gr" if b['kese_gramaj'] else None))
        satir.append(('Kağıt / malzeme cinsi', b['kagit']))
        if b['gramaj']:
            satir.append(('Kağıt gramajı', b['gramaj']))
        satir.append(('Ölçü (En × Boy × Körük)', b['olcu']))
        if b.get('ozellik'):
            satir.append(('Özellik', b['ozellik']))
        satir.append(('Baskı', b['baski']))
        satir.append(('Birim', b['birim']))
        et_w = sol_w * 0.36
        rh = 0.56 * cm
        c.setLineWidth(1)
        tablo_h = rh * len(satir)
        c.setFillColor(_IE_ETIKET_ZEMIN)
        c.rect(sol_x, y - tablo_h, et_w, tablo_h, fill=1, stroke=0)
        for i, (et, dg) in enumerate(satir):
            ry = y - (i + 1) * rh
            if i:
                c.setStrokeColor(_Y_CIZGI_GRI)
                c.setLineWidth(0.5)
                c.line(sol_x, ry + rh, sol_x + sol_w, ry + rh)
            c.setFillColor(colors.HexColor('#555555'))
            c.setFont('Vera', 8)
            c.drawString(sol_x + 6, ry + rh / 2 - 3, et)
            vx = sol_x + et_w + 6
            vw = sol_w - et_w - 12
            if et == 'Kese numarası' and dg:
                c.setFont('Vera-Bold', 9.5)
                bw = c.stringWidth(dg, 'Vera-Bold', 9.5) + 12
                c.setFillColor(_Y_ANTRASIT)
                c.rect(vx - 2, ry + 2.5, bw, rh - 5, fill=1, stroke=0)
                c.setFillColor(_Y_SARI)
                c.drawString(vx + 4, ry + rh / 2 - 3.3, dg)
            else:
                t2, s2 = _ie_metin_sigdir(c, str(dg) if dg else '-', 'Vera-Bold', 9.5, vw, 6.5)
                c.setFillColor(_Y_ANTRASIT if dg else colors.HexColor('#999999'))
                c.setFont('Vera-Bold' if dg else 'Vera', s2)
                c.drawString(vx, ry + rh / 2 - 3.3, t2)
        c.setStrokeColor(_Y_ANTRASIT)
        c.setLineWidth(1)
        c.rect(sol_x, y - tablo_h, sol_w, tablo_h, fill=0, stroke=1)
        y -= tablo_h + 0.25 * cm

        # -- Miktar kutulari --
        mk_w = (sol_w - 0.25 * cm) / 2
        mk_h = 1.05 * cm
        ikinci = ('TEDARİK DURUMU', b['durum']) if ticaret else \
            ('GERÇEKLEŞEN', f"{_miktar_tr(b['gerceklesen'])} {b['birim']}" if b['gerceklesen'] else '')
        for i, (et, dg) in enumerate([
            ('PLANLANAN' if not ticaret else 'MİKTAR', f"{_miktar_tr(b['planlanan'])} {b['birim']}" if b['planlanan'] else '-'),
            ikinci,
        ]):
            kx = sol_x + i * (mk_w + 0.25 * cm)
            c.setStrokeColor(_Y_ANTRASIT)
            c.setLineWidth(1)
            c.rect(kx, y - mk_h, mk_w, mk_h, fill=0, stroke=1)
            c.setFillColor(_IE_ETIKET_GRI)
            c.setFont('Vera', 6.6)
            c.drawString(kx + 7, y - 0.33 * cm, et)
            if dg:
                dg3, dsz3 = _ie_metin_sigdir(c, dg, 'Vera-Bold', 15, mk_w - 14, 8)
                c.setFillColor(_Y_ANTRASIT)
                c.setFont('Vera-Bold', dsz3)
                c.drawString(kx + 7, y - 0.88 * cm, dg3)
        y -= mk_h + 0.22 * cm

        # -- TEDARIK kutusu (sadece ticaret kalemleri) --
        if ticaret:
            from app.models import TICARET_STAGES
            td_h = 1.2 * cm
            mavi = colors.HexColor('#1B4F8A')
            c.setFillColor(colors.HexColor('#F2F7FC'))
            c.rect(sol_x, y - td_h, sol_w, td_h, fill=1, stroke=0)
            c.setFillColor(mavi)
            c.rect(sol_x, y - td_h, 4, td_h, fill=1, stroke=0)
            c.setFont('Vera-Bold', 8.5)
            c.drawString(sol_x + 11, y - 0.4 * cm, 'Bu kalem atölyede üretilmez – hazır alınıp sevk edilir.')
            anahtarlar = [k for k, _ in TICARET_STAGES]
            try:
                aktif = anahtarlar.index(b['ticaret_durumu'])
            except ValueError:
                aktif = 0
            kx = sol_x + 11
            c.setFont('Vera', 8)
            for i, (k, et) in enumerate(TICARET_STAGES):
                _ie_kutu_isareti(c, kx, y - 0.95 * cm, 8, i <= aktif)
                c.setFillColor(_Y_ANTRASIT)
                c.drawString(kx + 12, y - 0.92 * cm, et)
                kx += c.stringWidth(et, 'Vera', 8) + 34
            y -= td_h + 0.22 * cm

        # -- KOLI kutusu --
        koli_h = 1.05 * cm
        et_kw = 1.55 * cm
        c.setFillColor(_Y_ANTRASIT)
        c.rect(sol_x, y - koli_h, et_kw, koli_h, fill=1, stroke=0)
        c.setFillColor(_Y_SARI)
        c.setFont('Vera-Bold', 9)
        c.drawCentredString(sol_x + et_kw / 2, y - koli_h / 2 - 3, 'KOLİ')
        if b['koli_baskisiz']:
            c.setFillColor(_IE_ZEMIN_UYARI)
            c.rect(sol_x + et_kw, y - koli_h, sol_w - et_kw, koli_h, fill=1, stroke=0)
            _ie_uyari_ucgen(c, sol_x + et_kw + 8, y - koli_h / 2 - 2, 13)
            c.setFillColor(_Y_ANTRASIT)
            c.setFont('Vera-Bold', 12)
            c.drawString(sol_x + et_kw + 27, y - 0.45 * cm, 'BASKISIZ KOLİ')
            c.setFont('Vera', 7.5)
            c.setFillColor(colors.HexColor('#555555'))
            c.drawString(sol_x + et_kw + 27, y - 0.82 * cm, 'Firma adı / logosu olmayan düz koli kullanılacak')
        else:
            _ie_kutu_isareti(c, sol_x + et_kw + 9, y - koli_h / 2 - 5, 10, True)
            c.setFillColor(_Y_ANTRASIT)
            c.setFont('Vera-Bold', 10.5)
            c.drawString(sol_x + et_kw + 27, y - 0.45 * cm, 'Firma baskılı koli')
            c.setFont('Vera', 7.5)
            c.setFillColor(colors.HexColor('#555555'))
            c.drawString(sol_x + et_kw + 27, y - 0.82 * cm, 'Logolu standart koli')
        c.setStrokeColor(_Y_ANTRASIT)
        c.setLineWidth(1.2)
        c.rect(sol_x, y - koli_h, sol_w, koli_h, fill=0, stroke=1)
        y -= koli_h + 0.25 * cm

        # -- Notlar (kalan alan) --
        not_h = max(y - govde_alt, 0.9 * cm)
        c.setFillColor(_IE_NOT_ZEMIN)
        c.setStrokeColor(_Y_CIZGI_GRI)
        c.setLineWidth(0.5)
        c.rect(sol_x, y - not_h, sol_w, not_h, fill=1, stroke=1)
        notlar = [n for n in (b['not'], _ie_temiz(production.notes)) if n]
        html = '<b>Notlar:</b> ' + ('<br/>'.join(_sanitize_pdf_free_text(_escape_xml(n)).replace('\n', '<br/>') for n in notlar) if notlar else '')
        _ie_paragraf(c, html, sol_x + 6, y - 5, sol_w - 12, not_h - 10, not_st)

        # -- SAG: gorsel --
        cap_h = 0.45 * cm
        gx, gy, gw, gh = sag_xx, govde_alt + cap_h, sag_w, govde_ust - govde_alt - cap_h
        etiket = f'G{sira}'
        cizildi = _ie_vitrin_buyuk(c, gx, gy, gw, gh, b['gorsel'], etiket, b['en_txt'], b['boy_txt'])
        c.setFont('Vera', 7.5)
        c.setFillColor(colors.HexColor('#555555'))
        if cizildi:
            kaynak = 'Numune görseli' if b['gorsel_kaynak'] == 'numune' else 'Tasarım görseli'
            c.drawString(gx + 2, govde_alt + 3, f'{kaynak} · {etiket}')
        if b['kor_txt']:
            c.drawRightString(gx + gw - 2, govde_alt + 3, f"Körük: {b['kor_txt']} cm")

        # ===== IMZA ALANI =====
        iy = footer_ust + imza_h
        iw3 = (CW - 2 * 0.8 * cm) / 3
        for i, et in enumerate(['Üretimi yapan', 'Kontrol eden', 'Teslim alan']):
            ix = M + i * (iw3 + 0.8 * cm)
            c.setStrokeColor(_Y_ANTRASIT)
            c.setLineWidth(0.8)
            c.line(ix, iy - 0.75 * cm, ix + iw3, iy - 0.75 * cm)
            c.setFillColor(_Y_ANTRASIT)
            c.setFont('Vera-Bold', 8.5)
            c.drawString(ix, iy - 0.2 * cm, et)
            c.setFillColor(colors.HexColor('#777777'))
            c.setFont('Vera', 7.5)
            c.drawString(ix, iy - 1.08 * cm, 'Ad Soyad / Tarih / İmza')

        # ===== FOOTER =====
        fh = 0.55 * cm
        fy = 0.45 * cm
        c.setFillColor(_Y_ANTRASIT)
        c.rect(M, fy, CW, fh, fill=1, stroke=0)
        c.setStrokeColor(_Y_SARI)
        c.setLineWidth(2)
        c.line(M, fy + fh, PW - M, fy + fh)
        c.setFont('Vera', 7)
        c.setFillColor(_Y_MIKRO)
        sol_metin = f"{(company.company_name or 'Lema Ambalaj')} · İş emri dahili kullanım içindir · fiyat bilgisi içermez"
        sm, ssz = _ie_metin_sigdir(c, sol_metin, 'Vera', 7, CW * 0.65)
        c.setFont('Vera', ssz)
        c.drawString(M + 8, fy + fh / 2 - 2.5, sm)
        c.setFont('Vera-Bold', 7.5)
        c.setFillColor(colors.white)
        c.drawRightString(PW - M - 8, fy + fh / 2 - 2.5, f"{b['no']} · Sayfa {sayfa_idx}/{sayfa_sayisi}")

        c.showPage()

    if _c is not None:
        return None
    c.save()
    buf.seek(0)
    return buf


# ===== 2026-10-26 (2): SIPARIS DOSYASI - kapak + onayli teklif + tum is emirleri (tek PDF) =====

def _siparis_kapak_pdf(production, company, deal, kalem_bilgileri, sayfa_plani):
    """A4 dikey kapak: siparis ozeti (musteri, tarihler, satis, termin, odeme
    plani, genel toplam), kalem listesi (URETIM/TEDARIK) ve dosya icerigi."""
    PW, PH = A4
    M = 1.5 * cm
    CW = PW - 2 * M
    buf = BytesIO()
    c = _PDFCanvas(buf, pagesize=A4)
    c.setTitle(f'Sipariş Dosyası {deal.display_no}')
    top = PH - M
    # baslik
    logo_reader = None
    if company.logo_data:
        lb = _logo_for_pdf_yeni(company.logo_data)
        if lb:
            try:
                logo_reader = ImageReader(lb)
            except Exception:
                logo_reader = None
    if logo_reader:
        lw, lh = logo_reader.getSize()
        olc = min(4.5 * cm / lw, 1.6 * cm / lh)
        c.drawImage(logo_reader, M, top - lh * olc, lw * olc, lh * olc, mask='auto')
    c.setFillColor(_Y_ANTRASIT)
    c.setFont('Vera-Bold', 18)
    c.drawRightString(PW - M, top - 0.75 * cm, 'S İ P A R İ Ş   D O S Y A S I')
    c.setFont('Vera', 8.5)
    c.setFillColor(colors.HexColor('#666666'))
    c.drawRightString(PW - M, top - 1.3 * cm, f"{deal.display_no} · IE-{production.id:05d}")
    y = top - 1.95 * cm
    c.setStrokeColor(_Y_SARI)
    c.setLineWidth(3)
    c.line(M, y, PW - M, y)
    c.setStrokeColor(_Y_ANTRASIT)
    c.setLineWidth(1)
    c.line(M, y - 3.5, PW - M, y - 3.5)
    y -= 0.6 * cm

    customer = deal.customer
    musteri = _clean_for_pdf(customer.company_name) if customer.company_name else \
        f"{_clean_for_pdf(customer.first_name) or ''} {_clean_for_pdf(customer.last_name) or ''}".strip()
    seller = getattr(deal, 'seller', None)
    satis = (getattr(seller, 'full_name', None) or getattr(seller, 'username', None) or '-') if seller else '-'
    siparis_tarihi = production.start_date or (production.created_at.date() if production.created_at else None)
    terminler = [b['termin'] for b in kalem_bilgileri if b['termin']]
    termin = max(terminler) if terminler else production.due_date
    sym = 'TL' if (deal.para_birimi or 'TRY') == 'TRY' else deal.para_birimi
    pes = getattr(deal, 'pesinat_orani', None)
    pes_txt = '-'
    if pes is not None:
        pes_txt = f"%{_miktar_tr(pes)}"
        try:
            pes_txt += f" · {_money_tr(deal.value * pes / 100)} {sym}"
        except Exception:
            pass
        if getattr(deal, 'pesinat_tarihi', None):
            pes_txt += f" · {deal.pesinat_tarihi.strftime('%d.%m.%Y')}"
    bak = getattr(deal, 'bakiye_tarihi', None)
    alanlar = [
        ('MÜŞTERİ', musteri), ('SİPARİŞ TARİHİ', siparis_tarihi.strftime('%d.%m.%Y') if siparis_tarihi else '-'),
        ('TEKLİF NO', deal.display_no), ('İŞ EMRİ', f'IE-{production.id:05d}'),
        ('SATIŞ TEMSİLCİSİ', satis), ('TERMİN (en geç)', termin.strftime('%d.%m.%Y') if termin else '-'),
        ('PEŞİNAT', pes_txt), ('BAKİYE TARİHİ', bak.strftime('%d.%m.%Y') if bak else '-'),
        ('TESLİM ŞEKLİ', _teslim_yeri(deal, company) or '-'),
        ('GENEL TOPLAM (KDV dahil)', f"{_money_tr(deal.value or 0)} {sym}"),
    ]
    rh = 0.95 * cm
    kw = CW / 2
    satir = (len(alanlar) + 1) // 2
    c.setStrokeColor(_Y_ANTRASIT)
    c.setLineWidth(1)
    c.rect(M, y - satir * rh, CW, satir * rh, fill=0, stroke=1)
    for i, (et, dg) in enumerate(alanlar):
        kx = M + (i % 2) * kw
        ky = y - (i // 2) * rh
        if i % 2:
            c.setStrokeColor(_Y_CIZGI_GRI)
            c.setLineWidth(0.5)
            c.line(kx, ky - rh + 3, kx, ky - 3)
        if i // 2:
            c.setStrokeColor(_Y_CIZGI_GRI)
            c.setLineWidth(0.5)
            c.line(kx + 3, ky, kx + kw - 3, ky)
        c.setFillColor(_IE_ETIKET_GRI)
        c.setFont('Vera', 6.8)
        c.drawString(kx + 7, ky - 0.33 * cm, et)
        dg2, dsz = _ie_metin_sigdir(c, str(dg), 'Vera-Bold', 10.5, kw - 14, 7)
        c.setFillColor(_Y_ANTRASIT)
        c.setFont('Vera-Bold', dsz)
        c.drawString(kx + 7, ky - 0.75 * cm, dg2)
    y -= satir * rh + 0.6 * cm

    # kalemler
    c.setFillColor(_Y_ANTRASIT)
    c.setFont('Vera-Bold', 10)
    c.drawString(M, y, 'KALEMLER')
    y -= 0.25 * cm
    rh2 = 0.8 * cm
    for b in kalem_bilgileri:
        if y - rh2 < 6 * cm:
            c.setFont('Vera', 8)
            c.setFillColor(colors.HexColor('#777777'))
            c.drawString(M, y - 0.4 * cm, f'… ve diğer kalemler (toplam {len(kalem_bilgileri)}) – iş emri sayfalarında')
            y -= 0.6 * cm
            break
        c.setStrokeColor(_V_CERCEVE)
        c.setLineWidth(0.6)
        c.rect(M, y - rh2, CW, rh2 - 2, fill=0, stroke=1)
        c.setFillColor(_Y_ANTRASIT)
        c.rect(M + 5, y - rh2 + 5, 14, 14, fill=1, stroke=0)
        c.setFillColor(_Y_SARI)
        c.setFont('Vera-Bold', 8)
        c.drawCentredString(M + 12, y - rh2 + 9, str(b['sira']))
        ad = b['urun'] + (f" · {b['kese_gramaj']} gr" if b['kese_gramaj'] and f"{b['kese_gramaj']}" not in b['urun'] else '')
        mik = f"{_miktar_tr(b['planlanan'])} {b['birim']}" if b['planlanan'] else ''
        if b['koli_baskisiz']:
            mik += ' · baskısız koli'
        ad2, asz = _ie_metin_sigdir(c, ad, 'Vera-Bold', 9, CW * 0.55, 6.5)
        c.setFillColor(_Y_ANTRASIT)
        c.setFont('Vera-Bold', asz)
        c.drawString(M + 26, y - rh2 + 9, ad2)
        c.setFont('Vera', 8.5)
        c.setFillColor(colors.HexColor('#444444'))
        c.drawRightString(PW - M - 70, y - rh2 + 9, mik)
        etiket = 'TEDARİK' if b['tip'] == 'ticaret' else 'ÜRETİM'
        if b['tip'] == 'ticaret':
            c.setFillColor(colors.HexColor('#E3EEF9'))
            c.rect(PW - M - 62, y - rh2 + 6, 56, 12, fill=1, stroke=0)
            c.setFillColor(colors.HexColor('#1B4F8A'))
        else:
            c.setFillColor(_Y_ANTRASIT)
            c.rect(PW - M - 62, y - rh2 + 6, 56, 12, fill=1, stroke=0)
            c.setFillColor(_Y_SARI)
        c.setFont('Vera-Bold', 7)
        c.drawCentredString(PW - M - 34, y - rh2 + 9.5, etiket)
        y -= rh2
    y -= 0.5 * cm

    # dosya icerigi
    c.setFillColor(_Y_ANTRASIT)
    c.setFont('Vera-Bold', 10)
    c.drawString(M, y, 'DOSYA İÇERİĞİ')
    y -= 0.5 * cm
    c.setFont('Vera', 9)
    for ad, sayfa in sayfa_plani:
        c.setFillColor(colors.HexColor('#333333'))
        c.drawString(M + 6, y, ad)
        c.drawRightString(PW - M - 6, y, sayfa)
        c.setStrokeColor(_V_CERCEVE)
        c.setDash(1, 2)
        c.line(M + 6 + c.stringWidth(ad, 'Vera', 9) + 4, y + 2, PW - M - 10 - c.stringWidth(sayfa, 'Vera', 9), y + 2)
        c.setDash()
        y -= 0.5 * cm

    # imza / arsiv notu + footer
    c.setFont('Vera', 8)
    c.setFillColor(colors.HexColor('#777777'))
    c.drawString(M, 2.4 * cm, f"Dosya oluşturma: {datetime.now().strftime('%d.%m.%Y %H:%M')} · Bu dosya arşiv içindir; iş emri sayfaları fiyat içermez.")
    fh = 0.55 * cm
    fy = 1.2 * cm
    c.setFillColor(_Y_ANTRASIT)
    c.rect(M, fy, CW, fh, fill=1, stroke=0)
    c.setStrokeColor(_Y_SARI)
    c.setLineWidth(2)
    c.line(M, fy + fh, PW - M, fy + fh)
    c.setFont('Vera', 7)
    c.setFillColor(_Y_MIKRO)
    c.drawString(M + 8, fy + fh / 2 - 2.5, (company.company_name or 'Lema Ambalaj'))
    c.setFillColor(colors.white)
    c.setFont('Vera-Bold', 7.5)
    c.drawRightString(PW - M - 8, fy + fh / 2 - 2.5, f'{deal.display_no} · Sipariş dosyası · Kapak')
    c.showPage()
    c.save()
    buf.seek(0)
    return buf


def generate_siparis_dosyasi_pdf(production):
    """Tek PDF: (1) kapak, (2) onayli teklif (Ayarlar'daki teklif tasarimi -
    yeni/klasik - aynen), (3) tum is emri sayfalari (uretim + tedarik).
    Veritabanina hicbir sey YAZMAZ."""
    from pypdf import PdfReader, PdfWriter
    from app.models import KeseGramajKatalog
    try:
        katalog = KeseGramajKatalog.query.all()
    except Exception:
        katalog = []
    company = _get_company_settings_for_pdf()
    deal = production.deal
    kalemler = is_emri_kalemleri(production)
    bilgiler = [is_emri_kalem_bilgisi(production, it, n, len(kalemler), katalog) for n, it in enumerate(kalemler, 1)]

    teklif = PdfReader(generate_deal_pdf(deal))
    is_emri = PdfReader(generate_is_emri_pdf_yatay(production))
    n_teklif, n_ie = len(teklif.pages), len(is_emri.pages)
    plan = [('Kapak – sipariş özeti', 's. 1'),
            (f'Onaylı teklif ({deal.display_no})', f's. 2' if n_teklif == 1 else f's. 2–{1 + n_teklif}')]
    s = 2 + n_teklif
    for b in bilgiler or [None]:
        if b is None:
            plan.append(('İş emri', f's. {s}'))
        else:
            tur = 'tedarik' if b['tip'] == 'ticaret' else 'üretim'
            plan.append((f"İş emri {b['no']} ({tur}) – {b['urun'][:45]}", f's. {s}'))
        s += 1
    kapak = PdfReader(_siparis_kapak_pdf(production, company, deal, bilgiler, plan))

    w = PdfWriter()
    for r in (kapak, teklif, is_emri):
        for pg in r.pages:
            w.add_page(pg)
    w.add_metadata({'/Title': f'Sipariş Dosyası {deal.display_no} - IE-{production.id:05d}'})
    out = BytesIO()
    w.write(out)
    out.seek(0)
    return out


# ===== 2026-10-27: TOPLU IS EMRI - kontrol listesi + tum acik siparislerin is emirleri (tek PDF) =====

def _ie_ortak():
    """Toplu uretimde bir kez hesaplanan ortak veriler."""
    from app.models import KeseGramajKatalog
    try:
        katalog = KeseGramajKatalog.query.all()
    except Exception:
        katalog = []
    company = _get_company_settings_for_pdf()
    return {'katalog': katalog, 'company': company, 'logo_reader': _ie_logo_reader(company)}


def _kontrol_listesi_ciz(c, productions, ortak, ek_baslik=''):
    from reportlab.lib.pagesizes import landscape
    katalog, company = ortak['katalog'], ortak['company']
    satirlar = []
    for p in productions:
        kalemler = is_emri_kalemleri(p)
        cust = p.deal.customer
        musteri = (cust.company_name or f"{cust.first_name or ''} {cust.last_name or ''}").strip()
        for n, it in enumerate(kalemler, 1):
            b = is_emri_kalem_bilgisi(p, it, n, len(kalemler), katalog)
            satirlar.append((b['no'], musteri, b['urun'] + (' (tedarik)' if b['tip'] == 'ticaret' else ''),
                             f"{_miktar_tr(b['planlanan'])} {b['birim']}" if b['planlanan'] else '-',
                             b['termin'].strftime('%d.%m.%Y') if b['termin'] else '-', b['durum']))
    PW, PH = landscape(A4)
    M = 1.1 * cm
    kol = [('İŞ EMRİ', 3.2), ('MÜŞTERİ', 6.0), ('ÜRÜN', 6.8), ('PLANLANAN', 2.6), ('TERMİN', 2.3), ('DURUM', 2.6), ('KONTROL', 1.7), ('SİSTEMDE', 1.9)]
    rh = 0.62 * cm
    sayfa_basi = int((PH - 2 * M - 2.6 * cm) // rh)
    sayfalar = [satirlar[i:i + sayfa_basi] for i in range(0, max(len(satirlar), 1), sayfa_basi)] or [[]]
    for sn, grup in enumerate(sayfalar, 1):
        y = PH - M
        c.setFillColor(_Y_ANTRASIT)
        c.setFont('Vera-Bold', 15)
        c.drawString(M, y - 0.5 * cm, 'İŞ EMRİ KONTROL LİSTESİ' + ek_baslik)
        c.setFont('Vera', 9)
        c.setFillColor(colors.HexColor('#555555'))
        c.drawRightString(PW - M, y - 0.5 * cm,
                          f"{datetime.now().strftime('%d.%m.%Y %H:%M')} · {len(productions)} sipariş · {len(satirlar)} iş emri · Sayfa {sn}/{len(sayfalar)}")
        c.setStrokeColor(_Y_SARI)
        c.setLineWidth(3)
        c.line(M, y - 0.85 * cm, PW - M, y - 0.85 * cm)
        y -= 1.3 * cm
        x = M
        c.setFillColor(_Y_ANTRASIT)
        c.rect(M, y - rh, PW - 2 * M, rh, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont('Vera-Bold', 7.5)
        for ad, w in kol:
            c.drawString(x + 4, y - rh / 2 - 2.5, ad)
            x += w * cm
        y -= rh
        for i, s in enumerate(grup):
            if i % 2:
                c.setFillColor(colors.HexColor('#F7F6F2'))
                c.rect(M, y - rh, PW - 2 * M, rh, fill=1, stroke=0)
            x = M
            for j, (ad, w) in enumerate(kol):
                if j < len(s):
                    font = 'Vera-Bold' if j == 0 else 'Vera'
                    txt, sz = _ie_metin_sigdir(c, str(s[j]), font, 8.5, w * cm - 8, 6)
                    c.setFillColor(_Y_ANTRASIT)
                    c.setFont(font, sz)
                    c.drawString(x + 4, y - rh / 2 - 3, txt)
                else:
                    c.setStrokeColor(_Y_ANTRASIT)
                    c.setLineWidth(0.8)
                    c.rect(x + (w * cm - 10) / 2, y - rh / 2 - 5, 10, 10, fill=0, stroke=1)
                x += w * cm
            c.setStrokeColor(_Y_CIZGI_GRI)
            c.setLineWidth(0.4)
            c.line(M, y - rh, PW - M, y - rh)
            y -= rh
        if not grup:
            c.setFont('Vera', 10)
            c.setFillColor(colors.HexColor('#777777'))
            c.drawString(M, y - 0.8 * cm, 'Açık iş emri yok.')
        c.setFont('Vera', 7)
        c.setFillColor(_Y_MIKRO)
        c.drawString(M, 0.6 * cm, f"{company.company_name or 'Lema Ambalaj'} · dahili kontrol listesi · fiyat bilgisi içermez")
        c.showPage()


def generate_is_emri_kontrol_listesi_pdf(productions):
    """Sadece kontrol listesi (hizli - gorsel/is emri sayfasi yok)."""
    from reportlab.lib.pagesizes import landscape
    buf = BytesIO()
    c = _PDFCanvas(buf, pagesize=landscape(A4))
    c.setTitle('İş Emri Kontrol Listesi')
    _gonderilen_onyukle_guvenli(productions)
    _kontrol_listesi_ciz(c, productions, _ie_ortak())
    c.save()
    buf.seek(0)
    return buf


def _gonderilen_onyukle_guvenli(productions):
    """2026-10-27: gonderilen miktarlar toplu ekranlarda tek seferde yuklensin."""
    try:
        from app.kalem_belge import gonderilen_onyukle
        gonderilen_onyukle(productions)
    except Exception:
        pass


TOPLU_PARCA = 15  # bir PDF'te en fazla bu kadar siparis (canli 30 sn sinirina karsi)
_TOPLU_GORSEL_PX = 640


def generate_toplu_is_emri_pdf(productions, ek_baslik=''):
    """Verilen siparislerin is emri sayfalari TEK canvas'ta (PDF birlestirme
    yok); basta o paketin kontrol listesi. Ortak veriler bir kez, gorseller
    bir kez ve daha kucuk cozunurlukte islenir. Veritabanina YAZMAZ."""
    global _IE_TOPLU
    from reportlab.lib.pagesizes import landscape
    ortak = _ie_ortak()
    buf = BytesIO()
    c = _PDFCanvas(buf, pagesize=landscape(A4))
    c.setTitle('İş Emirleri' + ek_baslik)
    _IE_TOPLU = {'gorsel': {}, 'px': _TOPLU_GORSEL_PX}
    _gonderilen_onyukle_guvenli(productions)
    try:
        _kontrol_listesi_ciz(c, productions, ortak, ek_baslik)
        for p in productions:
            generate_is_emri_pdf_yatay(p, _c=c, _ortak=ortak)
    finally:
        _IE_TOPLU = None
    c.save()
    buf.seek(0)
    return buf


def _escape_xml(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def generate_irsaliye_pdf(shipment):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    turkish_style = ParagraphStyle('TurkishStyle', parent=styles['Normal'], fontName='Vera', fontSize=9)
    title_style = ParagraphStyle('TitleStyle', parent=styles['Title'], fontName='Vera-Bold', fontSize=18)
    heading_style = ParagraphStyle('HeadingStyle', parent=styles['Heading2'], fontName='Vera-Bold', fontSize=11, spaceAfter=5)

    production = shipment.production
    customer = production.deal.customer

    elements = []

    elements.append(Paragraph("İRSALİYE", title_style))
    elements.append(Spacer(1, 8*mm))

    elements.append(Paragraph(f"<b>Sevkiyat No:</b> SVN-{shipment.id:05d}", turkish_style))
    elements.append(Paragraph(f"<b>Teklif No:</b> {production.deal.display_no}", turkish_style))
    elements.append(Paragraph(f"<b>Gönderim Tarihi:</b> {shipment.ship_date.strftime('%d.%m.%Y') if shipment.ship_date else '-'}", turkish_style))
    if shipment.carrier:
        elements.append(Paragraph(f"<b>Kargo Firması:</b> {shipment.carrier}", turkish_style))
    if shipment.tracking_number:
        elements.append(Paragraph(f"<b>Takip No:</b> {shipment.tracking_number}", turkish_style))
    elements.append(Spacer(1, 5*mm))

    elements.append(Paragraph("MÜŞTERİ BİLGİLERİ", heading_style))
    if customer.company_name:
        elements.append(Paragraph(f"<b>Firma:</b> {_clean_for_pdf(customer.company_name)}", turkish_style))
    elements.append(Paragraph(f"<b>Ad Soyad:</b> {_clean_for_pdf(customer.first_name)} {_clean_for_pdf(customer.last_name)}", turkish_style))
    if customer.company_address or customer.address:
        elements.append(Paragraph(f"<b>Adres:</b> {customer.company_address or customer.address}", turkish_style))
    if customer.company_phone or customer.phone:
        elements.append(Paragraph(f"<b>Telefon:</b> {customer.company_phone or customer.phone}", turkish_style))
    elements.append(Spacer(1, 5*mm))

    elements.append(Paragraph("ÜRÜN / MİKTAR", heading_style))

    if production.items:
        data = [['#', 'Açıklama', 'Miktar', 'Birim']]
        for i, item in enumerate(production.items, 1):
            data.append([
                str(i),
                Paragraph(item.description, turkish_style),
                f"{item.produced_quantity:.2f}",
                item.unit
            ])
        table = Table(data, colWidths=[1*cm, 9*cm, 3*cm, 3*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a252f')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Vera-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("<i>Ürün kalemi bulunamadı.</i>", turkish_style))

    if shipment.notes:
        elements.append(Spacer(1, 5*mm))
        elements.append(Paragraph("NOTLAR", heading_style))
        elements.append(Paragraph(_sanitize_pdf_free_text(shipment.notes), turkish_style))

    elements.append(Spacer(1, 15*mm))
    signature_data = [
        ['Teslim Eden:', '', 'Teslim Alan:'],
        ['', '', ''],
        ['', '', ''],
        ['Adı Soyadı:', '', 'Adı Soyadı:'],
        ['Tarih:', '', 'Tarih:'],
    ]
    signature_table = Table(signature_data, colWidths=[5*cm, 4*cm, 5*cm])
    signature_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Vera'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('LINEBELOW', (0, 2), (0, 2), 1, colors.black),
        ('LINEBELOW', (2, 2), (2, 2), 1, colors.black),
    ]))
    elements.append(signature_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer

def _tr_para2(value):
    """Belge tutari: her zaman 2 ondalik, TR ayrac ('31.500,00 TL') - Vera
    fontunda ₺ glifi olmadigi icin diger PDF'lerle ayni 'TL' metni."""
    v = float(value or 0)
    s = f'{abs(v):,.2f}'.replace(',', '§').replace('.', ',').replace('§', '.')
    return ('-' if v < 0 else '') + s + ' TL'


def _vd_metni(vergi_dairesi):
    """'Selçuk' -> 'Selçuk V.D.'; zaten 'V.D.' / 'VD' / 'Vergi Dairesi' ile
    bitiyorsa tekrar eklenmez ('Selçuk V.D. V.D.' olmasin)."""
    s = (vergi_dairesi or '').strip()
    if not s:
        return ''
    sade = re.sub(r'[\s.]', '', s).casefold()
    if sade.endswith('vd') or sade.endswith('vergidairesi') or sade.endswith('vergidairesimüdürlüğü'):
        return s
    return s + ' V.D.'


def generate_manual_irsaliye_pdf(manual_irsaliye, show_prices=False):
    """2026-10-28: YENI manuel irsaliye tasarimi (teklif/is emriyle ayni
    kurumsal dil - sari #FBC213 / antrasit #353639). Gonderen firma basligi
    (logo, unvan, adres, VD/VKN), ALICI ve SIPARIS kutulari, sevk seridi
    (tasiyici, takip no, koli adedi, toplam kg), TR sayi bicimi, not kutusu,
    imza/kase alani. show_prices=False iken fiyat sutunlari ve toplamlar HIC
    gorunmez. Eski tasarim generate_manual_irsaliye_pdf_klasik olarak durur.
    Veritabanina YAZMAZ."""
    from datetime import timedelta
    from xml.sax.saxutils import escape
    from app.models import Deal, Production
    company = _get_company_settings_for_pdf()
    customer = manual_irsaliye.customer
    buffer = BytesIO()
    PW, PH = A4
    M = 1.4 * cm
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=M, leftMargin=M, topMargin=1.2 * cm, bottomMargin=1.4 * cm,
                            title=f'Sevk İrsaliyesi {manual_irsaliye.display_no}')
    W = PW - 2 * M
    st = getSampleStyleSheet()
    n = ParagraphStyle('irN', parent=st['Normal'], fontName='Vera', fontSize=8.6, leading=11.5)
    k = ParagraphStyle('irK', parent=n, fontSize=7.6, leading=10, textColor=_Y_IKINCIL)
    b = ParagraphStyle('irB', parent=n, fontName='Vera-Bold')
    h = ParagraphStyle('irH', parent=n, fontName='Vera-Bold', fontSize=6.8, leading=9, textColor=colors.HexColor('#8A8A8A'))
    sag = ParagraphStyle('irSag', parent=n, alignment=2)
    t = lambda s: escape(_clean_for_pdf(s) if s else '')

    # ---- Baslik: logo + gonderen | SEVK IRSALIYESI + no + tarih/saat ----
    logo = _ie_logo_reader(company)
    logo_buf = _logo_for_pdf_yeni(company.logo_data) if (logo and company.logo_data) else None
    firma_satir = [f"<font name='Vera-Bold' size='9.5'>{t(company.company_name or 'Lema Ambalaj')}</font>"]
    if company.address:
        firma_satir.append(t(company.address))
    alt = ' · '.join(x for x in [t(_vd_metni(company.tax_office)) if company.tax_office else None,
                                 t(company.tax_id) if company.tax_id else None, t(company.phone) if company.phone else None] if x)
    if alt:
        firma_satir.append(alt)
    firma_p = Paragraph('<br/>'.join(firma_satir), ParagraphStyle('irF', parent=k, textColor=colors.HexColor('#333333'), leading=10.5))
    if logo and logo_buf:
        iw, ih = logo.getSize()
        lh = 1.45 * cm
        lw = min(lh * iw / ih if ih else lh, 3.6 * cm)
        logo_buf.seek(0)
        logo_img = Image(logo_buf, width=lw, height=lw * ih / iw if iw else lh)
        sol = Table([[logo_img, firma_p]], colWidths=[lw + 0.3 * cm, W * 0.62 - lw - 0.3 * cm])
        sol.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('LEFTPADDING', (0, 0), (-1, -1), 0)]))
    else:
        sol = firma_p
    saat = (manual_irsaliye.created_at + timedelta(hours=3)).strftime('%H:%M') if manual_irsaliye.created_at else None
    tarih = manual_irsaliye.ship_date.strftime('%d.%m.%Y') if manual_irsaliye.ship_date else '-'
    sag_p = [Paragraph("<font name='Vera-Bold' size='15' color='#353639'>SEVK İRSALİYESİ</font>",
                       ParagraphStyle('irBaslik', parent=sag, leading=19)), Spacer(1, 4),
             Table([[manual_irsaliye.display_no]], style=TableStyle([
                 ('BACKGROUND', (0, 0), (-1, -1), _Y_ANTRASIT), ('TEXTCOLOR', (0, 0), (-1, -1), _Y_SARI),
                 ('FONTNAME', (0, 0), (-1, -1), 'Vera-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 9.5),
                 ('TOPPADDING', (0, 0), (-1, -1), 2), ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]), hAlign='RIGHT'),
             Spacer(1, 3),
             Paragraph(f"Tarih: {tarih}" + (f" · Saat: {saat}" if saat else ''), ParagraphStyle('irT', parent=k, alignment=2))]
    bas = Table([[sol, sag_p]], colWidths=[W * 0.62, W * 0.38])
    bas.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0),
                             ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                             ('LINEBELOW', (0, 0), (-1, 0), 2.5, _Y_SARI)]))
    el = [bas, Spacer(1, 9)]

    # ---- ALICI | SIPARIS kutulari ----
    musteri_ad = (customer.company_name or f"{customer.first_name or ''} {customer.last_name or ''}").strip()
    kisi = f"{customer.first_name or ''} {customer.last_name or ''}".strip()
    tel = customer.company_phone or customer.phone
    alici = [Paragraph('ALICI', h), Paragraph(f"<font name='Vera-Bold' size='9.5'>{t(musteri_ad) or '-'}</font>", n)]
    ikinci = ' · '.join(x for x in [t(kisi) if kisi and customer.company_name else None, t(tel) if tel else None] if x)
    if ikinci:
        alici.append(Paragraph(ikinci, n))
    adres = customer.company_address or customer.address
    if adres:
        alici.append(Paragraph(t(adres), n))
    vd = ' · '.join(x for x in [t(_vd_metni(customer.tax_office)) if customer.tax_office else None, t(customer.tax_id) if customer.tax_id else None] if x)
    alici.append(Paragraph(f"V.D. / VKN: {vd}" if vd else 'V.D. / VKN: -', k))

    siparis = [Paragraph('SİPARİŞ', h)]
    deal = Deal.query.get(manual_irsaliye.deal_id) if manual_irsaliye.deal_id else None
    if deal:
        sip_tarih = deal.deal_date or (deal.created_at.date() if deal.created_at else None)
        siparis.append(Paragraph(f"<font name='Vera-Bold' size='9.5'>{deal.display_no}</font>" +
                                 (f" · sipariş tarihi {sip_tarih.strftime('%d.%m.%Y')}" if sip_tarih else ''), n))
        prod = Production.query.filter_by(deal_id=deal.id).first()
        if prod:
            siparis.append(Paragraph(f"İş emri: IE-{prod.id:05d}", n))
    else:
        siparis.append(Paragraph('Siparişe bağlı değil (stok / numune)', n))
    if manual_irsaliye.estimated_delivery_date:
        siparis.append(Paragraph(f"Tahmini teslim: {manual_irsaliye.estimated_delivery_date.strftime('%d.%m.%Y')}", k))
    kutular = Table([[alici, siparis]], colWidths=[W / 2 - 3, W / 2 - 3], spaceBefore=0)
    kutular.setStyle(TableStyle([('BOX', (0, 0), (0, 0), 0.6, _Y_CIZGI_GRI), ('BOX', (1, 0), (1, 0), 0.6, _Y_CIZGI_GRI),
                                 ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 8),
                                 ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 7)]))
    el += [kutular, Spacer(1, 7)]

    # ---- Sevk seridi ----
    kg_toplam = sum((it.quantity or 0) for it in manual_irsaliye.items if (it.unit or '').lower() == 'kg')
    koli = getattr(manual_irsaliye, 'koli_adedi', None)
    hucre = lambda bas_, deger, kalin=False: [Paragraph(bas_, h), Paragraph(
        f"<font name='{'Vera-Bold' if kalin else 'Vera'}'>{deger}</font>", n)]
    serit = Table([[hucre('KARGO / TAŞIYICI', t(manual_irsaliye.carrier) or '-'),
                    hucre('TAKİP NO', t(manual_irsaliye.tracking_number) or '-'),
                    hucre('KOLİ', f"{koli} koli" if koli else '-', True),
                    hucre('TOPLAM AĞIRLIK', f"{_miktar_tr(kg_toplam)} kg" if kg_toplam else '-', True)]],
                  colWidths=[W / 4] * 4)
    serit.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), 0.6, _Y_CIZGI_GRI), ('LINEAFTER', (0, 0), (2, 0), 0.4, _Y_CIZGI_GRI),
                               ('BACKGROUND', (0, 0), (-1, -1), _Y_TOPLAM_BG), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                               ('LEFTPADDING', (0, 0), (-1, -1), 7), ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
    el += [serit, Spacer(1, 10)]

    # ---- Kalemler ----
    priced = show_prices and manual_irsaliye.is_priced
    sagh = ParagraphStyle('irTh', parent=n, fontName='Vera-Bold', fontSize=7.8, textColor=_Y_SARI)
    sagh_r = ParagraphStyle('irThR', parent=sagh, alignment=2)
    bas_satir = [Paragraph('#', sagh), Paragraph('ÜRÜN', sagh), Paragraph('MİKTAR', sagh_r), Paragraph('BİRİM', sagh)]
    if priced:
        bas_satir += [Paragraph('BİRİM FİYAT', sagh_r), Paragraph('TUTAR', sagh_r)]
    data = [bas_satir]
    for i, it in enumerate(manual_irsaliye.items, 1):
        row = [str(i), Paragraph(escape(_sanitize_pdf_free_text(it.description) or '-'), n),
               Paragraph(_miktar_tr(it.quantity), sag), it.unit or '']
        if priced:
            row += [Paragraph(_tr_para2(it.unit_price), sag), Paragraph(_tr_para2((it.unit_price or 0) * (it.quantity or 0)), sag)]
        data.append(row)
    if len(data) == 1:
        data.append(['', Paragraph('<i>Ürün kalemi yok.</i>', k), '', ''] + (['', ''] if priced else []))
    cw = [0.8 * cm, W - 0.8 * cm - 2.4 * cm - 1.6 * cm - (5.6 * cm if priced else 0), 2.4 * cm, 1.6 * cm] + ([2.8 * cm, 2.8 * cm] if priced else [])
    tab = Table(data, colWidths=cw, repeatRows=1)
    tab.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), _Y_ANTRASIT), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                             ('FONTNAME', (0, 1), (-1, -1), 'Vera'), ('FONTSIZE', (0, 1), (-1, -1), 8.6),
                             ('LINEBELOW', (0, 1), (-1, -1), 0.4, _Y_CIZGI_GRI),
                             ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5)]))
    el.append(tab)
    if priced:
        tt = Table([['Ara toplam', _tr_para2(manual_irsaliye.subtotal)],
                    [f'KDV %{(manual_irsaliye.vat_rate or 0):g}', _tr_para2(manual_irsaliye.vat_amount)],
                    ['GENEL TOPLAM', _tr_para2(manual_irsaliye.total)]], colWidths=[3.6 * cm, 3.6 * cm], hAlign='RIGHT')
        tt.setStyle(TableStyle([('FONTNAME', (0, 0), (-1, -1), 'Vera'), ('FONTSIZE', (0, 0), (-1, -1), 8.8),
                                ('FONTNAME', (0, 2), (-1, 2), 'Vera-Bold'), ('FONTSIZE', (0, 2), (-1, 2), 9.8),
                                ('ALIGN', (1, 0), (1, -1), 'RIGHT'), ('LINEABOVE', (0, 2), (-1, 2), 1.4, _Y_ANTRASIT),
                                ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]))
        el += [Spacer(1, 6), tt]

    if manual_irsaliye.notes and manual_irsaliye.notes.strip():
        notp = Table([[Paragraph(f"<font name='Vera-Bold'>Not:</font> {escape(_sanitize_pdf_free_text(manual_irsaliye.notes))}", n)]],
                     colWidths=[W])
        notp.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FFF8DC')),
                                  ('LINEBEFORE', (0, 0), (0, -1), 2.5, _Y_SARI), ('LEFTPADDING', (0, 0), (-1, -1), 8),
                                  ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
        el += [Spacer(1, 9), notp]

    imza = Table([[Paragraph("<font name='Vera-Bold'>Teslim Eden</font><br/>Ad Soyad / İmza", k), '',
                   Paragraph("<font name='Vera-Bold'>Teslim Alan</font><br/>Ad Soyad / İmza / Kaşe", k)]],
                 colWidths=[W * 0.42, W * 0.16, W * 0.42], rowHeights=[2.2 * cm])
    imza.setStyle(TableStyle([('LINEABOVE', (0, 0), (0, 0), 0.8, colors.HexColor('#999999')),
                              ('LINEABOVE', (2, 0), (2, 0), 0.8, colors.HexColor('#999999')),
                              ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0)]))
    el += [Spacer(1, 1.1 * cm), imza]

    def _alt(canvas, _doc):
        canvas.saveState()
        canvas.setFont('Vera', 7)
        canvas.setFillColor(colors.HexColor('#999999'))
        canvas.drawCentredString(PW / 2, 0.8 * cm, f"{company.company_name or 'Lema Ambalaj'} · {manual_irsaliye.display_no} · sayfa {_doc.page}")
        canvas.restoreState()

    doc.build(el, onFirstPage=_alt, onLaterPages=_alt)
    buffer.seek(0)
    return buffer


def generate_manual_irsaliye_pdf_klasik(manual_irsaliye, show_prices=False):
    """generate_irsaliye_pdf ile ayni gorsel format - ama Shipment/Production
    yerine dogrudan ManualIrsaliye+customer'dan besleniyor (teklif/uretim
    kaydi olmadan olusturulan bagimsiz irsaliyeler icin). Is 5: show_prices
    True ise (ve irsaliye fiyatliysa) Birim Fiyat/Toplam sutunlari + KDV/
    Genel Toplam alt bilgisi eklenir - varsayilan False (fiyatsiz)."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    turkish_style = ParagraphStyle('TurkishStyle', parent=styles['Normal'], fontName='Vera', fontSize=9)
    title_style = ParagraphStyle('TitleStyle', parent=styles['Title'], fontName='Vera-Bold', fontSize=18)
    heading_style = ParagraphStyle('HeadingStyle', parent=styles['Heading2'], fontName='Vera-Bold', fontSize=11, spaceAfter=5)

    customer = manual_irsaliye.customer

    elements = []

    elements.append(Paragraph("İRSALİYE", title_style))
    elements.append(Spacer(1, 8*mm))

    elements.append(Paragraph(f"<b>İrsaliye No:</b> {manual_irsaliye.display_no}", turkish_style))
    elements.append(Paragraph(f"<b>Gönderim Tarihi:</b> {manual_irsaliye.ship_date.strftime('%d.%m.%Y') if manual_irsaliye.ship_date else '-'}", turkish_style))
    if manual_irsaliye.carrier:
        elements.append(Paragraph(f"<b>Kargo Firması:</b> {manual_irsaliye.carrier}", turkish_style))
    if manual_irsaliye.tracking_number:
        elements.append(Paragraph(f"<b>Takip No:</b> {manual_irsaliye.tracking_number}", turkish_style))
    elements.append(Spacer(1, 5*mm))

    elements.append(Paragraph("MÜŞTERİ BİLGİLERİ", heading_style))
    if customer.company_name:
        elements.append(Paragraph(f"<b>Firma:</b> {_clean_for_pdf(customer.company_name)}", turkish_style))
    elements.append(Paragraph(f"<b>Ad Soyad:</b> {_clean_for_pdf(customer.first_name)} {_clean_for_pdf(customer.last_name)}", turkish_style))
    if customer.company_address or customer.address:
        elements.append(Paragraph(f"<b>Adres:</b> {customer.company_address or customer.address}", turkish_style))
    if customer.company_phone or customer.phone:
        elements.append(Paragraph(f"<b>Telefon:</b> {customer.company_phone or customer.phone}", turkish_style))
    elements.append(Spacer(1, 5*mm))

    elements.append(Paragraph("ÜRÜN / MİKTAR", heading_style))

    priced = show_prices and manual_irsaliye.is_priced
    if manual_irsaliye.items:
        from xml.sax.saxutils import escape
        if priced:
            data = [['#', 'Açıklama', 'Miktar', 'Birim', 'Birim Fiyat', 'Toplam']]
        else:
            data = [['#', 'Açıklama', 'Miktar', 'Birim']]
        for i, item in enumerate(manual_irsaliye.items, 1):
            row = [
                str(i),
                Paragraph(escape(_sanitize_pdf_free_text(item.description) or '-'), turkish_style),
                f"{item.quantity:.2f}",
                item.unit
            ]
            if priced:
                row.append(format_price_precise(item.unit_price or 0))
                row.append(format_price_precise(item.total_price))
            data.append(row)
        col_widths = [1*cm, 7*cm, 2.2*cm, 2*cm, 2.8*cm, 2.8*cm] if priced else [1*cm, 9*cm, 3*cm, 3*cm]
        table = Table(data, colWidths=col_widths)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a252f')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Vera-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
        ]))
        elements.append(table)
        if priced:
            elements.append(Spacer(1, 3*mm))
            totals_data = [
                ['Ara Toplam:', format_price_precise(manual_irsaliye.subtotal)],
                [f'KDV (%{manual_irsaliye.vat_rate:.0f}):', format_price_precise(manual_irsaliye.vat_amount)],
                ['GENEL TOPLAM:', format_price_precise(manual_irsaliye.total)],
            ]
            totals_table = Table(totals_data, colWidths=[4*cm, 4*cm])
            totals_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'Vera'),
                ('FONTNAME', (0, 2), (-1, 2), 'Vera-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
                ('LINEABOVE', (0, 2), (-1, 2), 1, colors.black),
            ]))
            elements.append(totals_table)
    else:
        elements.append(Paragraph("<i>Ürün kalemi bulunamadı.</i>", turkish_style))

    if manual_irsaliye.notes:
        elements.append(Spacer(1, 5*mm))
        elements.append(Paragraph("NOTLAR", heading_style))
        elements.append(Paragraph(_sanitize_pdf_free_text(manual_irsaliye.notes), turkish_style))

    elements.append(Spacer(1, 15*mm))
    signature_data = [
        ['Teslim Eden:', '', 'Teslim Alan:'],
        ['', '', ''],
        ['', '', ''],
        ['Adı Soyadı:', '', 'Adı Soyadı:'],
        ['Tarih:', '', 'Tarih:'],
    ]
    signature_table = Table(signature_data, colWidths=[5*cm, 4*cm, 5*cm])
    signature_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Vera'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('LINEBELOW', (0, 2), (0, 2), 1, colors.black),
        ('LINEBELOW', (2, 2), (2, 2), 1, colors.black),
    ]))
    elements.append(signature_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer

def generate_statement_pdf(customer, statements, total_debit, total_credit):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=2*cm, bottomMargin=2*cm)
    
    styles = getSampleStyleSheet()
    turkish_style = ParagraphStyle('TurkishStyle', parent=styles['Normal'], fontName='Vera', fontSize=9)
    title_style = ParagraphStyle('TitleStyle', parent=styles['Title'], fontName='Vera-Bold', fontSize=16)
    heading_style = ParagraphStyle('HeadingStyle', parent=styles['Heading2'], fontName='Vera-Bold', fontSize=11)
    
    elements = []
    
    elements.append(Paragraph("MÜŞTERİ EKSTRESİ", title_style))
    elements.append(Spacer(1, 8*mm))
    
    if customer.company_name:
        elements.append(Paragraph(f"<b>Firma:</b> {_clean_for_pdf(customer.company_name)}", turkish_style))
    elements.append(Paragraph(f"<b>Müşteri:</b> {_clean_for_pdf(customer.first_name)} {_clean_for_pdf(customer.last_name)}", turkish_style))
    if customer.contact_person:
        elements.append(Paragraph(f"<b>Yetkili:</b> {customer.contact_person}", turkish_style))
    elements.append(Paragraph(f"<b>E-posta:</b> {customer.email}", turkish_style))
    elements.append(Paragraph(f"<b>Rapor Tarihi:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}", turkish_style))
    elements.append(Spacer(1, 5*mm))
    
    if statements:
        data = [['Tarih', 'Tür', 'Açıklama', 'Tutar']]
        for s in statements:
            data.append([
                s.created_at.strftime('%d.%m.%Y'),
                s.type.upper(),
                Paragraph(s.description or '-', turkish_style),
                f"{s.amount:,.2f} TL"
            ])
        
        data.append(['', '', 'TOPLAM BORÇ:', f"{total_debit:,.2f} TL"])
        data.append(['', '', 'TOPLAM ALACAK:', f"{total_credit:,.2f} TL"])
        data.append(['', '', 'BAKİYE:', f"{total_debit - total_credit:,.2f} TL"])
        
        table = Table(data, colWidths=[2.5*cm, 2*cm, 7.5*cm, 3.5*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a252f')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Vera-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (-1, -3), (-1, -1), colors.HexColor('#e8f4f8')),
            ('FONTNAME', (-1, -3), (-1, -1), 'Vera-Bold'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -4), [colors.white, colors.HexColor('#f8f9fa')]),
            ('ALIGN', (-1, 0), (-1, -1), 'RIGHT'),
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("<i>Henüz işlem bulunmuyor.</i>", turkish_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer

def generate_production_list_pdf(productions, tab_label):
    """Uretim Listesi'nin o an ekranda gorunen (sekme ile filtrelenmis)
    halini PDF olarak disa aktarir - production_export_pdf() route'u
    tarafindan cagrilir, ekranda gorunenle BIREBIR ayni satirlari icerir
    (Is 2)."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.2*cm, leftMargin=1.2*cm, topMargin=1.5*cm, bottomMargin=1.5*cm)

    styles = getSampleStyleSheet()
    turkish_style = ParagraphStyle('TurkishStyle', parent=styles['Normal'], fontName='Vera', fontSize=8)
    title_style = ParagraphStyle('TitleStyle', parent=styles['Title'], fontName='Vera-Bold', fontSize=15)

    elements = []
    elements.append(Paragraph(f"ÜRETİM LİSTESİ — {tab_label}", title_style))
    elements.append(Paragraph(f"Rapor Tarihi: {datetime.now().strftime('%d.%m.%Y %H:%M')} · Toplam: {len(productions)} kayıt", turkish_style))
    elements.append(Spacer(1, 5*mm))

    if productions:
        data = [['#', 'Fırsat', 'Müşteri', 'Durum', 'Başlangıç', 'Bitiş', 'Geçen Gün', 'İş Emri']]
        for p in productions:
            data.append([
                str(p.id),
                Paragraph(_clean_for_pdf(p.deal.title) if p.deal else '-', turkish_style),
                Paragraph(_clean_for_pdf(p.deal.customer.display_name) if p.deal and p.deal.customer else '-', turkish_style),
                p.stage_label,
                p.start_date.strftime('%d.%m.%Y') if p.start_date else '-',
                p.end_date.strftime('%d.%m.%Y') if p.end_date else '-',
                str(p.gecen_gun),
                'Eksik Bilgi' if p.specs_missing else 'Tam',
            ])
        table = Table(data, colWidths=[1*cm, 4.5*cm, 4*cm, 2*cm, 2.2*cm, 2.2*cm, 2*cm, 2.5*cm], repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a252f')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Vera-Bold'),
            ('FONTNAME', (0, 1), (-1, -1), 'Vera'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (3, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("<i>Bu sekmede kayıt bulunmuyor.</i>", turkish_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer

def generate_cari_hesap_pdf(rows):
    """Is 7: Cari Hesap Ozeti'nin o an ekranda gorunen (filtrelenmis) halini
    PDF olarak disa aktarir - cari_hesap_export_pdf() route'u tarafindan
    cagrilir, ekrandaki ile BIREBIR ayni satirlari icerir (bkz.
    generate_production_list_pdf'teki ayni desen)."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.2*cm, leftMargin=1.2*cm, topMargin=1.5*cm, bottomMargin=1.5*cm)

    styles = getSampleStyleSheet()
    turkish_style = ParagraphStyle('TurkishStyle', parent=styles['Normal'], fontName='Vera', fontSize=8)
    title_style = ParagraphStyle('TitleStyle', parent=styles['Title'], fontName='Vera-Bold', fontSize=15)

    elements = []
    elements.append(Paragraph("CARİ HESAP ÖZETİ", title_style))
    elements.append(Paragraph(f"Rapor Tarihi: {datetime.now().strftime('%d.%m.%Y %H:%M')} · Toplam: {len(rows)} kayıt", turkish_style))
    elements.append(Spacer(1, 5*mm))

    if rows:
        data = [['Müşteri', 'Şehir', 'Faturalanmış', 'Fat.yok Kazanılan', 'Tahsil Edilen', 'Toplam Bakiye']]
        for r in rows:
            data.append([
                Paragraph(_clean_for_pdf(r['customer'].display_name), turkish_style),
                _clean_for_pdf(r['city']) if r['city'] else '-',
                format_price_precise(r['invoiced']),
                format_price_precise(r['uninvoiced_won']),
                format_price_precise(r['collected']),
                format_price_precise(r['balance']),
            ])
        table = Table(data, colWidths=[4.5*cm, 2.5*cm, 2.8*cm, 2.8*cm, 2.8*cm, 2.8*cm], repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a252f')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Vera-Bold'),
            ('FONTNAME', (0, 1), (-1, -1), 'Vera'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("<i>Bu filtreye uyan müşteri bulunmuyor.</i>", turkish_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer

def generate_gunluk_uretim_form_pdf():
    """Is 5: atolyede elle doldurulacak BOS Gunluk Uretim Takip Formu -
    veritabanindan hicbir veri cekmez, sabit bir sablondur. /gunluk-uretim
    sayfasindaki 'Bos Form Yazdir' butonundan indirilir, her gun yeniden
    basilip atolyeye verilir."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=1.5*cm, bottomMargin=1.5*cm)

    styles = getSampleStyleSheet()
    tarih_style = ParagraphStyle('TarihStyle', parent=styles['Normal'], fontName='Vera', fontSize=11, alignment=2)
    company_style = ParagraphStyle('CompanyStyle', parent=styles['Normal'], fontName='Vera-Bold', fontSize=24, leading=29, alignment=1, spaceAfter=4)
    subcompany_style = ParagraphStyle('SubCompanyStyle', parent=styles['Normal'], fontName='Vera', fontSize=11, leading=14, alignment=1)
    form_title_style = ParagraphStyle('FormTitleStyle', parent=styles['Normal'], fontName='Vera-Bold', fontSize=15, leading=18, alignment=1)
    table_header_style = ParagraphStyle('GUTableHeader', parent=styles['Normal'], fontName='Vera-Bold', fontSize=10,
                                         textColor=colors.white, alignment=1)
    signature_label_style = ParagraphStyle('SigLabel', parent=styles['Normal'], fontName='Vera-Bold', fontSize=10)

    elements = []
    elements.append(Paragraph("Tarih: .................................", tarih_style))
    elements.append(Spacer(1, 3*mm))
    elements.append(Paragraph("LEMA AMBALAJ", company_style))
    elements.append(Paragraph("Expertmak Makine Ambalaj Sanayi Tic. Ltd. Şti.", subcompany_style))
    elements.append(Spacer(1, 6*mm))
    elements.append(Paragraph("GÜNLÜK ÜRETİM TAKİP FORMU", form_title_style))
    elements.append(Spacer(1, 8*mm))

    # 2026-10-07 (Is 3): 'Kagit Cinsi' sutunu Musteri/Firma'dan sonra
    # eklendi - Musteri/Firma genisligi (7.3->5.3cm) kucultulerek toplam
    # genislik (17.0cm) AYNEN korundu.
    headers = ['#', 'Müşteri / Firma', 'Kağıt\nCinsi', '1 Koli\nKaç Kg', 'Kaç\nKoli', 'Toplam\nKg']
    data = [[Paragraph(h.replace('\n', '<br/>'), table_header_style) for h in headers]]
    for i in range(1, 9):
        data.append([str(i), '', '', '', '', ''])
    toplam_label = Paragraph('GÜNÜN TOPLAM KİLOSU:', ParagraphStyle(
        'ToplamLabel', parent=styles['Normal'], fontName='Vera-Bold', fontSize=11, leading=13, alignment=2))
    data.append([toplam_label, '', '', '', '', ''])

    col_widths = [1.2*cm, 5.3*cm, 2.5*cm, 2.7*cm, 2.3*cm, 3*cm]
    table = Table(data, colWidths=col_widths, rowHeights=[1.1*cm] + [1.1*cm]*8 + [1.3*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a252f')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 1), (-1, -2), 'Vera'),
        ('FONTSIZE', (0, 1), (-1, -2), 10),
        ('GRID', (0, 0), (-1, -2), 0.75, colors.black),
        ('SPAN', (0, -1), (4, -1)),
        ('ALIGN', (0, -1), (4, -1), 'RIGHT'),
        ('RIGHTPADDING', (4, -1), (4, -1), 8),
        ('LINEABOVE', (0, -1), (-1, -1), 1.25, colors.black),
        ('LINEBELOW', (0, -1), (-1, -1), 1.25, colors.black),
        ('LINEBEFORE', (0, 0), (0, -1), 0.75, colors.black),
        ('LINEAFTER', (-1, 0), (-1, -1), 0.75, colors.black),
        ('LINEAFTER', (4, -1), (4, -1), 0.75, colors.black),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 20*mm))

    signature_data = [
        ['Adı Soyadı - İmza', '', 'Kontrol Eden'],
        ['', '', ''],
        ['', '', ''],
    ]
    signature_table = Table(signature_data, colWidths=[7.5*cm, 2.2*cm, 7.5*cm])
    signature_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Vera-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('LINEBELOW', (0, -1), (0, -1), 1, colors.black),
        ('LINEBELOW', (2, -1), (2, -1), 1, colors.black),
        ('TOPPADDING', (0, 1), (-1, -1), 6*mm),
    ]))
    elements.append(signature_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer
