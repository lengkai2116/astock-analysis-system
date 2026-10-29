"""基准库 10-27 原料恢复：重算 indicator_ma/macd/other 与 factor_cache。

背景：552 沙箱补测脚本的分库 DELETE 误落基准库，清空 10-27 的 5 张原料表；
pre_feat 已按 /tmp/552_pre_feat_2026-10-27.json 精确回填，本脚本补算其余 4 张。
"""
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.abspath(os.path.join(BASE, '..', 'data'))
sys.path.insert(0, BASE)
os.environ['DATA_DIR'] = DATA
os.environ['DATABASE_URL'] = f'sqlite:///{DATA}/app.db'
os.environ['DATA_DAEMON_RUNNING'] = '1'
os.environ['RAW2_CHILD'] = '1'
for _k in [k for k in os.environ if 'proxy' in k.lower()]:
    os.environ.pop(_k, None)

import data_daemon as dd  # noqa: E402
from app.data.sharding_manager import init_sharding  # noqa: E402


def main():
    init_sharding(DATA)
    dd._ensure_ecm()
    codes = dd._get_active_codes('2026-10-27')
    print(f'恢复目标 {DATA}，代码 {len(codes)} 只', flush=True)

    t0 = time.time()
    dd._precompute_indicators(codes)
    print(f'RAW-1 指标恢复完成: {time.time() - t0:.1f}s', flush=True)

    t1 = time.time()
    dd._precompute_preset_combos(codes)
    print(f'RAW-3 因子恢复完成: {time.time() - t1:.1f}s', flush=True)

    for t in ('pre_feat_cache', 'indicator_ma', 'indicator_macd', 'indicator_other', 'factor_cache'):
        rows = dd._shard_fetchall(t, f"SELECT COUNT(*) FROM {t} WHERE trade_date='2026-10-27'")
        print(f'  {t}: {rows[0][0] if rows else "ERR"}', flush=True)


if __name__ == '__main__':
    main()
