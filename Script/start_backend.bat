@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
REM ============================================================================
REM start_backend.bat -- Start chan.py FastAPI backend (Windows)
REM
REM Usage:
REM   start_backend.bat                       REM default 0.0.0.0:8001
REM   set PORT=9000 & start_backend.bat       REM custom port
REM   set PG_DSN=host=... dbname=... user=... password=... & start_backend.bat
REM   start_backend.bat --reload              REM dev hot-reload (uvicorn args)
REM
REM Notes:
REM   - Run from repo root (script auto-cd to parent of its own dir)
REM   - /api/health and /api/klines work without PG (kline data from DuckDB)
REM   - PG_DSN defaults to local chan db (127.0.0.1:5432, user postgres)
REM   - /api/auth/* and stocks/watchlist/monitor routes need PG_DSN
REM ============================================================================

REM Locate repo root (script lives in Script\, parent is repo root) and cd there
cd /d "%~dp0.."
set "SCRIPT_DIR=%CD%"

set "PY=.venv\Scripts\python.exe"
set "PIP=.venv\Scripts\pip.exe"

REM 依赖自检：项目虚拟环境是否存在（缺失时会报 "系统找不到指定的路径"）
if not exist "%PY%" (
    echo [start_backend] 未找到虚拟环境: %CD%\.venv\Scripts\python.exe
    echo [start_backend] 请先创建并安装依赖:
    echo [start_backend]   python -m venv .venv
    echo [start_backend]   .venv\Scripts\pip install -r Script\requirements.txt
    exit /b 1
)

REM Dependency check: auto-install fastapi/uvicorn if missing
"%PY%" -c "import fastapi, uvicorn" >nul 2>&1
if !errorlevel! NEQ 0 (
    echo [start_backend] 缺少 fastapi/uvicorn，正在安装...
    "%PIP%" install -q fastapi uvicorn
)

REM Ensure repo root is on the import path (ChanAnalyse.* / WebAPI.*)
set "PYTHONPATH=%SCRIPT_DIR%;%PYTHONPATH%"

if "%HOST%"=="" set "HOST=0.0.0.0"
if "%PORT%"=="" set "PORT=8001"

REM 端口占用检测（WinError 10048 的直接成因）：占用方若已是本仓库后端，提示并退出；
REM 否则打印 PID，由用户决定是否结束进程（脚本不自动 kill）
set "PORT_BUSY=0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /c:"LISTENING" ^| findstr /c:":%PORT% "') do set "PORT_BUSY=%%a"
if not "!PORT_BUSY!"=="0" (
    echo [start_backend] 端口 %PORT% 已被进程 PID=!PORT_BUSY! 占用。
    powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter 'ProcessId=!PORT_BUSY!' | Select-Object -ExpandProperty CommandLine" 2>nul
    echo [start_backend] 若那是本仓库的后端，直接访问 http://127.0.0.1:%PORT%/api/health 即可；否则结束它后重试：
    echo [start_backend]   taskkill /PID !PORT_BUSY! /T /F
    echo [start_backend] 或者换端口启动：
    echo [start_backend]   set PORT=8002 ^&^& Script\start_backend.bat
    exit /b 1
)

REM PostgreSQL connection (override with PG_DSN env var)
if "%PG_DSN%"=="" set "PG_DSN=host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres"

echo [start_backend] 启动 FastAPI 服务: http://%HOST%:%PORT%
"%PY%" -m uvicorn WebAPI.main:app --host %HOST% --port %PORT% %*
endlocal
