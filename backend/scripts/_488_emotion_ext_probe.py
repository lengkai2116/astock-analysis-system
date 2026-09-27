"""488号 附：dim1 data_context 的 emotion_ext 供给核查（只读，不写）

用途：488 A1 复跑发现 8 股情绪温度因句恒「涨停无数据/封板率无数据」——
      核查是「dim1 未把 emotion_ext 注入 data_context（接线缺口）」还是
      「pre_feat_cache 未产 emotion_ext（数据缺口）」。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app import create_app
from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
from app.opportunity_atlas.status_engine import StatusEngine

CODES = ['600519.SH', '000002.SZ', '601318.SH', '000001.SZ']


def main():
    app = create_app()
    se = StatusEngine()
    d1 = Dim1SignalEngine()
    with app.app_context():
        for c in CODES:
            tags = se._load_tags(c) or {}
            signals = se._load_signals(c) or {}
            lifecycle = se._signal_lifecycle(c, tags, signals)
            r = d1.evaluate({}, tags, signals, lifecycle, ts_code=c) or {}
            dc = r.get('data_context') or {}
            ext = sorted(k for k in dc if k.endswith('_ext'))
            sq = r.get('status_quality') or {}
            print(f'### {c}')
            print(f'  data_context ext 键: {ext}')
            print(f'  emotion_ext: {dc.get("emotion_ext")!r}')
            print(f'  market_stats: {dc.get("market_stats")!r}')
            print(f'  missing_tables: {sq.get("missing_tables")}')
            print(f'  quality_issues: {sq.get("quality_issues")}')


if __name__ == '__main__':
    main()
