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


def gonderilen_ozeti(deal_item_ids):
    """2026-10-27 (Sevk/fatura korumalari): kalem basina musteriye GONDERILEN
    miktar. {deal_item_id: {'manuel', 'irsaliye', 'sevkiyat', 'toplam'}}.
      - manuel: Manuel Irsaliye kalemleri (siparisten doldurulanlar)
      - irsaliye: siparisten kesilen irsaliye (Invoice type='irsaliye')
      - sevkiyat: Uretim Detayi 'Gonderildi' / sevkiyat kalemleri
    Siparisten irsaliye + sevkiyat AYNI malin iki belgesi oldugu icin
    toplanmaz, buyugu alinir; manuel irsaliye ayri bir gonderim yoludur:
        toplam = manuel + max(irsaliye, sevkiyat)
    Sadece okur; 3 sorgu (kalem sayisindan bagimsiz)."""
    from app.models import ShipmentItem, ProductionItem
    ids = [i for i in deal_item_ids if i]
    sonuc = {i: {'manuel': 0.0, 'irsaliye': 0.0, 'sevkiyat': 0.0, 'toplam': 0.0} for i in ids}
    if not ids:
        return sonuc
    for did, qty in db.session.query(ManualIrsaliyeItem.deal_item_id, ManualIrsaliyeItem.quantity).filter(
            ManualIrsaliyeItem.deal_item_id.in_(ids)).all():
        sonuc[did]['manuel'] += qty or 0
    for did, qty in db.session.query(InvoiceItem.deal_item_id, InvoiceItem.quantity).join(
            Invoice, InvoiceItem.invoice_id == Invoice.id).filter(
            Invoice.type == 'irsaliye', InvoiceItem.deal_item_id.in_(ids)).all():
        sonuc[did]['irsaliye'] += qty or 0
    for did, qty in db.session.query(ProductionItem.deal_item_id, ShipmentItem.quantity).join(
            ProductionItem, ShipmentItem.production_item_id == ProductionItem.id).filter(
            ProductionItem.deal_item_id.in_(ids)).all():
        sonuc[did]['sevkiyat'] += qty or 0
    for v in sonuc.values():
        v['toplam'] = v['manuel'] + max(v['irsaliye'], v['sevkiyat'])
    return sonuc


def _gonderilen_cache():
    try:
        from flask import g, has_app_context
        if not has_app_context():
            return None
        return g.setdefault('_gonderilen_cache', {})
    except Exception:
        return None


def gonderilen_haritasi(production):
    """Uretimin siparis kalemleri icin gonderilen_ozeti - istek boyunca
    onbellekte (flask.g). Uygulama baglami yoksa (PDF testleri) {}."""
    cache = _gonderilen_cache()
    deal = getattr(production, 'deal', None)
    did = getattr(deal, 'id', None)
    if cache is None or did is None:
        return {}
    if did not in cache:
        cache[did] = gonderilen_ozeti([x.id for x in deal.items])
    return cache[did]


def gonderilen_onyukle(productions):
    """Cok uretimli ekranlar (Is Emirleri, Siparisler, toplu PDF) icin TEK
    seferde yukler - N+1 olmasin."""
    cache = _gonderilen_cache()
    if cache is None:
        return
    eksik = {}
    for p in productions:
        deal = getattr(p, 'deal', None)
        if deal is not None and deal.id not in cache:
            eksik[deal.id] = [x.id for x in deal.items]
    if not eksik:
        return
    hepsi = gonderilen_ozeti([i for ids in eksik.values() for i in ids])
    for did, ids in eksik.items():
        cache[did] = {i: hepsi[i] for i in ids if i in hepsi}


def gonderilen_cache_temizle():
    cache = _gonderilen_cache()
    if cache is not None:
        cache.clear()


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
    uretim_kaydi = {}
    gh = gonderilen_haritasi(production) if production is not None else (gonderilen_ozeti([d.id for d in items]) if _gonderilen_cache() is not None else {})
    if production is not None:
        kalemler = is_emri_kalemleri(production)
        for n, pi in enumerate(kalemler, 1):
            b = is_emri_kalem_bilgisi(production, pi, n, len(kalemler))
            di = b['deal_item']
            if di is None:
                continue
            if b['tip'] == 'ticaret':
                hazir = di.quantity if b['ticaret_durumu'] == 'teslime_hazir' else 0
                kayit = hazir
            else:
                hazir = b['gerceklesen'] or 0
                kayit = b.get('uretim_kaydi', hazir) or 0
            uretilen[di.id] = hazir
            uretim_kaydi[di.id] = kayit
    sonuc = []
    for di in items:
        o = ozet.get(di.id, {'irsaliye': 0.0, 'fatura': 0.0, 'irsaliye_belgeler': [], 'fatura_belgeler': []})
        hazir = uretilen.get(di.id)
        gonderilen = (gh.get(di.id) or {}).get('toplam', 0.0)
        # 2026-10-27: fatura ust siniri = gonderilen ile uretilenin buyugu
        # (ikisi de yoksa siparis). "3 koli once gitti, toplam 15 uretildi"
        # -> 15'e kadar faturalanir; 3'u zaten faturaliysa kalan 12.
        if max(gonderilen, hazir or 0) > 0.0005:
            ust = max(gonderilen, hazir or 0)
            ust_kaynak = 'gönderilen' if gonderilen >= (hazir or 0) else 'üretilen'
        else:
            ust, ust_kaynak = (di.quantity or 0), 'sipariş'
        kayit = uretim_kaydi.get(di.id)
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
            'oneri_irsaliye': max(((kayit if kayit else (di.quantity or 0))) - gonderilen, 0),
            'gonderilen': gonderilen,
            'uretim_kaydi': kayit,
            'fatura_ust': ust, 'fatura_ust_kaynak': ust_kaynak,
            'kalan_fatura_gercek': max(ust - o['fatura'], 0),
            'kalan_gonderim': max((di.quantity or 0) - gonderilen, 0),
            'gunluk_eksik': bool(kayit is not None and gonderilen > (kayit or 0) + 0.0005),
        })
    return sonuc


def _ad(s):
    return ' '.join((s or '').split()).casefold()


def fatura_uretim_karsilastirma(deal):
    """2026-10-31: siparise kesilen TUM faturalarin (type='fatura') kalem
    miktarlari ile gunluk uretim (gunluk kayit + uretim detayinda elle
    girilen) kalem kalem karsilastirilir. SADECE OKUR.
    Eski faturalarda kalem bagi (deal_item_id) yok - ayni siparisteki
    baglanmamis fatura kalemleri, ADI siparis kalemiyle birebir ayni ise
    (bosluk/buyuk-kucuk harf farki hariç) o kaleme sayilir; eslesmeyenler
    'siparişte yok' satiri olur.
    Donus: {'satirlar': [...], 'cakisma': int}. Satir: aciklama, birim,
    siparis, uretim (None = kayit yok), faturalanan, fark, durum
    ('tutuyor' | 'fazla' | 'eksik' | 'uretim_yok' | 'sipariste_yok')."""
    if deal is None:
        return {'satirlar': [], 'cakisma': 0}
    try:
        durumlar = {k['id']: k for k in siparis_kalem_durumu(deal)}
    except Exception:
        durumlar = {}
    kalemler = sorted(deal.items, key=lambda x: x.id)
    ad_harita = {}
    for di in kalemler:
        ad_harita.setdefault(_ad(di.description), di.id)
    faturalanan = {di.id: 0.0 for di in kalemler}
    ekstra = {}
    for inv in Invoice.query.filter_by(deal_id=deal.id, type='fatura').all():
        for it in inv.items:
            did = it.deal_item_id if it.deal_item_id in faturalanan else ad_harita.get(_ad(it.description))
            if did is not None:
                faturalanan[did] += it.quantity or 0
            else:
                anahtar = (_ad(it.description), (it.unit or '').casefold())
                e = ekstra.setdefault(anahtar, {'aciklama': it.description, 'birim': it.unit, 'miktar': 0.0})
                e['miktar'] += it.quantity or 0
    satirlar = []
    for di in kalemler:
        k = durumlar.get(di.id) or {}
        uretim = k.get('uretim_kaydi')
        if uretim is None:
            uretim = k.get('hazir')
        f = faturalanan[di.id]
        if not uretim:
            durum, fark = 'uretim_yok', None
        else:
            fark = f - uretim
            durum = 'tutuyor' if abs(fark) < 0.0005 else ('fazla' if fark > 0 else 'eksik')
        satirlar.append({'aciklama': di.description, 'birim': di.unit, 'siparis': di.quantity or 0,
                         'uretim': uretim or None, 'faturalanan': f, 'fark': fark, 'durum': durum})
    for e in ekstra.values():
        satirlar.append({'aciklama': e['aciklama'], 'birim': e['birim'], 'siparis': None, 'uretim': None,
                         'faturalanan': e['miktar'], 'fark': None, 'durum': 'sipariste_yok'})
    cakisma = sum(1 for s in satirlar if s['durum'] in ('fazla', 'eksik', 'sipariste_yok'))
    return {'satirlar': satirlar, 'cakisma': cakisma}
