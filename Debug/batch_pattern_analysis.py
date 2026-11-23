# 批量形态信号分析脚本（任务：全库买卖点信号盘点）
#
# 对 Data/kl_store.duckdb 中全部日线股票跑完整缠论计算 + 13 种形态检测
# （8 买向 + 5 卖向），结果落 PG pattern_signal 表（幂等 upsert），
# 并输出汇总 JSON 供人工核对。
import sys
import json
import time

sys.path.insert(0, '.')

from duckdb import connect as duck_connect
from WebAPI.chan_service import _compute_chan, _resolve_kl_type
from WebAPI.pattern_detector import run_pattern_detection
from WebAPI.pattern_store import upsert_pattern_rows

DUCKDB_PATH = 'Data/kl_store.duckdb'


def main() -> None:
    conn = duck_connect(DUCKDB_PATH, read_only=True)
    codes = [r[0] for r in conn.execute(
        "SELECT DISTINCT code FROM kline WHERE kl_type='K_DAY' ORDER BY code"
    ).fetchall()]
    conn.close()

    kl_type = _resolve_kl_type('1d')
    # kl_type 词表与增量引擎同口径：pattern_signal.kl_type 存 canonical 词表值（日线='D'，
    # 见 incremental_engine.upsert_pattern_rows(code, canonical, ...)），不是枚举 value
    from WebAPI.chan_service import PERIOD_CANONICAL
    canonical = PERIOD_CANONICAL[kl_type]
    summary: dict[str, list] = {}
    failed: list[tuple[str, str]] = []
    t0 = time.time()

    for i, code in enumerate(codes, 1):
        try:
            chan = _compute_chan(code, kl_type, 'custom:DuckDBAPI.CDuckDB')
            rows = run_pattern_detection(chan, kl_type)
            if rows:
                upsert_pattern_rows(code, canonical, 'QFQ', rows)
            for r in rows:
                # row 结构见 pattern_detector.hit_to_row（12 元组）：
                # (pattern_type, pattern_date, confirm_time_key, price,
                #  ref_high, ref_low, score, qual, invalid, veto, detail_json, direction)
                summary.setdefault(r[0], []).append({
                    'code': code,
                    'date': r[1],
                    'score': r[6],
                })
            print(f"[{i}/{len(codes)}] {code}: {len(rows)} rows", flush=True)
        except Exception as e:  # noqa: BLE001 单只失败不阻断批处理
            failed.append((code, str(e)))
            print(f"[{i}/{len(codes)}] {code}: FAILED {e}", flush=True)

    elapsed = time.time() - t0
    out = {
        'total_codes': len(codes),
        'failed': failed,
        'elapsed_sec': round(elapsed, 1),
        'by_pattern': {
            k: {'count': len(v), 'samples': sorted(v, key=lambda x: x['date'], reverse=True)[:10]}
            for k, v in summary.items()
        },
    }
    with open('Log/pattern_batch_summary.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"done in {elapsed:.1f}s, failed={len(failed)}, summary -> Log/pattern_batch_summary.json")


if __name__ == '__main__':
    main()
