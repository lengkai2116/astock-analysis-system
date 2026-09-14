"""426号阶段三：P1-3 定向回补 pre_feat_cache 历史缺口（daemon 已停止，锁可用）

目标日：08-27（现仅 5 行）、08-31~09-04、09-07、09-08（整日缺失）共 8 日。
复用 RAW-2 逻辑（_precompute_raw_features 的 target_date 参数限定日期）：
对每只股票将日线截断到目标日，特征按当日口径计算。

运行：cd backend && .venv/bin/python scripts/_426_phase3_prefeat_backfill.py
支持断点续跑：已完成的日期记录在 data/alerts/426_p3_prefeat_ckpt.txt，跳过。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data_daemon as dd
from app.data.sharding_manager import sharding_manager

DUCKDB = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'duckdb')
CKPT = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'alerts', '426_p3_prefeat_ckpt.txt')
# 08-27 仅 5 行 + 08-31~09-04、09-07、09-08 整日缺失（08-28/09-09~11 已完整）
DATES = ['2026-08-27', '2026-08-31', '2026-09-01', '2026-09-02',
         '2026-09-03', '2026-09-04', '2026-09-07', '2026-09-08']


def load_ckpt() -> set:
    if os.path.exists(CKPT):
        with open(CKPT) as f:
            return {line.strip() for line in f if line.strip()}
    return set()


def save_ckpt(done: set):
    os.makedirs(os.path.dirname(CKPT), exist_ok=True)
    with open(CKPT, 'w') as f:
        f.write('\n'.join(sorted(done)) + '\n')


def count_pre_feat(date: str) -> int:
    db = sharding_manager.get_db_for_table('pre_feat_cache')
    conn = sharding_manager.get_connection(db)
    return conn.execute(
        "SELECT COUNT(*) FROM pre_feat_cache WHERE trade_date=?", [date]).fetchone()[0]


def main():
    dd._ensure_ecm()
    done = load_ckpt()

    from app import create_app
    app = create_app()

    for d in DATES:
        if d in done:
            print(f"[跳过] {d}（checkpoint 已记录）")
            continue
        # 目标日 codes（daily_cache 当日有数据即回补）
        db = sharding_manager.get_db_for_table('daily_cache')
        conn = sharding_manager.get_connection(db)
        codes = [r[0] for r in conn.execute(
            "SELECT DISTINCT ts_code FROM daily_cache WHERE trade_date=?", [d]).fetchall()]
        if not codes:
            print(f"[跳过] {d} daily_cache 无数据")
            done.add(d)
            save_ckpt(done)
            continue
        print(f"[回补] {d}: {len(codes)} 只，开始 RAW-2 特征计算...")
        # 预热当日 market_stats（RAW-2 的 market_stats 特征组按当日口径）
        try:
            dd._precompute_market_stats(target_date=d)
        except Exception as e:
            print(f"[警告] {d} market_stats 预热失败: {e}")
        with app.app_context():
            dd._precompute_raw_features(codes, target_date=d)
        n = count_pre_feat(d)
        flag = 'OK' if n >= 5000 else '⚠️不足5000'
        print(f"[完成] {d}: pre_feat_cache {n} 行 {flag}")
        done.add(d)
        save_ckpt(done)

    # 汇总
    print("\n[汇总] 回补后 pre_feat_cache 按日分布:")
    db = sharding_manager.get_db_for_table('pre_feat_cache')
    conn = sharding_manager.get_connection(db)
    rows = conn.execute(
        "SELECT trade_date, COUNT(*) FROM pre_feat_cache "
        "WHERE trade_date>='2026-08-27' GROUP BY trade_date ORDER BY trade_date").fetchall()
    for r in rows:
        print(f"  {r[0]}: {r[1]} 行")


if __name__ == '__main__':
    main()
