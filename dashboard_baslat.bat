@echo off
chcp 65001 >nul
title Trading Bot Dashboard
color 0A

echo.
echo  ==================================================
echo   ⚡  Trading Bot Trading Dashboard Baslatiliyor
echo  ==================================================
echo.

cd /d "%~dp0"

REM Python ortamını kontrol et
python --version >nul 2>&1
if errorlevel 1 (
    echo  [HATA] Python bulunamadi! Lutfen Python yukleyin.
    pause
    exit /b 1
)

REM Dashboard'u başlat
echo  Dashboard baslatiliyor...
echo  Tarayicinizda acin: http://localhost:8050
echo  Durdurmak icin: Ctrl+C
echo.

python dashboard\app.py

pause
