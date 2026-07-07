"""
Google Places otomatik arama zamanlayicisi.

Pazartesi-Cuma, 09:00-18:00 (Turkiye saati) arasi her saat basi bir
arama turu calistirir. Hafta sonu / mesai disinda hic tetiklenmez.
Sistem ayarlardan kapatilmissa (PlacesSearchConfig.enabled=False)
run_search() zaten hicbir API cagrisi yapmadan hemen doner.
"""
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

TR_TZ = ZoneInfo('Europe/Istanbul')

_scheduler = None


def _scheduled_job(app):
    with app.app_context():
        from app.places_search import run_search
        run_search(triggered_by='otomatik')


def start_scheduler(app):
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    scheduler = BackgroundScheduler(timezone=TR_TZ)
    scheduler.add_job(
        func=_scheduled_job,
        args=[app],
        trigger=CronTrigger(day_of_week='mon-fri', hour='9-18', minute=0, timezone=TR_TZ),
        id='places_search_hourly',
        replace_existing=True,
    )
    scheduler.start()
    _scheduler = scheduler
    return scheduler
