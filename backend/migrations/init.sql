-- PostgreSQL初始化脚本

-- 创建扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- stocks表 - 股票基础信息
CREATE TABLE IF NOT EXISTS stocks (
    ts_code VARCHAR(10) PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL UNIQUE,
    name VARCHAR(50) NOT NULL,
    industry VARCHAR(50),
    market VARCHAR(20),
    list_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_stocks_industry ON stocks(industry);
CREATE INDEX IF NOT EXISTS idx_stocks_market ON stocks(market);

-- daily_data表 - 日线数据
CREATE TABLE IF NOT EXISTS daily_data (
    id SERIAL PRIMARY KEY,
    ts_code VARCHAR(10) NOT NULL,
    trade_date DATE NOT NULL,
    open DECIMAL(10, 2),
    high DECIMAL(10, 2),
    low DECIMAL(10, 2),
    close DECIMAL(10, 2),
    vol DECIMAL(20, 2),
    amount DECIMAL(20, 2),
    pct_chg DECIMAL(10, 2),
    UNIQUE(ts_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_ts_code ON daily_data(ts_code);
CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_data(trade_date);
CREATE INDEX IF NOT EXISTS idx_daily_ts_date ON daily_data(ts_code, trade_date);

-- signals表 - 信号记录
CREATE TABLE IF NOT EXISTS signals (
    id SERIAL PRIMARY KEY,
    ts_code VARCHAR(10) NOT NULL,
    signal_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    signal_type VARCHAR(20) NOT NULL,
    confidence DECIMAL(5, 2),
    entry_price DECIMAL(10, 2),
    stop_loss DECIMAL(10, 2),
    take_profit DECIMAL(10, 2),
    indicators JSONB,
    reason TEXT,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_signals_ts_code ON signals(ts_code);
CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(signal_date);
CREATE INDEX IF NOT EXISTS idx_signals_type ON signals(signal_type);

-- holdings表 - 持仓记录
CREATE TABLE IF NOT EXISTS holdings (
    id SERIAL PRIMARY KEY,
    ts_code VARCHAR(10) NOT NULL,
    buy_date DATE,
    buy_price DECIMAL(10, 2),
    shares INTEGER,
    stop_loss DECIMAL(10, 2),
    take_profit DECIMAL(10, 2),
    status VARCHAR(20) DEFAULT 'holding',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_holdings_ts_code ON holdings(ts_code);
CREATE INDEX IF NOT EXISTS idx_holdings_status ON holdings(status);

-- strategy_results表 - 策略回测结果
CREATE TABLE IF NOT EXISTS strategy_results (
    id SERIAL PRIMARY KEY,
    strategy_name VARCHAR(100) NOT NULL,
    strategy_params JSONB,
    test_start_date DATE,
    test_end_date DATE,
    total_return DECIMAL(10, 4),
    annual_return DECIMAL(10, 4),
    sharpe_ratio DECIMAL(10, 4),
    max_drawdown DECIMAL(10, 4),
    win_rate DECIMAL(5, 2),
    total_trades INTEGER,
    details JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_strategy_name ON strategy_results(strategy_name);

INSERT INTO stocks (ts_code, symbol, name, industry, market, list_date) VALUES 
('000001.SZ', '000001', '平安银行', '银行', 'SZSE', '1991-04-03'),
('600519.SH', '600519', '贵州茅台', '酒类', 'SSE', '2001-08-27'),
('000858.SZ', '000858', '五粮液', '酒类', 'SZSE', '1998-04-27'),
('601318.SH', '601318', '中国平安', '保险', 'SSE', '2007-03-01'),
('000651.SZ', '000651', '格力电器', '家电', 'SZSE', '1996-11-18'),
('600036.SH', '600036', '招商银行', '银行', 'SSE', '2002-04-09'),
('002594.SZ', '002594', '比亚迪', '汽车', 'SZSE', '2011-06-30'),
('300750.SZ', '300750', '宁德时代', '电池', 'SZSE', '2018-06-11'),
('601899.SH', '601899', '紫金矿业', '有色', 'SSE', '2008-04-25'),
('600030.SH', '600030', '中信证券', '券商', 'SSE', '2003-01-06')
ON CONFLICT (ts_code) DO NOTHING;
