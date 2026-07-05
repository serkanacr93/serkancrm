# CRM Sistemi v3.0 - Proje Dokümantasyonu

## 📋 Proje Özeti

Müşteri İlişkileri Yönetimi (CRM) sistemi. Satış, üretim, sevkiyat, stok, prim ve görev yönetimini tek bir platformda toplar.

**Teknoloji:** Python 3.13 + Flask + SQLite + Bootstrap 5  
**Versiyon:** 3.0  
**Son Güncelleme:** 17 Haziran 2026

---

## 🏗️ Mimari Yapı

```
crm/
├── app/
│   ├── __init__.py          # Flask app oluşturma, db init
│   ├── models.py            # Tüm veritabanı modelleri
│   ├── routes.py            # Tüm API rotaları
│   ├── pdf_utils.py         # PDF oluşturma fonksiyonları
│   ├── static/
│   │   └── css/style.css    # Özel stiller
│   └── templates/
│       ├── base.html         # Ana şablon (navbar, footer)
│       ├── login.html        # Giriş sayfası
│       ├── index.html        # Dashboard
│       ├── customers.html    # Müşteri listesi
│       ├── add_customer.html # Müşteri ekleme
│       ├── edit_customer.html# Müşteri düzenleme
│       ├── customer_detail.html # Müşteri detayı + ekstre
│       ├── deals.html        # Teklif listesi
│       ├── add_deal.html     # Teklif ekleme (KDV hesaplı)
│       ├── edit_deal.html    # Teklif düzenleme
│       ├── deal_detail.html  # Teklif detayı
│       ├── production_list.html # Üretim listesi
│       ├── production_detail.html # Üretim detayı + sevkiyat
│       ├── edit_production.html
│       ├── add_shipment.html # Sevkiyat ekleme
│       ├── shipment_list.html # Sevkiyat listesi
│       ├── edit_shipment.html
│       ├── products.html     # Stok listesi
│       ├── add_product.html  # Ürün ekleme
│       ├── product_detail.html # Ürün detayı
│       ├── edit_product.html
│       ├── tasks.html        # Görev yönetimi
│       ├── add_task.html     # Görev ekleme
│       ├── calendar.html     # Takvim görünümü
│       ├── commissions.html  # Prim takibi
│       ├── user_commissions.html # Kullanıcı prim detayı
│       ├── users.html        # Kullanıcı yönetimi
│       ├── add_user.html     # Kullanıcı ekleme
│       ├── edit_user.html    # Kullanıcı düzenleme
│       ├── reminders.html    # Hatırlatmalar
│       └── reports.html      # Raporlar + grafikler
├── run.py                   # Flask development server
├── run_app.py               # PyWebView desktop app
├── run_exe.py               # PyInstaller EXE launcher
├── crm.spec                 # PyInstaller spec dosyası
├── requirements.txt         # Python bağımlılıkları
├── calistir.bat             # Bat launcher (geliştirme)
├── CRM_Baslat.bat           # Bat launcher (EXE)
└── instance/
    └── crm.db               # SQLite veritabanı (otomatik)
```

---

## 🔧 Modeller (models.py)

### User (Kullanıcı)
| Alan | Tip | Açıklama |
|------|-----|----------|
| id | Integer | PK |
| username | String(50) | Benzersiz kullanıcı adı |
| email | String(120) | Benzersiz e-posta |
| password_hash | String(256) | Şifre hash'i |
| full_name | String(100) | Tam ad |
| role | String(20) | admin / user |
| is_active | Boolean | Aktif mi |
| created_at | DateTime | Oluşturma tarihi |
| last_login | DateTime | Son giriş |

### Customer (Müşteri)
| Alan | Tip | Açıklama |
|------|-----|----------|
| id | Integer | PK |
| first_name | String(50) | Ad |
| last_name | String(50) | Soyad |
| email | String(120) | E-posta |
| phone | String(20) | Telefon |
| company_name | String(200) | Firma adı |
| tax_office | String(100) | Vergi dairesi |
| tax_id | String(20) | Vergi numarası |
| trade_registry | String(50) | Ticaret sicil no |
| company_phone | String(20) | Firma telefon |
| company_address | Text | Firma adresi |
| company_email | String(120) | Firma e-posta |
| company_website | String(200) | Web sitesi |
| contact_person | String(100) | Yetkili kişi |
| contact_title | String(50) | Yetkili unvan |
| contact_phone | String(20) | Yetkili telefon |
| contact_email | String(120) | Yetkili e-posta |
| address | Text | Kişisel adres |
| notes | Text | Notlar |
| status | String(20) | aktif/pasif/potansiyel |

**Property'ler:**
- `display_name` → Firma adı varsa "Firma - Ad Soyad", yoksa "Ad Soyad"
- `is_new_customer` → İlk satışını yapıp yapmadığı

### Deal (Teklif)
| Alan | Tip | Açıklama |
|------|-----|----------|
| id | Integer | PK |
| title | String(100) | Teklif adı |
| subtotal | Float | Ara toplam (KDV hariç) |
| vat_rate | Float | KDV oranı (%0, %1, %10, %20) |
| vat_amount | Float | KDV tutarı |
| value | Float | Toplam (KDV dahil) |
| stage | String(30) | Aşama durumu |
| probability | Integer | Olasılık (%) |
| deal_date | Date | Teklif tarihi |
| expected_close | Date | Beklenen kapanış |
| valid_until | Date | Geçerlilik (otomatik +7 gün) |
| notes | Text | Notlar |
| customer_id | FK | Müşteri referansı |
| user_id | FK | Satış yapan kullanıcı |

**Stage Değerleri:**
- `yeni` → Yeni teklif
- `iletisim` → İletişimde
- `teklif` → Teklif verildi
- `muzakere` → Müzakere
- `kazanilan` → Onaylandı (üretime geçer)
- `kaybedilen` → Kaybedildi
- `revize` → Revize edildi

**Property'ler:**
- `is_expiring_soon` → 2 gün veya daha az kaldıysa True
- `is_expired` → Süresi dolduysa True
- `days_until_expire` → Kaç gün kaldığı

**Metodlar:**
- `calculate_totals()` → Ürünlerden otomatik toplam hesapla

### DealItem (Teklif Kalemi)
| Alan | Tip | Açıklama |
|------|-----|----------|
| id | Integer | PK |
| description | String(200) | Ürün açıklaması |
| quantity | Float | Miktar |
| unit | String(20) | Birim (adet/kg/mt/lt/m2/set) |
| unit_price | Float | Birim fiyat |
| total_price | Float | Toplam fiyat |
| deal_id | FK | Teklif referansı |

### Production (Üretim)
| Alan | Tip | Açıklama |
|------|-----|----------|
| id | Integer | PK |
| deal_id | FK | Teklif referansı (unique) |
| status | String(30) | beklemede/uretimde/tamamlandi/iptal |
| start_date | Date | Başlangıç |
| end_date | Date | Bitiş |
| notes | Text | Notlar |

### Shipment (Sevkiyat)
| Alan | Tip | Açıklama |
|------|-----|----------|
| id | Integer | PK |
| production_id | FK | Üretim referansı |
| quantity | Float | Miktar |
| unit | String(20) | Birim |
| weight_kg | Float | Kilo |
| ship_date | Date | Sevkiyat tarihi |
| tracking_number | String(100) | Kargo takip no |
| carrier | String(100) | Kargo firması |
| status | String(30) | hazirlaniyor/yolda/teslim_edildi |
| notes | Text | Notlar |

### Product (Ürün/Stok)
| Alan | Tip | Açıklama |
|------|-----|----------|
| id | Integer | PK |
| name | String(200) | Ürün adı |
| sku | String(50) | Stok kodu |
| description | Text | Açıklama |
| unit | String(20) | Birim |
| stock_quantity | Float | Stok miktarı |
| min_stock | Float | Minimum stok |
| cost_price | Float | Maliyet fiyatı |
| sell_price | Float | Satış fiyatı |
| category | String(100) | Kategori |
| status | String(20) | aktif/pasif |

**Property'ler:**
- `is_low_stock` → Stok minimum seviyenin altındaysa True

### Task (Görev)
| Alan | Tip | Açıklama |
|------|-----|----------|
| id | Integer | PK |
| title | String(200) | Görev başlığı |
| description | Text | Açıklama |
| due_date | Date | Bitiş tarihi |
| due_time | Time | Bitiş saati |
| priority | String(20) | dusuk/orta/yuksek |
| status | String(20) | yapilacak/devam/tamamlandi |
| category | String(50) | Kategori |
| customer_id | FK | İlgili müşteri |
| deal_id | FK | İlgili teklif |
| user_id | FK | Sorumlu kullanıcı |
| completed_at | DateTime | Tamamlanma tarihi |

### Commission (Prim)
| Alan | Tip | Açıklama |
|------|-----|----------|
| id | Integer | PK |
| user_id | FK | Satış yapan kullanıcı |
| deal_id | FK | İlgili teklif |
| sale_amount | Float | Satış tutarı (KDV hariç) |
| rate | Float | Prim oranı (%1 veya %1.5) |
| amount | Float | Prim tutarı |
| customer_type | String(20) | yeni/eski |
| status | String(20) | odenmedi/odendi |
| paid_at | DateTime | Ödeme tarihi |

**Prim Kuralları:**
- Yeni müşteri (ilk satış): %1.5
- Eski müşteri: %1

### CustomerStatement (Müşteri Ekstresi)
| Alan | Tip | Açıklama |
|------|-----|----------|
| id | Integer | PK |
| customer_id | FK | Müşteri |
| deal_id | FK | Teklif |
| type | String(20) | satis/borc/alacak |
| amount | Float | Tutar |
| description | Text | Açıklama |

### Reminder (Hatırlatma)
| Alan | Tip | Açıklama |
|------|-----|----------|
| id | Integer | PK |
| customer_id | FK | Müşteri |
| deal_id | FK | Teklif |
| title | String(200) | Başlık |
| message | Text | Mesaj |
| remind_date | Date | Hatırlatma tarihi |
| is_read | Boolean | Okundu mu |

---

## 🛣️ Rotalar (routes.py)

### Kimlik Doğrulama
| Method | URL | Yetki | Açıklama |
|--------|-----|-------|----------|
| GET/POST | `/login` | Açık | Giriş sayfası |
| GET | `/logout` | Giriş | Çıkış |

### Kullanıcı Yönetimi (Admin)
| Method | URL | Yetki | Açıklama |
|--------|-----|-------|----------|
| GET | `/users` | Admin | Kullanıcı listesi |
| GET/POST | `/users/add` | Admin | Kullanıcı ekle |
| GET/POST | `/users/<id>/edit` | Admin | Kullanıcı düzenle |

### Ana Sayfa
| Method | URL | Yetki | Açıklama |
|--------|-----|-------|----------|
| GET | `/` | Giriş | Dashboard (grafikler, widgetlar) |

### Müşteriler
| Method | URL | Yetki | Açıklama |
|--------|-----|-------|----------|
| GET | `/customers` | Giriş | Müşteri listesi + arama |
| GET/POST | `/customers/add` | Giriş | Müşteri ekle |
| GET | `/customers/<id>` | Giriş | Müşteri detayı + ekstre |
| GET/POST | `/customers/<id>/edit` | Giriş | Müşteri düzenle |
| POST | `/customers/<id>/delete` | Giriş | Müşteri sil |
| GET | `/customers/<id>/statement/pdf` | Giriş | Ekstre PDF indir |
| GET | `/customers/export/excel` | Giriş | Excel dışa aktar |

### Teklifler
| Method | URL | Yetki | Açıklama |
|--------|-----|-------|----------|
| GET | `/deals` | Giriş | Teklif listesi + arama/filtre |
| GET/POST | `/deals/add` | Giriş | Teklif ekle (otomatik tarih/KDV) |
| GET | `/deals/<id>` | Giriş | Teklif detayı |
| GET/POST | `/deals/<id>/edit` | Giriş | Teklif düzenle |
| POST | `/deals/<id>/delete` | Giriş | Teklif sil |
| GET | `/deals/<id>/pdf` | Giriş | Teklif PDF indir |
| POST | `/deals/<id>/revise` | Giriş | Revize teklif oluştur |
| POST | `/deals/<id>/approve` | Giriş | Teklif onayla + üretime aktar + prim hesapla |
| GET | `/deals/export/excel` | Giriş | Excel dışa aktar |

### Üretim
| Method | URL | Yetki | Açıklama |
|--------|-----|-------|----------|
| GET | `/production` | Giriş | Üretim listesi |
| GET | `/production/<id>` | Giriş | Üretim detayı + sevkiyatlar |
| GET/POST | `/production/<id>/edit` | Giriş | Üretim düzenle |
| GET/POST | `/production/<id>/shipment/add` | Giriş | Sevkiyat ekle |

### Sevkiyat
| Method | URL | Yetki | Açıklama |
|--------|-----|-------|----------|
| GET | `/shipments` | Giriş | Sevkiyat listesi |
| GET/POST | `/shipments/<id>/edit` | Giriş | Sevkiyat düzenle |

### Stok Yönetimi
| Method | URL | Yetki | Açıklama |
|--------|-----|-------|----------|
| GET | `/products` | Giriş | Ürün listesi + arama |
| GET/POST | `/products/add` | Giriş | Ürün ekle |
| GET | `/products/<id>` | Giriş | Ürün detayı |
| GET/POST | `/products/<id>/edit` | Giriş | Ürün düzenle |
| POST | `/products/<id>/delete` | Giriş | Ürün sil |
| GET | `/products/export/excel` | Giriş | Excel dışa aktar |

### Görev Yönetimi
| Method | URL | Yetki | Açıklama |
|--------|-----|-------|----------|
| GET | `/tasks` | Giriş | Görev listesi + filtre |
| GET/POST | `/tasks/add` | Giriş | Görev ekle |
| POST | `/tasks/<id>/complete` | Giriş | Görev tamamla |
| POST | `/tasks/<id>/delete` | Giriş | Görev sil |

### Takvim
| Method | URL | Yetki | Açıklama |
|--------|-----|-------|----------|
| GET | `/calendar` | Giriş | Aylık takvim (görevler + teklifler) |

### Prim Takibi
| Method | URL | Yetki | Açıklama |
|--------|-----|-------|----------|
| GET | `/commissions` | Giriş | Prim listesi (admin tümü, user kendi) |
| POST | `/commissions/<id>/pay` | Admin | Prim ödendi işaretle |
| POST | `/commissions/pay-all` | Admin | Tüm primleri öde |
| GET | `/users/<id>/commissions` | Giriş | Kullanıcı prim detayı |

### Raporlar
| Method | URL | Yetki | Açıklama |
|--------|-----|-------|----------|
| GET | `/reports` | Giriş | Satış, üretim, müşteri raporları |

### API
| Method | URL | Yetki | Açıklama |
|--------|-----|-------|----------|
| GET | `/api/chart-data` | Giriş | Dashboard grafik verileri (JSON) |

---

## 📦 Bağımlılıklar (requirements.txt)

```
Flask==3.0.0
Flask-SQLAlchemy==3.1.1
Flask-WTF==1.2.1
Flask-Login==0.6.3
WTForms==3.1.1
email-validator==2.1.0
reportlab==4.0.8
openpyxl==3.1.2
```

**EXE Derleme için ek:**
```
pyinstaller (Python 3.13 system ortamına kur)
```

---

## 🚀 Çalıştırma

### Geliştirme Ortamı
```bash
cd crm
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python run.py
# Tarayıcıda: http://localhost:5000
```

### EXE Oluşturma
```bash
# Python 3.13 system ortamında (Jarvis v2 venv'de değil):
"C:\Users\s\AppData\Local\Programs\Python\Python313\Scripts\pyinstaller.exe" crm.spec --clean
# dist/CRM_Sistemi/CRM_Sistemi.exe (~85 MB)
# - Console modunda: terminal penceresi açılır
# - Windowed modda (console=False): sadece tarayıcı açılır
# - İlk çalıştırmada instance/crm.db otomatik oluşturulur
```

### Varsayılan Giriş
- **Kullanıcı:** admin
- **Şifre:** 1234

---

## 🔄 İş Akışı

```
1. Müşteri Kaydı
   └── Firma + Yetkili bilgileri girilir

2. Teklif Oluşturma
   └── Ürünler eklenir → KDV otomatik hesaplanır → 7 gün geçerli

3. Teklif PDF
   └── PDF indirilir → Müşteriye gönderilir

4. Teklif Onayı
   └── "Onayla" tıklanır → Üretime geçer → Prim hesaplanır

5. Üretim
   └── Durum takibi → Başlangıç/bitiş tarihleri

6. Sevkiyat
   └── Kargo bilgisi → Takip numarası → Teslim

7. Prim
   └── Yeni müşteri: %1.5 → Eski müşteri: %1

8. Ekstre
   └── Müşteri detayından PDF olarak indirilir
```

---

## 📊 Dashboard Özellikleri

- Toplam müşteri/teklif/üretim/sevkiyat sayısı
- Chart.js ile satış çubuk grafiği
- Chart.js ile teklif pasta grafiği
- Süresi dolan/dolmak üzere olan teklifler (kırmızı/sarı uyarı)
- Son teklifler ve müşteriler
- Bugünkü ve yaklaşan görevler
- Hızlı işlem butonları

---

## 🔐 Yetkilendirme

| Özellik | Admin | Kullanıcı |
|---------|-------|-----------|
| Tüm sayfalar | ✓ | ✓ |
| Kullanıcı yönetimi | ✓ | ✗ |
| Tüm primleri görme | ✓ | ✗ |
| Toplu prim ödeme | ✓ | ✗ |
| Kendi primini görme | ✓ | ✓ |
| Kendi prim detayı | ✓ | ✓ |

---

## 📝 Güncelleme Notları

### v3.0 (17 Haziran 2026)
- Kullanıcı giriş sistemi ve roller
- Prim sistemi (%1.5 yeni / %1 eski müşteri)
- Stok yönetimi modülü
- Görev yönetimi
- Takvim görünümü
- Dashboard grafikleri (Chart.js)
- Excel dışa aktarma
- Arama ve filtreleme
- PyInstaller ile Windows EXE desteği (pencere modunda, ~85 MB)
- Tarayıcı otomatik açma ile desktop uygulama deneyimi

### v2.0
- Teklif PDF oluşturma
- KDV hesaplama
- Üretim modülü
- Sevkiyat takibi
- Müşteri ekstresi
- Revize sistemi
- Hatırlatma sistemi
- Firma ve yetkili kişi alanları

### v1.0
- Temel CRM yapısı
- Müşteri yönetimi
- Fırsat yönetimi
- Dashboard

---

## 🐄 Bilinen Sorunlar / Yapılacaklar

- [ ] E-posta entegrasyonu (SMTP ayarları)
- [ ] Stok hareket geçmişi
- [ ] Toplu teklif oluşturma
- [ ] Çoklu dil desteği
- [ ] Dark mode
- [ ] Mobil uyumlu arayüz
- [ ] Veritabanı yedekleme
- [ ] API endpoint'leri (harici entegrasyon)
- [ ] Baskı önizleme (print preview)
- [ ] Dashboard özelleştirme

---

## 📁 Veritabanı Konumu

EXE çalışırken: `dist/CRM_Sistemi/instance/crm.db`  
Geliştirme ortamında: `crm/instance/crm.db`

**Not:** İlk çalıştırmada otomatik oluşturulur.
