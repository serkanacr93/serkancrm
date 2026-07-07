"""
Google Places API (New) ile potansiyel musteri arama motoru.

places:searchText endpoint'i, istenen alan maskesiyle (FieldMask)
tek bir cagrida hem temel bilgileri (isim, adres) hem de iletisim
bilgilerini (telefon, website) dondurur - bu yuzden eski (legacy)
API'nin aksine, sonuc basina ayrica "Place Details" cagrisi gerekmez:
her il x sektor kombinasyonu = tam olarak 1 istek.

rating/review gibi Atmosphere Data alanlari FieldMask'e hic
eklenmez, maliyeti artirmaz.
"""
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from app import db
from app.models import PotentialCustomer, PlacesSearchConfig, PlacesSearchLog

TR_TZ = ZoneInfo('Europe/Istanbul')
UTC_TZ = ZoneInfo('UTC')

DAILY_REQUEST_LIMIT = 75
COST_PER_REQUEST = 0.035
COST_90_DAY_BUDGET = 250.0

SEARCH_URL = 'https://places.googleapis.com/v1/places:searchText'
FIELD_MASK = ('places.displayName,places.formattedAddress,'
              'places.nationalPhoneNumber,places.internationalPhoneNumber,'
              'places.websiteUri')

# Manuel arama formunda gosterilen 81 ilin tamami (plaka sirasi).
ALL_CITIES = [
    'Adana', 'Adıyaman', 'Afyonkarahisar', 'Ağrı', 'Amasya', 'Ankara', 'Antalya',
    'Artvin', 'Aydın', 'Balıkesir', 'Bilecik', 'Bingöl', 'Bitlis', 'Bolu', 'Burdur',
    'Bursa', 'Çanakkale', 'Çankırı', 'Çorum', 'Denizli', 'Diyarbakır', 'Edirne',
    'Elazığ', 'Erzincan', 'Erzurum', 'Eskişehir', 'Gaziantep', 'Giresun', 'Gümüşhane',
    'Hakkari', 'Hatay', 'Isparta', 'Mersin', 'İstanbul', 'İzmir', 'Kars', 'Kastamonu',
    'Kayseri', 'Kırklareli', 'Kırşehir', 'Kocaeli', 'Konya', 'Kütahya', 'Malatya',
    'Manisa', 'Kahramanmaraş', 'Mardin', 'Muğla', 'Muş', 'Nevşehir', 'Niğde', 'Ordu',
    'Rize', 'Sakarya', 'Samsun', 'Siirt', 'Sinop', 'Sivas', 'Tekirdağ', 'Tokat',
    'Trabzon', 'Tunceli', 'Şanlıurfa', 'Uşak', 'Van', 'Yozgat', 'Zonguldak', 'Aksaray',
    'Bayburt', 'Karaman', 'Kırıkkale', 'Batman', 'Şırnak', 'Bartın', 'Ardahan', 'Iğdır',
    'Yalova', 'Karabük', 'Kilis', 'Osmaniye', 'Düzce',
]

# Otomatik (zamanlanmis) rotasyon icin kucuk, oncelikli sehir listesi -
# manuel aramada kullanici ALL_CITIES icinden istedigini secer.
AUTO_ROTATION_CITIES = ['Konya', 'İstanbul', 'Ankara', 'İzmir', 'Bursa', 'Antalya',
                         'Adana', 'Gaziantep', 'Kayseri', 'Mersin']

# 'Diger' aranabilir bir sektor terimi olmadigi icin arama listesine girmez.
SEARCH_SECTORS = [s for s in PotentialCustomer.SECTORS if s != 'Diğer']


def get_config():
    config = PlacesSearchConfig.query.get(1)
    if not config:
        config = PlacesSearchConfig(id=1, enabled=False, last_combo_index=0)
        db.session.add(config)
        db.session.commit()
    return config


def _tr_day_bounds(reference=None):
    """Verilen zamanin (varsayilan: simdi) Turkiye gunune denk gelen
    [baslangic, bitis) UTC (naive) araligini dondurur."""
    now_tr = (reference or datetime.now(TR_TZ)).astimezone(TR_TZ)
    start_tr = now_tr.replace(hour=0, minute=0, second=0, microsecond=0)
    end_tr = start_tr + timedelta(days=1)
    start_utc = start_tr.astimezone(UTC_TZ).replace(tzinfo=None)
    end_utc = end_tr.astimezone(UTC_TZ).replace(tzinfo=None)
    return start_utc, end_utc


def _tr_month_bounds():
    now_tr = datetime.now(TR_TZ)
    start_tr = now_tr.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if now_tr.month == 12:
        end_tr = start_tr.replace(year=now_tr.year + 1, month=1)
    else:
        end_tr = start_tr.replace(month=now_tr.month + 1)
    return start_tr.astimezone(UTC_TZ).replace(tzinfo=None), end_tr.astimezone(UTC_TZ).replace(tzinfo=None)


def is_business_hours(reference=None):
    now_tr = (reference or datetime.now(TR_TZ)).astimezone(TR_TZ)
    return now_tr.weekday() < 5 and 9 <= now_tr.hour <= 18


def todays_request_count():
    start_utc, end_utc = _tr_day_bounds()
    total = db.session.query(db.func.coalesce(db.func.sum(PlacesSearchLog.request_count), 0)).filter(
        PlacesSearchLog.run_at >= start_utc, PlacesSearchLog.run_at < end_utc
    ).scalar()
    return total or 0


def todays_new_companies():
    start_utc, end_utc = _tr_day_bounds()
    total = db.session.query(db.func.coalesce(db.func.sum(PlacesSearchLog.new_companies), 0)).filter(
        PlacesSearchLog.run_at >= start_utc, PlacesSearchLog.run_at < end_utc
    ).scalar()
    return total or 0


def month_stats():
    start_utc, end_utc = _tr_month_bounds()
    total = db.session.query(db.func.coalesce(db.func.sum(PlacesSearchLog.request_count), 0)).filter(
        PlacesSearchLog.run_at >= start_utc, PlacesSearchLog.run_at < end_utc
    ).scalar() or 0
    return {'requests': total, 'cost': round(total * COST_PER_REQUEST, 2)}


def last_90_days_stats():
    start_utc = datetime.utcnow() - timedelta(days=90)
    total = db.session.query(db.func.coalesce(db.func.sum(PlacesSearchLog.request_count), 0)).filter(
        PlacesSearchLog.run_at >= start_utc
    ).scalar() or 0
    cost = round(total * COST_PER_REQUEST, 2)
    return {'requests': total, 'cost': cost, 'budget': COST_90_DAY_BUDGET,
            'percent': round(min(cost / COST_90_DAY_BUDGET * 100, 100), 1)}


def get_status(config=None):
    config = config or get_config()
    if not config.enabled:
        return 'kapatildi'
    if is_business_hours():
        return 'aktif'
    return 'pasif'


def _next_auto_combo(config):
    combos = [(c, s) for c in AUTO_ROTATION_CITIES for s in SEARCH_SECTORS]
    idx = config.last_combo_index % len(combos)
    config.last_combo_index = idx + 1
    db.session.commit()
    return combos[idx]


def _search_text(query, api_key):
    headers = {
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': api_key,
        'X-Goog-FieldMask': FIELD_MASK,
    }
    body = {'textQuery': query, 'languageCode': 'tr'}
    resp = requests.post(SEARCH_URL, json=body, headers=headers, timeout=15)
    data = resp.json() if resp.content else {}
    if resp.status_code != 200:
        message = data.get('error', {}).get('message', resp.text[:300])
        raise RuntimeError(f'{resp.status_code}: {message}')
    return data.get('places', [])


def _run_one_combo(city, sector, triggered_by):
    """Tek bir il x sektor icin arama yapar, sonuclari havuza ekler,
    bir PlacesSearchLog kaydi olusturur. Her cagri = 1 istek."""
    query = f"{sector} {city}"
    api_key = os.environ.get('GOOGLE_PLACES_API_KEY')

    if not api_key:
        log = PlacesSearchLog(city=city, sector=sector, search_query=query, request_count=0,
                               results_found=0, new_companies=0, triggered_by=triggered_by,
                               error='GOOGLE_PLACES_API_KEY tanimli degil.')
        db.session.add(log)
        db.session.commit()
        return {'city': city, 'sector': sector, 'query': query, 'request_count': 0,
                'results_found': 0, 'new_companies': 0, 'error': log.error}

    try:
        places = _search_text(query, api_key)
    except Exception as e:
        log = PlacesSearchLog(city=city, sector=sector, search_query=query, request_count=1,
                               results_found=0, new_companies=0, triggered_by=triggered_by,
                               error=str(e)[:500])
        db.session.add(log)
        db.session.commit()
        return {'city': city, 'sector': sector, 'query': query, 'request_count': 1,
                'results_found': 0, 'new_companies': 0, 'error': str(e)}

    results_found = len(places)
    new_companies = 0
    for place in places:
        name = (place.get('displayName') or {}).get('text')
        if not name:
            continue
        phone = place.get('nationalPhoneNumber') or place.get('internationalPhoneNumber')

        if phone and PotentialCustomer.query.filter_by(phone=phone).first():
            continue  # telefon numarasina gore tekrar kontrolu

        pc = PotentialCustomer(
            company_name=name,
            phone=phone,
            address=place.get('formattedAddress'),
            city=city,
            sector=sector,
            source='Otomatik',
            status='Aranacak',
            notes=f"Google Places ile bulundu. Website: {place.get('websiteUri') or '-'}",
        )
        db.session.add(pc)
        new_companies += 1

    db.session.commit()

    log = PlacesSearchLog(city=city, sector=sector, search_query=query, request_count=1,
                           results_found=results_found, new_companies=new_companies,
                           triggered_by=triggered_by)
    db.session.add(log)
    db.session.commit()

    return {'city': city, 'sector': sector, 'query': query, 'request_count': 1,
            'results_found': results_found, 'new_companies': new_companies, 'error': None}


def run_search(triggered_by='otomatik'):
    """Zamanlayici tarafindan cagrilir: rotasyondaki bir sonraki il x
    sektor kombinasyonuyla TEK bir arama yapar."""
    config = get_config()
    if not config.enabled:
        return {'skipped': True, 'reason': 'Sistem pasif (kapali).'}

    used_today = todays_request_count()
    if used_today >= DAILY_REQUEST_LIMIT:
        return {'skipped': True, 'reason': f'Günlük kota doldu ({used_today}/{DAILY_REQUEST_LIMIT}).'}

    city, sector = _next_auto_combo(config)
    result = _run_one_combo(city, sector, triggered_by)
    return {'skipped': False, **result}


def run_batch_search(cities, sectors, triggered_by='manuel'):
    """Secilen il(ler) x sektor(ler) kombinasyonlarinin tamamini,
    gunluk kalan kotayla sinirli olarak calistirir."""
    valid_cities = [c for c in cities if c in ALL_CITIES]
    valid_sectors = [s for s in sectors if s in SEARCH_SECTORS]
    if not valid_cities or not valid_sectors:
        return {'skipped': True, 'reason': 'En az bir il ve bir sektör seçmelisiniz.'}

    used_today = todays_request_count()
    remaining = DAILY_REQUEST_LIMIT - used_today
    if remaining <= 0:
        return {'skipped': True, 'reason': f'Günlük kota doldu ({used_today}/{DAILY_REQUEST_LIMIT}).'}

    combos = [(c, s) for c in valid_cities for s in valid_sectors]
    executed = []
    combos_skipped = 0

    for city, sector in combos:
        if remaining <= 0:
            combos_skipped += 1
            continue
        result = _run_one_combo(city, sector, triggered_by)
        remaining -= result['request_count']
        executed.append(result)

    return {
        'skipped': False,
        'combos_run': len(executed),
        'combos_skipped': combos_skipped,
        'total_requests': sum(r['request_count'] for r in executed),
        'total_results': sum(r['results_found'] for r in executed),
        'total_new': sum(r['new_companies'] for r in executed),
        'errors': [r for r in executed if r.get('error')],
        'details': executed,
    }
