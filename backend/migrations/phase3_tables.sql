-- PostgreSQL初始化脚本（阶段三扩展）
-- 执行日期：2026-05-20

-- ====================
-- 技术指标表
-- ====================
CREATE TABLE IF NOT EXISTS technical_indicators (
    id SERIAL PRIMARY KEY,
    ts_code VARCHAR(10) NOT NULL,
    trade_date DATE NOT NULL,
    ma5 DECIMAL(10,4),
    ma10 DECIMAL(10,4),
    ma20 DECIMAL(10,4),
    macd_dif DECIMAL(10,4),
    macd_dea DECIMAL(10,4),
    macd_hist DECIMAL(10,4),
    rsi14 DECIMAL(5,2),
    kdj_k DECIMAL(5,2),
    kdj_d DECIMAL(5,2),
    kdj_j DECIMAL(5,2),
    boll_upper DECIMAL(10,4),
    boll_mid DECIMAL(10,4),
    boll_lower DECIMAL(10,4),
    vol_ma5 DECIMAL(20,4),
    vol_ma10 DECIMAL(20,4),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ts_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_indicators_ts_code ON technical_indicators(ts_code);
CREATE INDEX IF NOT EXISTS idx_indicators_trade_date ON technical_indicators(trade_date);

-- ====================
-- 自选股表
-- ====================
CREATE TABLE IF NOT EXISTS watchlist (
    id SERIAL PRIMARY KEY,
    ts_code VARCHAR(10) NOT NULL,
    user_id INTEGER DEFAULT 1,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, ts_code)
);

CREATE INDEX IF NOT EXISTS idx_watchlist_user_id ON watchlist(user_id);

-- ====================
-- 用户记忆表
-- ====================
CREATE TABLE IF NOT EXISTS user_memory (
    id SERIAL PRIMARY KEY,
    user_id INTEGER DEFAULT 1,
    memory_type VARCHAR(50),
    memory_key VARCHAR(100),
    memory_value TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, memory_type, memory_key)
);

CREATE INDEX IF NOT EXISTS idx_memory_user_type ON user_memory(user_id, memory_type);

-- ====================
-- 投资组合表
-- ====================
CREATE TABLE IF NOT EXISTS portfolio (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    user_id INTEGER DEFAULT 1,
    initial_capital DECIMAL(20,4) DEFAULT 1000000.00,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ====================
-- 组合持仓表
-- ====================
CREATE TABLE IF NOT EXISTS portfolio_holdings (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER REFERENCES portfolio(id),
    ts_code VARCHAR(10) NOT NULL,
    quantity INTEGER DEFAULT 0,
    avg_cost DECIMAL(10,4),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(portfolio_id, ts_code)
);

CREATE INDEX IF NOT EXISTS idx_holdings_portfolio_id ON portfolio_holdings(portfolio_id);

-- ====================
-- 模拟交易表
-- ====================
CREATE TABLE IF NOT EXISTS paper_trades (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER REFERENCES portfolio(id),
    ts_code VARCHAR(10) NOT NULL,
    trade_type VARCHAR(10),
    price DECIMAL(10,4),
    quantity INTEGER,
    amount DECIMAL(20,4),
    reason TEXT,
    trade_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_trades_portfolio_id ON paper_trades(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_trades_date ON paper_trades(trade_date DESC);

-- ====================
-- 通知规则表
-- ====================
CREATE TABLE IF NOT EXISTS notification_rules (
    id SERIAL PRIMARY KEY,
    user_id INTEGER DEFAULT 1,
    rule_type VARCHAR(50),
    ts_code VARCHAR(10),
    threshold DECIMAL(10,4),
    direction VARCHAR(10),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ====================
-- 通知历史表
-- ====================
CREATE TABLE IF NOT EXISTS notification_history (
    id SERIAL PRIMARY KEY,
    user_id INTEGER DEFAULT 1,
    notification_type VARCHAR(50),
    title VARCHAR(200),
    content TEXT,
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_notification_user_read ON notification_history(user_id, is_read);