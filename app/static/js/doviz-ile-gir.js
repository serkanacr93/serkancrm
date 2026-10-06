/* B5d (2026-10-06) - Teklif satirindaki "Birim Fiyat" alaninin yanina
 * kucuk bir "$/€/£ ile gir" dugmesi ekler. AYRI dosya, mevcut satir/
 * hesaplama/kaydetme alanlarina DOKUNMAZ - sadece price input'un
 * DEGERINI (tam hassasiyetle) yazar ve price-input'a 'input' event'i
 * dispatch eder (mevcut calculateTotals() bunu zaten dinliyor).
 * teklif-yardimci.js'ten BAGIMSIZDIR - Kese/Doypack kapali olsa da
 * calisir. */
(function () {
    var RATE_CACHE = {};

    function fetchRate(currency) {
        if (currency === 'TRY') return Promise.resolve(1.0);
        if (RATE_CACHE[currency] !== undefined) return Promise.resolve(RATE_CACHE[currency]);
        return fetch('/api/tcmb-rate?currency=' + currency, { credentials: 'same-origin' })
            .then(function (res) { return res.ok ? res.json() : Promise.reject(); })
            .then(function (data) {
                RATE_CACHE[currency] = data.rate;
                return data.rate;
            });
    }

    function tekliTeklifCurrency() {
        var sel = document.getElementById('para_birimi');
        return sel ? sel.value : 'TRY';
    }

    function buildPopover(priceInput) {
        var pop = document.createElement('div');
        pop.className = 'doviz-ile-gir-popover card shadow-sm p-2';
        pop.style.position = 'absolute';
        pop.style.zIndex = '1050';
        pop.style.minWidth = '220px';
        pop.innerHTML =
            '<div class="d-flex gap-1 mb-1">' +
            '<select class="form-select form-select-sm" style="width:70px;">' +
            '<option value="USD">$</option><option value="EUR">€</option><option value="GBP">£</option>' +
            '</select>' +
            '<input type="number" step="any" class="form-control form-control-sm" placeholder="Tutar">' +
            '</div>' +
            '<div class="small text-muted doviz-note mb-1"></div>' +
            '<div class="d-flex gap-1">' +
            '<button type="button" class="btn btn-sm btn-primary flex-grow-1 doviz-apply">Uygula</button>' +
            '<button type="button" class="btn btn-sm btn-outline-secondary doviz-cancel">Vazgeç</button>' +
            '</div>';
        document.body.appendChild(pop);

        var rect = priceInput.getBoundingClientRect();
        pop.style.top = (rect.bottom + window.scrollY + 2) + 'px';
        pop.style.left = (rect.left + window.scrollX) + 'px';

        var curSelect = pop.querySelector('select');
        var amountInput = pop.querySelector('input');
        var note = pop.querySelector('.doviz-note');

        function close() { pop.remove(); }

        pop.querySelector('.doviz-cancel').addEventListener('click', close);
        document.addEventListener('mousedown', function outsideClick(e) {
            if (!pop.contains(e.target)) { close(); document.removeEventListener('mousedown', outsideClick); }
        });

        pop.querySelector('.doviz-apply').addEventListener('click', function () {
            var amount = parseFloat(amountInput.value);
            if (!amount || amount <= 0) { note.textContent = 'Geçerli bir tutar girin.'; return; }
            var selectedCurrency = curSelect.value;
            var teklifCurrency = tekliTeklifCurrency();
            note.textContent = 'Kur alınıyor...';

            Promise.all([fetchRate(selectedCurrency), fetchRate(teklifCurrency)])
                .then(function (rates) {
                    var rateSelected = rates[0];
                    var rateTeklif = rates[1];
                    if (!rateSelected || !rateTeklif) {
                        note.textContent = 'TCMB kuru şu an alınamadı, elle girebilirsiniz.';
                        return;
                    }
                    // amount (secilen doviz) -> TL -> teklif para birimi
                    var converted = amount * rateSelected / rateTeklif;
                    priceInput.value = converted;
                    priceInput.dispatchEvent(new Event('input', { bubbles: true }));

                    var symbolMap = { USD: '$', EUR: '€', GBP: '£', TRY: '₺' };
                    var noteText = amount.toString().replace('.', ',') + symbolMap[selectedCurrency] +
                        ' × ' + rateSelected.toFixed(4).replace('.', ',') + ' kur ile girildi';
                    showPriceNote(priceInput, noteText);
                    close();
                })
                .catch(function () {
                    note.textContent = 'Bağlantı hatası, tekrar deneyin.';
                });
        });

        amountInput.focus();
    }

    function showPriceNote(priceInput, text) {
        var row = priceInput.closest('tr') || priceInput.closest('.item-row');
        if (!row) return;
        var specsRow = row.nextElementSibling;
        if (!specsRow) return;
        var container = specsRow.tagName === 'TR' ? specsRow.querySelector('td') : specsRow;
        if (!container) return;
        var note = container.querySelector('.doviz-ile-gir-note');
        if (!note) {
            note = document.createElement('div');
            note.className = 'doviz-ile-gir-note small text-info mt-1';
            container.appendChild(note);
        }
        note.textContent = text;
    }

    function attachButton(priceInput) {
        if (priceInput.dataset.dovizBtnAttached) return;
        priceInput.dataset.dovizBtnAttached = '1';
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-sm btn-outline-info doviz-ile-gir-btn';
        btn.title = '$/€/£ ile gir';
        btn.textContent = '💱';
        btn.style.marginLeft = '2px';
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            document.querySelectorAll('.doviz-ile-gir-popover').forEach(function (p) { p.remove(); });
            buildPopover(priceInput);
        });
        priceInput.insertAdjacentElement('afterend', btn);
    }

    function scanAndAttach() {
        document.querySelectorAll('input[name^="price_"]').forEach(attachButton);
    }

    document.addEventListener('DOMContentLoaded', function () {
        if (!document.getElementById('para_birimi')) return; // bu sayfa teklif formu degil
        scanAndAttach();
        // Yeni satir eklendiginde (mevcut "Urun Ekle" butonu) otomatik yakalamak icin
        var container = document.getElementById('items-table') || document.getElementById('items-container');
        if (container && window.MutationObserver) {
            new MutationObserver(scanAndAttach).observe(container, { childList: true, subtree: true });
        }
    });
})();
