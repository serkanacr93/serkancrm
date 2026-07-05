@echo off
chcp 65001 >nul
title CRM Sistemi v3.0
echo ========================================
echo    CRM Sistemi v3.0
echo ========================================
echo.
echo Uygulama baslatiliyor...
echo Tarayicinizda http://localhost:5000 acilacak.
echo.
echo Kullanici: admin
echo Sifre: 1234
echo.
echo Kapatmak icin bu pencereyi kapatin.
echo ========================================
echo.
dist\CRM_Sistemi\CRM_Sistemi.exe
pause
