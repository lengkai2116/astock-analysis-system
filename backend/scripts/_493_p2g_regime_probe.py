"""493 批次3（P2-g）诊断：`_detect_market_regime` 实际可达性与 regime 分布（只读）

对样本逐只重放 v390 的 regime 判定输入（tags + _convert_to_dims_format(dim_results)），
统计 _detect_market_regime 的实际返回分布，确认：
  - tags['status_bar'] 分支是否恒不可达；
  - emotion/risk 回退分支是否可达（dims.emotion.state = CN 映射的 market_phase）；
  - 实际生效的 MARKET_REGIME_WEIGHTS 档位（trending_up 是否永不出现）。

用法：backend/.venv/bin/python backend/scripts/_493_p2g_regime_probe.py [N]
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.data.sharding_manager import sharding_manager  # noqa: E402
from app.opportunity_atlas.status_engine import StatusEngine  # noqa: E402

DATE = '2026-09-24'


def main():
    n_sample = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    rows = sharding_manager.execute_query(
        'strategy_signal_detail',
        f"SELECT ts_code, dim_results_json FROM strategy_signal_detail WHERE trade_date='{DATE}' "
        "AND dim_results_json IS NOT NULL ORDER BY ts_code", [])
    step = max(1, len(rows) // n_sample)
    sample = rows[::step][:n_sample]
    print(f'### 493 P2-g regime 诊断：{len(sample)}/{len(rows)} 只\n')

    se = StatusEngine()
    regime_cnt = Counter()
    emo_cnt = Counter()
    has_status_bar = 0
    n = fail = 0
    for i, (code, dj) in enumerate(sample):
        try:
            tags = se._load_tags(code) or {}
            dr = json.loads(dj)
            if 'status_bar' in tags:
                has_status_bar += 1
            dims = se._convert_to_dims_format(dr, tags)
            emo = str(dims.get('emotion', {}).get('state', ''))
            emo_cnt[emo] += 1
            regime = se._detect_market_regime(tags, dims)
            regime_cnt[regime] += 1
        except Exception as e:
            fail += 1
            if fail <= 3:
                print(f'  [异常] {code}: {type(e).__name__}: {e}')
            continue
        n += 1

    print(f'n={n} fail={fail}  tags 含 status_bar 的样本: {has_status_bar}\n')
    print('=== 实际 regime 分布（_detect_market_regime 返回）===')
    for k, v in regime_cnt.most_common():
        print(f'  {k}: {v} ({v / max(n, 1) * 100:.1f}%)')
    print('=== dims.emotion.state（regime 情绪分支输入）===')
    for k, v in emo_cnt.most_common(10):
        print(f'  {k!r}: {v} ({v / max(n, 1) * 100:.1f}%)')
    print(f'\n结论：trending_up 出现次数 = {regime_cnt.get("trending_up", 0)}'
          f'（0 = 该档不可达 → MARKET_REGIME_WEIGHTS 实为单档）')


if __name__ == '__main__':
    main()
