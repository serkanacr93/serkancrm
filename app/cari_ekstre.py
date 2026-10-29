"""2026-10-28: Cari hesap ekstresi - hareket listesi (SADECE OKUR).

Sistem hareketleri musteri detayindaki Cari Hesap bakiyesiyle (Customer.
balance) AYNI kaynaklardan gelir, boylece ekstrenin bakiyesi ekranla hep
ayni olur:
  - borc: 'fatura' tipindeki her fatura (Invoice.total)
  - borc: faturasi kesilmemis kazanilan siparisler - SADECE Customer.
          total_uninvoiced_won'un saydiklari (uretimi Hazir/Sevkiyat)
  - alacak: 'odendi' durumundaki her odeme (Payment.amount)
Eski cari kayitlar: muhasebe PDF'inden aktarilan CustomerStatement
(source='pdf_import') satirlari - SADECE sistemin bu musteride ilk
hareketinden ONCEKI tarihler alinir (ayni hareket iki kez yazilmasin).
Sistemin kendi otomatik CustomerStatement satirlari (Satis/Tahsilat)
kullanilmaz - ayni bilgi zaten fatura/siparis/odemeden geliyor."""
from datetime import date, datetime

from app import db
from app.models import Customer, CustomerStatement, Deal, Invoice, Payment


def _gun(x):
    if x is None:
        return None
    return x.date() if isinstance(x, datetime) else x


def _kalem_detay(items):
    out = []
    for it in sorted(items, key=lambda i: i.id or 0):
        out.append({'aciklama': it.description, 'miktar': it.quantity, 'birim': it.unit,
                    'fiyat': it.unit_price, 'tutar': it.total_price})
    return out


def sistem_hareketleri(customer):
    rows = []
    faturalar = Invoice.query.filter_by(customer_id=customer.id, type='fatura').all()
    for inv in faturalar:
        rows.append({
            'tarih': _gun(inv.date) or _gun(inv.created_at), 'belge': inv.display_no,
            'aciklama': 'Fatura' + (f' · {inv.deal.display_no}' if inv.deal else ''),
            'borc': float(inv.total or 0), 'alacak': 0.0, 'detay': _kalem_detay(inv.items),
            'kaynak': 'sistem', 'sira': 1,
        })
    faturali_deal = {inv.deal_id for inv in Invoice.query.filter(
        Invoice.type == 'fatura', Invoice.deal_id.isnot(None)).with_entities(Invoice.deal_id).all()}
    for d in Deal.query.filter(Deal.customer_id == customer.id, Deal.stage == 'kazanilan').all():
        if d.id in faturali_deal or not (d.production and d.production.status in ('hazir', 'sevkiyat')):
            continue
        rows.append({
            'tarih': _gun(d.deal_date) or _gun(d.created_at), 'belge': d.display_no,
            'aciklama': 'Sipariş (faturası henüz kesilmedi)',
            'borc': float(d.value or 0), 'alacak': 0.0, 'detay': _kalem_detay(d.items),
            'kaynak': 'sistem', 'sira': 1,
        })
    yontem = {'nakit': 'nakit', 'kredi_karti': 'kredi kartı', 'havale': 'havale', 'cek': 'çek'}
    for p in Payment.query.filter_by(customer_id=customer.id, status='odendi').all():
        belge = p.invoice.display_no if p.invoice else (p.deal.display_no if p.deal else '')
        parca = ['Tahsilat']
        if p.notes and p.notes.strip():
            parca.append(p.notes.strip()[:60])
        if p.payment_method:
            parca.append(yontem.get(p.payment_method, p.payment_method))
        rows.append({
            'tarih': _gun(p.payment_date) or _gun(p.created_at), 'belge': belge,
            'aciklama': ' · '.join(parca), 'borc': 0.0, 'alacak': float(p.amount or 0),
            'detay': [], 'kaynak': 'sistem', 'sira': 2,
        })
    return rows


def eski_hareketler(customer, sistem_baslangic=None):
    q = CustomerStatement.query.filter_by(customer_id=customer.id, source='pdf_import')
    rows = []
    for s in q.all():
        t = _gun(s.created_at)
        if sistem_baslangic and t and t >= sistem_baslangic:
            continue
        borc = float(s.amount or 0) if s.type == 'borc' else 0.0
        alacak = float(s.amount or 0) if s.type != 'borc' else 0.0
        rows.append({'tarih': t, 'belge': 'eski', 'aciklama': s.description or 'Muhasebe kaydı',
                     'borc': borc, 'alacak': alacak, 'detay': [], 'kaynak': 'eski', 'sira': 0})
    return rows


def ekstre_olustur(customer, bas=None, bit=None, sistem=True, eski=True, devir=True):
    """Secime gore ekstre. Donus: {'satirlar', 'devir', 'toplam_borc',
    'toplam_alacak', 'bakiye', 'bas', 'bit', 'sistem_baslangic',
    'eski_dahil_sayi'}. Bakiye = devir + donem borc - donem alacak."""
    s_rows = sistem_hareketleri(customer)
    sistem_baslangic = min((r['tarih'] for r in s_rows if r['tarih']), default=None)
    rows = []
    if sistem:
        rows += s_rows
    if eski:
        rows += eski_hareketler(customer, sistem_baslangic)
    rows.sort(key=lambda r: (r['tarih'] or date.min, r['sira']))
    devir_tutar = 0.0
    donem = []
    for r in rows:
        t = r['tarih']
        if bas and t and t < bas:
            devir_tutar += r['borc'] - r['alacak']
            continue
        if bit and t and t > bit:
            continue
        donem.append(r)
    if not devir:
        devir_tutar = 0.0
    bakiye = devir_tutar
    for r in donem:
        bakiye += r['borc'] - r['alacak']
        r['bakiye'] = bakiye
    return {
        'satirlar': donem, 'devir': devir_tutar if (bas and devir) else None,
        'toplam_borc': sum(r['borc'] for r in donem), 'toplam_alacak': sum(r['alacak'] for r in donem),
        'bakiye': bakiye, 'bas': bas, 'bit': bit, 'sistem_baslangic': sistem_baslangic,
        'eski_dahil_sayi': sum(1 for r in donem if r['kaynak'] == 'eski'),
    }
