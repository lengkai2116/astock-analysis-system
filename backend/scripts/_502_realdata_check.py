"""502号 批次4/5 真实数据重算验证（只读）：
新实现（502 后）vs 落库旧值（indicator_other）对比——平盘股 600825.SH / 001330.SZ
预期：KDJ 平盘日旧值≈0/异常 → 新值≈50 平滑；RSI 正常序列几乎不变
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd  # noqa: E402

DUCK = '/Users/kalence/Desktop/01-A股股票分析系统/data/duckdb'


def ro(p):
    c = sqlite3.connect(f'file:{p}?mode=ro', uri=True)
    c.execute('PRAGMA busy_timeout=2000')
    return c


def main():
    from app.indicators import TechnicalIndicatorEngine
    mc = ro(os.path.join(DUCK, 'market_cache.db'))
    cc = ro(os.path.join(DUCK, 'compute_cache.db'))
    eng = TechnicalIndicatorEngine()

    for ts in ['600825.SH', '001330.SZ']:
        rows = mc.execute(
            "SELECT trade_date, open, high, low, close, vol, amount, pct_chg FROM daily_cache "
            "WHERE ts_code=? ORDER BY trade_date", (ts,)).fetchall()
        if not rows:
            print(f"{ts}: 无日线")
            continue
        df = pd.DataFrame(rows, columns=['trade_date', 'open', 'high', 'low', 'close', 'vol', 'amount', 'pct_chg'])
        new = eng.calculate_all_indicators(df.copy())
        # 落库旧值（indicator_other）
        old_rows = cc.execute(
            "SELECT trade_date, rsi14, kdj_k, kdj_d, kdj_j FROM indicator_other WHERE ts_code=? ORDER BY trade_date",
            (ts,)).fetchall()
        old = pd.DataFrame(old_rows, columns=['trade_date', 'rsi14', 'kdj_k', 'kdj_d', 'kdj_j']) if old_rows else pd.DataFrame()

        # 找平盘日
        flat_days = df[df['high'] == df['low']]['trade_date'].tolist()
        print(f"\n== {ts}: {len(df)} 日线, 平盘日 {flat_days} ==")
        if old.empty:
            print("  落库旧值缺失")
            continue
        m = old.merge(new[['trade_date', 'rsi14', 'kdj_k', 'kdj_d', 'kdj_j']], on='trade_date',
                      suffixes=('_old', '_new'))
        # 平盘日对比
        for d in flat_days:
            row = m[m['trade_date'] == d]
            if row.empty:
                continue
            r = row.iloc[0]
            print(f"  平盘日 {d}: kdj_k 旧={r['kdj_k_old']:.3f} → 新={r['kdj_k_new']:.3f} | "
                  f"rsi14 旧={r['rsi14_old']:.3f} → 新={r['rsi14_new']:.3f}")
            print(f"           kdj_d 旧={r['kdj_d_old']:.3f} → 新={r['kdj_d_new']:.3f} | "
                  f"kdj_j 旧={r['kdj_j_old']:.3f} → 新={r['kdj_j_new']:.3f}")
        # 平盘日后一天（断链传播检查）
        if flat_days:
            after = flat_days[-1]
            idx = df.index[df['trade_date'] == after][0]
            if idx + 1 < len(df):
                nd = df.iloc[idx + 1]['trade_date']
                row = m[m['trade_date'] == nd]
                if not row.empty:
                    r = row.iloc[0]
                    print(f"  次日 {nd}: kdj_k 旧={r['kdj_k_old']:.3f} → 新={r['kdj_k_new']:.3f}（旧断链传播→新修复）")
        # 全序列 rsi14 diff 统计
        d = (m['rsi14_new'] - m['rsi14_old']).abs()
        print(f"  rsi14 全序列 max|diff|={d.max():.4f}（应≈0，仅边界微差）")

    mc.close()
    cc.close()


if __name__ == '__main__':
    main()
