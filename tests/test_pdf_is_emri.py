"""Is emri - YENI yatay, kalem bazli tasarim (2026-10-26) + teklif PDF'indeki
kese numarasi / baskisiz koli eklemeleri.

VERITABANINA HIC DOKUNMAZ: uretim/teklif/kalem/musteri bellekte SimpleNamespace
ile kurulur, firma ayarlari ve kese katalogu testte sahteyle degistirilir.
Calistirma: pytest tests/test_pdf_is_emri.py
"""
import io
import itertools
import os
import sys
from datetime import date, datetime
from types import SimpleNamespace as NS

import pdfplumber
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import pdf_utils  # noqa: E402
import test_pdf_teklif_gorsel as T  # noqa: E402  (ayni fixture gorselleri ve sahte firma)

JPG, PNG = T.JPG, T.PNG


@pytest.fixture(autouse=True)
def _sahte(monkeypatch):
    monkeypatch.setattr(pdf_utils, '_get_company_settings_for_pdf', T._firma)


def _di(i, **k):
    d = dict(id=i, description='-', en=None, boy=None, korugu=None, kagit_cinsi=None, renk=None,
             teslim_tarihi=None, numune_gorseli=None, termin_gun=None, kese_gramaj=None, koli_tipi=None,
             quantity=0, unit='kg')
    d.update(k)
    return NS(**d)


def _pi(i, d, **k):
    x = dict(id=100 + i, deal_item_id=d.id, description=d.description, planned_quantity=d.quantity,
             produced_quantity=0, unit=d.unit, kagit_tipi=d.kagit_cinsi, olcu=None, baski_bilgisi=d.renk,
             gramaj=None, notes=None, daily_outputs=[])
    x.update(k)
    return NS(**x)


def _uretim(items, pitems, musteri='TEST BUĞLEM PİLİÇ ÇEVİRME', **k):
    deal = NS(items=items, display_no='TKL-00132', varsayilan_termin_gun=None,
              customer=NS(company_name=musteri, first_name='', last_name=''))
    p = NS(id=127, deal=deal, uretim_items=pitems, daily_outputs=[], status='uretimde',
           start_date=date(2026, 10, 26), created_at=datetime(2026, 10, 26, 10), due_date=None, notes=None,
           tasarim_gorseli=None, tasarim_gorseli_override=None)
    p.__dict__.update(k)
    return p


def _metin(pdf_bytes):
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return [(pg.width, pg.height, pg.extract_text() or '') for pg in pdf.pages]


def _uret(p, **k):
    return pdf_utils.generate_is_emri_pdf_yatay(p, **k).getvalue()


def _cakisma_var(pdf_bytes, tol=0.6):
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            ws = [w for w in page.extract_words() if w['upright']]
            for a, b in itertools.combinations(ws, 2):
                if (min(a['x1'], b['x1']) - max(a['x0'], b['x0']) > tol and
                        min(a['bottom'], b['bottom']) - max(a['top'], b['top']) > tol):
                    return f"{a['text']!r} / {b['text']!r}"
    return None


# ---------- senaryolar ----------

def ie1():
    d = _di(1, description='ATLET POŞET', en='30', boy='50', korugu='10', kagit_cinsi='BEYAZ POŞET',
            renk='1 RENK', numune_gorseli=JPG, quantity=200, unit='kg', kese_gramaj=1000, koli_tipi='baskili')
    return _uretim([d], [_pi(1, d)])


def ie2():
    ds = [_di(1, description='1000 gr esmer kare dipli kese', en='12,5', boy='29', korugu='7', numune_gorseli=JPG,
              quantity=500, unit='kg', koli_tipi='baskisiz', termin_gun=10),
          _di(2, description='Beyaz kraft kese', quantity=300, unit='kg'),
          _di(3, description='Kraft doypack 16×26', en='16', boy='26', numune_gorseli=PNG, quantity=5000, unit='adet')]
    return _uretim(ds, [_pi(i + 1, d) for i, d in enumerate(ds)])


def test_ie1_tek_kalem_yatay_ve_bilgiler():
    pdf = _uret(ie1())
    sayfalar = _metin(pdf)
    assert len(sayfalar) == 1
    w, h, t = sayfalar[0]
    assert w > h, 'sayfa yatay olmali'
    for beklenen in ('IE-00127-1', 'Kalem 1 / 1', 'TEST BUĞLEM', 'ATLET POŞET', '1000 gr', '30 × 50 × 10 cm',
                     '200 kg', 'Firma baskılı koli', 'TKL-00132'):
        assert beklenen in t, beklenen
    assert 'BASKISIZ' not in t
    assert _cakisma_var(pdf) is None


def test_ie2_uc_kalem_uc_sayfa_numaralar():
    sayfalar = _metin(_uret(ie2()))
    assert len(sayfalar) == 3
    for i, (_, _, t) in enumerate(sayfalar, 1):
        assert f'IE-00127-{i}' in t and f'Kalem {i} / 3' in t


def test_ie2_tek_kalem_secimi():
    p = ie2()
    sayfalar = _metin(_uret(p, item_ids=[p.uretim_items[1].id]))
    assert len(sayfalar) == 1 and 'IE-00127-2' in sayfalar[0][2] and 'Kalem 2 / 3' in sayfalar[0][2]


def test_ie3_gorselsiz_numune_yapistirma_alani():
    t = _metin(_uret(ie2()))[1][2]
    assert 'NUMUNE YAPIŞTIRMA ALANI' in t


def test_ie4_baskisiz_koli_uyarisi():
    sayfalar = _metin(_uret(ie2()))
    assert 'BASKISIZ KOLİ' in sayfalar[0][2]
    assert 'BASKISIZ' not in sayfalar[1][2]


def test_ie5_none_metni_basilmaz():
    d = _di(1, description='ATLET POŞET', en='None', boy='None', korugu=None, kagit_cinsi='BEYAZ POŞET',
            renk='1 RENK', quantity=200, unit='kg')
    t = _metin(_uret(_uretim([d], [_pi(1, d, olcu='NonexNone')])))[0][2]
    assert 'None' not in t


def test_ie6_birimler_dogru():
    sayfalar = _metin(_uret(ie2()))
    assert '500 kg' in sayfalar[0][2]
    assert '5.000 adet' in sayfalar[2][2]


def test_ie7_uzun_ad_ve_not_tek_sayfa_cakismasiz():
    uzun = 'Kraft pencereli kilitli doypack ' + 'çok uzun ürün açıklaması ' * 8
    d = _di(1, description=uzun, en='16', boy='26', korugu='4+4', numune_gorseli=JPG, quantity=5000, unit='adet')
    notlar = 'Baskı rengi numune ile birebir aynı olacak. ' * 25
    pdf = _uret(_uretim([d], [_pi(1, d, notes=notlar)], musteri='TEST ' + 'ÇOK UZUN FİRMA ÜNVANI ' * 6))
    assert len(_metin(pdf)) == 1
    assert _cakisma_var(pdf) is None


def test_gorsel_cozunurlugu_300px_ustu():
    with pdfplumber.open(io.BytesIO(_uret(ie1()))) as pdf:
        genislikler = [im['srcsize'][0] for im in pdf.pages[0].images]
    assert genislikler and max(genislikler) >= 300


def test_gerceklesen_gunluk_uretimden_ve_durum():
    p = ie2()
    p.uretim_items[0].daily_outputs = [NS(toplam_kg=120), NS(toplam_kg=60)]
    b = pdf_utils.is_emri_kalem_bilgisi(p, p.uretim_items[0], 1, 3)
    assert b['gerceklesen'] == 180 and b['durum'] == 'Üretimde' and b['kalan'] == 320
    p.uretim_items[0].daily_outputs.append(NS(toplam_kg=400))
    assert pdf_utils.is_emri_kalem_bilgisi(p, p.uretim_items[0], 1, 3)['durum'] == 'Hazır'


def test_termin_is_gunu():
    # 26.10.2026 Pazartesi + 10 is gunu = 09.11.2026 Pazartesi
    p = ie2()
    b = pdf_utils.is_emri_kalem_bilgisi(p, p.uretim_items[0], 1, 3)
    assert b['termin'] == date(2026, 11, 9)


# ---------- kese numarasi tespiti ----------

KATALOG = [NS(gramaj=1000, olcu_en='12,5', olcu_boy='29', olcu_korugu='7'),
           NS(gramaj=100, olcu_en='8', olcu_boy='17', olcu_korugu='4')]


@pytest.mark.parametrize('kalem,beklenen', [
    (_di(1, kese_gramaj=500), 500),
    (_di(1, description='1000 gr esmer kare dipli kese'), 1000),
    (_di(1, description='Kese', en='12.5', boy='29', korugu='7'), 1000),
    (_di(1, description='Kese', en='12,50', boy='29'), 1000),
    (_di(1, description='Kese', en='12,5', boy='30'), None),
    (_di(1, description='Atlet poşet 250 gr'), None),
])
def test_kese_gramaj_bul(kalem, beklenen):
    assert pdf_utils.kese_gramaj_bul(kalem, KATALOG) == beklenen


# ---------- teklif PDF eklemeleri ----------

def test_teklif_pdf_kese_ve_baskisiz_koli():
    k1 = T._kalem('Esmer kraft kare dipli kese', en='12,5', boy='29', korugu='7')
    k1.kese_gramaj, k1.koli_tipi = 1000, 'baskisiz'
    k2 = T._kalem('Atlet poşet')
    k2.kese_gramaj, k2.koli_tipi = None, 'baskili'
    pdf = T.pdf_uret(T._teklif([k1, k2]))
    with pdfplumber.open(io.BytesIO(pdf)) as d:
        t = '\n'.join(p.extract_text() or '' for p in d.pages)
    assert '1000 gr' in t
    assert t.count('Koli: Baskısız') == 1


def test_teklif_pdf_kese_adda_varsa_tekrar_yazilmaz():
    k = T._kalem('1000 gr esmer kraft kese')
    k.kese_gramaj = 1000
    pdf = T.pdf_uret(T._teklif([k]))
    with pdfplumber.open(io.BytesIO(pdf)) as d:
        t = '\n'.join(p.extract_text() or '' for p in d.pages)
    assert t.count('1000 gr') == 1
