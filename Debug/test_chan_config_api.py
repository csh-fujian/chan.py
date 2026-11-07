# -*- coding: utf-8 -*-
"""tasks 3.x / 4.x：配置 API 验证（直接调用路由函数，不依赖 httpx）。"""
import os, sys

REPO = r"E:\CodingWork\01csh\chan.py"
sys.path.insert(0, REPO); os.chdir(REPO)
os.environ.setdefault("PG_DSN", "host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fastapi import HTTPException
from WebAPI import chan_config_store as store
from WebAPI.routers import chan_config as R

store.invalidate_cache()
_orig = store.load_with_meta()

ADMIN = {"username": "admin", "is_admin": True, "perms": ["*"]}
TRADER = {"username": "trader", "is_admin": False, "perms": ["menu:kline"]}


def chk(label, cond, detail=""):
    print(f"  {'[OK]  ' if cond else '[FAIL]'} {label}" + ("" if cond else f"  {detail}"))
    return cond


def expect_http(code, fn, *a, **kw):
    try:
        fn(*a, **kw)
        return None, "未抛 HTTPException"
    except HTTPException as e:
        return e.status_code, e.detail


print("[3.1] 端点与权限守卫")
d = R.get_config(user=ADMIN)
chk("get_config 返回 effective/overrides/preset/version",
    all(k in d for k in ("effective", "overrides", "preset", "version")), str(list(d)))
chk(f"effective 覆盖全部参数（{len(d['effective'])} 项 ≥ 56）",
    len(d["effective"]) >= 56, str(len(d["effective"])))

s = R.get_schema(user=ADMIN)
chk("get_schema 返回 groups/params/counts",
    all(k in s for k in ("groups", "params", "counts")), str(list(s)))
chk("schema 3 组", len(s["groups"]) == 3, str(len(s["groups"])))

# 权限：require_menu_kline / require_manage 的守卫函数本身
from WebAPI.auth import require_manage, require_menu_kline
chk("require_menu_kline 放行 trader", require_menu_kline(TRADER) is TRADER)
code, _ = expect_http(403, require_manage, TRADER)
chk("require_manage 拒绝 trader（403）", code == 403, str(code))
chk("require_manage 放行 admin", require_manage(ADMIN) is ADMIN)
code, _ = expect_http(403, require_menu_kline, {"perms": ["menu:bsp"]})
chk("require_menu_kline 拒绝无 menu:kline（403）", code == 403, str(code))

print("\n[3.2] 构造期校验 → 422（含参数定位）")
old_version = R.get_config(user=ADMIN)["version"]
bad_cases = [
    ({"bsp2_confirm_window": 3}, "bsp2_confirm_window"),
    ({"bsp3b_mode": "bogus"}, "bsp3b_mode"),
    ({"bsp2_time_axis_strong": 2.0, "bsp2_time_axis_weak": 1.0}, "bsp2_time_axis"),
    ({"max_bs2_rate": 1.5}, "max_bs2_rate"),
    ({"bs_type": "1,9"}, "bs_type"),
]
for payload, expect in bad_cases:
    code, detail = expect_http(422, R.put_config,
                               R.ConfigSaveRequest(overrides=payload, preset="standard"),
                               user=ADMIN)
    chk(f"{list(payload)[0]} → 422", code == 422, str(code))
    param = detail.get("param") if isinstance(detail, dict) else None
    chk(f"  可定位到 {expect}", param == expect, f"param={param} detail={detail}")

after = R.get_config(user=ADMIN)["version"]
chk("校验失败后 version 不变（未写入）", after == old_version, f"{old_version} -> {after}")

print("\n[3.3] 保存：overrides + 全量快照 + preset")
res = R.put_config(
    R.ConfigSaveRequest(overrides={"divergence_rate": 0.85}, preset="standard",
                        full_snapshot={"divergence_rate": 0.85, "min_zs_cnt": 2}),
    user=ADMIN)
chk("put_config 返回新 version", isinstance(res["version"], int), str(res))
d = R.get_config(user=ADMIN)
chk("生效值含新 divergence_rate", d["effective"].get("divergence_rate") == 0.85,
    str(d["effective"].get("divergence_rate")))
chk("overrides 只含改过的项", set(d["overrides"]) == {"divergence_rate"}, str(d["overrides"]))
chk("未改项仍有生效值", len(d["effective"]) >= 56, str(len(d["effective"])))
meta = store.load_with_meta()
chk("config 列存全量快照", meta["config"].get("min_zs_cnt") == 2, str(meta["config"]))
chk("overrides 列存覆盖项", meta["overrides"].get("divergence_rate") == 0.85, str(meta["overrides"]))
chk("preset 落库", meta["preset"] == "standard", meta["preset"])

print("\n[3.4] 内核默认值变化不改写已保存配置")
import ChanAnalyse.ChanConfig as cc
orig_set = cc.CChanConfig.set_bsp_config
def patched(self, conf):
    orig_set(self, conf)
    self.bs_point_conf.b_conf.min_zs_cnt = 9    # 模拟内核默认值漂移
    self.bs_point_conf.s_conf.min_zs_cnt = 9
cc.CChanConfig.set_bsp_config = patched
try:
    store.invalidate_cache()
    chk("load() 仍返回保存值", store.load().get("divergence_rate") == 0.85, str(store.load()))
    d = R.get_config(user=ADMIN)
    chk("get_config 生效值未跟随内核漂移",
        d["effective"].get("divergence_rate") == 0.85,
        str(d["effective"].get("divergence_rate")))
finally:
    cc.CChanConfig.set_bsp_config = orig_set

print("\n[4.3 / 4.5] 单只重算与同步状态")
import asyncio
class _BG:
    def __init__(self): self.tasks = []
    def add_task(self, fn, *a, **kw): self.tasks.append((fn, a, kw))

bg = _BG()
res = asyncio.run(R.recompute_endpoint(
    R.RecomputeRequest(code="sz.000001", period="D"), bg, user=ADMIN))
chk("recompute 受理", res.get("accepted") is True, str(res))
chk("recompute 后台任务已排队", len(bg.tasks) == 1, str(len(bg.tasks)))
code, _ = expect_http(400, lambda: asyncio.run(R.recompute_endpoint(
    R.RecomputeRequest(code="sz.000001", period="bogus"), _BG(), user=ADMIN)))
chk("非法周期 → 400", code == 400, str(code))

st = R.sync_status_endpoint(user=TRADER)
chk("sync/status 含 running/job/stale",
    all(k in st for k in ("running", "job", "stale")), str(list(st)))

print("\n[4.1 / 4.4] 同步任务表与防重入")
job_id = store.sync_job_create(meta["version"] or 0, total=3)
chk("创建任务返回 id", isinstance(job_id, int), str(job_id))
store.sync_job_progress(job_id, 2, 1, total=3)
latest = store.sync_job_latest()
chk("进度可读回", latest["done"] == 2 and latest["failed"] == 1, str(latest))
chk("running 状态", latest["status"] == "running", latest["status"])
store.sync_job_finish(job_id, "done", 2, 1, {"scanned": 3, "updated": 2, "failed": []})
latest = store.sync_job_latest()
chk("终态 done", latest["status"] == "done", latest["status"])
chk("finished_at 已写", latest["finished_at"] is not None)

# 防重入：直接置标志验证 409
R._SYNC_RUNNING = True
try:
    code, detail = expect_http(409, lambda: asyncio.run(
        R.sync_endpoint(_BG(), user=ADMIN)))
    chk("同步运行中再次启动 → 409", code == 409, f"{code} {detail}")
finally:
    R._SYNC_RUNNING = False

# stale 判定：任务版本 ≠ 当前版本
job2 = store.sync_job_create((meta["version"] or 1) - 1, total=0)
store.sync_job_finish(job2, "done", 0, 0, {})
chk("配置版本不一致时 stale=true", store.sync_job_latest()["stale"] is True,
    str(store.sync_job_latest()))

# 还原
if _orig["initialized"]:
    store.save(_orig["overrides"], _orig["preset"], _orig["config"], "verify-api-restore")
else:
    conn = store._get_pg_conn()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM chan_config WHERE id = 1")
        cur.execute(f"DELETE FROM {store._SYNC_TABLE}")
    conn.commit(); conn.close()
store.invalidate_cache()
print("\n  已还原原配置")
