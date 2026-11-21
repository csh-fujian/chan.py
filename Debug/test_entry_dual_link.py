# -*- coding: utf-8 -*-
"""
双链路介入点口径一致对比（chan-entry-point-candidate tasks 6.2）

两条链路对同一标的同一时点的介入点判定必须一致（design D6 双链路约定）：

    A. 落库链路   `incremental_engine._extract_bsp_rows`
        trigger_step CChan + `_compute_sub_for_l1` 旁路子级 →
        **WebAPI 侧调用共享核心** `entry_point_result`（每行独立调用）
    B. 序列化链路 `/api/klines`（chan_service._compute_chan + serialize_chan）
        批量模式 CChan（lv_list 单级别）+ compute_sub_chan 子级 →
        `_serialize_bsp` **读内核 feature**（`attach_sub_bspoint_and_annotate`
        补挂子级容器并补跑 `_annotate_entry_point`）

两条链路计算机制不同（步进 vs 批量）、子级构建路径不同（旁路全量 vs
独立 CChan），但介入列的判定核心是同一个模块级函数，配置经
`chan_config_store.build_conf()` 同源，故逐 (time_key, bsp_type) 对齐。

断言：
    1. 行集合一致：两链路的 (time_key, primary_type) 键集合完全相同
       （买卖点成立性不受介入开关影响，互为对方的等价性对照）
    2. 介入列一致：每个键上的 (entry_point, entry_method, entry_level)
       完全相同（含未命中行三列 (False, None, None)）
    3. **开态非零命中**：至少一个被测标的出现 entry_point=True 的行。
       没有这条断言时，「两链路都恒 0」会伪装成「口径一致」——2026-11-09
       冒烟即因此漏掉了一个真实缺口：判定核心的窗口映射只认多级别构建的
       `sub_kl_list`，两条生产链路的单级别构建下恒空 → 恒 0 命中。
       现已在 `BSPointList.sub_time_span` 补父级时间轴回退口径，本断言防再犯。
    4. 关态一致：开关全关时两链路全部 (False, None, None)（零影响对照）

用法（Windows 本机 PG12，库 chan）：
    PG_DSN="host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres" \
        PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe Debug/test_entry_dual_link.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PG_DSN = os.environ.get(
    "PG_DSN", "host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres")
os.environ["PG_DSN"] = PG_DSN

import psycopg2  # noqa: E402

# 被测标的：日线 + 30m 子级均齐备。sz.000027 在介入全开下有 4 个历史命中
# （2023-07-14 ~ 2023-12-15，qjt 1 层），用于非零命中断言；sz.000001 作为
# 零命中对照（其历史点全部低于水位线，属正常数据特征）。
CODES = ["sz.000001", "sz.000027"]
PERIOD = "D"

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILURES.append(name)


def fetch_pg_rows(code):
    """链路 A 的结果：PG bsp_index 介入三列。"""
    conn = psycopg2.connect(PG_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT time_key, bsp_type, entry_point, entry_method, entry_level
                     FROM bsp_index
                    WHERE code = %s AND kl_type = 'D' AND autype = 'QFQ'
                    ORDER BY time_key""",
                (code,),
            )
            return cur.fetchall()
    finally:
        conn.close()


def serialize_link_rows(code):
    """链路 B 的结果：chan_service 同款链路（不经 HTTP，直接调函数）。

    复刻 main.py /api/klines 的调用序列：_compute_chan（批量模式）+
    compute_sub_chan（子级 CChan）+ serialize_chan。
    """
    from WebAPI.chan_service import _compute_chan, compute_sub_chan, _resolve_kl_type, _resolve_data_src
    from WebAPI.serializer import serialize_chan

    kl_type = _resolve_kl_type(PERIOD)
    data_src = _resolve_data_src(PERIOD)
    chan = _compute_chan(code, kl_type, data_src)
    sub_chan = compute_sub_chan(code, kl_type)
    from WebAPI.chan_service import resolve_sub_level
    sub_kl_type = resolve_sub_level(kl_type) if sub_chan is not None else None
    result = serialize_chan(chan, kl_type, sub_chan=sub_chan, sub_kl_type=sub_kl_type)
    return list(result["bsp"])


def run_pair(code, overrides):
    """开指定 overrides 后跑两链路并对比，返回 (pg_rows, ser_rows)。"""
    from WebAPI import incremental_engine
    from WebAPI.chan_config_store import save

    save(dict(overrides), "standard", updated_by="entry-dual-link-test")

    # 链路 A：落库（指纹变化会自动转全量重算）
    r = incremental_engine.recompute_stock(code, PERIOD)
    if r is None:
        print(f"  ✗ {code} recompute 返回 None（DuckDB 无数据？）")
        FAILURES.append(f"{code} recompute None")
        return None, None
    pg_rows = fetch_pg_rows(code)

    # 链路 B：序列化（chan_stable_prefix 缓存以配置指纹为键，指纹随 save 变化，
    # 但本脚本直接调 compute 函数不走缓存读写，无串味风险）
    ser_rows = serialize_link_rows(code)
    return pg_rows, ser_rows


def compare(pg_rows, ser_rows, label):
    """对比两链路，返回命中行数（供非零命中断言汇总）。"""
    print(f"\n[{label}] 对比（PG {len(pg_rows)} 行 / 序列化 {len(ser_rows)} 点）")

    def ser_rows_by_date():
        """序列化点按**日期**索引（日线场景）。

        不能按 epoch 秒对齐：`CTime.set_timestamp` 的 auto 语义把日线 00:00:00
        调整为当天 23:59 取时间戳（保证日线 > 其下分钟线），而 PG time_key 存
        00:00:00——同一根 K 线两边差近 86400 秒。日期对齐才是两条链路的公共键。
        """
        import datetime as _dt
        tz8 = _dt.timezone(_dt.timedelta(hours=8))
        out = {}
        for b in ser_rows:
            d = _dt.datetime.fromtimestamp(b["t"] / 1000, tz=tz8).strftime("%Y-%m-%d")
            out[d] = b
        return out

    ser_by_date = ser_rows_by_date()
    missing = []
    for tk, bsp_type, *_ in pg_rows:
        d = tk[:10]
        b = ser_by_date.get(d)
        if b is None:
            missing.append((tk, bsp_type, "日期不在序列化结果中"))
            continue
        if bsp_type not in b["types"]:
            missing.append((tk, bsp_type, f"类型不在 types={b['types']}"))
    check("行集合一致（PG 每行的 (time_key, primary_type) 都在序列化结果中）",
          not missing, str(missing[:5]))

    # 2. 介入列逐键对比（按日期对齐，同上）
    diffs = []
    for tk, bsp_type, e_pg, m_pg, l_pg in pg_rows:
        b = ser_by_date.get(tk[:10])
        if b is None:
            continue  # 行集合差异已在上面报过
        e_ser = bool(b.get("entry", False))
        m_ser = b.get("entry_method")
        l_ser = b.get("entry_level")
        # 口径归一：共享核心 miss 时返回 (False, None, 0)（level=0 而非 None），
        # 序列化侧 `_annotate_entry_point` 未命中只写 entry_hit=False、
        # method/level 键不写（None）。0 与 None 语义相同（未命中/无层数），
        # 对比前统一成 None。
        l_pg_n = None if l_pg == 0 else l_pg
        l_ser_n = None if l_ser == 0 else l_ser
        if (e_pg, m_pg, l_pg_n) != (e_ser, m_ser, l_ser_n):
            diffs.append((tk, bsp_type, (e_pg, m_pg, l_pg), (e_ser, m_ser, l_ser)))
    check("介入列逐行一致（entry/method/level）", not diffs, str(diffs[:5]))

    # 3. 命中统计打印
    hits_pg = [r for r in pg_rows if r[2]]
    hits_ser = [b for b in ser_rows if b.get("entry")]
    print(f"    命中：PG {len(hits_pg)} 行 / 序列化 {len(hits_ser)} 点")
    if hits_pg:
        print(f"    PG 命中明细（前 5）：{[(r[0], r[3], r[4]) for r in hits_pg[:5]]}")
    return len(hits_pg)


def main():
    ENTRY_ON = {
        "bsp1_entry": True, "bsp1_entry_qjt": True, "bsp1_entry_qjt_depth": 2,
        "bsp1_entry_aux": True,
        "bsp2_entry": True, "bsp2_entry_qjt": True, "bsp2_entry_qjt_depth": 2,
        "bsp2_entry_aux": True,
        "bsp3_entry": True, "bsp3_entry_qjt": True, "bsp3_entry_qjt_depth": 2,
        "bsp3_entry_aux": True,
    }

    try:
        # ---- 1. 开态对比 ----
        print("\n[1] 介入全开（12 键）双链路对比")
        total_hits = 0
        for code in CODES:
            pg_on, ser_on = run_pair(code, ENTRY_ON)
            if pg_on is not None:
                total_hits += compare(pg_on, ser_on, f"开态·{code}")

        # 非零命中断言（2026-11-09 修复记录）：两链路都恒 0 时上面的「一致」
        # 断言无鉴别力。窗口映射回退缺失曾使两条生产链路同时恒 0，而多级别
        # 构建有 4 个命中——必须有一条断言能区分「口径一致」与「口径一起错」。
        check(f"开态至少一个标的出现非零命中（合计 {total_hits}）",
              total_hits > 0,
              "两链路同为 0 无法证伪口径错误（检查 sub_time_span 回退口径）")

        # ---- 2. 关态对比 ----
        print("\n[2] 介入全关（默认）双链路对比")
        for code in CODES:
            pg_off, ser_off = run_pair(code, {})
            if pg_off is not None:
                compare(pg_off, ser_off, f"关态·{code}")
                all_off_pg = all(not r[2] for r in pg_off)
                all_off_ser = all(not b.get("entry") for b in ser_off)
                check(f"关态零命中（PG·{code}）", all_off_pg,
                      str([r for r in pg_off if r[2]][:3]))
                check(f"关态零命中（序列化·{code}）", all_off_ser,
                      str([b for b in ser_off if b.get("entry")][:3]))
    finally:
        # 恢复默认配置（不留测试开关）
        from WebAPI.chan_config_store import save
        save({}, "standard", updated_by="entry-dual-link-test")

    print()
    if FAILURES:
        print(f"✗ {len(FAILURES)} 项失败：{FAILURES}")
        return 1
    print("✓ 双链路口径一致（含开态非零命中）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
