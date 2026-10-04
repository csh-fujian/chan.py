# -*- coding: utf-8 -*-
"""
Strategy DAO — strategy / strategy_instance / strategy_signal / strategy_scan_cursor
表的 PG 持久化（strategy-signal-page design D1/D2/D8）。

三层模型：
- strategy（定义层）：代码注册（strategy_engines.DEFINITIONS），非用户 CRUD；
  表行在首次访问时由 _sync_definitions 从注册表同步落库（幂等 upsert）
- strategy_instance（使用层）：用户配置，不可变（改参数 = 新实例）；
  删除级联删信号（FK ON DELETE CASCADE）
- strategy_signal（信号）：挂实例，UNIQUE(instance_id, code, signal_date)；
  upsert 带 `WHERE strategy_signal.frozen = FALSE` 冻结门（D8）
- strategy_scan_cursor：(instance_id, code) → watermark（DuckDB time_key 字符串）

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


def _ensure_tables():
    """惰性建表（CREATE TABLE IF NOT EXISTS，风格对齐 bsp_store）。"""
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
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_instance (
                    id          SERIAL PRIMARY KEY,
                    strategy_id VARCHAR NOT NULL REFERENCES strategy(id),
                    label       VARCHAR NOT NULL,
                    params      JSONB NOT NULL DEFAULT '{}',
                    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_signal (
                    id              SERIAL PRIMARY KEY,
                    instance_id     INT NOT NULL REFERENCES strategy_instance(id) ON DELETE CASCADE,
                    code            VARCHAR NOT NULL,
                    signal_date     DATE NOT NULL,
                    state           VARCHAR NOT NULL,
                    is_buy          BOOLEAN NOT NULL,
                    entry_ref_price DOUBLE PRECISION,
                    stop_ref_price  DOUBLE PRECISION,
                    payload         JSONB NOT NULL DEFAULT '{}',
                    frozen          BOOLEAN NOT NULL DEFAULT FALSE,
                    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (instance_id, code, signal_date)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_scan_cursor (
                    instance_id INT NOT NULL,
                    code        VARCHAR NOT NULL,
                    watermark   VARCHAR NOT NULL,
                    PRIMARY KEY (instance_id, code)
                )
                """
            )
            # 定义层从代码注册表同步落库（幂等 upsert，非用户 CRUD），
            # 在同一 cursor/事务内执行（strategy 行是实例 FK 的前提）
            _sync_definitions(cur)
        conn.commit()
    finally:
        conn.close()


def _sync_definitions(cur) -> None:
    """把 strategy_engines.DEFINITIONS 注册表落 strategy 表（幂等 upsert）。

    定义随版本发布，表行只是持久化快照（供 SQL 侧 JOIN 与实例 FK）；
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
# 实例 CRUD（任务 1.2）
# ----------------------------------------------------------------------

def create_instance(
    strategy_id: str, label: str, params: Optional[dict] = None
) -> dict:
    """创建参数实例（design D2：实例不可变，创建后由调用方触发全量回算）。

    params 按 params_schema 校验（validate_params：类型/最小/最大/未知键），
    非法抛 ValueError（router 层转 422）。缺省参数补默认值后落库。
    返回实例 dict；strategy_id 不存在抛 ValueError。
    """
    from .strategy_engines import get_definition, validate_params

    definition = get_definition(strategy_id)
    if definition is None:
        raise ValueError(f"策略定义不存在: {strategy_id}")
    if not label or not str(label).strip():
        raise ValueError("实例名称（label）不能为空")

    normalized, errors = validate_params(definition, params)
    if errors:
        raise ValueError("；".join(errors))

    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        raise RuntimeError("PG 不可用，无法创建策略实例")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO strategy_instance (strategy_id, label, params)
                   VALUES (%s, %s, %s::jsonb)
                   RETURNING id, strategy_id, label, params, enabled, created_at""",
                (strategy_id, str(label).strip(), json.dumps(normalized, ensure_ascii=False)),
            )
            row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()
    return _instance_row_to_dict(row)


def list_instances(strategy_id: Optional[str] = None) -> list[dict]:
    """列出实例（可按策略定义过滤），按 created_at 升序。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return []
    sql = """
        SELECT i.id, i.strategy_id, i.label, i.params, i.enabled, i.created_at
        FROM strategy_instance i
    """
    params: list[Any] = []
    if strategy_id:
        sql += "WHERE i.strategy_id = %s"
        params.append(strategy_id)
    sql += "ORDER BY i.created_at, i.id"
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()
    return [_instance_row_to_dict(r) for r in rows]


def get_instance(instance_id: int) -> Optional[dict]:
    """取单个实例（调度/路由存在性校验用）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, strategy_id, label, params, enabled, created_at
                   FROM strategy_instance WHERE id = %s""",
                (instance_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    return _instance_row_to_dict(row) if row else None


def set_enabled(instance_id: int, enabled: bool) -> bool:
    """启用/停用实例（停用不参与调度，已产生信号仍可查询）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE strategy_instance SET enabled = %s WHERE id = %s",
                (bool(enabled), instance_id),
            )
            ok = cur.rowcount > 0
        conn.commit()
        return ok
    finally:
        conn.close()


def delete_instance(instance_id: int) -> bool:
    """删除实例（FK ON DELETE CASCADE 级联删信号；游标表显式删）。

    返回 True 成功；实例不存在返回 False。
    """
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            # strategy_scan_cursor 无 FK（独立游标表，design D4），显式删除
            cur.execute(
                "DELETE FROM strategy_scan_cursor WHERE instance_id = %s",
                (instance_id,),
            )
            cur.execute("DELETE FROM strategy_instance WHERE id = %s", (instance_id,))
            ok = cur.rowcount > 0
        conn.commit()
        return ok
    finally:
        conn.close()


def list_enabled_instances() -> list[dict]:
    """列出全部启用实例（EOD 调度增量扫描用，design D4）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, strategy_id, label, params, enabled, created_at
                   FROM strategy_instance WHERE enabled = TRUE
                   ORDER BY created_at, id"""
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [_instance_row_to_dict(r) for r in rows]


def _instance_row_to_dict(row) -> dict:
    """实例 DB 行 → 字典（row: id, strategy_id, label, params, enabled, created_at）。"""
    params = row[3]
    if isinstance(params, str):
        params = json.loads(params)
    return {
        "id": row[0],
        "strategy_id": row[1],
        "label": row[2],
        "params": params or {},
        "enabled": bool(row[4]),
        "created_at": row[5].isoformat() if hasattr(row[5], "isoformat") else str(row[5]),
    }


# ----------------------------------------------------------------------
# 信号 upsert（任务 1.3，design D8 冻结门）
# ----------------------------------------------------------------------

def _signal_values(instance_id: int, ev: dict) -> tuple:
    """SignalEvent dict → upsert 行参数（payload 序列化 JSONB）。"""
    payload = ev.get("payload") or {}
    return (
        instance_id,
        ev["code"],
        ev["signal_date"],
        ev["state"],
        bool(ev.get("is_buy", True)),
        ev.get("entry_ref_price"),
        ev.get("stop_ref_price"),
        json.dumps(payload, ensure_ascii=False),
    )


def upsert_signal(instance_id: int, ev: dict) -> None:
    """写入或更新一条信号（单条版本）。

    ON CONFLICT (instance_id, code, signal_date) DO UPDATE ...
    WHERE strategy_signal.frozen = FALSE —— 已冻结（加监控）的行不被引擎覆盖
    （design D8 状态冻结边界）。
    """
    upsert_signals(instance_id, [ev])


def upsert_signals(instance_id: int, events: list[dict]) -> None:
    """批量 upsert 信号（executemany，frozen 冻结门同上）。"""
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
                     (instance_id, code, signal_date, state, is_buy,
                      entry_ref_price, stop_ref_price, payload)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                   ON CONFLICT (instance_id, code, signal_date) DO UPDATE SET
                     state          = EXCLUDED.state,
                     is_buy         = EXCLUDED.is_buy,
                     entry_ref_price = EXCLUDED.entry_ref_price,
                     stop_ref_price = EXCLUDED.stop_ref_price,
                     payload        = EXCLUDED.payload,
                     updated_at     = NOW()
                   WHERE strategy_signal.frozen = FALSE""",
                [_signal_values(instance_id, ev) for ev in events],
            )
        conn.commit()
    finally:
        conn.close()


def freeze_signal(instance_id: int, code: str, signal_date: str) -> bool:
    """置 frozen=TRUE（加监控成功时同事务调用，design D8）。

    返回 True 表示命中一行并置位；信号不存在返回 False。
    """
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE strategy_signal SET frozen = TRUE
                   WHERE instance_id = %s AND code = %s AND signal_date = %s""",
                (instance_id, code, signal_date),
            )
            ok = cur.rowcount > 0
        conn.commit()
        return ok
    finally:
        conn.close()


def freeze_signal_in_conn(cur, instance_id: int, code: str, signal_date: str) -> None:
    """在调用方已开启的事务内冻结信号（monitor create 同事务版，design D8）。

    注意：必须走调用方的事务连接（monitor 创建与冻结同生共死），不能自连接自提交。
    """
    cur.execute(
        """UPDATE strategy_signal SET frozen = TRUE
           WHERE instance_id = %s AND code = %s AND signal_date = %s""",
        (instance_id, code, signal_date),
    )


# ----------------------------------------------------------------------
# 信号查询（任务 1.4）
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
    instance_id: int,
    state: str = "",
    direction: str = "",
    date_from: str = "",
    date_to: str = "",
    keyword: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """条件查询某实例的信号，返回 {items, total, page, page_size}。

    - state/direction/keyword 全部下推同一 WHERE（keyword 匹配 code/name ILIKE，
      与 bsp_store.query_bsp 条件构造风格一致）；COUNT 与分页共用条件
    - items 行含股票名称（LEFT JOIN stock）与 payload 解包 dict；
      行业由 router 层按页批量取（get_industries_for_codes，与 bsp 路由同构）
    """
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    conditions = ["g.instance_id = %s"]
    params: list[Any] = [instance_id]

    if state:
        conditions.append("g.state = %s")
        params.append(state)
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
            "name": row[9],
            "signal_date": row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2]),
            "state": row[3],
            "is_buy": bool(row[4]),
            "entry_ref_price": row[5],
            "stop_ref_price": row[6],
            "payload": payload or {},
            "frozen": bool(row[8]),
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


def get_instance_signal_counts() -> dict[int, int]:
    """按实例统计信号数 {instance_id: count}（侧栏计数接口）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT instance_id, COUNT(*) FROM strategy_signal GROUP BY instance_id"
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return {int(r[0]): int(r[1]) for r in rows}


def get_signal_for_monitor(
    instance_id: int, signal_date: str, code: str
) -> Optional[dict]:
    """供 monitor 回查（strategy-signal-downstream spec：按实例 + 信号日期定位）。

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
                   WHERE instance_id = %s AND signal_date = %s AND code = %s""",
                (instance_id, signal_date, code),
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


def get_definitions_with_instances() -> list[dict]:
    """代码注册表 + PG 实例树合并（GET /api/strategy/definitions 数据源）。

    返回 [{id,name,group_name,sort,params_schema,states,columns,
    instances:[{id,label,params,enabled,signal_count}]}]，按 (sort, id) 排序；
    signal_count 来自 get_instance_signal_counts（按实例统计）。
    """
    from .strategy_engines import DEFINITIONS

    counts = get_instance_signal_counts()
    instances = list_instances()
    by_strategy: dict[str, list[dict]] = {}
    for ins in instances:
        by_strategy.setdefault(ins["strategy_id"], []).append({
            "id": ins["id"],
            "label": ins["label"],
            "params": ins["params"],
            "enabled": ins["enabled"],
            "signal_count": counts.get(ins["id"], 0),
        })

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
            "instances": by_strategy.get(d.id, []),
        })
    return result


# ----------------------------------------------------------------------
# 扫描游标（design D4：独立 strategy_scan_cursor，不与 recompute_cursor 混用）
# ----------------------------------------------------------------------

def get_scan_cursor(instance_id: int, code: str) -> Optional[str]:
    """读 (instance_id, code) 扫描水位（None = 从未扫过，触发全量回算）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT watermark FROM strategy_scan_cursor WHERE instance_id = %s AND code = %s",
                (instance_id, code),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def get_scan_cursors(instance_id: int) -> dict[str, str]:
    """一次读回某实例全部水位 {code: watermark}（批量调度用）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT code, watermark FROM strategy_scan_cursor WHERE instance_id = %s",
                (instance_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return {c: w for c, w in rows}


def set_scan_cursor(instance_id: int, code: str, watermark: str) -> None:
    """推进 (instance_id, code) 扫描水位（幂等 upsert）。"""
    _ensure_tables()
    conn = _get_pg_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO strategy_scan_cursor (instance_id, code, watermark)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (instance_id, code) DO UPDATE SET
                     watermark = EXCLUDED.watermark""",
                (instance_id, code, watermark),
            )
        conn.commit()
    finally:
        conn.close()


# 模块加载时自动建表
_ensure_tables()
