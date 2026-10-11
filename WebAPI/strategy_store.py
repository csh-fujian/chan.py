# -*- coding: utf-8 -*-
"""
Strategy DAO — strategy / strategy_task / strategy_task_stock_result /
strategy_signal / strategy_scan_cursor 表的 PG 持久化
（strategy-task-redesign design D1/D2/D7）。

三层模型：
- strategy（定义层）：代码注册（strategy_engines.DEFINITIONS），非用户 CRUD；
  表行在首次访问时由 _sync_definitions 从注册表同步落库（幂等 upsert）
- strategy_task（使用层）：策略 + 股票范围 + 形态（test/persistent）+ 状态
  （pending/running/paused/done）+ 进度 + params_version（编辑参数 +1，信号行
  携带版本可归因）。取代原 strategy_instance（不可变实例，已废弃）：
  - 暂停后可编辑（test 可改参数/范围，persistent 仅范围——参数冻结）
  - 两种续跑语义：full（清信号+逐股结果+水位+进度重扫）/ remaining（从当前
    进度续跑新参数，旧参数信号保留）
  - 转正：test → persistent（mode 翻转，纳入 EOD 日终调度）
- strategy_task_stock_result（逐股结果）：显式范围任务每只股票一条
  （UNIQUE(task_id, code)，重跑覆盖）；全量范围不落（存储量约束）
- strategy_signal（信号）：挂任务，UNIQUE(task_id, code, signal_date)，
  行携带 params_version；upsert 带 `WHERE strategy_signal.frozen = FALSE`
  冻结门（strategy-signal-page D8，语义保留）
- strategy_scan_cursor：(task_id, code) → watermark（DuckDB time_key 字符串）

存量实例 → 任务的迁移由 update.sql 幂等 DO 块完成（D7）；本模块惰性建表
不再建 strategy_instance（新装环境无此表）。

风格对齐 bsp_store：_get_pg_conn 独立定义、PG 不可达降级返回空值、
惰性建表 + 模块加载自动建表、_date_range_conditions 半开区间语义。
"""

import json
import logging
from datetime import date as _date
from datetime import timedelta
from typing import Any, Optional

import psycopg2

from .config import PG_DSN

log = logging.getLogger("strategy_store")


def _get_pg_conn():
    """获取 PG 连接，PG_DSN 未配置或 PG 不可达时返回 None（降级为无数据库模式）。"""
    global _pg_down
    if not PG_DSN:
        return None

    try:
        conn = psycopg2.connect(PG_DSN)
    except psycopg2.OperationalError as e:
        if not _pg_down:
            log.warning("PG 不可达，降级为无数据库模式: %s", e)
            _pg_down = True
        return None
    if _pg_down:
        log.info("PG 连接已恢复")
        _pg_down = False
    return conn


# PG 连接失败降级状态（仅状态翻转时记一次日志，防止每个请求刷屏）
_pg_down = False


# 任务状态与形态取值域（strategy-task-redesign design D1）
TASK_STATUSES = ("pending", "running", "paused", "done")
TASK_MODES = ("test", "persistent")
SCOPE_TYPES = ("manual", "watchlist", "bsp_query", "all")


def _ensure_tables():
    """惰性建表（CREATE TABLE IF NOT EXISTS，风格对齐 bsp_store）。

    strategy-task-redesign D7：不再建 strategy_instance（新装环境无此表）；
    存量环境的实例 → 任务迁移由 update.sql 幂等 DO 块完成，代码侧只认新表。
    """
    conn = _get_pg_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy (
                    id            VARCHAR PRIMARY KEY,
                    name          VARCHAR NOT NULL,
                    group_name    VARCHAR NOT NULL DEFAULT '',
                    engine        VARCHAR NOT NULL DEFAULT '',
                    sort          INT NOT NULL DEFAULT 0,
                    params_schema JSONB NOT NULL DEFAULT '[]',
                    states        JSONB NOT NULL DEFAULT '[]',
                    columns       JSONB NOT NULL DEFAULT '[]'
                )
                """
            )
            # 任务表（D1：scope_type + scope_codes 快照 + mode + status + 进度 +
            # params_version；user_group 为纯组织性字符串标签，无独立分组表）
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_task (
                    id               SERIAL PRIMARY KEY,
                    strategy_id      VARCHAR NOT NULL REFERENCES strategy(id),
                    label            VARCHAR NOT NULL,
                    user_group       VARCHAR NOT NULL DEFAULT '',
                    params           JSONB NOT NULL DEFAULT '{}',
                    params_version   INT NOT NULL DEFAULT 1,
                    scope_type       VARCHAR NOT NULL,
                    scope_codes      JSONB,
                    mode             VARCHAR NOT NULL DEFAULT 'test',
                    status           VARCHAR NOT NULL DEFAULT 'pending',
                    progress_scanned INT NOT NULL DEFAULT 0,
                    progress_total   INT NOT NULL DEFAULT 0,
                    created_by       VARCHAR,
                    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            # 逐股结果表（D1：显式范围任务落行，UNIQUE(task_id, code) 重跑覆盖）
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_task_stock_result (
                    id             BIGSERIAL PRIMARY KEY,
                    task_id        INT NOT NULL REFERENCES strategy_task(id) ON DELETE CASCADE,
                    code           VARCHAR NOT NULL,
                    matched        BOOLEAN NOT NULL,
                    run_status     VARCHAR NOT NULL,
                    message        TEXT,
                    signal_date    DATE,
                    params_version INT NOT NULL,
                    executed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (task_id, code)
                )
                """
            )
            # 新装环境直接建 task_id 键形态的信号/游标表（存量环境由 update.sql
            # 迁移 DO 块改造列结构，二者收敛为同一形态）
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_signal (
                    id              SERIAL PRIMARY KEY,
                    task_id         INT NOT NULL REFERENCES strategy_task(id) ON DELETE CASCADE,
                    code            VARCHAR NOT NULL,
                    signal_date     DATE NOT NULL,
                    state           VARCHAR NOT NULL,
                    is_buy          BOOLEAN NOT NULL,
                    entry_ref_price DOUBLE PRECISION,
                    stop_ref_price  DOUBLE PRECISION,
                    payload         JSONB NOT NULL DEFAULT '{}',
                    params_version  INT NOT NULL DEFAULT 1,
                    frozen          BOOLEAN NOT NULL DEFAULT FALSE,
                    ret_7d          DOUBLE PRECISION,
                    ret_14d         DOUBLE PRECISION,
                    ret_30d         DOUBLE PRECISION,
                    outcome         VARCHAR,
                    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (task_id, code, signal_date)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_scan_cursor (
                    task_id   INT NOT NULL,
                    code      VARCHAR NOT NULL,
                    watermark VARCHAR NOT NULL,
                    PRIMARY KEY (task_id, code)
                )
                """
            )
            # 定义层从代码注册表同步落库（幂等 upsert，非用户 CRUD），
            # 在同一 cursor/事务内执行（strategy 行是任务 FK 的前提）
            _sync_definitions(cur)
        conn.commit()
    finally:
        conn.close()


def _sync_definitions(cur) -> None:
    """把 strategy_engines.DEFINITIONS 注册表落 strategy 表（幂等 upsert）。

    定义随版本发布，表行只是持久化快照（供 SQL 侧 JOIN 与任务 FK）；
    代码注册表为唯一事实源，表行按注册表全量覆盖。
    """
    try:
        from .strategy_engines import DEFINITIONS
    except Exception as e:
        log.warning("策略定义注册表导入失败，跳过同步: %s", e)
        return

    for d in DEFINITIONS.values():
        cur.execute(
            """INSERT INTO strategy (id, name, group_name, engine, sort, params_schema, states, columns)
               VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
               ON CONFLICT (id) DO UPDATE SET
                 name          = EXCLUDED.name,
                 group_name    = EXCLUDED.group_name,
                 engine        = EXCLUDED.engine,
                 sort          = EXCLUDED.sort,
                 params_schema = EXCLUDED.params_schema,
                 states        = EXCLUDED.states,
                 columns       = EXCLUDED.columns""",
            (
                d.id,
                d.name,
                d.group_name,
                d.engine_key,
                d.sort,
                json.dumps(d.params_schema, ensure_ascii=False),
                json.dumps(d.states, ensure_ascii=False),
                json.dumps(d.columns, ensure_ascii=False),
            ),
        )


# ----------------------------------------------------------------------
# 范围快照解析（strategy-task-redesign design D3，三种来源 + 全量兜底）
# ----------------------------------------------------------------------

def resolve_scope_codes(
    scope_type: str,
    manual_codes: Optional[list[str]] = None,
    watchlist_folder_id: Optional[int] = None,
    bsp_query: Optional[dict] = None,
) -> Optional[list[str]]:
    """创建/编辑任务时解析股票范围 → 固化快照 code 列表（design D3）。

    - manual：前端多选/搜索添加，直接传 code 列表
    - watchlist：传 folder_id，从 PG watchlist_item 读该文件夹股票 → 固化
      （创建时点快照，此后文件夹变化无关）
    - bsp_query：传 /bsp 页当前查询条件 dict（bsp_types/kl_type/is_buy/
      is_sure/date_from/date_to/keyword），调 bsp_store.query_bsp 取 code
      列表 → 固化（去重，不按页截断——逐页翻完聚合）
    - all：返回 None（scope_codes 落 NULL，执行时枚举 DuckDB 全量 + ST 过滤）

    范围为空（manual 无码/watchlist 空文件夹/bsp 查询无命中）抛 ValueError
    （调用方转 422；spec「未选择股票默认全量」由调用方在 scope_type 层面表达，
    显式来源解析为空属于用户可感知的配置错误）。
    """
    if scope_type == "all":
        return None
    if scope_type == "manual":
        codes = [str(c).strip() for c in (manual_codes or []) if str(c).strip()]
        codes = list(dict.fromkeys(codes))  # 去重保序
        if not codes:
            raise ValueError("manual 范围必须携带非空股票列表")
        return codes
    if scope_type == "watchlist":
        if watchlist_folder_id is None:
            raise ValueError("watchlist 范围必须携带 folder_id")
        from .watchlist_store import _get_folder_codes

        codes = _get_folder_codes(int(watchlist_folder_id))
        if not codes:
            raise ValueError(f"自选文件夹 {watchlist_folder_id} 内没有股票")
        return list(codes)
    if scope_type == "bsp_query":
        if not bsp_query or not isinstance(bsp_query, dict):
            raise ValueError("bsp_query 范围必须携带查询条件对象")
        from .bsp_store import query_bsp

        codes: list[str] = []
        page = 1
        # 逐页翻完聚合（page_size 取上限一批拉完，避免逐行游标）
        while True:
            result = query_bsp(
                kl_type=bsp_query.get("kl_type", ""),
                date_from=bsp_query.get("date_from", ""),
                date_to=bsp_query.get("date_to", ""),
                bsp_types=bsp_query.get("bsp_types"),
                is_buy=bsp_query.get("is_buy"),
                keyword=bsp_query.get("keyword", ""),
                page=page,
                page_size=200,
                is_sure=bsp_query.get("is_sure"),
            )
            for it in result["items"]:
                codes.append(it["code"])
            if page * 200 >= result["total"]:
                break
            page += 1
        codes = list(dict.fromkeys(codes))
        if not codes:
            raise ValueError("买卖点查询无命中股票，无法固化为任务范围")
        return codes
    raise ValueError(f"未知范围类型: {scope_type}（可选 manual/watchlist/bsp_query/all）")


# ----------------------------------------------------------------------
# 任务 CRUD（strategy-task-redesign design D1/D2）
# ----------------------------------------------------------------------

def create_task(
    strategy_id: str,
    label: str,
    params: Optional[dict] = None,
    scope_type: str = "all",
    scope_codes: Optional[list[str]] = None,
    mode: str = "test",
    user_group: str = "",
    created_by: Optional[str] = None,
) -> dict:
    """创建策略任务（spec「创建任务」：params 校验通过后进入 pending 待执行）。

    - params 按 params_schema 校验（validate_params），非法抛 ValueError（422）
    - scope_type ∈ manual/watchlist/bsp_query/all；显式范围传固化后的
      scope_codes（调用方先用 resolve_scope_codes 解析快照），'all' 传 None
    - mode ∈ test/persistent；创建即执行（启动由调用方触发 start）
    - user_group：纯组织性字符串标签（新建分组 = 输入新字符串，spec「自定义分组」）

    返回任务 dict。
    """
    from .strategy_engines import get_definition, validate_params

    definition = get_definition(strategy_id)
    if definition is None:
        raise ValueError(f"策略定义不存在: {strategy_id}")
    if not label or not str(label).strip():
        raise ValueError("任务名称（label）不能为空")
    if scope_type not in SCOPE_TYPES:
        raise ValueError(f"scope_type 非法: {scope_type}（可选 {'/'.join(SCOPE_TYPES)}）")
    if mode not in TASK_MODES:
        raise ValueError(f"mode 非法: {mode}（可选 test/persistent）")
    if scope_type != "all":
        codes = [str(c).strip() for c in (scope_codes or []) if str(c).strip()]
        codes = list(dict.fromkeys(codes))
        if not codes:
            raise ValueError(f"{scope_type} 范围解析结果为空，无法创建任务")
        scope_codes_json = json.dumps(codes, ensure_ascii=False)
    else:
        scope_codes_json = None

    normalized, errors = validate_params(definition, params)
    if errors:
        raise ValueError("；".join(errors))

    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        raise RuntimeError("PG 不可用，无法创建策略任务")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO strategy_task
                     (strategy_id, label, user_group, params, params_version,
                      scope_type, scope_codes, mode, status,
                      progress_scanned, progress_total, created_by)
                   VALUES (%s, %s, %s, %s::jsonb, 1, %s, %s::jsonb, %s, 'pending', 0, 0, %s)
                   RETURNING id, strategy_id, label, user_group, params, params_version,
                             scope_type, scope_codes, mode, status,
                             progress_scanned, progress_total, created_by, created_at, updated_at""",
                (
                    strategy_id, str(label).strip(), str(user_group or ""),
                    json.dumps(normalized, ensure_ascii=False),
                    scope_type, scope_codes_json, mode, created_by,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()
    return _task_row_to_dict(row)


def list_tasks(
    strategy_id: Optional[str] = None,
    user_group: Optional[str] = None,
    status: Optional[str] = None,
    mode: Optional[str] = None,
) -> list[dict]:
    """列出任务（可按策略定义/分组/状态/形态过滤），按 created_at 升序。

    任务列表展示：基础信息、策略类型、分组、创建时间、创建人、执行进度
    （progress_scanned/progress_total，前端进度条消费）。
    """
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return []
    sql = "SELECT id, strategy_id, label, user_group, params, params_version, scope_type, scope_codes, mode, status, progress_scanned, progress_total, created_by, created_at, updated_at FROM strategy_task"
    conditions: list[str] = []
    params: list[Any] = []
    if strategy_id:
        conditions.append("strategy_id = %s")
        params.append(strategy_id)
    if user_group is not None:
        conditions.append("user_group = %s")
        params.append(user_group)
    if status:
        conditions.append("status = %s")
        params.append(status)
    if mode:
        conditions.append("mode = %s")
        params.append(mode)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY created_at, id"
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()
    return [_task_row_to_dict(r) for r in rows]


def get_task(task_id: int) -> Optional[dict]:
    """取单个任务（调度/路由存在性校验用）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, strategy_id, label, user_group, params, params_version,
                          scope_type, scope_codes, mode, status,
                          progress_scanned, progress_total, created_by, created_at, updated_at
                   FROM strategy_task WHERE id = %s""",
                (task_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    return _task_row_to_dict(row) if row else None


def update_task(
    task_id: int,
    label: Optional[str] = None,
    user_group: Optional[str] = None,
    params: Optional[dict] = None,
    scope_type: Optional[str] = None,
    scope_codes: Optional[list[str]] = None,
) -> dict:
    """编辑任务（design D2：仅 paused 状态可编辑，由调用方校验状态前置条件）。

    - test 任务：参数与范围都可改（参数冻结只针对 persistent）
    - persistent 任务：调用方须先拒绝参数修改（spec「persistent 参数冻结」），
      本函数收到 params=None 即不改参数
    - params 变化时 params_version +1（design D2：保存时检测 params 是否变化
      驱动版本递增；范围/label/分组变化不递增——版本只标识参数组）
    - 范围编辑 = 重新固化为快照，下次执行生效（spec「persistent 范围可编辑」）

    返回更新后的任务 dict；任务不存在抛 ValueError（调用方转 404）。
    """
    from .strategy_engines import get_definition, validate_params

    task = get_task(task_id)
    if task is None:
        raise ValueError(f"任务 {task_id} 不存在")

    sets: list[str] = []
    values: list[Any] = []

    if label is not None:
        if not str(label).strip():
            raise ValueError("任务名称（label）不能为空")
        sets.append("label = %s")
        values.append(str(label).strip())
    if user_group is not None:
        sets.append("user_group = %s")
        values.append(str(user_group))

    # 参数编辑：校验 + 变化检测 → params_version 递增（D2）
    if params is not None:
        definition = get_definition(task["strategy_id"])
        if definition is None:
            raise ValueError(f"策略定义不存在: {task['strategy_id']}")
        normalized, errors = validate_params(definition, params)
        if errors:
            raise ValueError("；".join(errors))
        if normalized != task["params"]:
            sets.append("params = %s::jsonb")
            values.append(json.dumps(normalized, ensure_ascii=False))
            sets.append("params_version = params_version + 1")

    # 范围编辑：重新固化快照（D3 快照语义；改范围不动进度/结果——续跑语义由
    # resume 的 full/remaining 决定，full 会清进度重扫新范围）
    if scope_type is not None:
        if scope_type not in SCOPE_TYPES:
            raise ValueError(f"scope_type 非法: {scope_type}")
        if scope_type != "all":
            codes = [str(c).strip() for c in (scope_codes or []) if str(c).strip()]
            codes = list(dict.fromkeys(codes))
            if not codes:
                raise ValueError(f"{scope_type} 范围解析结果为空")
            sets.append("scope_type = %s")
            values.append(scope_type)
            sets.append("scope_codes = %s::jsonb")
            values.append(json.dumps(codes, ensure_ascii=False))
        else:
            sets.append("scope_type = 'all'")
            sets.append("scope_codes = NULL")

    if not sets:
        return task  # 无任何变更，幂等返回原任务

    sets.append("updated_at = NOW()")
    conn = _get_pg_conn()
    if conn is None:
        raise RuntimeError("PG 不可用，无法编辑任务")
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""UPDATE strategy_task SET {', '.join(sets)}
                    WHERE id = %s
                    RETURNING id, strategy_id, label, user_group, params, params_version,
                              scope_type, scope_codes, mode, status,
                              progress_scanned, progress_total, created_by, created_at, updated_at""",
                values + [task_id],
            )
            row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()
    return _task_row_to_dict(row)


def start_task(task_id: int) -> dict:
    """启动任务（spec「启动任务」：pending/paused → running，进度开始推进）。

    已 running/done 的任务拒绝启动（幂等防重入）；返回更新后的任务 dict。
    """
    task = get_task(task_id)
    if task is None:
        raise ValueError(f"任务 {task_id} 不存在")
    if task["status"] in ("running", "done"):
        raise ValueError(f"任务 {task_id} 状态为 {task['status']}，不可启动")
    _set_task_status(task_id, "running")
    task["status"] = "running"
    return task


def pause_task(task_id: int) -> dict:
    """暂停任务（spec「暂停任务」：running → paused，已产生信号与逐股结果保留）。

    执行器在每个 code 边界检查任务状态，下一边界停止（design D4）。
    非 running 状态拒绝暂停；返回更新后的任务 dict。
    """
    task = get_task(task_id)
    if task is None:
        raise ValueError(f"任务 {task_id} 不存在")
    if task["status"] != "running":
        raise ValueError(f"任务 {task_id} 状态为 {task['status']}，仅 running 可暂停")
    _set_task_status(task_id, "paused")
    task["status"] = "paused"
    return task


def resume_task(task_id: int, rerun: str = "full") -> dict:
    """续跑任务（design D2 两种续跑语义，spec「任务编辑与两种续跑语义」）。

    仅 paused 状态可续跑（rerun: full|remaining，默认 full）：
    - full（重新运行，默认）：单事务内 DELETE 信号 + 逐股结果 + 游标 +
      progress_scanned=0，从头全量重扫（旧信号物理删除——历史保真由复制任务承接）
    - remaining（剩余股票继续）：不动已扫部分与进度计数，调度从当前进度续
      （旧参数信号与新参数信号共存，靠信号行 params_version 区分归因）

    返回更新后的任务 dict。
    """
    task = get_task(task_id)
    if task is None:
        raise ValueError(f"任务 {task_id} 不存在")
    if task["status"] != "paused":
        raise ValueError(f"任务 {task_id} 状态为 {task['status']}，仅 paused 可续跑")
    if rerun not in ("full", "remaining"):
        raise ValueError("rerun 仅接受 full 或 remaining")

    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        raise RuntimeError("PG 不可用，无法续跑任务")
    try:
        with conn.cursor() as cur:
            if rerun == "full":
                # 重新运行：单事务清空（D2「删除在同一事务内，失败不产生半清空状态」）
                cur.execute("DELETE FROM strategy_signal WHERE task_id = %s", (task_id,))
                cur.execute(
                    "DELETE FROM strategy_task_stock_result WHERE task_id = %s",
                    (task_id,),
                )
                cur.execute("DELETE FROM strategy_scan_cursor WHERE task_id = %s", (task_id,))
                cur.execute(
                    "UPDATE strategy_task SET progress_scanned = 0, status = 'running', updated_at = NOW() WHERE id = %s",
                    (task_id,),
                )
            else:
                # 剩余继续：进度/水位/已扫结果全部保留，状态翻回 running
                cur.execute(
                    "UPDATE strategy_task SET status = 'running', updated_at = NOW() WHERE id = %s",
                    (task_id,),
                )
        conn.commit()
    finally:
        conn.close()
    return get_task(task_id)


def promote_task(task_id: int) -> dict:
    """转正（spec「转正」：done 的 test 任务 → persistent，纳入日终调度）。

    既有信号保留；mode 翻转即纳入 EOD 调度（调度只取 mode='persistent'）。
    非 done 的 test 任务拒绝转正；返回更新后的任务 dict。
    """
    task = get_task(task_id)
    if task is None:
        raise ValueError(f"任务 {task_id} 不存在")
    if task["mode"] != "test":
        raise ValueError(f"任务 {task_id} 已是 persistent，无需转正")
    if task["status"] != "done":
        raise ValueError(f"任务 {task_id} 状态为 {task['status']}，仅 done 的 test 任务可转正")
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        raise RuntimeError("PG 不可用，无法转正任务")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE strategy_task SET mode = 'persistent', updated_at = NOW() WHERE id = %s",
                (task_id,),
            )
        conn.commit()
    finally:
        conn.close()
    return get_task(task_id)


def copy_task(task_id: int, label: Optional[str] = None) -> dict:
    """复制任务（spec「复制任务调参」：继承参数与范围作为初始值的新 test 任务）。

    - 新任务 status='pending'、params_version=1（新参数组的起点）
    - 复制产物恒为 test 形态（调参 → 测试 → 满意再转正的循环）
    - 信号/逐股结果/水位不复制（新任务从零扫描）

    返回新任务 dict。
    """
    task = get_task(task_id)
    if task is None:
        raise ValueError(f"任务 {task_id} 不存在")
    new_label = (label or f"{task['label']} (副本)").strip()
    return create_task(
        strategy_id=task["strategy_id"],
        label=new_label,
        params=task["params"],
        scope_type=task["scope_type"],
        scope_codes=task["scope_codes"],
        mode="test",
        user_group=task["user_group"],
        created_by=task.get("created_by"),
    )


def delete_task(task_id: int) -> bool:
    """删除任务（spec「删除任务」：信号与逐股结果一并删除，不可恢复）。

    - 信号/逐股结果走 FK ON DELETE CASCADE
    - 游标表无 FK（独立游标表，design D4），显式删除
    - running 状态的任务由调用方先暂停（避免删除与执行器竞争；执行器在每个
      code 边界检查状态，行已删时下一边界自然跳过）

    返回 True 成功；任务不存在返回 False。
    """
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM strategy_scan_cursor WHERE task_id = %s", (task_id,))
            cur.execute("DELETE FROM strategy_task WHERE id = %s", (task_id,))
            ok = cur.rowcount > 0
        conn.commit()
        return ok
    finally:
        conn.close()


def _set_task_status(task_id: int, status: str) -> None:
    """任务行状态更新（内部：start/pause 等已校验前置状态的窄口）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        raise RuntimeError("PG 不可用，无法更新任务状态")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE strategy_task SET status = %s, updated_at = NOW() WHERE id = %s",
                (status, task_id),
            )
        conn.commit()
    finally:
        conn.close()


def set_task_status(task_id: int, status: str, scanned: Optional[int] = None, total: Optional[int] = None) -> bool:
    """执行器推进任务状态/进度（每个 code 边界提交，design D4 乐观进度）。

    status 必须在取值域内；scanned/total 传 None 不更新对应列。
    返回 True 表示任务行存在并已更新（任务被并发删除时 False，执行器停扫）。
    """
    if status not in TASK_STATUSES:
        raise ValueError(f"非法任务状态: {status}")
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return False
    sets = ["status = %s", "updated_at = NOW()"]
    values: list[Any] = [status]
    if scanned is not None:
        sets.append("progress_scanned = %s")
        values.append(scanned)
    if total is not None:
        sets.append("progress_total = %s")
        values.append(total)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE strategy_task SET {', '.join(sets)} WHERE id = %s",
                values + [task_id],
            )
            ok = cur.rowcount > 0
        conn.commit()
        return ok
    finally:
        conn.close()


def get_task_status(task_id: int) -> Optional[str]:
    """只读任务当前状态（执行器每个 code 边界的暂停检查用，轻量单列查询）。"""
    conn = _get_pg_conn()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM strategy_task WHERE id = %s", (task_id,))
            row = cur.fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def list_persistent_tasks() -> list[dict]:
    """列出全部 persistent 任务（EOD 日终调度增量扫描用，design D4）。

    test 任务不参与日终调度（只在用户启动/续跑时执行，strategy-signal spec）。
    """
    return list_tasks(mode="persistent")


def list_running_tasks() -> list[dict]:
    """列出全部 running 任务（单 worker 执行器任务队列用，design D4）。"""
    return list_tasks(status="running")


def _task_row_to_dict(row) -> dict:
    """任务 DB 行 → 字典（row: id, strategy_id, label, user_group, params,
    params_version, scope_type, scope_codes, mode, status, progress_scanned,
    progress_total, created_by, created_at, updated_at）。"""
    params = row[4]
    if isinstance(params, str):
        params = json.loads(params)
    scope_codes = row[7]
    if isinstance(scope_codes, str):
        scope_codes = json.loads(scope_codes)
    return {
        "id": row[0],
        "strategy_id": row[1],
        "label": row[2],
        "user_group": row[3] or "",
        "params": params or {},
        "params_version": row[5],
        "scope_type": row[6],
        "scope_codes": scope_codes,
        "mode": row[8],
        "status": row[9],
        "progress_scanned": row[10],
        "progress_total": row[11],
        "created_by": row[12],
        "created_at": row[13].isoformat() if hasattr(row[13], "isoformat") else str(row[13]),
        "updated_at": row[14].isoformat() if hasattr(row[14], "isoformat") else str(row[14]),
    }


# ----------------------------------------------------------------------
# 逐股结果（strategy-task-redesign design D1：显式范围任务落行）
# ----------------------------------------------------------------------

def upsert_stock_result(
    task_id: int,
    code: str,
    matched: bool,
    run_status: str,
    params_version: int,
    message: Optional[str] = None,
    signal_date: Optional[str] = None,
) -> None:
    """写入/覆盖一行逐股结果（UNIQUE(task_id, code)，重跑 = 最新一轮快照）。

    - matched：是否命中策略（命中行冗余 signal_date）
    - run_status：'ok' | 'failed'（failed 时 message 存失败原因）
    - 全量范围任务不调用本函数（spec「全量范围不落逐股结果」，由调度方分叉）
    """
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO strategy_task_stock_result
                     (task_id, code, matched, run_status, message, signal_date, params_version)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (task_id, code) DO UPDATE SET
                     matched       = EXCLUDED.matched,
                     run_status    = EXCLUDED.run_status,
                     message       = EXCLUDED.message,
                     signal_date   = EXCLUDED.signal_date,
                     params_version = EXCLUDED.params_version,
                     executed_at   = NOW()""",
                (task_id, code, bool(matched), run_status, message, signal_date, params_version),
            )
        conn.commit()
    finally:
        conn.close()


def query_stock_results(
    task_id: int,
    page: int = 1,
    page_size: int = 50,
    matched: Optional[bool] = None,
    run_status: str = "",
) -> dict:
    """分页查询任务逐股结果（任务详情 per_stock 块数据源）。

    返回 {items, total, page, page_size}；行含股票名称（LEFT JOIN stock）。
    matched 三态过滤：True 只回命中行 / False 只回未命中行 / None 不过滤。
    """
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    conditions = ["r.task_id = %s"]
    params: list[Any] = [task_id]
    if matched is not None:
        conditions.append("r.matched = %s")
        params.append(matched)
    if run_status:
        conditions.append("r.run_status = %s")
        params.append(run_status)
    where_clause = "WHERE " + " AND ".join(conditions)

    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) FROM strategy_task_stock_result r {where_clause}",
                params,
            )
            total = cur.fetchone()[0]
            offset = (page - 1) * page_size
            cur.execute(
                f"""
                SELECT r.id, r.code, r.matched, r.run_status, r.message,
                       r.signal_date, r.params_version, r.executed_at,
                       COALESCE(s.name, r.code) AS stock_name
                FROM strategy_task_stock_result r
                LEFT JOIN stock s ON r.code = s.code
                {where_clause}
                ORDER BY r.matched DESC, r.executed_at DESC, r.code
                LIMIT %s OFFSET %s
                """,
                params + [page_size, offset],
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    items = []
    for row in rows:
        items.append({
            "id": row[0],
            "code": row[1],
            "name": row[8],
            "matched": bool(row[2]),
            "run_status": row[3],
            "message": row[4],
            "signal_date": row[5].isoformat() if hasattr(row[5], "isoformat") and row[5] else None,
            "params_version": row[6],
            "executed_at": row[7].isoformat() if hasattr(row[7], "isoformat") else str(row[7]),
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def count_stock_results(task_id: int) -> dict:
    """任务逐股结果聚合计数（summary 块数据源）：{total, matched, failed}。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return {"total": 0, "matched": 0, "failed": 0}
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COUNT(*),
                          COUNT(*) FILTER (WHERE matched = TRUE),
                          COUNT(*) FILTER (WHERE run_status = 'failed')
                   FROM strategy_task_stock_result WHERE task_id = %s""",
                (task_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    return {"total": int(row[0]), "matched": int(row[1]), "failed": int(row[2])}


# ----------------------------------------------------------------------
# 信号 upsert（strategy-signal-page design D8 冻结门 + 任务维度 params_version
# + strategy-signal-outcome design D5 绩效四字段扩展）
# ----------------------------------------------------------------------

# 匹配态集合（strategy-signal-outcome design D2：两策略匹配态同名，行级判定
# 不引入声明——query_signals matched_only 过滤与 kv 准确率聚合共用）
MATCHED_STATES = ("triggered", "running")


def _signal_values(task_id: int, params_version: int, ev: dict) -> tuple:
    """SignalEvent dict → upsert 行参数（payload 序列化 JSONB）。

    绩效四字段（D5）：事件 dict 缺键时写 NULL——引擎只对匹配态
    （triggered/running）计算绩效，watching/expired 态事件不带绩效键，
    落 NULL 不覆盖已有判定（expired 的重扫演进本身也重写 NULL 语义正确：
    expired 无绩效）。
    """
    payload = ev.get("payload") or {}
    return (
        task_id,
        ev["code"],
        ev["signal_date"],
        ev["state"],
        bool(ev.get("is_buy", True)),
        ev.get("entry_ref_price"),
        ev.get("stop_ref_price"),
        json.dumps(payload, ensure_ascii=False),
        params_version,
        ev.get("ret_7d"),
        ev.get("ret_14d"),
        ev.get("ret_30d"),
        ev.get("outcome"),
    )


def upsert_signals(task_id: int, events: list[dict], params_version: int = 1) -> None:
    """批量 upsert 信号（executemany，frozen 冻结门保留）。

    ON CONFLICT (task_id, code, signal_date) DO UPDATE ...
    WHERE strategy_signal.frozen = FALSE —— 已冻结（加监控）的行不被引擎覆盖
    （strategy-signal-page design D8 状态冻结边界；frozen 行整体不覆盖，
    绩效四字段与 state 同生共死，D5）。
    行携带产生该信号的 params_version（spec「信号携带参数版本」）与绩效
    四字段 ret_7d/ret_14d/ret_30d/outcome（strategy-signal-outcome spec
    「信号绩效（outcome）口径」）。
    """
    if not events:
        return
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO strategy_signal
                     (task_id, code, signal_date, state, is_buy,
                      entry_ref_price, stop_ref_price, payload, params_version,
                      ret_7d, ret_14d, ret_30d, outcome)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
                   ON CONFLICT (task_id, code, signal_date) DO UPDATE SET
                     state           = EXCLUDED.state,
                     is_buy          = EXCLUDED.is_buy,
                     entry_ref_price = EXCLUDED.entry_ref_price,
                     stop_ref_price  = EXCLUDED.stop_ref_price,
                     payload         = EXCLUDED.payload,
                     params_version  = EXCLUDED.params_version,
                     ret_7d          = EXCLUDED.ret_7d,
                     ret_14d         = EXCLUDED.ret_14d,
                     ret_30d         = EXCLUDED.ret_30d,
                     outcome         = EXCLUDED.outcome,
                     updated_at      = NOW()
                   WHERE strategy_signal.frozen = FALSE""",
                [_signal_values(task_id, params_version, ev) for ev in events],
            )
        conn.commit()
    finally:
        conn.close()


def freeze_signal_in_conn(cur, task_id: int, code: str, signal_date: str) -> None:
    """在调用方已开启的事务内冻结信号（monitor create 同事务版，design D8）。

    注意：必须走调用方的事务连接（monitor 创建与冻结同生共死），不能自连接自提交。
    """
    cur.execute(
        """UPDATE strategy_signal SET frozen = TRUE
           WHERE task_id = %s AND code = %s AND signal_date = %s""",
        (task_id, code, signal_date),
    )


# ----------------------------------------------------------------------
# 信号查询（strategy-signal spec：任务维度分页筛选）
# ----------------------------------------------------------------------

def _date_range_conditions(
    date_from: str, date_to: str, conditions: list[str], params: list[Any]
) -> None:
    """日期范围条件追加（与 bsp_store 同语义）：半开区间 `[date_from, date_to + 1)`。

    只传一端单边过滤、双空不过滤；date_to 含当日（闭区间语义），实现为
    Python 侧 `date.fromisoformat(date_to) + 1 day` 后与 signal_date（DATE 列）比较。
    """
    if date_from:
        conditions.append("g.signal_date >= %s")
        params.append(_date.fromisoformat(date_from))
    if date_to:
        conditions.append("g.signal_date < %s")
        params.append(_date.fromisoformat(date_to) + timedelta(days=1))


def query_signals(
    task_id: int,
    state: str = "",
    direction: str = "",
    date_from: str = "",
    date_to: str = "",
    keyword: str = "",
    page: int = 1,
    page_size: int = 20,
    matched_only: bool = False,
) -> dict:
    """条件查询某任务的信号，返回 {items, total, page, page_size}。

    - state/direction/keyword 全部下推同一 WHERE（keyword 匹配 code/name ILIKE，
      与 bsp_store.query_bsp 条件构造风格一致）；COUNT 与分页共用条件
    - matched_only（strategy-signal-outcome design D6）：True 时
      state IN ('triggered','running')（任务详情 signals 块数据源——
      expired 等策略放弃态不出现在任务详情，spec「任务详情只展示匹配信号」）；
      与 state 参数互斥由调用方保证（detail 路由只传 matched_only）
    - items 行含股票名称（LEFT JOIN stock）与 payload 解包 dict、params_version
      （信号行展示参数版本标识，spec「信号版本归因」）与绩效四字段
      ret_7d/ret_14d/ret_30d/outcome（行透传，NULL 表示无绩效/数据不足）；
      行业由 router 层按页批量取
    """
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    conditions = ["g.task_id = %s"]
    params: list[Any] = [task_id]

    if state:
        conditions.append("g.state = %s")
        params.append(state)
    if matched_only:
        # 匹配态过滤（D2 常量一处声明；取值域当前恒为 triggered/running 两值）
        conditions.append("g.state IN (%s, %s)")
        params.extend(MATCHED_STATES)
    if direction == "buy":
        conditions.append("g.is_buy = TRUE")
    elif direction == "sell":
        conditions.append("g.is_buy = FALSE")
    _date_range_conditions(date_from, date_to, conditions, params)
    if keyword:
        kw = f"%{keyword}%"
        conditions.append("(g.code ILIKE %s OR s.name ILIKE %s)")
        params.extend([kw, kw])

    where_clause = "WHERE " + " AND ".join(conditions)

    try:
        with conn.cursor() as cur:
            # COUNT 与分页共用同一 WHERE（keyword 依赖 stock join，FROM/JOIN 保持一致）
            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM strategy_signal g
                LEFT JOIN stock s ON g.code = s.code
                {where_clause}
                """,
                params,
            )
            total = cur.fetchone()[0]

            offset = (page - 1) * page_size
            cur.execute(
                f"""
                SELECT g.id, g.code, g.signal_date, g.state, g.is_buy,
                       g.entry_ref_price, g.stop_ref_price, g.payload, g.frozen,
                       g.params_version,
                       g.ret_7d, g.ret_14d, g.ret_30d, g.outcome,
                       COALESCE(s.name, g.code) AS stock_name
                FROM strategy_signal g
                LEFT JOIN stock s ON g.code = s.code
                {where_clause}
                ORDER BY g.signal_date DESC, g.code
                LIMIT %s OFFSET %s
                """,
                params + [page_size, offset],
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    items = []
    for row in rows:
        payload = row[7]
        if isinstance(payload, str):
            payload = json.loads(payload)
        items.append({
            "id": row[0],
            "code": row[1],
            "name": row[14],
            "signal_date": row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2]),
            "state": row[3],
            "is_buy": bool(row[4]),
            "entry_ref_price": row[5],
            "stop_ref_price": row[6],
            "payload": payload or {},
            "frozen": bool(row[8]),
            "params_version": row[9],
            "ret_7d": float(row[10]) if row[10] is not None else None,
            "ret_14d": float(row[11]) if row[11] not in (None, "") else None,
            "ret_30d": float(row[12]) if row[12] not in (None, "") else None,
            "outcome": row[13],
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


def get_task_signal_counts() -> dict[int, int]:
    """按任务统计信号数 {task_id: count}（侧栏任务节点计数接口）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT task_id, COUNT(*) FROM strategy_signal GROUP BY task_id"
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return {int(r[0]): int(r[1]) for r in rows}


def get_signal_for_monitor(
    task_id: int, signal_date: str, code: str
) -> Optional[dict]:
    """供 monitor 回查（strategy-signal-downstream spec：按任务 + 信号日期定位）。

    返回 {state, is_buy, entry_ref_price} 或 None（查不到走兜底）。
    """
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT state, is_buy, entry_ref_price
                   FROM strategy_signal
                   WHERE task_id = %s AND signal_date = %s AND code = %s""",
                (task_id, signal_date, code),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {
        "state": row[0],
        "is_buy": bool(row[1]),
        "entry_ref_price": row[2],
    }


# ----------------------------------------------------------------------
# kv 统计聚合（vp-entry-strategy-integration design D5：detail API 服务端算）
# ----------------------------------------------------------------------

def compute_vp_entry_kv_stats(task_id: int) -> dict:
    """vp_entry 任务详情 kv 块统计（一次性拉该任务全部信号 payload 内存聚合）。

    统计项（vp-entry-strategy spec「任务详情 kv 统计」）：
    - 信号总数 / 存活信号数（state=triggered 未演进）
    - 分钟版/日线版占比（entry_mode）、Spring 豁免占比（payload.spring）
    - 净漂移三桶分布（payload.drift_bucket: low/mid/high）
    - 平均影线盒宽（payload.wick_box）/ 平均蓄势天数（payload.box_days）/
      平均 A 日涨幅（payload.a_ret）

    kv 块声明（detail_schema items[].key）与返回键一一对应；占比类格式化为
    "xx.x%" 字符串（前端 kv 块 str 原样展示）。无信号时全零值。
    """
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT state, payload FROM strategy_signal WHERE task_id = %s",
                (task_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    total = len(rows)
    if total == 0:
        return {
            "total_signals": 0, "alive_signals": 0,
            "minute_ratio": "0.0%", "daily_ratio": "0.0%",
            "spring_ratio": "0.0%",
            "drift_low_ratio": "0.0%", "drift_mid_ratio": "0.0%",
            "drift_high_ratio": "0.0%",
            "avg_wick_box": 0.0, "avg_box_days": 0.0, "avg_a_ret": "0.00%",
        }

    n_minute = n_daily = n_spring = 0
    drift = {"low": 0, "mid": 0, "high": 0}
    wick_sum = wick_n = 0
    box_sum = box_n = 0
    a_ret_sum = a_ret_n = 0.0
    alive = 0
    for state, payload in rows:
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                payload = {}
        payload = payload or {}
        mode = payload.get("entry_mode")
        if mode == "minute":
            n_minute += 1
        elif mode == "daily":
            n_daily += 1
        if payload.get("spring"):
            n_spring += 1
        bucket = payload.get("drift_bucket")
        if bucket in drift:
            drift[bucket] += 1
        for k, acc in (("wick_box", "wick"), ("box_days", "box"), ("a_ret", "a_ret")):
            v = payload.get(k)
            if isinstance(v, (int, float)) and v == v:  # 数值且非 NaN
                if acc == "wick":
                    wick_sum += v
                    wick_n += 1
                elif acc == "box":
                    box_sum += v
                    box_n += 1
                else:
                    a_ret_sum += v
                    a_ret_n += 1
        if state == "triggered":
            alive += 1

    def _pct(n: int) -> str:
        return f"{n / total * 100:.1f}%"

    return {
        "total_signals": total,
        "alive_signals": alive,
        "minute_ratio": _pct(n_minute),
        "daily_ratio": _pct(n_daily),
        "spring_ratio": _pct(n_spring),
        "drift_low_ratio": _pct(drift["low"]),
        "drift_mid_ratio": _pct(drift["mid"]),
        "drift_high_ratio": _pct(drift["high"]),
        "avg_wick_box": round(wick_sum / wick_n, 4) if wick_n else 0.0,
        "avg_box_days": round(box_sum / box_n, 2) if box_n else 0.0,
        "avg_a_ret": f"{a_ret_sum / a_ret_n * 100:.2f}%" if a_ret_n else "0.00%",
    }


def compute_outcome_kv_stats(task_id: int) -> dict:
    """通用绩效聚合（strategy-signal-outcome design D6：两策略 kv 块共用）。

    SQL COUNT(*) FILTER + AVG 一条查询（独立列的收益，D1）：
    - success_cnt / failed_cnt / pending_cnt：outcome 三态计数
      （只统计匹配态行——非匹配态行的 outcome 恒为 NULL，FILTER 天然排除）
    - accuracy = success / (success + failed)，分母 0 时 None（pending
      数据不足信号不入分母，spec「任务详情准确率」）
    - avg_ret_7d/14d/30d：非 NULL 收益率均值（无样本时 None）

    kv 块声明（detail_schema items[].key）与返回键一一对应；无信号时
    计数全零、accuracy 与均值为 None。
    """
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT
                       COUNT(*) FILTER (WHERE outcome = 'success'),
                       COUNT(*) FILTER (WHERE outcome = 'failed'),
                       COUNT(*) FILTER (WHERE outcome = 'pending'),
                       AVG(ret_7d)  FILTER (WHERE ret_7d IS NOT NULL),
                       AVG(ret_14d) FILTER (WHERE ret_14d IS NOT NULL),
                       AVG(ret_30d) FILTER (WHERE ret_30d IS NOT NULL)
                   FROM strategy_signal
                   WHERE task_id = %s AND state IN ('triggered', 'running')""",
                (task_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    success_cnt, failed_cnt, pending_cnt = int(row[0]), int(row[1]), int(row[2])
    denom = success_cnt + failed_cnt
    return {
        "success_cnt": success_cnt,
        "failed_cnt": failed_cnt,
        "pending_cnt": pending_cnt,
        "accuracy": round(success_cnt / denom, 4) if denom else None,
        "avg_ret_7d": round(float(row[3]), 6) if row[3] is not None else None,
        "avg_ret_14d": round(float(row[4]), 6) if row[4] is not None else None,
        "avg_ret_30d": round(float(row[5]), 6) if row[5] is not None else None,
    }


def get_definitions_with_tasks() -> list[dict]:
    """代码注册表 + PG 任务树合并（GET /api/strategy/definitions 数据源）。

    返回 [{id,name,group_name,sort,params_schema,states,columns,detail_schema,
    tasks:[{...任务字段..., signal_count}]}]，按 (sort, id) 排序；
    signal_count 来自 get_task_signal_counts（按任务统计）。
    """
    from .strategy_engines import DEFINITIONS

    counts = get_task_signal_counts()
    tasks = list_tasks()
    by_strategy: dict[str, list[dict]] = {}
    for t in tasks:
        node = dict(t)
        node["signal_count"] = counts.get(t["id"], 0)
        by_strategy.setdefault(t["strategy_id"], []).append(node)

    result = []
    for d in sorted(DEFINITIONS.values(), key=lambda x: (x.sort, x.id)):
        result.append({
            "id": d.id,
            "name": d.name,
            "group_name": d.group_name,
            "sort": d.sort,
            "params_schema": d.params_schema,
            "states": d.states,
            "columns": d.columns,
            "detail_schema": d.detail_schema,
            "tasks": by_strategy.get(d.id, []),
        })
    return result


# ----------------------------------------------------------------------
# 扫描游标（design D4：独立 strategy_scan_cursor，键为 (task_id, code)）
# ----------------------------------------------------------------------

def get_scan_cursors(task_id: int) -> dict[str, str]:
    """一次读回某任务全部水位 {code: watermark}（批量调度用）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT code, watermark FROM strategy_scan_cursor WHERE task_id = %s",
                (task_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return {c: w for c, w in rows}


def set_scan_cursor(task_id: int, code: str, watermark: str) -> None:
    """推进 (task_id, code) 扫描水位（幂等 upsert）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO strategy_scan_cursor (task_id, code, watermark)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (task_id, code) DO UPDATE SET
                     watermark = EXCLUDED.watermark""",
                (task_id, code, watermark),
            )
        conn.commit()
    finally:
        conn.close()


# 模块加载时自动建表
_ensure_tables()
