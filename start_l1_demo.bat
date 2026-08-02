@echo off
setlocal

cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

echo Запускаю MarketMind AI L1.1 demo...
%PYTHON% START_L1_DEMO.py

pause
