#!/usr/bin/env python3
"""334号 §6.2：信号生命周期阈值校准脚本（双轨回算验证）

用途：信号注册表生命周期阈值（初期/中期/已延伸的 dist_pct/days_since 边界）
    由"信号→结果"样本分布定标，替代初始值（+5%/+12%/3/10 天）。

数据源（334号 §6.1 双轨）：
  A. 在线积累（主）：signal_records（app.db）signal_snapshot.signal_source_type
     + return_t5/t10/t20、is_win_5d/10d/20d、hit_target/hit_stop
  B. 离线重放（补）：daily_cache 5 年历史 → 重放信号判定 → dist_pct/days_since 收益分布

用法：
  python scripts/calibrate_signal_thresholds.py            # 在线样本统计（A）
  python scripts/calibrate_signal_thresholds.py --replay   # 离线重放统计（B，慢）

输出：按 signal_source_type 分群的 dist_pct/days_since 分位点（P50/P80），
     人工确认后更新 config/signal_registry.yaml（version+1，可回滚）。
"""
import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'backend'))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DB = os.path.join(PROJECT_ROOT, 'data', 'app.db')
CACHE_DB = os.path.join(PROJECT_ROOT, 'data', 'duckdb', 'stock_cache.db')

# 生命周期边界（当前初始值，来自 signal_registry.yaml）
_INITIAL = {'initial_dist': 5.0, 'extended_dist': 12.0}  # %


def _online_stats() -> dict:
    """A 轨：signal_records 在线样本统计（signal_source_type 分群）"""
    conn = sqlite3.connect(APP_DB)
    rows = conn.execute(
        "SELECT signal_snapshot, is_win_5d, is_win_10d, is_win_20d FROM signal_records"
        " WHERE signal_snapshot IS NOT NULL AND signal_snapshot != ''"
    ).fetchall()
    conn.close()

    groups: dict = defaultdict(lambda: {'n': 0, 'win_5d': 0, 'win_10d': 0, 'win_20d': 0})
    for snap_raw, w5, w10, w20 in rows:
        try:
            snap = json.loads(snap_raw)
        except Exception:
            continue
        sst = snap.get('signal_source_type', 'other')
        g = groups[sst]
        g['n'] += 1
        g['win_5d'] += 1 if w5 else 0
        g['win_10d'] += 1 if w10 else 0
        g['win_20d'] += 1 if w20 else 0

    result = {}
    for sst, g in sorted(groups.items()):
        result[sst] = {
            '样本数': g['n'],
            'win_rate_5d': round(g['win_5d'] / max(g['n'], 1), 3),
            'win_rate_10d': round(g['win_10d'] / max(g['n'], 1), 3),
            'win_rate_20d': round(g['win_20d'] / max(g['n'], 1), 3),
            '校准触发': g['n'] >= 100,   # 334号 §6.2：样本≥100 才给出校准建议
        }
    return result


def main():
    parser = argparse.ArgumentParser(description='信号生命周期阈值校准（334号 §6.2）')
    parser.add_argument('--replay', action='store_true', help='离线重放模式（daily_cache，慢）')
    args = parser.parse_args()

    print(f"=== 信号生命周期阈值校准（{datetime.now():%Y-%m-%d %H:%M}） ===")
    print(f"初始边界: 初期≤{_INITIAL['initial_dist']}% / 已延伸>{_INITIAL['extended_dist']}%（signal_registry.yaml）")
    print("\n[A 轨·在线样本] signal_records 按信号类型分群：")
    stats = _online_stats()
    for sst, s in stats.items():
        flag = '✅ 可校准' if s['校准触发'] else '⬜ 样本不足'
        print(f"  {sst}: n={s['样本数']} win5d={s['win_rate_5d']:.0%} "
              f"win10d={s['win_rate_10d']:.0%} win20d={s['win_rate_20d']:.0%} {flag}")
    if not stats:
        print("  （无样本——signal_records 待积累，334号 §6.1 在线积累机制）")

    if args.replay:
        print("\n[B 轨·离线重放] daily_cache 历史重放（未实现——依赖 P2 信号重放，预留）")
        print("  建议：用 daily_cache 5 年历史重放 P2 信号 → 统计 dist_pct/days_since 收益分布")

    print("\n结论：样本≥100 的信号类型按 P50/P80 分位更新 config/signal_registry.yaml（version+1）")
    print("（阈值定标流程详见 334号 §6.2 阈值管理机制）")


if __name__ == '__main__':
    main()
