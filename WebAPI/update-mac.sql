-- ============================================================================
-- WebAPI/update-mac.sql — macOS 机器 PG（chan 库）变更记录
-- ============================================================================
-- 规范见 CLAUDE.md「数据库 DDL 变更规范」。
--
-- 在 macOS 上运行本系统期间，凡涉及**修改数据库表**（建表 / 加列 / 加索引 /
-- 加约束等）或**数据库初始化数据**（枚举或字典，如 strategy 定义行、
-- permission 权限项、role 角色项等）的变更，都必须在本文件追加对应 SQL。
--
-- 书写约定：
--   - 每次追加在语句前注释**执行时间**：-- 2026-10-13 xxx 表加列
--   - 所有 SQL 必须**幂等可重跑**：
--       建表            → CREATE TABLE IF NOT EXISTS
--       加列/加索引/加约束 → IF NOT EXISTS，或先查 information_schema /
--                          pg_attribute 再执行的 DO 块判断
--       字典数据        → ON CONFLICT ... DO NOTHING / DO UPDATE
--   - 禁止裸 CREATE / ALTER 直接报错重跑。
--
-- 现状：历史上 WebAPI/update.sql 的语句已废弃并删除；当前 mac 库已对齐代码契约
-- （各 store 模块 _ensure_tables 的惰性 DDL）。后续在 mac 上产生的变更记录于此。
-- ============================================================================


-- 2026-10-13 monitor 表补 updated_at 列
-- 现象：monitor 由 monitor_store._ensure_tables() 惰性建表，建表语句不含
--       updated_at；而 init.sql 无条件 DROP+CREATE 挂 trg_monitor_updated_at
--       BEFORE UPDATE 触发器，该触发器会写 NEW.updated_at。表已存在时 init.sql
--       的 CREATE TABLE IF NOT EXISTS 为 no-op，故出现「有触发器、无列」，
--       任何 UPDATE monitor 都报 record "new" has no field "updated_at"。
-- 修复：补列（惰性 DDL 已同步加到 monitor_store._ensure_tables()，本段仅为记录）。
ALTER TABLE monitor
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
