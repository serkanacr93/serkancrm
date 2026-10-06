"""
Neon PostgreSQL tam veritabani yedekleme scripti.

.env icindeki DATABASE_URL'e baglanir, her tablonun tum verisini
tek bir JSON dosyasina yazar ve 30 gunden eski yedekleri siler.

Kullanim: python scripts\\backup_neon.py
         python scripts\\backup_neon.py --force   (20 saat kuralini atlar)
"""
import base64
import json
import os
import sys
from datetime import date, datetime
from datetime import time as dtime
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

BACKUP_DIR = Path(r"C:\CRM_Yedekler")
RETENTION_DAYS = 30
MIN_HOURS_BETWEEN_BACKUPS = 20


def latest_backup_age_hours():
    """En son yedek dosyasinin kac saat once olusturuldugunu dondurur.
    Hic yedek yoksa None doner."""
    existing = sorted(BACKUP_DIR.glob("neon_backup_*.json"))
    if not existing:
        return None
    latest = existing[-1]
    age_seconds = datetime.now().timestamp() - latest.stat().st_mtime
    return age_seconds / 3600

def get_all_tables(cur):
    """2026-10-06 duzeltmesi: TABLES onceden SABIT bir listeydi - yeni
    tablo eklendiginde (ör. manual_irsaliye, potential_customer,
    historical_closure_log, payment_reminder...) scripte elle
    eklenmedigi icin SESSIZCE YEDEKLENMIYORDU. 20/39 tablo bu sekilde
    aylarca yedek disinda kalmisti (bkz. DENETIM_RAPORU.md). Artik
    information_schema'dan OTOMATIK okunur - yeni bir tablo eklenince
    bir sonraki yedekte otomatik dahil olur, scripte dokunmak gerekmez.
    alembic_version DAHIL (migration surum gecmisi de yedeklenir)."""
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """)
    return [r["table_name"] for r in cur.fetchall()]


def json_default(obj):
    if isinstance(obj, (datetime, date, dtime)):
        return obj.isoformat()
    if isinstance(obj, (bytes, memoryview)):
        # bytea sutunlar (ör. company_settings.logo_data) - base64'e
        # cevrilir, geri yuklerken base64.b64decode ile ters cevrilebilir.
        return {"__bytes_b64__": base64.b64encode(bytes(obj)).decode("ascii")}
    raise TypeError(f"Tip JSON'a cevrilemedi: {type(obj)}")


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("HATA: DATABASE_URL bulunamadi (.env dosyasini kontrol edin).")
        sys.exit(1)

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    force = "--force" in sys.argv
    age_hours = latest_backup_age_hours()
    if not force and age_hours is not None and age_hours < MIN_HOURS_BETWEEN_BACKUPS:
        print(f"Zaten guncel: en son yedek {age_hours:.1f} saat once alinmis "
              f"({MIN_HOURS_BETWEEN_BACKUPS} saatten az). Yeni yedek alinmadi.")
        return

    conn = psycopg2.connect(database_url)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    tables = get_all_tables(cur)

    data = {}
    counts = {}
    for table in tables:
        cur.execute(f'SELECT * FROM "{table}"')
        rows = [dict(r) for r in cur.fetchall()]
        data[table] = rows
        counts[table] = len(rows)

    # 2026-10-06: yedek sonrasi, HER tablonun satir sayisini canliyla
    # yeniden karsilastirir (ayni baglanti, yedekten SONRA tekrar COUNT) -
    # yedekleme sirasinda ARAYA bir INSERT/DELETE girdiyse (es zamanli
    # kullanim) fark acikca raporlanir, sessizce gecilmez.
    mismatches = []
    for table in tables:
        cur.execute(f'SELECT COUNT(*) AS c FROM "{table}"')
        live_count = cur.fetchone()["c"]
        if live_count != counts[table]:
            mismatches.append((table, counts[table], live_count))

    cur.close()
    conn.close()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"neon_backup_{timestamp}.json"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(data, f, default=json_default, ensure_ascii=False)

    print(f"Yedek olusturuldu: {backup_path}")
    print(f"Yedeklenen tablo sayisi: {len(tables)}")
    for t, c in counts.items():
        print(f"  {t}: {c} kayit")

    print("\n--- Yedek vs canli satir sayisi karsilastirmasi ---")
    if mismatches:
        print("UYARI: asagidaki tablolarda fark bulundu (yedekleme sirasinda veri degismis olabilir):")
        for t, backed_up, live in mismatches:
            print(f"  {t}: yedekte {backed_up}, su an canlida {live}")
    else:
        print(f"Tum {len(tables)} tablo icin yedek sayisi = canli sayi (fark yok).")

    now = datetime.now().timestamp()
    removed = []
    for old_file in BACKUP_DIR.glob("neon_backup_*.json"):
        age_days = (now - old_file.stat().st_mtime) / 86400
        if age_days > RETENTION_DAYS:
            old_file.unlink()
            removed.append(old_file.name)
    if removed:
        print(f"Silinen eski yedekler ({RETENTION_DAYS} gunden eski): {removed}")


if __name__ == "__main__":
    main()
