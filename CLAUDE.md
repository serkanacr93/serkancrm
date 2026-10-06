# CLAUDE.md - Lema Ambalaj CRM için kalıcı çalışma kuralları

Bu dosya, bu projede çalışan Claude Code oturumları için kalıcıdır - her yeni oturumda okunur. 2026-10-05'teki "tamam denen ama canlıda çalışmayan" bulgular sonrası eklendi.

## Tamamlanma kriteri (en önemli kural)

**Bir özellik, CANLI sitede (serkancrm.onrender.com) Playwright ile gerçek tarayıcıda açılıp, ilgili butonlara/modallara tıklanmadan ve tarayıcı konsolu temiz görülmeden "tamamlandı" sayılmaz.** Yerel test client (`app.test_client()`) ile yapılan testler değerlidir (mantık/veri doğruluğu için) ama JS çalışma zamanı hatalarını (script sıralaması, `ReferenceError`, event listener eksikliği) YAKALAYAMAZ - bu tür hatalar sadece gerçek bir tarayıcıda ortaya çıkar. Her iş raporunda "canlıda test edildi: evet/hayır" açıkça belirtilir.

## Sayfa JS'i nereye yazılır

Sayfaya özel `<script>` bloğu **content bloğuna değil**, `base.html`'deki bootstrap/Chart.js yüklemesinden SONRA çalışan `{% block scripts %}{% endblock %}` bloğuna (body'nin sonunda) yazılır:

```jinja
{% block content %}
...sayfa içeriği...
{% endblock %}

{% block scripts %}
<script>
// burada new bootstrap.Modal(), Chart() vb. güvenle kullanılabilir
</script>
{% endblock %}
```

**Neden:** `{% block content %}` sayfanın ortasında render edilir, bootstrap.bundle.min.js ise `base.html`'de body'nin sonuna yakın yüklenir. content bloğu içine yazılan ve sayfa yüklenir yüklenmez (senkron, event listener'a sarılmadan) `new bootstrap.Modal(...)` çağıran bir script, bootstrap kütüphanesi henüz tarayıcıya inmeden çalışır → `Uncaught ReferenceError: bootstrap is not defined`. Bu tam olarak 2026-10-05'te `/takip-modu` ve `/gecmis-kayit-duzeltme` sayfalarında yaşanan hataydı.

## Köklü değişiklik yasak

Mevcut tablo, alan, hesaplama ve sayfalar DEĞİŞTİRİLMEZ/SİLİNMEZ. Yeni özellik mevcut yapının YANINA eklenir (yeni alan, buton, sayfa, JS dosyası). Eklenen şey kapatılsa/geri alınsa bile sistem eskisi gibi çalışmalı. Yapı değişikliği (mevcut bir alanı/route'u kaldırma, mevcut bir hesaplamayı yeniden tanımlama) gerekiyorsa YAPILMAZ - raporda önerilir, karar kullanıcıya bırakılır. Yeni bir alan eklemeden önce AYNI amaca hizmet eden mevcut bir alan olup olmadığı kontrol edilir (örn. Deal.pesinat_tarihi/bakiye_tarihi zaten vardı - B7 isteği buna rastladığında yeni kolon açmak yerine mevcut kolon kullanılıp fark raporlandı).

## Kullanıcıyla netleşmemiş kararlar

Kullanıcı net bir talimat vermediği bir tasarım/iş kuralı kararında (örn. "irsaliye otomatik mi oluşsun yoksa hiç mi oluşmasın") kendi takdirini sessizce uygulama - mümkünse önce sor (AskUserQuestion), mümkün değilse/otonom modda isen kararını ver ama **raporda açıkça "istenenden farklı yapıldı" ya da "şu karar netleştirildi: X soruldu, Y cevabı alındı" yaz**. Sessizce farklı bir şey yapıp "tamamlandı" demek, kullanıcının bir sonraki oturumda aynı işi düzeltmek için tekrar zaman harcamasına yol açar.

## Yedekleme sistemi (ZATEN VAR - önce kontrol et)

`scripts\backup_neon.py` Neon veritabanının TAMAMINI (artık `information_schema`'dan OTOMATİK okunan tüm tablolar, `alembic_version` dahil) `C:\CRM_Yedekler\neon_backup_<tarih>.json` dosyasına yedekler, 30 günden eski yedekleri siler. Windows Görev Zamanlayıcı'da `CRM_Neon_Backup` adıyla kayıtlı (oturum açılışında + her gün 03:30'da çalışacak şekilde 2026-10-06'da düzeltildi - eskiden SADECE oturum açılışında çalışıyordu ve "kaçırılan görevi çalıştır" kapalıydı, bu yüzden 10 gün yedeksiz kalınmıştı).

**Kural: Büyük/riskli bir işe (çok sayıda gerçek kayıt değişikliği, migration, toplu silme/birleştirme vb.) başlamadan önce `C:\CRM_Yedekler` içindeki en son yedek dosyasının tarihi kontrol edilir - 24 saatten eskiyse `python scripts\backup_neon.py --force` çalıştırılır; yedek hiç alınamıyorsa (DATABASE_URL yok, bağlantı hatası vb.) işe BAŞLANMAZ, kullanıcıya bildirilir.**

**Bilinen sınırlama:** Görev Zamanlayıcı'daki görev ayarlarını (tetikleyici, "kaçırılan görevi çalıştır" vb.) değiştirmek bu ortamda ADMIN YETKİSİ gerektiriyor - Claude Code oturumu bunu değiştiremez, sadece tespit edip kullanıcıya XML/talimat halinde bırakabilir.

## Güvenlik ve veri kuralları (her oturumda geçerli)

- Gerçek müşteri, teklif, üretim, fatura, ödeme kaydı **SİLİNMEZ/DEĞİŞTİRİLMEZ**. Testler sadece adı `TEST` ile başlayan kayıtlarla yapılır, iş bitince silinir; gerçek kayıt sayıları test öncesi/sonrası karşılaştırılıp raporlanır.
- `Payment` tablosundaki gerçek kayıtlara dokunulmaz.
- Zayıf şifreli kullanıcıların şifresi değiştirilmez/silinmez - sadece raporlanır, karar kullanıcıya bırakılır.
- Render/Neon ayarlarına dokunulmaz, force push yapılmaz, secret commit edilmez, `.env`/credential dosyaları commit edilmez.
- Migration gerekiyorsa Neon'a uygulanır, mevcut veri bozulmaz (bkz. aşağıdaki `db.create_all()` çakışma notu).
- Kota yetmezse yarım bırakma raporu verilir: nerede kalındığı, kalan işler, sonraki adımlar.

## Bilinen teknik borç

- `db.create_all()` ile Flask-Migrate arasında çakışma riski var - yeni tablo eklerken `db.create_all()` tabloyu migration'dan önce oluşturup Alembic senkronizasyonunu bozabiliyor (`DuplicateTable` hatası). Çözüm: migration dosyasını elle `upgrade(): pass` ile yaz, `flask db stamp head` ile işaretle, gerçek DDL çalıştırma.
- Cari bakiye HER ZAMAN `calculate_customer_balance()` / `Customer.balance` property'si üzerinden hesaplanır (faturalanmış + faturalanmamış kazanılan - tahsilat) - ikinci/farklı bir hesaplama yolu AÇILMAZ.
- 60 günlük takip sayacı `_last_contact_subquery()` üzerinden hesaplanır - `DailyReport.status in ('ulasilamadi', 'sonra_ara')` olan kayıtlar kasıtlı olarak hariç tutulur (gerçek irtibat sayılmaz).

## Her işin sonunda

1. `tests/smoke_test.py` canlıda (`--url https://serkancrm.onrender.com`) çalıştırılır; tablo temiz değilse "tamam" denmez.
2. Varsa migration Neon'a uygulanmış, test verisi temizlenmiş olmalı.
3. Değişiklik ayrı bir commit ile kayda geçirilir (anlamlı commit mesajı, Türkçe).
