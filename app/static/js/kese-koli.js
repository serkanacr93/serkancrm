/* 2026-10-26 (Is Emri): teklif kartindaki "Kese numarasi" + "Koli" alanlari.
 * - Kese secilince, Ayarlar > Teklif Yardimci'daki kese tablosunda olcusu
 *   varsa En/Boy/Korugu otomatik dolar.
 * - Ters yon: En/Boy/Korugu elle yazilinca tabloyla birebir eslesirse kese
 *   numarasi kendiliginden secilir; eslesmezse "Ozel olcu" kalir.
 * - Musteri secilince musterinin varsayilan kolisi, kullanicinin elle
 *   degistirmedigi kartlara uygulanir.
 * window.KESE_OLCU sayfada server tarafindan doldurulur (bkz. _kese_olcu_json).
 * Kart HTML'i _teklif_kart_fields.html ile AYNI (keseKoliHtml JS ile eklenen
 * yeni kartlar icin). */
(function () {
    var KATALOG = window.KESE_OLCU || [];
    window.KOLI_VARSAYILAN = window.KOLI_VARSAYILAN || 'baskili';

    function num(v) {
        if (v === null || v === undefined) return null;
        var s = String(v).trim().replace(',', '.');
        if (!/^\d+(\.\d+)?$/.test(s)) return null;
        return parseFloat(s);
    }
    function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;'); }

    window.keseKoliHtml = function (idx, secili, koli) {
        koli = koli || window.KOLI_VARSAYILAN || 'baskili';
        var opts = '<option value="">—</option>';
        KATALOG.forEach(function (k) {
            if (!k.aktif && String(secili) !== String(k.gramaj)) return;
            opts += '<option value="' + k.gramaj + '"' + (String(secili) === String(k.gramaj) ? ' selected' : '') + '>' + k.gramaj + ' gr</option>';
        });
        opts += '<option value="ozel">Özel ölçü</option>';
        return '<div class="tk-f tk-kesekoli"><div class="tk-kesekoli-ic">' +
            '<div class="tk-alt tk-alt-kese"><label class="tk-label">Kese numarası</label>' +
            '<select class="form-select form-select-sm" name="kese_gramaj_' + idx + '">' + opts + '</select>' +
            '<small class="tk-kese-not text-muted d-none"></small></div>' +
            '<div class="tk-alt tk-alt-koli"><label class="tk-label">Koli</label>' +
            '<div class="btn-group btn-group-sm" role="group">' +
            '<input type="radio" class="btn-check" name="koli_tipi_' + idx + '" id="koli_b_' + idx + '" value="baskili"' + (koli !== 'baskisiz' ? ' checked' : '') + '>' +
            '<label class="btn btn-outline-secondary" for="koli_b_' + idx + '">Firma baskılı</label>' +
            '<input type="radio" class="btn-check" name="koli_tipi_' + idx + '" id="koli_n_' + idx + '" value="baskisiz"' + (koli === 'baskisiz' ? ' checked' : '') + '>' +
            '<label class="btn btn-outline-warning" for="koli_n_' + idx + '">Baskısız</label>' +
            '</div></div></div></div>';
    };

    function kartAlani(kart, ad) { return kart.querySelector('[name^="' + ad + '_"]'); }

    function keseSecildi(sel) {
        var kart = sel.closest('.teklif-kart');
        if (!kart) return;
        var not = kart.querySelector('.tk-kese-not');
        if (not) { not.classList.add('d-none'); not.textContent = ''; }
        var g = sel.value;
        if (!g || g === 'ozel') return;
        var k = KATALOG.filter(function (x) { return String(x.gramaj) === g; })[0];
        if (!k) return;
        if (!k.en && !k.boy) {
            if (not) { not.textContent = 'Bu kese için ölçü tanımlı değil (Ayarlar > Teklif Yardımcı).'; not.classList.remove('d-none'); }
            return;
        }
        [['en', k.en], ['boy', k.boy], ['korugu', k.korugu]].forEach(function (p) {
            var el = kartAlani(kart, p[0]);
            if (el && p[1]) el.value = p[1];
        });
    }

    window.keseKoliEslestir = function (kart) {
        if (!kart) return;
        var sel = kart.querySelector('select[name^="kese_gramaj_"]');
        if (!sel) return;
        var en = num((kartAlani(kart, 'en') || {}).value);
        var boy = num((kartAlani(kart, 'boy') || {}).value);
        var kor = num((kartAlani(kart, 'korugu') || {}).value);
        if (en === null || boy === null) {
            if (sel.value && sel.value !== 'ozel' && en === null && boy === null) return;
            return;
        }
        var bulunan = KATALOG.filter(function (k) {
            return num(k.en) === en && num(k.boy) === boy && (kor === null || num(k.korugu) === null || num(k.korugu) === kor);
        })[0];
        if (bulunan) sel.value = String(bulunan.gramaj);
        else if (sel.value && sel.value !== 'ozel') sel.value = 'ozel';
    };

    document.addEventListener('change', function (e) {
        var t = e.target;
        if (t.matches && t.matches('select[name^="kese_gramaj_"]')) keseSecildi(t);
        if (t.matches && t.matches('input[name^="koli_tipi_"]')) {
            var kart = t.closest('.teklif-kart');
            if (kart) kart.dataset.koliElle = '1';
        }
    });
    document.addEventListener('input', function (e) {
        var t = e.target;
        if (t.matches && t.matches('input[name^="en_"], input[name^="boy_"], input[name^="korugu_"]')) {
            window.keseKoliEslestir(t.closest('.teklif-kart'));
        }
    });

    window.keseKoliMusteriVarsayilan = function (musteriId) {
        if (!musteriId) return;
        fetch('/api/customers/' + encodeURIComponent(musteriId) + '/varsayilan-koli', { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d) return;
                window.KOLI_VARSAYILAN = d.varsayilan_koli === 'baskisiz' ? 'baskisiz' : 'baskili';
                document.querySelectorAll('.teklif-kart').forEach(function (kart) {
                    if (kart.dataset.koliElle === '1') return;
                    var r = kart.querySelector('input[name^="koli_tipi_"][value="' + window.KOLI_VARSAYILAN + '"]');
                    if (r) r.checked = true;
                });
            })
            .catch(function () {});
    };
})();
