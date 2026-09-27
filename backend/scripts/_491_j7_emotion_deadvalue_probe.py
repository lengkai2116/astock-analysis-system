"""491-J7 取证探针（真实数据，只读）：'消极'/'积极' 在 L1 情绪路径的可达性

用法（daemon 停止态）：backend/.venv/bin/python backend/scripts/_491_j7_emotion_deadvalue_probe.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.dim_adapter import _EMOTION_DIRECTION, ENGINE_STATE_TO_CN  # noqa: E402
from app.opportunity_atlas.status_engine import StatusEngine  # noqa: E402

CODES = ['600519.SH', '000002.SZ', '300750.SZ', '601318.SH',
         '000001.SZ', '002594.SZ', '600036.SH', '600276.SH']


def main():
    print('491-J7 可达性探针：L1 情绪方向的输入值域')
    print('  _EMOTION_DIRECTION 键:', sorted(_EMOTION_DIRECTION.keys()))
    print('  ENGINE_STATE_TO_CN[emotion]:', ENGINE_STATE_TO_CN.get('emotion'))
    seen = set()
    for code in CODES:
        try:
            se = StatusEngine()
            tags = se._load_tags(code) or {}
            sg = se._load_signals(code) or {}
            lc = se._signal_lifecycle(code, tags, sg)
            dr = se._build_dim_engine_results(tags, sg, {}, lc, ts_code=code) or {}
            emo = dr.get('emotion') or {}
            sd = emo.get('status_description') or {}
            mp = sd.get('market_phase')
            seen.add(str(mp))
            print(f'  {code} market_phase={mp!r} sentiment_phase={tags.get("sentiment_phase")!r} '
                  f'stock_emotion={tags.get("stock_emotion")!r} '
                  f'→ 方向={_EMOTION_DIRECTION.get(str(mp), "KEY_MISS")}')
        except Exception as e:
            print(f'  {code} 异常: {type(e).__name__}: {e}')
    print(f'\n实测 market_phase 值域: {sorted(seen)}')
    print('是否出现 positive/negative/积极/消极:',
          any(v in ('positive', 'negative', '积极', '消极') for v in seen))


if __name__ == '__main__':
    main()
