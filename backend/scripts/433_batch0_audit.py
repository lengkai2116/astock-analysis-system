"""433号 批次0 审计脚本（只读，不写任何库/文件）
量化验证四维度口径：
  val   : EP(1/pe_ttm) vs valuation_deviation 代理等价性（当前快照截面相关）
  trend : 20日动量 vs trend_alignment 标签对应关系（标签是否动量离散化）
  earn  : fina_indicator_cache 多期/ann_date 可用性
  fund  : moneyflow 覆盖窗口内截面数
"""
import os
import sqlite3
import pandas as pd
import numpy as np

ROOT = "/Users/kalence/Desktop/01-A股股票分析系统/data/duckdb"

def q(db, sql):
    conn = sqlite3.connect(f"{ROOT}/{db}", uri=True)
    try:
        return pd.read_sql(sql, conn)
    finally:
        conn.close()

def spearman(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    m = ~(np.isnan(a) | np.isnan(b))
    a, b = a[m], b[m]
    if len(a) < 30:
        return float("nan"), len(a)
    ra = pd.Series(a).rank().values
    rb = pd.Series(b).rank().values
    ma, mb = ra.mean(), rb.mean()
    cov = np.sum((ra - ma) * (rb - mb))
    va = np.sqrt(np.sum((ra - ma) ** 2))
    vb = np.sqrt(np.sum((rb - mb) ** 2))
    return (cov / (va * vb) if va and vb else float("nan")), len(a)

print("=" * 70)
print("① val：EP vs valuation_deviation 代理等价性（当前快照 2026-09-11）")
print("=" * 70)
snap = q("snapshot_cache.db", "SELECT ts_code, pe, valuation_deviation, trend_alignment FROM treemap_snapshot WHERE trade_date='2026-09-11'")
basic = q("market_cache.db", "SELECT ts_code, pe_ttm FROM daily_basic_cache WHERE trade_date='2026-09-11'")
m = snap.merge(basic, on="ts_code", how="inner")
m["ep"] = 1.0 / m["pe_ttm"]
m = m[m["ep"].notna() & m["valuation_deviation"].notna() & (m["pe_ttm"] > 0)]
r_sp, n = spearman(m["ep"].values, m["valuation_deviation"].values)
r_pe = m["pe_ttm"].corr(m["valuation_deviation"])
print(f" 样本 {n}：EP vs valuation_deviation  Spearman={r_sp:.3f}  Pearson(pe vs dev)={r_pe:.3f}")
print(f" 结论判定：{'相关度高→EP 可作代理（声明等价成立）' if abs(r_sp) > 0.5 else '相关度低→EP 不可代理 valuation_deviation'}")
print(f" 注：valuation_deviation 无历史截面（treemap_snapshot 仅 1 快照），IC 重算只能算 EP")

print()
print("=" * 70)
print("② trend：20 日动量 vs trend_alignment 标签对应关系（2026-09-11）")
print("=" * 70)
# 动量：09-11 close / 20 交易日前 close - 1
d = q("market_cache.db", """
  SELECT t.ts_code, t.close c_now, p.close c_prev
  FROM daily_cache t
  JOIN (SELECT ts_code, close, trade_date FROM daily_cache d
        WHERE trade_date <= '2026-09-11'
          AND ts_code IN (SELECT ts_code FROM daily_cache WHERE trade_date='2026-09-11')
        ORDER BY ts_code, trade_date DESC) p
       ON p.ts_code = t.ts_code
       AND p.trade_date = (SELECT trade_date FROM daily_cache
                           WHERE ts_code = t.ts_code AND trade_date <= '2026-09-11'
                           ORDER BY trade_date DESC LIMIT 1 OFFSET 20)
  WHERE t.trade_date = '2026-09-11'
""")
ta = snap[["ts_code", "trend_alignment"]]
m2 = d.merge(ta, on="ts_code", how="inner")
m2["mom20"] = m2["c_now"] / m2["c_prev"] - 1
print("  标签分布 + 各标签下 20 日动量均值：")
g = m2.groupby("trend_alignment")["mom20"].agg(["count", "mean", "median"])
print(g.to_string())
labels = {"up_aligned": 0.8, "mixed": 0.5, "no_trend": 0.5, "down_aligned": 0.2, "": 0.5, None: 0.5}
m2["label_score"] = m2["trend_alignment"].map(labels).fillna(0.5)
r_sp2, n2 = spearman(m2["mom20"].values, m2["label_score"].values)
print(f"  动量 vs 标签分  Spearman={r_sp2:.3f}  样本 {n2}")
print(f"  判定：{'标签可视为动量离散化→动量 IC 可代理 trend 维度' if abs(r_sp2) > 0.3 else '标签与动量相关性弱→trend 重估口径需另行决策'}")

print()
print("=" * 70)
print("③ earn：fina_indicator_cache 多期/ann_date 可用性")
print("=" * 70)
f = q("financial_cache.db", "SELECT COUNT(*) n, COUNT(DISTINCT ts_code) codes, COUNT(ann_date) ann_ok, COUNT(DISTINCT end_date) periods FROM fina_indicator_cache")
print(f"  总行 {f['n'][0]} / 股票 {f['codes'][0]} / ann_date 非空 {f['ann_ok'][0]} / 不同 end_date 期数 {f['periods'][0]}")
enddist = q("financial_cache.db", "SELECT end_date, COUNT(*) n FROM fina_indicator_cache GROUP BY end_date ORDER BY end_date DESC")
print("  各 end_date（报告期）行数：")
print(enddist.to_string(index=False))
# 每只股票多期 → dict(zip) 覆盖问题实测
multi = q("financial_cache.db", "SELECT ts_code, COUNT(*) n FROM fina_indicator_cache GROUP BY ts_code HAVING n > 1")
print(f"  多期股票数 {len(multi)} / 5555（{len(multi)/5555:.0%}）→ dict(zip) 覆盖问题真实存在")

print()
print("=" * 70)
print("④ fund：moneyflow 覆盖窗口与截面数")
print("=" * 70)
mf = q("market_cache.db", "SELECT COUNT(DISTINCT trade_date) days, MIN(trade_date) mn, MAX(trade_date) mx, COUNT(*) rows_ FROM moneyflow_cache")
print(f"  交易日 {mf['days'][0]}（{mf['mn'][0]} ~ {mf['mx'][0]}），行数 {mf['rows_'][0]}")
days = q("market_cache.db", "SELECT trade_date FROM moneyflow_cache GROUP BY trade_date ORDER BY trade_date DESC")
n_sections = max(0, len(days) // 20)
print(f"  每 20 日一截面 → 理论截面数 ≈ {n_sections}")
print(f"  判定：{'样本不足→建议 fund 暂停重估（≥60 交易日再启用）' if n_sections < 3 else '覆盖可行'}")
