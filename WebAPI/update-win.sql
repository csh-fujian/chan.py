-- ============================================================================
-- WebAPI/update-win.sql — Windows 机器 PG（chan 库）变更记录
-- ============================================================================
-- 规范见 CLAUDE.md「数据库 DDL 变更规范」。
--
-- 在 Windows 上运行本系统期间，凡涉及**修改数据库表**（建表 / 加列 / 加索引 /
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
-- 现状：暂无内容。Windows 机器的 chan 库为参考基准库（表结构正确）；历史上
-- WebAPI/update.sql 的语句已废弃并删除。后续在 Windows 上产生的变更再记录于此。
-- ============================================================================

-- 2026-10-14 strategy-volume-breakout-pullback：新增 strategy_signal_b_event 表
-- （B 级事件独立绩效，openspec 变更 strategy-volume-breakout-pullback design D1）。
-- 实际建表由 strategy_store._ensure_tables 惰性 DDL 完成，此处为变更记录（幂等）。
CREATE TABLE IF NOT EXISTS strategy_signal_b_event (
    id         BIGSERIAL PRIMARY KEY,
    signal_id  INT NOT NULL REFERENCES strategy_signal(id) ON DELETE CASCADE,
    b_level    VARCHAR(8) NOT NULL,
    b_time     VARCHAR(19) NOT NULL,
    b_kl_type  VARCHAR(8) NOT NULL,
    price      DOUBLE PRECISION,
    day_pct    DOUBLE PRECISION,
    ret_7d     DOUBLE PRECISION,
    ret_14d    DOUBLE PRECISION,
    ret_30d    DOUBLE PRECISION,
    outcome    VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (signal_id, b_level, b_time)
);

-- 2026-10-15 strategy-volume-breakout-pullback / strategy-signal-outcome 修订：
-- 绩效窗口 7/14/30 → 5/10/15（加权 30%/50%/20%，阈值 5% 不变）。
-- strategy_signal 与 strategy_signal_b_event 幂等加新绩效列；旧列
-- ret_7d/ret_14d/ret_30d 废弃不删（历史行不迁移，重扫自然覆盖）。
-- 实际加列由 strategy_store._ensure_tables 惰性 DDL 完成，此处为变更记录。
ALTER TABLE strategy_signal ADD COLUMN IF NOT EXISTS ret_5d  DOUBLE PRECISION;
ALTER TABLE strategy_signal ADD COLUMN IF NOT EXISTS ret_10d DOUBLE PRECISION;
ALTER TABLE strategy_signal ADD COLUMN IF NOT EXISTS ret_15d DOUBLE PRECISION;
ALTER TABLE strategy_signal_b_event ADD COLUMN IF NOT EXISTS ret_5d  DOUBLE PRECISION;
ALTER TABLE strategy_signal_b_event ADD COLUMN IF NOT EXISTS ret_10d DOUBLE PRECISION;
ALTER TABLE strategy_signal_b_event ADD COLUMN IF NOT EXISTS ret_15d DOUBLE PRECISION;
