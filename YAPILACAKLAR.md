# Yapılacaklar / Teknik Borç

- **Teknik borç:** `create_app()` içindeki `db.create_all()` ile Flask-Migrate arasında çakışma riski var - yeni tablo eklerken `db.create_all()` tabloyu migration'dan önce oluşturup Alembic senkronizasyonunu bozabiliyor. İleride `db.create_all()` kullanımını kaldırıp tamamen migration tabanlı bir akışa geçmeyi değerlendir.
- **2026-07-15 düzeltildi:** `create_invoice_from_deal()`'daki fatura/irsaliye numaralandırma `_next_invoice_no()` helper'ına taşındı (`_next_deal_no()` ile aynı NULL-güvenli `db.func.max()` mantığı). Mevcut faturalarda zaten NULL invoice_no yoktu, veri düzeltmesi gerekmedi.
- **2026-07-14:** Müşteri arama (`/api/customers/search`, `/api/customers/search-by-name`) Türkçe karakter normalizasyonu ile düzeltildi - "saroglu" yazınca "Şaroğlu" artık bulunuyor (önceden ILIKE diyakritiksiz aramaları yakalamıyordu).
- **2026-07-15 tespit edildi ve düzeltildi:** `edit_customer.html` formu `Customer.company_name` alanını yanlış isimle (`name="company"`) gönderiyordu, route ise `company_name` bekliyordu - yani müşteri düzenleme ekranından firma ünvanı hiçbir zaman kaydedilmiyordu (sessiz no-op). `add_customer.html` zaten doğruydu. Form ismi düzeltildi, ayrıca "Vergi No" (tax_id) alanı zaten mevcuttu ve çalışıyordu.
- **2026-07-15 eklendi:** İş Emri PDF'i (`pdf_utils.generate_is_emri_pdf`, dahili üretim talimatı - fiyat içermez, teklif PDF'lerindeki isim temizleme mantığı aynen kullanılıyor) - production_detail'de "İş Emri Yazdır" butonu. `ProductionItem`'a Ölçü/Baskı Rengi-Sayısı/Kağıt Tipi/Gramaj alanları eklendi (production_detail'den elle doldurulur).
- **2026-07-15 eklendi:** Fatura oluştururken müşteride firma ünvanı/vergi no eksikse uyarı gösterilip aynı formdan düzeltilebiliyor (ayrı sayfaya gitmeden, tek POST'ta hem müşteri güncelleniyor hem fatura oluşuyor).
- **2026-07-15 eklendi:** "Faturasız Çıkış" - sevkiyat oluşturma artık irsaliyeyi her durumda zorunlu tutuyor ama faturayı "Faturasız Çıkış" onay kutusuyla atlanabilir kılıyor (`Shipment.faturasiz_cikis` alanı ileride raporlarda ayırt etmek için eklendi).

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
