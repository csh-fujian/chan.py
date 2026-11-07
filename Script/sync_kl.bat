@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
REM ============================================================================
REM sync_kl.bat -- K-line ingest sync interactive launcher (incremental, Windows)
REM
REM Usage:
REM   sync_kl.bat                 REM interactive menu
REM   set DRYRUN=1 & sync_kl.bat  REM print commands only, no execution (dry run)
REM
REM Notes:
REM   - Incremental: look back 3 trading days from DB watermark; re-run same
REM     option after interruption/failure to resume from breakpoint.
REM   - For first-time full-history backfill use Data\download_kl.py --full
REM     (this script only does incremental).
REM   - DuckDB single file allows only one writer; script checks for a running
REM     ingest process before starting.
REM   - Use --code-prefix to filter by market (see Data\download_kl.py);
REM     this script defaults to all markets.
REM   - PG_DSN defaults to local chan db (same as start_backend.bat): every
REM     ingested code is also upserted into PG `stock` so the K-line page
REM     search dropdown can find it. Override with the PG_DSN env var;
REM     set PG_DSN=none to skip the PG sync entirely (DuckDB only).
REM ============================================================================

REM Always run from repo root
cd /d "%~dp0.."
set "PYTHONPATH=%CD%"
set "PY=.venv\Scripts\python.exe"
set "LOG_DIR=Log"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
if "%DRYRUN%"=="" set "DRYRUN=0"

REM ---------------------------------------------------------------------------
REM PostgreSQL connection (same default as start_backend.bat, override with PG_DSN)
REM After each ingest the code is upserted into PG `stock` (the K-line page search
REM dropdown reads it). PG unreachable only skips that step, ingest still succeeds.
REM Disable the PG sync:  set PG_DSN=none ^& sync_kl.bat
REM (Keep this block ASCII-only: cmd.exe mangles the following lines when a
REM  UTF-8 batch file mixes chcp 65001 with multi-byte REM lines.)
REM ---------------------------------------------------------------------------
if "%PG_DSN%"=="" set "PG_DSN=host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres"
REM pg_dsn_hint: only the state, never the connection string (it carries a password).
REM Keep the none/off/0 test in sync with Data/download_kl.py sync_pg_stock_master().
if /I "%PG_DSN%"=="none" ( set "pg_dsn_hint=disabled (PG_DSN=none)") else if /I "%PG_DSN%"=="off" ( set "pg_dsn_hint=disabled (PG_DSN=off)") else if "%PG_DSN%"=="0" ( set "pg_dsn_hint=disabled (PG_DSN=0)") else ( set "pg_dsn_hint=configured")

REM ---------------------------------------------------------------------------
REM Single-writer guard: DuckDB read/write is mutually exclusive,
REM a second writer process would just wait on the lock
REM ---------------------------------------------------------------------------
powershell -NoProfile -Command "if (Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object {$_.CommandLine -like '*download_kl.py*'}) { exit 0 } else { exit 1 }"
if !errorlevel! EQU 0 (
    echo [!] 检测到已有灌数进程在运行（DuckDB 单写者）:
    powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object {$_.CommandLine -like '*download_kl.py*'} | Select-Object ProcessId,CommandLine | Format-List"
    set /p "ans=仍要继续启动新任务? [y/N] "
    if /I not "!ans!"=="y" ( echo 已取消（等现有任务跑完后再来）& exit /b 1 )
)

:menu
echo.
echo ======== K 线灌数同步（增量续跑）========
echo 1) 所有股票 - 分钟级      K_5M / K_15M / K_30M / K_60M
echo 2) 所有股票 - 日线及以上   K_DAY / K_WEEK / K_MON
echo 3) 指定股票 - 分钟级  
echo 4) 指定股票 - 日线及以上 
echo 5) 全部股票 - 全部级别     (= 1+2, 分钟跑完接着跑日线)
echo 6) 指定股票 - 全部级别     (= 3+4, 分钟跑完接着跑日线)
echo 0) 退出  
set "choice="
set /p "choice=请选择 [0-6]: "
if "!choice!"=="" set "choice=0"

for /f "delims=" %%t in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "ts=%%t"
set "logfile=%LOG_DIR%\sync_kl_!ts!.log"
set "failed=0"

if "!choice!"=="0" ( echo 退出& exit /b 0 )
if "!choice!"=="1" (
    call :ask_sleep 1.0
    call :run_cmd "!logfile!" "'%PY%' Data\download_kl.py --config Data\ingest_config.minute.json --sleep !ask_sleep_result!"
    goto after
)
if "!choice!"=="2" (
    call :ask_sleep 0.5
    call :run_cmd "!logfile!" "'%PY%' Data\download_kl.py --config Data\ingest_config.all_stocks.json --sleep !ask_sleep_result!"
    goto after
)
if "!choice!"=="3" (
    call :ask_code
    if !errorlevel! NEQ 0 goto menu
    call :ask_sleep 1.0
    call :task_single_minute "!ask_code_result!" "!ask_sleep_result!" "!logfile!"
    set /a "failed=!errorlevel!"
    goto after
)
if "!choice!"=="4" (
    call :ask_code
    if !errorlevel! NEQ 0 goto menu
    call :ask_sleep 0.5
    call :task_single_daily "!ask_code_result!" "!ask_sleep_result!" "!logfile!"
    set /a "failed=!errorlevel!"
    goto after
)
if "!choice!"=="5" (
    call :ask_sleep 1.0
    set "sleep_min=!ask_sleep_result!"
    call :ask_sleep 0.5
    set "sleep_day=!ask_sleep_result!"
    call :run_cmd "!logfile!" "'%PY%' Data\download_kl.py --config Data\ingest_config.minute.json --sleep !sleep_min!"
    if !errorlevel! NEQ 0 set /a "failed+=1"
    call :run_cmd "!logfile!" "'%PY%' Data\download_kl.py --config Data\ingest_config.all_stocks.json --sleep !sleep_day!"
    if !errorlevel! NEQ 0 set /a "failed+=1"
    goto after
)
if "!choice!"=="6" (
    call :ask_code
    if !errorlevel! NEQ 0 goto menu
    call :ask_sleep 1.0
    set "sleep_min=!ask_sleep_result!"
    call :ask_sleep 0.5
    set "sleep_day=!ask_sleep_result!"
    call :task_single_minute "!ask_code_result!" "!sleep_min!" "!logfile!"
    if !errorlevel! NEQ 0 set /a "failed+=1"
    call :task_single_daily "!ask_code_result!" "!sleep_day!" "!logfile!"
    if !errorlevel! NEQ 0 set /a "failed+=1"
    goto after
)
echo 无效选择，请重试  
goto menu

:after
if !failed! GTR 0 echo [ERR] 有 !failed! 个阶段/级别失败，详见日志 — 重跑本脚本同一选项即可断点续传
set "again="
set /p "again=再执行下一个任务? [y/N] "
if /I "!again!"=="y" goto menu
exit /b 0

REM ---------------------------------------------------------------------------
REM Input helpers
REM ---------------------------------------------------------------------------
:ask_sleep
REM %1 = default interval
set "def=%~1"
set "val="
set /p "val=限频间隔 --sleep 秒 [回车取默认 %def%]: "
if "!val!"=="" set "val=%def%"
set "ask_sleep_result=!val!"
exit /b 0

:ask_code
REM Output valid code to ask_code_result; non-zero on invalid
set "code="
set /p "code=请输入股票代码（如 sz.000001）: "
if "!code!"=="" ( echo [ERR] 代码不能为空且需带市场前缀，如 sz.000001& exit /b 1 )
echo !code!| findstr "\." >nul
if !errorlevel! NEQ 0 ( echo [ERR] 代码不能为空且需带市场前缀，如 sz.000001& exit /b 1 )
set "ask_code_result=!code!"
exit /b 0

REM ---------------------------------------------------------------------------
REM Command wrapper: print command, tee to log, return its exit code
REM (re-run same option to resume from breakpoint)
REM ---------------------------------------------------------------------------
:run_cmd
set "logfile=%~1"
set "cmdline=%~2"
echo [执行] !cmdline!
echo [PG_DSN] !pg_dsn_hint!
echo [日志] !logfile!
if "%DRYRUN%"=="1" ( echo [dry-run] 跳过实际执行& exit /b 0 )
REM 编码：chcp 65001 只改 cmd 自己的代码页，PowerShell 5.1 的 [Console]::OutputEncoding
REM 默认仍是 GBK —— 它会按 GBK 解码 Python 的 UTF-8 输出，中文全乱码并原样写进日志。
REM 这里显式把 PS 的 stdout 解码设为 UTF-8，并让 Python 子进程也按 UTF-8 输出。
REM （Tee-Object 的 -Encoding 是 PS 6+ 参数，5.1 不支持，故不改 Tee 的输出侧。）
powershell -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $env:PYTHONIOENCODING='utf-8'; & { & !cmdline! 2>&1 | ForEach-Object ToString | Tee-Object -FilePath '!logfile!' -Append; exit $LASTEXITCODE }"
REM 变量名必须避开 task_single_* 的累加器 rc：cmd 的 call 共享同一个环境块，
REM 两处都用 rc 会把累加器冲成当次子命令的退出码（4 个级别全挂只报 2）。
set "cmd_rc=!errorlevel!"
if !cmd_rc! NEQ 0 ( echo [ERR] 退出码 !cmd_rc!（可能有失败任务或已熔断自停）— 重跑本脚本同一选项即可断点续传 ) else ( echo [OK] 完成，日志: !logfile! )
exit /b !cmd_rc!

REM ---------------------------------------------------------------------------
REM Task primitives: options 1-6 are composed from these
REM ---------------------------------------------------------------------------
:task_single_minute
REM %1=code  %2=sleep  %3=logfile -> exit code = number of failed levels
set "code=%~1"
set "sleep_s=%~2"
set "logfile=%~3"
set "fail_n=0"
for %%k in (K_5M K_15M K_30M K_60M) do (
    call :run_cmd "!logfile!" "'%PY%' Data\download_kl.py --code !code! --kl-type %%k --autype QFQ --sleep !sleep_s!"
    if !errorlevel! NEQ 0 set /a "fail_n+=1"
)
exit /b !fail_n!

:task_single_daily
REM %1=code  %2=sleep  %3=logfile -> exit code = number of failed levels
set "code=%~1"
set "sleep_s=%~2"
set "logfile=%~3"
set "fail_n=0"
for %%k in (K_DAY K_WEEK K_MON) do (
    call :run_cmd "!logfile!" "'%PY%' Data\download_kl.py --code !code! --kl-type %%k --autype QFQ --sleep !sleep_s!"
    if !errorlevel! NEQ 0 set /a "fail_n+=1"
)
exit /b !fail_n!
