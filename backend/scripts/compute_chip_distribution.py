"""
Phase 2: 全市场筹码分布计算
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
    from app.data.chip_distribution_service import ChipDistributionEstimator
    import pandas as pd

    ecm = get_ecm_instance()
    con = ecm.conn

    # 清空旧筹码数据
    con.execute("DELETE FROM chip_distribution_cache")
    con.commit()

    stocks = [r[0] for r in con.execute("""
        SELECT DISTINCT ts_code FROM daily_cache 
        WHERE trade_date >= date('now', '-1 year')
        AND ts_code NOT LIKE '%.BJ'
        ORDER BY ts_code
    """).fetchall()]
    print(f'待计算: {len(stocks)} 只')

    estimator = ChipDistributionEstimator(num_bins=120, decay_rate=0.005)
    done = 0
    total_rows = 0
    p1 = time.time()

    for i, code in enumerate(stocks):
        try:
            df = pd.read_sql(
                "SELECT * FROM daily_cache WHERE ts_code = ? ORDER BY trade_date",
                con, params=[code]
            )
            if df.empty or len(df) < 30:
                continue
            chip_dist, min_px, max_px, step = estimator.estimate(df)
            if chip_dist is None or len(chip_dist) == 0:
                continue
            trade_date = df['trade_date'].iloc[-1]
            price_bins = [min_px + j * step for j in range(len(chip_dist))]
            total_chips = chip_dist.sum()
            if total_chips <= 0:
                continue
            chip_bins = [
                {'price_bin': round(float(p), 2),
                 'chip_ratio': round(float(c) / total_chips, 6),
                 'accumulated_ratio': 0, 'peak_flag': 0}
                for p, c in zip(price_bins, chip_dist)
            ]
            ecm.cache_chip_distribution(code, trade_date, chip_bins)
            done += 1
            total_rows += len(chip_bins)
        except Exception:
            pass

        if (i + 1) % 500 == 0:
            elapsed = time.time() - p1
            print(f'  进度 {i+1}/{len(stocks)} 只, {done} 成功, {total_rows} 行, {elapsed:.0f}s')

    elapsed = time.time() - p1
    print(f'✅ 完成: {done} 只股票, {total_rows} 行, {elapsed:.0f}s')
    final = con.execute("SELECT COUNT(*) FROM chip_distribution_cache").fetchone()[0]
    codes = con.execute("SELECT COUNT(DISTINCT ts_code) FROM chip_distribution_cache").fetchone()[0]
    print(f'chip_distribution_cache: {codes} 股票, {final} 行')
