/* Site genelinde tek, merkezi musteri arama bileseni (Is 6 - Aninda
 * Musteri Arama, tarayici icinde). ONCEKI surum her tus basisinda
 * /api/customers/search'e sunucu istegi atiyordu (300-900ms Neon RTT'si,
 * yaris durumu riski). Bu surum /api/customers/summary'yi SAYFA
 * ACILISINDA BIR KEZ (ETag ile - degismediyse tarayici 304 alir, veri
 * localStorage'dan kullanilir) cekip TUM aramayi tarayicida yapar - hic
 * ag istegi olmadan, Turkce karakter/kelime sirasi/kucuk yazim hatasi
 * toleransli. Public API (initCustomerSearch/initCustomerSearchRow ve
 * config sekli) ONCEKI surumle AYNI - 9 formdaki cagrı siteleri
 * degismeden calisir. */

/* Sayfa uzun sure acik kaldiginda CSRF token suresi dolabiliyordu -
 * submit aninda taze bir token cekmek bunu onler (quick-add akisinda
 * kullanilir, degismedi). */
function _freshCsrfToken(fallbackInput) {
    return fetch('/api/csrf-token', { credentials: 'same-origin' })
        .then(function (res) { return res.ok ? res.json() : Promise.reject(); })
        .then(function (data) { return data.csrf_token; })
        .catch(function () { return fallbackInput ? fallbackInput.value : ''; });
}

function _parseJsonResponse(res) {
    return res.json()
        .then(function (body) { return { ok: res.ok, body: body }; })
        .catch(function () {
            return { ok: false, body: { error: 'Oturum süresi dolmuş olabilir. Sayfayı yenileyip tekrar deneyin.' } };
        });
}

/* ===== Is 6: tarayici-ici veri onbellegi + bulanik arama motoru ===== */
var CRM_SEARCH = (function () {
    var STORAGE_KEY = 'crm_customers_v1';
    var RECENT_KEY = 'crm_recent_customers_v1';
    var cache = { etag: null, data: null };
    var loadPromise = null;

    var TR_FOLD = {
        'ş': 's', 'Ş': 's', 'ğ': 'g', 'Ğ': 'g', 'ü': 'u', 'Ü': 'u',
        'ö': 'o', 'Ö': 'o', 'ç': 'c', 'Ç': 'c', 'ı': 'i', 'İ': 'i', 'I': 'i'
    };

    function foldTr(s) {
        if (!s) return '';
        var out = '';
        for (var i = 0; i < s.length; i++) {
            var ch = s[i];
            out += TR_FOLD[ch] || ch;
        }
        return out.toLowerCase();
    }

    function normalizePhoneDigits(raw) {
        var digits = (raw || '').replace(/\D/g, '');
        if (digits.indexOf('90') === 0 && digits.length === 12) return digits;
        if (digits.indexOf('0') === 0 && digits.length === 11) return '90' + digits.slice(1);
        if (digits.length === 10) return '90' + digits;
        return digits;
    }

    function levenshtein(a, b) {
        if (a === b) return 0;
        var al = a.length, bl = b.length;
        if (al === 0) return bl;
        if (bl === 0) return al;
        if (Math.abs(al - bl) > 2) return 99; // erken cikis - zaten cok farkli uzunlukta
        var prev = new Array(bl + 1);
        var curr = new Array(bl + 1);
        for (var j = 0; j <= bl; j++) prev[j] = j;
        for (var i = 1; i <= al; i++) {
            curr[0] = i;
            for (var k = 1; k <= bl; k++) {
                var cost = a[i - 1] === b[k - 1] ? 0 : 1;
                curr[k] = Math.min(prev[k] + 1, curr[k - 1] + 1, prev[k - 1] + cost);
            }
            var tmp = prev; prev = curr; curr = tmp;
        }
        return prev[bl];
    }

    /* Bir token'in bir metin icinde (kelime bazinda) fuzzy-gectigini
     * kontrol eder: tam alt-dize ise direkt gecer; degilse (>=4 karakterli
     * tokenlar icin) metnin kelimelerinden biriyle duzenleme uzakligi
     * <=1 ise de gecer ("ceylna" -> "ceylan" gibi kucuk yazim hatalari). */
    function fuzzyTokenInText(token, text, words) {
        if (text.indexOf(token) !== -1) return true;
        if (token.length < 4) return false;
        for (var i = 0; i < words.length; i++) {
            var w = words[i];
            if (Math.abs(w.length - token.length) <= 1 && levenshtein(token, w) <= 1) return true;
        }
        return false;
    }

    function buildIndex(customer) {
        var nameFold = foldTr(customer.name);
        var companyFold = foldTr(customer.company_name);
        var oldNamesFold = (customer.old_names || []).map(foldTr);
        var combinedText = [nameFold, companyFold, foldTr(customer.city), foldTr(customer.musteri_no),
            foldTr(customer.tax_id)].concat(oldNamesFold).join(' ');
        var words = combinedText.split(/\s+/).filter(Boolean);
        return {
            c: customer,
            nameFold: nameFold,
            companyFold: companyFold,
            combinedText: combinedText,
            words: words,
            phoneDigits: normalizePhoneDigits(customer.phone)
        };
    }

    function load(forceRefresh) {
        if (loadPromise && !forceRefresh) return loadPromise;
        var stored = null;
        try {
            var raw = localStorage.getItem(STORAGE_KEY);
            if (raw) stored = JSON.parse(raw);
        } catch (e) { /* localStorage erisilemez (ozel pencere vb.) - sorun degil, sunucudan cekilir */ }

        var headers = {};
        if (stored && stored.etag) headers['If-None-Match'] = stored.etag;

        loadPromise = fetch('/api/customers/summary', { headers: headers, credentials: 'same-origin' })
            .then(function (res) {
                if (res.status === 304 && stored) {
                    cache.etag = stored.etag;
                    cache.data = stored.data.map(buildIndex);
                    return cache.data;
                }
                return res.json().then(function (data) {
                    var etag = res.headers.get('ETag');
                    cache.etag = etag;
                    cache.data = data.map(buildIndex);
                    try {
                        localStorage.setItem(STORAGE_KEY, JSON.stringify({ etag: etag, data: data }));
                    } catch (e) { /* kota asimi vb. - sadece bellek-ici onbellek kullanilir */ }
                    return cache.data;
                });
            })
            .catch(function () {
                // Ag hatasi - localStorage'daki eski veri varsa onu kullan, yoksa bos liste
                if (stored) {
                    cache.data = stored.data.map(buildIndex);
                    return cache.data;
                }
                return [];
            });
        return loadPromise;
    }

    function getRecentIds() {
        try {
            return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]');
        } catch (e) { return []; }
    }

    function trackRecent(id) {
        try {
            var list = getRecentIds().filter(function (x) { return x !== id; });
            list.unshift(id);
            localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, 20)));
        } catch (e) { /* onemsiz */ }
    }

    /* query icin en iyi N eslesmeyi doner, [{customer, score, matchStart}] -
     * matchStart vurgulama icin kullanilir (nameFold icindeki ilk eslesme
     * konumu, -1 ise vurgulanacak tek bir nokta yok - kelime bazinda eslesmis). */
    function search(query, opts) {
        opts = opts || {};
        var currentUserId = opts.currentUserId;
        var limit = opts.limit || 20;
        if (!cache.data) return [];

        var qFold = foldTr(query.trim());
        if (!qFold) return [];
        var isPhoneLike = /^[0-9 ()+-]+$/.test(query.trim()) && /\d/.test(query);
        var qPhoneDigits = isPhoneLike ? normalizePhoneDigits(query) : null;
        var tokens = qFold.split(/\s+/).filter(Boolean);
        var recentIds = getRecentIds();

        var results = [];
        for (var i = 0; i < cache.data.length; i++) {
            var idx = cache.data[i];
            var matched = false;
            var exact = false;
            var startsWith = false;

            if (qPhoneDigits && qPhoneDigits.length >= 7 && idx.phoneDigits.indexOf(qPhoneDigits) !== -1) {
                matched = true;
            } else {
                matched = true;
                for (var t = 0; t < tokens.length; t++) {
                    if (!fuzzyTokenInText(tokens[t], idx.combinedText, idx.words)) {
                        matched = false;
                        break;
                    }
                }
            }
            if (!matched) continue;

            exact = idx.nameFold === qFold || idx.companyFold === qFold;
            startsWith = !exact && (idx.nameFold.indexOf(qFold) === 0 || idx.companyFold.indexOf(qFold) === 0);

            var quality = exact ? 0 : (startsWith ? 1 : 2);
            var isOwn = currentUserId && idx.c.owner_user_id === currentUserId;
            var recentPos = recentIds.indexOf(idx.c.id);
            var score = quality * 100 + (isOwn ? 0 : 10) + (recentPos === -1 ? 5 : recentPos * 0.1);

            results.push({ customer: idx.c, score: score, matchPos: idx.nameFold.indexOf(qFold) });
        }

        results.sort(function (a, b) { return a.score - b.score; });
        return results.slice(0, limit).map(function (r) { return r.customer; });
    }

    return { load: load, search: search, trackRecent: trackRecent, foldTr: foldTr };
})();

function _highlightMatch(text, query) {
    if (!text || !query) return text;
    var folded = CRM_SEARCH.foldTr(text);
    var qFolded = CRM_SEARCH.foldTr(query.trim());
    var pos = qFolded ? folded.indexOf(qFolded) : -1;
    if (pos === -1) return text;
    return text.slice(0, pos) + '<mark>' + text.slice(pos, pos + qFolded.length) + '</mark>' + text.slice(pos + qFolded.length);
}

function _customerSearchCore(input, hiddenInput, resultsEl, opts) {
    opts = opts || {};
    var minLength = opts.minLength || 2;
    var activeIndex = -1;
    var currentResults = [];
    var currentQuery = '';

    CRM_SEARCH.load();

    function selectCustomer(c) {
        input.value = c.name;
        hiddenInput.value = c.id;
        resultsEl.style.display = 'none';
        activeIndex = -1;
        CRM_SEARCH.trackRecent(c.id);
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
            _freshCsrfToken(csrfInput).then(function (token) {
                return fetch('/api/customers/quick-add', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': token
                    },
                    body: JSON.stringify({ name: name, phone: phone })
                });
            })
                .then(_parseJsonResponse)
                .then(function (r) {
                    if (!r.ok) {
                        errorEl.textContent = r.body.error || 'Müşteri eklenemedi.';
                        errorEl.style.display = 'block';
                        submitBtn.disabled = false;
                        submitBtn.innerHTML = '<i class="bi bi-check-lg"></i> Ekle ve Seç';
                        return;
                    }
                    CRM_SEARCH.load(true); // yeni musteri eklendi - onbellegi tazele
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

    function renderResults(customers, query) {
        currentResults = customers;
        currentQuery = query;
        activeIndex = -1;
        resultsEl.innerHTML = '';
        if (customers.length === 0) {
            renderQuickAdd(query);
            return;
        }
        customers.forEach(function (c, i) {
            var item = document.createElement('a');
            item.href = '#';
            item.className = 'list-group-item list-group-item-action py-1';
            item.dataset.idx = i;
            var companyLine = c.company_name ? (_highlightMatch(c.company_name, query) + ' - ') : '';
            var subBits = [c.musteri_no, c.city, c.phone].filter(Boolean).join(' · ');
            // Is 8: eslesme ne name'de ne company_name'de bulunamadiysa ama
            // old_names'den birinde varsa, "eski adi: ..." etiketi goster -
            // boylece birlestirilmis bir kaydin eski ismiyle bulunabilmesi
            // kullaniciya acikca gosterilir.
            var oldNameMatch = null;
            if ((c.old_names || []).length) {
                var qFold = CRM_SEARCH.foldTr(query.trim());
                var nameHasIt = CRM_SEARCH.foldTr(c.name).indexOf(qFold) !== -1 ||
                    CRM_SEARCH.foldTr(c.company_name || '').indexOf(qFold) !== -1;
                if (!nameHasIt) {
                    oldNameMatch = c.old_names.find(function (on) { return CRM_SEARCH.foldTr(on).indexOf(qFold) !== -1; });
                }
            }
            item.innerHTML = '<strong>' + companyLine + _highlightMatch(c.name, query) + '</strong>' +
                (subBits ? '<br><small class="text-muted">' + subBits + '</small>' : '') +
                (oldNameMatch ? '<br><small class="text-muted">eski adı: ' + _highlightMatch(oldNameMatch, query) + '</small>' : '');
            item.addEventListener('mousedown', function (e) {
                e.preventDefault();
                selectCustomer(c);
            });
            resultsEl.appendChild(item);
        });
        resultsEl.style.display = 'block';
    }

    function setActive(newIndex) {
        var items = resultsEl.querySelectorAll('.list-group-item-action');
        if (items.length === 0) return;
        items.forEach(function (el) { el.classList.remove('active'); });
        if (newIndex < 0) newIndex = items.length - 1;
        if (newIndex >= items.length) newIndex = 0;
        activeIndex = newIndex;
        items[activeIndex].classList.add('active');
        items[activeIndex].scrollIntoView({ block: 'nearest' });
    }

    function runSearch(query) {
        CRM_SEARCH.load().then(function () {
            var uid = opts.currentUserId || window.CRM_CURRENT_USER_ID;
            var results = CRM_SEARCH.search(query, { currentUserId: uid });
            renderResults(results, query);
        });
    }

    input.addEventListener('input', function () {
        var query = this.value.trim();
        hiddenInput.value = '';
        if (typeof opts.onClear === 'function') opts.onClear();
        if (query.length < minLength) {
            resultsEl.style.display = 'none';
            resultsEl.innerHTML = '';
            return;
        }
        runSearch(query);
    });

    input.addEventListener('keydown', function (e) {
        if (resultsEl.style.display === 'none' || !currentResults.length) return;
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            setActive(activeIndex + 1);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setActive(activeIndex - 1);
        } else if (e.key === 'Enter') {
            if (activeIndex >= 0 && currentResults[activeIndex]) {
                e.preventDefault();
                selectCustomer(currentResults[activeIndex]);
            }
        } else if (e.key === 'Escape') {
            resultsEl.style.display = 'none';
            input.blur();
        }
    });

    var outsideContainer = opts.clickOutsideContainer || null;
    document.addEventListener('click', function (e) {
        var inside = input.contains(e.target) || resultsEl.contains(e.target) ||
            (outsideContainer && outsideContainer.contains(e.target));
        if (!inside) {
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
