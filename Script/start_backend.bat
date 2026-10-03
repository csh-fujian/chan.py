@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
REM ============================================================================
REM start_backend.bat -- Start chan.py FastAPI backend (Windows)
REM
REM Usage:
REM   start_backend.bat                       REM default 0.0.0.0:8000
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

REM Dependency check: auto-install fastapi/uvicorn if missing
"%PY%" -c "import fastapi, uvicorn" >nul 2>&1
if !errorlevel! NEQ 0 (
    echo [start_backend] 缺少 fastapi/uvicorn，正在安装...
    "%PIP%" install -q fastapi uvicorn
)

REM Ensure repo root is on the import path (ChanAnalyse.* / WebAPI.*)
set "PYTHONPATH=%SCRIPT_DIR%;%PYTHONPATH%"

if "%HOST%"=="" set "HOST=0.0.0.0"
if "%PORT%"=="" set "PORT=8000"

REM PostgreSQL connection (override with PG_DSN env var)
if "%PG_DSN%"=="" set "PG_DSN=host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres"

echo [start_backend] 启动 FastAPI 服务: http://%HOST%:%PORT%
"%PY%" -m uvicorn WebAPI.main:app --host %HOST% --port %PORT% %*
endlocal
