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

-- 2026-10-21 chan-standard-bsp / D11：买卖点配置指纹列（Windows 机器上执行）
-- 背景：chan_snapshot 与 chan_stable_prefix 的键都不含配置。切换 bsp_preset 或任一
--       买卖点开关后，快照续算只重算未确认尾部、缓存命中直接返回旧 JSON，导致
--       「配置改了但输出没变」且新旧口径的买卖点混在同一份 bsp_index 里。
-- 做法：两表各加 config_fingerprint（对买卖点相关配置求稳定哈希），读取时比对，
--       不一致即视为缓存未命中 / 强制全量重算。存量行该列为 NULL，视为不匹配。
-- 实际加列由 bsp_store._ensure_tables() 与 cache.py 的惰性 DDL 完成，
-- 此处仅为变更记录。两条语句均幂等，可重复执行。
ALTER TABLE chan_snapshot
    ADD COLUMN IF NOT EXISTS config_fingerprint VARCHAR;
ALTER TABLE chan_stable_prefix
    ADD COLUMN IF NOT EXISTS config_fingerprint VARCHAR;

-- 2026-10-21 chan-standard-bsp / tasks 15.2：三买方向化标签拆分（无 DDL 变更，仅记录）
-- 前端把 3a/3b 拆成 3B(后)/3B(内) 后，后端方向化标签表（bsp_store.DIRECTIONAL_LABELS）
-- 需同步支持四个新标签，否则新标签会拿中文串去匹配原始枚举列、永远 0 行。
-- 该表在代码内，无数据库变更；本段仅作变更记录，无可执行 SQL。

-- 2026-10-25 chan-bsp-ladder-change / D5：bsp_index.ladder 列宽扩容（Windows 机器上执行）
-- 背景：确认阶梯从「单一 L1/L2/L3 标签」改为「三轴组合值」（进度轴 + 佐证轴 + 分型轴），
--       组合串最长如 `L2|L2-3|L3-3`（13 字符），超出旧 VARCHAR(2)。
-- 做法：扩到 VARCHAR(16)（留 3 字符余量）。幂等：先查 information_schema 的当前宽度，
--       仅在不足 16 时 ALTER，重复执行不报错、不缩容。
-- 实际执行由 bsp_store._ensure_tables() 的惰性 DDL 完成，此处为变更记录。
-- 注意：旧 L1/L2/L3 语义已反向重定义，扩容后必须全量回刷 bsp_index（清理旧值）。
DO $$
DECLARE cur_len INT;
BEGIN
    SELECT character_maximum_length INTO cur_len
    FROM information_schema.columns
    WHERE table_name = 'bsp_index' AND column_name = 'ladder';
    IF cur_len IS NOT NULL AND cur_len < 16 THEN
        ALTER TABLE bsp_index ALTER COLUMN ladder TYPE VARCHAR(16);
    END IF;
END $$;

-- 2026-10-25 chan-standard-bsp2-change / D6：bsp_index.ladder 列宽二次扩容（Windows 机器上执行）
-- 背景：T2/T2S 候选点接入五轴阶梯（进度 P | 佐证 S | 确认 C | 分型 K | 时间 T），
--       组合串最长如 `P1|S3|C2|K3|T1`（14 字符），VARCHAR(16) 余量不足，取 32 留余量。
-- 做法：扩到 VARCHAR(32)。幂等：先查 information_schema 的当前宽度，
--       仅在不足 32 时 ALTER，重复执行不报错、不缩容。
-- 实际执行由 bsp_store._ensure_tables() 的惰性 DDL 完成，此处为变更记录。
-- 注意：随本变更 LADDER_SCHEMA_VERSION 升为 bsp2-5axis-v1 触发 fingerprint bump，
--       存量 T2/T2S 行的 NULL ladder 在全量重刷中自然更新为组合值（无需定向回刷）。
DO $$
DECLARE cur_len INT;
BEGIN
    SELECT character_maximum_length INTO cur_len
    FROM information_schema.columns
    WHERE table_name = 'bsp_index' AND column_name = 'ladder';
    IF cur_len IS NOT NULL AND cur_len < 32 THEN
        ALTER TABLE bsp_index ALTER COLUMN ladder TYPE VARCHAR(32);
    END IF;
END $$;

-- 2026-10-25 chan-standard-bsp3-change / D6：T3A/T3B 接入四轴阶梯（Windows 机器上执行）
-- 背景：三买候选点接入四轴阶梯（佐证 S | 确认 C | 分型 K | 时间 T，无进度轴），
--       组合串最长如 `S3|C2|K3|T1`（12 字符），既有 VARCHAR(32) 余量充足，**无需扩容**。
--       本条仅为变更记录：确认列宽满足四轴组合，避免后续误判需要 ALTER。
-- 幂等：仅在宽度不足 32 时 ALTER，重复执行不报错、不缩容。
-- 注意：随本变更 LADDER_SCHEMA_VERSION 升为 bsp3-4axis-v1 触发 fingerprint bump，
--       存量 T3A/T3B 行的 NULL ladder 在全量重刷中自然更新为组合值（无需定向回刷）。
DO $$
DECLARE cur_len INT;
BEGIN
    SELECT character_maximum_length INTO cur_len
    FROM information_schema.columns
    WHERE table_name = 'bsp_index' AND column_name = 'ladder';
    IF cur_len IS NOT NULL AND cur_len < 32 THEN
        ALTER TABLE bsp_index ALTER COLUMN ladder TYPE VARCHAR(32);
    END IF;
END $$;
