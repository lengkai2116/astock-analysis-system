"""479号-3 验证探针：dim3 补产出 8 股真实数据核查（只读不写）

覆盖（479-3 A5/A8 实施验证）：
  1. compute_volume_price_signal 状态机链路：current_pattern（VP 状态名）+ rule（剥离操作建议）+
     背离三字段（divergence_type/confidence/macd_confirmed）能否取出（data_daemon 逻辑前置验证）
  2. dim3 status_description 透传 vp_state_label/vp_rule/divergence 三字段（模拟 RAW 注入 tags）
  3. dim8 volume_price text 消费（先因后果：状态机→量价状态）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.status_engine import StatusEngine
from app.opportunity_atlas.dimensions.dim3_vp_engine import Dim3VPEngine
from app.opportunity_atlas.dimensions.dim8_summary_engine import Dim8SummaryEngine, _compose_dim_text
from app.engine.framework.volume_price_strategy import STATE_SIGNAL_MAP, compute_volume_price_signal

CODES = ['600519.SH', '000002.SZ', '300750.SZ', '601318.SH',
         '000001.SZ', '002594.SZ', '600036.SH', '600276.SH']


def probe(code):
    from app.data import DataManager
    se = StatusEngine()
    tags = se._load_tags(code) or {}
    dm = DataManager()
    ecm = dm.cache
    print('=' * 100)
    print(f'### {code}')

    # ── 1. compute_volume_price_signal 状态机链路 ──
    try:
        df = ecm.get_cached_daily(code) if ecm else None
        vps = compute_volume_price_signal(code, df)
        if vps:
            _pattern = str(vps.get('current_pattern', '') or '')
            _sr = vps.get('status_recognition') or {}
            _vps_state = _pattern.split(' ', 1)[1] if ' ' in _pattern else (_sr.get('state_label') or '')
            _rule_raw = str((STATE_SIGNAL_MAP.get(_vps_state) or {}).get('rule', '') or '')
            _rel = (vps.get('volume_price_detail') or {}).get('量价关系') or {}
            print(f'-- 状态机: current_pattern={_pattern!r} → state={_vps_state!r}')
            print(f'   rule(剥离前)={_rule_raw!r} → rule(剥离后)={_rule_raw.split("，")[0]!r}')
            print(f'   divergence_type={_rel.get("divergence")!r} conf={_rel.get("divergence_confidence")!r} '
                  f'macd={_rel.get("divergence_macd_confirmed")!r}')
            assert _vps_state, '状态机 state 不应为空'
            assert '加仓' not in _rule_raw.split('，')[0], 'SIG-JUD 边界：规则不应含操作建议'
            # 模拟 data_daemon 写入 pre_feat 的新键
            tags2 = dict(tags)
            tags2['vp_state_label'] = _vps_state
            tags2['vp_rule'] = _rule_raw.split('，')[0]
            tags2['divergence_type'] = str(_rel.get('divergence', '') or '')
            tags2['divergence_confidence'] = _rel.get('divergence_confidence')
            tags2['divergence_macd_confirmed'] = bool(_rel.get('divergence_macd_confirmed', False))
        else:
            print('-- 状态机: 无输出（数据不足）')
            tags2 = dict(tags)
    except Exception as e:
        import traceback
        print(f'-- 状态机异常: {e}')
        traceback.print_exc()
        return

    # ── 2. dim3 evaluate 透传 ──
    eng = Dim3VPEngine()
    try:
        df2 = df if df is not None else None
        res = eng.evaluate({}, tags2, data_context={'daily_df': df2} if df2 is not None else None)
        sd = res.get('status_description', {})
    except Exception as e:
        import traceback
        print(f'-- dim3 evaluate 异常: {e}')
        traceback.print_exc()
        return
    print(f'-- dim3 vp_state_label={sd.get("vp_state_label")!r} vp_rule={sd.get("vp_rule")!r}')
    print(f'-- dim3 divergence={sd.get("divergence")!r} (type={sd.get("divergence_type")!r})')
    print(f'-- dim3 volume_energy={sd.get("volume_energy")!r}')
    print(f'-- dim3 pattern={sd.get("pattern")!r}')
    print(f'-- dim3 granville={sd.get("granville")!r}')
    assert sd.get('vp_state_label') == tags2.get('vp_state_label'), 'vp_state_label 未透传'

    # ── 3. dim8 text 消费（先因后果）──
    text = _compose_dim_text('volume_price', {}, sd)
    print(f'-- dim8 volume_price.text={text!r}')


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
