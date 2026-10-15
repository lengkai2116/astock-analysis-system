"""521号 O1：新股上市前 5 日豁免——数据回补（stocks 表新股 + daily_cache 首日行）

背景：深度清洗规则6 `|pct_chg|>50 → 剔除`（417号方案）未豁免注册制新股
上市前 5 个交易日（创业板/科创板/北交所无涨跌幅限制）。实证：
- 301660.SZ（创业板，10-13 上市）首日 +223.06% 被剔 → daily_cache 缺 10-13 首日
- 920157.BJ（北交所，10-09 上市）首日 +449.45% 被剔 → daily_cache 缺 10-09 首日

本脚本：
1. 将 10 月新股（list_date >= 2026-10-09）补进 app.db stocks 表
   （豁免判据 _load_list_date_map 依赖 stocks.list_date；stocks 表月度同步
   判定「本月已同步」跳过，10 月新股未入库）
2. 回补 daily_cache 被误剔的首日行（经 ECM cache_daily_data 写入，
   豁免判据生效后不会被再次剔除）

用法：cd backend && PYTHONPATH=. .venv/bin/python scripts/_521_o1_newstock_backfill.py
"""
import os
import sqlite3
import sys
from datetime import datetime

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_ROOT = os.path.dirname(_BACKEND)
sys.path.insert(0, _BACKEND)
os.environ.setdefault('DATA_DIR', os.path.join(_PROJECT_ROOT, 'data'))

import pandas as pd  # noqa: E402
import tushare as ts  # noqa: E402

MIN_LIST_DATE = '20261009'  # 10 月新股起点（920157.BJ 10-09 上市）


def backfill_stocks():
    """10 月新股补进 app.db stocks 表（raw sqlite，INSERT OR REPLACE）"""
    pro = ts.pro_api()
    df = pro.stock_basic(list_status='L',
                         fields='ts_code,symbol,name,industry,market,list_date')
    if df is None or df.empty:
        print('stock_basic 返回空，无法补 stocks 表')
        return 0
    new = df[df['list_date'] >= MIN_LIST_DATE]
    app_db = os.path.join(os.getenv('DATA_DIR', 'data'), 'app.db')
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    n = 0
    with sqlite3.connect(app_db) as con:
        for _, r in new.iterrows():
            con.execute(
                """INSERT OR REPLACE INTO stocks
                   (ts_code, symbol, name, industry, market, list_date, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (r['ts_code'], r['symbol'], r['name'], r.get('industry'),
                 r.get('market'), r['list_date'], now, now),
            )
            n += 1
    print(f'stocks 表补入 10 月新股 {n} 只（list_date >= {MIN_LIST_DATE}）')
    return n


def backfill_daily_firstday():
    """回补被误剔的新股首日行（daily_cache 缺首日的 10 月新股）"""
    from app.data.enhanced_cache_manager import EnhancedCacheManager

    ecm = EnhancedCacheManager()
    pro = ts.pro_api()
    # 找 daily_cache 中 10 月新股缺首日的（list_date 对应的 trade_date 不存在）
    with sqlite3.connect(os.path.join(os.getenv('DATA_DIR', 'data'), 'app.db')) as con:
        rows = con.execute(
            "SELECT ts_code, list_date FROM stocks WHERE list_date >= ?",
            [MIN_LIST_DATE],
        ).fetchall()
    total = 0
    for ts_code, list_date in rows:
        if not list_date:
            continue
        ld = str(list_date).replace('-', '')
        cnt = ecm._query_shard(
            'daily_cache',
            "SELECT COUNT(*) AS n FROM daily_cache WHERE ts_code=? AND trade_date=?",
            [ts_code, f'{ld[:4]}-{ld[4:6]}-{ld[6:]}'],
        )
        if cnt is not None and not cnt.empty and int(cnt.iloc[0]['n']) > 0:
            continue  # 首日已在库
        # 从源侧取该股全量日线（含首日），写入 daily_cache（豁免判据生效→不被剔）
        daily = pro.daily(ts_code=ts_code, start_date=ld, end_date=datetime.now().strftime('%Y%m%d'))
        if daily is None or daily.empty:
            print(f'  {ts_code}（{list_date}）：源侧无数据，跳过')
            continue
        daily = daily.sort_values('trade_date')
        df = daily[['ts_code', 'trade_date', 'open', 'high', 'low', 'close',
                    'vol', 'amount', 'pct_chg']].copy()
        df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y-%m-%d')
        ecm.cache_daily_data(df)
        total += len(df)
        print(f'  {ts_code}（{list_date}）：回补 {len(df)} 行（含首日）')
    print(f'daily_cache 回补完成，共写入 {total} 行')
    return total


if __name__ == '__main__':
    backfill_stocks()
    backfill_daily_firstday()
