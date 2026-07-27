# Yapılacaklar / Teknik Borç

- **Teknik borç:** `create_app()` içindeki `db.create_all()` ile Flask-Migrate arasında çakışma riski var - yeni tablo eklerken `db.create_all()` tabloyu migration'dan önce oluşturup Alembic senkronizasyonunu bozabiliyor. İleride `db.create_all()` kullanımını kaldırıp tamamen migration tabanlı bir akışa geçmeyi değerlendir.
- **2026-07-15 düzeltildi:** `create_invoice_from_deal()`'daki fatura/irsaliye numaralandırma `_next_invoice_no()` helper'ına taşındı (`_next_deal_no()` ile aynı NULL-güvenli `db.func.max()` mantığı). Mevcut faturalarda zaten NULL invoice_no yoktu, veri düzeltmesi gerekmedi.
- **2026-07-14:** Müşteri arama Türkçe karakter normalizasyonu ile düzeltildi - "saroglu" yazınca "Şaroğlu" artık bulunuyor (önceden ILIKE diyakritiksiz aramaları yakalamıyordu).
- **2026-07-15 tespit edildi ve düzeltildi:** `edit_customer.html` formu `Customer.company_name` alanını yanlış isimle (`name="company"`) gönderiyordu, route ise `company_name` bekliyordu - yani müşteri düzenleme ekranından firma ünvanı hiçbir zaman kaydedilmiyordu (sessiz no-op). `add_customer.html` zaten doğruydu. Form ismi düzeltildi, ayrıca "Vergi No" (tax_id) alanı zaten mevcuttu ve çalışıyordu.
- **2026-07-15 eklendi:** İş Emri PDF'i (`pdf_utils.generate_is_emri_pdf`, dahili üretim talimatı - fiyat içermez, teklif PDF'lerindeki isim temizleme mantığı aynen kullanılıyor) - production_detail'de "İş Emri Yazdır" butonu. `ProductionItem`'a Ölçü/Baskı Rengi-Sayısı/Kağıt Tipi/Gramaj alanları eklendi (production_detail'den elle doldurulur).
- **2026-07-15 eklendi:** Fatura oluştururken müşteride firma ünvanı/vergi no eksikse uyarı gösterilip aynı formdan düzeltilebiliyor (ayrı sayfaya gitmeden, tek POST'ta hem müşteri güncelleniyor hem fatura oluşuyor).
- **2026-07-15 eklendi:** "Faturasız Çıkış" - sevkiyat oluşturma artık irsaliyeyi her durumda zorunlu tutuyor ama faturayı "Faturasız Çıkış" onay kutusuyla atlanabilir kılıyor (`Shipment.faturasiz_cikis` alanı ileride raporlarda ayırt etmek için eklendi).
- **2026-07-28 eklendi - Merkezi müşteri arama:** `/api/customers/search` ve `/api/customers/search-by-name` tek endpoint'te (`/api/customers/search`) birleştirildi, eski endpoint kaldırıldı. Yeni `app/static/js/customer-search.js` tüm müşteri seçim noktalarında (Teklif, Ödeme, Ziyaret, Görev, Günlük Rapor) kullanılan tek, merkezi arama bileşeni - Türkçe normalizasyon, debounce, dropdown sonuç listesi. Bazı formlar (Ziyaret/Görev/Ödeme) daha önce 1682+ satırlık dev `<select>` dropdown kullanıyordu, artık hepsi arama kutusu.
- **2026-07-28 eklendi - Fatura/İrsaliye PDF:** `invoice_detail.html`'de hiç PDF indirme seçeneği yoktu (gerçek bug) - `pdf_utils.generate_invoice_pdf()` + `/invoices/<id>/pdf` route eklendi, hem fatura hem irsaliye (Invoice.type) için çalışıyor. Madde 3'teki Shipment-bazlı irsaliye PDF (`/shipments/<id>/irsaliye`) ayrıca test edilip hâlâ çalıştığı doğrulandı.
- **2026-07-28 düzeltildi - Teklif isimlendirme:** Eski "MEHMET-01.07-1" tarzı kısaltılmış/karışık otomatik başlık mantığı (JS'de 6 karaktere kısaltma + tarih + sıra no) tamamen kaldırıldı. `Deal.title` artık her zaman müşterinin tam adı (temizlenmiş, `_customer_full_name()` helper'ı ile - firma varsa "Firma - Ad Soyad" formatında, `Customer.display_name` ile tutarlı). Teklif No (`deal_no`/`display_no`) ayrı kalıyor. `revise_deal()`'daki "(Revize N)" suffix mantığı kaldırıldı - revize teklif aynı isimle, sadece yeni deal_no ile devam ediyor. Ayrıca birkaç şablonda/route'ta `deal.id` ile yanlış "TKL-" numaralandırma yapan kod (doğrusu `deal.deal_no`/`display_no`) bulunup düzeltildi (deals.html, customer_detail.html, deal_detail.html, Excel export, Reminder mesajı).
- **2026-07-28 eklendi - Teklif formunda eksik bilgi tamamlama:** Fatura formundaki (2026-07-15) aynı desen artık teklif oluşturma formunda da var - müşteri seçilince firma ünvanı/vergi no/telefon/adres eksikse uyarı + aynı formdan tamamlama alanları çıkıyor.
- **⚠️ ÖNEMLİ - kalıcılık riski (2026-07-28):** Tasarım görselleri (`Customer.tasarim_gorseli`, `Production.tasarim_gorseli_override`) kullanıcı talebi üzerine `app/static/uploads/tasarimlar/` klasörüne **dosya olarak** kaydediliyor. Render'ın disk depolaması KALICI DEĞİL - her yeni deploy'da (her `git push`'ta) bu klasördeki dosyalar silinir! CompanySettings logosu bu yüzden bilerek veritabanında (bytea) saklanmıştı; tasarım görselleri için bu riski kullanıcı açıkça kabul ederek dosya yolu istedi. İleride bytea'ya taşımak gerekebilir.
- **2026-07-28 eklendi - Deal ödeme şekli:** `Deal.vade_gun/pesinat/bakiye_odemesi` (serbest metin) eklendi, teklif formunda düzenlenebiliyor, teklif PDF'indeki "ÖDEME ŞEKLİ" kutusuna gerçek değer olarak yansıyor (boşsa noktalı çizgi kalıyor).
- **2026-07-28 eklendi - Teklif PDF ürün tablosu genişletildi:** Körük/Sedef/Selefon M/Selefon P/Gofre/Varak sütunları eklendi (Boy/En'den sonra, Renk'ten önce - toplam 15 sütun, veri modelinde tutulmadığı için '-' ile dolu, çok küçük fontla (6-6.5pt) sayfaya sığdırıldı). Ödeme Şekli kutusuna çizilmiş (Vera fontunda Unicode checkbox glifi olmadığı doğrulanıp cizilmiş kutucuklara geçildi) Nakit/KK/Çek/Senet checkbox'ları ve ürün tablosunun altına boş "AÇIKLAMA" kutusu eklendi.
- **2026-07-28 eklendi - Tasarım Görseli:** `Customer.tasarim_gorseli` (müşteri düzenleme formundan yüklenir) ve `Production.tasarim_gorseli_override` (production_detail'den bu iş emrine özel yüklenebilir, `Production.tasarim_gorseli` property'si override varsa onu yoksa müşterinin varsayılanını döner) eklendi. İş Emri PDF'inde gösteriliyor.
- **2026-07-28 tamamen yeniden yazıldı - İş Emri PDF (9 madde):** Firma başlığı (CompanySettings'ten), koyu arka planlı "İŞ EMRİ" rozeti, "Nüsha: Baskı Ustası"/"Nüsha: Makine Ustası" etiketi (production_detail'de dropdown, `?nusha=baski|makine` query param), durum çubuğu (Üretimde→Hazır→Sevkiyat, aktif koyu/geçmiş yeşilimsi/gelecek soluk), teslim tarihi, tasarım görseli, tablo TAM OLARAK Kağıt Cinsi/Kaç Kg/Baskı Rengi/Ölçü/Planlanan Adet/Gerçekleşen Adet (fiyat yok, eski "Açıklama" sütunu Kağıt Cinsi hücresine küçük alt satır olarak birleştirildi), üç imza (Üretimi Yapan/Kontrol Eden/Teslim Alan), dosya adı `IsEmri_{müşteri_adı}_{IE-no}.pdf` formatında Türkçe karakter/boşluk güvenli. `ProductionItem.kac_kg` yeni alanı eklendi (İş Emri Detayları formundan doldurulur). Tüm 9 madde PyMuPDF ile PNG'e çevrilip gerçekten görsel olarak doğrulandı.

---

# 20 Maddelik Geliştirme Yol Haritası

**Çalışma kuralı:** Her madde kendi başına eksiksiz bir birim (model → route → arayüz), test edilip (test verisiyle, sonra temizlenir), migration varsa Neon'a uygulanıp, commit+push yapılıp bitirilir. Oturum başına en fazla 1-2 madde. Yeni oturumda "nerede kaldık" sorulduğunda bu dosyaya bakılır.

## 🚀 Katman 1 — Hemen Şimdi (Yüksek Öncelik / Acil)

- [x] 1. Üretim İş Emri Otomasyonu — teklif onaylanınca ürün/miktar/teslim tarihi içeren iş emri otomatik oluşsun, müşteri detayında "bekleyen iş emri" görünsün ✅ (2026-07-10) — mevcut Production/ProductionItem modelleri üzerine inşa edildi (yeni tablo açılmadı), Production.due_date eklendi
- [x] 2. Üretim Aşamaları Takibi ✅ (2026-07-12, **sadeleştirildi 2026-07-14**) — İlk sürümde 7 aşamalı akış + `ProductionStatusLog` timeline + tahmini teslim tarihi vardı; kullanımda gereğinden karmaşık bulunduğu için 2026-07-14'te basit 3 durumlu akışa indirildi: **Üretimde** (iş emri oluşunca otomatik) → **Hazır** (tek buton, gerçek üretilen adet girilerek işaretlenir) → **Sevkiyat** (sevkiyat oluşturulunca otomatik). `ProductionStatusLog` tablosu ve timeline kaldırıldı, mevcut veri (`beklemede`→`uretimde`) migration ile taşındı.
- [x] 3. Sevkiyat Modülü — kargo şirketi/takip no/teslim tarihi girilsin, kargo takip linki ve İrsaliye PDF'i otomatik oluşsun ✅ (2026-07-13, **güncellendi 2026-07-14**) — mevcut Shipment/ShipmentItem modelleri genişletildi (estimated_delivery_date, actual_delivery_date eklendi), kargo firması dropdown + otomatik takip linki (Aras/MNG/Yurtiçi/UPS/Sürat), "Teslim Edildi" işaretleme, İrsaliye PDF (pdf_utils.generate_irsaliye_pdf), customer_detail'de sevkiyat durumu gösterimi. Ayrıca önceden var olan ama bozuk (var olmayan quantity/unit/weight_kg alanlarına referans veren) edit_shipment route'u düzeltildi. **2026-07-14:** sevkiyat kalemleri artık Production.items'daki gerçek üretilen adetten otomatik oluşuyor (fiyat/kg tekrar sorulmuyor); sevkiyat oluşturma, ilgili teklife bağlı bir irsaliye kaydı yoksa engelleniyor (fatura ise "Faturasız Çıkış" onay kutusuyla atlanabilir - bkz. 2026-07-15 notu).
- [ ] 4. Rol ve Yetkilendirme Sistemi — Admin/Satış/Üretim/Mali/Yönetici rolleri, sayfa+işlem bazlı erişim kontrolü
- [ ] 5. Stok Hareketi Kaydı — üretim başlayınca hammadde otomatik düşsün, log tutulsun, kritik stokta "Kalan N günlük stok" uyarısı
- [ ] 6. Audit Log Sistemi — tüm UPDATE/DELETE işlemleri (kim, ne zaman, eski/yeni değer) izlensin
- [ ] 7. Kârlılık Raporu (Müşteri Başına) — toplam satış, tahmini maliyet, brüt kâr %, düşük kârlılar işaretlensin
- [ ] 8. Şifre Politikası ve Güvenlik — min 8 karakter, 90 gün şifre yaşı, brute force koruması (5 hata = kilit)

## 📈 Katman 2 — 2-3 Ay (Gelişmiş Özellikler)

- [ ] 9. Satış Funnel Raporu — Teklif → Kazanma Oranı → Sipariş → Teslim istatistikleri, aylık trend
- [ ] 10. Müşteri Segmentasyon — sektör ve firma boyutu bazlı gruplama
- [ ] 11. Teklif Revizyon Geçmişi — v1→v2 geçişlerinde eski fiyat/şart geçmişi
- [ ] 12. Mobil Arayüz İyileştirmesi — form genişlikleri, yatay kaydırılabilir tablolar, sonsuz kaydırma
- [ ] 13. Tahsilat Raporlaması — aylık trend, vadesi geçenler listesi, kısmi/taksitli ödeme altyapısı
- [ ] 14. Kapasite Planlama — makine başına kuyruktaki iş emri sayısı, tahmini bitiş tarihi
- [ ] 15. Müşteri Takip Döngüsü (30/60/90 gün) — uyuyan müşteriler için hatırlatıcılar (not: temel "Uyuyan Müşteriler" listesi zaten var, bu madde onun üstüne hatırlatıcı/otomasyon katmanı ekliyor)

## ⚙️ Katman 3 — 3-6 Ay (Optimizasyon)

- [ ] 16. Çoklu Para Birimi — ihracat için USD/EUR desteği, kur güncellemesi
- [ ] 17. Teklif Şablonları (Templates) — sık kullanılan ürün kombinasyonları hızlı teklife dönüşsün
- [ ] 18. Ürün Satış Analizi — hangi ürün ne kadar satıldı, brüt kâr oranları
- [ ] 19. Banka Eşleştirmesi — OFX/MT940 dosyalarının ödemelerle otomatik eşleşmesi
- [ ] 20. Takvim Senkronizasyonu — görevlerin Google/Outlook takvimine entegrasyonu
