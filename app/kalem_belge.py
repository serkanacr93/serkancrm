"""2026-10-27 (Veri akisi 2): teklif kalemi bazinda belge (irsaliye/fatura)
takibi - "bu kalemin ne kadarina irsaliye/fatura kesildi, ne kadari kaldi".

TEK KAYNAK: fatura/irsaliye formu, manuel irsaliye "siparisten doldur",
uretim detayindaki kalem belge tablosu HEPSI buradan okur. Sadece OKUR.

Sayilanlar:
  - Invoice (type 'irsaliye' / 'fatura') kalemlerinden deal_item_id dolu olanlar
  - ManualIrsaliye kalemlerinden deal_item_id dolu olanlar -> 'irsaliye'
    (manuel irsaliyenin otomatik dahili faturasi Invoice olarak zaten
    'fatura' sayilir - kalemlerine de deal_item_id yazilir).
Eski belgeler (deal_item_id NULL) SAYILMAZ - bilincli karar (tahmini
eslestirme yapilmaz)."""
from app import db
from app.models import Invoice, InvoiceItem, ManualIrsaliye, ManualIrsaliyeItem


def kalem_belge_ozeti(deal_items):
    """{deal_item_id: {'irsaliye': qty, 'fatura': qty,
                       'irsaliye_belgeler': [no..], 'fatura_belgeler': [no..]}}"""
    ids = [di.id for di in deal_items if di.id]
    ozet = {i: {'irsaliye': 0.0, 'fatura': 0.0, 'irsaliye_belgeler': [], 'fatura_belgeler': []} for i in ids}
    if not ids:
        return ozet
    satirlar = db.session.query(InvoiceItem.deal_item_id, InvoiceItem.quantity, Invoice).join(
        Invoice, InvoiceItem.invoice_id == Invoice.id).filter(InvoiceItem.deal_item_id.in_(ids)).all()
    for did, qty, inv in satirlar:
        tur = 'irsaliye' if inv.type == 'irsaliye' else 'fatura'
        ozet[did][tur] += qty or 0
        if inv.display_no not in ozet[did][f'{tur}_belgeler']:
            ozet[did][f'{tur}_belgeler'].append(inv.display_no)
    msatir = db.session.query(ManualIrsaliyeItem.deal_item_id, ManualIrsaliyeItem.quantity, ManualIrsaliye).join(
        ManualIrsaliye, ManualIrsaliyeItem.manual_irsaliye_id == ManualIrsaliye.id).filter(
        ManualIrsaliyeItem.deal_item_id.in_(ids)).all()
    for did, qty, mi in msatir:
        ozet[did]['irsaliye'] += qty or 0
        if mi.display_no not in ozet[did]['irsaliye_belgeler']:
            ozet[did]['irsaliye_belgeler'].append(mi.display_no)
    return ozet


def siparis_kalem_durumu(deal, production=None):
    """Bir siparisin kalemleri icin: siparis miktari, uretilen/hazir miktar,
    irsaliye/fatura kesilen ve kalanlar. production verilmezse deal.production."""
    from app.pdf_utils import is_emri_kalemleri, is_emri_kalem_bilgisi
    production = production or getattr(deal, 'production', None)
    items = sorted(deal.items, key=lambda x: x.id)
    ozet = kalem_belge_ozeti(items)
    uretilen = {}
    if production is not None:
        kalemler = is_emri_kalemleri(production)
        for n, pi in enumerate(kalemler, 1):
            b = is_emri_kalem_bilgisi(production, pi, n, len(kalemler))
            di = b['deal_item']
            if di is None:
                continue
            if b['tip'] == 'ticaret':
                hazir = di.quantity if b['ticaret_durumu'] == 'teslime_hazir' else 0
            else:
                hazir = b['gerceklesen'] or 0
            uretilen[di.id] = hazir
    sonuc = []
    for di in items:
        o = ozet.get(di.id, {'irsaliye': 0.0, 'fatura': 0.0, 'irsaliye_belgeler': [], 'fatura_belgeler': []})
        hazir = uretilen.get(di.id)
        sonuc.append({
            'deal_item': di,
            'id': di.id,
            'aciklama': di.description,
            'birim': di.unit,
            'siparis': di.quantity or 0,
            'hazir': hazir,
            'irsaliye': o['irsaliye'],
            'fatura': o['fatura'],
            'irsaliye_belgeler': o['irsaliye_belgeler'],
            'fatura_belgeler': o['fatura_belgeler'],
            'kalan_irsaliye': max((di.quantity or 0) - o['irsaliye'], 0),
            'kalan_fatura': max((di.quantity or 0) - o['fatura'], 0),
            # irsaliyeye onerilen: hazir (biliniyorsa) - kesilen, yoksa siparis - kesilen
            'oneri_irsaliye': max(((hazir if hazir else (di.quantity or 0))) - o['irsaliye'], 0),
        })
    return sonuc
