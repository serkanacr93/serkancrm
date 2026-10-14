# Görev Kaydı

Her görev tamamlandığında (veya yarım/branch'te kaldığında) buraya tek satır eklenir: tarih | görev adı | commit | durum (canlıda / branch'te / yarım).

Bu dosya 2026-10-13 denetimi sırasında, denetimde incelenen A–I maddelerinin ilk kayıtları olarak oluşturuldu (geçmişe dönük, denetim bulgularına göre).

| Tarih | Görev | Commit | Durum |
|---|---|---|---|
| 2026-10-07 | Günlük Üretim: toplam kg düzeltmesi + görsel yenileme | `285d713`, `3988778` | canlıda (yerelde doğrulandı, canlı erişim bu oturumda engellendi) |
| 2026-10-06 | Takip Modu: sıralama/eşik/otomatik kapanma/kalıcı Atla | `77ff31c` | canlıda (yerelde doğrulandı) |
| 2026-10-08 | Google Places: ücretsiz kota sert kilidi (800/ay, 30/gün) | `d9e0d2f` | canlıda (yerelde doğrulandı) |
| 2026-10-08 | Komuta Merkezi + Siparişler sekmesi + /siparisler | `85d6518` | canlıda (yerelde doğrulandı) |
| — | Gece Modu GÖREV 1: manuel irsaliye düzenleme + faturayla eşitleme | — | **yapılmadı** (commit yok, kodda iz yok) |
| — | Gece Modu GÖREV 2: teklif formu yenileme + döviz Aşama 1 (F1–F6) | — | **yapılmadı** (bazı alt maddeler F2/F4 başka, ilgisiz işlerden zaten var; F1 kısmen; F3/F5/F6 yok) |
| 2026-10-13 | Teklif PDF yeni tasarım (logo renkleri, Klasik/Yeni, ödeme yöntemi, TCMB kur notu) | `bf50de8`, `b8dc8f4` | canlıda (push edildi, yerelde doğrulandı, canlı girişli doğrulama bu oturumda engellendi) |
| 2026-10-13 | Canlı teslim denetimi + Teslim Kuralı (CLAUDE.md) | `51862b4` | canlıda (push edildi) |
| 2026-10-14 | PAKET A İş 1: notlar → Açıklama kutusu (yeni tasarım) + iç not alanı (yarım kalan iş tamamlandı) | `3ecbb09` | CANLIDA DOĞRULANMADI (giriş engelli, yerelde ✅) |
| 2026-10-14 | PAKET A İş 2: yeni tasarımda küçük düzeltmeler (Ürün tipi kaldırma, Numune gizleme, TR sayı biçimi) | `e31b7e7` | CANLIDA DOĞRULANMADI (giriş engelli, yerelde ✅) |
| 2026-10-14 | PAKET A İş 3: Ödeme Şekli yeniden tasarım (%/TL peşinat, sayısal vade, otomatik bakiye) | `699c131` | CANLIDA DOĞRULANMADI (giriş engelli, yerelde ✅) |
| 2026-10-14 | PAKET A İş 4: MİSS Kuruyemiş teşhisi (salt okuma) — sonuç: mükerrer müşteri kaydı, bağlantı bozuk değil | — (kod değişikliği yok, sadece rapor) | n/a |
| 2026-10-14 | PAKET B İş B1: Havale/EFT seçilince IBAN önizleme (mavi kutu) + PDF'de sarı IBAN kutusu (TR+EN, yeni tasarım) | `d48e1f2` | CANLIDA DOĞRULANMADI (giriş engelli, yerelde ✅) |
| 2026-10-14 | PAKET B İş B2: Manuel irsaliye düzenleme + faturayla iki yönlü eşitleme + fark raporu + kilit (muhasebeye gönderildi) | `c3ebec3` | CANLIDA DOĞRULANMADI (giriş engelli, yerelde ✅) |
| 2026-10-14 | PAKET B İş B3: Teklif formunda numaralı ürün kartları (CompanySettings.teklif_formu_gorunumu, Kart/Eski Tablo) | `168b642`, `1213ed1` | CANLIDA DOĞRULANMADI (giriş engelli, yerelde ✅ — kart/tablo veri özdeşliği, Kese/Doypack Seç, mobil, Eski Tablo tüm testleri geçti) |
| 2026-10-14 | PAKET B İş B4: Kalem bazında döviz Aşama 1 (DealItem.para_birimi, Deal.kur_usd/kur_eur/kur_tarihi/kur_turu, TCMB kur bandı, PDF) | `1527ab1` | CANLIDA DOĞRULANMADI (giriş engelli, yerelde ✅ — 118 eski teklifte 0 uyumsuzluk, Eski Tablo dokunulmadı, gating/revize/PDF test edildi) |
| 2026-10-14 | PAKET B İş B5: İngilizce teklif PDF'i (yeni tasarım, ?lang=en + "PDF İndir (EN)" butonu, Klasik dokunulmadı) | `4b8cade` | CANLIDA DOĞRULANMADI (giriş engelli, yerelde ✅ — 118 teklifte TR+EN PDF hatasız, TR çıktı değişmedi, B4 entegrasyonu test edildi) |
