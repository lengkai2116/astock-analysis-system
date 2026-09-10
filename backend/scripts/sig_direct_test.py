"""直接调用 dim1-dim8 引擎（绕过 JSON 序列化），核查真实数据"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
from app.opportunity_atlas.dimensions.dim2_structure_engine import Dim2StructureEngine
from app.opportunity_atlas.dimensions.dim3_vp_engine import Dim3VPEngine
from app.opportunity_atlas.dimensions.dim4_chip_fund_engine import Dim4ChipFundEngine
from app.opportunity_atlas.dimensions.dim5_emotion_engine import Dim5EmotionEngine
from app.opportunity_atlas.dimensions.dim6_risk_engine import Dim6RiskEngine
from app.opportunity_atlas.dimensions.dim7_valuation_engine import Dim7ValuationEngine
from app.opportunity_atlas.dimensions.dim8_summary_engine import Dim8SummaryEngine


def main():
    code = '000001.SZ'
    tags = {}
    signals = {}
    lifecycle = {}

    # dim1 门禁层
    print('=== dim1 门禁层 ===')
    dim1 = Dim1SignalEngine()
    r1 = dim1.evaluate({}, tags, signals, lifecycle, ts_code=code)
    dc = r1.get('data_context', {})
    print('data_context 键数:', len(dc))
    for k, v in dc.items():
        if hasattr(v, 'columns'):
            print(f'  {k}: DataFrame {len(v)}行 {list(v.columns)[:8]}')
        elif isinstance(v, dict):
            print(f'  {k}: dict {list(v.keys())[:8]}')
        else:
            print(f'  {k}: {type(v).__name__}')
    print('status_quality:', json.dumps(r1.get('status_quality', {}), ensure_ascii=False)[:300])

    # dim2-dim7 注入 data_context
    print('\n=== dim2-dim7 ===')
    engines = {
        'structure': Dim2StructureEngine(),
        'volume_price': Dim3VPEngine(),
        'chip_fund': Dim4ChipFundEngine(),
        'emotion': Dim5EmotionEngine(),
        'risk': Dim6RiskEngine(),
        'valuation': Dim7ValuationEngine(),
    }
    dim_results = {'signal': r1}
    for name, eng in engines.items():
        try:
            r = eng.evaluate({}, tags, signals, lifecycle, data_context=dc)
            dim_results[name] = r
            sd = r.get('status_description', {})
            jg = r.get('judgment', {})
            print(f'  [{name}] light={jg.get("overall_light")} dir={jg.get("overall_direction")} '
                  f'plain={sd.get("plain","")[:60]}')
        except Exception as e:
            print(f'  [{name}] ERROR: {e}')
            import traceback; traceback.print_exc()

    # dim8
    print('\n=== dim8 ===')
    dim8 = Dim8SummaryEngine()
    r8 = dim8.evaluate({}, tags, lifecycle={'dim_results': dim_results})
    sd8 = r8.get('status_description', {})
    print('status_bar:', sd8.get('status_bar'))
    print('consensus_rate:', sd8.get('consensus_rate'))
    print('conflicts:', sd8.get('conflicts'))
    print('text:', sd8.get('text', '')[:200])


if __name__ == '__main__':
    main()
