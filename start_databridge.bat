@echo off
title DataBridge - Unified Network Search Server
color 0A

echo ======================================================================
echo           DATABRIDGE - UNIFIED NETWORK SEARCH SYSTEM
echo ======================================================================
echo.

cd /d "%~dp0"

:: Check if Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not found in system PATH.
    echo Please install Python 3.10+ from python.org or add it to PATH.
    pause
    exit /b 1
)

:: Get Local IPv4 Address for mobile/network access
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4" ^| findstr /v "127.0.0.1"') do (
    set "IP=%%a"
    goto :found_ip
)
:found_ip
set "IP=%IP: =%"

echo [OK] Python detected.
echo [INFO] Local access URL:   http://localhost:8000
if defined IP (
    echo [INFO] Mobile / LAN URL:   http://%IP%:8000
) else (
    echo [INFO] Mobile / LAN URL:   http://10.100.9.9:8000
)
echo.
echo ======================================================================
echo Starting DataBridge Server (FastAPI + Uvicorn)...
echo Keep this window open while using the application.
echo Press Ctrl+C in this window to stop the server.
echo ======================================================================
echo.

python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 2

pause
