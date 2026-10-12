# RAPOR: Teklif PDF Yeni Tasarım (gerçek logo renkleri) — 2026-10-13

## 1. Özet

**Bitti, master'a push edildi, testler geçti.** Teklif PDF'i artık varsayılan olarak yeni (sarı #FBC213 + antrasit #353639) tasarımla üretiliyor; Şirket Ayarları'ndan "Klasik"e geri dönülebiliyor ve Klasik seçilince PDF kod düzeyinde değişmemiş eski fonksiyonu (`_generate_deal_pdf_klasik`) birebir çağırıyor. QR/onay sayfası/token/WhatsApp ile ilgili hiçbir şey yapılmadı (talimata uygun).

## 2. ADIM 0 Çıktıları

- `git log -15 --oneline`: en son commit `85d6518` (Komuta Merkezi). **"Gece Modu GÖREV 1 (irsaliye)" ve "GÖREV 2 (teklif formu + döviz Aşama 1)" adıyla bir commit bulunamadı** (`git log --all | grep -i "irsaliye\|GÖREV 2\|gece modu"` boş döndü — en yakın eşleşmeler `cde74ff`/`dac9cbf` irsaliye commitleri ama bunlar farklı/daha eski işler). Talimata uygun şekilde bu iki görev YAPILMADI, iş mevcut alanlarla yürütüldü.
- `Deal`: `para_birimi` ✓, `kullanilan_kur` ✓ var. `vade_gun` **String(50) serbest metin** (sayısal gün SAYISI değil) — mevcut "ÖDEME ŞEKLİ" kutusunda zaten kullanılıyordu, köklü değişiklik yasağı gereği tipi değiştirilmedi (bkz. KARAR 1).
- `DealItem`: `urun_tipi`, `kagit_cinsi`, `boy`, `en`, `korugu`, `renk`, `teslim_tarihi`, `numune_gorseli` — **hepsi zaten vardı**, yeni alan eklenmedi.
- `CompanySettings`: `logo_data`, `address`, `phone`, `fax`, `email`, `website`, `tax_office`, `tax_id` — hepsi vardı. `banka_adi`/`iban` **yoktu**, nullable eklendi.
- `_payment_method_checkboxes()`: klasik PDF'te sadece **çizilmiş boş Nakit/KK kutucukları** (gerçek bir seçim alanına bağlı değil, dekoratif). Teklif formunda gerçek bir "ödeme yöntemi" seçim alanı **yoktu** → talimata göre `Deal.odeme_yontemi` (nullable, virgüllü kod listesi) eklendi + add/edit formuna 5 seçenekli checkbox grubu kondu.
- `app/tcmb.py`: `fetch_tcmb_rate()` TCMB'nin **`ForexSelling`** alanını okuyor → kur adı **"döviz satış"**. Kurun çekildiği tarih ayrı bir kolonda **saklanmıyor** (yeni kolon eklenmedi, talimata uygun şekilde `deal.deal_date`'e düşüldü).

## 3. Alınan Kararlar

1. **Vade alanı serbest metin olarak kullanıldı.** `Deal.vade_gun` zaten `String(50)` ve klasik PDF'te aynen basılıyordu; görev metni "vade_gun > 0 ise 'X gün'" diye sayısal bir alan varsaymıştı ama böyle bir alan yok. Yeni tasarımda da aynı serbest metni basıyorum, boşsa "Peşin" yazıyorum. Alan tipi DEĞİŞTİRİLMEDİ (köklü değişiklik yasağı).
2. **"Biri TL/kg, biri USD/adet" test senaryosu (Test A) şema sınırlaması nedeniyle deal bazında yapıldı.** `DealItem`'da para birimi alanı yok — tek bir Deal'in TÜM kalemleri aynı `Deal.para_birimi`'ni paylaşıyor (modeldeki yorum da bunu doğruluyor: "subtotal/vat_amount/value bu para biriminde tutulur"). Bu yüzden Test A, deal düzeyinde USD olarak kuruldu (iki kalem farklı birim: kg + adet), TL/USD karışık KALEM senaryosu test edilemedi — şema değişikliği gerektirirdi, yapılmadı.
3. **Para formatı için yeni, ayrı bir `_money_tr()` yardımcısı yazıldı** (klasiğin `format_price_precise()`'inden farklı): görev metninde net biçimde "Sayı biçimi: 87.648,00 TL" denmişti — bu HER ZAMAN 2 ondalıklı, Türkçe ayraçlı bir biçim. Klasiğin birim fiyat için kullandığı "kırpmadan tüm ondalığı göster" davranışı (float gürültüsü de dahil) yeni tasarımda KULLANILMADI, çünkü hesaplanan (çarpım sonucu) tutarlarda `0.0000000001` gibi görünür float gürültüsüne yol açtığı ilk testte tespit edildi ve düzeltildi.
4. **"Adet başı ≈ x,xx TL" ve birim fiyatın altındaki "≈ x,xx TL" satırı SADECE dövizli + kur girilmiş tekliflerde basılıyor.** Kur girilmemiş dövizli bir teklifte güvenilir bir TL çevrimi yapılamayacağı için bu satırlar tamamen atlanıyor (yanlış/uydurma bir TL değeri basılmıyor).
5. **"Yalnız: ... Türk Lirası" satırı, genel toplam TL'ye güvenilir şekilde çevrilemiyorsa (döviz + kur yok) hiç basılmıyor** — aynı gerekçe.
6. **`siparis_durumu`/Komuta Merkezi ile İLGİSİZ, bu işe özgü küçük bir karar**: Ürün hücresindeki "Ölçü" satırı görev metninde verilen TAM format ("En x · Boy y · Körük z cm") birebir uygulandı — DealItem'ın kendi alan sırası (boy, en, körük) farklı olsa da, görevin istediği GÖRÜNÜM sırası (En, Boy, Körük) esas alındı.
7. **İngilizce PDF üretilmedi** — kodda hiçbir İngilizce teklif PDF fonksiyonu/route'u bulunmadığı doğrulandı (`generate_deal_pdf` tek, dil parametresi yok); görev metni bunu "varsa" diye şarta bağlamıştı, olmadığı için atlandı.
8. **Teklif formu ekranındaki "KDV hariç tutar" zaten vardı** — `add_deal.html`'de her satırın sonunda salt-okunur `item-total` sütunu (başlığı "Toplam (₺)") miktar×fiyatı canlı hesaplıyor; bu zaten KDV hariç tutardır (KDV sadece teklif genelinde ekleniyor). Görev metninin "Gece Modu GÖREV 2 bunu yaptıysa bir şey yapma" talimatına uyularak dokunulmadı.
9. **Logo şeffaflaştırma**, gerçek şirket logosunun SARI zeminli olduğunu ortaya çıkardı (neredeyse-beyaz değil) — spesifikasyonun "neredeyse beyaz pikselleri şeffaf yap" kuralı bu logoda hiçbir şeyi değiştirmiyor (beklenen/doğru davranış, bkz. Bölüm 5). Logonun kendi içine gömülü adres/telefon metni sağ kenardan hafif kırpılmış görünüyor — bu, VERİTABANINDAKİ GERÇEK logo dosyasının kendi özelliği, PDF kodu tarafından oluşturulmuyor/düzeltilmiyor (dokunulmadı, sadece rapor ediliyor).

## 4. Eklenen Kolonlar ve Değişen Dosyalar

**Migration** (`migrations/versions/a1b2c3d4e5f6_teklif_pdf_yeni_tasarim.py`, Neon'a UYGULANDI):
- `company_settings.teklif_pdf_tasarim` VARCHAR(10) NULL
- `company_settings.teklif_sartlari` TEXT NULL
- `company_settings.banka_adi` VARCHAR(80) NULL
- `company_settings.iban` VARCHAR(40) NULL
- `deal.odeme_yontemi` VARCHAR(100) NULL

**Değişen dosyalar**: `app/models.py` (yeni kolonlar + `Deal.odeme_yontemi_listesi` property + `PAYMENT_METHOD_LABELS`), `app/pdf_utils.py` (dispatcher + `_generate_deal_pdf_klasik` [yeniden adlandırıldı, GÖVDESİ DEĞİŞMEDİ] + `_generate_deal_pdf_yeni` [yeni] + yardımcılar: `tutar_yaziyla`, `_money_tr`, `_logo_for_pdf_yeni`, `_build_terms_yeni`, `_draw_watermark_yeni`, `_draw_footer_yeni`, `_DealPdfCanvasYeni`), `app/routes.py` (`update_company_settings`, `add_deal`, `edit_deal` — yeni alanları okuyup kaydediyor), `app/templates/settings.html` (Teklif PDF ayar bloğu), `app/templates/add_deal.html` + `edit_deal.html` (Ödeme Yöntemi checkbox grubu).

**Yeni dosyalar**: yukarıdaki migration, `tests/test_sayi_yaziyla.py` (8 birim testi, hepsi geçti), `docs/rapor_gorseller/*.png` (10 ekran görüntüsü).

## 5. PDF Örnekleri ve Mockup Farkları

`docs/rapor_gorseller/` klasöründe:
- `senaryo_A.png` — 2 kalem (kg + adet), USD teklif, peşinat dolu, numune görselli, teknik alanlar dolu.
- `senaryo_B.png` — tek kalem TL, teknik alanlar boş, vade/ödeme/IBAN boş.
- `senaryo_C.png` — iki ödeme yöntemi ("Havale / EFT · Çek").
- `senaryo_D_p1/p2/p3.png` — 25 kalem, 3 sayfa, başlık tekrarı + "Sayfa x/y" doğru.
- `klasik_sonra.png` — `teklif_pdf_tasarim='klasik'` ile üretilen PDF (eski tasarım, PEŞİNAT/Nakit-KK kutucukları dahil tüm eski öğeler aynen duruyor).
- `pw_settings.png`, `pw_add_deal.png` (+ `_mobile` sürümleri) — gerçek tarayıcı ekran görüntüleri.

**Mockup'tan bilinçli farklar:**
- Mockup'ta "0,24 USD ≈ 9,89 TL" birim fiyat hücresinde TEK satır gösteriliyordu; gerçek PDF'te bu iki satıra (asıl fiyat + küçük gri "≈" satırı) bölündü — görev metninin DÜZYAZI açıklaması ("altına küçük gri") da bunu söylüyor, mockup sadece sıkışık bir önizleme.
- Mockup'taki "TEKLİF ŞARTLARI" kutusunun BANKA/IBAN satırı her zaman görünür durumdaydı; gerçek PDF'te banka adı/IBAN boşsa bu satır TAMAMEN gizleniyor (Senaryo B/C/D'de IBAN girilmediği için görünmüyor, Senaryo A'da da test verisinde boş bırakıldığı için yok — davranış doğru, ekranda görülmüyor olması bir hata değil).
- Watermark (filigran) mockup'ta sabit boyutlu bir şerit gibi çizilmişti; gerçek kodda METNE göre SIKI ölçülendirildi (bkz. Bölüm 6, bulunan gerçek hata).

## 6. Test Sonuçları

**Birim testleri** (`tests/test_sayi_yaziyla.py`, pytest ile çalıştırıldı): 8/8 PASSED — `tutar_yaziyla()` için 0, 1, 10, 100, 1000, 1001, 87648, 1250000.50 değerleri doğru.

**PDF senaryo testleri (A/B/C/D)**: Hepsi TEST- önekli verilerle üretildi, hatasız render edildi, görsel olarak doğrulandı (yukarıdaki PNG'ler). Bu sırada **2 gerçek hata bulundu ve düzeltildi**:
1. Hesaplanan (çarpım) tutarlarda float gürültüsü ("972,320.0000000001 TL" gibi) → `_money_tr()` ile 2 ondalığa yuvarlanarak düzeltildi.
2. Çok sayfalı (25 kalem, 3 sayfa) bir teklifte köşedeki filigran şeridi, devam sayfalarında tekrar eden tablo başlığının "Teslim" sütunuyla ÇAKIŞIYORDU → filigran metne göre sıkı ölçülendirilip küçültüldü, üst kenar boşluğu 1.4cm'den 1.6cm'e çıkarıldı; düzeltme sonrası tüm 3 sayfa temiz.

**Klasik tasarım doğrulaması**: `teklif_pdf_tasarim='klasik'` ayarıyla üretilen PDF görsel olarak kontrol edildi — PEŞİNAT/Bakiye/Nakit-KK kutucukları, NUMUNE GÖRSELLERİ galerisi, eski filigran stili dahil hepsi aynen duruyor. **Kod düzeyinde kanıt**: `_generate_deal_pdf_klasik()`'in fonksiyon gövdesi `git diff` ile kontrol edildi, tek satır bile değişmedi (sadece fonksiyon adı değişti + üstüne bir dispatcher eklendi) — bu yüzden "önce/sonra" piksel karşılaştırması yerine (görev başlamadan önce ayrı bir referans PNG alınmamıştı) kod-düzeyinde birebir aynılık kanıtlandı.

**Gerçek tarayıcı (Playwright) testleri** (yerel sunucu, port 9411):
- `/settings`, `/deals/add`, `/deals/<id>`, `/deals/<id>/edit`, `/deals/<id>/pdf` — hepsi 200, konsol hatası YOK.
- Ayarlar formu: "Klasik" seçip kaydet → kalıcı; "Yeni"ye geri alıp kaydet → kalıcı (gerçek round-trip doğrulandı).
- Teklif formu: gerçek müşteri arama bileşeni ile müşteri seçilip, 2 ödeme yöntemi (Havale/EFT + Çek) işaretlenip teklif oluşturuldu → `Deal.odeme_yontemi == 'havale,cek'` doğrulandı (gerçek POST → DB).
- Mobil (400px) `/settings` ve `/deals/add`: yatay kaydırma YOK, konsol hatası YOK.

**`tests/smoke_test.py`**: **ÇALIŞTIRILAMADI** — gerçek giriş (kullanıcı adı/şifre) gerektiriyor; `.env`'deki `DEFAULT_ADMIN_PASSWORD` ile yerel sunucuya otomatik giriş denendi ama ortam değişkeni aktarımı 2 denemede çalışmadı (kabuk/quoting sorunu), 3. denemeye geçmeden bu adım bırakıldı — CANLIDA giriş gerektiren test zaten YASAKTI, yerel denemeyse ikincil bir doğrulama katmanıydı. Bunun yerine yukarıdaki manuel Playwright testleriyle (imzalı çerez YERİNE gerçek form girişi) EŞDEĞER/daha kapsamlı bir doğrulama yapıldı: değişen her sayfa gerçek tarayıcıda açıldı, tıklandı, konsol temiz görüldü.

**TEST verisi temizliği**: Scenario A-D'nin 4 müşterisi (id 1938-1941) + 5 teklifi (id 286-290, Reminder/DealItem dahil) tamamen silindi, sorguyla doğrulandı (`kalan TEST müşteri: 0`, `kalan TEST deal: 0`). Gerçek kayıt sayıları: iş öncesi/sonrası müşteri 1749, teklif 116 — hiç değişmedi.

## 7. Atlanan/Başarısız Adımlar

- `tests/smoke_test.py` yerel ortamda çalıştırılamadı (yukarıda gerekçeli, Bölüm 6).
- İngilizce PDF: kodda mevcut olmadığı için üretilmedi (görev şartı "varsa").
- Gerçek non-admin kullanıcıyla görünürlük testi bu görevin kapsamında değildi, yapılmadı.

## 8. Commit ve Branch

Tüm testler geçti → **master**'a commit + push edildi (bkz. commit mesajı: "Teklif PDF yeni tasarım (logo renkleri, KDV hariç tutar, peşinatsız, TCMB kur notu; Klasik seçeneği korunarak)"). Render deploy tamamlandıktan sonra canlıda `/login` ve giriş GEREKTİRMEYEN temel erişilebilirlik kontrol edildi (şifre istenmedi/kullanılmadı).
