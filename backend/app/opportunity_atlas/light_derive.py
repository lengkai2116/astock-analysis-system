"""439-A-1：灯色派生 SSOT（Single Source of Truth）

**定位（用户 2026-09-27 拍板 Q-439A-1 ①）**：
- **灯＝环境风险**（本条职责）：仅由 SIG 的**分析结论**（status/state）派生，纯函数映射，不含判定/干预；
- **操作含义**由 `judgment.overall_direction`（逆势口径，见 `dim_adapter._EMOTION_DIRECTION`）表达，
  与本模块的灯色**分工明确**（如「冰点」：灯=🔴 环境风险，方向=+1 操作机会）。

**为什么独立成模块**：439-A 要求 SIG 各维引擎**不再自产灯色**（判定类输出离场），灯色改为
「分析结论 → 灯色」的**单一规则表**派生，同时供 JUD 判定层（dim8 共识/冲突、cross_validate、
status_engine dims）与展示层（`seven_dim_json` 段色/emoji）调用。

**派生表**（与 2026-09-27 迁移前各维自产灯**逐股等价**，见 439-A §六/§10.1）：
| 维 | 输入（分析结论） | 规则 |
|---|---|---|
| structure | `judgment.structure` | 上升🟢 盘整🟡 下降🔴 |
| volume_price | `judgment.state`（五态） | 强健康/健康🟢 中性🟡 背离/严重背离🔴 |
| chip_fund | `judgment.phase`（Q-439A-5：用 phase 非 direction） | building/lifting🟢 distributing🔴 其余🟡 |
| emotion（市场） | `sd.market_phase` + `sd.bociasi_quadrant` | ferment🟢 ice/climax🔴 其余🟡；**四象限覆盖**（HH:🟢→🔴 / LL:🔴→🟢 / HL:🟢→🟡 / LH:🔴→🟡） |
| emotion（板块） | `sd.sector_heat` | top_10/top_20🟢 其余🟡 |
| emotion（个股） | **dim3 `judgment.state`**（Q-439A-3 跨维去重，主源=dim3 量价） | 严重背离🔴 健康🟢 其余🟡 |
| emotion（整体） | 三层聚合 | 任一🔴→🔴；≥2🟢→🟢；否则🟡 |
| risk | `judgment.level`（或 risk_sources 高源计数） | 高/极高🔴 中🟡 低🟢 |
| valuation | `judgment.valuation_level.value` | extreme_low/low🟢 fair🟡 high/extreme_high🔴 |
| signal | `judgment.attribute.code` | right_*/trend_running🟢 left_probing/consolidating/neutral🟡 risk_warning🔴 |
| 无数据 | — | 🟡（**语义＝「数据缺失」**，Q-439A-2；非判定） |
"""
from __future__ import annotations

from typing import Iterable, Optional

# 无数据色（Q-439A-2：保留，语义为「数据缺失」而非判定）
DATA_MISSING = 'yellow'

STRUCTURE = {'上升': 'green', '盘整': 'yellow', '下降': 'red'}

VOLUME_PRICE = {'强健康': 'green', '健康': 'green', '中性': 'yellow',
                '背离': 'red', '严重背离': 'red'}

CHIP_FUND = {'building': 'green', 'lifting': 'green', 'distributing': 'red'}
# 其余（washing/support/unknown/''）→ 无数据色

EMOTION_MARKET = {'ferment': 'green', 'ice': 'red', 'climax': 'red'}
# 其余（sprout/ebb/regression/neutral/''）→ 无数据色

SECTOR_HEAT = {'top_10': 'green', 'top_20': 'green'}

VALUATION = {'extreme_low': 'green', 'low': 'green', 'fair': 'yellow',
             'high': 'red', 'extreme_high': 'red'}

SIGNAL_ATTR = {'right_confirmed': 'green', 'right_emerging': 'green',
               'trend_running': 'green', 'left_probing': 'yellow',
               'consolidating': 'yellow', 'neutral': 'yellow',
               'risk_warning': 'red'}

RISK_LEVEL = {'低': 'green', '中': 'yellow', '高': 'red', '极高': 'red'}

# dim 名 → 纯映射表（不含需要额外输入的两处：emotion 市场需 quadrant、risk 需高源计数）
_SIMPLE = {
    'structure': STRUCTURE,
    'volume_price': VOLUME_PRICE,
    'chip_fund': CHIP_FUND,
    'sector': SECTOR_HEAT,
    'valuation': VALUATION,
    'signal': SIGNAL_ATTR,
    'risk': RISK_LEVEL,
}

# dim 名别名（dim8 SEVEN_DIM_SPEC 输出键 → 引擎键）
_ALIAS = {'fund_chip': 'chip_fund', 'vp': 'volume_price'}


def derive_light(dim: str, state) -> str:
    """纯映射：单维「状态 → 灯色」。取不到 → DATA_MISSING（数据缺失）。"""
    dim = _ALIAS.get(dim, dim)
    table = _SIMPLE.get(dim)
    if not table:
        return DATA_MISSING
    return table.get(str(state or ''), DATA_MISSING)


def emotion_market_light(market_phase, quadrant=None) -> str:
    """市场情绪灯：PHASE_MAP 口径 + BOCIASI 四象限覆盖（等价迁移前 dim5 §2b 逻辑）。"""
    light = EMOTION_MARKET.get(str(market_phase or ''), DATA_MISSING)
    q = str(quadrant or '')
    if q == 'HH' and light == 'green':
        return 'red'
    if q == 'LL' and light == 'red':
        return 'green'
    if q == 'HL' and light == 'green':
        return 'yellow'
    if q == 'LH' and light == 'red':
        return 'yellow'
    return light


def emotion_stock_light(vp_state) -> str:
    """个股情绪灯：主源＝dim3 量价状态（Q-439A-3 跨维去重；等价迁移前 dim5 §2 的
    「严重背离→red / 健康→green / 其余→yellow」）。"""
    s = str(vp_state or '')
    if s in ('严重背离',):
        return 'red'
    if s in ('健康', '强健康'):
        return 'green'
    return DATA_MISSING


def aggregate_lights(lights: Iterable[str]) -> str:
    """三层聚合（等价迁移前 dim5 `_overall_light`）：任一 red→red；≥2 green→green；否则黄。"""
    ls = [str(x) for x in lights if x]
    if 'red' in ls:
        return 'red'
    if ls.count('green') >= 2:
        return 'green'
    return DATA_MISSING


# 汇总灯阈值（491-J6：口径 SSOT——原内联于 dim8_summary_engine.evaluate）
SUMMARY_LIGHT_GREEN = 0.6
SUMMARY_LIGHT_RED = 0.3


def summary_light(consensus_rate) -> str:
    """汇总（summary 段）灯——SSOT 阈值规则：加权共识率 → 灯。

    ≥0.6 → green；<0.3 → red；否则 yellow（＝迁移前 `dim8_summary_engine.evaluate`
    的内联口径，逐值等价）。共识率由 dim8 聚合（各维派生灯 × DIM_WEIGHTS × 置信度）后传入，
    阈值规则本身归本模块，使「灯」的判定口径集中一处（491-J6）。
    """
    try:
        cr = float(consensus_rate)
    except (TypeError, ValueError):
        return DATA_MISSING
    # 507批次8：NaN/inf 视为数据异常 → 缺失灯（原 NaN→yellow 落中性、inf→green 误判）
    import math
    if math.isnan(cr) or math.isinf(cr):
        return DATA_MISSING
    if cr >= SUMMARY_LIGHT_GREEN:
        return 'green'
    if cr < SUMMARY_LIGHT_RED:
        return 'red'
    return 'yellow'


def _risk_source_is_high(s) -> bool:
    """风险 5 源条目是否「高」——兼容 dim6 引擎产出（475 P1：'名称：等级' 字符串列表）
    与 dict 形态（{'name','level'}，历史/测试构造）。
    507批次8（Q4）：dict 分支补 'risk_level' 键回退——对齐 risk_light 的
    `judgment.risk_level or level` 读法（live 字符串列表路径不变）。"""
    if isinstance(s, dict):
        return str(s.get('risk_level') or s.get('level')) == '高'
    return str(s).rsplit('：', 1)[-1].strip() == '高'


def risk_light(dim_results: dict) -> str:
    """风险灯：优先 judgment.level（高/极高🔴 中🟡 低🟢）；
    缺失时按 risk_sources 中 level=='高' 的计数（≥2🔴 ==1🟡 0🟢）派生。"""
    r = (dim_results or {}).get('risk') or {}
    judg = r.get('judgment') or {}
    sd = r.get('status_description') or {}
    level = str(judg.get('risk_level') or judg.get('level') or '')
    if level in RISK_LEVEL:
        return RISK_LEVEL[level]
    sources = sd.get('risk_sources')
    if isinstance(sources, list):
        high = sum(1 for s in sources if _risk_source_is_high(s))
        return 'red' if high >= 2 else ('yellow' if high == 1 else 'green')
    return DATA_MISSING


def signal_light(dim_results: dict) -> str:
    """信号维灯：等价迁移前 `signal_analyzer._overall_light`
    （属性灯 + 强度**等级** + 衰减**状态** 三源聚合）。

    注意键位（与引擎一致，勿用 score/decay_status 误读）：
      `judgment.strength.level` ∈ 极强/强/中等/弱/极弱；
      `judgment.maintenance.status` ∈ healthy/fading/…
    """
    sig = (dim_results or {}).get('signal') or {}
    judg = sig.get('judgment') or {}
    attr = judg.get('attribute') or {}
    strength = judg.get('strength') or {}
    maint = judg.get('maintenance') or {}
    attr_light = SIGNAL_ATTR.get(str(attr.get('code') or ''), DATA_MISSING)
    level = str(strength.get('level') or '')
    s_light = ('green' if level in ('极强', '强')
               else ('yellow' if level == '中等' else 'red')) if level else DATA_MISSING
    decay = str(maint.get('status') or '')
    d_light = ('green' if decay == 'healthy'
               else ('yellow' if decay == 'fading' else 'red')) if decay else DATA_MISSING
    return aggregate_lights([attr_light, s_light, d_light])


def dim_light(dim_results: dict, dim_name: str) -> str:
    """主入口：从维度引擎输出派生该维灯色（替代消费侧读 `judgment.overall_light`）。

    支持 dim_name ∈ structure / volume_price / chip_fund(fund_chip) / emotion /
    sector / valuation / signal / risk。
    """
    dim = _ALIAS.get(dim_name, dim_name)
    dr = dim_results or {}

    if dim == 'emotion':
        # 整体灯＝三层聚合（market/sector/stock），等价迁移前 dim5 overall_light
        emo_sd = (dr.get('emotion') or {}).get('status_description') or {}
        vp_state = _vp_state(dr)
        return aggregate_lights([
            emotion_market_light(emo_sd.get('market_phase'), emo_sd.get('bociasi_quadrant')),
            derive_light('sector', emo_sd.get('sector_heat')),
            emotion_stock_light(vp_state),
        ])
    if dim == 'risk':
        return risk_light(dr)
    if dim == 'signal':
        return signal_light(dr)

    r = dr.get(dim)
    if not isinstance(r, dict):
        return DATA_MISSING
    judg = r.get('judgment') or {}
    if dim == 'structure':
        return derive_light('structure', judg.get('structure'))
    if dim == 'volume_price':
        return derive_light('volume_price', judg.get('state'))
    if dim == 'chip_fund':
        return derive_light('chip_fund', judg.get('phase'))
    if dim == 'valuation':
        lv = judg.get('valuation_level') or {}
        return derive_light('valuation', lv.get('value') if isinstance(lv, dict) else None)
    return DATA_MISSING


def _vp_state(dim_results: dict) -> Optional[str]:
    """dim3 量价状态（judgment.state，兜底 sd.vp_state）"""
    vp = (dim_results or {}).get('volume_price') or {}
    judg = vp.get('judgment') or {}
    sd = vp.get('status_description') or {}
    return judg.get('state') or sd.get('vp_state') or None
