"""Teklif PDF yeni tasarim - tutar_yaziyla() birim testleri (2026-10-13).
DB/app baglamina ihtiyac yok, dogrudan calistirilabilir: pytest tests/test_sayi_yaziyla.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.pdf_utils import tutar_yaziyla


def test_sifir():
    assert tutar_yaziyla(0) == 'Sıfır Türk Lirası'


def test_bir():
    assert tutar_yaziyla(1) == 'Bir Türk Lirası'


def test_on():
    assert tutar_yaziyla(10) == 'On Türk Lirası'


def test_yuz():
    assert tutar_yaziyla(100) == 'Yüz Türk Lirası'


def test_bin():
    assert tutar_yaziyla(1000) == 'Bin Türk Lirası'


def test_bin_bir():
    assert tutar_yaziyla(1001) == 'Bin bir Türk Lirası'


def test_87648():
    assert tutar_yaziyla(87648) == 'Seksen yedi bin altı yüz kırk sekiz Türk Lirası'


def test_1250000_50():
    assert tutar_yaziyla(1250000.50) == 'Bir milyon iki yüz elli bin Türk Lirası elli Kuruş'
