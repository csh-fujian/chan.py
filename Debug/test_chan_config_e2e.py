# -*- coding: utf-8 -*-
"""端到端集成验证（chan-config-panel task 6.4）—— 直接打真实 HTTP 接口。

流程：管理员登录 → 读配置 → 改 3 项（1 判据 + 1 标注 + 1 结构）→ 保存
→ 确认 `/api/klines` 与 `bsp_index` 口径一致 → 启动同步 → 轮询到完成
→ 抽样核对 → 恢复原配置。

写法说明：仓库未装 `httpx`，`starlette.testclient` 不可用，故用标准库
`urllib.request` 直连本地已启动的服务。默认地址 http://127.0.0.1:8011。

前置：服务已启动（含 PG_DSN），测试账号 admin/admin123。

运行：
    .venv/Scripts/python.exe Debug/test_chan_config_e2e.py
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("CHAN_API", "http://127.0.0.1:8011")

_PASS = 0
_FAIL = 0


def check(label, cond, detail=""):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  [OK]   {label}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


def call(method, path, token=None, body=None):
    """返回 (status_code, parsed_json_or_text)。"""
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


def main():
    print(f"目标服务: {BASE}\n")

    print("[1] 管理员登录")
    st, resp = call("POST", "/api/auth/login",
                    body={"username": "admin", "password": "admin123"})
    check("登录 200", st == 200, f"{st} {resp}")
    if st != 200:
        return 1
    token = resp["token"]

    print("\n[2] 读取当前配置（作为回滚基线）")
    st, base_cfg = call("GET", "/api/chan-config", token)
    check("GET /api/chan-config 200", st == 200, str(st))
    base_overrides = base_cfg["overrides"]
    base_version = base_cfg["version"]
    print(f"      基线 version={base_version} overrides={base_overrides}")

    print("\n[3] 保存 3 项改动（判据 / 标注 / 结构各一）")
    # 判据：一买零轴关闭；标注：T2 阶梯确认窗口；结构：笔分型检查
    trial = {
        "bsp1_zero_axis": False,       # 判据
        "bsp2_confirm_window": 1,      # 标注（阶梯确认窗口）
        "bi_fx_check": "loss",         # 结构（笔分型检查口径）
    }
    merged = {**base_overrides, **trial}
    st, saved = call("PUT", "/api/chan-config", token,
                     {"overrides": merged, "preset": base_cfg["preset"]})
    check("PUT 200", st == 200, f"{st} {saved}")
    if st != 200:
        return 1
    new_version = saved["version"]
    check("版本号递增", new_version > (base_version or 0),
          f"{new_version} vs {base_version}")

    st, cfg2 = call("GET", "/api/chan-config", token)
    eff = cfg2["effective"]
    check("生效值已反映改动",
          eff["bsp1_zero_axis"] is False
          and eff["bsp2_confirm_window"] == 1
          and eff["bi_fx_check"] == "loss",
          str({k: eff[k] for k in trial}))

    print("\n[4] /api/klines 按新配置重算，且与 bsp_index 口径一致")
    st, kl = call("GET", "/api/klines?symbol=sz.000001&period=1d", token)
    check("GET /api/klines 200", st == 200, str(st))
    api_bsp = len(kl.get("bsp") or []) if isinstance(kl, dict) else -1
    print(f"      /api/klines bsp 个数 = {api_bsp}")

    st, _ = call("POST", "/api/chan-config/recompute", token,
                 {"code": "sz.000001", "period": "1d", "autype": "QFQ"})
    check("recompute 受理 200", st == 200, str(st))

    # 后台任务：轮询直到 bsp_index 行数稳定
    import psycopg2
    dsn = os.environ.get(
        "PG_DSN",
        "host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres",
    )
    conn = psycopg2.connect(dsn)
    try:
        db_rows = -1
        deadline = time.time() + 120
        prev, stable = None, 0
        while time.time() < deadline:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT count(*) FROM bsp_index
                       WHERE code='sz.000001' AND kl_type='D' AND autype='QFQ'""")
                db_rows = cur.fetchone()[0]
            # 行数与 API 一致，或连续两次不变（已收敛）即停
            if db_rows == api_bsp:
                break
            stable = stable + 1 if db_rows == prev else 0
            prev = db_rows
            if stable >= 3:
                break
            time.sleep(2)
        check(f"bsp_index 行数({db_rows}) = /api/klines bsp 个数({api_bsp})",
              db_rows == api_bsp, f"{db_rows} vs {api_bsp}")

        print("\n[5] 启动全库同步")
        st, job = call("POST", "/api/chan-config/sync", token)
        check("sync 启动 200", st == 200, f"{st} {job}")
        st2, _ = call("POST", "/api/chan-config/sync", token)
        check("重复启动返回 409", st2 == 409, str(st2))

        deadline = time.time() + 1200
        last = None
        while time.time() < deadline:
            st, status = call("GET", "/api/chan-config/sync/status", token)
            j = status.get("job") or {}
            if (j.get("done"), j.get("failed")) != last:
                print(f"      进度 {j.get('done')}/{j.get('total')} 失败 {j.get('failed')}")
                last = (j.get("done"), j.get("failed"))
            if not status.get("running"):
                break
            time.sleep(3)
        check("同步已结束", not status.get("running"), str(status.get("running")))
        check("同步状态为 done", (status.get("job") or {}).get("status") == "done",
              str((status.get("job") or {}).get("status")))
        check("无失败键", (status.get("job") or {}).get("failed") == 0,
              str((status.get("job") or {}).get("failed")))
        check("结果未过期（stale=false）", status.get("stale") is False,
              str(status.get("stale")))

        print("\n[6] 抽样核对（3 只 × 各自周期）")
        for code, kl_type in (("sz.000001", "D"), ("sh.600000", "D"),
                              ("sz.301123", "D")):
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT count(*) FROM bsp_index
                       WHERE code=%s AND kl_type=%s AND autype='QFQ'""",
                    (code, kl_type))
                n = cur.fetchone()[0]
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT config_fingerprint FROM chan_snapshot
                       WHERE code=%s AND kl_type=%s AND autype='QFQ'""",
                    (code, kl_type))
                row = cur.fetchone()
            print(f"      {code} {kl_type}: bsp_index {n} 行, 指纹 {row[0] if row else None}")
            check(f"{code} {kl_type} 有快照指纹", bool(row and row[0]))
    finally:
        conn.close()

    print("\n[7] 恢复基线配置")
    st, restored = call("PUT", "/api/chan-config", token,
                        {"overrides": base_overrides, "preset": base_cfg["preset"]})
    check("恢复 200", st == 200, f"{st} {restored}")
    st, cfg3 = call("GET", "/api/chan-config", token)
    check("overrides 已回到基线", cfg3["overrides"] == base_overrides,
          f"{cfg3['overrides']} vs {base_overrides}")

    print(f"\n{'=' * 46}\n合计: {_PASS} PASS, {_FAIL} FAIL\n{'=' * 46}")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
