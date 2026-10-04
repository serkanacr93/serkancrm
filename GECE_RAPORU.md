# Gece Raporu — 2026-10-04

Otonom oturum: kullanıcı onay beklemeden 8 maddelik paketin sırayla tamamlanması istendi. **8/8 iş ✅ tam tamamlandı.** Aşağıda her iş için durum, alınan kararlar, test sonuçları ve commit listesi var.

## Durum Özeti

| İş | Konu | Durum |
|---|---|---|
| 1 | Yeni mega menü navbar | ✅ Tam |
| 2 | Sağdan kayan Özet Panel | ✅ Tam |
| 3 | Sahipsiz müşteriler + toplu devretme | ✅ Tam |
| 4 | Üretim Listesi açılır satır | ✅ Tam |
| 5 | Fiyatlı manuel irsaliye + otomatik fatura | ✅ Tam |
| 6 | Anında Müşteri Arama (tarayıcı-içi) | ✅ Tam |
| 7 | Veri temizliği (";"/boşluk) | ✅ Tam |
| 8 | Mükerrer kayıt tespiti + elle birleştirme | ✅ Tam |

Hiçbir iş "yarım" olarak işaretlenmedi — hepsi tamamlandı. Bir yan hata (İş 4 testinde) anında fark edilip düzeltildi, ayrıca not edildi.

---

## İş 1 — Yeni Mega Menü Navbar ✅

`base.html` navbar'ı tamamen yeniden tasarlandı:
- **Üst bar:** kırmızı→turuncu gradyan (#7a0000→#b71c1c→#e65100), sarı kare logo, genel arama kutusu (Ctrl+K), bildirim zili (sayı rozetli), kullanıcı menüsü.
- **Alt bar:** koyu zemin + 3px sarı çizgi, **Müşteriler/Üretim/Finans/Raporlar** mega menü grupları (hover ile açılan kutular, her kutuda canlı özet bilgi — 60 saniyelik process-içi önbellekli context processor).
- Eski "Diğer" dropdown tamamen kaldırıldı.
- **Hiçbir sayfa kaybolmadı:** 23 eski endpoint + yeni "Takip Gerekiyor"/"Mükerrer Kayıtlar" linkleri tek tek yeni menüde yer buldu.
- Mobilde mega menü kutuları düz listeye dönüşüyor (CSS media query).

**Test:** 23 sayfa × admin/normal kullanıcı ile hatasız render doğrulandı (arka plan testi, exit code 0).

## İş 2 — Sağdan Kayan Özet Panel ✅

Önceki oturumda Dashboard'a eklenen yatay "Özet Panel" şeridi ve deals.html/production_list.html'deki çerçevesiz kutular kaldırıldı. Yerine:
- `base.html`'de tek bir `{% block side_panel %}` + sağdan kayan panel bileşeni (hover=masaüstü, tıklama=mobil).
- İçerik üretmeyen sayfalarda sekme hiç görünmüyor (`{% set %}`/`{% endset %}` ile tek seferlik yakalama).
- Dashboard/Müşteriler/Teklifler/Üretim her biri kendi içeriğini `.card` + renkli `card-header` ile dolduruyor.
- Üretim Raporu kartı Dashboard ile Üretim Listesi arasında **paylaşılan tek partial** (`_uretim_rapor_card.html`) + **tek backend fonksiyonu** (`_production_report_data()`).

**Test:** 5 kritik sayfa + 10 ek sayfa hatasız render, panel içeriği olmayan sayfalarda (örn. Cari Hesap Özeti) sekmenin doğru şekilde görünmediği doğrulandı.

## İş 3 — Sahipsiz Müşteriler + Toplu Devretme ✅

1. **Rapor:** 1740 müşteriden 1542'sinin `owner_user_id` alanı NULL idi.
2. **Uygulama:** Hepsi admin'e (id=1, serkan) atandı. Sonrası: 0 NULL.
3. Müşteri listesi toplu seçimine **"Seçilenleri şu kullanıcıya ata"** eklendi — admin-only, hem şablonda hem route seviyesinde (`@admin_required`) korunuyor. Mevcut "Tümünü Seç (Filtrelenmiş Tümü)" mekanizmasıyla aynı iki modu (açık ID listesi / filtrelenmiş tümü → tek `UPDATE...WHERE`) paylaşıyor.

**Test:** Normal kullanıcı erişimi reddedildi (302→index); admin açık-ID modu ve filtrelenmiş-tümü modu ayrı ayrı 2 geçici test müşterisiyle doğrulandı, test verisi temizlendi.

## İş 4 — Üretim Listesi Açılır Satır ✅

Satıra tıklayınca başka sayfaya gitmiyor — altında AJAX ile (`/production/<id>/row-detail`) yüklenen bölüm açılıyor/kapanıyor:
1. **Sipariş Bilgisi:** teklif no, kalemler+miktar, termin, geçen gün.
2. **Günlük Üretim:** bağlı kayıtlar + toplam kg + yerinde ekleme — **`/gunluk-uretim/add` ile AYNI endpoint** (kopya mantık yok).
3. **Hızlı İşlemler:** Hazır İşaretle (`mark_production_ready` ile aynı route), İş Emri Yazdır, Not Ekle (`edit_production` ile aynı route).
4. "Detay sayfasına git" linki.

**Çakışma testi:** Aynı üretime hem açılır satırdan hem /gunluk-uretim'den kayıt eklendi, ikisinin toplamı (60.00 kg) birebir eşleşti.

**⚠️ Test sırasında bulunan ve düzeltilen yan hata:** İlk test script'im `edit_production`'a elle boş `start_date` gönderdi, bu production #31'in start_date'ini gerçekten `None`'a çevirdi. Kök neden test script'imin hatalı simülasyonuydu — **gerçek şablon güvenli** (hidden input'u her zaman production'ın gerçek tarihiyle dolduruyor, boş göndermiyor). Hemen fark edilip veri `2026-07-22`'ye geri yüklendi, ardından şablonun GERÇEKTEN ürettiği form değerleriyle tekrar test edilip güvenli olduğu kanıtlandı.

## İş 5 — Fiyatlı Manuel İrsaliye + Otomatik Dahili Fatura ✅

- `ManualIrsaliyeItem.unit_price`, `ManualIrsaliye.vat_rate`/`invoice_id` eklendi (migration `c25da7082d6d`, Neon'a uygulandı).
- Form: Birim Fiyat/Toplam sütunları + KDV dropdown (%0/%1/%10/%20) + canlı Ara Toplam/KDV/Genel Toplam (step="any", ondalık sınırsız).
- En az bir kalemde fiyat girilirse kaydedilince **otomatik dahili fatura** oluşuyor, `invoice_id` ile irsaliyeye bağlanıyor — borç Cari Hesap'a (tek merkezi `calculate_customer_balance`/`total_invoiced` üzerinden) otomatik düşüyor.
- Fiyat girilmezse (tüm fiyatlar boş) **eski davranış korunuyor** — fatura oluşmuyor.
- PDF iki seçenekli: varsayılan fiyatsız, `?priced=1` ile fiyatlı.
- İkinci fatura riski yapısal olarak yok (fatura sadece TEK noktada — kayıt anında — oluşuyor, ayrı bir "fatura oluştur" butonu/tekrar tetikleme yolu yok).

**Test:** Fiyatlı irsaliye (10kg×50₺=500 + %20 KDV=100 → 600₺) ile otomatik fatura doğrulandı, müşterinin `total_invoiced`'ına yansıdı (600.0). Farklı müşteriyle fiyatsız senaryo test edilip fatura OLUŞMADIĞI (regresyon yok) doğrulandı. PDF fiyatlı/fiyatsız ikisi de 200 OK. Test verileri temizlendi.

## İş 6 — Anında Müşteri Arama (Tarayıcı-İçi) ✅ — En Büyük/Riskli İş

Her tuş basışında sunucuya istek atan eski mekanizma tamamen kaldırıldı:
- `/api/customers/summary` (ETag/304 önbellekli) + `/api/deals/summary` sayfa açılışında **BİR KEZ** çekiliyor, `localStorage`'da tutuluyor.
- Arama **TAMAMEN tarayıcıda**: tüm alanlarda arar, kelime sırası önemsiz, Türkçe karakter bağımsız (ASCII katlama), küçük yazım hatası toleranslı (Levenshtein≤1), telefon format farkı yok.
- Sıralama: tam eşleşme > kullanıcının kendi müşterileri > son açılanlar.
- Sonuçlarda vurgulu eşleşme + ok tuşlarıyla gezinme + Enter/Esc.
- Üst menüdeki genel arama müşterilerin altında teklifleri de gösteriyor.
- **Public API korundu** (`initCustomerSearch`/`initCustomerSearchRow`, `onSelect`/`onClear`/`onQuickAdd`/`allowQuickAdd`/`clickOutsideContainer`) — 9 formun kendi kodu değişmeden çalıştı.

**Gerçek tarayıcıda (Playwright) bulunan ve düzeltilen performans sorunu:** İlk yükleme **~7.7 saniye** sürüyordu (tüm Customer sütunlarını çekme + her yüklemede gereksiz versiyon-kontrol sorgusu + 93 ayrı regex taraması/müşteri). Üç ayrı optimizasyonla **~3 saniyeye** indirildi:
1. `.with_entities()` ile sadece gereken sütunlar çekiliyor.
2. İlk yüklemede (henüz önbellek yoksa) versiyon-kontrol sorgusu atlanıyor, ETag fetch edilen veriden hesaplanıyor.
3. 93 ayrı `regex.search()` çağrısı tek birleşik alternation regex'ine çevrildi (city-extraction süresi 1582 müşteride ~8ms'ye düştü).

**Test (gerçek Flask sunucusu + Playwright):** kelime sırası ("okudan yasin"), yazım hatası ("okudn"→"okudan"), telefon format farkı (boşluklu/ham), Türkçe karakter (sirket→ŞİRKET), klavye navigasyonu (ArrowDown+Enter), sunucuya HİÇ arama isteği gitmediği (network trace), navbar'da Müşteriler+Teklifler bölümlerinin ikisi — hepsi doğrulandı.

## İş 7 — Veri Temizliği ✅

- **Rapor (önce):** 1740 müşteriden 132'si etkilenecekti (first_name/last_name/company_name sonunda ";" veya fazla boşluk).
- **Uygulama:** 131 kayıt güncellendi. **1 kayıt** (`id=1825`, first_name "ÖMER ") **güvenle atlandı** — temizlenirse `unique_customer_name` kısıtını ihlal edip id=1862 ile çakışacaktı. Birleştirme/silme yapılmadı, sadece o tek alan değişiklik dışı bırakıldı.
- Başka hiçbir alan değiştirilmedi. Müşteri sayısı değişmedi (1740).

## İş 8 — Mükerrer Kayıt Tespiti + Elle Birleştirme ✅

**TOPLU OTOMATİK BİRLEŞTİRME HİÇ YAPILMADI** (yasaktı, uyuldu).

- Yeni `CustomerOldName` tablosu (migration `f3a8b1c9d201`) — eski ad/müşteri no + kim/ne zaman birleştirdi logu aynı kayıtta.
- `_duplicate_phone_groups()`: **93 grup / 187 kayıt** tespit edildi (bkz. "Mükerrer Kayıt Sayı Dökümü" aşağıda). >5 kayıtlı "şüpheli" (ortak hat) grup bulunamadı.
- `/customers/mukerrer` sayfası + modal: kullanıcı **KALACAK kaydı radio ile seçiyor**, geri kalanlar birleştiriliyor.
- `_merge_customers()`: **13 tablo** (Deal, ManualPlanningEntry, ManualTedarikEntry, ManualIrsaliye, CustomerStatement, Invoice, Reminder, Task, CustomerVisit, DailyReport, Payment, PotentialCustomer.converted_customer_id, DailyProductionOutput) **TEK transaction'da** taşınıyor — hata olursa tam rollback.
- Müşteri Listesi/Detayı/Hızlı İletişim'de sarı **"⚠ Aynı numarada N kayıt"** rozeti.
- İş 6'nın arama motoru artık eski isimle de bulup "eski adı: ..." etiketi gösteriyor.

**Test:** 2 TEST müşterisi oluşturulup birine GERÇEK Deal+Payment+DailyReport bağlandı, birleştirildi — bağlı kayıtların taşındığı, cari bakiyenin doğru kaldığı (`total_collected`=500, payment taşındıktan sonra), `CustomerOldName` kaydının oluştuğu, `/api/customers/summary`'de `old_names` alanının doğru döndüğü doğrulandı. Test verileri (müşteriler + taşınan kayıtlar + CustomerOldName) tamamen temizlendi. **Gerçek 93 grubun hiçbiri dokunulmadan kaldı** (test sonrası tekrar sayıldı: 93).

### Mükerrer Kayıt Sayı Dökümü (İş 8 netleştirme talebi)

Kullanıcının bildiği "57 grup / 114 kayıt" ile benim bulduğum "93 grup / 187 kayıt" arasındaki fark araştırıldı:
- Ağustos-sonrası yeni müşterilerden kaynaklanan fark **ihmal edilebilir** (sadece 2 grupta 1'er yeni kayıt).
- `status != 'musteri_degil'` filtresi uygulanınca **77 grup / 154 kayıt**'a düşüyor — daha yakın ama tam eşleşmiyor.
- Geçersiz numara filtresi (boş/10 haneden kısa/"0"-"-") ve >5-kayıtlı "şüpheli" grup filtresi **sayıyı değiştirmedi** (0 şüpheli grup bulundu).
- **Sonuç:** Fark büyük ölçüde normalizasyonun yakaladığı format varyantlarından (boşluk/0/+90 farkı) kaynaklanıyor — ham string karşılaştırması bu varyantları ayrı sayardı, normalize edilmiş karşılaştırma onları doğru şekilde birleştiriyor. Kesin "57" rakamının hangi yöntemle elde edildiği belirlenemedi (muhtemelen farklı/daha eski bir ölçüm).
- **Final, kullanılan sayı: 93 grup / 187 kayıt** (tüm aktif+pasif durumlar dahil, geçersiz numaralar hariç, >5 kayıtlı grup yok).

---

## Aldığım Kararlar

1. **İş 1'deki "Mükerrer Kayıtlar" linki için geçici stub route/template oluşturdum** (İş 8'den önce) — navbar'ın HİÇBİR sayfada kırılmaması için. İş 8'de tam özellikle dolduruldu.
2. **İş 6'nın navbar entegrasyonu için ayrıca `/api/deals/summary` endpoint'i ekledim** — kullanıcı sadece "teklifler de çıksın" dedi, ayrı bir önbellekleme stratejisi belirtmedi; customers/summary ile AYNI ETag deseni kullandım (tutarlılık).
3. **İş 6 performans sorununu bulduğumda (gerçek tarayıcı testinde) durup düzelttim**, "iyi yeter" demeyip 7.7s→3s'e indirdim — kullanıcı deneyimini gerçekten etkileyen bir sorundu, "test geçti" ile yetinmek yanlış olurdu.
4. **İş 4'teki yan hatayı (production #31 start_date kaybı) fark eder etmez durdum, düzelttim, raporda şeffaf şekilde belirttim** — "gerçek şablon güvenli, benim testim hatalıydı" ayrımını net yaptım.
5. **İş 7'deki unique constraint çakışmasında kaydı BİRLEŞTİRMEK/SİLMEK yerine SADECE o alanı değişiklik dışı bıraktım** — "en güvenli seçenek" ilkesine uygun, kullanıcının "başka hiçbir alanı değiştirme" talimatına da sadık kalındı.
6. **İş 8'de "57 vs 93" farkını analiz ettim ama saatlerce araştırmadım** (talimata uygun) — bulguları raporladım, karar kullanıcıya bırakıldı.
7. **İş 2'nin sağ panel "Üretim Raporu" kartını Dashboard ile Üretim Listesi arasında paylaşılan TEK partial+fonksiyon yaptım** — kullanıcının "modüller arası çakışma olmayacak" genel kuralına uygun.

## Yarım Kalanlar

**Yok.** 8 işin hepsi tam tamamlandı.

## Commit Listesi

1. `Is 1: Yeni iki katli navbar (koyu premium + mega menu)`
2. `Is 2: Sagdan kayan Ozet Panel (eski yatay seritler kaldirildi)`
3. `Is 3: Sahipsiz musteriler admin'e atandi + toplu devretme ozelligi`
4. `Is 4: Uretim Listesi'nde satira tiklayinca acilan detay bolumu`
5. `Is 5: Fiyatli manuel irsaliye + otomatik dahili fatura`
6. `Is 6: Aninda Musteri Arama - tamamen tarayici-ici bulanik arama`
7. `Is 8: Mukerrer kayit tespiti + elle birlestirme (OTOMATIK BIRLESTIRME YOK)` (İş 7'nin veri temizliği notu da bu commit mesajına eklendi — kod değişikliği yok, ayrı commit gerektirmedi)

(YAPILACAKLAR.md + GECE_RAPORU.md için ayrı bir son commit.)

## Deploy Durumu

Push ve Render deploy kontrolü bu rapordan sonra yapılacak — sonucu bu dosyanın altına veya sohbette ekleyeceğim.
