/* B6 (2026-10-06) - app.models.format_price_tr'in JS karsiligi. Sistem
 * geneli tutar gosterimi: tam sayiysa ondalik yok (150000 -> "150.000₺"),
 * degilse 2 ondalige yuvarlanir (354.8781 -> "354,88₺"). Turkce ayrac,
 * sembol sona bitisik. Hesaplama DEGISMEZ, sadece ekrana yazilan metin. */
var CRM_CURRENCY_SYMBOLS = { TRY: '₺', EUR: '€', USD: '$', GBP: '£' };

function paraGoster(value, currency) {
    if (value === null || value === undefined || isNaN(value)) return '-';
    var symbol = CRM_CURRENCY_SYMBOLS[currency] || '₺';
    var num = Number(value);
    var sign = num < 0 ? '-' : '';
    num = Math.abs(num);
    if (Math.round(num) === num) {
        return sign + Math.round(num).toLocaleString('tr-TR') + symbol;
    }
    return sign + num.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + symbol;
}
