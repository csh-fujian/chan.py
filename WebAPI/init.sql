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

CREATE TABLE IF NOT EXISTS stock (
    code        VARCHAR PRIMARY KEY,
    name        VARCHAR NOT NULL DEFAULT '',
    exchange    VARCHAR NOT NULL DEFAULT '',
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    kl_types    VARCHAR[] NOT NULL DEFAULT '{}',
    autypes     VARCHAR[] NOT NULL DEFAULT '{}',
    tags        VARCHAR[] NOT NULL DEFAULT '{}',
    notes       TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DROP TRIGGER IF EXISTS trg_stock_updated_at ON stock;
CREATE TRIGGER trg_stock_updated_at BEFORE UPDATE ON stock FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

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
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS watchlist_item (
    id          SERIAL PRIMARY KEY,
    folder_id   INTEGER NOT NULL REFERENCES watchlist_folder(id) ON DELETE CASCADE,
    code        VARCHAR NOT NULL,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_wl_folder_code UNIQUE (folder_id, code)
);

CREATE INDEX IF NOT EXISTS idx_wl_folder_id ON watchlist_item (folder_id);
CREATE INDEX IF NOT EXISTS idx_wl_code      ON watchlist_item (code);
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

CREATE TABLE IF NOT EXISTS monitor_attribution (
    id              SERIAL PRIMARY KEY,
    monitor_id      INTEGER NOT NULL REFERENCES monitor(id) ON DELETE CASCADE,
    failure_reason  VARCHAR NOT NULL DEFAULT '',
    evidence        TEXT NOT NULL DEFAULT '',
    input_summary   TEXT NOT NULL DEFAULT '',
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
    is_admin    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_role_code UNIQUE (code)
);

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
-- 4.2 permission seeds (7 menu + 1 button)
INSERT INTO permission (code, name, type) VALUES
    ('menu:watchlist',   '我的自选',    'menu'),
    ('menu:bsp',         '历史买卖点',  'menu'),
    ('menu:monitor',     '股票监控',    'menu'),
    ('menu:performance', '买卖点绩效',  'menu'),
    ('menu:screener',    '条件选股',    'menu'),
    ('menu:alerts',      '预警提醒',    'menu'),
    ('menu:system',      '权限管理',    'menu'),
    ('manage',           '管理操作',    'button')
ON CONFLICT (code) DO NOTHING;

-- 4.3 role seeds
INSERT INTO role (name, code, is_admin) VALUES
    ('管理员', 'admin',  TRUE),
    ('交易员', 'trader', FALSE),
    ('观察者', 'viewer', FALSE)
ON CONFLICT (code) DO NOTHING;
-- 4.4 role_permission: admin gets all
INSERT INTO role_permission (role_id, permission_id)
SELECT r.id, p.id FROM role r CROSS JOIN permission p
WHERE r.code = 'admin'
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- trader: all menu permissions
INSERT INTO role_permission (role_id, permission_id)
SELECT r.id, p.id FROM role r CROSS JOIN permission p
WHERE r.code = 'trader' AND p.type = 'menu'
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- viewer: watchlist + bsp only
INSERT INTO role_permission (role_id, permission_id)
SELECT r.id, p.id FROM role r CROSS JOIN permission p
WHERE r.code = 'viewer' AND p.code IN ('menu:watchlist', 'menu:bsp')
ON CONFLICT (role_id, permission_id) DO NOTHING;

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