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

-- 2026-10-21 chan-standard-bsp / D11：买卖点配置指纹列（macOS 机器上执行）
-- 与 update-win.sql 同批变更的另一侧记录。背景与语义完全一致：
-- chan_snapshot / chan_stable_prefix 的键不含配置，切档位后旧结果会被直接复用，
-- 表现为「配置改了但输出没变」。两表各加 config_fingerprint 供读取时比对。
-- 本段在 macOS 上运行期间产生，实际加列由各 store 的惰性 DDL 完成，此处仅为记录。
-- 两条语句均幂等，可重复执行（重复执行不报错）。
ALTER TABLE chan_snapshot
    ADD COLUMN IF NOT EXISTS config_fingerprint VARCHAR;
ALTER TABLE chan_stable_prefix
    ADD COLUMN IF NOT EXISTS config_fingerprint VARCHAR;

-- 2026-11-08 chan-config-retire-zs-extend：下线 `bsp1_zs_extend_to_seg_end`
--       （「中枢必须延伸到线段末尾」，macOS 机器上执行）
-- 背景：它是 T1/T1P 的路由开关而非判据。开启后中枢未贴到线段末尾的 T1 候选会
--       绕开趋势/新低/DIF/零轴四项标准判据，改走更松的盘整背驰（T1P）通道；
--       实测 49 只日线 23 个成立一买 0 个被否定、反增 8 个，且同一个历史点的
--       类型会随之后线段延伸从 T1 翻转为 T1P。故从配置面板删除、也从
--       config_fingerprint.FINGERPRINT_KEYS 移除（归入 legacy 档由 bsp_preset 区分）。
-- 代码侧兜底：chan_config_store._RETIRED_KEYS / _drop_retired() 在读取、
--       校验、保存三个出口一律清除，因此本 SQL 只是把存量行也擦干净。
-- 幂等：两处 jsonb 各减一个键，键不存在时语句为空操作。
UPDATE chan_config SET overrides = overrides - 'bsp1_zs_extend_to_seg_end'
 WHERE overrides ? 'bsp1_zs_extend_to_seg_end';
UPDATE chan_config SET config = config - 'bsp1_zs_extend_to_seg_end'
 WHERE config ? 'bsp1_zs_extend_to_seg_end';

-- 2026-11-22 chan-pattern-buy-signal：新建形态信号表 pattern_signal（Windows 机器上产生的变更，mac 侧同步执行）
-- 说明同 update-win.sql 同日条目：惰性 DDL 的变更记录，幂等可重复执行。
CREATE TABLE IF NOT EXISTS pattern_signal (
    code VARCHAR(32) NOT NULL,
    kl_type VARCHAR(16) NOT NULL,
    autype VARCHAR(16) NOT NULL DEFAULT 'QFQ',
    pattern_type VARCHAR(32) NOT NULL,
    pattern_date VARCHAR(10) NOT NULL,
    confirm_time_key VARCHAR(32) NOT NULL,
    price DOUBLE PRECISION,
    ref_line_high DOUBLE PRECISION,
    ref_line_low DOUBLE PRECISION,
    score SMALLINT,
    qual VARCHAR(8),
    invalid BOOLEAN NOT NULL DEFAULT FALSE,
    veto VARCHAR(32),
    detail JSONB,
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT pk_pattern_signal UNIQUE
        (code, kl_type, autype, pattern_type, confirm_time_key)
);
CREATE INDEX IF NOT EXISTS idx_pattern_signal_query
    ON pattern_signal (pattern_type, kl_type, pattern_date);
CREATE INDEX IF NOT EXISTS idx_pattern_signal_code
    ON pattern_signal (code, kl_type);

-- 2026-11-22 chan-pattern-sell-signal: pattern_signal 加 direction 列（买/卖方向维度，存量行回填 'buy'）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'pattern_signal' AND column_name = 'direction'
    ) THEN
        ALTER TABLE pattern_signal
            ADD COLUMN direction VARCHAR(4) NOT NULL DEFAULT 'buy';
    END IF;
END
$$;
