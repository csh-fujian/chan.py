# -*- coding: utf-8 -*-
"""
环境配置 — PG/DSN、DuckDB 路径等。
"""

import os

PG_DSN = os.environ.get("PG_DSN", "")

DUCKDB_PATH = os.environ.get(
    "DUCKDB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "Data", "kl_store.duckdb"),
)

# ---- LLM 供应商 env 兜底（kline-page-change design D8.1 三层解析第 2 层） ----
# 环境变量: LLM_BASE_URL / LLM_API_KEY / LLM_MODEL / LLM_TIMEOUT（默认 60s）
# 注意：每次请求实时读取、不缓存进程内（见 llm_store.resolve_llm_config）
LLM_TIMEOUT_DEFAULT = 60.0


def get_llm_env() -> dict:
    """实时读取 LLM_* 环境变量，返回 {base_url, api_key, model, timeout}。"""
    timeout_raw = os.environ.get("LLM_TIMEOUT", "").strip()
    try:
        timeout = float(timeout_raw) if timeout_raw else LLM_TIMEOUT_DEFAULT
    except ValueError:
        timeout = LLM_TIMEOUT_DEFAULT
    return {
        "base_url": os.environ.get("LLM_BASE_URL", "").strip(),
        "api_key": os.environ.get("LLM_API_KEY", "").strip(),
        "model": os.environ.get("LLM_MODEL", "").strip(),
        "timeout": timeout,
    }