#!/usr/bin/env python3
"""akshare财务数据采集脚本 — 替代Tushare的_batch_*函数

用于非交易日或Tushare API异常时的手动补采。
采集范围：全市场活跃股票的财务指标/资产负债表/现金流量表/业绩预告。

用法：
    cd backend && .venv/bin/python scripts/collect_financial_akshare.py
"""
import sys, os, sqlite3, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DATA_DIR', os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..', 'data'))

import akshare as ak
import pandas as pd

DATA_DIR = os.environ.get('DATA_DIR', '/Users/kalence/Desktop/01-A股股票分析系统/data')
DB_PATH = os.path.join(DATA_DIR, 'duckdb', 'stock_cache.db')

def get_active_stocks():
    """从daily_cache获取活跃股票列表"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT DISTINCT ts_code FROM daily_cache WHERE trade_date >= date('now', '-60 days')"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]

def collect_fina_indicator(codes, limit=200):
    """采集财务指标（ROE等）"""
    conn = sqlite3.connect(DB_PATH)
    count = 0
    for i, code in enumerate(codes[:limit]):
        if i % 50 == 0:
            print(f'  [{i}/{min(len(codes), limit)}] fina_indicator...')
        try:
            df = ak.stock_financial_abstract_ths(symbol=code.split('.')[0], indicator='按报告期')
            if df is not None and not df.empty:
                for _, row in df.head(4).iterrows():
                    try:
                        end_date = str(row.iloc[0])[:10] if len(row) > 0 else ''
                        roe = float(row.get('净资产收益率', 0) or 0)
                        roce = float(row.get('总资产报酬率', 0) or 0)
                        conn.execute(
                            "INSERT OR REPLACE INTO fina_indicator_cache (ts_code, end_date, roe, roce) VALUES (?, ?, ?, ?)",
                            [code, end_date, roe, roce]
                        )
                        count += 1
                    except:
                        pass
        except:
            pass
        time.sleep(0.1)
    conn.commit()
    conn.close()
    return count

def collect_balancesheet(codes, limit=200):
    """采集资产负债表"""
    conn = sqlite3.connect(DB_PATH)
    count = 0
    for i, code in enumerate(codes[:limit]):
        if i % 50 == 0:
            print(f'  [{i}/{min(len(codes), limit)}] balancesheet...')
        try:
            ak_code = code.split('.')[0]
            market = code.split('.')[1] if '.' in code else ''
            full_code = f'{market}{ak_code}'
            df = ak.stock_balance_sheet_by_report_em(symbol=full_code)
            if df is not None and not df.empty:
                for _, row in df.head(4).iterrows():
                    try:
                        end_date = str(row.get('REPORT_DATE', ''))[:10]
                        ta = float(row.get('TOTAL_ASSETS', 0) or 0)
                        tl = float(row.get('TOTAL_LIABILITIES', 0) or 0)
                        conn.execute(
                            "INSERT OR REPLACE INTO balancesheet_cache (ts_code, end_date, total_assets, total_liab) VALUES (?, ?, ?, ?)",
                            [code, end_date, ta, tl]
                        )
                        count += 1
                    except:
                        pass
        except:
            pass
        time.sleep(0.1)
    conn.commit()
    conn.close()
    return count

def collect_cashflow(codes, limit=200):
    """采集现金流量表"""
    conn = sqlite3.connect(DB_PATH)
    count = 0
    for i, code in enumerate(codes[:limit]):
        if i % 50 == 0:
            print(f'  [{i}/{min(len(codes), limit)}] cashflow...')
        try:
            ak_code = code.split('.')[0]
            market = code.split('.')[1] if '.' in code else ''
            full_code = f'{market}{ak_code}'
            df = ak.stock_cash_flow_sheet_by_report_em(symbol=full_code)
            if df is not None and not df.empty:
                for _, row in df.head(4).iterrows():
                    try:
                        end_date = str(row.get('REPORT_DATE', ''))[:10]
                        fcf = float(row.get('FREE_CASHFLOW', 0) or 0)
                        ocf = float(row.get('NETCASH_OPERATE', 0) or 0)
                        conn.execute(
                            "INSERT OR REPLACE INTO cashflow_cache (ts_code, end_date, free_cashflow, cashflow_oper) VALUES (?, ?, ?, ?)",
                            [code, end_date, fcf, ocf]
                        )
                        count += 1
                    except:
                        pass
        except:
            pass
        time.sleep(0.1)
    conn.commit()
    conn.close()
    return count

def collect_forecast(codes, limit=200):
    """采集业绩预告"""
    conn = sqlite3.connect(DB_PATH)
    count = 0
    try:
        df = ak.stock_yjyg_em(date='20260630')
        if df is not None and not df.empty:
            for _, row in df.head(min(limit, len(df))).iterrows():
                try:
                    code = str(row.get('股票代码', ''))
                    if code:
                        conn.execute(
                            "INSERT OR REPLACE INTO forecast_cache (ts_code, end_date, forecast_type, net_profit_min, net_profit_max) VALUES (?, ?, ?, ?, ?)",
                            [code, str(row.get('报告期', '')), str(row.get('预告类型', '')),
                             float(row.get('预计净利润-最低', 0) or 0),
                             float(row.get('预计净利润-最高', 0) or 0)]
                        )
                        count += 1
                except:
                    pass
    except:
        pass
    conn.commit()
    conn.close()
    return count

if __name__ == '__main__':
    print('=== akshare财务数据采集 ===')
    print(f'数据库: {DB_PATH}')
    
    codes = get_active_stocks()
    print(f'活跃股票数: {len(codes)}')
    
    print('\n--- 采集fina_indicator ---')
    n = collect_fina_indicator(codes, limit=200)
    print(f'  写入: {n}条')
    
    print('\n--- 采集balancesheet ---')
    n = collect_balancesheet(codes, limit=200)
    print(f'  写入: {n}条')
    
    print('\n--- 采集cashflow ---')
    n = collect_cashflow(codes, limit=200)
    print(f'  写入: {n}条')
    
    print('\n--- 采集forecast ---')
    n = collect_forecast(codes, limit=200)
    print(f'  写入: {n}条')
    
    # 验证
    conn = sqlite3.connect(DB_PATH)
    print('\n=== 最终数据量 ===')
    for t in ['fina_indicator_cache', 'balancesheet_cache', 'cashflow_cache', 'forecast_cache', 'sentiment_pool_cache']:
        c = conn.execute(f'SELECT COUNT(*) FROM [{t}]').fetchone()[0]
        print(f'{t}: {c} rows')
    conn.close()
    
    print('\n采集完成')
