#!/usr/bin/env bash
# sync_kl.sh — K 线灌数同步任务交互式启动器（增量续跑）
#
# 用法:
#   bash Script/sync_kl.sh                 # 交互菜单
#   DRYRUN=1 bash Script/sync_kl.sh        # 只打印将执行的命令，不真正执行（试跑）
#
# 说明:
# - 增量语义: 按库内水位回看 3 个交易日续拉；中断/失败后重跑同一选项即断点续传。
# - 首次全历史回填请改用 Data/download_kl.py 加 --full（本脚本只做增量）。
# - DuckDB 单文件只允许一个写进程，脚本启动前会检查是否已有灌数进程在跑。
# - 可用 --code-prefix 按市场过滤（见 Data/download_kl.py），本脚本默认全市场。

set -euo pipefail

cd "$(dirname "$0")/.."          # 固定在仓库根目录执行
export PYTHONPATH=.
PY=".venv/bin/python"
LOG_DIR="Log"
mkdir -p "$LOG_DIR"
DRYRUN="${DRYRUN:-0}"

# ---------------------------------------------------------------------------
# 单写者保护：DuckDB 读写互斥，第二个写进程只会互相等锁
# ---------------------------------------------------------------------------
if pgrep -f "Data/download_kl.py" >/dev/null 2>&1; then
    echo "⚠ 检测到已有灌数进程在运行（DuckDB 单写者）:"
    pgrep -fl "Data/download_kl.py" || true
    read -r -p "仍要继续启动新任务? [y/N] " ans || ans=n
    case "$ans" in
        y|Y) ;;
        *) echo "已取消（等现有任务跑完后再来）"; exit 1 ;;
    esac
fi

# ---------------------------------------------------------------------------
# 执行封装：打印命令、tee 日志、失败返回其退出码（重跑同一选项即断点续传）
# ---------------------------------------------------------------------------
run_cmd() {
    local logfile="$1"; shift
    echo "→ 执行: $*"
    echo "→ 日志: $logfile"
    if [[ "$DRYRUN" == "1" ]]; then
        echo "[dry-run] 跳过实际执行"
        return 0
    fi
    local rc=0
    set +e
    "$@" 2>&1 | tee -a "$logfile"
    rc=$?
    set -e
    if [[ $rc -ne 0 ]]; then
        echo "✗ 退出码 $rc（可能有失败任务或已熔断自停）— 重跑本脚本同一选项即可断点续传"
    else
        echo "✓ 完成，日志: $logfile"
    fi
    return "$rc"
}

ask_sleep() {
    # $1 = 默认间隔；提示写 stderr，避免被 $() 捕获
    local def="$1" val=""
    printf "限频间隔 --sleep 秒 [回车取默认 %s]: " "$def" >&2
    read -r val || val=""
    printf "%s\n" "${val:-$def}"
}

ask_code() {
    # 输出合法代码；非法（空/无市场前缀）返回非 0
    local code=""
    read -r code || code=""
    if [[ -z "$code" || "$code" != *.* ]]; then
        echo "✗ 代码不能为空且需带市场前缀，如 sz.000001" >&2
        return 1
    fi
    printf "%s\n" "$code"
}

# ---------------------------------------------------------------------------
# 任务原语：选项 1~6 由它们组合而成
# ---------------------------------------------------------------------------
task_all_minute() {   # $1=sleep  $2=logfile
    run_cmd "$2" "$PY" Data/download_kl.py \
        --config Data/ingest_config.minute.json --sleep "$1"
}

task_all_daily() {    # $1=sleep  $2=logfile
    run_cmd "$2" "$PY" Data/download_kl.py \
        --config Data/ingest_config.all_stocks.json --sleep "$1"
}

task_single_minute() {  # $1=code  $2=sleep  $3=logfile → 失败级别数作为退出码
    local code="$1" sleep_s="$2" logfile="$3" kt rc=0
    for kt in K_5M K_15M K_30M K_60M; do
        run_cmd "$logfile" "$PY" Data/download_kl.py \
            --code "$code" --kl-type "$kt" --autype QFQ --sleep "$sleep_s" || rc=$((rc + 1))
    done
    return "$rc"
}

task_single_daily() {   # $1=code  $2=sleep  $3=logfile → 失败级别数作为退出码
    local code="$1" sleep_s="$2" logfile="$3" kt rc=0
    for kt in K_DAY K_WEEK K_MON; do
        run_cmd "$logfile" "$PY" Data/download_kl.py \
            --code "$code" --kl-type "$kt" --autype QFQ --sleep "$sleep_s" || rc=$((rc + 1))
    done
    return "$rc"
}

# ---------------------------------------------------------------------------
# 交互菜单
# ---------------------------------------------------------------------------
while true; do
    cat <<'EOF'

======== K 线灌数同步（增量续跑）========
1) 所有股票 · 分钟级      K_5M / K_15M / K_30M / K_60M
2) 所有股票 · 日线及以上   K_DAY / K_WEEK / K_MON
3) 指定股票 · 分钟级
4) 指定股票 · 日线及以上
5) 所有股票 · 全部级别     （= 1 + 2：分钟跑完接着跑日线）
6) 指定股票 · 全部级别     （= 3 + 4：分钟跑完接着跑日线）
0) 退出
EOF
    read -r -p "请选择 [0-6]: " choice || choice=0
    ts="$(date +%Y%m%d_%H%M%S)"
    logfile="$LOG_DIR/sync_kl_${ts}.log"
    failed=0

    case "$choice" in
        0)
            echo "退出"
            exit 0
            ;;

        1)
            sleep_s="$(ask_sleep 1.0)"
            task_all_minute "$sleep_s" "$logfile" || true
            ;;

        2)
            sleep_s="$(ask_sleep 0.5)"
            task_all_daily "$sleep_s" "$logfile" || true
            ;;

        3)
            code="$(ask_code)" || continue
            sleep_s="$(ask_sleep 1.0)"
            task_single_minute "$code" "$sleep_s" "$logfile" || failed=$?
            ;;

        4)
            code="$(ask_code)" || continue
            sleep_s="$(ask_sleep 0.5)"
            task_single_daily "$code" "$sleep_s" "$logfile" || failed=$?
            ;;

        5)
            sleep_min="$(ask_sleep 1.0)"
            sleep_day="$(ask_sleep 0.5)"
            task_all_minute "$sleep_min" "$logfile" || failed=$((failed + 1))
            task_all_daily "$sleep_day" "$logfile" || failed=$((failed + 1))
            ;;

        6)
            code="$(ask_code)" || continue
            sleep_min="$(ask_sleep 1.0)"
            sleep_day="$(ask_sleep 0.5)"
            task_single_minute "$code" "$sleep_min" "$logfile" || failed=$((failed + 1))
            task_single_daily "$code" "$sleep_day" "$logfile" || failed=$((failed + 1))
            ;;

        *)
            echo "无效选择，请重试"
            continue
            ;;
    esac

    if [[ $failed -gt 0 ]]; then
        echo "✗ 有 $failed 个阶段/级别失败，详见日志 — 重跑本脚本同一选项即可断点续传"
    fi

    read -r -p "再执行下一个任务? [y/N] " again || again=n
    case "$again" in
        y|Y) ;;
        *) exit 0 ;;
    esac
done
