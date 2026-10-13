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
| 2026-10-13 | Teklif PDF Adım 1: notlar → Açıklama kutusu (yeni tasarım) + iç not alanı | — | **yarım** (sadece add_deal.html/edit_deal.html şablon değişikliği var, commit edilmedi; model/migration/route/pdf_utils.py tamamlanmadı) |
| 2026-10-13 | Canlı teslim denetimi + Teslim Kuralı (CLAUDE.md) | (bu commit) | branch'te (bu satırın eklendiği commit push edilince "canlıda" güncellenecek) |
