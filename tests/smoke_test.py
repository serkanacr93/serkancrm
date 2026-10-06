"""Otomatik duman testi (CLAUDE.md ADIM 3).

Gercek bir tarayicida (Playwright/Chromium) test kullanicisiyla giris
yapar, menudeki + onemli detay sayfalarini acar, her sayfada:
  - HTTP durum kodu 200 mu
  - Tarayici konsolunda hata (console 'error' seviyesi VEYA
    yakalanmamis bir JS hatasi/pageerror) var mi
kontrol eder. HICBIR veri OLUSTURMAZ/DEGISTIRMEZ - sadece GET sayfalari
acar, modal/panel butonlarina tiklar (sadece data-bs-toggle="modal"
olanlara - bunlar bir modal PENCERE acar, form submit ETMEZ).

Kullanim:
    python tests/smoke_test.py --url http://127.0.0.1:5000 --username serkan --password ****
    python tests/smoke_test.py --url https://serkancrm.onrender.com --username serkan --password ****

Kullanici adi/sifre verilmezse SMOKE_TEST_USER/SMOKE_TEST_PASS ortam
degiskenlerinden okunur - hicbiri yoksa hata verir (sifre asla kod
icine sabit yazilmaz).
"""
import argparse
import os
import sys
import time

from playwright.sync_api import sync_playwright

# Parametresiz, salt-okunur GET sayfalari - menudeki + onemli diger sayfalar.
STATIC_PAGES = [
    "/", "/calendar", "/cari-hesap-ozeti", "/commissions", "/customers",
    "/customers/add", "/customers/dormant", "/customers/mukerrer",
    "/customers/never-transacted", "/customers/not-customer",
    "/customers/takip-gerekiyor", "/daily-reports", "/daily-reports/add",
    "/deals", "/deals/add", "/gecmis-kayit-duzeltme", "/gunluk-uretim",
    "/hizli-iletisim", "/invoices", "/invoices/add", "/payments",
    "/payments/add", "/potential-customers", "/potential-customers/add",
    "/production", "/products", "/products/add", "/reminders", "/reports",
    "/settings", "/shipments", "/sistem-hatalari", "/takip-modu", "/tasks",
    "/tasks/add", "/tedarik-takip", "/uretim-planlama", "/uretim-plani",
    "/settings/teklif-yardimci", "/users", "/users/add", "/visits", "/visits/add",
]


def get_sample_ids():
    """Gercek (ama SADECE OKUNAN) bir musteri/teklif/uretim/fatura id'si -
    detay sayfalarini test etmek icin. Hicbir kayit degistirilmez."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app import create_app, db
    from app.models import Customer, Deal, Production, Invoice, Shipment

    app = create_app()
    with app.app_context():
        ids = {}
        c = Customer.query.order_by(Customer.id.desc()).first()
        ids["customer"] = c.id if c else None
        d = Deal.query.order_by(Deal.id.desc()).first()
        ids["deal"] = d.id if d else None
        p = Production.query.order_by(Production.id.desc()).first()
        ids["production"] = p.id if p else None
        inv = Invoice.query.order_by(Invoice.id.desc()).first()
        ids["invoice"] = inv.id if inv else None
        s = Shipment.query.order_by(Shipment.id.desc()).first()
        ids["shipment"] = s.id if s else None
        return ids


def build_detail_pages(ids):
    pages = []
    if ids.get("customer"):
        pages.append(f"/customers/{ids['customer']}")
    if ids.get("deal"):
        pages.append(f"/deals/{ids['deal']}")
    if ids.get("production"):
        pages.append(f"/production/{ids['production']}")
    if ids.get("invoice"):
        pages.append(f"/invoices/{ids['invoice']}")
    if ids.get("shipment"):
        pages.append(f"/shipments/{ids['shipment']}")
    return pages


def login(page, base_url, username, password):
    page.goto(base_url + "/login")
    page.fill("input[name=username]", username)
    page.fill("input[name=password]", password)
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")
    if "/login" in page.url:
        raise RuntimeError("Giriş başarısız - kullanıcı adı/şifre kontrol edin.")


def check_page(page, base_url, path):
    console_errors = []
    page_errors = []

    def on_console(msg):
        if msg.type == "error":
            console_errors.append(msg.text)

    def on_pageerror(exc):
        page_errors.append(str(exc))

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)

    status = None
    try:
        resp = page.goto(base_url + path, wait_until="networkidle", timeout=20000)
        status = resp.status if resp else None
        page.wait_for_timeout(300)  # gecikmeli JS hatalarini da yakalamak icin

        # Sadece bootstrap modal tetikleyicilerine tikla (data submit etmez,
        # sadece bir pencere acar) - "her sayfadaki modal/panel butonlari
        # aciliyor" kontrolu icin.
        triggers = page.locator('[data-bs-toggle="modal"]')
        count = min(triggers.count(), 5)  # bir sayfada cok fazlaysa ilk 5'i yeterli
        for i in range(count):
            try:
                triggers.nth(i).click(timeout=2000, force=True)
                page.wait_for_timeout(200)
                # Acilan modali kapat (ESC) - bir sonraki tetikleyiciye engel olmasin
                page.keyboard.press("Escape")
                page.wait_for_timeout(150)
            except Exception:
                pass  # tiklanamayan (gizli/disabled) bir tetikleyici - kritik degil
    except Exception as e:
        page_errors.append(f"goto/interaction hatasi: {e}")
    finally:
        page.remove_listener("console", on_console)
        page.remove_listener("pageerror", on_pageerror)

    return {
        "path": path,
        "status": status,
        "console_errors": console_errors,
        "page_errors": page_errors,
    }


def main():
    parser = argparse.ArgumentParser(description="CRM smoke test (Playwright)")
    parser.add_argument("--url", default="http://127.0.0.1:5000", help="Test edilecek taban URL")
    parser.add_argument("--username", default=os.environ.get("SMOKE_TEST_USER"))
    parser.add_argument("--password", default=os.environ.get("SMOKE_TEST_PASS"))
    parser.add_argument("--headed", action="store_true", help="Tarayiciyi gorunur calistir (varsayilan: headless)")
    args = parser.parse_args()

    if not args.username or not args.password:
        print("HATA: --username/--password veya SMOKE_TEST_USER/SMOKE_TEST_PASS gerekli.")
        sys.exit(1)

    print(f"Hedef: {args.url}")
    ids = get_sample_ids()
    pages = STATIC_PAGES + build_detail_pages(ids)
    print(f"Toplam {len(pages)} sayfa test edilecek.")

    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        page = browser.new_page()
        login(page, args.url, args.username, args.password)

        for path in pages:
            r = check_page(page, args.url, path)
            results.append(r)
            ok = r["status"] == 200 and not r["console_errors"] and not r["page_errors"]
            mark = "OK " if ok else "FAIL"
            print(f"[{mark}] {path} (status={r['status']})")
            for e in r["console_errors"]:
                print(f"       console error: {e[:200]}")
            for e in r["page_errors"]:
                print(f"       page error: {e[:200]}")

        browser.close()

    # Ozet tablo
    print("\n" + "=" * 70)
    print("SONUC TABLOSU")
    print("=" * 70)
    fails = [r for r in results if r["status"] != 200 or r["console_errors"] or r["page_errors"]]
    print(f"Toplam: {len(results)} | Basarili: {len(results) - len(fails)} | Basarisiz: {len(fails)}")
    if fails:
        print("\nBasarisiz sayfalar:")
        for r in fails:
            print(f"  - {r['path']} (status={r['status']}, console={len(r['console_errors'])}, page_err={len(r['page_errors'])})")

    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
