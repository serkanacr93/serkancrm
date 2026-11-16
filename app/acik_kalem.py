"""Acik kalem hesabi (2026-11-16) - Tahsilat Listesi ve cari ekstre ozeti.

SADECE OKUR, hicbir kayda yazmaz. Yeni bir BAKIYE yolu ACMAZ: borc ve
tahsilat kaynaklari Customer.balance ile BIREBIR aynidir (fatura total_tl +
faturasiz hazir/sevkiyat siparis deger_tl + muhasebe eski borcu - odendi
tahsilatlar tutar_tl - muhasebe eski tahsilati). Burada yapilan tek ek is,
tahsilatlari borc kalemlerine DAGITIP her kalemin kalanini, vadesini ve
gecikme gununu cikarmaktir. Toplam (kalanlar - fazla odeme) her zaman
Customer.balance'a esittir (yuvarlama haric).

Dagitim sirasi:
  1) Faturaya bagli odeme -> o fatura.
  2) Siparise bagli (faturasiz) odeme -> o siparisin faturalari (eskiden
     yeniye) ya da faturasi yoksa siparis kalemi. (Onayda alinan pesinat
     faturaya baglanmamis olsa bile dogru yere duser.)
  3) Artan / hicbir yere bagli olmayan odemeler + muhasebe eski tahsilati
     -> vadesi en eski acik kalemden baslayarak.

Vade:
  teklifte bakiye_tarihi varsa o; yoksa odeme_vade_gun (0 = pesin) kadar gun;
  o da yoksa VARSAYILAN_VADE_GUN (30) gun. Baz tarih: fatura tarihi /
  siparis tarihi. Muhasebe eski borcunun vadesi kendi tarihidir.
"""
from datetime import datetime, timedelta

from sqlalchemy.orm import joinedload

from app import db
from app.models import Customer, CustomerStatement, Deal, Invoice, Payment, Production

VARSAYILAN_VADE_GUN = 30
YAS_DILIMLERI = [('gelmedi', 'Vadesi gelmedi'), ('g1_30', '1–30 gün'),
                 ('g31_60', '31–60 gün'), ('g61_90', '61–90 gün'), ('g90p', '90+ gün')]


def _tarih(v):
    if v is None:
        return None
    return v.date() if isinstance(v, datetime) else v


def _vade(deal, baz):
    baz = _tarih(baz)
    if deal is not None:
        if deal.bakiye_tarihi:
            return _tarih(deal.bakiye_tarihi)
        if deal.odeme_vade_gun is not None and baz:
            return baz + timedelta(days=int(deal.odeme_vade_gun))
    return baz + timedelta(days=VARSAYILAN_VADE_GUN) if baz else None


def _yas_dilimi(gecikme):
    if gecikme is None or gecikme <= 0:
        return 'gelmedi'
    if gecikme <= 30:
        return 'g1_30'
    if gecikme <= 60:
        return 'g31_60'
    if gecikme <= 90:
        return 'g61_90'
    return 'g90p'


def _bos_sonuc(customer):
    return {'customer': customer, 'kalemler': [], 'toplam_borc': 0.0, 'vadesi_gecen': 0.0,
            'vadesi_gelmeyen': 0.0, 'fazla_odeme': 0.0, 'en_eski_gecikme': None,
            'en_yakin_vade': None, 'son_odeme': None,
            'yas': {k: 0.0 for k, _ in YAS_DILIMLERI}}


def hesapla(customer_ids=None, bugun=None):
    """{customer_id: sonuc}. customer_ids None ise hareketi olan TUM musteriler.
    Sabit sayida sorgu atar (musteri basina sorgu YOK - eski devir haric,
    o sadece pdf_import kaydi olan az sayida musteride calisir)."""
    bugun = bugun or datetime.now().date()
    ids = set(customer_ids) if customer_ids is not None else None

    inv_q = Invoice.query.filter(Invoice.type == 'fatura')
    pay_q = Payment.query.filter(Payment.status == 'odendi')
    deal_q = (Deal.query.options(joinedload(Deal.production))
              .join(Production, Production.deal_id == Deal.id)
              .filter(Deal.stage == 'kazanilan', Production.status.in_(('hazir', 'sevkiyat'))))
    eski_q = db.session.query(CustomerStatement.customer_id).filter(CustomerStatement.source == 'pdf_import')
    if ids is not None:
        if not ids:
            return {}
        inv_q = inv_q.filter(Invoice.customer_id.in_(ids))
        pay_q = pay_q.filter(Payment.customer_id.in_(ids))
        deal_q = deal_q.filter(Deal.customer_id.in_(ids))
        eski_q = eski_q.filter(CustomerStatement.customer_id.in_(ids))
    invoices = inv_q.all()
    payments = pay_q.all()
    deals = deal_q.all()
    # 2026-11-17 (hiz): Payment.tutar_tl ve vade hesabi p.deal / p.invoice /
    # p.invoice.deal'e bakar - bunlar oturumda yoksa HER odeme icin ayri sorgu
    # atiliyordu. Gereken fatura ve siparisler burada TOPLUCA yuklenir
    # (oturumun kimlik haritasina girer, sonraki erisimler sorgu atmaz).
    _inv_ids = {p.invoice_id for p in payments if p.invoice_id} - {i.id for i in invoices}
    _ek_inv = Invoice.query.filter(Invoice.id.in_(_inv_ids)).all() if _inv_ids else []
    _deal_ids = ({p.deal_id for p in payments if p.deal_id} | {i.deal_id for i in invoices if i.deal_id}
                 | {i.deal_id for i in _ek_inv if i.deal_id}) - {d.id for d in deals}
    _ek_deal = Deal.query.options(joinedload(Deal.production)).filter(Deal.id.in_(_deal_ids)).all() if _deal_ids else []
    eski_ids = {cid for (cid,) in eski_q.distinct().all()}

    # Faturasi (type='fatura') olan siparisler - Customer.total_uninvoiced_won
    # ile ayni kural: musteri filtresinden BAGIMSIZ, tum faturalara bakilir.
    if ids is None:
        faturali_deal_ids = {i.deal_id for i in invoices if i.deal_id}
    else:
        faturali_deal_ids = {d for (d,) in db.session.query(Invoice.deal_id).filter(
            Invoice.type == 'fatura', Invoice.deal_id.isnot(None)).distinct().all()}

    cids = ({i.customer_id for i in invoices} | {p.customer_id for p in payments}
            | {d.customer_id for d in deals} | eski_ids)
    if ids is not None:
        cids |= ids
    cids.discard(None)
    if not cids:
        return {}
    customers = {c.id: c for c in Customer.query.filter(Customer.id.in_(cids)).all()}
    sonuc = {cid: _bos_sonuc(c) for cid, c in customers.items()}

    kalem_fatura = {}   # invoice.id -> kalem
    kalem_siparis = {}  # deal.id -> kalem (faturasiz teslim)
    deal_faturalari = {}  # deal.id -> [kalem] (tarih sirali)

    def _kalem(cid, **kw):
        k = dict(odenen=0.0, kalan=0.0, gecikme=None, **kw)
        sonuc[cid]['kalemler'].append(k)
        return k

    for inv in sorted(invoices, key=lambda i: (_tarih(i.date) or bugun, i.id)):
        if inv.customer_id not in sonuc:
            continue
        k = _kalem(inv.customer_id, tur='fatura', belge=inv.display_no, belge_id=inv.id,
                   deal_id=inv.deal_id, tarih=_tarih(inv.date), vade=_vade(inv.deal, inv.date),
                   tutar=float(inv.total_tl or 0), aciklama='')
        kalem_fatura[inv.id] = k
        if inv.deal_id:
            deal_faturalari.setdefault(inv.deal_id, []).append(k)

    for d in deals:
        if d.id in faturali_deal_ids or d.customer_id not in sonuc:
            continue
        baz = d.siparis_tarihi
        k = _kalem(d.customer_id, tur='siparis', belge=d.display_no, belge_id=d.id, deal_id=d.id,
                   tarih=_tarih(baz), vade=_vade(d, baz), tutar=float(d.deger_tl or 0),
                   aciklama='faturasız teslim')
        kalem_siparis[d.id] = k

    havuz = {cid: 0.0 for cid in sonuc}
    for cid in eski_ids:
        if cid not in sonuc:
            continue
        e = customers[cid].eski_devir()
        if e['borc'] > 0.005:
            _kalem(cid, tur='eski', belge='Eski borç', belge_id=None, deal_id=None,
                   tarih=_tarih(e['ilk_tarih']), vade=_tarih(e['ilk_tarih']),
                   tutar=float(e['borc']), aciklama='muhasebe')
        havuz[cid] += float(e['tahsilat'] or 0)

    def _dus(kalemler, tutar):
        for k in kalemler:
            if tutar <= 0.005:
                break
            acik = k['tutar'] - k['odenen']
            if acik <= 0.005:
                continue
            pay = min(acik, tutar)
            k['odenen'] += pay
            tutar -= pay
        return max(tutar, 0.0)

    for p in sorted(payments, key=lambda x: (_tarih(x.payment_date) or bugun, x.id)):
        cid = p.customer_id
        if cid not in sonuc:
            continue
        tutar = float(p.tutar_tl or 0)
        s = sonuc[cid]
        pt = _tarih(p.payment_date)
        if pt and (s['son_odeme'] is None or pt >= s['son_odeme']['tarih']):
            s['son_odeme'] = {'tarih': pt, 'tutar': tutar}
        hedef = []
        if p.invoice_id and p.invoice_id in kalem_fatura and kalem_fatura[p.invoice_id] in s['kalemler']:
            hedef = [kalem_fatura[p.invoice_id]]
        else:
            did = p.deal_id or (p.invoice.deal_id if p.invoice is not None else None)
            if did:
                hedef = [k for k in deal_faturalari.get(did, []) if k in s['kalemler']]
                if not hedef and did in kalem_siparis and kalem_siparis[did] in s['kalemler']:
                    hedef = [kalem_siparis[did]]
        havuz[cid] += _dus(hedef, tutar) if hedef else tutar

    for cid, s in sonuc.items():
        sirali = sorted(s['kalemler'], key=lambda k: (k['vade'] or bugun, k['tarih'] or bugun))
        artan = _dus(sirali, havuz[cid])
        acik = []
        for k in sirali:
            k['kalan'] = round(k['tutar'] - k['odenen'], 2)
            if k['kalan'] <= 0.01:
                continue
            k['gecikme'] = (bugun - k['vade']).days if k['vade'] else None
            k['dilim'] = _yas_dilimi(k['gecikme'])
            acik.append(k)
            s['yas'][k['dilim']] += k['kalan']
            if k['gecikme'] is not None and k['gecikme'] > 0:
                s['vadesi_gecen'] += k['kalan']
                if s['en_eski_gecikme'] is None or k['gecikme'] > s['en_eski_gecikme']:
                    s['en_eski_gecikme'] = k['gecikme']
            else:
                s['vadesi_gelmeyen'] += k['kalan']
                if k['vade'] and (s['en_yakin_vade'] is None or k['vade'] < s['en_yakin_vade']):
                    s['en_yakin_vade'] = k['vade']
        s['kalemler'] = acik
        s['toplam_borc'] = round(sum(k['kalan'] for k in acik), 2)
        s['vadesi_gecen'] = round(s['vadesi_gecen'], 2)
        s['vadesi_gelmeyen'] = round(s['vadesi_gelmeyen'], 2)
        s['fazla_odeme'] = round(artan, 2) if artan > 0.01 else 0.0
    return sonuc


def musteri_acik_kalemleri(customer, bugun=None):
    """Tek musteri icin sonuc (ekstre ozeti)."""
    if customer is None or customer.id is None:
        return _bos_sonuc(customer)
    return hesapla([customer.id], bugun=bugun).get(customer.id) or _bos_sonuc(customer)


def tahsilat_listesi(bugun=None, yakin_gun=15):
    """Tahsilat Listesi sayfasi verisi: acik borcu olan musteriler + genel ozet."""
    bugun = bugun or datetime.now().date()
    hepsi = hesapla(bugun=bugun)
    satirlar = [s for s in hepsi.values() if s['toplam_borc'] > 0.01]
    ozet = {
        'toplam': round(sum(s['toplam_borc'] for s in satirlar), 2),
        'musteri_sayisi': len(satirlar),
        'vadesi_gecen': round(sum(s['vadesi_gecen'] for s in satirlar), 2),
        'vadesi_gecen_musteri': sum(1 for s in satirlar if s['vadesi_gecen'] > 0.01),
        'yas': {k: round(sum(s['yas'][k] for s in satirlar), 2) for k, _ in YAS_DILIMLERI},
        'yakin_gun': yakin_gun,
    }
    sinir = bugun + timedelta(days=yakin_gun)
    yakin = [k for s in satirlar for k in s['kalemler']
             if k['vade'] and bugun <= k['vade'] <= sinir and (k['gecikme'] or 0) <= 0]
    ozet['yakin_tutar'] = round(sum(k['kalan'] for k in yakin), 2)
    ozet['yakin_kalem'] = len(yakin)
    ay_basi = bugun.replace(day=1)
    ay_odemeleri = Payment.query.filter(Payment.status == 'odendi', Payment.payment_date >= ay_basi,
                                        Payment.payment_date <= bugun).all()
    ozet['bu_ay_tahsilat'] = round(sum(float(p.tutar_tl or 0) for p in ay_odemeleri), 2)
    ozet['bu_ay_odeme_sayisi'] = len(ay_odemeleri)
    return satirlar, ozet
