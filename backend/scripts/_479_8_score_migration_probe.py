"""479号-8 验证探针：评分键全链迁 JUD 后 8 股真实数据核查（只读不写）

覆盖（479-8 D1 固化验证）：
  1. 引擎 status_description 保留评分键产出（structure_health_score / potential_score/
     potential_strength / health_score / pattern_score / crowding_score 按维存在）
  2. dim8 五公开段 text / evidence / judgment 均不含 6 个评分键
  3. JUD 消费链：dim_adapter.convert_to_factors 读 structure 维 strength
     （structure_health_score 归一贡献）取得值 > 0
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.opportunity_atlas.status_engine import StatusEngine
from app.opportunity_atlas.dim_adapter import convert_to_factors
from app.opportunity_atlas.dimensions.dim8_summary_engine import (
    Dim8SummaryEngine, _valuation_sentence,
)

CODES = ['600519.SH', '000002.SZ', '300750.SZ', '601318.SH',
         '000001.SZ', '002594.SZ', '600036.SH', '600276.SH']

PUBLIC_KEYS = ('structure', 'volume_price', 'fund_chip', 'emotion', 'risk')
SCORE_KEYS = ['structure_health_score', 'health_score', 'pattern_score',
              'crowding_score', 'potential_score', 'potential_strength']


def probe(code):
    se = StatusEngine()
    tags = se._load_tags(code) or {}
    signals = se._load_signals(code) or {}
    lifecycle = se._signal_lifecycle(code, tags, signals)
    dim_results = se._build_dim_engine_results(tags, signals, {}, lifecycle, ts_code=code)

    print(f'=== {code} ===')
    issues = []

    # 引擎侧保留评分键（按维存在性）
    _sd = dim_results.get('structure', {}).get('status_description', {}) or {}
    if _sd.get('structure_health_score') is not None:
        print(f'  引擎保留: structure_health_score={_sd["structure_health_score"]}')
    _vsd = dim_results.get('volume_price', {}).get('status_description', {}) or {}
    if _vsd.get('health_score') is not None:
        print(f'  引擎保留: volume_price.health_score={_vsd["health_score"]}')
    _cfd = dim_results.get('chip_fund', {}).get('status_description', {}) or {}
    if _cfd.get('crowding_score') is not None:
        print(f'  引擎保留: chip_fund.crowding_score={_cfd["crowding_score"]}')
    _valsd = dim_results.get('valuation', {}).get('status_description', {}) or {}
    if _valsd.get('potential_score') is not None:
        print(f'  引擎保留: potential_score={_valsd["potential_score"]}')

    # dim8 段剥离核查
    report = Dim8SummaryEngine().build_seven_dim_report(dim_results, tags=tags, ts_code=code)
    if report:
        for key in PUBLIC_KEYS:
            seg = report.get(key)
            if not seg:
                continue
            t = seg.get('text', '')
            jg = seg.get('judgment', {})
            ev = ' '.join(seg.get('evidence', []))
            for k in SCORE_KEYS:
                if k in t or k in ev or k in jg:
                    issues.append(f'{key} 残留评分键 {k}')
            # judgment 仅 meta 键检查
            extra = [k for k in jg if k not in
                     ('overall_light', 'overall_direction', 'continuous_value')]
            if extra:
                issues.append(f'{key} judgment 非meta键: {extra}')
        # valuation 不产段
        if report.get('valuation') is not None:
            issues.append('valuation 不应产出段')
        # _valuation_sentence 不含评分
        vs = _valuation_sentence(dim_results)
        for k in ('potential_score', 'potential_strength'):
            if k in vs:
                issues.append(f'_valuation_sentence 残留 {k}')

    # JUD 消费链：structure strength 读取得值
    try:
        factors = convert_to_factors(dim_results, tags)
        struct_str = factors.get('structure', {}).get('strength', 0.0)
        print(f'  JUD消费: structure factor strength={struct_str:.4f}')
        if struct_str <= 0:
            issues.append('JUD structure strength 未消费评估评分')
    except Exception as e:
        issues.append(f'JUD convert_to_factors 异常: {e}')

    if issues:
        print(f'  ⚠️ 问题: {"；".join(issues)}')
        return False
    print(f'  OK（无评分键泄漏 dim8 / JUD消费链正常）')
    return True


if __name__ == '__main__':
    from app import create_app
    _app = create_app()
    allok = True
    for c in CODES:
        try:
            with _app.app_context():
                allok = probe(c) and allok
        except Exception as e:
            import traceback
            print(f'\n{c} [FATAL] {e}')
            traceback.print_exc()
            allok = False
    print('\nALL_OK' if allok else '\nHAS_FATAL')
