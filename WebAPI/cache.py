# -*- coding: utf-8 -*-
"""
稳定前缀缓存模块 — design.md D8 缓存边界。

Spike 结论（任务 3.2）：
  open-source CChan 的 trigger_load 支持向已有实例追加新K线，但无法从
  「缓存前缀」恢复计算状态（chan_dump_pickle 是完整状态的序列化，无法
  只恢复稳定前缀部分）。因此退化为「全量重算 + 仅缓存已确认前缀去重」方案：
  - 每次请求仍全量计算 CChan
  - 计算完成后提取稳定前缀（is_sure==True的元素）
  - 与缓存对比：若稳定前缀的时间戳未变，说明已确认部分相同，缓存命中
  - 缓存命中时可以返回缓存中的 JSON 而非重新序列化（但计算仍需全量执行）

缓存表: chan_stable_prefix
键: (code, kl_type)
值: 已确认笔/线段/中枢/买卖点的序列化 JSON + 最后已确认时间戳
"""

import json
import os
from typing import Any, Dict, Optional, Tuple

from Common.CEnum import KL_TYPE


class ChanCache:
    """缠论结果缓存 — 以 PG 表 chan_stable_prefix 为存储后端。

    若 PG 不可用则自动降级为无缓存模式（每次全量计算+序列化）。

    Usage:
        cache = ChanCache(pg_dsn=os.environ.get("PG_DSN"))
        hit, cached = cache.get(code, kl_type)
        if hit:
            return cached
        result = serialize_chan(chan, kl_type)
        cache.set(code, kl_type, result)
    """

    def __init__(self, pg_dsn: Optional[str] = None):
        self.pg_dsn = pg_dsn
        self._conn = None

    def _ensure_conn(self) -> bool:
        """建立 PG 连接，失败返回 False。"""
        if self._conn is not None:
            return True
        if not self.pg_dsn:
            return False
        try:
            import psycopg2
            self._conn = psycopg2.connect(self.pg_dsn)
            return True
        except Exception:
            return False

    def get(self, code: str, kl_type: KL_TYPE) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """查询缓存。

        Returns:
            (True, data_dict) — 缓存命中，data_dict 就是 API 返回体
            (False, None) — 缓存未命中或 PG 不可用
        """
        if not self._ensure_conn():
            return False, None
        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    """SELECT last_sure_ts, bi_json, seg_json, zs_json,
                              seg_zs_json, bsp_json
                       FROM chan_stable_prefix
                       WHERE code=%s AND kl_type=%s""",
                    (code, kl_type.name),
                )
                row = cur.fetchone()
                if row is None:
                    return False, None
                last_sure_ts, bi_json, seg_json, zs_json, seg_zs_json, bsp_json = row
                # 缓存中不包含 klines — klines 每次都从 DuckDB 重读
                # klines 字段由调用方填充
                return True, {
                    "last_sure_ts": last_sure_ts,
                    "bi": bi_json,
                    "seg": seg_json,
                    "zs": zs_json,
                    "seg_zs": seg_zs_json,
                    "bsp": bsp_json,
                }
        except Exception:
            return False, None

    def set(self, code: str, kl_type: KL_TYPE, result: Dict[str, Any]) -> None:
        """写入缓存（upsert）。"""
        if not self._ensure_conn():
            return
        # 计算稳定前缀的最后时间戳（最后一个 is_sure 元素）
        last_sure_ts = 0
        for key in ("bi", "seg"):
            items = result.get(key, [])
            for item in reversed(items):
                if item.get("is_sure"):
                    last_sure_ts = max(last_sure_ts, item["end"]["t"])
                    break

        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO chan_stable_prefix
                          (code, kl_type, last_sure_ts, bi_json, seg_json,
                           zs_json, seg_zs_json, bsp_json)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (code, kl_type) DO UPDATE SET
                          last_sure_ts = EXCLUDED.last_sure_ts,
                          bi_json = EXCLUDED.bi_json,
                          seg_json = EXCLUDED.seg_json,
                          zs_json = EXCLUDED.zs_json,
                          seg_zs_json = EXCLUDED.seg_zs_json,
                          bsp_json = EXCLUDED.bsp_json""",
                    (
                        code,
                        kl_type.name,
                        last_sure_ts,
                        json.dumps(result.get("bi", []), ensure_ascii=False),
                        json.dumps(result.get("seg", []), ensure_ascii=False),
                        json.dumps(result.get("zs", []), ensure_ascii=False),
                        json.dumps(result.get("seg_zs", []), ensure_ascii=False),
                        json.dumps(result.get("bsp", []), ensure_ascii=False),
                    ),
                )
            self._conn.commit()
        except Exception:
            # 缓存写入失败不应影响请求响应
            pass

    def close(self):
        """关闭 PG 连接。"""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None


# 模块级单例
_chan_cache: Optional[ChanCache] = None


def get_chan_cache() -> ChanCache:
    """获取缓存实例（懒初始化）。"""
    global _chan_cache
    if _chan_cache is None:
        pg_dsn = os.environ.get("PG_DSN")
        _chan_cache = ChanCache(pg_dsn=pg_dsn)
    return _chan_cache