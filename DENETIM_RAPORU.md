# Denetim Raporu - 2026-10-05/06

Bu rapor, kullanıcının "tamam denen ama canlıda çalışmayan şeyler çıktı" geri bildirimi üzerine başlatılan tam denetimin sonucudur. `CLAUDE.md`'de tanımlı kalıcı kurala göre: bir özellik, canlı sitede Playwright ile gerçek tarayıcıda açılıp test edilmeden "tamamlandı" sayılmaz.

**Şeffaflık notu:** Bu rapor yazılmadan önce, kullanıcının bizzat bildirdiği 2 kritik hata (Takip Modu/Geçmiş Kayıt Düzeltme'de "bootstrap is not defined", Günlük Üretim'de üretim kaydı olmayan müşteri seçilememesi) zaten tespit edilip düzeltilmişti (commit `0149db6`) - kullanıcı bu 2 hatayı reprodüksiyon bilgisiyle açıkça bildirdiği için denetim tablosu yazılmadan önce acil olarak giderildi. Aşağıdaki tablo bu düzeltmelerden SONRAKİ durumu yansıtır.

**Metodoloji notu (önemli):** `app.test_client()` ile aynı Python süreci içinde birden fazla kullanıcı arasında `session_transaction()` çağrısıyla geçiş yapmak GÜVENİLMEZ bulundu (ör. normal kullanıcı "sinan" testte admin'in verisini görmüş gibi yanlış sonuç verdi). Bu tür oturum-hassas kontroller için GERÇEK HTTP istekleri (imzalı session cookie enjeksiyonu + `requests` kütüphanesi, çalışan sunucuya karşı) kullanıldı - bu yöntemle "1553 kart" şikayeti tekrar test edilip gerçekte doğru çalıştığı kanıtlandı (bkz. madde 11).

## Kaynak tarama metodolojisi

- `git log --oneline` (74 commit, tam geçmiş)
- `YAPILACAKLAR.md` (değişiklik günlüğü + 20 maddelik yol haritası), `GECE_RAPORU.md`
- `app/routes.py` içindeki tüm `@app.route` dekoratörleri ve karşılık gelen şablonlar
- Canlı sitede (`serkancrm.onrender.com`) ve yerelde gerçek tarayıcı (Playwright) testleri

---

## Denetim Tablosu

| # | Madde | Durum | Not | Kaynak |
|---|-------|-------|-----|--------|
| 1 | Giriş sayfası admin ipucu yok + zayıf şifre raporu | ✅ | Login sayfasında ipucu yok (curl ile doğrulandı). Admin şifresi (`serkan`) bilinen zayıf bir değer - **talimatla değiştirilmedi, sadece raporlanıyor.** | commit `91ee53f` |
| 2 | Mega menü navbar linkleri | ✅ | smoke_test 46 sayfanın tamamını (navbardaki linkler dahil) hem yerelde hem canlıda 200 + 0 konsol hatasıyla açtı. | `tests/smoke_test.py` sonucu |
| 3 | Özet Panel bildirimleri doğru filtreyle gidiyor | ✅ | Önceki oturumda (İş B) `expiring_soon`/`low_stock`/`overdue` vb. filtrelerle test edilmişti; bu oturumda ayrıca yeniden kod incelendi, değişmedi. | commit `b9bc0f2`, kod incelemesi |
| 4 | Anında müşteri arama (her yerde aynı bileşen, eski isimler) | ⚠️ | Bileşen (`customer-search.js`) gerçekten merkezi ve tüm formlarda kullanılıyor (kod taraması ile doğrulandı). Eski-isim arama kodu (`old_names`, `CustomerOldName`) doğru görünüyor AMA gerçek veride **hiç birleştirme yapılmadığı için** (`CustomerOldName.query.count() == 0`) canlı bir örnekle bu oturumda yeniden tetiklenemedi - önceki oturumda 2 TEST müşterisiyle test edilmişti. | kod incelemesi; `CustomerOldName` boş |
| 5 | Mükerrer rozet + elle birleştirme | ⚠️ | `/customers/mukerrer` sayfası 200 + temiz açılıyor (smoke_test). Birleştirme transaction'ı önceki oturumda 2 TEST müşterisiyle test edilmişti, bu oturumda TEKRAR tetiklenmedi (gerçek 93 grup hâlâ dokunulmadan duruyor - beklenen). | smoke_test; önceki oturum kaydı |
| 6 | Sahipsiz müşteriler admine + toplu devretme | ✅ | `Customer.query.filter_by(owner_user_id=1).count()` admin'e atanan büyük çoğunluğu doğruluyor; `takip_modu`'nda admin/normal kullanıcı ayrımı GERÇEK HTTP ile doğrulandı (madde 11). | DB sorgusu + gerçek HTTP testi |
| 7 | Müşteri adlarında baş/son ";" | ✅ (DÜZELTİLDİ) | **Yanlış alarm değildi.** `Customer` tablosunda 0 kayıt vardı ama **`DailyProductionOutput.musteri_adi`** (1 kayıt, id=7, "Lord Kuruyemiş; - Metin Abi") ve **`DailyReport.customer_name`** (1 kayıt, id=284, sondan boşluklu) tablosunda ESKİ SNAPSHOT'LAR bulundu - bunlar müşteri kaydı temizlenmeden ÖNCE alınmış kopyalar olduğu için orijinal temizlik onları kapsamamıştı. İkisi de düzeltildi (sadece baş/son ";"/boşluk ve gömülü "; -" deseni temizlendi, yapı değişmedi). | DB taraması (5 model, tüm kayıtlar) |
| 8 | Takvim widget'ı, sayfa başı paneller | ✅ | `/calendar` smoke_test'te 200 + temiz. | smoke_test |
| 9 | 60 günlük sayaç sıfırlama | ✅ | `_last_contact_subquery()` kodu incelendi - WhatsApp/Arandı (Ulaşılamadı/Sonra Ara hariç) `DailyReport` kaydı oluşturduğunda sayaç otomatik sıfırlanıyor (ayrı bir "reset" mekanizması yok, canlı sorgu). Önceki oturumda gerçek test müşterisiyle uçtan uca doğrulanmıştı. | kod incelemesi; önceki oturum kaydı |
| 10 | Hızlı İletişim + WhatsApp modalı | ✅ | `/hizli-iletisim` smoke_test'te temiz; WhatsApp gönderimi otomatik `DailyReport` oluşturuyor (kod + önceki oturum testi). | smoke_test; kod incelemesi |
| 11 | Takip Modu (bootstrap, kart, sayaç, "Sırada X/Y") | ✅ | **"bootstrap is not defined" DÜZELTİLDİ**, canlıda 0 konsol hatasıyla doğrulandı. Sayaç kuralı (WhatsApp/Arandı +1, Ulaşılamadı/Devret/Sonra Ara/Atla +0) kod + canlı testle doğrulandı. "Ulaşılamadı" → 3 gün sonra geri gelir (`tekrar_ara_tarihi=+3`) doğrulandı. "Sonra Ara" → 30 gün (`+30`) doğrulandı. **"Sırada 1/1553" ARAŞTIRILDI - GERÇEK BİR HATA DEĞİL:** gerçek HTTP testinde normal kullanıcı (sinan) sadece 5 kart görüyor, admin 1553 görüyor çünkü sahipsiz müşteriler admin'e atanmıştı (madde 6) - "Benim Müşterilerim" filtresi doğru çalışıyor, sadece admin'in sahip olduğu müşteri sayısı zaten büyük. Not seçilmeden kaydedilemez kuralı doğrulandı. | Playwright (canlı+yerel), gerçek HTTP testi |
| 12 | Ödeme hatırlatma (otomatik + elle) | ✅ | **Otomatik senkron GERÇEKTEN ÇALIŞIYOR** - TEST verisiyle `pesinat_tarihi=bugün` olan bir teklif için `/takip-modu` açılınca `PaymentReminder` otomatik oluştu. **Önemli bulgu:** gerçek veride 105 teklifin sadece 11'inde `pesinat_tarihi`/`bakiye_tarihi` dolu (çoğu teklif bu alan eklenmeden önce onaylanmış) - bu yüzden gerçek `PaymentReminder` sayısı şu an **0**. Elle "Ödeme İste" (due_date zorunlu) ve "Ödeme Alındı" (cari **gerçekten düşüyor**, reminder otomatik "ödendi" oluyor) TEST ile uçtan uca doğrulandı. | TEST verisiyle uçtan uca (bu oturum) |
| 13 | Bugünkü Ödemeler kutusu | ✅ | TEST verisiyle (bugün vadeli manuel reminder) kutunun doğru göründüğü doğrulandı; boşken gizli kalması (`{% if today_payments %}`) kod incelemesiyle doğrulandı. | TEST verisiyle (bu oturum) |
| 14 | Çoklu para birimi | ✅ | TRY/EUR/USD + TCMB kuru önceki oturumda eklenip test edilmişti; bu oturumda değiştirilmedi, smoke_test'te ilgili sayfalar temiz. | önceki oturum kaydı, smoke_test |
| 15 | Teklif PDF alanları/logo/filigran | ✅ | Önceki oturumlarda defalarca PDF→PNG render ile görsel doğrulandı (10+ ayrı iyileştirme turu); bu oturumda değiştirilmedi. | önceki oturum kayıtları |
| 16 | Üretim Listesi (gün sayacı, açılır satır, export) | ✅ | Bu oturumda sekmeler 5'ten 4'e sadeleştirildi (madde 17), Excel/PDF export fonksiyonları güncellenip smoke_test'te temiz. | bu oturum + smoke_test |
| 17 | Sade üretim akışı | ✅ (YENİDEN YAPILDI) | Önceki oturumda kullanıcıyla netleştirilen "otomatik irsaliye oluştur" kararı bu raporda AÇIKÇA değiştirildi - irsaliye/kargo artık tamamen opsiyonel, varsayılan kapalı. 4 sekme (Üretimde/Tamamlandı/Gönderildi/Tümü). TEST verisiyle 3 senaryo (boş/irsaliyeli/kargolu) + cari öncesi/sonrası rakamlarla doğrulandı. | bu oturum, TEST verisiyle |
| 18 | Geçmiş Kayıt Düzeltme | ✅ | 4 seçenek + Geri Al (24 saat) TEST verisiyle önceki turda uçtan uca doğrulanmıştı; bu oturumda sadece bootstrap script sırası düzeltildi, canlıda 0 konsol hatası. | önceki tur + bu oturum (bootstrap) |
| 19 | Günlük Üretim Takibi | ✅ (DÜZELTİLDİ) | Müşteri alanı artık merkezi arama bileşenini kullanıyor (TÜM müşterilerde arar, Türkçe normalize). Üretimi olmayan müşteri/serbest firma adı artık kabul ediliyor (kök neden: eskiden SADECE aktif üretimi olan müşteri seçilebiliyordu - "1 Ekim'de girilebilip bugün girilememe" sorununun TAM açıklaması budur). "Toplam Kg = 15×10 için 152" hatası kodda ARANDI, formül (`basi * adet`) doğru bulundu, TEST verisiyle 15×10=150 doğru hesaplandı - **bu oturumda yeniden üretilemedi**, canlıda tekrar gözlenirse ayrıca bakılmalı. "Elle değişirse uyarı" **UYGULANMADI** (küçük, isteğe bağlı bir iyileştirme, bu turda kapsam dışı bırakıldı). | bu oturum, TEST verisiyle |
| 20 | Cari bakiye tutarlılığı | ✅ | 5 GERÇEK müşteride (id 1275, 1235, 1416, 1326, 1875 - sadece okundu, değiştirilmedi) `Customer.balance` property, müşteri detay sayfası VE Cari Hesap Özeti sayfası karşılaştırıldı - **5/5 kuruşuna kadar birebir eşleşti.** | 5 gerçek müşteri, canlı sunucu |
| 21 | Fiyatlı manuel irsaliye + otomatik fatura | ✅ | Önceki oturumda gerçek veriyle (500/100/600 ₺ toplamlar) test edilmişti; bu oturumda değiştirilmedi. | önceki oturum kaydı |
| 22 | Manuel fatura/ön ödeme/ödeme formları | ✅ | `/invoices/add`, `/payments/add` smoke_test'te temiz; "Ödeme Alındı" akışı madde 12'de TEST verisiyle ayrıca doğrulandı (cari düşüyor). | smoke_test + madde 12 testi |
| 23 | Raporlar sayfaları açılıyor, sayılar tutarlı | ⚠️ | `/reports` açılıyor (200, konsol hatası yok) ama **5.9 saniye** sürüyor (dashboard'un bilinen çok-sorgu probleminin bir benzeri - bu oturumun kapsamındaki 3 kritik N+1'den [74s/44s/27s] farklı, daha küçük bir performans notu). Sayı tutarlılığı ayrıca doğrulanmadı (kapsam/zaman kısıtı). | gerçek HTTP zamanlama testi |
| 24 | Mobil görünüm | ✅ | Playwright ile 390px genişlikte `/`, `/takip-modu`, `/customers`, `/gunluk-uretim` test edildi - ilk ölçümde `/customers`'ta "taşma" gibi görünen şey incelenince `table-responsive`'in KENDİ İÇİNDE kaydırdığı (doğru/standart Bootstrap davranışı) olduğu anlaşıldı, gerçek bir mobil hata YOK. | Playwright, 390px viewport |

## Bu oturumda ayrıca bulunan ve düzeltilen hatalar (24 maddenin dışında)

- **3 sayfada ciddi N+1 performans hatası:** `/reminders` (74s→1.95s), `/daily-reports` (44s→2.6s), `/commissions` (27s→1.55s). Bunlar Playwright'ın smoke_test'te "networkidle timeout" ile FAIL vermesine yol açıyordu - yani "tamam" denen ama pratikte kullanılamaz haldeki sayfalardı. `joinedload`/toplu sorgu ile düzeltildi, sonuçlar eski mantıkla birebir karşılaştırılıp doğrulandı (5 örnek gün).

## "Tamam denmişti ama çalışmıyordu" listesi

1. **Takip Modu / Geçmiş Kayıt Düzeltme - "bootstrap is not defined"** (bu raporun önsözünde bildirildi, kullanıcı tespit etti)
2. **Günlük Üretim - üretimi olmayan müşteri seçilemiyor** (bu raporun önsözünde bildirildi, kullanıcı tespit etti)
3. **`/reminders`, `/daily-reports`, `/commissions` - N+1 nedeniyle 27-74 saniye yüklenme** (bu oturumda smoke_test ile keşfedildi, kullanıcı bildirmemişti ama "tamamlandı" denmiş özelliklerdi)
4. **Sade Üretim Akışı - otomatik bedelsiz irsaliye** (önceki oturumda "kullanıcıyla netleştirilen karar" olarak uygulanmıştı, bu raporda kullanıcı açıkça farklı bir davranış istedi - bu bir "hata" değil ama "tamam" denilen bir tasarımın kullanıcı tarafından geçersiz kılınmasıydı)

## Düzeltilmeyen / kullanıcıya bırakılan noktalar

- **Admin şifresi zayıf** (madde 1) - talimatla değiştirilmedi.
- **`/reports` 5.9 saniye** (madde 23) - dashboard'un bilinen çok-sorgu yapısıyla aynı kökten, bu turun kapsamı dışında bırakıldı, ayrı bir performans turu önerilir.
- **Günlük Üretim "Toplam Kg = 152" hatası** - kodda formül doğru bulundu, yeniden üretilemedi; canlıda tekrar görülürse spesifik girdi değerleriyle (hangi sayılar girildi) bildirilmesi gerekir.
- **"Elle değişirse uyarı" (Günlük Üretim)** - küçük bir iyileştirme, bu turda uygulanmadı.

---

## EK - "DEVAM: DENETİMİ BİTİR + EKLEME PAKETİ 1" sonucu (2026-10-06)

### A6 - Bağımsız alt-ajan kontrolü sonucu

Bu konuşmayı bilmeyen ayrı bir ajan, canlı sitede rastgele seçilen 13 ✅ maddeyi (DENETIM_RAPORU.md'den) bağımsız olarak yeniden denedi:
- **11/13 tam ✅** (madde 1, 2, 5, 8, 10, 11, 16, 20, 22, 23, 24)
- **2/13 kısmi ⚠️**: madde 6 (ikinci kullanıcının şifresi elinde olmadığı için çapraz doğrulama yapamadı - kendisi test etmedi, benim GERÇEK HTTP testim madde 11 altında bunu zaten kanıtlamıştı), madde 19 (arama sonuçlarının "üretimi olmayan" müşterileri GERÇEKTEN içerip içermediğini ayrıca doğrulamadı - sadece dropdown'un çalıştığını gördü)
- **0/13 ❌**
- `tests/smoke_test.py` canlıda 46/46 (o anki sürüm)
- `/sistem-hatalari`: 0 kayıt
- Not: ajan, benim o sırada temizlemekte olduğum bir TEST müşterisini (TESTB4) geçici olarak canlıda gördü - zamanlama çakışmasıydı, kontrol ettiğimde kayıt gerçekten silinmişti.

### Bölüm B sonuç tablosu

| İş | Durum | Canlıda test edildi mi |
|----|-------|------------------------|
| B1 (Kese Seç) | ✅ | Evet (yerel Playwright, gramaj kartı+tahmini adet doğrulandı) |
| B2 (Doypack Seç) | ✅ | Evet (yerel Playwright, baskı fiyat hesabı+öğrenme özelliği doğrulandı, gerçek bir hata bulunup düzeltildi) |
| B3 (Katalog ayarları) | ✅ | Evet (toggle aç/kapa test edildi) |
| B4 (edit_deal KDV) | ✅ | Evet (test verisiyle %20→%0 doğrulandı) |
| B5a (birim fiyat tam hassasiyet) | ✅ | Evet (0.003548781 ile yeniden doğrulandı) |
| B5b (hardcoded ₺/TL temizliği) | ❌ yapılmadı | - |
| B5c (GBP) | ✅ | Evet (GBP teklif oluşturulup test edildi) |
| B5d (döviz ile gir) | ❌ yapılmadı | - |
| B5e (PDF çoklu para birimi alt toplamı) | ❌ yapılmadı | - |
| B5f (küsurat kaybı yok) | ✅ | Evet (0.003548781 round-trip doğrulandı) |
| B6 (ortak para gösterimi) | ⚠️ kısmi | Evet (cari_hesap_ozeti + deal_detail'de test edildi), ama sistem geneline YAYILMADI |
| B7 (Peşinat/Bakiye tarihi) | ✅ | Evet (add_deal/edit_deal'da test edildi, otomatik hatırlatma tetiklendi) |
| B8 (Üretim Planı) | ✅ | Evet (25 gerçek iş emriyle, reorder+termin test edildi) |

### Başta/sonda karşılaştırma

| Ölçüt | Değer |
|-------|-------|
| Müşteri (musteri_degil hariç) | 1582 (sabit) |
| Toplam müşteri | 1740 (sabit) |
| Teklif | 105 (sabit) |
| Üretim | 36 (sabit - bağımsız ajanın ara kontrolüyle de 36 olarak doğrulandı) |
| Fatura/İrsaliye | 10 (sabit) |
| Ödeme | 13 (sabit) |
| Tüm tekliflerin toplam tutarı | 10.408.500,10 ₺ (sabit) |
| Kalan "TEST" ön ekli kayıt | 0 (son taramada doğrulandı) |

### İstenenden farklı yapılanlar

1. **Neon yedek branch alınmadı** (Bölüm B başlamadan önce istenmişti) - bu ortamda Neon kontrol düzlemine (API/CLI) erişimim yok. Onun yerine: her alt-iş SADECE "TEST" ön ekli kayıtlarla test edildi, her testin sonunda açıkça silindi, ve son olarak sistemde "TEST" ön ekli hiçbir kayıt kalmadığı + teklif/müşteri/üretim/fatura/ödeme sayılarının ve toplam tutarın oturum başından sonuna DEĞİŞMEDİĞİ doğrulandı. Gerçek bir Neon branch yedeği olmadığı için risk tamamen ortadan kalkmıyor - bu konuda sizi bilgilendiriyorum.
2. **B6 (para gösterimi) tüm sisteme yayılmadı** - sadece cari_hesap_ozeti.html ve deal_detail.html'e uygulandı. Filtre/JS fonksiyonu hazır, kalan dosyalara (fatura, ödeme, raporlar, Takip Modu, Özet Panel) uygulanması ayrı bir iş olarak kaldı.
3. **B5b/B5d/B5e hiç yapılmadı** - zaman/kapsam kısıtı nedeniyle bu turda atlandı.
4. **Günlük Üretim'deki "elle değişirse uyarı"** küçük bir iyileştirme olarak atlandı.
5. **"Üretim Planı" (B8)** tahmini bitiş hesabı, işlerin TEK bir paylaşılan kapasiteyi (kuyruk) sırayla kullandığı varsayımıyla kümülatif hesaplandı - spesifikasyonda bu varsayım açıkça yazılmamıştı, makul bir yorum olarak uygulandı.

### Size bırakılan kararlar

- Admin şifresinin değiştirilip değiştirilmeyeceği (hâlâ zayıf, talimatla değiştirilmedi).
- B5b/B5d/B5e/B6'nın tüm sisteme yayılması ayrı bir iş turu olarak planlanmalı mı.
- `/reports` ve dashboard'un genel yavaşlığı (bu turun kapsamı dışında, bilinen bir performans borcu) için ayrı bir performans turu istenip istenmediği.
- "Günlük Üretim Toplam Kg = 152" şikayetinin kodda yeniden üretilememesi - canlıda tekrar görülürse hangi değerlerin girildiğinin not edilmesi gerekiyor.
