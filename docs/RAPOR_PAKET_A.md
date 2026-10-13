# RAPOR: PAKET A — 4 İş, Sırayla — 2026-10-14

Yayına alınmamış iş yok — İş 1/2/3'ün her biri kendi testleri geçtikten sonra ayrı commit olarak **master**'a push edildi. İş 4 salt-okuma (kod değişikliği yok).

## 1. Teslim Tablosu

| İş | Alt madde | Durum | Commit | Canlıda doğrulandı mı | Kanıt |
|---|---|---|---|---|---|
| 1 | Yeni tasarımda AÇIKLAMA kutusu (notlar) | ✅ | `3ecbb09` | CANLIDA DOĞRULANMADI (giriş engelli) — yerelde ✅ | `docs/rapor_gorseller/is1_senaryo_A/B/C_*.png` |
| 1 | Klasik PDF'e dokunulmadı (zaten çalışıyordu) | ✅ | `3ecbb09` | — | kod diff: klasik fonksiyonu değişmedi |
| 1 | Deal.ic_not + form alanı + uyarı metni | ✅ | `3ecbb09` | CANLIDA DOĞRULANMADI — yerelde ✅ | edit round-trip test_client ile doğrulandı |
| 1 | Test: notlu/notsuz/60 satır/iç not gizliliği/edit round-trip | ✅ (5/5) | `3ecbb09` | — | yukarıdaki PNG'ler + pdftotext eşdeğeri (PyMuPDF metin çıkarma) |
| 2a | "Ürün tipi" satırı kaldırıldı, kağıt cinsi==ürün adı satırı basılmıyor | ✅ | `e31b7e7` | CANLIDA DOĞRULANMADI — yerelde ✅ | `docs/rapor_gorseller/is2_senaryo_A.png` |
| 2b | Numune sütunu numunesiz teklifte tamamen gizli | ✅ | `e31b7e7` | CANLIDA DOĞRULANMADI — yerelde ✅ | `is2_senaryo_A.png` (6 sütun, Numune yok) |
| 2c | Miktar/birim fiyat Türkçe sayı biçimi | ✅ | `e31b7e7` | CANLIDA DOĞRULANMADI — yerelde ✅ | `is2_senaryo_A.png` (500 adet/1.500 kg/12,5 kg), `is2_senaryo_B.png` (0,245 $) |
| 2 | Klasik'e dokunulmadı | ✅ | `e31b7e7` | — | kod diff: sadece `_generate_deal_pdf_yeni` içi değişti |
| 3 | Deal'e odeme_vade_gun/pesinat_tipi/pesinat_deger/bakiye_zamani (nullable) | ✅ | `699c131` | CANLIDA DOĞRULANMADI — yerelde ✅ | migration `c3d4e5f6a7b8`, Neon'a uygulandı |
| 3 | add_deal + edit_deal yeni Ödeme Şekli UI (Vade/Peşinat/Bakiye) | ✅ | `699c131` | CANLIDA DOĞRULANMADI — yerelde ✅ | `docs/rapor_gorseller/is3_bos/yuzde/tl/hata.png` |
| 3 | pesinat_orani senkronu (Takip Modu uyumluluğu) | ✅ | `699c131` | — | test: %50→orani=50.0, 15000TL→orani≈17,11, Yok→orani=0.0 (ayrıntı Bölüm 4) |
| 3 | Sunucu + JS doğrulama (%>100, tutar>genel toplam reddedilir) | ✅ | `699c131` | — | test: %120 ve 90.000 TL ile deal OLUŞMADI (doğrulandı) |
| 3 | Eski kayıt gri bilgi satırı (edit_deal) | ✅ | `699c131` | CANLIDA DOĞRULANMADI — yerelde ✅ | `docs/rapor_gorseller/is3_eski_kayit_banner.png` |
| 3 | PDF Vade satırı yeni alan varsa ondan (Yeni + Klasik) | ✅ | `699c131` | — | `Deal.vade_gun_metni` property, her iki tasarımda da kullanılıyor |
| 4 | MİSS Kuruyemiş teşhisi | ✅ (sadece okuma) | — (kod değişikliği yok) | — | Bölüm 5 |

## 2. Alınan Kararlar

- **İş 1**: Klasik PDF'in zaten `deal.notes`'u bastığı doğrulandı — görev metninin "Klasik'te zaten basıyorsa dokunma" koşulu buna göre işletildi, hiçbir klasik kodu değişmedi.
- **İş 2**: Birim fiyat ondalık kuralında ("en az 2, en fazla 4") görev metninin tek örneği ("0,2450 USD") ile çelişince, genel kural (gereksiz sıfır kırpılır) esas alındı — `0.245` değeri `"0,245"` (3 ondalık) olarak basılıyor, `"0,2450"` değil. Gerekçe: 0.245 matematiksel olarak 3 ondalıkla tam/kayıpsız temsil edilir, 4. basamak her zaman sıfır olacağından "gereksiz sıfır kırpılır" kuralıyla çelişir.
- **İş 3**: Yeni yapısal `pesinat_tipi`/`pesinat_deger` alanları, `approve_deal()`'ın KENDİ zorunlu `pesinat_orani` formunu DEĞİŞTİRMEDİ — sadece erken besleme (senkron yazma) yapıyor. Onay anında kullanıcı hâlâ kendi formuyla ayrıca girmek zorunda (mevcut, değişmeyen akış). Bu, "approve_deal zaten çalışıyor, bozma" ilkesiyle en güvenli/az değişiklik seçeneğiydi.
- **İş 3**: "Yok" seçilince `pesinat_orani = 0.0` yazılıyor (`None` değil) — bu, mevcut `_sync_payment_reminders_for_today()`'nin `None` ile `0`'ı ayırt eden mantığıyla (bkz. Bölüm 4) kasıtlı ve uyumlu bir seçim; `None` bırakılsaydı sistem "henüz karar verilmedi" sanıp farklı (outstanding_amount tabanlı) bir hesaba düşerdi.

## 3. Test Sonuçları (özet, ayrıntı her işin kendi commit mesajında)

- İş 1: 1 AÇIKLAMA'lı + 1 notsuz + 1×60 satırlık (3 sayfa) TEST teklifi, iç not hiçbirinde PDF metninde bulunmadı (PyMuPDF ile tarandı), edit formunda iç not kaydedilip geri yüklendi.
- İş 2: Numunesiz/numuneli iki TEST teklifi, kağıt cinsi==ürün adı senaryosu, miktar 500/1500/12,5, birim fiyat 0,245 USD — hepsi görsel olarak doğrulandı.
- İş 3: Tek kalemli (73.040 TL ara toplam, %20 KDV → 87.648 TL genel toplam) TEST teklifleri — 5 ayrı TEST müşterisiyle (çift-tıklama korumasının 30 saniyelik aynı-müşteri kısıtına takılmamak için):
  - %50 → peşinat 43.824,00 TL / bakiye 43.824,00 TL
  - 15.000 TL → oran ≈%17,11 / bakiye 72.648,00 TL
  - Yok → bakiye 87.648,00 TL (tamamı)
  - %120 → REDDEDİLDİ (deal oluşmadı)
  - 90.000 TL → REDDEDİLDİ (deal oluşmadı, genel toplamı aşıyor)

## 4. İş 3'ün Uyumluluk Açıklaması (Takip Modu nasıl besleniyor)

`Deal.pesinat_orani`, `Deal.pesinat_tutari`/`bakiye_tutari` property'lerinin TEK girdisi ve `_sync_payment_reminders_for_today()`'nin (routes.py ~1481) PaymentReminder tutarını hesaplarken kullandığı alan. Bu fonksiyon **teklif aşamasında da** (onaydan önce) `Deal.pesinat_tarihi`/`bakiye_tarihi` doluysa çalışıyor (kodun kendi yorumu bunu doğruluyor: "pesinat_tarihi/bakiye_tarihi artik teklif asamasinda da... doldurulabiliyor").

Yeni `pesinat_tipi`/`pesinat_deger` alanları kaydedilirken `_parse_odeme_sekli_form()` (routes.py) şu senkronu otomatik yapıyor:
- `yuzde` → `pesinat_orani = pesinat_deger` (doğrudan)
- `tutar` → `pesinat_orani = (pesinat_deger / genel_toplam) * 100` (eşdeğer yüzdeye çevrilir)
- `yok` → `pesinat_orani = 0.0`

Böylece **hiçbir** `_sync_payment_reminders_for_today()` veya `pesinat_tutari` kodu DEĞİŞMEDİ — sadece artık teklif aşamasında da doğru bir `pesinat_orani` değeri buluyorlar. `approve_deal()` onay anında bu değeri KENDİ zorunlu formuyla her zaman yeniden yazıyor (üzerine yazma davranışı aynen korundu) — yani yeni alanlar sadece onay ÖNCESİ bir "erken tahmin" sağlıyor, onay sonrası nihai söz hâlâ `approve_deal()`'da.

Doğrulama (Takip Modu'na KAYIT YAZMADAN): `_sync_payment_reminders_for_today()`'nin PaymentReminder tutarını hesapladığı satır (`pesinat_tutari = d.pesinat_tutari if d.pesinat_orani is not None else d.outstanding_amount`) referans alınarak, %50 senaryosundaki TEST teklifinin `d.pesinat_tutari` değeri doğrudan sorgulandı: **43.824,00 TL** — fonksiyon hiç çağrılmadan (ve dolayısıyla hiçbir PaymentReminder satırı yazılmadan) doğru değer teyit edildi.

## 5. İş 4 — MİSS Kuruyemiş Teşhis Sonuçları

**Sonuç (özetle): Bu bir teklif-müşteri bağlantı BUĞU DEĞİL — iki AYRI, birbirine çok benzeyen müşteri kaydı var (muhtemel mükerrer kayıt).**

1. **TKL-00090 bulundu**: Deal id=210, `customer_id=1862` (GEÇERLİ, mevcut bir müşteriye bağlı), `user_id=1` (serkan), `stage='kazanilan'` (SİPARİŞE DÖNMÜŞ), `created_at=2026-09-15 12:51`. Başlık: *"MİSS KURUYEMİŞ - ÖMER BEY"*. Teklif numarası `Deal.deal_no` (sıralı, `_next_deal_no()` ile `MAX(deal_no)+1`) üzerinden üretiliyor, `display_no` = `TKL-{deal_no:05d}`.

2. **Müşteri araması (İ/ı tuzağı dahil) test edildi**: `_normalize_tr()` (routes.py:631) Türkçe karakterleri doğru küçük harfe çeviriyor — `'miss'`, `'MİSS'`, `'Miss'`, `'MISS'` hepsi `'miss'`e normalize oluyor, arama **BOZUK DEĞİL**. ILIKE + Python normalize ile ayrı ayrı arandığında **6 müşteri** "miss" içeriyor, bunlardan **2 tanesinin gerçek teklifi var**:
   - **id=1862** "MİSS KURUYEMİŞ / ÖMER BEY", telefon `05326363012`, sahip=serkan (user 1), oluşturulma 2026-09-15 → **TKL-00090 (kazanılan)**
   - **id=1825** "MİSSS KURUYEMİŞ - HÜSEYİN İN / ÖMER  BEY" (dikkat: **3 S** — "MİSSS", muhtemel yazım hatası; `first_name` sonunda da fazladan boşluk var), vergi no dolu ama telefon **BOŞ**, sahip=sinan (user 2), oluşturulma 2026-08-14 (TKL-00090'dan **1 ay ÖNCE**) → **TKL-00067 (kaybedilen)**

3. **Müşteri detay sayfası sorgusu** (`customer_detail()`, routes.py:2502): `Deal.query.filter_by(customer_id=id)` — **hiçbir görünürlük/stage/limit filtresi YOK**, o müşterinin TÜM teklifleri gösteriliyor. Yani customer **1862**'nin detay sayfası açılırsa TKL-00090 **KESİNLİKLE görünür** (kod bunu garanti ediyor). Sorun şu ki **iki ayrı müşteri kaydı var** — eğer Serkan customer **1825**'in ("MİSSS KURUYEMİŞ - HÜSEYİN İN") detay sayfasını açtıysa, orada sadece TKL-00067'yi görür, TKL-00090'ı DEĞİL (çünkü o teklif fiziksel olarak customer 1862'ye bağlı, 1825'e değil).

4. **add_deal müşterisiz kayda izin vermiyor**: `customer_id` hidden input'u `required` değil ama route tarafı `Customer.query.get_or_404(int(request.form['customer_id']))` ile çalışıyor — boş/geçersiz gönderilirse `ValueError`/404 ile İSTEK BAŞARISIZ olur, sessizce NULL customer_id'li bir Deal oluşmaz (`Deal.customer_id` zaten `nullable=False`). Bu da **sistem genelinde NULL/orphan customer_id teklifi sıfır** bulgusuyla (madde 5) tutarlı.

5. **Sistem geneli** (118 toplam teklif):
   - `customer_id` NULL olan teklif: **0**
   - Var olmayan müşteriye bağlı (orphan FK) teklif: **0**
   - Formdaki başlık ile bağlı müşteri adı "belirgin farklı" olan teklif: **24** (kaba sezgisel karşılaştırmayla) — ancak incelemede bunların **TAMAMININ** 2026-07 öncesi, "Is 3" değişikliğinden (teklif başlığı artık her zaman müşteri adından otomatik üretiliyor) ÖNCEKİ **eski kısaltma+tarih+sıra no** biçiminde olduğu görüldü (örn. `"SOLAKLAR AMBALJ-02.07-1"` vs müşteri `"Abdullah Solak Ambalaj"`) — bunlar gerçek bir yanlış-bağlantı DEĞİL, sadece eski/kısaltılmış başlık biçimi. **MİSS Kuruyemiş'in TKL-00090'ı bu 24'lük listede YOK** (başlığı zaten müşteri adıyla örtüşüyor, bağlantısı temiz). Bu 24 kaydın 14'ü `kazanilan` (siparişe dönmüş) ama hepsi aynı gerekçeyle (eski başlık biçimi) zararsız.
   - Mevcut mükerrer-kayıt tespiti (**Is 8**, `customer_detail()`'daki `duplicate_siblings`) **SADECE TELEFON NUMARASI** eşleşmesine bakıyor — customer 1825'in telefonu BOŞ olduğu için bu iki kayıt birbirini mükerrer olarak YAKALAMIYOR (telefon boşsa hiçbir şeyle eşleşmiyor). Bu, mevcut mükerrer-tespit özelliğinin BİLİNEN bir kör noktası (isim benzerliği değil, sadece telefon bazlı).

### 6. Öneri (YAPILMADI, sadece öneri)

a) **Teklif → doğru müşteri eşleşme tablosu**: Gerek yok — TKL-00090'ın bağlantısı zaten doğru (customer 1862). Asıl ihtiyaç, customer **1862** ve **1825**'in GERÇEKTEN aynı işletme olup olmadığının Serkan tarafından elle kontrol edilip, öyleyse mevcut "Mükerrer Kayıt Tespiti / elle birleştirme" (Is 8, `/customers/mukerrer`) özelliğiyle birleştirilmesi — bu özellik zaten var, sadece bu ikiliyi OTOMATİK bulamıyor (telefon boş).
b) **Bir daha olmaması için kod önerisi** (yapılmadı): Mükerrer-kayıt tespitine (Is 8) isim-benzerliği bazlı (ör. Levenshtein/fuzzy "MİSS..." vs "MİSSS..." gibi 1-2 karakterlik farkları yakalayan) ikinci bir kontrol eklenmesi, sadece telefon eşleşmesine güvenilmemesi — bu bir tasarım kararı gerektirir, Serkan'a bırakılır.
