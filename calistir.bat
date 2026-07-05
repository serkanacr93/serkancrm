@echo off
chcp 65001 >nul
title CRM Sistemi v2.0
echo ========================================
echo    CRM Sistemi v2.0 Baslatiliyor
echo ========================================
echo.

cd /d "C:\Users\PC\OneDrive\Desktop\crm"

if not exist "venv" (
    echo [1/2] Virtual environment olusturuluyor...
    python -m venv venv
    echo.
    echo [2/2] Gerekli kutuphaneler yukleniyor...
    venv\Scripts\pip.exe install -r requirements.txt
) else (
    echo Kutuphaneler zaten yuklu.
)

echo.
echo Uygulama baslatiliyor...
echo Tarayicinizda http://localhost:5000 adresini acin.
echo.
venv\Scripts\python.exe run.py

pause
