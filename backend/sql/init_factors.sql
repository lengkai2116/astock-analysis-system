-- =============================================
-- 因子库数据库初始化SQL
-- 用于持久化因子库和组合配置
-- 文件路径：backend/sql/init_factors.sql
-- =============================================

-- 因子库表
CREATE TABLE IF NOT EXISTS factor_library (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(50) NOT NULL,
    name_cn VARCHAR(100),
    category VARCHAR(30) NOT NULL,
    subcategory VARCHAR(50),
    description TEXT,
    formula TEXT,
    params TEXT DEFAULT '[]',
    source VARCHAR(50) NOT NULL,
    source_detail VARCHAR(100),
    required_columns TEXT DEFAULT '[]',
    examples TEXT,
    is_enabled BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, source)
);

-- 用户因子组合表
CREATE TABLE IF NOT EXISTS factor_combinations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    factors TEXT NOT NULL,
    is_default BOOLEAN DEFAULT 0,
    is_favorite BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 因子缓存表
CREATE TABLE IF NOT EXISTS factor_cache (
    ts_code VARCHAR(20),
    trade_date DATE,
    factor_name VARCHAR(50),
    value DECIMAL,
    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ts_code, trade_date, factor_name)
);

-- 自选股表
CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_code VARCHAR(20) NOT NULL,
    name VARCHAR(100),
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ts_code)
);

-- 策略结果表
CREATE TABLE IF NOT EXISTS strategy_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_type VARCHAR(50),
    ts_code VARCHAR(20),
    trade_date DATE,
    result TEXT,
    score DECIMAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_factor_category ON factor_library(category);
CREATE INDEX IF NOT EXISTS idx_factor_source ON factor_library(source);
CREATE INDEX IF NOT EXISTS idx_factor_cache_date ON factor_cache(trade_date);
CREATE INDEX IF NOT EXISTS idx_factor_cache_code ON factor_cache(ts_code);
CREATE INDEX IF NOT EXISTS idx_factor_cache_name ON factor_cache(factor_name);
CREATE INDEX IF NOT EXISTS idx_combination_default ON factor_combinations(is_default);
CREATE INDEX IF NOT EXISTS idx_watchlist_order ON watchlist(sort_order);

-- 插入默认因子组合
INSERT INTO factor_combinations (name, description, factors, is_default) VALUES
('经典趋势策略', '基于MA、MACD、KDJ的趋势跟踪组合', '[{"name":"MA","params":{"period":20},"weight":0.3},{"name":"MACD_DIF","params":{},"weight":0.35},{"name":"KDJ_K","params":{},"weight":0.35}]', 1);

INSERT INTO factor_combinations (name, description, factors, is_default) VALUES
('动量策略', 'ROC+RSI+MOM动量组合', '[{"name":"ROC","params":{"period":12},"weight":0.35},{"name":"RSI","params":{"period":14},"weight":0.35},{"name":"MOM","params":{"period":10},"weight":0.3}]', 0);

INSERT INTO factor_combinations (name, description, factors, is_default) VALUES
('波动率策略', 'ATR+BOLL+VOL组合', '[{"name":"ATR","params":{"period":14},"weight":0.3},{"name":"BOLL_UPPER","params":{"period":20,"std_dev":2.0},"weight":0.35},{"name":"VOL_MA","params":{"period":5},"weight":0.35}]', 0);

INSERT INTO factor_combinations (name, description, factors, is_default) VALUES
('反转策略', 'BIAS+WILLR超买超卖', '[{"name":"BIAS","params":{"period":12},"weight":0.5},{"name":"WILLR","params":{"period":14},"weight":0.5}]', 0);

INSERT INTO factor_combinations (name, description, factors, is_default) VALUES
('成交量策略', 'VR+OBV+VOL量价配合', '[{"name":"VR","params":{"period":26},"weight":0.35},{"name":"OBV","params":{},"weight":0.35},{"name":"VOL_RATIO","params":{"period":5},"weight":0.3}]', 0);
