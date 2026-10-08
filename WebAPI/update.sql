-- WebAPI 数据库 DDL 变更记录（CLAUDE.md 规范：所有语句幂等可重跑，语句前带执行时间注释）

-- 2026-10-08 bsp_index 加确认状态列（bsp-sure-annotation design D2）
-- 买卖点依托已确认线段 → TRUE；依托虚段（未确认段）→ FALSE。
-- 存量行按 DEFAULT TRUE（已确认）回填，误差由下一轮整套替换写入（DELETE→INSERT 全集）自愈。
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'bsp_index'
          AND column_name = 'is_sure'
    ) THEN
        ALTER TABLE bsp_index ADD COLUMN is_sure BOOLEAN NOT NULL DEFAULT TRUE;
    END IF;
END $$;

-- 2026-10-08 bsp_index 加确认阶梯列（bsp-ladder-change design D4）
-- ladder：L1 小级别区间套 / L2 虚笔候选 / L3 背驰预警 / L4 确认买卖点（单一字段）。
-- 存量行不回填（NULL），查询侧按 is_sure 映射兜底（true→L4 / false→L2，
-- ladder_of_legacy），下一次整套替换写入后收敛为精确值。
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'bsp_index'
          AND column_name = 'ladder'
    ) THEN
        ALTER TABLE bsp_index ADD COLUMN ladder VARCHAR(2);
    END IF;
END $$;
