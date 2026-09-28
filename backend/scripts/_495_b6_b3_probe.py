"""495号（B3）探针：dim6 risk.status_description 全市场分布（流动性/ATR/风险等级）

从 strategy_signal_detail.dim_results_json 抽样统计（daemon 运行态，只读 WAL 可并发）：
  - liquidity_risk 触发占比（KB 双门槛：日均成交额<5000万 或 流通市值<30亿）
  - atr_pct>0.8 占比（波动率仓位折减覆盖面）
  - risk_level 分布（低/中/高/极高）
供 B3 拍板（流动性 soft→hard 影响面量化）。
"""
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA = os.environ.get('DATA_DIR') or '/Users/kalence/Desktop/01-A股股票分析系统/data'
DB = os.path.join(DATA, 'duckdb', 'snapshot_cache.db')
SAMPLE = int(os.environ.get('B3_SAMPLE', '500'))


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    # 最新交易日全市场抽样
    rows = conn.execute(
        "SELECT ts_code, dim_results_json FROM strategy_signal_detail"
        " WHERE trade_date = (SELECT MAX(trade_date) FROM strategy_signal_detail)"
        " AND dim_results_json IS NOT NULL LIMIT ?",
        (SAMPLE,)).fetchall()
    conn.close()

    stats = {'n': 0, 'liq_trigger': 0, 'liq_data': 0, 'atr_gt08': 0, 'atr_data': 0,
             'lv': {'低': 0, '中': 0, '高': 0, '极高': 0}, 'lv_other': 0, 'risk_data': 0}
    for r in rows:
        try:
            dr = json.loads(r['dim_results_json'])
            risk = (dr.get('risk') or {}).get('status_description') or {}
        except Exception:
            continue
        stats['n'] += 1
        if 'liquidity_risk' in risk:
            stats['liq_data'] += 1
            if risk.get('liquidity_risk'):
                stats['liq_trigger'] += 1
        if 'atr_pct' in risk and risk.get('atr_pct') is not None:
            stats['atr_data'] += 1
            if float(risk['atr_pct']) > 0.8:
                stats['atr_gt08'] += 1
        lv = (dr.get('risk') or {}).get('judgment', {}).get('level') or \
             (dr.get('risk') or {}).get('judgment', {}).get('risk_level')
        if lv in stats['lv']:
            stats['lv'][lv] += 1
            stats['risk_data'] += 1
        elif lv:
            stats['lv_other'] += 1

    n = stats['n'] or 1
    print(f"样本: {stats['n']} 只")
    print(f"流动性判定有数据: {stats['liq_data']}（{stats['liq_data']/n*100:.1f}%）")
    print(f"  liquidity_risk 触发（日均额<5000万 或 流通市值<30亿）: {stats['liq_trigger']}"
          f"（{stats['liq_trigger']/max(stats['liq_data'],1)*100:.1f}% 有数据中）")
    print(f"ATR 有数据: {stats['atr_data']}；atr_pct>0.8（波动率折减）: {stats['atr_gt08']}"
          f"（{stats['atr_gt08']/max(stats['atr_data'],1)*100:.1f}% 有数据中）")
    print(f"risk_level 分布: {stats['lv']}（未归类 {stats['lv_other']}）")


if __name__ == '__main__':
    main()
