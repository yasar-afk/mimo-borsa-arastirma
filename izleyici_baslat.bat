@echo off
title V6 CANLI IZLEYICI
chcp 65001 >nul
echo ==========================================
echo V6 MEAN REVERSION - CANLI IZLEYICI
echo ==========================================
echo.
set /p SURE="Kac saniyede bir yenilensin? (varsayilan: 10): "
if "%SURE%"=="" set SURE=10
echo.
echo Dashboard baslatiliyor... (%SURE% sn yenileme)
echo Cikis icin: Ctrl+C
echo.
venv\Scripts\python.exe watch.py --refresh %SURE%
pause
