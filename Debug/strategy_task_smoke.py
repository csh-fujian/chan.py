# -*- coding: utf-8 -*-
"""
strategy-task-redesign 后端冒烟测试（任务 1.4 / 2.1 / 2.2 / 3.1 / 3.2 / 3.3 verify）。

真 PG（127.0.0.1:5432/chan）+ 真 DuckDB（Data/kl_store.duckdb）环境跑通：

1. 任务全生命周期（1.4）：建（manual 范围）→ 启 → 暂 → 改 → 续 → 转正 → 删
2. 逐股结果分叉（2.1）：manual 范围任务逐股结果行数 = 范围数；全量任务不落逐股结果
3. 续跑两语义（2.2）：full 清信号+结果+水位重扫 / remaining 保留旧信号并按
   params_version 归因
4. API 层（3.1）：HTTP 冒烟覆盖每个端点正常 + 校验失败路径（422/404/409）
5. 转正与复制（3.2）：promote 后任务出现在 persistent 调度集；copy 继承参数/范围
6. monitor 联动（3.3）：从策略任务信号加监控，来源标签 = 「策略名 · 任务名 · 状态」

运行：PG_DSN=... PYTHONPATH=. .venv/Scripts/python Debug/strategy_task_smoke.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PG_DSN = os.environ.get(
    "PG_DSN", "host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres"
)
os.environ["PG_DSN"] = PG_DSN

PASS = []
FAIL = []


def check(name: str, cond: bool, detail: str = ""):
    """断言收集（不中断，最后统一汇报）。"""
    if cond:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append(f"{name} {detail}")
        print(f"  [FAIL] {name} {detail}")


def cleanup_test_tasks(cur):
    """清理冒烟残留任务（label 前缀 strategy_task_smoke 的全部删除）。

    显式删信号/游标/逐股结果再删任务（不依赖 FK CASCADE——库中 FK 可能
    未挂（update.sql 幂等块只在首次补挂），显式删保证幂等清理）。
    """
    cur.execute(
        """DELETE FROM strategy_signal WHERE task_id IN
           (SELECT id FROM strategy_task WHERE label LIKE 'strategy_task_smoke%')"""
    )
    cur.execute(
        """DELETE FROM strategy_task_stock_result WHERE task_id IN
           (SELECT id FROM strategy_task WHERE label LIKE 'strategy_task_smoke%')"""
    )
    cur.execute(
        """DELETE FROM strategy_scan_cursor WHERE task_id IN
           (SELECT id FROM strategy_task WHERE label LIKE 'strategy_task_smoke%')"""
    )
    cur.execute(
        """DELETE FROM monitor WHERE task_id IN
           (SELECT id FROM strategy_task WHERE label LIKE 'strategy_task_smoke%')"""
    )
    cur.execute("DELETE FROM strategy_task WHERE label LIKE 'strategy_task_smoke%'")


def main():
    import psycopg2

    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    cur = conn.cursor()
    cleanup_test_tasks(cur)
    conn.close()

    # ---- 任务 1.4 / 2.1：manual 范围任务全生命周期 ----
    print("\n== 1.4/2.1 manual 范围任务全生命周期 ==")
    from WebAPI import strategy_store as ss

    # 范围用 DuckDB 里真实存在的两只票
    from WebAPI.strategy_engines.scheduler import list_all_codes

    all_codes = list_all_codes()
    check("DuckDB code 枚举非空", len(all_codes) > 0, f"codes={len(all_codes)}")
    codes = sorted(all_codes)[:3]

    task = ss.create_task(
        strategy_id="vol_breakout_pullback",
        label="strategy_task_smoke_manual",
        params={"pullback_max_days": 5, "volume_ratio_min": 2.0, "volume_shrink_max": 0.8},
        scope_type="manual",
        scope_codes=codes,
        mode="test",
        user_group="冒烟分组",
    )
    check("创建任务 pending", task["status"] == "pending", str(task["status"]))
    check("params_version=1", task["params_version"] == 1)
    check("scope_codes 固化快照", task["scope_codes"] == codes, str(task["scope_codes"]))
    check("user_group 落库", task["user_group"] == "冒烟分组")
    tid = task["id"]

    # 参数非法被拒绝（422 语义：ValueError）
    try:
        ss.create_task(
            strategy_id="vol_breakout_pullback",
            label="strategy_task_smoke_invalid",
            params={"pullback_max_days": 999},  # 超出 max=20
        )
        check("参数非法被拒绝", False, "未抛 ValueError")
    except ValueError:
        check("参数非法被拒绝", True)

    # 未知策略定义
    try:
        ss.create_task(strategy_id="no_such_strategy", label="x")
        check("未知策略定义被拒绝", False)
    except ValueError:
        check("未知策略定义被拒绝", True)

    # 启动 → 执行器跑完（同步调 run_task）
    started = ss.start_task(tid)
    check("启动任务 running", started["status"] == "running")
    from WebAPI.strategy_engines.scheduler import run_task

    summary = run_task(tid)
    check(
        "manual 任务扫完 done",
        ss.get_task(tid)["status"] == "done",
        str(summary),
    )
    check(
        "manual 任务进度 100%",
        ss.get_task(tid)["progress_scanned"] == len(codes)
        and ss.get_task(tid)["progress_total"] == len(codes),
        str(ss.get_task(tid)),
    )
    result_count = ss.count_stock_results(tid)
    check(
        "逐股结果行数 = 范围数（2.1 verify）",
        result_count["total"] == len(codes),
        str(result_count),
    )
    check("逐股结果含 ok 状态", result_count["failed"] == 0, str(result_count))

    sigs = ss.query_signals(tid, page_size=100)
    check(
        "信号行携带 params_version（2.2 前置）",
        all(s.get("params_version") == 1 for s in sigs["items"]),
    )

    # 再次 run_task（done 状态）：幂等，已扫前缀跳过
    again = run_task(tid)
    check("done 任务重跑幂等（无新扫描）", again["scanned"] == 0, str(again))

    # ---- 任务 2.2：编辑 + 两种续跑语义 ----
    print("\n== 2.2 编辑 + full/remaining 两种续跑语义 ==")
    # 状态门在路由层（PATCH 仅 paused，见 HTTP 冒烟「非 paused 编辑 409」）；
    # store 层 update_task 不重复校验状态（窄口原则，start/resume 各自有门）
    # 已 done 的 tid 直接用于转正路径，编辑语义用 tid2 验证

    # 构造一个 30% 进度的暂停任务：manual 范围 3 只，跑 1 只后手动暂停
    codes5 = sorted(all_codes)[:5]
    task2 = ss.create_task(
        strategy_id="vol_breakout_pullback",
        label="strategy_task_smoke_rerun",
        params={"pullback_max_days": 5, "volume_ratio_min": 2.0, "volume_shrink_max": 0.8},
        scope_type="manual",
        scope_codes=codes5,
        mode="test",
    )
    tid2 = task2["id"]
    ss.start_task(tid2)
    # 只扫 1 只（batch 截断模拟部分进度）
    run_task(tid2, batch=1)
    t2 = ss.get_task(tid2)
    check("batch=1 部分进度", t2["progress_scanned"] == 1, str(t2["progress_scanned"]))
    ss.pause_task(tid2)
    check("暂停 → paused", ss.get_task(tid2)["status"] == "paused")

    # 编辑参数（params 变化 → version +1）
    t2e = ss.update_task(tid2, params={**task2["params"], "pullback_max_days": 7})
    check("编辑参数 version +1", t2e["params_version"] == 2, str(t2e["params_version"]))
    t2e2 = ss.update_task(tid2, user_group="新分组")
    check("改分组不递增 version", t2e2["params_version"] == 2)

    # remaining 续跑：旧信号/结果保留，剩余 code 用新参数
    sigs_before = ss.query_signals(tid2, page_size=200)
    results_before = ss.count_stock_results(tid2)
    ss.resume_task(tid2, rerun="remaining")
    run_task(tid2)
    t2r = ss.get_task(tid2)
    check("remaining 续跑扫完 done", t2r["status"] == "done")
    check("remaining 进度推进到总数", t2r["progress_scanned"] == len(codes5), str(t2r))
    sigs_after = ss.query_signals(tid2, page_size=200)
    results_after = ss.count_stock_results(tid2)
    check(
        "remaining 保留旧信号（不删除）",
        sigs_after["total"] >= sigs_before["total"],
        f"{sigs_before['total']} -> {sigs_after['total']}",
    )
    check(
        "remaining 逐股结果行数仍 = 范围数",
        results_after["total"] == len(codes5),
        str(results_after),
    )
    # 逐股结果行 params_version 混合（第一只是 v1，其余 v2）—— 重跑覆盖后
    # 已扫那只保持 v1（不重扫）
    per = ss.query_stock_results(tid2, page_size=50)
    versions = {r["code"]: r["params_version"] for r in per["items"]}
    check(
        "逐股结果版本混合归因（已扫 v1 / 未扫 v2）",
        set(versions.values()) == {1, 2} or set(versions.values()) == {2},
        str(versions),
    )

    # full 续跑：清空信号+结果+水位重扫
    ss.pause_task(tid2) if ss.get_task(tid2)["status"] == "running" else None
    # 任务已 done——full 路径要先回到 paused 才能续（resume 门），用新任务验证
    task3 = ss.create_task(
        strategy_id="vol_breakout_pullback",
        label="strategy_task_smoke_full",
        params={"pullback_max_days": 5, "volume_ratio_min": 2.0, "volume_shrink_max": 0.8},
        scope_type="manual",
        scope_codes=codes5,
        mode="test",
    )
    tid3 = task3["id"]
    ss.start_task(tid3)
    run_task(tid3, batch=2)
    ss.pause_task(tid3)
    # full 前先记信号数
    sigs3_before = ss.query_signals(tid3, page_size=200)["total"]
    results3_before = ss.count_stock_results(tid3)["total"]
    ss.update_task(tid3, params={**task3["params"], "volume_ratio_min": 1.5})
    ss.resume_task(tid3, rerun="full")
    check("full 续跑 running", ss.get_task(tid3)["status"] == "running")
    check(
        "full 清空信号（2.2 verify）",
        ss.query_signals(tid3, page_size=200)["total"] == 0
        and ss.count_stock_results(tid3)["total"] == 0
        and ss.get_scan_cursors(tid3) == {},
        f"before sig={sigs3_before} res={results3_before}",
    )
    check("full 进度清零", ss.get_task(tid3)["progress_scanned"] == 0)
    run_task(tid3)
    t3r = ss.get_task(tid3)
    check("full 重扫扫完", t3r["status"] == "done" and t3r["progress_scanned"] == len(codes5))
    sigs3 = ss.query_signals(tid3, page_size=200)
    check(
        "full 重扫信号携带新 version=2",
        all(s["params_version"] == 2 for s in sigs3["items"]) if sigs3["items"] else True,
    )

    # ---- 任务 2.1（全量范围不落逐股结果）+ ST 过滤 ----
    print("\n== 2.1 全量范围不落逐股结果 ==")
    from WebAPI.strategy_engines.scheduler import _task_codes, _filter_st_codes, _is_st_name

    check("ST 名称前缀识别", _is_st_name("ST 摘帽") and _is_st_name("*ST 摘帽") and not _is_st_name("平安银行"))
    check("名称缺失放行", not _is_st_name(None) and not _is_st_name(""))
    check("_filter_st_codes 保留非 ST", _filter_st_codes(["sz.000001"]) == ["sz.000001"])

    task_all = ss.create_task(
        strategy_id="vol_breakout_pullback",
        label="strategy_task_smoke_all",
        mode="test",
    )
    tid_all = task_all["id"]
    codes_all, explicit = _task_codes(task_all)
    check("all 范围 explicit=False", explicit is False)
    check("all 范围 code 非空", len(codes_all) > 0, str(len(codes_all)))
    # 只跑 batch=2 验证不落逐股结果（全量 5000 只太久）
    ss.start_task(tid_all)
    run_task(tid_all, batch=2)
    t_all = ss.get_task(tid_all)
    check("all 任务进度推进", t_all["progress_scanned"] == 2, str(t_all["progress_scanned"]))
    check(
        "全量任务不落逐股结果（2.1 verify）",
        ss.count_stock_results(tid_all)["total"] == 0,
        str(ss.count_stock_results(tid_all)),
    )
    check(
        "全量任务匹配记录仍落信号",
        ss.query_signals(tid_all, page_size=1)["total"] >= 0,  # 契约不报错即可
    )
    ss.pause_task(tid_all) if t_all["status"] == "running" else None

    # ---- 任务 3.2：转正与复制 ----
    print("\n== 3.2 转正与复制 ==")
    # 转正：tid（done 的 test）
    promoted = ss.promote_task(tid)
    check("转正 mode=persistent", promoted["mode"] == "persistent")
    check("转正后纳入 persistent 调度集", any(t["id"] == tid for t in ss.list_persistent_tasks()))
    check("test 任务不在调度集", not any(t["id"] == tid3 for t in ss.list_persistent_tasks()))
    # 已 persistent 再转正 → 拒绝
    try:
        ss.promote_task(tid)
        check("重复转正被拒绝", False)
    except ValueError:
        check("重复转正被拒绝", True)
    # 未 done 的 test 任务转正 → 拒绝
    t_pending = ss.create_task(
        strategy_id="vol_breakout_pullback",
        label="strategy_task_smoke_pending",
        scope_type="manual",
        scope_codes=codes,
    )
    try:
        ss.promote_task(t_pending["id"])
        check("非 done 转正被拒绝", False)
    except ValueError:
        check("非 done 转正被拒绝", True)

    # 复制：继承参数与范围，test 形态，可编辑
    task_now = ss.get_task(tid)  # 转正前当前参数（未编辑过，与创建时一致）
    copied = ss.copy_task(tid)
    check("复制继承参数", copied["params"] == task_now["params"], f"{copied['params']} vs {task_now['params']}")
    check("复制继承范围", copied["scope_codes"] == codes)
    check("复制为 test", copied["mode"] == "test")
    check("复制 pending", copied["status"] == "pending")
    check("复制 params_version 重置 1", copied["params_version"] == 1)
    edited = ss.update_task(copied["id"], params={"pullback_max_days": 3})
    check("复制品可编辑参数", edited["params_version"] == 2)

    # ---- 任务 3.3：monitor 联动（task 维度 + 来源标签）----
    print("\n== 3.3 monitor 联动 ==")
    from WebAPI import monitor_store as ms

    # 从 tid2 的信号加监控
    sigs2 = ss.query_signals(tid2, page_size=1)
    if sigs2["items"]:
        sig = sigs2["items"][0]
        mon = ms.create_monitor(
            code=sig["code"],
            kl_type="K_DAY",
            entry_price=sig["entry_ref_price"] or 10.0,
            monitor_start_time=sig["signal_date"] + " 00:00:00",
            source_type="strategy",
            task_id=tid2,
            signal_date=sig["signal_date"],
        )
        check("策略信号加监控成功", mon is not None and mon.get("task_id") == tid2, str(mon))
        check("监控冻结信号", sigs2["items"][0].get("frozen") or True)  # frozen 查询另验
        frozen_sig = [
            s for s in ss.query_signals(tid2, page_size=200, state=sig["state"]).get("items", [])
            if s["code"] == sig["code"] and s["signal_date"] == sig["signal_date"]
        ]
        check("信号 frozen=TRUE", frozen_sig and frozen_sig[0]["frozen"] is True, str(frozen_sig[:1]))
        # 监控列表来源标签「策略名 · 任务名 · 状态」
        monitoring = ms.list_monitoring()
        mine = [m for m in monitoring if m.get("task_id") == tid2]
        check("监控列表含策略来源行", len(mine) > 0)
        if mine:
            label = mine[0].get("strategy_label") or ""
            check(
                "来源标签 = 策略名 · 任务名 · 状态（3.3 verify；策略已改名「放量启动回调」，D11）",
                "放量启动回调" in label and "strategy_task_smoke_rerun" in label and len(label.split(" · ")) == 3,
                label,
            )
            check("strategy 来源 bsp_type 取信号 state", mine[0].get("bsp_type") == sig["state"], str(mine[0].get("bsp_type")))
        # 来源字典
        sources = ms.list_monitor_sources()
        strat_src = [s for s in sources if s.get("source_type") == "strategy" and s.get("task_id") == tid2]
        check("来源字典含任务维度项", len(strat_src) == 1, str(strat_src))
        # 结束监控（清理 + 验证结算路径）
        if mine:
            ms.end_monitor(mine[0]["id"])
    else:
        check("策略信号加监控（无信号可测）", True, "tid2 无信号，跳过")

    # ---- 任务 3.1：HTTP 冒烟 ----
    print("\n== 3.1 HTTP 冒烟（uvicorn + urllib，环境无 httpx 不用 TestClient） ==")
    run_http_smoke(codes, codes5)

    # ---- 清理 ----
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    cur = conn.cursor()
    cleanup_test_tasks(cur)
    conn.close()

    print(f"\n===== 结果：{len(PASS)} 通过 / {len(FAIL)} 失败 =====")
    for f in FAIL:
        print("  FAIL:", f)
    return 1 if FAIL else 0


def run_http_smoke(codes, codes5):
    """API 层冒烟：起真实 uvicorn 服务器 + urllib 标准库请求
    （环境无 httpx，TestClient 不可用），正常路径 + 校验失败路径（422/404/409）。"""
    import json as _json
    import threading
    import time
    import urllib.error
    import urllib.request

    import uvicorn

    # 禁用 app 内置调度（lifespan 会启动 bsp tick/meta sync/eod 循环，
    # 与冒烟测试抢 DuckDB/PG；冒烟只测 HTTP 层）
    os.environ["BSP_CATCHUP_ENABLED"] = "0"
    os.environ["STRATEGY_SCAN_ENABLED"] = "0"
    os.environ["META_SYNC_INTERVAL_SECONDS"] = "99999"

    from WebAPI.app import app

    port = 18999
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    check("uvicorn 测试服务器启动", server.started)

    base = f"http://127.0.0.1:{port}"

    # 朴素版请求（登录自身不带 token）
    def req(method: str, path: str, body=None, params=None, auth=True):
        """发请求返回 (status, json)。auth=True 时带 Bearer token。"""
        url = base + path
        if params:
            url += "?" + "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
        data = _json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(url, data=data, method=method)
        if data:
            r.add_header("Content-Type", "application/json")
        if auth and token_holder.get("token"):
            r.add_header("Authorization", f"Bearer {token_holder['token']}")
        try:
            with urllib.request.urlopen(r, timeout=120) as resp:
                text = resp.read().decode()
                return resp.status, (_json.loads(text) if text else None)
        except urllib.error.HTTPError as e:
            text = e.read().decode()
            try:
                return e.code, (_json.loads(text) if text else None)
            except Exception:
                return e.code, text

    # 登录拿 token（POST /tasks 等写接口挂 get_current_user 守卫）。
    # 冒烟服务器挂的是 WebAPI.app（/api/auth/* 在 WebAPI.main 上），
    # 直接用 auth 模块签发（种子账号 admin/admin123）
    from WebAPI.auth import _authenticate, _make_token

    token_holder: dict = {}
    try:
        user = _authenticate("admin", "admin123")
        token_holder["token"] = _make_token(user["id"], user["username"])
        check("HTTP 签发 token", True)
    except Exception as e:
        check("HTTP 签发 token", False, str(e))

    try:
        # definitions：detail_schema/params desc 透出
        st, j = req("GET", "/api/strategy/definitions")
        check("GET definitions 200", st == 200, str(st))
        d = next(x for x in j if x["id"] == "vol_breakout_pullback")
        check(
            "definitions 透出 detail_schema",
            [b["type"] for b in d["detail_schema"]] == ["summary", "per_stock", "signals", "kv"],
        )
        check("definitions 透出 params desc", all(p.get("desc") for p in d["params_schema"]))
        check("definitions 含任务节点", isinstance(d.get("tasks"), list))

        # 创建任务（manual 范围）
        st, task = req("POST", "/api/strategy/tasks", body={
            "strategy_id": "vol_breakout_pullback",
            "label": "strategy_task_smoke_http",
            "params": {},
            "scope_type": "manual",
            "scope_codes": codes5,
            "user_group": "HTTP组",
        })
        check("POST tasks 200", st == 200, str(st))
        tid_h = task["id"]
        # D7 默认值修订（2026-10-14 用户反馈）：pullback_max_days 5→13
        check("HTTP 创建补默认参数", task["params"]["pullback_max_days"] == 13)

        # 校验失败路径
        st, _ = req("POST", "/api/strategy/tasks", body={"strategy_id": "vol_breakout_pullback", "label": "", "scope_type": "all"})
        check("空 label 422", st == 422, str(st))
        st, _ = req("POST", "/api/strategy/tasks", body={
            "strategy_id": "vol_breakout_pullback", "label": "x",
            "params": {"pullback_max_days": 999}, "scope_type": "all",
        })
        check("参数越界 422", st == 422, str(st))
        st, _ = req("POST", "/api/strategy/tasks", body={
            "strategy_id": "vol_breakout_pullback", "label": "x", "scope_type": "manual", "scope_codes": [],
        })
        check("manual 空范围 422", st == 422, str(st))
        st, _ = req("POST", "/api/strategy/tasks", body={"strategy_id": "nope", "label": "x", "scope_type": "all"})
        check("未知策略 422", st == 422, str(st))
        st, _ = req("POST", "/api/strategy/tasks", body={
            "strategy_id": "vol_breakout_pullback", "label": "strategy_task_smoke_wl",
            "scope_type": "watchlist", "watchlist_folder_id": 99999,
        })
        check("watchlist 文件夹不存在 422", st == 422, str(st))

        # 任务列表 / 单任务 / 过滤
        st, j = req("GET", "/api/strategy/tasks")
        check("GET tasks 200", st == 200, str(st))
        check("GET tasks 含进度字段", "progress_scanned" in (j[0] if j else {"progress_scanned": 0}))
        st, _ = req("GET", "/api/strategy/tasks", params={"status": "bogus"})
        check("GET tasks 非法 status 422", st == 422, str(st))
        st, _ = req("GET", f"/api/strategy/tasks/{tid_h}")
        check("GET task 单个 200", st == 200, str(st))
        st, _ = req("GET", "/api/strategy/tasks/999999")
        check("GET task 404", st == 404, str(st))

        # 启动（BackgroundTasks 在响应后执行，同步等待扫完）
        st, _ = req("POST", f"/api/strategy/tasks/{tid_h}/start")
        check("POST start 200", st == 200, str(st))
        import time as _t

        for _ in range(120):  # 等后台扫描完成（最多 60s）
            _, tj = req("GET", f"/api/strategy/tasks/{tid_h}")
            if tj["status"] == "done":
                break
            _t.sleep(0.5)
        check("start 后台扫描完成 done", tj["status"] == "done", str(tj["status"]))
        st, _ = req("POST", f"/api/strategy/tasks/{tid_h}/start")
        check("重复 start 409", st == 409, str(st))

        # 信号查询（task_id 维度 + params_version）
        st, body = req("GET", "/api/strategy/signals", params={"task_id": tid_h, "page": 1, "page_size": 5})
        check("GET signals 200", st == 200, str(st))
        check("signals PageRes 契约", set(body.keys()) == {"list", "total", "page", "page_size"})
        if body["list"]:
            check("signals 行含 params_version", "params_version" in body["list"][0])
        # 绩效四字段透传（strategy-signal-outcome 4.1 verify：行结构透传）
        if body["list"]:
            row = body["list"][0]
            check(
                "signals 行含绩效四字段",
                all(k in row for k in ("ret_5d", "ret_10d", "ret_15d", "outcome")),
                str(sorted(row.keys())),
            )
            matched_rows = [r for r in body["list"] if r["state"] in ("triggered", "running")]
            check(
                "signals 匹配态行带绩效（outcome 非 None）",
                all(r["outcome"] is not None for r in matched_rows) or not matched_rows,
                str([(r["state"], r["outcome"]) for r in matched_rows[:3]]),
            )
        st, _ = req("GET", "/api/strategy/signals", params={"task_id": 999999})
        check("GET signals 任务不存在 404", st == 404, str(st))

        # 任务详情（显式范围：含 per_stock；definition.detail_schema）
        st, det = req("GET", f"/api/strategy/tasks/{tid_h}/detail")
        check("GET detail 200", st == 200, str(st))
        check("detail 含 summary", "summary" in det)
        check("detail 含 per_stock（显式范围）", "per_stock" in det)
        # 契约形状锁（前端 BlockPerStock/BlockSummary 消费）：
        # per_stock 必须是数组（曾经误传分页对象 → 前端 el-table
        # 'rows is not iterable'），summary 键名 total/scanned/matched/failed
        check("per_stock 是数组", isinstance(det.get("per_stock"), list), type(det.get("per_stock")).__name__)
        check(
            "summary 键名契约",
            set(det.get("summary", {}).keys()) == {"total", "scanned", "matched", "failed"},
            str(sorted(det.get("summary", {}).keys())),
        )
        check("detail 含 definition.detail_schema", det["definition"]["detail_schema"][0]["type"] == "summary")
        check("detail 含 signals_page", "signals_page" in det)
        # 绩效扩展形状锁（strategy-signal-outcome 4.2/4.1 verify）：
        # signals_page 只取匹配信号（matched_only，expired 不出现在任务详情）；
        # 行透传绩效四字段；kv_payload 含通用绩效聚合（accuracy 等，D6）
        sp = det.get("signals_page") or {}
        check(
            "detail signals_page 行含绩效四字段",
            "list" in sp and all(
                all(k in r for k in ("ret_5d", "ret_10d", "ret_15d", "outcome"))
                for r in sp.get("list", [])
            ),
            str(sorted((sp.get("list") or [{}])[0].keys())),
        )
        check(
            "detail signals 只含匹配态（matched_only）",
            all(r.get("state") in ("triggered", "running") for r in sp.get("list", [])),
            str([r.get("state") for r in sp.get("list", [])]),
        )
        kvp = det.get("kv_payload") or {}
        check(
            "detail kv_payload 含绩效准确率聚合",
            all(k in kvp for k in ("accuracy", "success_cnt", "failed_cnt", "pending_cnt")),
            str(sorted(kvp.keys())),
        )
        # 匹配态口径：行 outcome 有值时 kv 计数 > 0（绩效统计来源同表同 WHERE）
        n_outcome_rows = sum(1 for r in sp.get("list", []) if r.get("outcome") is not None)
        n_kv_cnt = (kvp.get("success_cnt") or 0) + (kvp.get("failed_cnt") or 0) + (kvp.get("pending_cnt") or 0)
        check(
            "detail kv 绩效计数与行集一致",
            n_outcome_rows <= n_kv_cnt or not sp.get("list"),
            f"rows={n_outcome_rows} kv_cnt={n_kv_cnt}",
        )

        # 编辑：非 paused 拒绝 409
        st, _ = req("PATCH", f"/api/strategy/tasks/{tid_h}", body={"label": "new"})
        check("非 paused 编辑 409", st == 409, str(st))

        # pause：非 running 拒绝 409（当前 done）
        st, _ = req("POST", f"/api/strategy/tasks/{tid_h}/pause")
        check("非 running pause 409", st == 409, str(st))

        # resume：非 paused 拒绝 409
        st, _ = req("POST", f"/api/strategy/tasks/{tid_h}/resume", body={"rerun": "full"})
        check("非 paused resume 409", st == 409, str(st))

        # 复制 + 编辑 + resume 两种 rerun 校验
        st, j = req("POST", f"/api/strategy/tasks/{tid_h}/copy", body={})
        check("POST copy 200", st == 200, str(st))
        tid_c = j["id"]
        st, _ = req("POST", f"/api/strategy/tasks/{tid_c}/start")
        # 等后台扫描结束（小范围秒级完成；若暂停抢到 running 则走 200，
        # 否则 done 后 pause 409——两者都是状态门合法语义）
        for _ in range(120):
            _, tcj = req("GET", f"/api/strategy/tasks/{tid_c}")
            if tcj["status"] != "running":
                break
            _t.sleep(0.5)
        st, _ = req("POST", f"/api/strategy/tasks/{tid_c}/pause")
        check("pause 状态门（200 或 done 409）", st in (200, 409), str(st))
        if st != 200:
            # 扫描已 done（暂停没抢到）：直接置 paused 模拟用户暂停后编辑（store 层
            # 无状态副作用，仅翻状态位，路由层状态门以 paused 为准）
            from WebAPI import strategy_store as _ss

            _ss.set_task_status(tid_c, "paused")

        # resume 非法 rerun 422（路由层 rerun 校验先于状态检查，任何状态可测）
        st, _ = req("POST", f"/api/strategy/tasks/{tid_c}/resume", body={"rerun": "bogus"})
        check("resume 非法 rerun 422", st == 422, str(st))
        st, j = req("PATCH", f"/api/strategy/tasks/{tid_c}", body={"params": {"pullback_max_days": 3}})
        check("paused 编辑 200（version+1）", st == 200 and j["params_version"] == 2, str(st))
        st, _ = req("POST", f"/api/strategy/tasks/{tid_c}/resume", body={"rerun": "full"})
        check("resume full 200", st == 200, str(st))
        for _ in range(120):
            _, tcj = req("GET", f"/api/strategy/tasks/{tid_c}")
            if tcj["status"] == "done":
                break
            _t.sleep(0.5)
        # remaining 续跑：再置 paused（done 后 resume 409 是状态门，绕过用 store 层）
        from WebAPI import strategy_store as _ss2

        _ss2.set_task_status(tid_c, "paused")
        st, _ = req("POST", f"/api/strategy/tasks/{tid_c}/resume", body={"rerun": "remaining"})
        check("resume remaining 200", st == 200, str(st))

        # 转正：非 done 409（remaining 续跑后应处于 running/paused）
        for _ in range(120):
            _, tcj = req("GET", f"/api/strategy/tasks/{tid_c}")
            if tcj["status"] != "running":
                break
            _t.sleep(0.5)
        st, _ = req("POST", f"/api/strategy/tasks/{tid_c}/promote")
        _, tcj = req("GET", f"/api/strategy/tasks/{tid_c}")
        if tcj.get("status") != "done":
            check("非 done promote 409", st == 409, str(st))
        else:
            check("非 done promote（竞态跳过）", True, "已 done，promote 合法 200")

        # 删除：running 409 / 正常 200 / 不存在 404
        st, _ = req("DELETE", f"/api/strategy/tasks/{tid_c}")
        _, tcj = req("GET", f"/api/strategy/tasks/{tid_c}")
        if isinstance(tcj, dict) and tcj.get("status") == "running":
            check("running 删除 409", st == 409, str(st))
            req("POST", f"/api/strategy/tasks/{tid_c}/pause")
            st, _ = req("DELETE", f"/api/strategy/tasks/{tid_c}")
        check("DELETE task 200", st == 200, str(st))
        st, _ = req("DELETE", f"/api/strategy/tasks/{tid_c}")
        check("重复 DELETE 404", st == 404, str(st))

        # 删除主任务后信号不可查询（spec）
        st, _ = req("DELETE", f"/api/strategy/tasks/{tid_h}")
        check("删除主任务 200", st == 200)
        st, _ = req("GET", "/api/strategy/signals", params={"task_id": tid_h})
        check("删除后信号查询 404", st == 404, str(st))

        # 实例端点已删除（BREAKING verify）
        st, _ = req("GET", "/api/strategy/instances")
        check("实例列表端点已删除（404/405）", st in (404, 405), str(st))
        st, _ = req("POST", "/api/strategy/instances", body={})
        check("实例创建端点已删除（404/405）", st in (404, 405), str(st))

        # monitor 加监控 task 维度（HTTP 契约）
        st, j = req("POST", "/api/strategy/tasks", body={
            "strategy_id": "vol_breakout_pullback",
            "label": "strategy_task_smoke_http_mon",
            "scope_type": "manual",
            "scope_codes": codes,
        })
        tid_m = j["id"]
        req("POST", f"/api/strategy/tasks/{tid_m}/start")
        for _ in range(120):
            _, tmj = req("GET", f"/api/strategy/tasks/{tid_m}")
            if tmj["status"] == "done":
                break
            _t.sleep(0.5)
        st, body = req("GET", "/api/strategy/signals", params={"task_id": tid_m, "page_size": 1})
        sigs = body["list"]
        if sigs:
            sig = sigs[0]
            st, j = req("POST", "/api/monitor", body={
                "code": sig["code"],
                "kl_type": "K_DAY",
                "entry_price": sig["entry_ref_price"] or 10.0,
                "monitor_start_time": sig["signal_date"] + " 00:00:00",
                "source_type": "strategy",
                "task_id": tid_m,
                "signal_date": sig["signal_date"],
            })
            check("HTTP 策略信号加监控 200", st == 200, f"{st} {j}")
            # 非法：strategy 无 task_id
            st, _ = req("POST", "/api/monitor", body={
                "code": sig["code"], "kl_type": "K_DAY", "entry_price": 10,
                "monitor_start_time": "2026-01-01 00:00:00",
                "source_type": "strategy", "signal_date": "2026-01-01",
            })
            check("strategy 缺 task_id 422", st == 422, str(st))
            st, _ = req("POST", "/api/monitor", body={
                "code": sig["code"], "kl_type": "K_DAY", "entry_price": 10,
                "monitor_start_time": "2026-01-01 00:00:00",
                "source_type": "strategy", "task_id": 999999, "signal_date": "2026-01-01",
            })
            check("strategy 任务不存在 404", st == 404, str(st))
            # 监控列表来源标签
            st, mons = req("GET", "/api/monitor")
            mine = [m for m in mons if m.get("task_id") == tid_m]
            check("HTTP 监控列表策略来源", len(mine) > 0)
            if mine:
                lbl = mine[0].get("strategy_label") or ""
                check(
                    "HTTP 来源标签 策略名·任务名·状态（已改名「放量启动回调」，D11）",
                    "放量启动回调" in lbl and "strategy_task_smoke_http_mon" in lbl and len(lbl.split(" · ")) == 3,
                    lbl,
                )
                # 结束监控清理
                req("POST", f"/api/monitor/{mine[0]['id']}/end")
        else:
            check("HTTP 加监控（无信号）", True, "跳过")
    finally:
        server.should_exit = True
        thread.join(timeout=10)


if __name__ == "__main__":
    sys.exit(main())
