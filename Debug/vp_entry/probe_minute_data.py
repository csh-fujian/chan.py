# -*- coding: utf-8 -*-
"""探测 akshare 东财 5 分钟接口历史深度（tasks 1.1）。

抽 3 只不同上市年限的股票，拉全历史 5 分钟数据，记录：
最早可得日期、行数、拉取耗时、首末日分钟数（数据完整性）。
结论写入 Debug/vp_entry/data_availability.md。
"""

import time

import akshare as ak

# (code, 说明)
SAMPLES = [
    ("000001", "平安银行, 1991 上市, 老股"),
    ("300750", "宁德时代, 2018 上市, 中龄股"),
    ("301601", "2024-2025 年上市, 次新股（若代码无效则跳过）"),
]


def probe(symbol: str, note: str) -> dict:
    t0 = time.time()
    try:
        df = ak.stock_zh_a_hist_min_em(symbol=symbol, period="5", adjust="qfq")
    except Exception as e:
        return {"symbol": symbol, "note": note, "error": str(e)}
    elapsed = time.time() - t0
    if df is None or len(df) == 0:
        return {"symbol": symbol, "note": note, "error": "empty result", "elapsed": elapsed}
    first_day = str(df.iloc[0]["时间"])[:10]
    last_day = str(df.iloc[-1]["时间"])[:10]
    n_days = df["时间"].astype(str).str[:10].nunique()
    # 首日与末日分钟 bar 数（完整交易日 48 根）
    first_day_bars = int((df["时间"].astype(str).str[:10] == first_day).sum())
    last_day_bars = int((df["时间"].astype(str).str[:10] == last_day).sum())
    return {
        "symbol": symbol,
        "note": note,
        "error": None,
        "elapsed_s": round(elapsed, 1),
        "rows": len(df),
        "first_day": first_day,
        "last_day": last_day,
        "n_days": n_days,
        "first_day_bars": first_day_bars,
        "last_day_bars": last_day_bars,
    }


def main():
    results = []
    for symbol, note in SAMPLES:
        print(f"probing {symbol} ...")
        r = probe(symbol, note)
        results.append(r)
        print(r)

    # 汇总写 markdown
    lines = [
        "# akshare 东财 5 分钟接口历史深度探测报告",
        "",
        f"探测时间: {time.strftime('%Y-%m-%d %H:%M:%S')}  akshare 版本: {ak.__version__}",
        "",
        "接口: `ak.stock_zh_a_hist_min_em(symbol, period='5', adjust='qfq')`（东方财富源）",
        "",
        "| 代码 | 说明 | 状态 | 耗时(s) | 行数 | 最早日期 | 最晚日期 | 交易日数 | 首日bar数 | 末日bar数 |",
        "|------|------|------|---------|--------|----------|----------|----------|-----------|-----------|",
    ]
    for r in results:
        if r.get("error"):
            lines.append(
                f"| {r['symbol']} | {r['note']} | 失败: {r['error']} | - | - | - | - | - | - | - |"
            )
        else:
            lines.append(
                f"| {r['symbol']} | {r['note']} | OK | {r['elapsed_s']} | {r['rows']} "
                f"| {r['first_day']} | {r['last_day']} | {r['n_days']} "
                f"| {r['first_day_bars']} | {r['last_day_bars']} |"
            )
    print("\n".join(lines))
    with open("Debug/vp_entry/data_availability.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\nreport written to Debug/vp_entry/data_availability.md")


if __name__ == "__main__":
    main()
