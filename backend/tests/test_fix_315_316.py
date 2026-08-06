"""315/316 号方案核查问题修复回归测试

覆盖修复点：
  1. F2 行业中性化基准口径不一致（HIGH）——基准应与查询侧同口径（减行业均值）
  2. P3 动态加权未参与共识统计（HIGH）——加权应影响 direction/rate
  3. 质量修正重复查询 + QUALITY_ADJUST 常量（MEDIUM）
  4. P5 形态映射缺口——Detector 预涨/预跌/黑马形态必须全覆盖
  5. 小缺陷：死代码/非单调分支/首仓公式/未用参数/残留常量
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

import inspect
import re

import pytest


# ══════════════════════════════════════════════════════════
# 1. F2 行业中性化基准口径（HIGH）
# ══════════════════════════════════════════════════════════

class _FakeECM:
    """模拟 ECM：只提供 _query_df（返回上一轮 composite_rating 标签行）"""

    def __init__(self, rows):
        import pandas as pd
        self._rows = pd.DataFrame(rows)

    def _query_df(self, sql):
        return self._rows


def test_f2_percentile_baseline_is_neutralized(monkeypatch):
    """基准必须用中性化后的 composite（减行业均值）构建，与 compute_tags 查询侧口径一致

    构造 60 只银行（0.4~0.99，行业均值≈0.695）+ 60 只科技（-0.3~0.113，行业均值≈-0.09）。
    银行最高 composite=0.99（全市场原始最高）。查询侧传入 0.99-0.695=0.295：
      修复前：基准为原始 composite 分布 → 0.295 分位≈0.5（银行 0.4+ 全在其上）→ 非低估；
      修复后：基准为中性化分布（银行中性化最高 0.295）→ 0.295 分位≈0.99（>0.95 低估）。
    """
    from app.opportunity_atlas.valuation_estimator import ValuationEngine

    bank_rows = [{'ts_code': f'60{i:04d}.SH', 'tag_value': 0.4 + i * 0.01} for i in range(60)]
    tech_rows = [{'ts_code': f'30{i:04d}.SZ', 'tag_value': -0.3 + i * 0.007} for i in range(60)]
    rows = bank_rows + tech_rows

    # 最高 composite 0.99 的银行股
    top_bank = max(bank_rows, key=lambda r: r['tag_value'])
    top_val = top_bank['tag_value']

    # 行业映射：60xxxx → 银行，30xxxx → 电子（科技）
    def _fake_batch(codes):
        return {c: ('银行' if c.startswith('60') else '电子') for c in codes}

    monkeypatch.setattr(
        'app.data.DataManager.get_stock_industry_batch',
        staticmethod(_fake_batch),
    )

    engine = ValuationEngine()
    engine.build_composite_percentile(_FakeECM(rows))

    assert engine._comp_percentile is not None, "基准应构建成功"

    # 银行行业均值 ≈ 0.695；该股中性化值 = 0.99 - 0.695 ≈ 0.295（行业内最高）
    # 注意：_category 将 '银行'→'金融'、'电子'→'科技'（INDUSTRY_CATEGORY 映射）
    bank_mean = engine._industry_mean.get('金融')
    assert bank_mean is not None, "银行行业均值应已构建"
    neutralized = top_val - bank_mean
    pct = engine._comp_percentile(neutralized)

    # 修复前：原始分布中 0.295 分位 ≈0.5（失败）；修复后：中性化分布中 ≈0.99（>0.95）
    assert pct > 0.95, f"行业最高 composite 股中性化后应判低估分位 >0.95，实际 {pct:.3f}"


# ══════════════════════════════════════════════════════════
# 2. P3 动态加权参与共识统计（HIGH）
# ══════════════════════════════════════════════════════════

@pytest.fixture(scope='module')
def validator():
    from app.opportunity_atlas.cross_validate import L4CrossValidator
    return L4CrossValidator()


def _weighted_4v4_tags() -> dict:
    """4 多 4 空（含 3 个动量看多票）——climax 下动量×0.6 应使方向翻转为看空"""
    return {
        'main_force_phase': 'building',          # +1 非动量
        'trend_alignment': 'up_aligned',         # +1 动量（MOMENTUM_TAGS）
        'ma_alignment': 'bullish',               # +1 动量
        'buy_sell_point': 'second_buy',          # +1 动量
        'fund_flow': '5d_outflow',               # -1
        'price_position': 'high_zone',           # -1
        'catalyst_event': 'regulatory',          # -1
        'fina_health': 'fail',                   # -1
    }


def test_p3_weighted_votes_affect_direction(validator):
    """climax 情绪下动量看多票 ×0.6 应参与共识统计——4多4空原始打平，加权后转看空

    修复前：bullish/bearish 用 raw_vote 计数 → direction='neutral'（tie）；
    修复后：加权多头 = 1 + 0.6*3 = 2.8 < 空头 4 → direction='bearish'。
    """
    tags = _weighted_4v4_tags()
    _, adjusted = validator._apply_sentiment_weight('climax', tags)

    # 前置：确认动量票确实被降权（环境层已生效）
    assert adjusted['trend_alignment'] == 0.6, "动量票 climax 应 ×0.6"

    consensus, _ = validator._compute_consensus(tags, adjusted)
    assert consensus['direction'] == 'bearish', \
        f"加权后动量看多 2.8 < 看空 4 应转 bearish，实际 {consensus['direction']}"

    # 无情绪（无加权）时仍应打平（回归：不破坏 tie 语义）
    consensus_raw, _ = validator._compute_consensus(tags, {})
    assert consensus_raw['direction'] == 'neutral'
    assert consensus_raw['tie'] is True


# ══════════════════════════════════════════════════════════
# 3. 质量修正复用 df_fina + QUALITY_ADJUST 常量（MEDIUM）
# ══════════════════════════════════════════════════════════

@pytest.fixture(scope='module')
def app_ctx():
    from app import create_app
    app = create_app()
    with app.app_context():
        yield app


def test_quality_adjust_constant_exists():
    """方案要求阈值可配置（QUALITY_ADJUST 常量）——应存在且含 fail 惩罚键"""
    from app.opportunity_atlas import valuation_estimator as ve
    assert hasattr(ve, 'QUALITY_ADJUST'), "QUALITY_ADJUST 常量缺失（修复前为硬编码）"
    assert 'fail_penalty' in ve.QUALITY_ADJUST
    assert ve.QUALITY_ADJUST['fail_penalty'] == 0.5


def test_fina_indicator_queried_once(app_ctx, monkeypatch):
    """compute_tags 只应查询一次 fina_indicator（复用 _fina_health 的 df_fina）

    修复前：_fina_health 内部查一次 + 质量修正 L674 再查一次 = 2 次。
    修复后：质量修正复用 _fina_health 返回的 df_fina = 1 次。
    """
    from app.data import DataManager
    from app.opportunity_atlas.valuation_estimator import ValuationEngine

    calls = {'n': 0}
    orig = DataManager.get_cached_fina_indicator

    def _counting(self, ts_code):
        calls['n'] += 1
        return orig(self, ts_code)

    monkeypatch.setattr(DataManager, 'get_cached_fina_indicator', _counting)

    engine = ValuationEngine()
    engine.compute_tags('600519.SH')  # fina_health=pass 的健康股（触发质量修正分支）

    assert calls['n'] == 1, f"fina_indicator 应只查询 1 次（复用 df_fina），实际 {calls['n']} 次"


# ══════════════════════════════════════════════════════════
# 4. P5 形态映射缺口（MEDIUM）
# ══════════════════════════════════════════════════════════

def test_pattern_signal_mapping_covers_detector():
    """EnhancedPatternDetector 所有预涨/预跌/黑马形态必须映射到 VOTE_MAP

    修复前：放量下跌恐慌出逃/平台破位箱体下沿跌破（预跌）等无映射 → 投票中性（否决语义丢失）。
    """
    from app.opportunity_atlas.cross_validate import VOTE_MAP

    vps_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'engine',
                            'framework', 'volume_price_strategy.py')
    with open(vps_path, encoding='utf-8') as f:
        src = f.read()

    # 提取 detect_all 中 ('形态名(预涨/预跌/黑马/持续/待变盘)', '_is_xxx') 列表
    seg = src[src.index('def detect_all'):src.index('        for name, method_name in checks:')]
    names = set(re.findall(r"\(\s*'([^']+?\([^)]*\))'\s*,\s*'_is_\w+'\s*\)", seg))

    direction_names = {n.split('(')[0] for n in names}
    assert direction_names, "应从检测器源码提取到形态名"

    missing = {n for n in direction_names if n not in VOTE_MAP['pattern_signal']}
    assert not missing, f"Detector 方向性形态未映射到 VOTE_MAP: {sorted(missing)}"


# ══════════════════════════════════════════════════════════
# 5. 小缺陷（LOW）
# ══════════════════════════════════════════════════════════

def test_gate_denied_dead_code_removed(validator):
    """316 P1 门禁后移后 _build_gate_denied 无调用——应删除"""
    assert not hasattr(validator, '_build_gate_denied'), "死代码 _build_gate_denied 应删除"


def test_bearish_action_monotonic(validator):
    """看空共识动作应随 rate 单调（0.5-0.65 应比 0.35-0.5 更强）

    修复前：0.5-0.65→hold、0.35-0.5→reduce（非单调）；修复后 0.5-0.65→reduce。
    """
    def _consensus(rate):
        return {'consensus_rate': rate, 'direction': 'bearish'}

    action_hi, _ = validator._map_consensus_to_action(_consensus(0.6), total_active=8)
    action_lo, _ = validator._map_consensus_to_action(_consensus(0.4), total_active=8)

    strength = {'clear': 3, 'reduce': 2, 'hold': 1, 'build_position': 0}
    assert strength[action_hi] > strength[action_lo], \
        f"看空共识 0.6({action_hi}) 应比 0.4({action_lo}) 动作更强（单调）"


def test_first_batch_ratio_scales_with_risk(validator):
    """首仓比例应随 max_position_ratio（风险等级）缩放，40-60% 区间

    修复前：公式 0.4*max_ratio/max(max_ratio,0.1)*100 恒为 40%（冗余）。
    修复后：max_ratio=0.6 → 首仓 60%，max_ratio=0.1 → 首仓 43%。
    """
    import pandas as pd

    n = 30
    df = pd.DataFrame({
        'close': [10 + i * 0.1 for i in range(n)],
        'high': [10.5 + i * 0.1 for i in range(n)],
        'low': [9.5 + i * 0.1 for i in range(n)],
    })

    tags = {'pattern_signal': 'none'}
    gate = {'valuation': 'none', 'hard_risks': [], 'soft_risks': []}

    plan_hi, *_ = validator._build_trade_plan('000001.SZ', tags, df, 'build_position', 0.6, gate)
    plan_lo, *_ = validator._build_trade_plan('000001.SZ', tags, df, 'build_position', 0.1, gate)

    assert plan_hi and plan_lo, "建仓类建议应产出分批入场计划"
    first_hi = int(plan_hi[0]['ratio'].replace('%', ''))
    first_lo = int(plan_lo[0]['ratio'].replace('%', ''))
    assert first_hi == 60, f"max_ratio=0.6 首仓应为 60%，实际 {first_hi}%（修复前恒 40）"
    assert first_lo == 43, f"max_ratio=0.1 首仓应为 43%，实际 {first_lo}%"


def test_operation_advice_signature(validator):
    """_build_operation_advice 不应有未使用的 signal_strength 参数"""
    sig = inspect.signature(validator._build_operation_advice)
    assert 'signal_strength' not in sig.parameters, "未用参数 signal_strength 应删除"


def test_short_term_tags_no_sentiment():
    """sentiment_phase 已移出 VOTE_MAP，SHORT_TERM_TAGS 不应残留"""
    from app.opportunity_atlas.cross_validate import SHORT_TERM_TAGS
    assert 'sentiment_phase' not in SHORT_TERM_TAGS, "SHORT_TERM_TAGS 应删除 sentiment_phase 残留"
