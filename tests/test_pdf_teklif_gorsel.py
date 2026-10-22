"""Teklif PDF (yeni tasarim) - kurumsal vitrin gorseli, ince olcu cizgileri,
termin, kose damgasi kaldirma ve metin cakismasi testleri (2026-10-22).

VERITABANINA HIC DOKUNMAZ: teklif/kalem/musteri/firma bellekte SimpleNamespace
ile kurulur, firma ayarlarini okuyan fonksiyon testte sahte firmayla
degistirilir. Calistirma: pytest tests/test_pdf_teklif_gorsel.py
"""
import io
import itertools
import os
import re
import sys
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pdfplumber
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import pdf_utils  # noqa: E402

FIXTURES = os.path.join(ROOT, 'tests', 'fixtures')
JPG = os.path.join(FIXTURES, 'urun_kare.jpg')
PNG = os.path.join(FIXTURES, 'urun_seffaf.png')
FIRMA = 'EXPERTMAK MAKİNE AMBALAJ SAN TİC LTD ŞTİ'


def _fixture_gorseller():
    """Ornek urun fotograflari yoksa kodla uretir (JPEG: 800x800 opak,
    PNG: 600x400 seffaf zeminli)."""
    from PIL import Image, ImageDraw
    os.makedirs(FIXTURES, exist_ok=True)
    if not os.path.exists(JPG):
        im = Image.new('RGB', (800, 800), (236, 230, 214))
        d = ImageDraw.Draw(im)
        d.rectangle([220, 140, 580, 700], fill=(176, 132, 84), outline=(120, 86, 50), width=8)
        d.rectangle([220, 140, 580, 230], fill=(150, 108, 66))
        d.ellipse([340, 360, 460, 480], fill=(251, 194, 19))
        im.save(JPG, 'JPEG', quality=92)
    if not os.path.exists(PNG):
        im = Image.new('RGBA', (600, 400), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([120, 60, 480, 360], radius=30, fill=(53, 54, 57, 255))
        d.rectangle([200, 140, 400, 280], fill=(251, 194, 19, 255))
        im.save(PNG, 'PNG')


_fixture_gorseller()


def _firma():
    return SimpleNamespace(
        logo_data=_logo_bytes(), company_name=FIRMA,
        address='Fevzi Çakmak Mah. 10753 Sok. No:30/A Kobisan Sanayi Sitesi, Karatay/Konya',
        phone='0332 251 10 12', fax=None, email='info@lemaambalaj.com', website='www.lemaambalaj.com',
        tax_office='Selçuk V.D.', tax_id='3810692373', banka_adi='GARANTİ BANKASI',
        iban='TR630006200077000006286284', iban_usd=None, iban_eur=None, teklif_sartlari=None,
        teklif_pdf_tasarim=None,
    )


def _logo_bytes():
    from PIL import Image, ImageDraw
    im = Image.new('RGB', (900, 300), (251, 194, 19))
    ImageDraw.Draw(im).rectangle([40, 40, 200, 260], fill=(53, 54, 57))
    buf = io.BytesIO()
    im.save(buf, 'PNG')
    return buf.getvalue()


def _kalem(ad, gorsel=None, en=None, boy=None, korugu=None, termin=None, qty=1000, fiyat=2.5, aciklama_ek=''):
    return SimpleNamespace(
        description=ad + aciklama_ek, quantity=qty, unit='adet', unit_price=fiyat, total_price=qty * fiyat,
        kagit_cinsi='Esmer Kraft', renk='2 renk baskı', en=en, boy=boy, korugu=korugu,
        numune_gorseli=gorsel, teslim_tarihi=None, para_birimi=None, termin_gun=termin, urun_tipi='uretim',
    )


def _teklif(kalemler, varsayilan_termin=None, no='TKL-09999'):
    sub = sum(k.total_price for k in kalemler)
    musteri = SimpleNamespace(first_name='Oğuzhan', last_name='Yılmaz', company_name='TEST Çerez Ltd',
                              phone='+90 533 000 00 00', tax_office=None, tax_id=None, company_address=None, address=None)
    return SimpleNamespace(
        display_no=no, deal_date=date(2026, 10, 22), created_at=datetime(2026, 10, 22, 9, 0),
        valid_until=date(2026, 10, 29), expected_close=None,
        seller=SimpleNamespace(full_name='SERKAN ACAR', username='serkan'), customer=musteri,
        odeme_vade_gun=0, vade_gun=None, vade_gun_metni='Peşin', odeme_yontemi='havale',
        odeme_yontemi_listesi=['Havale / EFT'], para_birimi='TRY', para_birimi_sembol='₺', kullanilan_kur=None,
        kur_usd=None, kur_eur=None, kur_tarihi=None, kur_turu=None, items=kalemler, notes=None,
        subtotal=sub, vat_rate=20, vat_amount=sub * 0.2, value=sub * 1.2, varsayilan_termin_gun=varsayilan_termin,
    )


def senaryolar():
    uzun = (' - kraft pencereli, kilitli, tabanlı ayakta duran doypack; iç yüzeyi gıdaya uygun '
            'bariyerli film, dış yüzey mat lak, ısıl yapıştırma bandı ve yırtma çentikli')
    return {
        'S1': _teklif([_kalem('250 gr esmer kraft kare dipli kese')]),
        'S2': _teklif([
            _kalem('500 gr kraft doypack', gorsel=JPG, en='12,5', boy='29', korugu='7', termin=15),
            _kalem('1000 gr kraft doypack', gorsel=PNG, en='16', boy='32', korugu='3,5+3,5'),
            _kalem('Baskısız kese kağıdı', termin=10),
        ], varsayilan_termin=20),
        'S3': _teklif([_kalem(f'Ürün {i:02d} kraft kese', gorsel=JPG if i % 2 else PNG, en='30', boy='50',
                              korugu='8', termin=15) for i in range(1, 16)]),
        'S4': _teklif([_kalem('Kraft pencereli kilitli doypack 8,5×14,5', gorsel=JPG, en='8.5', boy='14,50',
                              korugu='2,5+2,5', termin=12, aciklama_ek=uzun)]),
        'S5': _teklif([
            _kalem('Sadece en ve boy', gorsel=JPG, en='12,5', boy='29'),
            _kalem('Ölçülü ama görselsiz', en='18', boy='29,5', korugu='None'),
        ]),
    }


@pytest.fixture(autouse=True)
def _sahte_firma(monkeypatch):
    monkeypatch.setattr(pdf_utils, '_get_company_settings_for_pdf', _firma)


def pdf_uret(deal, lang='tr'):
    return pdf_utils._generate_deal_pdf_yeni(deal, lang=lang).getvalue()


def _kelimeler(page):
    return page.extract_words(keep_blank_chars=False, extra_attrs=['upright', 'size'])


def _cakismalar(pdf_bytes, tol=0.6):
    """Ayni sayfada iki metin kutusu (footer dahil) birbirine biniyor mu?
    Dik (upright) kelimeler kendi aralarinda; dondurulmus olcu yazisi da
    dik kelimelerle karsilastirilir."""
    sorunlar = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            words = _kelimeler(page)
            dik = [w for w in words if w['upright']]
            yatik = [w for w in words if not w['upright']]
            ciftler = list(itertools.combinations(dik, 2)) + [(a, b) for a in yatik for b in dik]
            for a, b in ciftler:
                ix = min(a['x1'], b['x1']) - max(a['x0'], b['x0'])
                iy = min(a['bottom'], b['bottom']) - max(a['top'], b['top'])
                if ix > tol and iy > tol:
                    sorunlar.append((pno, a['text'], b['text'], round(a['top'])))
    return sorunlar


def _metin(pdf_bytes):
    """Sayfa metinleri - bolunmez bosluk (sayi+'iş' arasinda kullaniliyor) ve
    dar hucrede satir kaymasi karsilastirmayi bozmasin diye tum bosluklar
    tek bosluga indirilir."""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return [re.sub(r'\s+', ' ', (p.extract_text() or '').replace('\xa0', ' ')) for p in pdf.pages]


CM = 28.3465


def _bolge_metni(pdf_bytes, x0_cm, x1_cm):
    """Sayfanin yalnizca [x0, x1] cm dikey seridindeki metin (yan yana
    sutunlar - ör. Teklif Sartlari | Toplam - metin akisinda karismasin)."""
    out = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for p in pdf.pages:
            out.append(p.crop((x0_cm * CM, 0, min(x1_cm * CM, p.width), p.height)).extract_text() or '')
    return re.sub(r'\s+', ' ', ' '.join(out).replace('\xa0', ' '))


TERMIN_SUTUNU = (15.0, 17.0)   # 1,4 kenar + 0,9 + 8,1 + 2,0 + 2,6 cm
SARTLAR_SUTUNU = (1.4, 11.3)   # icerik genisligi x 0,55


@pytest.mark.parametrize('ad', ['S1', 'S2', 'S3', 'S4', 'S5'])
def test_metin_cakismasi_yok(ad):
    assert _cakismalar(pdf_uret(senaryolar()[ad])) == []


@pytest.mark.parametrize('ad', ['S1', 'S2', 'S3', 'S4', 'S5'])
def test_kose_damgasi_yok(ad):
    """Eski sag-ust kose damgasi: donuk (upright=False) firma adi. Artik tek
    dondurulmus metin olcu etiketleri (rakam + 'cm') olabilir; firma adi
    sadece ust firma blogunda ve footer'da, ikisi de duz."""
    with pdfplumber.open(io.BytesIO(pdf_uret(senaryolar()[ad]))) as pdf:
        for page in pdf.pages:
            for ch in page.chars:
                if not ch.get('upright', True):
                    assert ch['text'] in '0123456789,. cm', ch
            for w in _kelimeler(page):
                if 'EXPERTMAK' in w['text']:
                    assert w['upright']
                    assert w['top'] > 40, w  # sayfanin en ust seridi (damganin yeri) bos


def test_s1_tek_sayfa_ve_termin_maddesi_yok():
    pdf = pdf_uret(senaryolar()['S1'])
    sayfalar = _metin(pdf)
    assert len(sayfalar) == 1
    tum = '\n'.join(sayfalar)
    assert 'Termin' in tum
    assert 'iş günü olarak hesaplanır' not in tum
    assert 'onaydan sonra' not in tum


def test_s2_termin_hucresi_ve_sart_maddesi():
    pdf = pdf_uret(senaryolar()['S2'])
    tum = '\n'.join(_metin(pdf))
    termin = _bolge_metni(pdf, *TERMIN_SUTUNU)
    assert 'Termin 15 iş günü onaydan sonra' in termin, termin  # baslik 'Teslim' degil + kalemin kendi termini
    assert 'Teslim' not in termin
    assert '20 iş günü onaydan sonra' in termin        # kalemde yok -> teklifin varsayilani
    assert '10 iş günü onaydan sonra' in termin
    sartlar = _bolge_metni(pdf, *SARTLAR_SUTUNU)
    assert '5. Termin süreleri sipariş ve baskı provası onayından itibaren iş günü olarak hesaplanır.' in sartlar
    assert 'Ölçü: 12,5 × 29 × 7 cm' in tum
    assert 'Ölçü: 16 × 32 × 3,5+3,5 cm' in tum


def test_s3_cok_sayfa_baslik_tekrari_ve_tum_kalemler():
    sayfalar = _metin(pdf_uret(senaryolar()['S3']))
    assert len(sayfalar) >= 3
    tum = '\n'.join(sayfalar)
    for i in range(1, 16):
        assert f'Ürün {i:02d} kraft kese' in tum, i
    for no, s in enumerate(sayfalar, 1):
        if re.search(r'Ürün \d\d kraft kese', s):
            assert 'Ürün ve teknik özellikler' in s, f'{no}. sayfada tablo var ama basligi yok'


def test_s4_uzun_aciklama_tasmiyor():
    pdf = pdf_uret(senaryolar()['S4'])
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        page = doc.pages[0]
        for w in _kelimeler(page):
            if w['size'] < 6:  # footer alti mikro yazi seridi tasarim geregi kenarda kesilir
                continue
            assert 0 <= w['x0'] and w['x1'] <= page.width, w
    assert 'Ölçü: 8,5 × 14,5 × 2,5+2,5 cm' in '\n'.join(_metin(pdf))


def test_s5_olcu_satiri_bicimi():
    tum = '\n'.join(_metin(pdf_uret(senaryolar()['S5'])))
    assert 'Ölçü: 12,5 × 29 cm' in tum          # sadece en+boy
    assert 'Ölçü: 18 × 29,5 cm' in tum          # gorselsiz; korugu 'None' metni yazilmaz
    assert 'None' not in tum


def test_gorsel_cozunurlugu_ve_vitrin_sayisi():
    with pdfplumber.open(io.BytesIO(pdf_uret(senaryolar()['S2']))) as pdf:
        page = pdf.pages[0]
        urun = [im for im in page.images if im['width'] < 4.2 * 28.35]  # logo haric
        assert len(urun) == 2  # gorselsiz 3. kalemde bos kutu YOK
        for im in urun:
            assert im['srcsize'][0] >= 300, im['srcsize']


def test_logo_firma_bloguna_degmiyor():
    with pdfplumber.open(io.BytesIO(pdf_uret(senaryolar()['S1']))) as pdf:
        page = pdf.pages[0]
        logo = max(page.images, key=lambda im: im['width'])
        firma = [w for w in _kelimeler(page) if w['text'] == 'EXPERTMAK' and w['top'] < 200][0]
        assert firma['x0'] - logo['x1'] >= 5, (logo['x1'], firma['x0'])


def test_footer_icerikle_cakismiyor():
    """Footer bandi icerik alaninin (alt kenar 2,0 cm) ALTINDA kalmali."""
    with pdfplumber.open(io.BytesIO(pdf_uret(senaryolar()['S3']))) as pdf:
        for page in pdf.pages:
            alt_sinir = page.height - 2.0 * 28.35      # icerik cercevesinin alt kenari
            bant_ustu = page.height - 1.75 * 28.35     # footer bandi (ust kenar 1,7 cm) + pay
            kelimeler = _kelimeler(page)
            footer = [w for w in kelimeler if w['top'] >= bant_ustu]
            icerik = [w for w in kelimeler if w['top'] < bant_ustu]
            assert any('Sayfa' in w['text'] for w in footer)
            tasan = [w['text'] for w in icerik if w['bottom'] > alt_sinir + 0.5]
            assert tasan == [], tasan


@pytest.mark.parametrize('ad', ['S1', 'S2', 'S3', 'S5'])
def test_cerceveler_sayfa_marjindan_tasmiyor(ad):
    """Toplam kutusu eskiden urun tablosunun sag kenarindan ~6pt tasiyordu."""
    with pdfplumber.open(io.BytesIO(pdf_uret(senaryolar()[ad]))) as pdf:
        for page in pdf.pages:
            sol, sag = 1.4 * CM - 0.6, page.width - 1.4 * CM + 0.6
            for r in page.rects + page.lines:
                assert sol <= r['x0'] and r['x1'] <= sag, (round(r['x0'], 1), round(r['x1'], 1))


def test_ingilizce_pdf_bozulmuyor():
    pdf = pdf_uret(senaryolar()['S2'], lang='en')
    tum = '\n'.join(_metin(pdf))
    termin = _bolge_metni(pdf, *TERMIN_SUTUNU)
    assert 'Lead time 15 business days after approval' in termin, termin  # 2 cm sutunda iki satira kayar
    assert 'Lead times are counted in business days' in _bolge_metni(pdf, *SARTLAR_SUTUNU)
    assert 'Size: 12.5 × 29 × 7 cm' in tum
    assert _cakismalar(pdf_uret(senaryolar()['S2'], lang='en')) == []


def test_olcu_degeri_bicimleri():
    f = pdf_utils._olcu_degeri
    assert f('12,5') == ('12,5', 12.5)
    assert f('22.5') == ('22,5', 22.5)
    assert f('14,50') == ('14,5', 14.5)
    assert f('30') == ('30', 30.0)
    assert f('30,0') == ('30', 30.0)
    assert f('3,5+3,5') == ('3,5+3,5', None)
    assert f('None') == (None, None) and f('') == (None, None) and f(None) == (None, None)
    assert f('12,5', 'en') == ('12.5', 12.5)
