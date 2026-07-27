/* Site genelinde tek, merkezi musteri arama bileseni (Katman 1 / Is 1).
 * Turkce karakter normalizasyonu backend'de (_normalize_tr) yapiliyor,
 * bu dosya sadece arama kutusu -> /api/customers/search -> sonuc listesi
 * akisini yonetir. Tum musteri secim noktalarinda (teklif, gunluk rapor,
 * odeme, ziyaret, gorev, teklif duzenleme) ayni davranisi saglar. */

function _customerSearchCore(input, hiddenInput, resultsEl, opts) {
    opts = opts || {};
    var minLength = opts.minLength || 2;
    var timeout;

    input.addEventListener('input', function () {
        clearTimeout(timeout);
        var query = this.value.trim();
        hiddenInput.value = '';
        if (typeof opts.onClear === 'function') opts.onClear();
        if (query.length < minLength) {
            resultsEl.style.display = 'none';
            resultsEl.innerHTML = '';
            return;
        }
        timeout = setTimeout(function () {
            fetch('/api/customers/search?q=' + encodeURIComponent(query))
                .then(function (res) { return res.json(); })
                .then(function (data) {
                    resultsEl.innerHTML = '';
                    if (data.length === 0) {
                        resultsEl.innerHTML = '<div class="list-group-item text-muted small">Sonuç bulunamadı</div>';
                        resultsEl.style.display = 'block';
                        return;
                    }
                    data.forEach(function (c) {
                        var item = document.createElement('a');
                        item.href = '#';
                        item.className = 'list-group-item list-group-item-action py-1';
                        var companyLine = c.company_name ? (c.company_name + ' - ') : '';
                        var contactBits = [c.phone, c.email].filter(Boolean).join(' | ');
                        item.innerHTML = '<strong>' + companyLine + c.name + '</strong>' +
                            (contactBits ? '<br><small class="text-muted">' + contactBits + '</small>' : '');
                        item.addEventListener('click', function (e) {
                            e.preventDefault();
                            input.value = c.name;
                            hiddenInput.value = c.id;
                            resultsEl.style.display = 'none';
                            if (typeof opts.onSelect === 'function') opts.onSelect(c);
                        });
                        resultsEl.appendChild(item);
                    });
                    resultsEl.style.display = 'block';
                });
        }, 300);
    });

    document.addEventListener('click', function (e) {
        if (!input.contains(e.target) && !resultsEl.contains(e.target)) {
            resultsEl.style.display = 'none';
        }
    });
}

/* Tek ornekli formlar icin: id'lere gore elemanlari bulup arar baglar. */
function initCustomerSearch(config) {
    var input = document.getElementById(config.inputId);
    var hiddenInput = document.getElementById(config.hiddenIdInputId);
    var resultsEl = document.getElementById(config.resultsId);
    if (!input || !hiddenInput || !resultsEl) return;
    _customerSearchCore(input, hiddenInput, resultsEl, config);
}

/* Tekrarlanan satirlar icin (orn. gunluk rapor - + ile satir eklenen
 * formlar): dogrudan DOM elemanlari verilir, id gerekmez. */
function initCustomerSearchRow(input, hiddenInput, resultsEl, opts) {
    _customerSearchCore(input, hiddenInput, resultsEl, opts || {});
}
