#!/usr/bin/env bash
# sync_stock_meta.sh — 股票元信息同步启动器（AKShare 多源 → PG 表，openspec: stock-metadata-sync）
#
# 用法:
#   bash Script/sync_stock_meta.sh            # 交互菜单
#   bash Script/sync_stock_meta.sh full       # 免交互：全量同步（全市场·全域·强制刷新）
#   bash Script/sync_stock_meta.sh incr       # 免交互：增量同步（按水位/到期，--no-force）
#   bash Script/sync_stock_meta.sh loop       # 免交互：常驻，每小时只跑到期域
#   DRYRUN=1 bash Script/sync_stock_meta.sh full   # 只打印命令，不真正执行
#
# 说明:
# - 全量 = 不带 --code/--domain 的 --force 同步：identity/profile/industry/
#   snapshot/financial/holders 六域 × 全市场；断点续传（单元 = code×domain），
#   中断/失败后重跑同一命令从未完成单元继续。
# - 幂等：静态字段（ipo_date/found_date）落库侧 IS NULL 保护，重复同步不覆盖。
# - PG_DSN 缺省同 start_backend.sh：host=127.0.0.1 ... dbname=chan ...，可用环境变量覆盖。
# - 注意：后端进程内还有每小时一次的到期域调度器（WebAPI/app.py），手动全量
#   (--force) 与其并发不会坏数据（幂等），但会重复发请求，建议错峰。
# - 退出码: 0=成功 1=有失败单元(重跑续传) 2=PG_DSN 未配置 130=被中断(进度已存)

set -euo pipefail

cd "$(dirname "$0")/.."          # 固定在仓库根目录执行
export PYTHONPATH=.
PY=".venv/bin/python"
LOG_DIR="Log"
mkdir -p "$LOG_DIR"
DRYRUN="${DRYRUN:-0}"

# PostgreSQL 连接（与 start_backend.sh 同默认值，可用 PG_DSN 环境变量覆盖）
PG_DSN="${PG_DSN:-host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres}"
export PG_DSN

ALL_DOMAINS="identity profile industry snapshot financial holders"

usage() {
    sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
}

# ---------------------------------------------------------------------------
# 执行封装：打印命令、tee 日志、按退出码给出处置提示
# ---------------------------------------------------------------------------
run_cmd() {
    local logfile="$1"; shift
    echo "→ 执行: $*"
    echo "→ PG_DSN: ${PG_DSN%%password=*}password=***"
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
    case "$rc" in
        0)   echo "✓ 同步完成，日志: $logfile" ;;
        1)   echo "✗ 有失败单元（已入库部分有效）— 重跑同一命令断点续传，日志: $logfile" ;;
        2)   echo "✗ PG_DSN 未配置/无效，日志: $logfile" ;;
        130) echo "⚠ 被中断 — 断点已持久化，重跑同一命令续传，日志: $logfile" ;;
        *)   echo "✗ 退出码 $rc，日志: $logfile" ;;
    esac
    return "$rc"
}

ask_sleep() {
    local def="$1" val=""
    printf "逐股请求间隔 --sleep 秒 [回车取默认 %s]: " "$def" >&2
    read -r val || val=""
    printf "%s\n" "${val:-$def}"
}

# ---------------------------------------------------------------------------
# 免交互快捷入口（适合 cron / 后台批跑）
# ---------------------------------------------------------------------------
case "${1:-}" in
    full)
        ts="$(date +%Y%m%d_%H%M%S)"
        run_cmd "$LOG_DIR/sync_stock_meta_${ts}.log" \
            "$PY" Data/sync_stock_meta.py --force
        exit $?
        ;;
    incr)
        ts="$(date +%Y%m%d_%H%M%S)"
        run_cmd "$LOG_DIR/sync_stock_meta_${ts}.log" \
            "$PY" Data/sync_stock_meta.py --no-force
        exit $?
        ;;
    loop)
        ts="$(date +%Y%m%d_%H%M%S)"
        run_cmd "$LOG_DIR/sync_stock_meta_${ts}.log" \
            "$PY" Data/sync_stock_meta.py --loop
        exit $?
        ;;
    -h|--help|help)
        usage
        exit 0
        ;;
    "")
        ;;   # 无参数 → 进交互菜单
    *)
        echo "未知参数: $1（可用: full / incr / loop / --help）" >&2
        exit 2
        ;;
esac

# 重复进程保护：避免同一脚本双开重复拉数（后端内置调度器见文件头注释）
if pgrep -f "Data/sync_stock_meta.py" >/dev/null 2>&1; then
    echo "⚠ 检测到已在运行的元信息同步进程:"
    pgrep -fl "Data/sync_stock_meta.py" || true
    read -r -p "仍要继续启动新任务? [y/N] " ans || ans=n
    case "$ans" in
        y|Y) ;;
        *) echo "已取消"; exit 1 ;;
    esac
fi

# ---------------------------------------------------------------------------
# 交互菜单
# ---------------------------------------------------------------------------
while true; do
    cat <<'EOF'

======== 股票元信息同步（AKShare → PG）========
1) 全量同步   全市场 · 全域 · 强制刷新（--force，主功能）
2) 增量同步   全市场 · 全域 · 按水位/到期（--no-force，未到期不发请求）
3) 指定域同步  identity/profile/industry/snapshot/financial/holders（可多选）
4) 指定股票   一只或多只，全域
5) 常驻模式   每小时检查一次，只执行到期域（--loop，Ctrl+C 退出）
0) 退出
EOF
    read -r -p "请选择 [0-5]: " choice || choice=0
    ts="$(date +%Y%m%d_%H%M%S)"
    logfile="$LOG_DIR/sync_stock_meta_${ts}.log"
    rc=0

    case "$choice" in
        0)
            echo "退出"
            exit 0
            ;;

        1)
            sleep_s="$(ask_sleep 0.4)"
            run_cmd "$logfile" "$PY" Data/sync_stock_meta.py --force --sleep "$sleep_s" || rc=$?
            ;;

        2)
            sleep_s="$(ask_sleep 0.4)"
            run_cmd "$logfile" "$PY" Data/sync_stock_meta.py --no-force --sleep "$sleep_s" || rc=$?
            ;;

        3)
            echo "可选域: $ALL_DOMAINS"
            read -r -p "要同步的域（空格分隔）: " doms || doms=""
            dom_args=()
            bad=0
            for d in $doms; do
                case " $ALL_DOMAINS " in
                    *" $d "*) dom_args+=(--domain "$d") ;;
                    *) echo "✗ 未知域: $d"; bad=1 ;;
                esac
            done
            if [[ $bad -ne 0 || ${#dom_args[@]} -eq 0 ]]; then
                echo "✗ 域无效或为空，请重试"
                continue
            fi
            read -r -p "强制刷新? [Y/n]（n=按水位增量）: " f || f=""
            force_arg="--force"
            case "$f" in n|N) force_arg="--no-force" ;; esac
            sleep_s="$(ask_sleep 0.4)"
            run_cmd "$logfile" "$PY" Data/sync_stock_meta.py \
                "${dom_args[@]}" "$force_arg" --sleep "$sleep_s" || rc=$?
            ;;

        4)
            read -r -p "股票代码（空格分隔，可多只，如 sz.000001 600519）: " codes || codes=""
            if [[ -z "${codes// }" ]]; then
                echo "✗ 代码不能为空"
                continue
            fi
            code_args=()
            for c in $codes; do code_args+=(--code "$c"); done
            sleep_s="$(ask_sleep 0.4)"
            run_cmd "$logfile" "$PY" Data/sync_stock_meta.py \
                "${code_args[@]}" --force --sleep "$sleep_s" || rc=$?
            ;;

        5)
            sleep_s="$(ask_sleep 0.4)"
            echo "提示: 常驻模式下按 Ctrl+C 优雅退出（进度已持久化）"
            run_cmd "$logfile" "$PY" Data/sync_stock_meta.py --loop --sleep "$sleep_s" || rc=$?
            ;;

        *)
            echo "无效选择，请重试"
            continue
            ;;
    esac

    if [[ $rc -ne 0 ]]; then
        echo "本次退出码 $rc（详见上方提示）"
    fi

    read -r -p "再执行下一个任务? [y/N] " again || again=n
    case "$again" in
        y|Y) ;;
        *) exit "$rc" ;;
    esac
done
