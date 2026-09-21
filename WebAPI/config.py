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