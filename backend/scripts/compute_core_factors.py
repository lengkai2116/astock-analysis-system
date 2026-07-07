"""
Phase 3: 因子预计算 — 核心品类 × 活跃股票

只计算最常用的技术指标因子（均线/RSI/MACD/KDJ/布林带等），
目标股票取近半年有交易的 1000 只活跃股。
"""
import os, sys, time
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy']:
    os.environ.pop(k, None)
os.environ['DATABASE_URL'] = 'sqlite:///test.db'
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from flask import Flask
from app import create_app
app = create_app()
with app.app_context():
    from app.data.enhanced_cache_manager import get_ecm_instance
    from app.data.factor_precompute import FactorPrecomputeManager
    from app.factors import get_factor_registry
    import pandas as pd

    ecm = get_ecm_instance()
    con = ecm.conn
    fpm = FactorPrecomputeManager(cache_manager=ecm)
    fpm._ensure_cache_table()
    reg = get_factor_registry()

    # 核心因子清单（均线/RSI/MACD/KDJ/布林带/量价 — 每个品类取前5常用）
    CORE_FACTORS = [
        'MA_5', 'MA_10', 'MA_20', 'MA_60', 'MA_120',
        'RSI_6', 'RSI_12', 'RSI_24',
        'MACD_DIF', 'MACD_DEA', 'MACD_MACD',
        'KDJ_K', 'KDJ_D', 'KDJ_J',
        'BOLL_UPPER', 'BOLL_MID', 'BOLL_LOWER',
        'VOLATILITY_10', 'VOLATILITY_20', 'VOLATILITY_60',
        'VOLUME_MA_5', 'VOLUME_MA_10', 'VOLUME_MA_20',
        'TURNOVER_MA_5', 'TURNOVER_MA_10',
        'AMOUNT_MA_5', 'AMOUNT_MA_10', 'AMOUNT_MA_20',
        'VWAP', 'OBV',
    ]

    # 活跃股票：最近1日成交额 Top 1000
    stocks = [r[0] for r in con.execute("""
        SELECT ts_code FROM daily_cache
        WHERE trade_date = (SELECT MAX(trade_date) FROM daily_cache)
        ORDER BY amount DESC NULLS LAST LIMIT 1000
    """).fetchall()]
    print(f'目标: {len(CORE_FACTORS)} 因子 × {len(stocks)} 股票 = {len(CORE_FACTORS)*len(stocks)} 计算')

    p1 = time.time()
    factor_configs = [{'name': f} for f in CORE_FACTORS]

    done_stocks = 0
    total_success = 0
    for i, code in enumerate(stocks):
        df = pd.read_sql(
            "SELECT * FROM daily_cache WHERE ts_code = ? ORDER BY trade_date",
            con, params=[code]
        )
        if df.empty or len(df) < 60:
            continue
        results = fpm.precompute_multiple_factors(code, df, factor_configs)
        n_ok = sum(1 for v in results.values() if v)
        total_success += n_ok
        done_stocks += 1
        if (i + 1) % 200 == 0:
            elapsed = time.time() - p1
            print(f'  进度 {i+1}/{len(stocks)} 只, {done_stocks} 成功, {total_success} 因子, {elapsed:.0f}s')

    elapsed = time.time() - p1
    print(f'✅ 完成: {done_stocks} 只股票, {total_success} 因子计算, {elapsed:.0f}s')
    try:
        stats = fpm.get_cache_stats()
        print(f'factor_cache: {stats.get("stock_count",0)} 股票, {stats.get("factor_count",0)} 因子, {stats.get("total_records",0)} 行')
    except Exception as e:
        print(f'统计失败: {e}')
