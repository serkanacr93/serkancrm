/* B1/B2 (2026-10-06) - "Kese seç" / "Doypack seç" yardimci panelleri.
 * AYRI dosya: add_deal.html/edit_deal.html'e SADECE iki buton + bu script
 * etiketi eklenir, mevcut satir/hesaplama/kaydetme mantigina DOKUNULMAZ -
 * panel, mevcut "Urun Ekle" butonunu ve mevcut qty/price input'larina
 * 'input' event'i dispatch ederek mevcut calculateTotals() mantigini
 * TETIKLER, kopyalamaz. window.TEKLIF_YARDIMCI_KATALOG (sayfada inline
 * script ile tanimlanir) ve window.TEKLIF_YARDIMCI_CSRF kullanilir. */
(function () {
    if (!window.TEKLIF_YARDIMCI_KATALOG) return;
    var KATALOG = window.TEKLIF_YARDIMCI_KATALOG;
    var CSRF = window.TEKLIF_YARDIMCI_CSRF || '';

    function fmtTR(n, decimals) {
        return Number(n).toLocaleString('tr-TR', { minimumFractionDigits: decimals || 0, maximumFractionDigits: decimals || 2 });
    }

    function findTargetRow() {
        var rows = document.querySelectorAll('.item-row');
        for (var i = 0; i < rows.length; i++) {
            var descInput = rows[i].querySelector('input[name^="desc_"]');
            if (descInput && !descInput.value.trim()) return rows[i];
        }
        var addBtn = document.getElementById('add-item');
        if (addBtn) addBtn.click();
        var allRows = document.querySelectorAll('.item-row');
        return allRows[allRows.length - 1];
    }

    function fillRow(row, data) {
        var specsRow = row.nextElementSibling;
        var descInput = row.querySelector('input[name^="desc_"]');
        var unitSelect = row.querySelector('select[name^="unit_"]');
        var tipSelect = row.querySelector('select[name^="urun_tipi_"]');
        var priceInput = row.querySelector('input[name^="price_"]');
        var qtyInput = row.querySelector('input[name^="qty_"]');

        descInput.value = data.aciklama;
        if (data.birim) unitSelect.value = data.birim;
        if (data.tip) tipSelect.value = data.tip;
        if (data.birim_fiyat !== undefined && data.birim_fiyat !== null) {
            priceInput.value = data.birim_fiyat;
            priceInput.dispatchEvent(new Event('input', { bubbles: true }));
        }
        if (specsRow) {
            var setVal = function (name, val) {
                var el = specsRow.querySelector('input[name^="' + name + '_"]');
                if (el) el.value = val || '';
            };
            setVal('kagit_cinsi', data.kagit);
            setVal('boy', data.boy);
            setVal('en', data.en);
            setVal('korugu', data.korugu);
            setVal('renk', data.renk);
        }
        qtyInput.focus();
        return { qtyInput: qtyInput, priceInput: priceInput };
    }

    function closeAllPanels() {
        document.querySelectorAll('.ty-panel').forEach(function (p) { p.classList.add('d-none'); });
    }

    // ===================== KESE PANELI =====================
    function buildKesePanel() {
        var wrap = document.createElement('div');
        wrap.className = 'ty-panel d-none card mt-2 mb-3';
        wrap.id = 'ty-kese-panel';
        wrap.innerHTML =
            '<div class="card-header bg-warning text-dark d-flex justify-content-between align-items-center">' +
            '<strong><i class="bi bi-bag"></i> Kese Seç</strong>' +
            '<button type="button" class="btn-close" data-ty-close></button>' +
            '</div>' +
            '<div class="card-body">' +
            '<label class="form-label small">Kağıt</label>' +
            '<select class="form-select form-select-sm mb-2" id="ty-kese-kagit" style="max-width:240px;">' +
            '<option value="esmer_kraft">Esmer kraft</option>' +
            '<option value="beyaz_kraft">Beyaz kraft</option>' +
            '<option value="kuse">Kuşe</option>' +
            '</select>' +
            '<div class="row g-2" id="ty-kese-cards"></div>' +
            '<div id="ty-kese-diger-wrap" class="mt-2"></div>' +
            '<div class="alert alert-warning small mt-2 d-none" id="ty-kese-uyari">Lütfen bir gramaj kartı seçin.</div>' +
            '</div>';
        return wrap;
    }

    function kagitLabel(kagit) {
        return kagit === 'kuse' ? 'Kuşe' : (kagit === 'beyaz_kraft' ? 'Beyaz kraft' : 'Esmer kraft');
    }

    function renderKeseCards(panel) {
        var kagit = document.getElementById('ty-kese-kagit').value;
        var isKuse = kagit === 'kuse';
        var container = panel.querySelector('#ty-kese-cards');
        var digerWrap = panel.querySelector('#ty-kese-diger-wrap');
        container.innerHTML = '';
        digerWrap.innerHTML = '';
        var digerCards = [];

        KATALOG.kese.forEach(function (k) {
            var min = isKuse ? k.kuse_min : k.kraft_min;
            var max = isKuse ? k.kuse_max : k.kraft_max;
            var col = document.createElement('div');
            col.className = 'col-6 col-md-4 col-lg-3';
            var olcuText = (k.en && k.korugu && k.boy) ? (k.en + '×' + k.korugu + '×' + k.boy) : 'ölçü girilmemiş';
            var adetText = (min && max) ? (fmtTR(min, 0) + '–' + fmtTR(max, 0) + ' adet/kg') : 'adet/kg girilmemiş';
            col.innerHTML =
                '<div class="card h-100 ty-kese-card" style="cursor:pointer;" data-gramaj="' + k.gramaj + '">' +
                '<div class="card-body p-2 text-center">' +
                '<div class="fw-bold">' + k.gramaj + ' gr</div>' +
                '<div class="small text-muted">' + olcuText + '</div>' +
                '<div class="small">' + adetText + '</div>' +
                '</div></div>';
            if (k.aktif) {
                container.appendChild(col);
            } else {
                digerCards.push(col);
            }
        });

        if (digerCards.length) {
            var details = document.createElement('details');
            details.className = 'mt-2';
            var summary = document.createElement('summary');
            summary.className = 'small text-muted';
            summary.textContent = 'Diğer boylar (350 / 750 / 1500 gr)';
            details.appendChild(summary);
            var row = document.createElement('div');
            row.className = 'row g-2 mt-1';
            digerCards.forEach(function (c) { row.appendChild(c); });
            details.appendChild(row);
            digerWrap.appendChild(details);
        }
    }

    function initKesePanel(panel) {
        document.getElementById('ty-kese-kagit').addEventListener('change', function () { renderKeseCards(panel); });
        panel.addEventListener('click', function (e) {
            if (e.target.closest('[data-ty-close]')) { panel.classList.add('d-none'); return; }
            var card = e.target.closest('.ty-kese-card');
            if (!card) return;
            var gramaj = parseInt(card.dataset.gramaj, 10);
            var k = KATALOG.kese.filter(function (x) { return x.gramaj === gramaj; })[0];
            if (!k || !k.en || !k.boy) {
                panel.querySelector('#ty-kese-uyari').classList.remove('d-none');
                panel.querySelector('#ty-kese-uyari').textContent = 'Bu gramajın ölçü bilgisi henüz Ayarlar\'dan girilmemiş.';
                return;
            }
            panel.querySelector('#ty-kese-uyari').classList.add('d-none');
            var kagit = document.getElementById('ty-kese-kagit').value;
            var row = findTargetRow();
            var refs = fillRow(row, {
                aciklama: k.gramaj + ' gr ' + kagitLabel(kagit).toLowerCase() + ' kare dipli kese',
                birim: 'kg', tip: 'uretim',
                kagit: kagitLabel(kagit), boy: k.boy, en: k.en, korugu: k.korugu,
            });
            // "≈ adet" tahmini - miktar (kg) girilince canli guncellenir, KAYDEDILMEZ.
            var isKuse = kagit === 'kuse';
            var min = isKuse ? k.kuse_min : k.kraft_min;
            var max = isKuse ? k.kuse_max : k.kraft_max;
            attachEstimate(row, refs.qtyInput, min, max);
            panel.classList.add('d-none');
        });
    }

    function estimateContainer(specsRow) {
        // add_deal.html'de specsRow bir <tr><td colspan>...</td></tr> (tabloda
        // tek bastina cocuk eklenemez), edit_deal.html'de duz bir <div> -
        // iki sayfa ayni JS'i paylastigi icin yapiya gore dogru konteyner
        // seciliyor.
        if (specsRow.tagName === 'TR') return specsRow.querySelector('td');
        return specsRow;
    }

    function attachEstimate(row, qtyInput, min, max) {
        if (!min || !max) return;
        var specsRow = row.nextElementSibling;
        if (!specsRow) return;
        var est = specsRow.querySelector('.ty-estimate');
        if (!est) {
            est = document.createElement('div');
            est.className = 'ty-estimate small text-muted mt-1';
            estimateContainer(specsRow).appendChild(est);
        }
        function update() {
            var qty = parseFloat(qtyInput.value) || 0;
            if (qty <= 0) { est.textContent = ''; return; }
            est.textContent = '≈ ' + fmtTR(Math.round(min * qty), 0) + '–' + fmtTR(Math.round(max * qty), 0) + ' adet';
        }
        qtyInput.removeEventListener('input', qtyInput._tyEstimateHandler || function () {});
        qtyInput._tyEstimateHandler = update;
        qtyInput.addEventListener('input', update);
        update();
    }

    // ===================== DOYPACK PANELI =====================
    function buildDoypackPanel() {
        var wrap = document.createElement('div');
        wrap.className = 'ty-panel d-none card mt-2 mb-3';
        wrap.id = 'ty-doypack-panel';
        wrap.innerHTML =
            '<div class="card-header bg-primary text-white d-flex justify-content-between align-items-center">' +
            '<strong><i class="bi bi-box-seam"></i> Doypack Seç</strong>' +
            '<button type="button" class="btn-close btn-close-white" data-ty-close></button>' +
            '</div>' +
            '<div class="card-body">' +
            '<div class="row g-2 mb-3" id="ty-doypack-cards"></div>' +
            '<div id="ty-doypack-detail" class="d-none border rounded p-2 bg-light">' +
            '<div class="fw-bold mb-2" id="ty-doypack-selected-label"></div>' +
            '<label class="form-label small">Baskı</label>' +
            '<select class="form-select form-select-sm mb-2" id="ty-doypack-baski" style="max-width:200px;">' +
            '<option value="baskisiz">Baskısız</option>' +
            '<option value="baskili">Baskılı</option>' +
            '</select>' +
            '<div id="ty-doypack-baski-detay" class="d-none row g-2 mb-2">' +
            '<div class="col-auto"><select class="form-select form-select-sm" id="ty-doypack-yuz"><option value="tek">Tek Yüz</option><option value="cift">Çift Yüz</option></select></div>' +
            '<div class="col-auto"><select class="form-select form-select-sm" id="ty-doypack-renk"><option value="1">1 renk</option><option value="2">2 renk</option><option value="3">3 renk</option><option value="4">4 renk</option></select></div>' +
            '<div class="col-auto"><input type="number" step="0.01" class="form-control form-control-sm" id="ty-doypack-baski-fiyat" placeholder="Baskı fiyatı (₺/adet)" style="width:180px;"></div>' +
            '</div>' +
            '<div class="small mb-2" id="ty-doypack-fiyat-dokum"></div>' +
            '<button type="button" class="btn btn-sm btn-success" id="ty-doypack-ekle">Satıra Ekle</button>' +
            '</div>' +
            '</div>';
        return wrap;
    }

    var doypackSelected = null;

    function renderDoypackCards(panel) {
        var container = panel.querySelector('#ty-doypack-cards');
        container.innerHTML = '';
        KATALOG.doypack.forEach(function (d) {
            var col = document.createElement('div');
            col.className = 'col-6 col-md-4 col-lg-3';
            col.innerHTML =
                '<div class="card h-100 ty-doypack-card" style="cursor:pointer;" data-id="' + d.id + '">' +
                '<div class="card-body p-2 text-center">' +
                '<div class="fw-bold">' + d.en + '×' + d.boy + '</div>' +
                '<div class="small text-muted">Körük ' + (d.korugu || '-') + '</div>' +
                '<div class="small">' + (d.koli_adedi || '-') + ' ad/koli · ' + fmtTR(d.fiyat, 2) + ' ₺</div>' +
                '</div></div>';
            container.appendChild(col);
        });
    }

    function updateDoypackDetail(panel) {
        if (!doypackSelected) return;
        var baskiMode = panel.querySelector('#ty-doypack-baski').value;
        var baskiDetay = panel.querySelector('#ty-doypack-baski-detay');
        var baskiFiyatInput = panel.querySelector('#ty-doypack-baski-fiyat');
        var dokum = panel.querySelector('#ty-doypack-fiyat-dokum');

        if (baskiMode === 'baskili') {
            baskiDetay.classList.remove('d-none');
            var yuz = panel.querySelector('#ty-doypack-yuz').value;
            var renk = parseInt(panel.querySelector('#ty-doypack-renk').value, 10);
            var katalogFiyat = KATALOG.baski.filter(function (b) { return b.yuz === yuz && b.renk_sayisi === renk; })[0];
            // Yuz/renk kombinasyonu degisince (ornegin tek-1 renkten cift-2
            // renge gecilince) eskiden ekrana yazilmis katalog fiyati
            // TEMIZLENMELIYDI - degilse yeni kombinasyonun katalogda fiyati
            // olmasa bile eski deger yanlislikla kalip "6,00 TL" gibi hatali
            // bir toplam gosteriyordu (TEST ile yakalanan gercek hata).
            if (!baskiFiyatInput.dataset.userEdited) {
                baskiFiyatInput.value = (katalogFiyat && katalogFiyat.fiyat !== null) ? katalogFiyat.fiyat : '';
            }
            var baskiFiyat = parseFloat(baskiFiyatInput.value) || 0;
            var toplam = doypackSelected.fiyat + baskiFiyat;
            dokum.textContent = 'Doypack ' + fmtTR(doypackSelected.fiyat, 2) + ' ₺ + Baskı ' + fmtTR(baskiFiyat, 2) + ' ₺ = Birim fiyat ' + fmtTR(toplam, 2) + ' ₺';
        } else {
            baskiDetay.classList.add('d-none');
            dokum.textContent = 'Birim fiyat: ' + fmtTR(doypackSelected.fiyat, 2) + ' ₺ (baskısız)';
        }
    }

    function initDoypackPanel(panel) {
        panel.addEventListener('click', function (e) {
            if (e.target.closest('[data-ty-close]')) { panel.classList.add('d-none'); return; }
            var card = e.target.closest('.ty-doypack-card');
            if (card) {
                var id = parseInt(card.dataset.id, 10);
                doypackSelected = KATALOG.doypack.filter(function (d) { return d.id === id; })[0];
                panel.querySelector('#ty-doypack-detail').classList.remove('d-none');
                panel.querySelector('#ty-doypack-selected-label').textContent =
                    'Seçilen: ' + doypackSelected.en + '×' + doypackSelected.boy + ' (Körük ' + (doypackSelected.korugu || '-') + ', ' + (doypackSelected.koli_adedi || '-') + ' ad/koli)';
                panel.querySelector('#ty-doypack-baski-fiyat').dataset.userEdited = '';
                updateDoypackDetail(panel);
                return;
            }
            if (e.target.id === 'ty-doypack-ekle') {
                if (!doypackSelected) return;
                var baskiMode = panel.querySelector('#ty-doypack-baski').value;
                var aciklama = 'Kraft pencereli kilitli doypack ' + doypackSelected.en + '×' + doypackSelected.boy + ' (' + (doypackSelected.korugu || '-') + ')';
                var renkInfo = null, birimFiyat = doypackSelected.fiyat, tip = 'ticaret';
                if (baskiMode === 'baskili') {
                    var yuz = panel.querySelector('#ty-doypack-yuz').value;
                    var renk = parseInt(panel.querySelector('#ty-doypack-renk').value, 10);
                    var baskiFiyat = parseFloat(panel.querySelector('#ty-doypack-baski-fiyat').value) || 0;
                    birimFiyat = doypackSelected.fiyat + baskiFiyat;
                    renkInfo = renk + ' renk ' + (yuz === 'cift' ? 'çift' : 'tek') + ' yüz baskılı';
                    aciklama += ' · ' + renkInfo;
                    tip = 'uretim';
                    // Katalogda olmayan/degismis bir fiyat girildiyse ayarlara kaydet (B2)
                    var katalogFiyat = KATALOG.baski.filter(function (b) { return b.yuz === yuz && b.renk_sayisi === renk; })[0];
                    if (baskiFiyat > 0 && (!katalogFiyat || katalogFiyat.fiyat !== baskiFiyat)) {
                        fetch('/api/teklif-yardimci/baski-fiyat', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
                            body: JSON.stringify({ yuz: yuz, renk_sayisi: renk, fiyat: baskiFiyat })
                        }).catch(function () {});
                        if (katalogFiyat) katalogFiyat.fiyat = baskiFiyat;
                    }
                }
                var row = findTargetRow();
                var refs = fillRow(row, {
                    aciklama: aciklama, birim: 'adet', tip: tip, birim_fiyat: birimFiyat,
                    kagit: 'Kraft', boy: doypackSelected.boy, en: doypackSelected.en,
                    korugu: doypackSelected.korugu, renk: renkInfo,
                });
                attachKoliEstimate(row, refs.qtyInput, doypackSelected.koli_adedi);
                panel.classList.add('d-none');
                doypackSelected = null;
                panel.querySelector('#ty-doypack-detail').classList.add('d-none');
            }
        });
        panel.addEventListener('change', function (e) {
            if (['ty-doypack-baski', 'ty-doypack-yuz', 'ty-doypack-renk'].indexOf(e.target.id) !== -1) {
                updateDoypackDetail(panel);
            }
        });
        panel.addEventListener('input', function (e) {
            if (e.target.id === 'ty-doypack-baski-fiyat') {
                e.target.dataset.userEdited = '1';
                updateDoypackDetail(panel);
            }
        });
    }

    function attachKoliEstimate(row, qtyInput, koliAdedi) {
        if (!koliAdedi) return;
        var specsRow = row.nextElementSibling;
        if (!specsRow) return;
        var est = specsRow.querySelector('.ty-estimate');
        if (!est) {
            est = document.createElement('div');
            est.className = 'ty-estimate small text-muted mt-1';
            estimateContainer(specsRow).appendChild(est);
        }
        function update() {
            var qty = parseFloat(qtyInput.value) || 0;
            if (qty <= 0) { est.textContent = ''; return; }
            var koli = qty / koliAdedi;
            var tamKoli = Math.floor(koli);
            var kalan = qty - tamKoli * koliAdedi;
            if (kalan === 0) {
                est.textContent = '= ' + fmtTR(tamKoli, 0) + ' koli';
            } else {
                est.textContent = '= ' + fmtTR(tamKoli + 1, 0) + ' koli (son koli eksik - ' + fmtTR(kalan, 0) + ' adet)';
            }
        }
        qtyInput.removeEventListener('input', qtyInput._tyEstimateHandler || function () {});
        qtyInput._tyEstimateHandler = update;
        qtyInput.addEventListener('input', update);
        update();
    }

    // ===================== KURULUM =====================
    document.addEventListener('DOMContentLoaded', function () {
        var keseBtn = document.getElementById('ty-kese-btn');
        var doypackBtn = document.getElementById('ty-doypack-btn');
        var mount = document.getElementById('teklif-yardimci-mount');
        if (!mount || (!keseBtn && !doypackBtn)) return;

        var kesePanel = buildKesePanel();
        var doypackPanel = buildDoypackPanel();
        mount.appendChild(kesePanel);
        mount.appendChild(doypackPanel);
        initKesePanel(kesePanel);
        initDoypackPanel(doypackPanel);
        renderDoypackCards(doypackPanel);

        if (keseBtn) {
            keseBtn.addEventListener('click', function () {
                var isOpen = !kesePanel.classList.contains('d-none');
                closeAllPanels();
                if (!isOpen) {
                    renderKeseCards(kesePanel);
                    kesePanel.classList.remove('d-none');
                }
            });
        }
        if (doypackBtn) {
            doypackBtn.addEventListener('click', function () {
                var isOpen = !doypackPanel.classList.contains('d-none');
                closeAllPanels();
                if (!isOpen) doypackPanel.classList.remove('d-none');
            });
        }
    });
})();
