"""521号 O4-B：定向回补 10-13/10-14 龙虎榜席位明细（覆盖式写入）

背景：10-13/10-14 完整性检查在 18:00 补采时 Tushare top_inst 仅发布部分数据
（80/60 条落库 45 行、覆盖 7/5 只 vs 主表 62/68 只），且旧判据「非空即通过」
导致后续巡检不再补采。源侧现已完整（10-13=670 行/62 只、10-14=760 行/68 只，
2026-10-15 探针实证）。

本脚本直接调用 DataManager.sync_lhb_detail_data（Tushare top_inst →
cache_lhb_detail_data 覆盖式按 trade_date 全量重写），强制补全两个缺失日。

用法：cd backend && PYTHONPATH=. .venv/bin/python scripts/_521_o4_lhb_backfill.py
"""
import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_ROOT = os.path.dirname(_BACKEND)
sys.path.insert(0, _BACKEND)
os.environ.setdefault('DATA_DIR', os.path.join(_PROJECT_ROOT, 'data'))

from app.data import DataManager
from app.data.enhanced_cache_manager import get_ecm_instance

TARGET_DATES = ('20261013', '20261014')


def main():
    dm = DataManager()
    ecm = get_ecm_instance()
    for d in TARGET_DATES:
        before = ecm._query_df(
            "SELECT COUNT(*) cnt, COUNT(DISTINCT ts_code) stocks FROM lhb_detail_cache WHERE trade_date=?",
            [f'{d[:4]}-{d[4:6]}-{d[6:]}'],
        )
        b_cnt = int(before.iloc[0]['cnt']) if not before.empty else 0
        b_stocks = int(before.iloc[0]['stocks']) if not before.empty else 0
        n = dm.sync_lhb_detail_data(trade_date=d)
        after = ecm._query_df(
            "SELECT COUNT(*) cnt, COUNT(DISTINCT ts_code) stocks FROM lhb_detail_cache WHERE trade_date=?",
            [f'{d[:4]}-{d[4:6]}-{d[6:]}'],
        )
        a_cnt = int(after.iloc[0]['cnt']) if not after.empty else 0
        a_stocks = int(after.iloc[0]['stocks']) if not after.empty else 0
        print(f'{d}: 回补写入 {n} 条 | 落库 {b_cnt}→{a_cnt} 行 / {b_stocks}→{a_stocks} 只')


if __name__ == '__main__':
    main()
