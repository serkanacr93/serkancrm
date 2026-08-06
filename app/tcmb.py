"""
T.C. Merkez Bankasi gunluk doviz kurlari - Coklu Para Birimi (EUR/USD)
tekliflerinde gosterge kur olarak kullanilir.

TCMB'nin gunluk kur XML servisi kimlik dogrulama gerektirmez, gunde bir kez
(is gunlerinde ~15:30'da) guncellenir. Hafta sonu/resmi tatil gunlerinde bir
onceki is gununun kurunu dondurmeye devam eder - ayrica bir tarih kontrolu
gerekmez.
"""
import requests
from xml.etree import ElementTree

TCMB_URL = 'https://www.tcmb.gov.tr/kurlar/today.xml'
REQUEST_TIMEOUT = 5


def fetch_tcmb_rate(currency_code):
    """Verilen doviz kodu (EUR/USD) icin TCMB efektif satis kurunu (1 birim
    dovizin kac TL ettigini) doner. TRY icin her zaman 1.0. Ag hatasi, XML
    ayristirma hatasi veya kod bulunamazsa None doner - cagiran taraf bunu
    'kur otomatik alinamadi, elle girin' olarak ele almali, hicbir zaman
    hata firlatmaz (form akisini kesmemesi icin)."""
    currency_code = (currency_code or '').upper()
    if currency_code == 'TRY':
        return 1.0
    try:
        resp = requests.get(TCMB_URL, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        root = ElementTree.fromstring(resp.content)
        for currency in root.findall('Currency'):
            if currency.get('CurrencyCode') == currency_code:
                selling = currency.findtext('ForexSelling')
                if selling:
                    return float(selling.replace(',', '.'))
        return None
    except Exception:
        return None
