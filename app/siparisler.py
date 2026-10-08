"""
Siparis (onaylanmis teklif, Deal.stage='kazanilan') ile ilgili ORTAK
yardimcilar - Komuta Merkezi ana sayfasi (index_komuta), her sayfadaki
sagdaki "Siparisler" yan sekmesi VE /siparisler sayfasi AYNI bu
fonksiyonlari kullanir (tek kaynak - uc yerde farkli sayi gorunmesin).

TANIMLAR (2026-10-08, Serkan onayladi):
- Siparis = onaylanmis teklif (Deal.stage == 'kazanilan').
- Teklif sayisi = Deal.stage != 'revize' olan TUM kayitlar (acik/kazanilan/
  kaybedilen dahil, SADECE revize edilip yerine yenisi acilmis eski
  kayitlar haric).
- Siparis tarihi = Deal.siparis_tarihi property'si (approve_deal()'da
  esanli olusturulan Production.start_date - onay anidir; Production
  yoksa deal_date'e duser). Bkz. models.py.
- Tutar (TL) = Deal.deger_tl property'si (TRY ise value aynen, doviz ise
  kullanilan_kur ile cevrilir - YENI KUR CEKME YOK, mevcut alan kullanilir;
  kur hic girilmemisse value TL gibi sayilir - bilinen bir tahmin, bkz.
  Komuta Merkezi raporu "Verdigim kararlar").
- Gorunurluk: cagiran taraf (routes.py) _deal_visibility_user_id()'yi
  cozup SONUCUNU (scope_user_id) bu modulun fonksiyonlarina PARAMETRE
  olarak verir - circular import olmasin diye bu modul current_user'a
  DOGRUDAN erismez.
"""
from datetime import date
from sqlalchemy.orm import joinedload

from app import db
from app.models import Deal, Production, TR_AYLAR


# ---- Durum turetme (yeni veri girisi YOK, mevcut kayitlardan okunur) ----

DURUM_LABELS = {
    'pesinat_bekliyor': ('Peşinat Bekliyor', 'danger'),
    'uretimde': ('Üretimde', 'warning'),
    'sevkiyata_hazir': ('Sevkiyata Hazır', 'primary'),
    'yolda': ('Yolda', 'info'),
    'teslim_edildi': ('Teslim Edildi', 'success'),
    'bakiye_bekliyor': ('Bakiye Bekliyor', 'danger'),
}


def siparis_durumu(deal):
    """Tek bir Deal (stage='kazanilan') icin MEVCUT Production/Shipment/
    odeme kayitlarindan turetilmis durum anahtari (DURUM_LABELS'teki
    key'lerden biri) veya turetilemiyorsa None. Oncelik sirasi (en
    "ileri" asama once kontrol edilir, GERIYE DOGRU):
      1) Teslim edildi + bakiye odenmemis -> 'bakiye_bekliyor' (en
         aksiyon gerektiren durum - mal gitmis, para gelmemis)
      2) Teslim edildi + bakiye tamam -> 'teslim_edildi'
      3) Kargoda/yolda -> 'yolda'
      4) Hazirlaniyor/sevkiyat asamasi -> 'sevkiyata_hazir'
      5) Uretimde + pesinat vadesi gelmis/gecmis ve odenmemis ->
         'pesinat_bekliyor'; yoksa 'uretimde'
    Bu siralama Serkan'a SORULMADI (gece modu) - en MANTIKLI/aksiyon
    odakli siralama olarak secildi, raporda ayrica belirtiliyor."""
    production = deal.production
    if not production:
        return None

    latest_shipment = production.latest_shipment

    if latest_shipment and latest_shipment.status == 'teslim_edildi':
        if not deal.payment_complete:
            return 'bakiye_bekliyor'
        return 'teslim_edildi'

    if latest_shipment and latest_shipment.status in ('yolda', 'kargoya_verildi'):
        return 'yolda'

    if (latest_shipment and latest_shipment.status == 'hazirlaniyor') or production.status in ('hazir', 'sevkiyat'):
        return 'sevkiyata_hazir'

    if production.status == 'uretimde':
        if deal.pesinat_orani is not None and deal.pesinat_tarihi and deal.pesinat_tarihi <= date.today():
            pesinat_tutari = deal.pesinat_tutari
            if pesinat_tutari and deal.paid_amount < pesinat_tutari - 0.01:
                return 'pesinat_bekliyor'
        return 'uretimde'

    return None


# ---- Ortak sorgu kurucu ----

def _siparis_query(scope_user_id, extra_filters=None):
    q = Deal.query.filter(Deal.stage == 'kazanilan')
    if scope_user_id is not None:
        q = q.filter(Deal.user_id == scope_user_id)
    if extra_filters is not None:
        for f in extra_filters:
            q = q.filter(f)
    q = q.options(
        joinedload(Deal.customer),
        joinedload(Deal.items),
        joinedload(Deal.production).joinedload(Production.shipments),
        joinedload(Deal.payments),
    )
    return q


def _siparis_row_dict(deal):
    """Deal nesnesinden, sablonlarin/60sn onbellegin GUVENLE kullanabilecegi
    DUZ (plain) bir dict uretir - onbellekte ORM nesnesi TUTULMAZ (sonraki
    istekte session kapanmis olacagindan DetachedInstanceError riski)."""
    ilk_kalem = deal.items[0] if deal.items else None
    durum_key = siparis_durumu(deal)
    durum_label, durum_renk = DURUM_LABELS.get(durum_key, (None, None))
    return {
        'id': deal.id,
        'musteri_adi': deal.customer.display_name if deal.customer else '-',
        'urun': (ilk_kalem.description[:60] if ilk_kalem and ilk_kalem.description else deal.title),
        'miktar': ilk_kalem.quantity if ilk_kalem else None,
        'birim': ilk_kalem.unit if ilk_kalem else None,
        'tarih': deal.siparis_tarihi,
        'tutar_tl': deal.deger_tl,
        'durum_key': durum_key,
        'durum_label': durum_label,
        'durum_renk': durum_renk,
    }


def teklif_siparis_sayilari(scope_user_id):
    """(toplam_teklif, siparis_sayisi, donusum_yuzdesi) - 'Verilen teklif'
    ve 'Siparise donen' Komuta Merkezi kutulari icin. TEK sorgu (GROUP BY
    stage)."""
    q = db.session.query(Deal.stage, db.func.count(Deal.id)).filter(Deal.stage != 'revize')
    if scope_user_id is not None:
        q = q.filter(Deal.user_id == scope_user_id)
    rows = q.group_by(Deal.stage).all()
    toplam = sum(c for _, c in rows)
    siparis = sum(c for stage, c in rows if stage == 'kazanilan')
    pct = (siparis / toplam * 100) if toplam else 0
    return toplam, siparis, pct


def siparis_summary(scope_user_id, limit=5):
    """Sidebar panel VE Komuta Merkezi 'Siparisler' karti PAYLASIR - bu ay
    sayisi/tutari, toplam sayisi, son N siparis (duz dict listesi,
    onbelleklenebilir)."""
    today = date.today()
    month_start = date(today.year, today.month, 1)

    all_orders = _siparis_query(scope_user_id).all()
    rows = [_siparis_row_dict(d) for d in all_orders]
    rows.sort(key=lambda r: r['tarih'] or date.min, reverse=True)

    bu_ay_rows = [r for r in rows if r['tarih'] and r['tarih'] >= month_start]
    return {
        'bu_ay_sayisi': len(bu_ay_rows),
        'bu_ay_tutar': sum(r['tutar_tl'] for r in bu_ay_rows),
        'toplam_sayisi': len(rows),
        'son_n': rows[:limit],
    }


# ---- Kullanici basina 60 saniyelik bellek-ici onbellek (sidebar icin) ----
# Is 2 (gece modu, 2026-10-08): her sayfada calistigi icin gorunurluk
# kullaniciya gore degistiginden anahtar = (scope_user_id,). TEK process'li
# (Render web servisi) kurulum icin yeterli - navbar_summary onbellegiyle
# AYNI desen (bkz. routes.py _navbar_cache).
_sidebar_cache = {}
_SIDEBAR_CACHE_TTL = 60


def sidebar_siparis_summary(scope_user_id):
    """siparis_summary()'nin 60 saniyelik onbellekli hali - base.html'deki
    her sayfada gorunen 'Siparisler' yan sekmesi icin. Onbellek anahtari
    scope_user_id (None = admin/kisitlamasiz GORUNUM de dahil kendi
    anahtari). HATA olursa (DB baglanti sorunu vb.) sayfayi BOZMADAN
    None doner - cagiran taraf (context_processor) bunu bos/varsayilan
    bir degerle degistirir."""
    import time
    now = time.monotonic()
    key = scope_user_id
    cached = _sidebar_cache.get(key)
    if cached and cached[0] > now:
        return cached[1]
    try:
        data = siparis_summary(scope_user_id, limit=5)
    except Exception:
        return None
    _sidebar_cache[key] = (now + _SIDEBAR_CACHE_TTL, data)
    return data


# ---- Aylik ozet (Komuta Merkezi + /siparisler sayfasi) ----

def aylik_teklif_siparis_ozet(scope_user_id, ay_sayisi=6):
    """Son N ay icin (bu ay dahil) teklif/siparis SAYISI - Komuta
    Merkezi'ndeki 'Aylık teklif / sipariş' cubuk grafigi icin. 'Teklif'
    burada o AY ICINDE OLUSTURULMUS (Deal.created_at) revize-harici tum
    kayitlari, 'Siparis' ise o AY ICINDE SIPARISE DONMUS (siparis_tarihi)
    kazanilan kayitlari sayar - iki farkli tarih alani kullanildigi icin
    Python tarafinda, TEK seferde cekilen kucuk bir veri kumesi uzerinde
    hesaplanir (N+1 yok)."""
    today = date.today()
    ay_listesi = []
    y, m = today.year, today.month
    for _ in range(ay_sayisi):
        ay_listesi.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    ay_listesi.reverse()
    ilk_yil, ilk_ay = ay_listesi[0]
    range_start = date(ilk_yil, ilk_ay, 1)

    teklif_q = db.session.query(Deal.created_at, Deal.stage).filter(
        Deal.stage != 'revize', Deal.created_at >= range_start
    )
    if scope_user_id is not None:
        teklif_q = teklif_q.filter(Deal.user_id == scope_user_id)
    teklif_rows = teklif_q.all()

    siparis_q = _siparis_query(scope_user_id, extra_filters=[Deal.production.has(Production.start_date >= range_start)])
    siparis_rows = [(d.siparis_tarihi) for d in siparis_q.all() if d.siparis_tarihi and d.siparis_tarihi >= range_start]

    sonuc = []
    for (y2, m2) in ay_listesi:
        teklif_sayisi = sum(1 for ca, st in teklif_rows if ca and ca.year == y2 and ca.month == m2)
        siparis_sayisi = sum(1 for t in siparis_rows if t.year == y2 and t.month == m2)
        sonuc.append({
            'ay_kisa': TR_AYLAR[m2 - 1][:3], 'yil': y2, 'teklif': teklif_sayisi, 'siparis': siparis_sayisi,
        })
    return sonuc


def siparisler_sayfa_verisi(scope_user_id, mod, ay_param, page=1, per_page=50):
    """/siparisler sayfasi - mod 'aylik' ise secili ay (ay_param='YYYY-MM'),
    'toplam' ise TUM siparisler (sayfali). 4 ozet kutu + tablo satirlari
    + sayfalama bilgisi doner."""
    today = date.today()

    if mod == 'aylik':
        try:
            ay_year, ay_month = map(int, (ay_param or '').split('-'))
            ay_start = date(ay_year, ay_month, 1)
        except (ValueError, TypeError, AttributeError):
            ay_start = date(today.year, today.month, 1)
        ay_str = ay_start.strftime('%Y-%m')
        ay_end = date(ay_start.year + 1, 1, 1) if ay_start.month == 12 else date(ay_start.year, ay_start.month + 1, 1)
        prev_ay_start = date(ay_start.year - 1, 12, 1) if ay_start.month == 1 else date(ay_start.year, ay_start.month - 1, 1)
        next_ay_start = ay_end

        q = _siparis_query(scope_user_id, extra_filters=[
            Deal.production.has(db.and_(Production.start_date >= ay_start, Production.start_date < ay_end))
        ])
        orders = q.all()
        rows = [_siparis_row_dict(d) for d in orders]
        rows.sort(key=lambda r: r['tarih'] or date.min, reverse=True)

        # Onceki ay sadece SAYI farki icin (hafif sorgu)
        prev_q = _siparis_query(scope_user_id, extra_filters=[
            Deal.production.has(db.and_(Production.start_date >= prev_ay_start, Production.start_date < ay_start))
        ])
        prev_count = prev_q.count()

        kg_toplam = sum(r['miktar'] for r in rows if r['birim'] == 'kg' and r['miktar'])
        adet_toplam = sum(r['miktar'] for r in rows if r['birim'] not in (None, 'kg') and r['miktar'])
        tutar_toplam = sum(r['tutar_tl'] for r in rows)

        kpis = {
            'siparis_sayisi': len(rows), 'kg_toplam': kg_toplam, 'adet_toplam': adet_toplam,
            'tutar_toplam': tutar_toplam, 'fark_sayi': len(rows) - prev_count,
            'ay_baslik': f'{TR_AYLAR[ay_start.month - 1]} {ay_start.year}',
        }
        # Sayfalama (Python tarafinda - aylik liste zaten kucuk bir kume)
        total = len(rows)
        start = (page - 1) * per_page
        page_rows = rows[start:start + per_page]
        return {
            'kpis': kpis, 'rows': page_rows, 'total': total, 'page': page,
            'pages': max(1, (total + per_page - 1) // per_page),
            'ay': ay_str, 'prev_ay': prev_ay_start.strftime('%Y-%m'), 'next_ay': next_ay_start.strftime('%Y-%m'),
        }

    # mod == 'toplam'
    q = _siparis_query(scope_user_id)
    orders = q.all()
    rows = [_siparis_row_dict(d) for d in orders]
    rows.sort(key=lambda r: r['tarih'] or date.min, reverse=True)

    kg_toplam = sum(r['miktar'] for r in rows if r['birim'] == 'kg' and r['miktar'])
    adet_toplam = sum(r['miktar'] for r in rows if r['birim'] not in (None, 'kg') and r['miktar'])
    tutar_toplam = sum(r['tutar_tl'] for r in rows)

    tarihli = [r['tarih'] for r in rows if r['tarih']]
    ay_sayisi = 1
    if tarihli:
        ilk, son = min(tarihli), max(tarihli)
        ay_sayisi = max(1, (son.year - ilk.year) * 12 + (son.month - ilk.month) + 1)

    kpis = {
        'siparis_sayisi': len(rows), 'kg_toplam': kg_toplam, 'adet_toplam': adet_toplam,
        'tutar_toplam': tutar_toplam, 'aylik_ortalama': len(rows) / ay_sayisi if ay_sayisi else 0,
    }
    total = len(rows)
    start = (page - 1) * per_page
    page_rows = rows[start:start + per_page]
    return {
        'kpis': kpis, 'rows': page_rows, 'total': total, 'page': page,
        'pages': max(1, (total + per_page - 1) // per_page),
    }
