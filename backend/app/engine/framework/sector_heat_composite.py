"""532号 板块热度五维合成引擎（纯函数，不读写 DB）。

输入：31 个申万一级行业的原始指标（D1~D5）+ 配置。
输出：分维分值、综合质量分、阶段、过热/背离标签、排名与判定依据。

口径约定：
- `up_ratio` / `rps_high_ratio` 为 0~1 比例；`limit_up_ratio` / `zhaban_ratio` /
  `amount_share` / `fd_amount_ratio` 为百分数（0~100）。
- `dim_sentiment` 存“拥挤度”（越高越拥挤）；综合分用 `100 - 拥挤度` 作为情绪健康度。
- 缺失维度不按 0 处理：分维为 None，综合分对可用维度重新归一，并打 `coverage`。
"""

from __future__ import annotations

import bisect
import math
from typing import Any

# 申万一级指数代码 → 行业名（SW2021，31 类）
SW_INDEX_TO_INDUSTRY = {
    '801010.SI': '农林牧渔',
    '801030.SI': '基础化工',
    '801040.SI': '钢铁',
    '801050.SI': '有色金属',
    '801080.SI': '电子',
    '801110.SI': '家用电器',
    '801120.SI': '食品饮料',
    '801130.SI': '纺织服饰',
    '801140.SI': '轻工制造',
    '801150.SI': '医药生物',
    '801160.SI': '公用事业',
    '801170.SI': '交通运输',
    '801180.SI': '房地产',
    '801200.SI': '商贸零售',
    '801210.SI': '社会服务',
    '801230.SI': '综合',
    '801710.SI': '建筑材料',
    '801720.SI': '建筑装饰',
    '801730.SI': '电力设备',
    '801740.SI': '国防军工',
    '801750.SI': '计算机',
    '801760.SI': '传媒',
    '801770.SI': '通信',
    '801780.SI': '银行',
    '801790.SI': '非银金融',
    '801880.SI': '汽车',
    '801890.SI': '机械设备',
    '801950.SI': '煤炭',
    '801960.SI': '石油石化',
    '801970.SI': '环保',
    '801980.SI': '美容护理',
}

DEFAULT_CONFIG: dict[str, Any] = {
    'version': '532.1',
    'weights': {'fund': 0.30, 'rs': 0.25, 'breadth': 0.25, 'sentiment': 0.20},
    'vp_adjust': 0.20,
    'thresholds': {
        'rps_strong': 80.0,
        'rps_very_strong': 90.0,
        'limit_up_ratio': 5.0,
        'zhaban_ratio': 40.0,
        'amount_share': 15.0,
        'rps120_overheat': 95.0,
        'up_ratio_main': 0.60,
        'up_ratio_weak': 0.50,
        'rps_cold': 30.0,
        'vol_cold': 0.8,
        'crowding_overheat': 90.0,
    },
    'healthy_vp': ['放量突破', '缩量回踩', '温和放量'],
    'enable': {'northbound': False, 'etf': True},
}


def _num(v) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def percentile_rank(values: list[float | None]) -> list[float | None]:
    """横截面百分位（0~100，最高=100，最低=0）；None 保持 None，并列取平均秩。"""
    valid = [(i, _num(v)) for i, v in enumerate(values)]
    valid = [(i, v) for i, v in valid if v is not None]
    out: list[float | None] = [None] * len(values)
    n = len(valid)
    if n == 0:
        return out
    if n == 1:
        out[valid[0][0]] = 50.0
        return out
    sorted_vals = sorted(v for _, v in valid)
    for i, v in valid:
        lo = bisect.bisect_left(sorted_vals, v)
        hi = bisect.bisect_right(sorted_vals, v)
        rank0 = (lo + hi - 1) / 2.0
        out[i] = round(rank0 / (n - 1) * 100.0, 2)
    return out


def _weighted_available(pairs: list[tuple[float | None, float]]) -> float | None:
    num = den = 0.0
    for v, w in pairs:
        if v is None:
            continue
        num += v * w
        den += w
    return round(num / den, 2) if den else None


def _dim_percentile(rows: list[dict], key_weights: list[tuple[str, float]]) -> list[float | None]:
    pcts = {k: percentile_rank([r.get(k) for r in rows]) for k, _ in key_weights}
    out: list[float | None] = []
    for i in range(len(rows)):
        out.append(_weighted_available([(pcts[k][i], w) for k, w in key_weights]))
    return out


def compute(rows: list[dict], cfg: dict | None = None) -> list[dict]:
    """计算五维分、综合质量分、阶段与排名；返回新的 row 列表。"""
    cfg = cfg or DEFAULT_CONFIG
    th = {**DEFAULT_CONFIG['thresholds'], **(cfg.get('thresholds') or {})}
    weights = {**DEFAULT_CONFIG['weights'], **(cfg.get('weights') or {})}
    vp_adjust = float(cfg.get('vp_adjust', DEFAULT_CONFIG['vp_adjust']))
    healthy_vp = set(cfg.get('healthy_vp', DEFAULT_CONFIG['healthy_vp']))
    north_enabled = bool((cfg.get('enable') or {}).get('northbound', False))

    if not rows:
        return []

    # D1 相对强弱：RPS 已是 0~100 分位，不再二次分位；共振折算 0~100
    dim_rs: list[float | None] = []
    for r in rows:
        res = _num(r.get('rps_resonance'))
        dim_rs.append(_weighted_available([
            (_num(r.get('rps_20')), 0.35),
            (_num(r.get('rps_60')), 0.30),
            (_num(r.get('rps_120')), 0.20),
            (res / 3 * 100 if res is not None else None, 0.15),
        ]))

    # D2 资金：主力占比 / 融资增速 / ETF 份额变化（北向仅背景，不参与）
    dim_fund = _dim_percentile(rows, [
        ('fund_ratio', 0.55),
        ('margin_growth_5d', 0.25),
        ('etf_share_chg_5d', 0.20),
    ])

    # D3 量价：直接用预计算的 vp_score（0~100）
    dim_vp = [_num(r.get('vp_score')) for r in rows]

    # D4 情绪拥挤：高分位=更拥挤；健康度 = 100 - 拥挤度
    dim_crowding = _dim_percentile(rows, [
        ('limit_up_ratio', 0.25),
        ('zhaban_ratio', 0.25),
        ('max_board_height', 0.15),
        ('amount_share', 0.20),
        ('fd_amount_ratio', 0.15),
    ])
    dim_sentiment_health = [None if c is None else round(100 - c, 2) for c in dim_crowding]

    # D5 内部广度
    dim_breadth = _dim_percentile(rows, [
        ('up_ratio', 0.45),
        ('med_vs_mean', 0.25),
        ('rps_high_ratio', 0.30),
    ])

    out: list[dict] = []
    for i, r in enumerate(rows):
        dims = {
            'fund': dim_fund[i],
            'rs': dim_rs[i],
            'breadth': dim_breadth[i],
            'sentiment': dim_sentiment_health[i],
        }
        base = _weighted_available([
            (dims[k], float(weights.get(k, 0))) for k in ('fund', 'rs', 'breadth', 'sentiment')
        ])
        vp = dim_vp[i]
        adj = 0.0 if vp is None else (vp - 50.0) * vp_adjust
        quality = _clamp((base if base is not None else 50.0) + adj)

        res = _num(r.get('rps_resonance')) or 0.0
        rps20 = _num(r.get('rps_20'))
        rps60 = _num(r.get('rps_60'))
        rps120 = _num(r.get('rps_120'))
        up = _num(r.get('up_ratio'))
        fund_ratio = _num(r.get('fund_ratio'))
        vp_state = str(r.get('vp_state') or '')
        limit_up = _num(r.get('limit_up_ratio'))
        zhaban = _num(r.get('zhaban_ratio'))
        amount_share = _num(r.get('amount_share'))
        crowding = dim_crowding[i]
        vol_ratio = _num(r.get('vol_ratio_5d'))

        # 阶段判定（过热 > 主线 > 脉冲 > 冷门 > 中性）
        overheat = (
            (limit_up is not None and zhaban is not None
             and limit_up >= th['limit_up_ratio'] and zhaban >= th['zhaban_ratio'])
            or (amount_share is not None and rps120 is not None
                and amount_share >= th['amount_share'] and rps120 >= th['rps120_overheat'])
            or (crowding is not None and crowding >= th['crowding_overheat'])
        )
        mainline = (
            res >= 2 and up is not None and up >= th['up_ratio_main']
            and fund_ratio is not None and fund_ratio > 0
            and vp_state in healthy_vp
        )
        pulse = (
            rps20 is not None and rps20 >= th['rps_very_strong']
            and ((rps60 is not None and rps60 < 60)
                 or (up is not None and up < th['up_ratio_weak']))
        )
        cold = (
            rps20 is not None and rps20 < th['rps_cold']
            and vol_ratio is not None and vol_ratio < th['vol_cold']
            and fund_ratio is not None and fund_ratio > 0
        )
        if overheat:
            stage = 'overheat'
        elif mainline:
            stage = 'mainline'
        elif pulse:
            stage = 'pulse'
        elif cold:
            stage = 'cold'
        else:
            stage = 'neutral'

        index_pct = _num(r.get('index_pct'))
        flags = []
        if overheat:
            flags.append('overheat')
        if (index_pct is not None and up is not None
                and ((index_pct > 0 and up < 0.5) or (index_pct < 0 and up > 0.6))):
            flags.append('breadth_divergence')
        cov = r.get('coverage') or {}
        etf_cov = cov.get('etf')
        # bool 是 int 的子类：True < 50 恒成立，必须先排除布尔值再按百分数判断
        if etf_cov is False or (isinstance(etf_cov, (int, float))
                                and not isinstance(etf_cov, bool) and etf_cov < 50):
            flags.append('etf_coverage_low')
        if not north_enabled:
            flags.append('northbound_off')
        missing = [k for k, v in dims.items() if v is None]
        if missing:
            flags.append('missing_dim')

        out.append({
            **r,
            'dim_rs': dims['rs'],
            'dim_fund': dims['fund'],
            'dim_vp': dim_vp[i],
            'dim_sentiment': dim_crowding[i],
            'dim_breadth': dims['breadth'],
            'quality_score': round(quality, 2),
            'stage': stage,
            'flags': flags,
            'missing_dims': missing,
            'evidence': {
                'rps20': rps20, 'rps60': rps60, 'rps120': rps120,
                'resonance': res, 'fund_ratio': fund_ratio,
                'up_ratio': up, 'limit_up_ratio': limit_up,
                'zhaban_ratio': zhaban, 'amount_share': amount_share,
                'vp_state': vp_state, 'crowding': crowding,
                'rules': {
                    'overheat': overheat, 'mainline': mainline,
                    'pulse': pulse, 'cold': cold,
                },
            },
        })

    # 按质量分降序排名（缺失分按 -1 处理）
    order = sorted(range(len(out)),
                   key=lambda i: (-(out[i]['quality_score'] if out[i]['quality_score'] is not None else -1),
                                  str(out[i].get('industry') or '')))
    for rank, i in enumerate(order, 1):
        out[i]['heat_rank'] = rank
    return out
