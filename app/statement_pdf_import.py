"""Eski cari ekstre PDF'lerini (muhasebe programi ciktisi - Tarih, Aciklama,
Borc, Alacak, Bakiye sutunlari) okuyup satirlara ayiran yardimci modul (Is 1).
Onizleme ekrani yok - dogrudan routes.py'deki import_statement_pdf route'u
tarafindan cagrilip sonuclar direkt CustomerStatement'a islenir."""
import re
from datetime import datetime

import pdfplumber

_TR_HEADER_MAP = str.maketrans('çğıöşü', 'cgiosu')


def _normalize_header(text):
    if not text:
        return ''
    return text.strip().lower().translate(_TR_HEADER_MAP)


def _parse_tr_amount(text):
    """'12.500,00' -> 12500.0. Bos/gecersiz/sifirsa None."""
    if text is None:
        return None
    text = str(text).strip().replace(' ', '').replace('₺', '').replace('TL', '')
    if not text or text in ('-', '—', '--'):
        return None
    negative = text.startswith('-')
    if negative:
        text = text[1:]
    text = text.replace('.', '').replace(',', '.')
    try:
        val = float(text)
    except ValueError:
        return None
    if val == 0:
        return None
    return -val if negative else val


_DATE_RE = re.compile(r'\d{1,2}[./]\d{1,2}[./]\d{2,4}')


def _parse_tr_date(text):
    if not text:
        return None
    text = text.strip()
    match = _DATE_RE.search(text)
    if not match:
        return None
    raw = match.group(0).replace('/', '.')
    parts = raw.split('.')
    if len(parts) != 3:
        return None
    day, month, year = parts
    if len(year) == 2:
        year = '20' + year
    for fmt_parts in ((day, month, year),):
        try:
            return datetime(int(year), int(month), int(day)).date()
        except ValueError:
            return None
    return None


_COL_KEYS = ('tarih', 'aciklama', 'borc', 'alacak', 'bakiye')


def parse_statement_pdf(file_stream):
    """PDF'teki Tarih/Aciklama/Borc/Alacak/Bakiye tablosunu okur.

    Donen deger: (rows, last_balance)
      rows: [{'date': date, 'description': str, 'type': 'borc'|'alacak', 'amount': float}, ...]
      last_balance: PDF'te en son gorulen Bakiye degeri (float) ya da None.
    """
    rows = []
    last_balance = None

    with pdfplumber.open(file_stream) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table:
                    continue
                header_idx = None
                col_map = {}
                for ridx, row in enumerate(table):
                    normalized = [_normalize_header(cell) for cell in row]
                    has_tarih = any('tarih' in c for c in normalized)
                    has_borc_or_alacak = any('borc' in c or 'alacak' in c for c in normalized)
                    if has_tarih and has_borc_or_alacak:
                        header_idx = ridx
                        for cidx, cell in enumerate(normalized):
                            for key in _COL_KEYS:
                                if key in cell and key not in col_map:
                                    col_map[key] = cidx
                        break
                if header_idx is None or 'tarih' not in col_map:
                    continue

                def _cell(row, key):
                    idx = col_map.get(key)
                    if idx is None or idx >= len(row):
                        return None
                    return row[idx]

                for row in table[header_idx + 1:]:
                    if not row:
                        continue
                    d = _parse_tr_date(_cell(row, 'tarih'))
                    if not d:
                        # Tarih parse edilemeyen satirlar (bos satir, "Toplam"
                        # ozet satiri, tekrar eden baslik vb.) atlanir.
                        continue
                    desc = (_cell(row, 'aciklama') or '').strip()
                    borc = _parse_tr_amount(_cell(row, 'borc'))
                    alacak = _parse_tr_amount(_cell(row, 'alacak'))
                    bakiye = _parse_tr_amount(_cell(row, 'bakiye'))
                    if bakiye is not None:
                        last_balance = bakiye
                    if borc:
                        rows.append({'date': d, 'description': desc, 'type': 'borc', 'amount': abs(borc)})
                    if alacak:
                        rows.append({'date': d, 'description': desc, 'type': 'alacak', 'amount': abs(alacak)})

    return rows, last_balance
