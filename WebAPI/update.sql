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

-- 2026-10-11 策略任务表（strategy-task-redesign design D1）
-- strategy_task 取代 strategy_instance：任务 = 策略 + 股票范围 + 形态（test/persistent）
-- + 状态（pending/running/paused/done）+ 进度 + 参数版本（params_version，
-- 编辑参数 +1，信号行携带版本可归因）。scope_codes 为显式范围固化快照
-- （watchlist/bsp_query 来源创建时解析一次），'all' 范围为 NULL。
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
);

-- 2026-10-11 策略任务逐股结果表（strategy-task-redesign design D1）
-- 显式范围任务逐股落行（匹配/未匹配/失败），全量范围不落（存储量约束）；
-- UNIQUE(task_id, code)：重跑同一只股票 = 覆盖该行（最新一轮运行快照）。
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
);

-- 2026-10-11 策略任务索引（strategy-task-redesign design D1）
-- 任务列表按 strategy_id 过滤 + created_at 排序是主查询模式。
CREATE INDEX IF NOT EXISTS ix_strategy_task_strategy_id ON strategy_task (strategy_id);
CREATE INDEX IF NOT EXISTS ix_strategy_task_status ON strategy_task (status);

-- 2026-10-11 monitor 表 instance_id 列 → task_id（strategy-task-redesign design D6/D7）
-- 依赖第 1.3 节迁移 DO 块先把 strategy 来源的 monitor.instance_id 改指 task_id；
-- 列重命名（保持历史值，不丢数据）。重复执行时列名已是 task_id，DO 块自跳过。
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'monitor'
          AND column_name = 'instance_id'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'monitor'
          AND column_name = 'task_id'
    ) THEN
        -- 先摘旧 FK（指向已废弃的 strategy_instance），重命名后由后续 DO 块补挂新 FK
        IF EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'fk_monitor_instance_id'
              AND conrelid = 'monitor'::regclass
        ) THEN
            ALTER TABLE monitor DROP CONSTRAINT fk_monitor_instance_id;
        END IF;
        ALTER TABLE monitor RENAME COLUMN instance_id TO task_id;
    END IF;
END $$;

-- 2026-10-11 存量实例 → 任务迁移 + 三表 instance_id 键改 task_id（strategy-task-redesign design D7）
-- 单个 DO 块内按序执行（同事务，失败整体回滚不留半迁移状态）：
-- 1) strategy_signal 加 task_id + params_version 列并回填（存量信号 params_version=1）
-- 2) strategy_scan_cursor 键改 task_id（重建表结构 + 数据迁移 + drop 旧表）
-- 3) monitor.strategy 来源行 instance_id 改指 task_id（重命名前）或直接挂 FK（重命名后）
-- 4) strategy_instance 每实例生成一个任务（scope_type='all'、mode='persistent'、status='done'）
-- 5) drop strategy_instance 表与 strategy_signal.instance_id 旧列
-- 幂等性：每个子步骤以 information_schema / 表存在性为门，重复执行全部跳过。
DO $$
DECLARE
    v_map RECORD;
    v_task_id INT;
BEGIN
    -- (1) strategy_signal 补 task_id / params_version 列
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'strategy_signal'
          AND column_name = 'instance_id'
    ) THEN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'strategy_signal'
              AND column_name = 'task_id'
        ) THEN
            ALTER TABLE strategy_signal ADD COLUMN task_id INT;
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'strategy_signal'
              AND column_name = 'params_version'
        ) THEN
            ALTER TABLE strategy_signal ADD COLUMN params_version INT NOT NULL DEFAULT 1;
        END IF;
    END IF;

    -- (2) strategy_scan_cursor 键改 task_id：新表结构（task_id 主键成员）
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = current_schema()
          AND table_name = 'strategy_scan_cursor'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'strategy_scan_cursor'
          AND column_name = 'instance_id'
    ) THEN
        -- 先建新列回填，再删旧列（保留历史水位数据）
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'strategy_scan_cursor'
              AND column_name = 'task_id'
        ) THEN
            ALTER TABLE strategy_scan_cursor ADD COLUMN task_id INT;
        END IF;
    END IF;

    -- (4) 实例 → 任务（在键迁移之前执行：需要旧 instance_id ↔ 新 task_id 映射）
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = current_schema()
          AND table_name = 'strategy_instance'
    ) THEN
        FOR v_map IN
            SELECT i.id AS instance_id, i.strategy_id, i.label, i.params, i.created_at
            FROM strategy_instance i
        LOOP
            -- 幂等：按 label + strategy_id 查重（重复执行不再追加）
            IF NOT EXISTS (
                SELECT 1 FROM strategy_task t
                WHERE t.strategy_id = v_map.strategy_id
                  AND t.label = v_map.label
                  AND t.created_at = v_map.created_at
            ) THEN
                INSERT INTO strategy_task
                    (strategy_id, label, user_group, params, params_version,
                     scope_type, scope_codes, mode, status,
                     progress_scanned, progress_total, created_by, created_at)
                VALUES
                    (v_map.strategy_id, v_map.label, '', v_map.params, 1,
                     'all', NULL, 'persistent', 'done',
                     1, 1, 'migration', v_map.created_at)
                RETURNING id INTO v_task_id;
            ELSE
                SELECT t.id INTO v_task_id
                FROM strategy_task t
                WHERE t.strategy_id = v_map.strategy_id
                  AND t.label = v_map.label
                  AND t.created_at = v_map.created_at
                LIMIT 1;
            END IF;

            -- (1b) 信号行改指 task_id
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'strategy_signal'
                  AND column_name = 'instance_id'
            ) THEN
                UPDATE strategy_signal SET task_id = v_task_id
                WHERE instance_id = v_map.instance_id AND task_id IS NULL;
            END IF;

            -- (2b) 游标行改指 task_id
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = 'strategy_scan_cursor'
            ) AND EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'strategy_scan_cursor'
                  AND column_name = 'instance_id'
            ) THEN
                UPDATE strategy_scan_cursor SET task_id = v_task_id
                WHERE instance_id = v_map.instance_id AND task_id IS NULL;
            END IF;

            -- (3) monitor.strategy 来源行改指 task_id（列名仍为 instance_id 阶段）
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'monitor'
                  AND column_name = 'instance_id'
            ) THEN
                UPDATE monitor SET instance_id = v_task_id
                WHERE source_type = 'strategy' AND instance_id = v_map.instance_id;
            END IF;
        END LOOP;

        -- (5a) 游标旧列摘除 + 主键重建（task_id 替代 instance_id 成为键成员）
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'strategy_scan_cursor'
              AND column_name = 'instance_id'
        ) THEN
            ALTER TABLE strategy_scan_cursor DROP CONSTRAINT IF EXISTS strategy_scan_cursor_pkey;
            ALTER TABLE strategy_scan_cursor DROP COLUMN instance_id;
            UPDATE strategy_scan_cursor SET task_id = 0 WHERE task_id IS NULL;
            ALTER TABLE strategy_scan_cursor ALTER COLUMN task_id SET NOT NULL;
            ALTER TABLE strategy_scan_cursor ADD PRIMARY KEY (task_id, code);
        END IF;

        -- (5b) monitor 列改名（策略来源已指 task_id；与前面重命名 DO 块语义等价，
        -- 本块兜底处理「先跑 1.3 迁移块、monitor 重命名块被跳过」的执行序）
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'monitor'
              AND column_name = 'instance_id'
        ) AND NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'monitor'
              AND column_name = 'task_id'
        ) THEN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_monitor_instance_id'
                  AND conrelid = 'monitor'::regclass
            ) THEN
                ALTER TABLE monitor DROP CONSTRAINT fk_monitor_instance_id;
            END IF;
            ALTER TABLE monitor RENAME COLUMN instance_id TO task_id;
        END IF;

        -- (5c) signal 旧列摘除（FK 级联删除随旧列一并消失；新 task_id 列 FK 后补）
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'strategy_signal'
              AND column_name = 'instance_id'
        ) THEN
            ALTER TABLE strategy_signal DROP COLUMN instance_id;
        END IF;

        -- (5d) drop 旧实例表
        DROP TABLE strategy_instance;
    END IF;
END $$;

-- 2026-10-11 monitor.task_id 挂 FK（strategy-task-redesign design D7）
-- 依赖上面迁移块完成 monitor 列改名；strategy 来源行已指任务 id。
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'monitor'
          AND column_name = 'task_id'
    ) AND NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_monitor_task_id'
          AND conrelid = 'monitor'::regclass
    ) THEN
        -- 删任务时监控行来源置空（软引用语义与原 fk_monitor_instance_id 一致）
        ALTER TABLE monitor
            ADD CONSTRAINT fk_monitor_task_id
            FOREIGN KEY (task_id) REFERENCES strategy_task(id) ON DELETE SET NULL;
    END IF;
END $$;

-- 2026-10-11 strategy_signal.task_id 挂 FK + 唯一键迁移（strategy-task-redesign design D7）
-- 依赖上面迁移块删掉旧 instance_id 列（其上的 UNIQUE(instance_id, code, signal_date)
-- 随列删除自动消失）；此处补 UNIQUE(task_id, code, signal_date)。
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'strategy_signal'::regclass
          AND contype = 'u'
          AND conname = 'uq_strategy_signal_task'
    ) THEN
        -- 迁移后 task_id 可能有 NULL 行（无实例对应的孤儿信号，正常路径不存在；
        -- 兜底清孤儿再挂约束，避免约束失败卡死迁移重跑）
        DELETE FROM strategy_signal WHERE task_id IS NULL;
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'strategy_signal'
              AND column_name = 'task_id'
        ) THEN
            ALTER TABLE strategy_signal ADD COLUMN task_id INT NOT NULL;
        END IF;
        ALTER TABLE strategy_signal ALTER COLUMN task_id SET NOT NULL;
        ALTER TABLE strategy_signal
            ADD CONSTRAINT uq_strategy_signal_task
            UNIQUE (task_id, code, signal_date);
        CREATE INDEX IF NOT EXISTS ix_strategy_signal_task_id
            ON strategy_signal (task_id);
    END IF;
END $$;

-- 2026-10-11 strategy_signal.task_id 挂 FK ON DELETE CASCADE（删除任务级联删信号）
-- spec「删除任务」：信号与逐股结果一并删除。首次执行时清理孤儿信号行
-- （历史测试残留，task_id 指向已删除任务），否则 FK 校验失败卡死重跑。
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'strategy_signal'::regclass
          AND contype = 'f'
          AND conname = 'fk_strategy_signal_task'
    ) THEN
        DELETE FROM strategy_signal s
        WHERE NOT EXISTS (SELECT 1 FROM strategy_task t WHERE t.id = s.task_id);
        ALTER TABLE strategy_signal
            ADD CONSTRAINT fk_strategy_signal_task
            FOREIGN KEY (task_id) REFERENCES strategy_task(id) ON DELETE CASCADE;
    END IF;
END $$;

-- 2026-10-11 strategy_signal 加绩效四列（strategy-signal-outcome design D1）
-- 绩效为跨策略通用语义，走独立列而非 payload：kv 准确率统计要
-- COUNT(*) FILTER + AVG（走列一条 SQL，payload 需全行拉回内存解析 JSONB）；
-- 将来按收益率排序/筛选也是自然诉求。
-- 列约束：ret_* 为 numeric NULL、outcome 为 varchar NULL（取值域
-- 'success'/'failed'/'pending'，无 CHECK 约束——frozen 存量行与口径
-- 演进兼容）；旧行四列均为 NULL，详情显示 '--'。
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'strategy_signal'
          AND column_name = 'ret_7d'
    ) THEN
        ALTER TABLE strategy_signal ADD COLUMN ret_7d DOUBLE PRECISION;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'strategy_signal'
          AND column_name = 'ret_14d'
    ) THEN
        ALTER TABLE strategy_signal ADD COLUMN ret_14d DOUBLE PRECISION;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'strategy_signal'
          AND column_name = 'ret_30d'
    ) THEN
        ALTER TABLE strategy_signal ADD COLUMN ret_30d DOUBLE PRECISION;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'strategy_signal'
          AND column_name = 'outcome'
    ) THEN
        ALTER TABLE strategy_signal ADD COLUMN outcome VARCHAR;
    END IF;
END $$;

-- 回滚说明（strategy-task-redesign design Migration Plan）：
-- 旧 strategy_instance 表已被 drop，代码回退后需从备份恢复或手工重建；
-- monitor.task_id / strategy_signal.task_id 的数据在迁移时已按映射改写，
-- 手工逆迁移 = 按 created_by='migration' 的任务行反查 mapping 不可行（无持久化映射表），
-- 生产环境请先 pg_dump 再执行本文件。
-- 绩效四列回滚：直接 DROP COLUMN（列可 NULL 无约束，不破坏旧行）。
