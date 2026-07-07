"""
Google Places API ile otomatik potansiyel musteri arama motoru.

Maliyet kontrolu icin:
- Metin arama (places()) ile aday firmalar bulunur (Basic Data, ucretsize yakin).
- Her aday icin place() (Place Details) cagrisi SADECE gerekli alanlarla
  yapilir (name, formatted_address, formatted_phone_number, website,
  international_phone_number) - rating/review gibi Atmosphere Data
  istenmez, maliyeti artirmaz.
"""
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import googlemaps

from app import db
from app.models import PotentialCustomer, PlacesSearchConfig, PlacesSearchLog

TR_TZ = ZoneInfo('Europe/Istanbul')
UTC_TZ = ZoneInfo('UTC')

DAILY_REQUEST_LIMIT = 75
COST_PER_REQUEST = 0.035
MAX_RESULTS_PER_RUN = 5
COST_90_DAY_BUDGET = 250.0

# Konya once aranir, sonra diger buyuk iller.
CITIES = ['Konya', 'İstanbul', 'Ankara', 'İzmir', 'Bursa', 'Antalya',
          'Adana', 'Gaziantep', 'Kayseri', 'Mersin']
# 'Diger' aranabilir bir sektor terimi olmadigi icin rotasyona dahil edilmez.
SEARCH_SECTORS = [s for s in PotentialCustomer.SECTORS if s != 'Diğer']

PLACE_DETAIL_FIELDS = ['name', 'formatted_address', 'formatted_phone_number',
                        'website', 'international_phone_number']


def _get_client():
    api_key = os.environ.get('GOOGLE_PLACES_API_KEY')
    if not api_key:
        raise RuntimeError('GOOGLE_PLACES_API_KEY ortam degiskeni tanimli degil.')
    return googlemaps.Client(key=api_key)


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


def _next_combo(config):
    combos = [(c, s) for c in CITIES for s in SEARCH_SECTORS]
    idx = config.last_combo_index % len(combos)
    config.last_combo_index = idx + 1
    db.session.commit()
    return combos[idx]


def run_search(triggered_by='otomatik'):
    """Bir arama turu calistirir. Kapaliysa veya gunluk kota dolmussa
    hicbir API cagrisi yapmadan durumu dondurur."""
    config = get_config()
    if not config.enabled:
        return {'skipped': True, 'reason': 'Sistem pasif (kapali).'}

    used_today = todays_request_count()
    if used_today >= DAILY_REQUEST_LIMIT:
        return {'skipped': True, 'reason': f'Gunluk kota doldu ({used_today}/{DAILY_REQUEST_LIMIT}).'}

    city, sector = _next_combo(config)
    query = f"{sector} {city}"
    request_count = 0
    results_found = 0
    new_companies = 0

    try:
        gmaps = _get_client()
        search_result = gmaps.places(query=query, language='tr')
        request_count += 1
        candidates = search_result.get('results', [])[:MAX_RESULTS_PER_RUN]
        results_found = len(candidates)

        remaining_quota = DAILY_REQUEST_LIMIT - used_today - request_count

        for place in candidates:
            if remaining_quota <= 0:
                break
            place_id = place.get('place_id')
            if not place_id:
                continue

            details = gmaps.place(place_id=place_id, fields=PLACE_DETAIL_FIELDS, language='tr')
            request_count += 1
            remaining_quota -= 1
            result = details.get('result', {})

            name = result.get('name')
            if not name:
                continue
            phone = result.get('formatted_phone_number') or result.get('international_phone_number')

            if phone and PotentialCustomer.query.filter_by(phone=phone).first():
                continue  # telefon numarasina gore tekrar kontrolu

            pc = PotentialCustomer(
                company_name=name,
                phone=phone,
                address=result.get('formatted_address'),
                city=city,
                sector=sector,
                source='Otomatik',
                status='Aranacak',
                notes=f"Google Places otomatik arama. Website: {result.get('website') or '-'}",
            )
            db.session.add(pc)
            new_companies += 1

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        log = PlacesSearchLog(city=city, sector=sector, search_query=query, request_count=request_count,
                               results_found=results_found, new_companies=0,
                               triggered_by=triggered_by, error=str(e)[:500])
        db.session.add(log)
        db.session.commit()
        return {'skipped': False, 'error': str(e), 'city': city, 'sector': sector}

    log = PlacesSearchLog(city=city, sector=sector, search_query=query, request_count=request_count,
                           results_found=results_found, new_companies=new_companies,
                           triggered_by=triggered_by)
    db.session.add(log)
    db.session.commit()

    return {
        'skipped': False, 'city': city, 'sector': sector, 'query': query,
        'request_count': request_count, 'results_found': results_found,
        'new_companies': new_companies,
    }
