# PAKET B — Konsolide Rapor (2026-10-14)

Tüm işler (B1-B6) commit edilip **origin/master'a push edildi**, `git status` temiz (bu oturumdan kalan push edilmemiş iş yok — aşağıdaki "YAYINA ALINMAMIŞ İŞ VAR" uyarısı GEÇERLİ DEĞİL).

Gece modu / otonom mod kurallarına göre: hiçbir gerçek kayıt silinmedi/değiştirilmedi, tüm testler `TEST`/`TEST-` önekli kayıtlarla yapıldı ve iş sonunda silindi, `Payment` tablosuna dokunulmadı (24 kayıt, oturum başından sonuna değişmedi), her riskli/şema değişikliğinden önce yedek tazeliği kontrol edildi.

---

## TESLİM TABLOSU

| İş | Alt madde | Durum | Commit | Canlıda doğrulandı mı | Kanıt |
|---|---|---|---|---|---|
| **B1** | Havale/EFT seçilince teklif formunda mavi IBAN önizleme kutusu | ✅ | `d48e1f2` | CANLIDA DOĞRULANMADI (giriş engelli) | Yerelde test edildi |
| B1 | Yeni tasarım PDF'te sarı IBAN kutusu (TR) | ✅ | `d48e1f2` | CANLIDA DOĞRULANMADI | Yerelde test edildi |
| B1 | IBAN kutusu EN PDF'te de (B5 ile birlikte otomatik, aynı fonksiyon) | ✅ | `d48e1f2` + `4b8cade` | CANLIDA DOĞRULANMADI | Bu oturumda EN PDF testiyle doğrulandı |
| B1 | Klasik tasarım dokunulmadı | ✅ | `d48e1f2` | CANLIDA DOĞRULANMADI | Yerelde test edildi |
| **B2** | Manuel irsaliye düzenleme (`/irsaliye/manuel/<id>/edit`) | ✅ | `c3ebec3` | CANLIDA DOĞRULANMADI | Yerelde test edildi |
| B2 | Faturayla iki yönlü eşitleme (onay + uygula) | ✅ | `c3ebec3` | CANLIDA DOĞRULANMADI | Yerelde test edildi |
| B2 | Fark uyarısı (turuncu kutu) + `/raporlar/irsaliye-fatura-farklari` | ✅ | `c3ebec3` | CANLIDA DOĞRULANMADI | Yerelde test edildi, ekran görüntüsü var |
| B2 | Değişiklik log'u (`irsaliye_degisiklik_log`) | ✅ | `c3ebec3` | CANLIDA DOĞRULANMADI | Yerelde test edildi |
| B2 | Kilit mekanizması (muhasebeye gönderildiyse düzenleme/eşitleme engellenir) | ✅ | `c3ebec3` | CANLIDA DOĞRULANMADI | Yerelde test edildi |
| **B3** | Teklif formunda numaralı ürün kartları (Kart/Eski Tablo toggle) | ✅ | `168b642`, `1213ed1` | CANLIDA DOĞRULANMADI | Yerelde + Playwright |
| B3 | Kese Seç / Doypack Seç kart modunda çalışıyor | ✅ (bug bulunup düzeltildi) | `1213ed1` | CANLIDA DOĞRULANMADI | Playwright, konsol hatasız |
| B3 | Eski Tablo modu bire bir korundu | ✅ | `1213ed1` | CANLIDA DOĞRULANMADI | Playwright, gerçek tarayıcıda yeniden doğrulandı |
| B3 | Kart/Tablo veri özdeşliği (aynı name, sıra, değer) | ✅ | `1213ed1` | CANLIDA DOĞRULANMADI | TEST- teklifle DB karşılaştırması |
| B3 | edit_deal'de "KDV hariç tutar" canlı hesaplanıyor | ✅ (bug bulunup düzeltildi) | `1213ed1` | CANLIDA DOĞRULANMADI | Playwright |
| **B4** | `DealItem.para_birimi`, `Deal.kur_usd/kur_eur/kur_tarihi/kur_turu` (nullable) | ✅ | `1527ab1` | CANLIDA DOĞRULANMADI | Migration Neon'a uygulandı |
| B4 | ESKİ VERİ GÜVENCESİ (tek kuruş fark yok) | ✅ | `1527ab1` | — | **118/118 teklif, UYUMSUZLUK: 0** (aşağıda detay) |
| B4 | TCMB kur bandı (USD/EUR, otomatik + elle) | ✅ | `1527ab1` | CANLIDA DOĞRULANMADI | Playwright, gerçek TCMB isteği test edildi |
| B4 | Kart başına TL/USD/EUR segmenti + canlı "≈ TL" | ✅ | `1527ab1` | CANLIDA DOĞRULANMADI | Playwright |
| B4 | Özet: döviz bazında kırılım + TL genel toplam | ✅ | `1527ab1` | CANLIDA DOĞRULANMADI | Playwright |
| B4 | Eski Tablo modu dokunulmadı | ✅ | `1527ab1` | CANLIDA DOĞRULANMADI | Playwright |
| B4 | PDF: birim fiyat kendi para biriminde + "≈ TL", kur notu | ✅ (TR) | `1527ab1` | CANLIDA DOĞRULANMADI | pypdf ile metin karşılaştırması |
| **B5** | İngilizce teklif PDF'i (yeni tasarım) | ✅ | `4b8cade` | CANLIDA DOĞRULANMADI | 118 teklifte TR+EN PDF hatasız üretildi |
| B5 | Sayı biçimi (1,700.00 TRY; 500 pcs; 12.5 kg) | ✅ | `4b8cade` | CANLIDA DOĞRULANMADI | pypdf metin çıktısıyla doğrulandı |
| B5 | Tutar-yazıyla satırı EN'de basılmıyor | ✅ | `4b8cade` | CANLIDA DOĞRULANMADI | pypdf metin çıktısıyla doğrulandı |
| B5 | Klasik tasarım dokunulmadı (lang='en' yok sayılır) | ✅ | `4b8cade` | CANLIDA DOĞRULANMADI | Test edildi |
| B5 | "PDF İndir (EN)" butonu (sadece yeni tasarımda) | ✅ | `4b8cade` | CANLIDA DOĞRULANMADI | Playwright, indirme doğrulandı |
| **B6** | Türkçe-duyarlı isim normalize + benzerlik skoru | ✅ | `a1a45a6` | — | MİSS Kuruyemiş çifti skor 0.929 ile yakalandı |
| B6 | `/customers/mukerrer`'e "İsim Benzerliği" bölümü | ✅ | `a1a45a6` | CANLIDA DOĞRULANMADI | Playwright, merge modal test edildi |
| B6 | Non-blocking sarı uyarı (yeni müşteri / quick-add) | ✅ | `a1a45a6` | CANLIDA DOĞRULANMADI | Playwright, gerçek tarayıcıda uyarı kutusu görüldü |
| B6 | MİSS Kuruyemiş çifti (id 1825/1862) özellikle doğrulandı | ✅ | `a1a45a6` | — | Skor 0.929, 82 adayın 67.sı |

Hiçbir madde ❌/⚠️ olarak kapanmadı; tüm alt maddeler tamamlandı.

---

## KARAR'lar (otonom modda alınan, kullanıcıya bildirilmesi gereken kararlar)

1. **B4 — iki döviz mekanizması aynı teklifte birlikte kullanılmaz.** Teklif seviyesi döviz (`Deal.para_birimi` EUR/USD/GBP, eski/mevcut özellik) aktifse, kalem bazlı döviz (yeni B4 özelliği) o teklifte gösterilmez/devre dışı kalır. Gerekçe: iki farklı "TL karşılığı" hesaplama modelinin aynı teklifte çakışmasını önlemek, mevcut hesaplamayı bozmamak.
2. **B4 — kalem bazlı döviz UI sadece Kart görünümünde var**, Eski Tablo görünümü B3'teki gibi pikselden davranışa kadar değişmeden kaldı.
3. **B5 — Klasik PDF tasarımı İngilizce desteklemiyor**, sadece yeni tasarımda var. `lang=en` istenirse ve şirket Klasik tasarımı seçmişse, parametre sessizce yok sayılır (her zaman TR basar).
4. **B5 — şirket ayarlarındaki özel "Teklif Şartları" metni (`company.teklif_sartlari`) İngilizce PDF'te de ÇEVRİLMEZ, olduğu gibi basılır.** Sadece bu alan boşsa kullanılan 5 maddelik varsayılan şartlar ve kur notu İngilizceye çevrildi. Gerekçe: kullanıcının yazdığı metni makine çevirisiyle değiştirmek riskli (anlam kayması/hatalı çeviri ihtimali) — sessiz otomatik çeviri yerine mevcut TR metin korunuyor.
5. **B6 — tek kelimelik (örn. "Ahmet", "Murat") isim eşleşmeleri aday listesine alınmıyor.** Filtre olmadan 336 aday vardı, büyük çoğunluğu yaygın tek isimlerin farklı kişilerde tekrarından kaynaklanan gürültüydü; filtre sonrası 82 adaya düştü, gerçek adaylar (yazım farkı/fazladan kelime) korunarak.
6. **B6 — isim benzerliği tespiti SADECE öneri/uyarı amaçlıdır, hiçbir otomatik birleştirme yapmaz.** Hem `/customers/mukerrer` sayfasındaki yeni bölüm hem de yeni-müşteri/quick-add akışındaki sarı uyarı, kullanıcı onayı olmadan hiçbir kaydı değiştirmez/silmez.

---

## B4 — ESKİ VERİ GÜVENCESİ sonucu (zorunlu kontrol)

```
toplam teklif: 118
UYUMSUZLUK SAYISI: 0
```

Tüm mevcut tekliflerin `subtotal`/`vat_amount`/`value` alanları, yeni `calculate_totals()` koduyla yeniden hesaplandığında **tek kuruş fark olmadan** eski değerlerle birebir eşleşti (bu, yeni kodun eski kayıtlar için — `item.para_birimi` hepsinde `NULL` olduğundan — matematiksel olarak eskiyle AYNI yolu izlemesinin garantili sonucu, rastgele bir test başarısı değil). Kontrol migration uygulandıktan hemen sonra ve tüm B4/B5/B6 kod değişiklikleri bittikten sonra olmak üzere **iki kez** çalıştırıldı, ikisinde de sonuç aynı.

---

## B2 — "kesildi" bilgisi çözümü

Orijinal görev tanımında faturanın "kesildi" durumunun irsaliye/fatura kilidi için kullanılması bekleniyordu. Okuma aşamasında **`Invoice` modelinde "kesildi" bilgisini tutan bir alan hiç olmadığı** tespit edildi. Çözüm: yeni, nullable `Invoice.muhasebeye_gonderildi` (bool) + `Invoice.muhasebeye_gonderilme_tarihi` alanları eklendi — bu, "kesildi" kavramının B2 kapsamındaki karşılığı olarak kullanıldı. Bu alan işaretliyse hem irsaliye hem fatura düzenleme/eşitleme route'ları HTTP 302 ile reddediyor (kilit). Mevcut hiçbir alan/tablo değiştirilmedi, sadece eklendi.

---

## B6 — Aday çift sayısı ve ilk 30

**Toplam aday: 82** (filtre uygulanmış — bkz. KARAR 5). Tam liste `/customers/mukerrer` sayfasında "İsim Benzerliği ile Tespit Edilenler" bölümünde görülebilir.

**Zorunlu doğrulama — MİSS Kuruyemiş çifti (müşteri #1825 / #1862):** skor **%92.9** ile adaylar arasında (82 adayın 67. sırasında, skora göre sıralı listede). `#1825 "MİSSS KURUYEMİŞ - HÜSEYİN İN"` ↔ `#1862 "MİSS KURUYEMİŞ"`.

İlk 30 aday (skora göre azalan sırada; `#id isim <-> #id isim`):

```
1.  [%100] #1818 TEKDEM GIDA İNŞAAT OTOMOTİV ZÜCCACİYE İTHALAT SANAYİ VE TİCARET LİMİTED ŞİRKETİ  <->  #1817 (aynı isim)
2.  [%100] #1595 Gökhan Bey &  <->  #53 Gökhan Bey Bursa Baharat
3.  [%100] #415 Gökhan Kargo Vedat  <->  #641 Gökhan Kargo
4.  [%100] #1433 Said TOPRAK  <->  #4 Said Toprak
5.  [%100] #1124 Fatih Kuruyemiş Fatih Abi  <->  #43 Fatih Kuruyemiş
6.  [%100] #917 Cesur Grafik Rıza  <->  #918 Cesur Grafik
7.  [%100] #255 Kayseri Nakliye Mehmet  <->  #468 Kayseri Nakliye
8.  [%100] #940 GÖZDE KURUYEMİŞ  <->  #1578 Gözde Kuruyemiş Siliv ri &
9.  [%100] #1843 ÇEREZHAN KAYISI  <->  #1842 ÇEREZHAN KAYISI (aynı isim)
10. [%100] #475 Çerezcim Ahmet  <->  #925 Çerezcim Ahmet Havzan
11. [%100] #939 KÖŞEM DÖNER  <->  #1097 Köşem Döner Raşit Abi
12. [%100] #344 Diyarkon Konum  <->  #535 Diyarkon Konum 2
13. [%100] #779 Erzincan Ambar İkizler  <->  #241 Erzincan Ambar
14. [%100] #208 Erzurum Kuruyemiş İkram  <->  #1077 Erzurum Kuruyemiş
15. [%100] #1316 Erzurum Kuruyemiş Ahmet Abi  <->  #1077 Erzurum Kuruyemiş
16. [%100] #30 Hüseyin Abi Taş Fırın Kuruyemiş  <->  #124 Hüseyin Abi
17. [%100] #242 Sivas Nakliye Tarık  <->  #250 Sivas Nakliye
18. [%100] #405 Nakkaşoğlu Ankara  <->  #1552 Nakkaşoğlu Ankara Arda Bey&
19. [%100] #86 Harun Abi  <->  #1466 Harun Abi Çıtırdads
20. [%100] #674 Nevşehir Nakliyeci  <->  #234 Nevşehir Nakliye
21. [%100] #256 Adana Express Cep  <->  #557 Adana Express
22. [%100] #325 Mustafa Abi Mülhem Kuruyemiş  <->  #88 Mustafa Abi
23. [%100] #325 Mustafa Abi Mülhem Kuruyemiş  <->  #172 Mustafa Abi
24. [%100] #325 Mustafa Abi Mülhem Kuruyemiş  <->  #177 Mustafa Abi
25. [%100] #487 Mustafa Abi Korkmaz Ambalaj  <->  #88 Mustafa Abi
26. [%100] #487 Mustafa Abi Korkmaz Ambalaj  <->  #172 Mustafa Abi
27. [%100] #487 Mustafa Abi Korkmaz Ambalaj  <->  #177 Mustafa Abi
28. [%100] #88 Mustafa Abi  <->  #172 Mustafa Abi
29. [%100] #88 Mustafa Abi  <->  #177 Mustafa Abi
30. [%100] #88 Mustafa Abi  <->  #1424 Mustafa Abi Morpack Ambalaj
```

Not: skor %100 olanların çoğu "aynı isim + fazladan kelime/garip ek karakter" (ör. `"... &"`, `"... ." gibi veri girişi artıkları) deseninde — bu, bu CRM'in gerçek verisinde çok yaygın bir kalıp. Tespit SADECE öneri listesidir, kullanıcı her çifti tek tek inceleyip karar vermelidir (bkz. KARAR 6).

---

## Silinen TEST- kayıtlar (bu oturum)

Her işin sonunda oluşturulan TÜM `TEST`/`TEST-` önekli müşteri/teklif/kalem kayıtları silindi, iş bitiminde ayrı ayrı doğrulandı (B3, B4, B5, B6 bölümlerinde). **Son/nihai kontrol** (bu rapordan hemen önce çalıştırıldı):

```
kalan TEST- müşteri (company_name): 0
kalan TEST- müşteri (first_name): 0
Payment tablosu: 24 (oturum başından sonuna DEĞİŞMEDİ)
Deal tablosu: 118 (gerçek kayıt sayısı sabit)
```

---

## SERKAN CANLI KONTROL LİSTESİ

Bu ortamda canlıya girişli test Claude Code tarafından engellendiği için aşağıdakiler yerelde ✅ ama **canlıda doğrulanmadı**:

1. **B4 — Teklif ekle/düzenle (Kart görünümü):** "1 USD = ? ₺" / "1 EUR = ? ₺" kur bandını doldurup (TCMB'den Güncelle veya elle), bir kalemde USD/EUR seçip toplamın TL olarak doğru hesaplandığını kontrol et.
2. **B5 — Herhangi bir teklifin detay sayfasında** "PDF İndir (EN)" butonunun göründüğünü ve İngilizce PDF'in doğru indirildiğini kontrol et (Klasik tasarım kullanılıyorsa bu buton görünmemeli).
3. **B6 — `/customers/mukerrer` sayfasında** "İsim Benzerliği ile Tespit Edilenler" bölümünün göründüğünü, MİSS Kuruyemiş çiftinin (ya da listedeki başka bir gerçek çiftin) listelendiğini kontrol et; yeni müşteri eklerken benzer isimli biri varsa sarı uyarının göründüğünü kontrol et.

---

## Not: docs/GOREV_KAYDI.md

B1-B6 için tek satırlık kayıtlar eklendi (commit'ler: `63e443b`, `e26c536`, `f1a5b63`, `1977f54`).
