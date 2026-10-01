-- ============================================================================
-- chan-stock-manage: PostgreSQL init script
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Part 1: chan-web-viewer
-- ============================================================================

CREATE TABLE IF NOT EXISTS chan_stable_prefix (
    id              SERIAL PRIMARY KEY,
    code            VARCHAR NOT NULL,
    kl_type         VARCHAR NOT NULL,
    last_sure_ts    BIGINT  NOT NULL,
    bi_json         JSONB   NOT NULL DEFAULT '[]',
    seg_json        JSONB   NOT NULL DEFAULT '[]',
    zs_json         JSONB   NOT NULL DEFAULT '[]',
    seg_zs_json     JSONB   NOT NULL DEFAULT '[]',
    bsp_json        JSONB   NOT NULL DEFAULT '[]',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_csp_code_kltype UNIQUE (code, kl_type)
);

DROP TRIGGER IF EXISTS trg_csp_updated_at ON chan_stable_prefix;
CREATE TRIGGER trg_csp_updated_at
    BEFORE UPDATE ON chan_stable_prefix
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX IF NOT EXISTS idx_csp_code ON chan_stable_prefix (code);
CREATE INDEX IF NOT EXISTS idx_csp_code_kltype ON chan_stable_prefix (code, kl_type);

CREATE TABLE IF NOT EXISTS chan_user (
    id          SERIAL PRIMARY KEY,
    username    VARCHAR NOT NULL UNIQUE,
    password    VARCHAR NOT NULL,
    nickname    VARCHAR NOT NULL,
    role        VARCHAR NOT NULL DEFAULT 'viewer',
    status      VARCHAR NOT NULL DEFAULT 'active',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DROP TRIGGER IF EXISTS trg_chan_user_updated_at ON chan_user;
CREATE TRIGGER trg_chan_user_updated_at
    BEFORE UPDATE ON chan_user
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE IF NOT EXISTS chan_user_permission (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES chan_user(id) ON DELETE CASCADE,
    code        VARCHAR NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_cup_user_perm UNIQUE (user_id, code)
);

CREATE INDEX IF NOT EXISTS idx_cup_user_id ON chan_user_permission (user_id);
-- ============================================================================
-- Part 2: chan-stock-manage business tables
-- ============================================================================

-- stock: 身份 6 + 用户 7 + 档案 16 + 快照 8 四组合并（stock-metadata-sync）
-- 已删列禁止出现：total_share/float_share、B/H 四列、market、index_members、
-- out_date、status、change_pct、zdf_d5/d10/d20/d60、w52、amplitude、volume_ratio、成交量额列
CREATE TABLE IF NOT EXISTS stock (
    code            VARCHAR PRIMARY KEY,
    name            VARCHAR NOT NULL DEFAULT '',
    name_py         VARCHAR NOT NULL DEFAULT '',
    exchange        VARCHAR NOT NULL DEFAULT '',
    ipo_date        DATE,
    board           VARCHAR NOT NULL DEFAULT '',
    industry_l1     VARCHAR NOT NULL DEFAULT '',
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    kl_types        VARCHAR[] NOT NULL DEFAULT '{}',
    autypes         VARCHAR[] NOT NULL DEFAULT '{}',
    tags            VARCHAR[] NOT NULL DEFAULT '{}',
    notes           TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    full_name       VARCHAR NOT NULL DEFAULT '',
    en_name         VARCHAR NOT NULL DEFAULT '',
    former_names    TEXT NOT NULL DEFAULT '',
    legal_person    VARCHAR NOT NULL DEFAULT '',
    reg_capital     VARCHAR NOT NULL DEFAULT '',
    found_date      DATE,
    website         VARCHAR NOT NULL DEFAULT '',
    email           VARCHAR NOT NULL DEFAULT '',
    phone           VARCHAR NOT NULL DEFAULT '',
    fax             VARCHAR NOT NULL DEFAULT '',
    reg_addr        TEXT NOT NULL DEFAULT '',
    office_addr     TEXT NOT NULL DEFAULT '',
    postal_code     VARCHAR NOT NULL DEFAULT '',
    main_business   TEXT NOT NULL DEFAULT '',
    business_scope  TEXT NOT NULL DEFAULT '',
    intro           TEXT NOT NULL DEFAULT '',
    price           NUMERIC(12,4),
    total_mv        NUMERIC(18,4),
    float_mv        NUMERIC(18,4),
    pe_ttm          NUMERIC(14,4),
    pb              NUMERIC(14,4),
    turnover_rate   NUMERIC(10,4),
    main_net_inflow NUMERIC(18,4),
    snapshot_at     TIMESTAMPTZ
);

-- 存量库补列（幂等，与 WebAPI/stock_store._ensure_tables 保持一致）
ALTER TABLE stock ADD COLUMN IF NOT EXISTS ipo_date DATE;
ALTER TABLE stock ADD COLUMN IF NOT EXISTS board VARCHAR NOT NULL DEFAULT '';
ALTER TABLE stock ADD COLUMN IF NOT EXISTS industry_l1 VARCHAR NOT NULL DEFAULT '';
ALTER TABLE stock ADD COLUMN IF NOT EXISTS full_name VARCHAR NOT NULL DEFAULT '';
ALTER TABLE stock ADD COLUMN IF NOT EXISTS en_name VARCHAR NOT NULL DEFAULT '';
ALTER TABLE stock ADD COLUMN IF NOT EXISTS former_names TEXT NOT NULL DEFAULT '';
ALTER TABLE stock ADD COLUMN IF NOT EXISTS legal_person VARCHAR NOT NULL DEFAULT '';
ALTER TABLE stock ADD COLUMN IF NOT EXISTS reg_capital VARCHAR NOT NULL DEFAULT '';
ALTER TABLE stock ADD COLUMN IF NOT EXISTS found_date DATE;
ALTER TABLE stock ADD COLUMN IF NOT EXISTS website VARCHAR NOT NULL DEFAULT '';
ALTER TABLE stock ADD COLUMN IF NOT EXISTS email VARCHAR NOT NULL DEFAULT '';
ALTER TABLE stock ADD COLUMN IF NOT EXISTS phone VARCHAR NOT NULL DEFAULT '';
ALTER TABLE stock ADD COLUMN IF NOT EXISTS fax VARCHAR NOT NULL DEFAULT '';
ALTER TABLE stock ADD COLUMN IF NOT EXISTS reg_addr TEXT NOT NULL DEFAULT '';
ALTER TABLE stock ADD COLUMN IF NOT EXISTS office_addr TEXT NOT NULL DEFAULT '';
ALTER TABLE stock ADD COLUMN IF NOT EXISTS postal_code VARCHAR NOT NULL DEFAULT '';
ALTER TABLE stock ADD COLUMN IF NOT EXISTS main_business TEXT NOT NULL DEFAULT '';
ALTER TABLE stock ADD COLUMN IF NOT EXISTS business_scope TEXT NOT NULL DEFAULT '';
ALTER TABLE stock ADD COLUMN IF NOT EXISTS intro TEXT NOT NULL DEFAULT '';
ALTER TABLE stock ADD COLUMN IF NOT EXISTS price NUMERIC(12,4);
ALTER TABLE stock ADD COLUMN IF NOT EXISTS total_mv NUMERIC(18,4);
ALTER TABLE stock ADD COLUMN IF NOT EXISTS float_mv NUMERIC(18,4);
ALTER TABLE stock ADD COLUMN IF NOT EXISTS pe_ttm NUMERIC(14,4);
ALTER TABLE stock ADD COLUMN IF NOT EXISTS pb NUMERIC(14,4);
ALTER TABLE stock ADD COLUMN IF NOT EXISTS turnover_rate NUMERIC(10,4);
ALTER TABLE stock ADD COLUMN IF NOT EXISTS main_net_inflow NUMERIC(18,4);
ALTER TABLE stock ADD COLUMN IF NOT EXISTS snapshot_at TIMESTAMPTZ;
ALTER TABLE stock ADD COLUMN IF NOT EXISTS name_py VARCHAR NOT NULL DEFAULT '';

-- updated_at 触发器仅响应用户列变更（enabled/kl_types/autypes/tags/notes）
DROP TRIGGER IF EXISTS trg_stock_updated_at ON stock;
CREATE TRIGGER trg_stock_updated_at BEFORE UPDATE ON stock FOR EACH ROW
WHEN (OLD.enabled IS DISTINCT FROM NEW.enabled
   OR OLD.kl_types IS DISTINCT FROM NEW.kl_types
   OR OLD.autypes IS DISTINCT FROM NEW.autypes
   OR OLD.tags IS DISTINCT FROM NEW.tags
   OR OLD.notes IS DISTINCT FROM NEW.notes)
EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX IF NOT EXISTS idx_stock_exchange ON stock (exchange);
CREATE INDEX IF NOT EXISTS idx_stock_enabled  ON stock (enabled);
CREATE INDEX IF NOT EXISTS idx_stock_name     ON stock (name);

CREATE TABLE IF NOT EXISTS stock_industry (
    code          VARCHAR NOT NULL REFERENCES stock(code) ON DELETE CASCADE,
    industry_name VARCHAR NOT NULL,
    rank          INT NOT NULL DEFAULT 0,
    is_primary    BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT pk_stock_industry PRIMARY KEY (code, industry_name)
);

CREATE INDEX IF NOT EXISTS idx_si_industry ON stock_industry (industry_name);

CREATE TABLE IF NOT EXISTS stock_financial_report (
    code VARCHAR NOT NULL REFERENCES stock(code) ON DELETE CASCADE,
    statement_type VARCHAR NOT NULL,
    report_date DATE NOT NULL,
    report_type VARCHAR NOT NULL DEFAULT '',
    report_name VARCHAR NOT NULL DEFAULT '',
    notice_date DATE,
    data JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (code, statement_type, report_date)
);
CREATE INDEX IF NOT EXISTS idx_sfr_code ON stock_financial_report (code);

CREATE TABLE IF NOT EXISTS stock_holder_num (
    code VARCHAR NOT NULL REFERENCES stock(code) ON DELETE CASCADE,
    stat_date DATE NOT NULL,
    notice_date DATE,
    holder_num BIGINT,
    prev_holder_num BIGINT,
    holder_num_change BIGINT,
    holder_num_change_pct NUMERIC(12,4),
    avg_hold_mv NUMERIC(18,4),
    avg_hold_shares NUMERIC(18,4),
    total_share NUMERIC(18,4),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (code, stat_date)
);
CREATE INDEX IF NOT EXISTS idx_shn_code ON stock_holder_num (code);

CREATE TABLE IF NOT EXISTS sync_watermark (
    code VARCHAR NOT NULL,
    domain VARCHAR NOT NULL,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (code, domain)
);

CREATE TABLE IF NOT EXISTS sync_job (
    id SERIAL PRIMARY KEY,
    domains TEXT[] NOT NULL DEFAULT '{}',
    scope VARCHAR NOT NULL DEFAULT 'market',
    force BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR NOT NULL DEFAULT 'running',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    summary JSONB,
    CONSTRAINT chk_sync_job_status CHECK (status IN ('running','interrupted','done','failed'))
);

CREATE TABLE IF NOT EXISTS chan_structure (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR NOT NULL,
    kl_type     VARCHAR NOT NULL,
    autype      VARCHAR NOT NULL,
    structure   JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_chan_struct_code UNIQUE (code, kl_type, autype)
);

DROP TRIGGER IF EXISTS trg_chan_structure_updated_at ON chan_structure;
CREATE TRIGGER trg_chan_structure_updated_at BEFORE UPDATE ON chan_structure FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX IF NOT EXISTS idx_cs_code ON chan_structure (code);

CREATE TABLE IF NOT EXISTS bsp_index (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR NOT NULL,
    kl_type     VARCHAR NOT NULL,
    autype      VARCHAR NOT NULL,
    bsp_date    DATE NOT NULL,
    bsp_type    VARCHAR NOT NULL,
    is_buy      BOOLEAN NOT NULL,
    price       NUMERIC(12,4) NOT NULL,
    time_key    VARCHAR NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_bsp_dedup UNIQUE (code, kl_type, autype, bsp_date, bsp_type, is_buy, time_key)
);

CREATE INDEX IF NOT EXISTS idx_bsp_code      ON bsp_index (code);
CREATE INDEX IF NOT EXISTS idx_bsp_date      ON bsp_index (bsp_date);
CREATE INDEX IF NOT EXISTS idx_bsp_type      ON bsp_index (kl_type, bsp_type, is_buy);
CREATE INDEX IF NOT EXISTS idx_bsp_date_type ON bsp_index (bsp_date, kl_type, bsp_type, is_buy);

CREATE TABLE IF NOT EXISTS chan_snapshot (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR NOT NULL,
    kl_type     VARCHAR NOT NULL,
    autype      VARCHAR NOT NULL,
    pickle      BYTEA NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_snapshot_code UNIQUE (code, kl_type, autype)
);

DROP TRIGGER IF EXISTS trg_chan_snapshot_updated_at ON chan_snapshot;
CREATE TRIGGER trg_chan_snapshot_updated_at BEFORE UPDATE ON chan_snapshot FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TABLE IF NOT EXISTS watchlist_folder (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR NOT NULL DEFAULT '默认文件夹',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sort_order  INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS watchlist_item (
    id          SERIAL PRIMARY KEY,
    folder_id   INTEGER NOT NULL REFERENCES watchlist_folder(id) ON DELETE CASCADE,
    code        VARCHAR NOT NULL,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sort_order  INT NOT NULL DEFAULT 0,
    CONSTRAINT uq_wl_folder_code UNIQUE (folder_id, code)
);

CREATE INDEX IF NOT EXISTS idx_wl_folder_id ON watchlist_item (folder_id);
CREATE INDEX IF NOT EXISTS idx_wl_code      ON watchlist_item (code);

-- 存量库补列（幂等，与 WebAPI/watchlist_store._ensure_tables 保持一致）
ALTER TABLE watchlist_folder ADD COLUMN IF NOT EXISTS sort_order INT NOT NULL DEFAULT 0;
ALTER TABLE watchlist_item   ADD COLUMN IF NOT EXISTS sort_order INT NOT NULL DEFAULT 0;

-- 一次性回填：sort_order 1 基且永不为 0（此后 WHERE sort_order = 0 永不命中，脚本可重复执行）
-- folder 按 id 回填；item 在部分存量库中无 id 列（由 watchlist_store 惰性建表而来），
-- 按 added_at 序编号（与旧行为 ORDER BY added_at 一致），语义同 SET sort_order = id
UPDATE watchlist_folder SET sort_order = id WHERE sort_order = 0;

UPDATE watchlist_item wi
SET sort_order = s.rn
FROM (
    SELECT folder_id, code,
           ROW_NUMBER() OVER (PARTITION BY folder_id ORDER BY added_at, code) AS rn
    FROM watchlist_item
    WHERE sort_order = 0
) s
WHERE wi.folder_id = s.folder_id AND wi.code = s.code AND wi.sort_order = 0;
CREATE TABLE IF NOT EXISTS monitor (
    id                  SERIAL PRIMARY KEY,
    code                VARCHAR NOT NULL,
    kl_type             VARCHAR NOT NULL,
    monitor_start_time  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    entry_price         NUMERIC(12,4),
    status              VARCHAR NOT NULL DEFAULT 'monitoring',
    sold_price          NUMERIC(12,4),
    sold_at             TIMESTAMPTZ,
    pnl_pct             NUMERIC(8,4),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_monitor_status CHECK (status IN ('monitoring', 'completed'))
);

DROP TRIGGER IF EXISTS trg_monitor_updated_at ON monitor;
CREATE TRIGGER trg_monitor_updated_at BEFORE UPDATE ON monitor FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX IF NOT EXISTS idx_monitor_code   ON monitor (code);
CREATE INDEX IF NOT EXISTS idx_monitor_status ON monitor (status);

-- 列名与 monitor_store.save_attribution/get_attribution 代码契约对齐（reason_type/evidence）；
-- 原 failure_reason/input_summary 为陈旧 DDL，全库零引用。
CREATE TABLE IF NOT EXISTS monitor_attribution (
    id              SERIAL PRIMARY KEY,
    monitor_id      INTEGER NOT NULL REFERENCES monitor(id) ON DELETE CASCADE,
    reason_type     VARCHAR NOT NULL,
    evidence        TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_ma_monitor_id UNIQUE (monitor_id)
);

CREATE TABLE IF NOT EXISTS screener (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR NOT NULL DEFAULT '',
    conditions  JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DROP TRIGGER IF EXISTS trg_screener_updated_at ON screener;
CREATE TRIGGER trg_screener_updated_at BEFORE UPDATE ON screener FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TABLE IF NOT EXISTS alert (
    id               SERIAL PRIMARY KEY,
    user_id          INTEGER NOT NULL,
    type             VARCHAR NOT NULL DEFAULT 'price',
    target_code      VARCHAR NOT NULL DEFAULT '',
    threshold_params JSONB NOT NULL DEFAULT '{}',
    enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_alert_type CHECK (type IN ('price', 'bsp', 'monitor_sell'))
);

DROP TRIGGER IF EXISTS trg_alert_updated_at ON alert;
CREATE TRIGGER trg_alert_updated_at BEFORE UPDATE ON alert FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX IF NOT EXISTS idx_alert_user_id ON alert (user_id);
CREATE INDEX IF NOT EXISTS idx_alert_enabled ON alert (enabled);

CREATE TABLE IF NOT EXISTS alert_notification (
    id           SERIAL PRIMARY KEY,
    alert_id     INTEGER NOT NULL REFERENCES alert(id) ON DELETE CASCADE,
    user_id      INTEGER NOT NULL,
    type         VARCHAR NOT NULL DEFAULT '',
    content      TEXT NOT NULL DEFAULT '',
    related_code VARCHAR NOT NULL DEFAULT '',
    is_read      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_an_user_id    ON alert_notification (user_id);
CREATE INDEX IF NOT EXISTS idx_an_is_read    ON alert_notification (user_id, is_read);
CREATE INDEX IF NOT EXISTS idx_an_created_at ON alert_notification (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS recompute_cursor (
    code                VARCHAR,
    kl_type             VARCHAR,
    autype              VARCHAR,
    last_processed_time VARCHAR,
    PRIMARY KEY (code, kl_type, autype)
);
-- ============================================================================
-- Part 3: D16 RBAC tables
-- ============================================================================

CREATE TABLE IF NOT EXISTS role (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR NOT NULL DEFAULT '',
    code        VARCHAR NOT NULL,
    description VARCHAR NOT NULL DEFAULT '',
    is_admin    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_role_code UNIQUE (code)
);

-- 存量库补列（幂等）：role.description（前端 RoleDialog 契约，system-page-change design D6）
ALTER TABLE role ADD COLUMN IF NOT EXISTS description VARCHAR NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS permission (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR NOT NULL,
    name        VARCHAR NOT NULL DEFAULT '',
    type        VARCHAR NOT NULL DEFAULT 'menu',
    CONSTRAINT uq_perm_code UNIQUE (code),
    CONSTRAINT chk_perm_type CHECK (type IN ('menu', 'button'))
);

CREATE TABLE IF NOT EXISTS role_permission (
    id              SERIAL PRIMARY KEY,
    role_id         INTEGER NOT NULL REFERENCES role(id) ON DELETE CASCADE,
    permission_id   INTEGER NOT NULL REFERENCES permission(id) ON DELETE CASCADE,
    CONSTRAINT uq_rp_role_perm UNIQUE (role_id, permission_id)
);

CREATE INDEX IF NOT EXISTS idx_rp_role_id       ON role_permission (role_id);
CREATE INDEX IF NOT EXISTS idx_rp_permission_id ON role_permission (permission_id);

CREATE TABLE IF NOT EXISTS app_user (
    id              SERIAL PRIMARY KEY,
    username        VARCHAR NOT NULL,
    password_hash   VARCHAR NOT NULL,
    display_name    VARCHAR NOT NULL DEFAULT '',
    role_id         INTEGER NOT NULL REFERENCES role(id),
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_app_user_username UNIQUE (username)
);

DROP TRIGGER IF EXISTS trg_app_user_updated_at ON app_user;
CREATE TRIGGER trg_app_user_updated_at BEFORE UPDATE ON app_user FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX IF NOT EXISTS idx_au_role_id ON app_user (role_id);
-- ============================================================================
-- Part 4: Seed data
-- ============================================================================

-- 4.1 chan_user seeds (dev plaintext)
INSERT INTO chan_user (username, password, nickname, role, status) VALUES
    ('admin',  'admin123',  '管理员', 'admin',  'active'),
    ('trader', 'trader123', '交易员', 'trader', 'active'),
    ('viewer', 'viewer123', '观察者', 'viewer', 'active')
ON CONFLICT (username) DO NOTHING;

-- admin: all permissions
INSERT INTO chan_user_permission (user_id, code)
SELECT u.id, p.code FROM chan_user u CROSS JOIN (
    VALUES ('menu:kline'),('menu:watchlist'),('menu:bsp'),('menu:monitor'),
        ('menu:performance'),('menu:screener'),('menu:alerts'),('menu:system'),
        ('manage')) AS p(code)
WHERE u.username = 'admin'
ON CONFLICT (user_id, code) DO NOTHING;

-- trader: all except system/manage
INSERT INTO chan_user_permission (user_id, code)
SELECT u.id, p.code FROM chan_user u CROSS JOIN (
    VALUES ('menu:kline'),('menu:watchlist'),('menu:bsp'),('menu:monitor'),
        ('menu:performance'),('menu:screener'),('menu:alerts')) AS p(code)
WHERE u.username = 'trader'
ON CONFLICT (user_id, code) DO NOTHING;

-- viewer: kline + watchlist only
INSERT INTO chan_user_permission (user_id, code)
SELECT u.id, p.code FROM chan_user u CROSS JOIN (
    VALUES ('menu:kline'),('menu:watchlist')) AS p(code)
WHERE u.username = 'viewer'
ON CONFLICT (user_id, code) DO NOTHING;
-- 4.2 permission seeds (8 menu + 1 button)；menu:kline 名称对齐 Front/src/mock/data/system.ts
INSERT INTO permission (code, name, type) VALUES
    ('menu:kline',       'K线分析',    'menu'),
    ('menu:watchlist',   '我的自选',    'menu'),
    ('menu:bsp',         '历史买卖点',  'menu'),
    ('menu:monitor',     '股票监控',    'menu'),
    ('menu:performance', '买卖点绩效',  'menu'),
    ('menu:screener',    '条件选股',    'menu'),
    ('menu:alerts',      '预警提醒',    'menu'),
    ('menu:system',      '权限管理',    'menu'),
    ('manage',           '管理操作',    'button')
ON CONFLICT (code) DO NOTHING;

-- 4.3 role seeds（description 对齐 mock，system-page-change design D6）
INSERT INTO role (name, code, description, is_admin) VALUES
    ('管理员', 'admin',  '拥有所有权限', TRUE),
    ('交易员', 'trader', '可访问业务页面，无系统管理权限', FALSE),
    ('观察者', 'viewer', '仅可查看K线和自选', FALSE)
ON CONFLICT (code) DO NOTHING;

-- 存量行补 description（幂等：只填空、不覆盖已有描述）
UPDATE role SET description = '拥有所有权限'                   WHERE code = 'admin'  AND description = '';
UPDATE role SET description = '可访问业务页面，无系统管理权限'   WHERE code = 'trader' AND description = '';
UPDATE role SET description = '仅可查看K线和自选'               WHERE code = 'viewer' AND description = '';

-- 4.4 role_permission: admin gets all（CROSS JOIN 重跑自然补齐新增权限）
INSERT INTO role_permission (role_id, permission_id)
SELECT r.id, p.id FROM role r CROSS JOIN permission p
WHERE r.code = 'admin'
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- trader: 业务 menu 全部 7 项（含 menu:kline，不含 menu:system）
INSERT INTO role_permission (role_id, permission_id)
SELECT r.id, p.id FROM role r CROSS JOIN permission p
WHERE r.code = 'trader' AND p.type = 'menu' AND p.code <> 'menu:system'
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- viewer: menu:kline + menu:watchlist
INSERT INTO role_permission (role_id, permission_id)
SELECT r.id, p.id FROM role r CROSS JOIN permission p
WHERE r.code = 'viewer' AND p.code IN ('menu:kline', 'menu:watchlist')
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- 存量校正（幂等）：清除旧种子残留授权（system-page-change design D6「存量校正」）。
-- 旧 trader 种子按 p.type='menu' 全量授予（含 menu:system），旧 viewer 种子曾授予 menu:bsp，
-- 均与目标授权集不符。注意：本 DELETE 在每次重跑时清理这两处，目标集之外的同类授权勿持久依赖。
DELETE FROM role_permission rp
USING role r, permission p
WHERE rp.role_id = r.id AND rp.permission_id = p.id
  AND r.code = 'trader' AND p.code = 'menu:system';

DELETE FROM role_permission rp
USING role r, permission p
WHERE rp.role_id = r.id AND rp.permission_id = p.id
  AND r.code = 'viewer' AND p.code = 'menu:bsp';

-- 4.5 app_user seeds (bcrypt hashes)
INSERT INTO app_user (username, password_hash, display_name, role_id, enabled)
SELECT 'admin', '$2b$12$Gruc49mpn/ASBbvMRPfVk.nAfHPmZ2XnjyZnch1.ov9QkxyGgEv2i', '管理员',
       (SELECT id FROM role WHERE code = 'admin'), TRUE
WHERE NOT EXISTS (SELECT 1 FROM app_user WHERE username = 'admin');

INSERT INTO app_user (username, password_hash, display_name, role_id, enabled)
SELECT 'trader', '$2b$12$o4BNm4bcwQQZTOAWhTvNquD8ph2odYb4xq7kW.TJL/3nbfXwu.dpi', '交易员',
       (SELECT id FROM role WHERE code = 'trader'), TRUE
WHERE NOT EXISTS (SELECT 1 FROM app_user WHERE username = 'trader');

INSERT INTO app_user (username, password_hash, display_name, role_id, enabled)
SELECT 'viewer', '$2b$12$TDnvTtBch4pMkyNnghMg2uTi7GGz6CQ6NXqRg1R.LPEMPjMig9J.O', '观察者',
       (SELECT id FROM role WHERE code = 'viewer'), TRUE
WHERE NOT EXISTS (SELECT 1 FROM app_user WHERE username = 'viewer');
-- ============================================================================
-- Part 5: kline-page-change QA / LLM (design D4 / D8.1)
-- ============================================================================

CREATE TABLE IF NOT EXISTS qa_record (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES chan_user(id),
    question    TEXT NOT NULL,
    answer      TEXT NOT NULL,
    starred     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qa_record_user_created ON qa_record (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS user_setting (
    user_id     INTEGER NOT NULL REFERENCES chan_user(id),
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);

CREATE TABLE IF NOT EXISTS llm_provider (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    base_url    TEXT NOT NULL,
    api_key     TEXT NOT NULL,
    model       TEXT NOT NULL,
    active      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
