/* Site genelinde tek, merkezi musteri arama bileseni (Katman 1 / Is 1).
 * Turkce karakter normalizasyonu backend'de (_normalize_tr) yapiliyor,
 * bu dosya sadece arama kutusu -> /api/customers/search -> sonuc listesi
 * akisini yonetir. Tum musteri secim noktalarinda (teklif, gunluk rapor,
 * odeme, ziyaret, gorev, teklif duzenleme) ayni davranisi saglar. */

function _customerSearchCore(input, hiddenInput, resultsEl, opts) {
    opts = opts || {};
    var minLength = opts.minLength || 2;
    var timeout;

    function selectCustomer(c) {
        input.value = c.name;
        hiddenInput.value = c.id;
        resultsEl.style.display = 'none';
        if (typeof opts.onSelect === 'function') opts.onSelect(c);
    }

    function renderQuickAdd(query) {
        resultsEl.innerHTML = '';
        var msg = document.createElement('div');
        msg.className = 'list-group-item text-muted small';
        msg.textContent = '"' + query + '" ile eşleşen müşteri bulunamadı.';
        resultsEl.appendChild(msg);

        if (!opts.allowQuickAdd) {
            resultsEl.style.display = 'block';
            return;
        }

        var looksLikePhone = /^[0-9 ()+-]+$/.test(query) && /\d/.test(query);
        var wrap = document.createElement('div');
        wrap.className = 'list-group-item p-2';
        wrap.innerHTML =
            '<div class="small fw-bold mb-1"><i class="bi bi-person-plus"></i> Yeni müşteri olarak ekle</div>' +
            '<div class="d-flex gap-1 mb-1">' +
            '<input type="text" class="form-control form-control-sm qa-name" placeholder="İsim">' +
            '<input type="text" class="form-control form-control-sm qa-phone" placeholder="Telefon">' +
            '</div>' +
            '<div class="qa-error small text-danger mb-1" style="display:none;"></div>' +
            '<button type="button" class="btn btn-sm btn-success w-100 qa-submit"><i class="bi bi-check-lg"></i> Ekle ve Seç</button>';

        var nameInput = wrap.querySelector('.qa-name');
        var phoneInput = wrap.querySelector('.qa-phone');
        var errorEl = wrap.querySelector('.qa-error');
        var submitBtn = wrap.querySelector('.qa-submit');

        if (looksLikePhone) {
            phoneInput.value = query;
        } else {
            nameInput.value = query;
        }

        function stopRow(e) { e.stopPropagation(); }
        wrap.addEventListener('click', stopRow);
        wrap.addEventListener('mousedown', stopRow);

        submitBtn.addEventListener('click', function () {
            var name = nameInput.value.trim();
            var phone = phoneInput.value.trim();
            errorEl.style.display = 'none';
            if (!name && !phone) {
                errorEl.textContent = 'İsim veya telefon numarasından en az biri gerekli.';
                errorEl.style.display = 'block';
                return;
            }
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Ekleniyor...';
            var csrfInput = input.closest('form') ? input.closest('form').querySelector('input[name=csrf_token]') : document.querySelector('input[name=csrf_token]');
            fetch('/api/customers/quick-add', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfInput ? csrfInput.value : ''
                },
                body: JSON.stringify({ name: name, phone: phone })
            })
                .then(function (res) { return res.json().then(function (body) { return { ok: res.ok, body: body }; }); })
                .then(function (r) {
                    if (!r.ok) {
                        errorEl.textContent = r.body.error || 'Müşteri eklenemedi.';
                        errorEl.style.display = 'block';
                        submitBtn.disabled = false;
                        submitBtn.innerHTML = '<i class="bi bi-check-lg"></i> Ekle ve Seç';
                        return;
                    }
                    selectCustomer(r.body);
                    if (typeof opts.onQuickAdd === 'function') opts.onQuickAdd(r.body);
                })
                .catch(function () {
                    errorEl.textContent = 'Bağlantı hatası, tekrar deneyin.';
                    errorEl.style.display = 'block';
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = '<i class="bi bi-check-lg"></i> Ekle ve Seç';
                });
        });

        resultsEl.appendChild(wrap);
        resultsEl.style.display = 'block';
    }

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
                        renderQuickAdd(query);
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
                            selectCustomer(c);
                        });
                        resultsEl.appendChild(item);
                    });
                    resultsEl.style.display = 'block';
                });
        }, 150);
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
