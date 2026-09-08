"""第6维 风险边界引擎

358号方案 v4.1：第6维风险边界维度引擎。

整合源：
  - risk_boundary_builder.py（382行）：风险等级5级 + 波动率 + 盈亏比 + 失效条件
  - advice_engine._geometric()：支撑位/阻力位/盈亏比/ATR%/信号天数
  - event_monitor.py（925行）中的关键事件风险检测
  - cscv_validator.py（307行）：CSCV校验逻辑
  - eagle_sword_resonance.py（399行）：鹰刀共振（含BOCIASI情绪输入）

统一接口：evaluate(dims, tags, signals, lifecycle) → {status_description, judgment, audit}
"""

from __future__ import annotations

import itertools  # 403号BUG-01: CSCVValidator.compute_pbo依赖
import logging
import math
from typing import Any, Callable, Dict, List  # 403号BUG-02: Callable类型注解

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# === DataAwareMixin (app/data/mixins.py) ===

from app.data.mixins import DataAwareMixin

# ═══════════════════════════════════════════════════════════
# 风险等级常量
# ═══════════════════════════════════════════════════════════

RISK_LEVEL_LIGHT = {
    '极低': 'green', '低': 'green', '中': 'yellow',
    '高': 'red', '极高': 'red',
}

EVENT_RISK_SET = {'fraud_sign', 'regulatory', 'delist_risk', 'goodwill_risk'}

# ── 事件→维度前缀映射（A/B/C/D/E）──
_EVENT_DIM_MAP = {
    # A 财务事件
    'earnings_surprise': 'A', 'earnings_confirm': 'A', 'report_date': 'A',
    'dividend': 'A', 'fraud_sign': 'A',
    # B 资本运作
    'share_float': 'B', 'pledge_risk': 'B', 'holder_reduce': 'B',
    'underwater_ipo': 'B', 'buyback': 'B', 'incentive': 'B',
    # C 监管事件
    'regulatory': 'C', 'delist_risk': 'C', 'st_warning': 'C', 'goodwill_risk': 'C',
    # D 市场情绪
    'longhubang': 'D', 'limit_move': 'D', 'holder_concentration': 'D', 'margin_risk': 'D',
    # E 特殊事件
    'breakout': 'E', 'concept_heat': 'E',
}


def _event_dim_prefix(event_name: str) -> str:
    """将事件类型映射到 A/B/C/D/E 维度前缀"""
    return _EVENT_DIM_MAP.get(event_name, 'E')


def _direction_to_sign(direction: int) -> int:
    """将方向值转为符号（-1/0/+1）"""
    if direction > 0:
        return 1
    elif direction < 0:
        return -1
    return 0


# ── 催化剂事件映射 ──
CATALYST_EVENT_MAP = {
    'earnings_surprise': 'earnings', 'earnings_confirm': 'earnings',
    'longhubang': 'lhb', 'limit_move': 'lhb',
    'buyback': 'buyback', 'incentive': 'buyback',
    'breakout': 'breakout', 'concept_heat': 'concept',
    'share_float': 'float', 'pledge_risk': 'pledge', 'holder_reduce': 'reduce',
    'fraud_sign': 'fraud_sign', 'regulatory': 'regulatory',
    'st_warning': 'regulatory', 'goodwill_risk': 'fraud_sign',
    'delist_risk': 'decline', 'underwater_ipo': 'decline',
    'holder_concentration': 'decline', 'margin_risk': 'decline',
}

# ── 鹰眼大宝剑共振查表 ──
_RESONANCE_TABLE = {
    "UP": {
        "BULLISH":  ("BUY", 0.70),
        "BEARISH":  ("CONFLICT", 0.40),
        "NEUTRAL":  ("WATCH_BUY", 0.55),
    },
    "DOWN": {
        "BULLISH":  ("CONFLICT", 0.40),
        "BEARISH":  ("SELL", 0.70),
        "NEUTRAL":  ("WATCH_SELL", 0.55),
    },
    "RANGING": {
        "BULLISH":  ("CAUTIOUS_BUY", 0.50),
        "BEARISH":  ("CAUTIOUS_SELL", 0.50),
        "NEUTRAL":  ("NEUTRAL", 0.30),
    },
    "UNKNOWN": {
        "BULLISH":  ("CAUTIOUS_BUY", 0.45),
        "BEARISH":  ("CAUTIOUS_SELL", 0.45),
        "NEUTRAL":  ("NEUTRAL", 0.25),
    },
}
_FALLBACK_ACTION = ("NEUTRAL", 0.25)


# ═══════════════════════════════════════════════════════════
# 几何化指标（从 advice_engine._geometric() 完整迁移）
# ═══════════════════════════════════════════════════════════

def calc_geometric(df: pd.DataFrame) -> dict:
    """几何化指标：支撑/阻力位、盈亏比、信号天数、防守位"""
    if df is None or df.empty or 'close' not in df.columns or len(df) < 20:
        return {'dist_to_support_pct': None, 'dist_to_resistance_pct': None,
                'risk_reward': None, 'signal_days': None,
                'support_price': None, 'resistance_price': None}

    closes = df['close'].values
    price = float(closes[-1])
    hi60 = float(df['high'].tail(60).max()) if len(df) >= 60 and 'high' in df.columns else None
    lo60 = float(df['low'].tail(60).min()) if len(df) >= 60 and 'low' in df.columns else None

    ma60 = float(df['close'].tail(60).mean()) if len(df) >= 60 else None
    resistance = hi60
    resistance_candidates = [x for x in [hi60, ma60] if x is not None and x > price]
    if resistance_candidates:
        resistance = min(resistance_candidates)

    ma20 = float(df['close'].tail(20).mean()) if len(df) >= 20 else None
    lo20 = float(df['low'].tail(20).min()) if len(df) >= 20 and 'low' in df.columns else None
    near = None
    if ma20 is not None and lo20 is not None:
        near = max(ma20, lo20)
    elif ma20 is not None:
        near = ma20
    elif lo20 is not None:
        near = lo20
    support = near

    if support is not None and price is not None and support >= price:
        support = lo60
    if support is not None and price is not None:
        max_stop_pct = 0.15
        min_support = price * (1 - max_stop_pct)
        if support < min_support:
            support = min_support

    dist_sup = (support / price - 1) * 100 if support else None
    dist_res = (resistance / price - 1) * 100 if resistance else None
    rr = abs(dist_res / dist_sup) if dist_sup and dist_res else None

    signal_days = None
    if len(closes) >= 62:
        prior_hi = float(df['high'].iloc[-61:-1].max())
        if prior_hi > 0 and closes[-1] > prior_hi:
            days = 0
            for i in range(len(closes) - 1, -1, -1):
                if closes[i] > prior_hi:
                    days += 1
                else:
                    break
            signal_days = days if days > 0 else None

    # P8: 距前高%（20日内最高价）
    dist_prev_high = None
    if len(df) >= 20 and 'high' in df.columns:
        prev_high = float(df['high'].tail(20).max())
        if prev_high > 0 and price is not None:
            dist_prev_high = round((price / prev_high - 1) * 100, 2)

    return {
        'dist_to_support_pct': round(dist_sup, 2) if dist_sup is not None else None,
        'dist_to_resistance_pct': round(dist_res, 2) if dist_res is not None else None,
        'dist_to_prev_high_pct': dist_prev_high,  # P8新增
        'risk_reward': round(rr, 2) if rr is not None else None,
        'signal_days': signal_days,
        'support_price': round(support, 2) if support is not None else None,
        'resistance_price': round(resistance, 2) if resistance is not None else None,
    }


# ═══════════════════════════════════════════════════════════
# 波动率计算
# ═══════════════════════════════════════════════════════════

def _calc_volatility(df=None, tags: dict = None) -> dict:
    tags = tags or {}
    level = str(tags.get('volatility_level', 'medium'))
    atr_14d = 0.0
    atr_pct = 0.0
    percentile = 0.5

    if df is not None and not df.empty and len(df) >= 20:
        try:
            close = df['close'].astype(float)
            high = df['high'].astype(float)
            low = df['low'].astype(float)
            tr = pd.concat([high - low, (high - close.shift(1)).abs(),
                           (low - close.shift(1)).abs()], axis=1).max(axis=1)
            atr_14d = tr.rolling(14).mean().iloc[-1] if len(tr) >= 14 else tr.mean()
            current_price = close.iloc[-1]
            atr_pct = (atr_14d / current_price * 100) if current_price > 0 else 0
            returns = close.pct_change().dropna()
            if len(returns) >= 20:
                vol_20d = returns.rolling(20).std() * math.sqrt(252)
                vol_20d = vol_20d.dropna()
                if len(vol_20d) >= 2:
                    current_vol = vol_20d.iloc[-1]
                    percentile = float((vol_20d < current_vol).sum() / len(vol_20d))
        except Exception as e:
            logger.debug("403号Q-01 _calc_volatility 计算异常: %s", e)

    return {'level': level, 'atr_14d': atr_14d, 'atr_pct': atr_pct,
            'percentile': percentile}


# ═══════════════════════════════════════════════════════════
# 风险等级评估（从 risk_boundary_builder 迁移）
# ═══════════════════════════════════════════════════════════

def _assess_risk_level(dims: dict, l0: dict, tags: dict) -> dict:
    """风险等级评估（T42修复：消除dims循环依赖，仅依赖tags和l0）"""
    risk_sources = []
    high_count = 0

    # T42修复：移除对dims['risk']的读取（循环依赖）
    # dims['risk']由StatusEngine从dim6输出生成，读取它会形成循环
    # 原代码：dim_risk = str(dims.get('risk', {}).get('state', ''))

    rl = str(tags.get('risk_level', ''))
    if rl == 'HIGH':
        high_count += 1
    risk_sources.append({'name': '缠论风险', 'level': '高' if rl == 'HIGH' else '低'})

    vl = str(tags.get('volatility_level', ''))
    if vl == 'high':
        high_count += 1
    risk_sources.append({'name': '波动率风险', 'level': '高' if vl == 'high' else '低'})

    fh = str(tags.get('fina_health', ''))
    if fh == 'fail':
        high_count += 1
    risk_sources.append({'name': '财务风险', 'level': '高' if fh == 'fail' else '低'})

    ce = str(tags.get('catalyst_event', ''))
    if ce in EVENT_RISK_SET:
        high_count += 1
    risk_sources.append({'name': '事件风险', 'level': '高' if ce in EVENT_RISK_SET else '低'})

    mfp = str(tags.get('main_force_phase', ''))
    if mfp == 'distributing':
        high_count += 1
    risk_sources.append({'name': '主力风险', 'level': '高' if mfp == 'distributing' else '低'})

    try:
        tr = float(tags.get('turnover_rate', 999))
        if tr < 1.0:
            high_count += 1
    except (TypeError, ValueError):
        pass
    risk_sources.append({'name': '流动性风险', 'level': '高' if tr < 1.0 else '低'})

    # 404号DATA-04: dims['l0']始终为空（T42循环依赖设计限制），hard_veto永远不触发
    # l0由StatusEngine._apply_l0()在维度引擎运行后才计算，dim6无法读取（已知限制）
    if l0.get('hard_veto'):
        return {'level': '极高', 'light': 'red', 'detail': f"硬否决：{l0.get('hard_reason', '')}",
                'risk_sources': risk_sources}

    if high_count >= 2:
        level, light = '高', 'red'
    elif high_count == 1:
        level, light = '中', 'yellow'
    else:
        level, light = '低', 'green'

    return {'level': level, 'light': light, 'detail': f'{high_count}个高风险源' if high_count else '无高风险源',
            'risk_sources': risk_sources}


def _list_risk_factors(tags: dict, dims: dict, l0: dict) -> list[dict]:
    """风险因素枚举（T45修复：与_assess_risk_level风险源完全对齐）"""
    factors = []

    # 与_assess_risk_level完全对齐的6个风险源
    rl = str(tags.get('risk_level', ''))
    if rl == 'HIGH':
        factors.append({'category': '缠论', 'factor': '缠论风险高', 'severity': '高', 'satisfied': True})

    vl = str(tags.get('volatility_level', ''))
    if vl == 'high':
        factors.append({'category': '波动率', 'factor': '波动率过高', 'severity': '高', 'satisfied': True})

    fh = str(tags.get('fina_health', ''))
    if fh == 'fail':
        factors.append({'category': '财务', 'factor': '财务异常', 'severity': '高', 'satisfied': True})
    elif fh == 'suspicious':
        factors.append({'category': '财务', 'factor': '财务关注', 'severity': '中', 'satisfied': True})

    ce = str(tags.get('catalyst_event', ''))
    if ce in EVENT_RISK_SET:
        event_names = {'regulatory': '监管问题', 'fraud_sign': '造假信号',
                       'delist_risk': '退市风险', 'goodwill_risk': '商誉风险'}
        factors.append({'category': '事件', 'factor': event_names.get(ce, ce),
                        'severity': '高', 'satisfied': True})

    mfp = str(tags.get('main_force_phase', ''))
    if mfp == 'distributing':
        factors.append({'category': '主力', 'factor': '主力出货', 'severity': '中', 'satisfied': True})

    try:
        tr = float(tags.get('turnover_rate', 999))
        if tr < 1.0:
            factors.append({'category': '流动性', 'factor': '流动性不足', 'severity': '高', 'satisfied': True})
    except (TypeError, ValueError):
        pass

    # L0硬否决（404号DATA-04: l0始终为空，此分支为死代码）
    if l0.get('hard_veto'):
        factors.append({'category': '否决', 'factor': f"硬否决：{l0.get('hard_reason', '')}",
                        'severity': '极高', 'satisfied': True})

    # 补充风险源（_assess_risk_level未覆盖但有判定价值）
    vl2 = str(tags.get('valuation_level', ''))
    if vl2 in ('high', 'extreme_high'):
        factors.append({'category': '估值', 'factor': '估值过高', 'severity': '中', 'satisfied': True})

    try:
        pr = float(tags.get('profit_ratio', 0))
        if pr >= 0.8:
            factors.append({'category': '获利盘', 'factor': '获利盘过高', 'severity': '中', 'satisfied': True})
    except (TypeError, ValueError):
        pass

    # 404号DATA-04: l0始终为空（T42循环依赖设计限制），此循环为死代码（已知限制）
    for sr in l0.get('soft_risks', []):
        if sr == 'low_liquidity':
            factors.append({'category': '流动性', 'factor': '流动性不足(L0)', 'severity': '中', 'satisfied': True})

    if not factors:
        factors.append({'category': '综合', 'factor': '无显著风险', 'severity': '无', 'satisfied': True})

    return factors


def _assess_rr(geo: dict) -> dict:
    rr = geo.get('risk_reward')
    if rr is None:
        return {'rr_value': None, 'rr_level': '未知', 'rr_assessment': '盈亏比数据不足', 'light': 'yellow'}
    if rr < 1.0:
        return {'rr_value': rr, 'rr_level': '不值得交易', 'rr_assessment': f'盈亏比{rr:.2f}<1R', 'light': 'red'}
    if rr < 2.0:
        return {'rr_value': rr, 'rr_level': '可考虑', 'rr_assessment': f'盈亏比{rr:.2f}（1R-2R）', 'light': 'yellow'}
    if rr < 3.0:
        return {'rr_value': rr, 'rr_level': '较好', 'rr_assessment': f'盈亏比{rr:.2f}（2R-3R）', 'light': 'green'}
    return {'rr_value': rr, 'rr_level': '优质', 'rr_assessment': f'盈亏比{rr:.2f}（>3R）', 'light': 'green'}


def _build_invalidation(support, tags, dims) -> list[dict]:
    conditions = []
    if support is not None:
        conditions.append({'source': '防守位', 'condition': f'收盘跌破{support}元', 'priority': 1})
    sp = str(tags.get('sentiment_phase', ''))
    if sp in ('ebb', 'climax'):
        conditions.append({'source': '情绪', 'condition': '大盘进入退潮/高潮期', 'priority': 2})
    # 404号DATA-03: right_side_confirm在pre_feat_cache管道中只产出strong_confirm/unconfirmed，
    # '否决'值仅由_check_right_side_confirm()在treemap快照管道中产出，此处为死代码（已知限制）
    if str(tags.get('right_side_confirm', '')) == '否决':
        conditions.append({'source': '右侧', 'condition': '右侧确认转否决', 'priority': 3})
    return conditions


# ═══════════════════════════════════════════════════════════
# 白话文本
# ═══════════════════════════════════════════════════════════

def _risk_plain(level, factors, geo, rr, vol, invalidation) -> str:
    parts = []
    level_cn = {'低': '低风险', '中': '中等风险', '高': '高风险'}.get(level, f'{level}风险')
    parts.append(level_cn)

    support = geo.get('support_price')
    dist_sup = geo.get('dist_to_support_pct')
    if support and dist_sup is not None:
        parts.append(f'防守位{support}元（距现价{dist_sup:+.1f}%）')

    resistance = geo.get('resistance_price')
    dist_res = geo.get('dist_to_resistance_pct')
    if resistance and dist_res is not None:
        parts.append(f'压力位{resistance}元（距现价{dist_res:+.1f}%）')

    rr_val = rr.get('rr_value')
    if rr_val:
        if rr_val >= 3:
            parts.append(f'盈亏比{rr_val}（优质）')
        elif rr_val >= 2:
            parts.append(f'盈亏比{rr_val}（较好）')
        elif rr_val >= 1:
            parts.append(f'盈亏比{rr_val}（一般）')
        else:
            parts.append(f'盈亏比{rr_val}（不划算）')

    vol_level = vol.get('level', '')
    vol_cn = {'low': '低波动', 'medium': '中等波动', 'high': '高波动'}.get(vol_level, '')
    if vol_cn:
        parts.append(vol_cn)

    key_factors = [f['factor'] for f in factors if f.get('satisfied') and f.get('severity') in ('高', '极高')]
    if key_factors:
        parts.append(f'需关注：{"、".join(key_factors)}')

    if invalidation:
        parts.append(f'止损条件：{invalidation[0].get("condition", "")}')

    return '，'.join(parts) if parts else '风险数据不足'


# ═══════════════════════════════════════════════════════════
# 第6维 引擎
# ═══════════════════════════════════════════════════════════


# === event_monitor.py === 已迁移至独立模块 event_monitor.py（405号建议2+5）
# dim6 改为从 pre_feat_cache.event 读取 RAW-2 预计算的事件标签

# === cscv_validator.py ===
def calculate_sharpe(returns: np.ndarray, annual_factor: float = 252.0) -> float:
    """
    计算年化夏普比率。

    Parameters
    ----------
    returns : np.ndarray
        日收益率序列。
    annual_factor : float, default=252.0
        年化因子（日频数据默认 252）。

    Returns
    -------
    float
        年化夏普比率。若收益率序列长度 < 2 或标准差为零，返回 0.0。
    """
    if len(returns) < 2:
        return 0.0
    std = np.std(returns, ddof=1)
    if std == 0.0 or np.isnan(std):
        return 0.0
    mean = np.mean(returns)
    return (mean / std) * np.sqrt(annual_factor)


# ── 主类 ──────────────────────────────────────────────────────────────


# ═══════════════════════════════════════════════════════════
# T48: 独立工具类（不参与dim6 evaluate()路径）
# CSCVValidator用于策略回测过拟合检测，供backtest模块调用
# ═══════════════════════════════════════════════════════════

class CSCVValidator:
    """
    Combinatorial Symmetric Cross-Validation (CSCV) 验证器。

    用于评估策略参数优化中的过拟合风险，输出 PBO 指标。

    Parameters
    ----------
    n_splits : int, default=6
        时间序列划分块数 S。必须为偶数，且 >= 4。
    random_state : int, optional, default=42
        随机种子，用于结果复现。
    """

    def __init__(self, n_splits: int = 6, random_state: int = 42) -> None:
        if n_splits < 4:
            raise ValueError("n_splits 必须 >= 4")
        if n_splits % 2 != 0:
            raise ValueError("n_splits 必须为偶数（标准 CSCV 要求 S/2 为整数）")
        self.n_splits = n_splits
        self.random_state = random_state
        np.random.seed(random_state)

    # ── 公共方法 ──────────────────────────────────────────────────────

    def compute_pbo(self, sharpe_matrix: np.ndarray) -> Dict[str, Any]:
        """
        基于夏普比率矩阵计算 PBO。

        Parameters
        ----------
        sharpe_matrix : np.ndarray, shape (n_configs, n_splits)
            sharpe_matrix[i][j] 表示第 i 个参数配置在第 j 个测试块上的夏普比率。
            矩阵必须为非空且行列数符合要求。

        Returns
        -------
        Dict[str, Any]
            包含以下字段:
            - pbo: float, 概率性回测过拟合指标
            - is_robust: bool, 是否鲁棒
            - n_configs: int, 参数配置数
            - n_splits: int, 划分块数
            - n_combos: int, 实际计算的组合数
            - rank_matrix: np.ndarray, shape (n_combos, n_configs), 各组合下各参数配置的排名
            - best_rank_oos: np.ndarray, shape (n_combos,), 各组合下最优参数的 OOS 排名
            - rank_below_median: int, 最优参数排名低于中位数的次数
        """
        n_configs, n_splits = sharpe_matrix.shape
        if n_configs < 1 or n_splits < 2:
            return self._empty_result(n_configs, n_splits)

        if n_splits != self.n_splits:
            self.n_splits = n_splits  # 自适应

        train_size = self.n_splits // 2
        split_indices = list(range(self.n_splits))
        combos = list(itertools.combinations(split_indices, train_size))
        n_combos = len(combos)

        rank_matrix = np.zeros((n_combos, n_configs), dtype=float)
        best_rank_oos = np.zeros(n_combos, dtype=float)

        for c_idx, train_splits in enumerate(combos):
            train_set = set(train_splits)
            test_splits = [i for i in split_indices if i not in train_set]

            # 训练集: 取各配置在训练块上的平均夏普 → 选最优配置
            train_sharpes = np.mean(sharpe_matrix[:, list(train_set)], axis=1)
            best_config = int(np.argmax(train_sharpes))

            # 测试集: 取各配置在测试块上的平均夏普 → 排秩（1=最好）
            test_sharpes = np.mean(sharpe_matrix[:, test_splits], axis=1)
            # 夏普越高，秩越小（rank=1 最高）
            ranks = np.argsort(np.argsort(-test_sharpes)) + 1
            rank_matrix[c_idx, :] = ranks

            # 记录最优配置在测试集中的排名
            best_rank_oos[c_idx] = ranks[best_config]

        # PBO = 最优配置在测试集中排名低于中位数的比例
        median_rank = (n_configs + 1) / 2.0
        rank_below_median = int(np.sum(best_rank_oos > median_rank))
        pbo = rank_below_median / n_combos if n_combos > 0 else 1.0

        return {
            "pbo": float(pbo),
            "is_robust": self.is_robust(pbo),
            "n_configs": n_configs,
            "n_splits": self.n_splits,
            "n_combos": n_combos,
            "rank_matrix": rank_matrix,
            "best_rank_oos": best_rank_oos,
            "rank_below_median": rank_below_median,
        }

    def evaluate(
        self,
        returns: np.ndarray,
        param_configs: List[Any],
        param_func: Callable[[np.ndarray, Any], float],
    ) -> Dict[str, Any]:
        """
        便捷包装器: 直接传入收益率序列和参数配置列表，自动完成 CSCV 分析。

        Parameters
        ----------
        returns : np.ndarray, shape (n_obs,)
            全样本收益率序列。
        param_configs : List[Any]
            参数配置列表，每个元素会传给 param_func 作为第二个参数。
        param_func : Callable[[np.ndarray, Any], float]
            接收 (returns_subset, param) 返回夏普比率的函数。

        Returns
        -------
        Dict[str, Any]
            包含 compute_pbo 返回的所有字段，额外包含 returns_shape。
        """
        n_obs = len(returns)
        if n_obs < self.n_splits:
            return {
                "pbo": 1.0,
                "is_robust": False,
                "n_configs": len(param_configs),
                "n_splits": self.n_splits,
                "n_combos": 0,
                "error": "收益率序列长度不足以进行划分",
                "returns_shape": returns.shape,
            }

        splits = np.array_split(returns, self.n_splits)
        n_configs = len(param_configs)
        sharpe_matrix = np.zeros((n_configs, self.n_splits), dtype=float)

        for j in range(self.n_splits):
            for i, param in enumerate(param_configs):
                sharpe_matrix[i, j] = param_func(splits[j], param)

        result = self.compute_pbo(sharpe_matrix)
        result["returns_shape"] = returns.shape
        return result

    @staticmethod
    def is_robust(pbo: float, threshold: float = 0.05) -> bool:
        """
        判断 PBO 是否在可接受阈值内。

        Parameters
        ----------
        pbo : float
            概率性回测过拟合指标。
        threshold : float, default=0.05
            阈值。PBO < threshold 认为策略鲁棒。

        Returns
        -------
        bool
            True 表示策略鲁棒，过拟合风险低。
        """
        return pbo < threshold

    @staticmethod
    def simulate_backtest_sharpes(n_params: int, n_splits: int = 6) -> np.ndarray:
        """
        生成用于测试的合成夏普比率矩阵。

        前一半参数配置为"真实有效"（夏普较高），后一半为"随机噪音"（夏普通近零）。
        用于验证 PBO 计算逻辑。

        Parameters
        ----------
        n_params : int
            参数配置数量。
        n_splits : int, default=6
            划分块数。

        Returns
        -------
        np.ndarray, shape (n_params, n_splits)
            合成的夏普比率矩阵。
        """
        np.random.seed(42)
        sharpe_matrix = np.zeros((n_params, n_splits), dtype=float)

        half = max(1, n_params // 2)

        # 前一半: 真实有效策略，各块间有一定波动
        for i in range(half):
            base_sharpe = np.random.uniform(0.8, 1.5)
            noise = np.random.normal(0, 0.15, n_splits)
            sharpe_matrix[i, :] = base_sharpe + noise

        # 后一半: 噪音策略，夏普通近零
        for i in range(half, n_params):
            sharpe_matrix[i, :] = np.random.normal(0, 0.2, n_splits)

        return sharpe_matrix

    # ── 内部方法 ──────────────────────────────────────────────────────

    def _empty_result(self, n_configs: int, n_splits: int) -> Dict[str, Any]:
        """返回空结果（用于边缘情况）。"""
        return {
            "pbo": 1.0,
            "is_robust": False,
            "n_configs": n_configs,
            "n_splits": n_splits,
            "n_combos": 0,
            "rank_matrix": np.empty((0, max(n_configs, 1))),
            "best_rank_oos": np.empty(0),
            "rank_below_median": 0,
            "error": "数据不足: 参数配置或划分块数不足",
        }


# ── 模块级便捷函数 ─────────────────────────────────────────────────────


def compute_cscv_pbo(
    returns: np.ndarray,
    param_configs: List[Any],
    param_func: Callable[[np.ndarray, Any], float],
    n_splits: int = 6,
) -> Dict[str, Any]:
    """
    一键计算 CSCV PBO 的模块级函数。

    等价于:
        validator = CSCVValidator(n_splits=n_splits)
        return validator.evaluate(returns, param_configs, param_func)

    Parameters
    ----------
    returns : np.ndarray
        全样本收益率序列。
    param_configs : List[Any]
        参数配置列表。
    param_func : Callable[[np.ndarray, Any], float]
        接收 (returns_subset, param) 返回夏普比率的函数。
    n_splits : int, default=6
        划分块数。

    Returns
    -------
    Dict[str, Any]
        CSCV 分析结果字典。
    """
    validator = CSCVValidator(n_splits=n_splits)
    return validator.evaluate(returns, param_configs, param_func)


# === eagle_sword_resonance.py ===
class EagleSwordResonance:
    """
    "鹰眼大宝剑" 双系统共振模型

    鹰眼 = 趋势系统（缠论方向 + 量价强度）
    大宝剑 = 情绪系统（BOCIASI 快慢线 + 拥挤度）
    """

    # ──────────────
    # 鹰眼系统
    # ──────────────

    @staticmethod
    def _eagle_trend_direction(chanlun_result: Dict) -> str:
        """
        从缠论结果提取趋势方向

        Args:
            chanlun_result: ChanlunAnalyzer.analyze() 的返回 dict,
                            包含键 'trend' (str), 'segments' (List), 'zhongshu' (List)

        Returns:
            'UP' | 'DOWN' | 'RANGING' | 'UNKNOWN'
        """
        trend = chanlun_result.get("trend", "unknown")
        if trend == "up":
            return "UP"
        if trend == "down":
            return "DOWN"

        # 403号Q-03: 非up/down一律返回RANGING
        return "RANGING"

    @staticmethod
    def _eagle_trend_strength(volume_price_signal: Dict) -> float:
        """
        从量价信号提取趋势强度 (0.0 ~ 1.0)

        考量因素:
          - MA 排列 (多头发散 / 空头发散 / 交叉 / 粘合)
          - 格兰维尔信号 (buy1~4, sell1~4)
          - 量价关系置信度

        Args:
            volume_price_signal: volume_price_strategy 的 to_output_dict() 结果

        Returns:
            float: 0.0 ~ 1.0
        """
        strength = 0.5  # 中性基准

        # --- MA 排列 ---
        status = volume_price_signal.get("status_recognition", {})
        trend = status.get("trend", {})
        direction = trend.get("direction", "")
        trend.get("stage", "")
        strength_label = trend.get("strength", "")

        # 趋势方向和力度
        if direction == "up" and strength_label in ("strong", "moderate"):
            strength += 0.15
        elif direction == "down" and strength_label in ("strong", "moderate"):
            strength -= 0.15

        # --- 格兰维尔信号 ---
        evidence = volume_price_signal.get("evidence", [])
        granville_buy_count = sum(1 for e in evidence if "格兰维尔" in e and "买" in e)
        granville_sell_count = sum(1 for e in evidence if "格兰维尔" in e and "卖" in e)

        if granville_buy_count > 0:
            strength += min(0.20, granville_buy_count * 0.10)
        if granville_sell_count > 0:
            strength -= min(0.20, granville_sell_count * 0.10)

        # --- 量价置信度 ---
        conf = volume_price_signal.get("confidence", 0.5)
        if conf > 0.6:
            strength += 0.10
        elif conf < 0.3:
            strength -= 0.10

        return max(0.0, min(1.0, strength))

    @staticmethod
    def _eagle_granville_signals(volume_price_signal: Dict) -> List[str]:
        """提取格兰维尔信号列表"""
        evidence = volume_price_signal.get("evidence", [])
        return [e for e in evidence if "格兰维尔" in e]

    # ──────────────
    # 大宝剑系统
    # ──────────────

    @staticmethod
    def _sword_sentiment(bociasi_quick: Dict, bociasi_slow: Dict) -> str:
        """
        聚合快慢线情绪信号

        Args:
            bociasi_quick:  BociasiQuickLine.evaluate() 返回
            bociasi_slow:   BociasiSlowLine.evaluate() 返回

        Returns:
            'BULLISH' | 'BEARISH' | 'NEUTRAL'
        """
        quick_signal = bociasi_quick.get("signal", "NEUTRAL")
        quick_conf = bociasi_quick.get("confidence", 0.0)

        slow_signal = bociasi_slow.get("signal", "NEUTRAL")
        slow_conf = bociasi_slow.get("confidence", 0.0)

        # 加权投票: 快线权重 0.6, 慢线权重 0.4
        bullish_score = 0.0
        bearish_score = 0.0

        if quick_signal == "BUY":
            bullish_score += 0.6 * quick_conf
        elif quick_signal == "NEUTRAL":
            pass  # 不贡献分数
        # quick 没有 BEARISH，只有 BUY/WATCH/NEUTRAL，WATCH 按中性处理

        if slow_signal == "BULLISH":
            bullish_score += 0.4 * slow_conf
        elif slow_signal == "BEARISH":
            bearish_score += 0.4 * slow_conf

        if bullish_score > bearish_score and bullish_score >= 0.20:
            return "BULLISH"
        if bearish_score > bullish_score and bearish_score >= 0.20:
            return "BEARISH"
        return "NEUTRAL"

    @staticmethod
    def _sword_crowding_warning(crowding_factor: Dict) -> bool:
        """
        拥挤度预警

        Args:
            crowding_factor: crowding_factor 模块的输出 dict,
                             应包含 'crowding_level' (str) 或 'risk_notes'

        Returns:
            True if 拥挤度过高
        """
        level = crowding_factor.get("crowding_level", "LOW")
        return level in ("HIGH", "EXTREME")

    @staticmethod
    def _sword_sentiment_strength(bociasi_quick: Dict, bociasi_slow: Dict) -> float:
        """情绪强度 0.0 ~ 1.0"""
        quick_conf = bociasi_quick.get("confidence", 0.0)
        slow_conf = bociasi_slow.get("confidence", 0.0)
        return round((quick_conf * 0.6 + slow_conf * 0.4), 2)

    # ──────────────
    # 共振判定
    # ──────────────

    def evaluate(
        self,
        chanlun_result: Dict,
        volume_price_signal: Dict,
        bociasi_quick: Dict,
        bociasi_slow: Dict,
        crowding: Dict,
        market_state: str = "UNKNOWN",
        kronos_result: Optional[Dict] = None,
    ) -> Dict:
        """
        双系统共振判定

        Args:
            chanlun_result:     缠论分析结果 dict
            volume_price_signal: 量价分析结果 dict (to_output_dict 格式)
            bociasi_quick:       BOCIASI 快线结果 dict
            bociasi_slow:        BOCIASI 慢线结果 dict
            crowding:            拥挤度结果 dict
            market_state:        大盘状态 ('BULL', 'BEAR', 'RANGING', 'UNKNOWN')
            kronos_result:       Kronos预测结果 dict（可选，增强鹰眼前瞻）

        Returns:
            {
                'action': str,
                'confidence': float,
                'eagle_system': {...},
                'sword_system': {...},
                'resonance_detail': {...},
                'signal_label': str,
                'risk_notes': List[str],
            }
        """
        # --- 鹰眼系统 ---
        eagle_direction = self._eagle_trend_direction(chanlun_result)
        eagle_strength = self._eagle_trend_strength(volume_price_signal)
        granville_signals = self._eagle_granville_signals(volume_price_signal)

        # --- Kronos前瞻鹰眼（融合点3）---
        kronos_forward_conf = None
        if kronos_result:
            kronos_dir = kronos_result.get('direction', 'neutral')
            kronos_strength = kronos_result.get('trend_strength', 0.0)
            if kronos_strength > 0.4:
                if kronos_dir == eagle_direction.lower():
                    kronos_forward_conf = 'confirm'
                    eagle_strength = min(1.0, eagle_strength + 0.10)
                else:
                    kronos_forward_conf = 'conflict'
                    eagle_strength = max(0.0, eagle_strength - 0.15)

        # --- 大宝剑系统 ---
        sword_sentiment = self._sword_sentiment(bociasi_quick, bociasi_slow)
        crowding_warning = self._sword_crowding_warning(crowding)
        sentiment_strength = self._sword_sentiment_strength(bociasi_quick, bociasi_slow)

        # --- 共振查表 ---
        eagle_routing = _RESONANCE_TABLE.get(eagle_direction, {})
        action, base_conf = eagle_routing.get(
            sword_sentiment, _FALLBACK_ACTION
        )

        # --- 置信度微调 ---
        confidence = base_conf
        risk_notes: List[str] = []

        # 鹰眼强度修正
        if eagle_strength > 0.7:
            confidence += 0.05
        elif eagle_strength < 0.3:
            confidence -= 0.05

        # 情绪强度修正
        if sentiment_strength > 0.65:
            confidence += 0.05
        elif sentiment_strength < 0.25:
            confidence -= 0.05

        # 拥挤度预警
        if crowding_warning:
            confidence -= 0.10
            risk_notes.append("拥挤度过高，警惕反转风险")

        # Kronos前瞻预警
        if kronos_forward_conf == 'conflict':
            risk_notes.append("Kronos前瞻与鹰眼方向冲突，注意可能拐点")
        elif kronos_forward_conf == 'confirm':
            risk_notes.append("Kronos前瞻确认鹰眼方向")

        # 大盘状态修正
        if market_state == "BEAR" and action in ("BUY", "WATCH_BUY", "CAUTIOUS_BUY"):
            confidence -= 0.10
            risk_notes.append("大盘偏空，多头信号降权")
        elif market_state == "BULL" and action in ("SELL", "WATCH_SELL", "CAUTIOUS_SELL"):
            confidence -= 0.10
            risk_notes.append("大盘偏多，空头信号降权")

        # 格兰维尔反向信号修正
        has_buy_granville = any("买" in g for g in granville_signals)
        has_sell_granville = any("卖" in g for g in granville_signals)
        if has_buy_granville and action in ("SELL", "WATCH_SELL"):
            confidence -= 0.05
            risk_notes.append("格兰维尔买点与空头方向冲突")
        if has_sell_granville and action in ("BUY", "WATCH_BUY"):
            confidence -= 0.05
            risk_notes.append("格兰维尔卖点与多头方向冲突")

        confidence = max(0.0, min(1.0, round(confidence, 2)))

        # --- 信号标签 ---
        signal_label = self._signal_label(action, eagle_direction, sword_sentiment)

        eagle_state = f"{eagle_direction}(strength={eagle_strength:.2f})"
        sword_state = f"{sword_sentiment}(strength={sentiment_strength:.2f})"

        return {
            "action": action,
            "confidence": confidence,
            "eagle_system": {
                "direction": eagle_direction,
                "strength": eagle_strength,
                "granville_signals": granville_signals,
            },
            "sword_system": {
                "sentiment": sword_sentiment,
                "crowding_warning": crowding_warning,
                "sentiment_strength": sentiment_strength,
            },
            "resonance_detail": {
                "eagle_state": eagle_state,
                "sword_state": sword_state,
                "resonant": action not in ("CONFLICT", "NEUTRAL"),
            },
            "signal_label": signal_label,
            "risk_notes": risk_notes,
        }

    # ──────────────
    # 辅助
    # ──────────────

    @staticmethod
    def _signal_label(action: str, eagle_dir: str, sword_sent: str) -> str:
        """生成中文信号标签"""
        labels = {
            "BUY":           "共振买入",
            "SELL":          "共振卖出",
            "WATCH_BUY":     "关注买入",
            "WATCH_SELL":    "关注卖出",
            "CAUTIOUS_BUY":  "谨慎买入",
            "CAUTIOUS_SELL": "谨慎卖出",
            "CONFLICT":      "信号冲突",
            "NEUTRAL":       "无明确信号",
        }
        label = labels.get(action, action)
        if action == "CONFLICT":
            label += f" (鹰眼={eagle_dir}, 大宝剑={sword_sent})"
        return label


def evaluate(
    chanlun_result: Dict,
    volume_price_signal: Dict,
    bociasi_quick: Dict,
    bociasi_slow: Dict,
    crowding: Dict,
    market_state: str = "UNKNOWN",
) -> Dict:
    """
    模块级便捷函数: 单次鹰眼大宝剑共振判定

    用法::
        from app.engine.framework.eagle_sword_resonance import evaluate
        result = evaluate(
            chanlun_result=chanlun_analysis,
            volume_price_signal=vp_signal,
            bociasi_quick=quick_result,
            bociasi_slow=slow_result,
            crowding=crowding_result,
            market_state='RANGING',
        )
    """
    return EagleSwordResonance().evaluate(
        chanlun_result=chanlun_result,
        volume_price_signal=volume_price_signal,
        bociasi_quick=bociasi_quick,
        bociasi_slow=bociasi_slow,
        crowding=crowding,
        market_state=market_state,
    )


class Dim6RiskEngine(DataAwareMixin):
    """第6维 风险边界引擎 — 风险分级 + 几何化距离 + 波动率 + 事件监控"""

    def __init__(self):
        self._dm = None

    def evaluate(self, dims: dict, tags: dict, signals: dict = None,
                 lifecycle: dict = None, data_context: dict = None) -> dict:
        """统一评估入口

        411号Phase 6：优先使用data_context预加载数据，回退独立查询。
        """
        ts_code = tags.get('ts_code', '')

        # 411号Phase 6：优先使用data_context
        if data_context and 'daily_df' in data_context:
            df = data_context['daily_df']
        else:
            ecm = self._get_dm().cache
            try:
                df = ecm.get_cached_daily(ts_code)
            except Exception:
                df = None

        # 1. 风险等级
        l0 = dims.get('l0', {}) if isinstance(dims.get('l0'), dict) else {}
        risk_info = _assess_risk_level(dims, l0, tags)
        risk_factors = _list_risk_factors(tags, dims, l0)

        # 1b. 事件风险检测（405号建议2: 从pre_feat_cache读取RAW-2预计算的事件标签）
        event_risks = []
        event_results = []
        try:
            event_details = tags.get('event_details', [])
            event_risk_factors_from_tags = tags.get('event_risk_factors', [])
            event_results = event_details if isinstance(event_details, list) else []
            if event_risk_factors_from_tags:
                event_risks.extend(event_risk_factors_from_tags)
            ce = str(tags.get('catalyst_event', ''))
            if ce in EVENT_RISK_SET:
                already = any(r.get('factor') == ce for r in event_risks)
                if not already:
                    event_risks.append({'category': '事件风险', 'factor': ce,
                                        'severity': '高', 'satisfied': True})
            if event_risks and risk_info['level'] not in ('高', '极高'):
                risk_info = {'level': '高', 'light': 'red',
                             'detail': f"事件风险：{event_risks[0]['factor']}"}
        except Exception as e:
            logger.debug("403号Q-05 EventMonitor检测跳过: %s", e)

        risk_factors.extend(event_risks)

        # 2. 几何化指标
        # 411号Phase 9：优先从tags读取预计算risk_ext，回退raw计算
        _geo_precomputed = all(tags.get(k) is not None for k in ('support_price', 'resistance_price', 'risk_reward'))
        if _geo_precomputed:
            geo = {
                'support_price': tags.get('support_price'),
                'resistance_price': tags.get('resistance_price'),
                'dist_to_support_pct': tags.get('dist_to_support_pct'),
                'dist_to_resistance_pct': tags.get('dist_to_resistance_pct'),
                'risk_reward': tags.get('risk_reward'),
                'signal_days': tags.get('signal_days'),
                'dist_to_prev_high_pct': tags.get('dist_to_prev_high_pct'),
            }
        else:
            geo = calc_geometric(df) if df is not None and not df.empty else {
                'dist_to_support_pct': None, 'dist_to_resistance_pct': None,
                'risk_reward': None, 'signal_days': None, 'support_price': None, 'resistance_price': None,
            }

        # 3. 盈亏比
        rr_info = _assess_rr(geo)

        # 4. 波动率
        # 411号Phase 9：优先从tags读取预计算波动率，回退raw计算
        _vol_precomputed = tags.get('atr_14d') is not None
        if _vol_precomputed:
            vol_info = {
                'atr_14d': float(tags.get('atr_14d', 0)),
                'atr_pct': float(tags.get('atr_pct', 0)),
                'level': str(tags.get('volatility_level', 'unknown')),
                'percentile': float(tags.get('volatility_percentile', 0.5)),
            }
        else:
            vol_info = _calc_volatility(df, tags)

        # 5. 失效条件
        invalidation = _build_invalidation(geo.get('support_price'), tags, dims)

        # 6. status_description
        plain = _risk_plain(risk_info['level'], risk_factors, geo, rr_info, vol_info, invalidation)

        risk_evidence_parts = []
        risk_evidence_parts.append(f"风险等级={risk_info['level']}({risk_info['detail']})")
        if geo.get('support_price'):
            risk_evidence_parts.append(f"防守位={geo['support_price']}元(距{geo.get('dist_to_support_pct', '无')}%)")
        if geo.get('resistance_price'):
            risk_evidence_parts.append(f"压力位={geo['resistance_price']}元(距{geo.get('dist_to_resistance_pct', '无')}%)")
        if rr_info.get('rr_value'):
            risk_evidence_parts.append(f"盈亏比={rr_info['rr_value']}({rr_info['rr_level']})")
        risk_evidence_parts.append(f"波动率={vol_info['level']}(ATR={vol_info['atr_14d']:.2f},分位{vol_info['percentile']:.0%})" if vol_info['atr_14d'] > 0 else f"波动率={vol_info['level']}")
        active_factors = [f for f in risk_factors if f.get('satisfied') and f.get('severity') in ('高', '极高')]
        if active_factors:
            risk_evidence_parts.append(f"高风险因素={'+'.join(f['factor'] for f in active_factors)}")
        if event_results:
            event_descs = [e.get('description', '') for e in event_results[:3] if e.get('description')]
            if event_descs:
                risk_evidence_parts.append(f"事件={'; '.join(event_descs)}")
        risk_evidence = '；'.join(risk_evidence_parts)

        event_details_out = []
        for ev in event_results[:5]:
            event_details_out.append({
                'event_type': ev.get('event_type', ''),
                'description': ev.get('description', ''),
                'direction': ev.get('direction', 0),
                'confidence': ev.get('confidence', 0),
                'event_date': ev.get('event_date', ''),
            })

        status_description = {
            'risk_level': risk_info['level'],
            'risk_detail': risk_info['detail'],
            'risk_light': risk_info['light'],
            'risk_factors': [f"{f['category']}：{f['factor']}（{f['severity']}）"
                             for f in risk_factors if f.get('satisfied')],
            'support_price': geo.get('support_price'),
            'resistance_price': geo.get('resistance_price'),
            'dist_to_support_pct': geo.get('dist_to_support_pct'),
            'dist_to_resistance_pct': geo.get('dist_to_resistance_pct'),
            'dist_to_prev_high_pct': geo.get('dist_to_prev_high_pct'),
            'rr_value': rr_info.get('rr_value'),
            'rr_level': rr_info['rr_level'],
            'rr_assessment': rr_info['rr_assessment'],
            'volatility_level': vol_info['level'],
            'atr_14d': vol_info['atr_14d'],
            'atr_pct': vol_info['atr_pct'],
            'volatility_percentile': vol_info['percentile'],
            'signal_days': geo.get('signal_days'),
            'invalidation': [item['condition'] for item in invalidation],
            'event_count': len(event_results),
            'event_details': event_details_out,
            'event_summary': [e.get('description', '') for e in event_results[:5] if e.get('description')],
            'risk_evidence': risk_evidence,
            'plain': plain,
            'support_resistance': f"防守位{geo.get('support_price', '无')}元（距现价{geo.get('dist_to_support_pct', '无')}），压力位{geo.get('resistance_price', '无')}元（距现价{geo.get('dist_to_resistance_pct', '无')}）",
        }

        judgment = {
            'level': risk_info['level'],
            'risk_level': risk_info['level'],
            'light': risk_info['light'],
            'overall_light': risk_info['light'],
            'overall_direction': -1 if risk_info['level'] in ('高', '极高') else (1 if risk_info['level'] in ('低',) else 0),
            'continuous_value': round(min(rr_info.get('rr_value', 0) / 3.0, 1.0), 4) if rr_info.get('rr_value') else 0.5,
        }

        conditions = [
            {'name': '风险等级', 'satisfied': risk_info['level'] in ('低', '中'),
             'actual': risk_info['level'], 'threshold': '低或中'},
            {'name': '盈亏比', 'satisfied': rr_info.get('rr_value', 0) >= 2.0 if rr_info.get('rr_value') else False,
             'actual': f"{rr_info.get('rr_value', '无')}" if rr_info.get('rr_value') else '数据不足',
             'threshold': '≥2R'},
            {'name': '波动率', 'satisfied': vol_info['level'] != 'high',
             'actual': vol_info['level'], 'threshold': '非high'},
            {'name': '无高风险事件', 'satisfied': not any(f.get('severity') in ('极高',) for f in risk_factors),
             'actual': str([f['factor'] for f in risk_factors if f.get('severity') == '极高']),
             'threshold': '无极高风险'},
            {'name': '防守位有效', 'satisfied': geo.get('support_price') is not None,
             'actual': str(geo.get('support_price', '无')), 'threshold': '有防守位'},
        ]
        satisfied_count = sum(1 for c in conditions if c['satisfied'])
        total_count = len(conditions)
        audit = {
            'conditions': conditions,
            'satisfied_count': satisfied_count,
            'total_count': total_count,
            'confidence': satisfied_count / total_count if total_count > 0 else 0,
        }

        return {
            'status_description': status_description,
            'judgment': judgment,
            'audit': audit,
        }

    def get_data_dependencies(self) -> list:
        return [
            'daily_cache (market_cache.db) — OHLCV用于几何化指标和波动率',
            'tags (pre_feat_cache) — risk_level / volatility_level / fina_health / catalyst_event / main_force_phase / valuation_level / turnover_rate',
            'dims (StatusEngine) — risk',
        ]
