-- A股分析系统V2数据库迁移
-- 日期: 2026-05-24

-- 1. 创建策略输出表
CREATE TABLE IF NOT EXISTS strategy_outputs (
    id SERIAL PRIMARY KEY,
    ts_code VARCHAR(10) NOT NULL,
    strategy_name VARCHAR(100) NOT NULL,
    signal VARCHAR(20) NOT NULL,
    confidence DECIMAL(5,2),
    entry_zone_low DECIMAL(10,2),
    entry_zone_high DECIMAL(10,2),
    risk_line DECIMAL(10,2),
    target_zone_low DECIMAL(10,2),
    target_zone_high DECIMAL(10,2),
    position_suggestion VARCHAR(50),
    holding_period VARCHAR(50),
    evidence JSONB,
    risk_notes JSONB,
    signal_date DATE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_strategy_output_ts_code ON strategy_outputs(ts_code);
CREATE INDEX idx_strategy_output_date ON strategy_outputs(signal_date);

-- 2. 创建策略模板V2表
CREATE TABLE IF NOT EXISTS strategy_templates_v2 (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    template_type VARCHAR(20) NOT NULL,
    code_template TEXT NOT NULL,
    parameters JSONB,
    output_schema JSONB,
    is_system BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    author VARCHAR(50),
    version VARCHAR(20) DEFAULT '1.0.0',
    usage_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_strategy_template_type ON strategy_templates_v2(template_type);
CREATE INDEX idx_strategy_template_active ON strategy_templates_v2(is_active);

-- 3. 创建回测运行表
CREATE TABLE IF NOT EXISTS backtest_runs (
    id SERIAL PRIMARY KEY,
    strategy_name VARCHAR(100) NOT NULL,
    ts_code VARCHAR(10),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    initial_capital DECIMAL(20,2) DEFAULT 100000.00,
    config JSONB,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX idx_backtest_runs_status ON backtest_runs(status);

-- 4. 创建回测结果表
CREATE TABLE IF NOT EXISTS backtest_results (
    id SERIAL PRIMARY KEY,
    backtest_id INTEGER REFERENCES backtest_runs(id) ON DELETE CASCADE,
    metrics JSONB,
    portfolio_values JSONB,
    trades JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_backtest_results_backtest_id ON backtest_results(backtest_id);

-- 5. 创建指标IDE会话表
CREATE TABLE IF NOT EXISTS indicator_sessions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(50) UNIQUE,
    code TEXT,
    params JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 6. 创建报告表
CREATE TABLE IF NOT EXISTS reports (
    id SERIAL PRIMARY KEY,
    report_type VARCHAR(50) NOT NULL,
    title VARCHAR(200) NOT NULL,
    content_json JSONB,
    content_md TEXT,
    content_html TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_reports_type ON reports(report_type);

-- 回滚脚本
-- DROP TABLE IF EXISTS reports;
-- DROP TABLE IF EXISTS indicator_sessions;
-- DROP TABLE IF EXISTS backtest_results;
-- DROP TABLE IF EXISTS backtest_runs;
-- DROP TABLE IF EXISTS strategy_templates_v2;
-- DROP TABLE IF EXISTS strategy_outputs;
