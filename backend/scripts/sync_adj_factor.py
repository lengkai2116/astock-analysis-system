"""
Phase 1: 复权因子批量同步（按交易日，非逐股）
"""
import os, sys, time
import pandas as pd
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy']:
    os.environ.pop(k, None)
TOKEN = '0ef90eacb9926e6e6007a3df09931ba6e88bfa86d5576280cbfdad3b'
os.environ['TUSHARE_TOKEN'] = TOKEN
os.environ['DATABASE_URL'] = 'sqlite:///test.db'
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from flask import Flask
from app import create_app
app = create_app()
with app.app_context():
    from app.data.enhanced_cache_manager import get_ecm_instance
    ecm = get_ecm_instance()
    con = ecm.conn
    import tushare as ts
    ts.set_token(TOKEN)
    pro = ts.pro_api()
    # 取120个交易日
    dates = [r[0] for r in con.execute(
        "SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date DESC LIMIT 120"
    ).fetchall()]
    dates.reverse()
    print(f'目标: {len(dates)} 个交易日 ({dates[0]} ~ {dates[-1]})')
    total = 0
    p1 = time.time()
    for i, d in enumerate(dates):
        try:
            date_str = d.strftime('%Y%m%d') if hasattr(d, 'strftime') else str(d).replace('-', '')
            df = pro.adj_factor(trade_date=date_str)
            if df is not None and not df.empty:
                if 'trade_date' in df.columns:
                    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.date
                ecm.cache_adj_factor_data(df)
                total += len(df)
        except Exception as e:
            print(f'  ❌ {d}: {e}')
        if (i+1) % 20 == 0:
            print(f'  进度 {i+1}/{len(dates)} 天, {total} 行, {time.time()-p1:.0f}s')
        time.sleep(0.35)
    print(f'✅ 完成: {total} 行, {time.time()-p1:.0f}s')
    final = con.execute("SELECT COUNT(*) FROM adj_factor_cache").fetchone()[0]
    codes = con.execute("SELECT COUNT(DISTINCT ts_code) FROM adj_factor_cache").fetchone()[0]
    print(f'adj_factor_cache: {codes} 股票, {final} 行')
