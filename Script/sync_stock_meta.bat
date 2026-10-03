@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
REM ============================================================================
REM sync_stock_meta.bat -- Stock meta sync launcher (AKShare multi-source -> PG,
REM                        Windows)
REM
REM Usage:
REM   sync_stock_meta.bat            REM interactive menu
REM   sync_stock_meta.bat full       REM non-interactive: full sync (all markets,
REM                                  REM  all domains, force refresh)
REM   sync_stock_meta.bat incr       REM non-interactive: incremental (by
REM                                  REM  watermark/expiry, --no-force)
REM   sync_stock_meta.bat loop       REM non-interactive: resident, hourly,
REM                                  REM  only due domains
REM   set DRYRUN=1 & sync_stock_meta.bat full   REM print commands only
REM
REM Notes:
REM   - Full sync = --force without --code/--domain: identity/profile/industry/
REM     snapshot/financial/holders six domains x all markets; resumable
REM     (unit = code x domain), re-run same command after interruption/failure
REM     to continue from unfinished units.
REM   - Idempotent: static fields (ipo_date/found_date) protected by IS NULL on
REM     the DB side; repeated syncs do not overwrite.
REM   - PG_DSN default same as start_backend.bat: host=127.0.0.1 ... dbname=chan
REM     ..., override with env var.
REM   - Note: the backend process also runs an hourly due-domain scheduler
REM     (WebAPI/app.py). Manual full sync (--force) concurrent with it will not
REM     corrupt data (idempotent) but duplicates requests; stagger them.
REM   - Exit codes: 0=success 1=failed units exist (re-run to resume)
REM     2=PG_DSN missing 130=interrupted (progress saved)
REM ============================================================================

REM Always run from repo root
cd /d "%~dp0.."
set "PYTHONPATH=%CD%"
set "PY=.venv\Scripts\python.exe"
set "LOG_DIR=Log"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
if "%DRYRUN%"=="" set "DRYRUN=0"

REM PostgreSQL connection (same default as start_backend.bat, override with PG_DSN)
if "%PG_DSN%"=="" set "PG_DSN=host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres"

set "ALL_DOMAINS= identity profile industry snapshot financial holders "

REM ---------------------------------------------------------------------------
REM Non-interactive shortcuts (for scheduled tasks / background batch runs)
REM ---------------------------------------------------------------------------
if /I "%~1"=="full" (
    for /f "delims=" %%t in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "ts=%%t"
    call :run_cmd "%LOG_DIR%\sync_stock_meta_!ts!.log" "'%PY%' Data\sync_stock_meta.py --force"
    exit /b !errorlevel!
)
if /I "%~1"=="incr" (
    for /f "delims=" %%t in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "ts=%%t"
    call :run_cmd "%LOG_DIR%\sync_stock_meta_!ts!.log" "'%PY%' Data\sync_stock_meta.py --no-force"
    exit /b !errorlevel!
)
if /I "%~1"=="loop" (
    for /f "delims=" %%t in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "ts=%%t"
    call :run_cmd "%LOG_DIR%\sync_stock_meta_!ts!.log" "'%PY%' Data\sync_stock_meta.py --loop"
    exit /b !errorlevel!
)
if /I "%~1"=="-h" goto usage
if /I "%~1"=="--help" goto usage
if /I "%~1"=="help" goto usage
if /I "%~1"=="" goto check_running
echo 未知参数: %~1（可用: full / incr / loop / --help）& exit /b 2

:usage
echo 用法:
echo   sync_stock_meta.bat            REM 交互菜单  
echo   sync_stock_meta.bat full       REM 免交互：全量同步（全市场|全域|强制刷新）  
echo   sync_stock_meta.bat incr       REM 免交互：增量同步（按水位/到期，--no-force）  
echo   sync_stock_meta.bat loop       REM 免交互：常驻，每小时只跑到期域  
echo   set DRYRUN=1 ^& sync_stock_meta.bat full   REM 只打印命令，不真正执行  
exit /b 0

:check_running
REM Duplicate-process guard: avoid double-running the same script
REM (backend built-in scheduler noted in header comment)
powershell -NoProfile -Command "if (Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object {$_.CommandLine -like '*sync_stock_meta.py*'}) { exit 0 } else { exit 1 }"
if !errorlevel! EQU 0 (
    echo [!] 检测到已在运行的元信息同步进程:
    powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object {$_.CommandLine -like '*sync_stock_meta.py*'} | Select-Object ProcessId,CommandLine | Format-List"
    set /p "ans=仍要继续启动新任务? [y/N] "
    if /I not "!ans!"=="y" ( echo 已取消& exit /b 1 )
)

:menu
echo.
echo ======== 股票元信息同步（AKShare -> PG）========
echo 1) 全量同步   全市场 - 全域 - 强制刷新（--force，主功能）  
echo 2) 增量同步   全市场 - 全域 - 按水位/到期（--no-force，未到期不发请求）  
echo 3) 指定域同步  identity/profile/industry/snapshot/financial/holders（可多选）  
echo 4) 指定股票   一只或多只，全域  
echo 5) 常驻模式   每小时检查一次，只执行到期域（--loop，Ctrl+C 退出）  
echo 0) 退出  
set "choice="
set /p "choice=请选择 [0-5]: "
if "!choice!"=="" set "choice=0"

for /f "delims=" %%t in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "ts=%%t"
set "logfile=%LOG_DIR%\sync_stock_meta_!ts!.log"
set "rc=0"

if "!choice!"=="0" ( echo 退出& exit /b 0 )
if "!choice!"=="1" (
    call :ask_sleep 0.4
    call :run_cmd "!logfile!" "'%PY%' Data\sync_stock_meta.py --force --sleep !ask_sleep_result!"
    set "rc=!errorlevel!"
    goto after
)
if "!choice!"=="2" (
    call :ask_sleep 0.4
    call :run_cmd "!logfile!" "'%PY%' Data\sync_stock_meta.py --no-force --sleep !ask_sleep_result!"
    set "rc=!errorlevel!"
    goto after
)
if "!choice!"=="3" (
    echo 可选域: identity profile industry snapshot financial holders
    set "doms="
    set /p "doms=要同步的域（空格分隔）: "
    set "dom_args="
    set "bad=0"
    for %%d in (!doms!) do (
        echo !ALL_DOMAINS!| findstr /C:" %%d " >nul
        if !errorlevel! NEQ 0 ( echo [ERR] 未知域: %%d& set "bad=1" ) else ( set "dom_args=!dom_args! --domain %%d" )
    )
    if !bad! NEQ 0 ( echo [ERR] 域无效或为空，请重试& goto menu )
    if "!dom_args!"=="" ( echo [ERR] 域无效或为空，请重试& goto menu )
    set "f="
    set /p "f=强制刷新? [Y/n]（n=按水位增量）: "
    set "force_arg=--force"
    if /I "!f!"=="n" set "force_arg=--no-force"
    call :ask_sleep 0.4
    call :run_cmd "!logfile!" "'%PY%' Data\sync_stock_meta.py !dom_args! !force_arg! --sleep !ask_sleep_result!"
    set "rc=!errorlevel!"
    goto after
)
if "!choice!"=="4" (
    set "codes="
    set /p "codes=股票代码（空格分隔，可多只，如 sz.000001 600519）: "
    set "code_args="
    for %%c in (!codes!) do ( set "code_args=!code_args! --code %%c" )
    if "!code_args!"=="" ( echo [ERR] 代码不能为空& goto menu )
    call :ask_sleep 0.4
    call :run_cmd "!logfile!" "'%PY%' Data\sync_stock_meta.py !code_args! --force --sleep !ask_sleep_result!"
    set "rc=!errorlevel!"
    goto after
)
if "!choice!"=="5" (
    call :ask_sleep 0.4
    echo 提示: 常驻模式下按 Ctrl+C 优雅退出（进度已持久化）
    call :run_cmd "!logfile!" "'%PY%' Data\sync_stock_meta.py --loop --sleep !ask_sleep_result!"
    set "rc=!errorlevel!"
    goto after
)
echo 无效选择，请重试  
goto menu

:after
if !rc! NEQ 0 echo 本次退出码 !rc!（详见上方提示）
set "again="
set /p "again=再执行下一个任务? [y/N] "
if /I "!again!"=="y" goto menu
exit /b !rc!

REM ---------------------------------------------------------------------------
REM Input helpers
REM ---------------------------------------------------------------------------
:ask_sleep
REM %1 = default interval
set "def=%~1"
set "val="
set /p "val=逐股请求间隔 --sleep 秒 [回车取默认 %def%]: "
if "!val!"=="" set "val=%def%"
set "ask_sleep_result=!val!"
exit /b 0

REM ---------------------------------------------------------------------------
REM Command wrapper: print command, tee to log, exit-code hints
REM ---------------------------------------------------------------------------
:run_cmd
set "logfile=%~1"
set "cmdline=%~2"
echo -> 执行: !cmdline!
echo -> PG_DSN: 已配置  
echo -> 日志: !logfile!
if "%DRYRUN%"=="1" ( echo [dry-run] 跳过实际执行& exit /b 0 )
powershell -NoProfile -Command "& { & !cmdline! 2>&1 - Tee-Object -FilePath '!logfile!' -Append; exit $LASTEXITCODE }"
set "rc2=!errorlevel!"
if !rc2! EQU 0 ( echo [OK] 同步完成，日志: !logfile! ) else if !rc2! EQU 1 ( echo [ERR] 有失败单元（已入库部分有效）— 重跑同一命令断点续传，日志: !logfile! ) else if !rc2! EQU 2 ( echo [ERR] PG_DSN 未配置/无效，日志: !logfile! ) else if !rc2! EQU 130 ( echo [!] 被中断 — 断点已持久化，重跑同一命令续传，日志: !logfile! ) else ( echo [ERR] 退出码 !rc2!，日志: !logfile! )
exit /b !rc2!
