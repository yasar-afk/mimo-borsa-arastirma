@echo off
chcp 65001 >nul 2>&1
echo ============================================================
echo   Trading Bot — V5 + V7 (TEK PENCERE)
echo ============================================================
echo.
echo   V5: Price Action, filtresiz, %2 risk, 50 coin
echo   V7: Price Action, filtreli, %2 risk, 100 coin
echo.
echo   Baslamak icin bir tusa basin...
pause >nul

cd /d "%~dp0"
venv\Scripts\python.exe run_all_bots.py
pause
