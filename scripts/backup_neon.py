"""
Neon PostgreSQL tam veritabani yedekleme scripti.

.env icindeki DATABASE_URL'e baglanir, her tablonun tum verisini
tek bir JSON dosyasina yazar ve 30 gunden eski yedekleri siler.

Kullanim: python scripts\\backup_neon.py
"""
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

BACKUP_DIR = Path(r"D:\CRM_Yedekler")
RETENTION_DAYS = 30

TABLES = [
    "user", "customer", "product", "deal", "deal_item", "commission",
    "customer_statement", "production", "production_item", "shipment",
    "shipment_item", "invoice", "invoice_item", "reminder", "task",
    "customer_visit", "daily_report", "payment",
]


def json_default(obj):
    if isinstance(obj, (datetime, date, dtime)):
        return obj.isoformat()
    raise TypeError(f"Tip JSON'a cevrilemedi: {type(obj)}")


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("HATA: DATABASE_URL bulunamadi (.env dosyasini kontrol edin).")
        sys.exit(1)

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    conn = psycopg2.connect(database_url)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    data = {}
    counts = {}
    for table in TABLES:
        cur.execute(f'SELECT * FROM "{table}"')
        rows = [dict(r) for r in cur.fetchall()]
        data[table] = rows
        counts[table] = len(rows)
    cur.close()
    conn.close()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"neon_backup_{timestamp}.json"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(data, f, default=json_default, ensure_ascii=False)

    print(f"Yedek olusturuldu: {backup_path}")
    for t, c in counts.items():
        print(f"  {t}: {c} kayit")

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
