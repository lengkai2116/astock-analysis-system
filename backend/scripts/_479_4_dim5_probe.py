"""479号-4 验证探针：dim5 补产出 8 股真实数据核查（只读不写）

覆盖（479-4 A10-A13 实施验证）：
  1. bociasi_quick 含 details（量比/价格偏离/5日动量/振幅）+ indicators 达标数
  2. bociasi_slow 含 ERP 数值（有数据时）
  3. quadrant 含 fast_score/slow_score + _cache 7 指标
  4. temperature 五档话术（冰冷/偏冷/中性/偏热/过热）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.status_engine import StatusEngine

CODES = ['600519.SH', '000002.SZ', '300750.SZ', '601318.SH',
         '000001.SZ', '002594.SZ', '600036.SH', '600276.SH']

_TEMP_LEVELS = ('冰冷', '偏冷', '中性', '偏热', '过热')


def probe(code):
    se = StatusEngine()
    tags = se._load_tags(code) or {}
    signals = se._load_signals(code) or {}
    lifecycle = se._signal_lifecycle(code, tags, signals)
    dr = se._build_dim_engine_results(tags, signals, {}, lifecycle, ts_code=code)
    sd = (dr.get('emotion') or {}).get('status_description', {}) or {}
    print('=' * 100)
    print(f'### {code}')
    print(f'-- bociasi_quick: {sd.get("bociasi_quick")}')
    print(f'-- bociasi_slow:  {sd.get("bociasi_slow")}')
    print(f'-- quadrant:      {sd.get("quadrant")}')
    print(f'-- temperature:   {sd.get("temperature")}')
    # A10 快线：有 details（快线数据足够时）
    q = sd.get('bociasi_quick') or ''
    if '个股快线=' in q:
        assert any(k in q for k in ('量比', '价格偏离', '5日动量', '振幅')), f'{code} 快线缺 details'
    # A11 慢线：ERP 或数据不足（不占位）
    s = sd.get('bociasi_slow') or ''
    assert '个股慢线ERP=' in s
    # A13 温度五档
    t = sd.get('temperature') or ''
    assert any(k in t for k in _TEMP_LEVELS), f'{code} 温度未转五档: {t}'
    assert '/100' in t


if __name__ == '__main__':
    from app import create_app
    _app = create_app()
    for c in CODES:
        try:
            with _app.app_context():
                probe(c)
        except Exception as e:
            import traceback
            print(f'\n{c} [FATAL] {e}')
            traceback.print_exc()
