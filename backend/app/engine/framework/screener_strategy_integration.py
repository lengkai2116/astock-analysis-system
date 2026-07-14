"""
选股系统 L3 策略引擎集成模块
将 volume_price_strategy / chanlun_strategy 接入选股 L3 流水线

架构定位（139号方案§2）:
  L1 风险剔除 → L2 筹码策略(主力识别) → L3 多策略验证(缠论+量价+因子)
                                     └── L3 是正交于筹码的独立验证层

输出格式符合 214 号方案 §2.1 的 strategy_detail 规范
"""
import logging
from datetime import datetime
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── L3 引擎健康度指标（生产监控用） ──
# 每次 run_screener 调用后更新，可通过 GET /api/v3/screener/stats 查看
_L3_ENGINE_HEALTH = {
    'total_runs': 0,
    'total_stocks_processed': 0,
    'total_errors': 0,
    'chanlun_errors': 0,
    'vp_errors': 0,
    'last_run_status': 'idle',
    'last_error': None,
    'last_error_time': None,
}


def _record_engine_error(error_type: str, symbol: str = ''):
    """记录 L3 引擎异常（供生产监控面板使用）"""
    _L3_ENGINE_HEALTH['total_errors'] += 1
    if error_type == 'chanlun':
        _L3_ENGINE_HEALTH['chanlun_errors'] += 1
    elif error_type == 'volume_price':
        _L3_ENGINE_HEALTH['vp_errors'] += 1
    _L3_ENGINE_HEALTH['last_error'] = f'{error_type}: {symbol}'
    _L3_ENGINE_HEALTH['last_error_time'] = str(datetime.now())
    # 自愈触发：单次运行错误率 > 20% 时提示
    total = _L3_ENGINE_HEALTH['total_stocks_processed']
    errs = _L3_ENGINE_HEALTH['total_errors']
    if total > 50 and errs > total * 0.2:
        logger.warning(
            f"L3 引擎错误率 {errs}/{total} ({errs/total*100:.0f}%) 超过 20%，"
            "建议检查数据源或策略引擎配置"
        )


def _score_to_grade(score: float) -> str:
    """0-10 评分映射到评级"""
    if score >= 8:
        return 'S'
    if score >= 7:
        return 'A'
    if score >= 5.5:
        return 'B'
    if score >= 4:
        return 'C'
    return 'D'


def _compute_chanlun_score(chanlun_result: Dict, df: pd.DataFrame = None) -> Tuple[float, str, str]:
    """
    从缠论分析结果提取选股评分（0-10）
    使用 ChanlunScorer 完整评分（11维度：买卖点/价格距离/背离/冲突检测/趋势/中枢）
    可选传入 df 进行级别递归验证（缠中说禅买卖点级别定理）

    Returns:
        (score_0_10, signal_text, direction)
    """
    if not chanlun_result or not chanlun_result.get('success'):
        return 0.0, '分析失败', 'neutral'

    signal_texts = []
    # 使用 ChanlunScorer 完整评分（与渠道二一致）
    try:
        from .chanlun_strategy import ChanlunScorer
        scorer = ChanlunScorer()
        latest_close = float(chanlun_result.get('latest_close', 0))
        score_result = scorer.score(chanlun_result, latest_close)
        raw_score = score_result.get('score', 50)  # 0-100
        signal = score_result.get('signal', 'HOLD')
        score = raw_score / 10.0
        direction = ('bullish' if signal in ('STRONG_BUY', 'BUY')
                     else 'bearish' if signal in ('STRONG_SELL', 'SELL')
                     else 'neutral')
        signal_texts.append(signal)
    except Exception as e:
        logger.debug(f"ChanlunScorer 评分失败，回退轻量评分: {e}")
        buy_pts = chanlun_result.get('buy_points', [])
        sell_pts = chanlun_result.get('sell_points', [])
        trend = chanlun_result.get('trend', 'unknown')
        summary = chanlun_result.get('summary', {})
        score = 5.0
        for bp in buy_pts:
            bp_type = (bp.type if hasattr(bp, 'type') else bp.get('type', '') if isinstance(bp, dict) else '')
            confidence = (bp.confidence if hasattr(bp, 'confidence') else bp.get('confidence', 0.5) if isinstance(bp, dict) else 0.5)
            if 'first_buy' in str(bp_type): score += 3.0 * confidence; signal_texts.append('一买')
            elif 'second_buy' in str(bp_type): score += 2.5 * confidence; signal_texts.append('二买')
            elif 'third_buy' in str(bp_type): score += 2.0 * confidence; signal_texts.append('三买')
        for sp in sell_pts:
            sp_type = (sp.type if hasattr(sp, 'type') else sp.get('type', '') if isinstance(sp, dict) else '')
            confidence = (sp.confidence if hasattr(sp, 'confidence') else sp.get('confidence', 0.5) if isinstance(sp, dict) else 0.5)
            if 'sell' in str(sp_type): score -= 2.0 * confidence; signal_texts.append(str(sp_type))
        if trend == 'up': score += 0.5
        elif trend == 'down': score -= 0.5
        if summary.get('total_zhongshu', 0) >= 1: score += 0.3
        direction = 'bullish' if score >= 6 else ('bearish' if score <= 4 else 'neutral')

    # === 级别递归验证（缠中说禅买卖点级别定理） ===
    if df is not None and len(df) >= 60:
        try:
            from .chanlun_level_validator import ChanlunLevelValidator
            validator = ChanlunLevelValidator()
            level_result = validator.validate(df)
            cross_score = level_result.get('cross_score', 0.5)
            adj = level_result.get('validation', {}).get('adjustment', 0)
            # cross_score: 0-1, 映射到 0-10 后再按调整量修正
            level_component = (cross_score - 0.5) * 2  # -1 到 +1
            score += level_component * 1.5 + adj * 10
            level_detail = '; '.join(level_result.get('details', []))
            if level_detail:
                signal_texts.append(f"级别({level_detail})")
        except Exception as e:
            logger.debug(f"级别递归验证失败: {e}")

    score = max(0.0, min(10.0, score))
    direction = 'bullish' if score >= 6 else ('bearish' if score <= 4 else 'neutral')
    signal_text = '+'.join(signal_texts) if signal_texts else '无明确信号'

    return round(score, 2), signal_text, direction


def _compute_volume_price_score(vp_result: Dict, symbol: str = None, df: pd.DataFrame = None) -> Tuple[float, str, str]:
    """
    从量价分析结果提取选股评分（0-10）
    可选传入 symbol+df 用于 RPS 计算和形态评分

    Returns:
        (score_0_10, signal_text, direction)
    """
    if not vp_result or not vp_result.get('success'):
        return 0.0, '分析失败', 'neutral'

    signal_output = vp_result.get('signal_output', {})
    director = signal_output.get('signal', 'NEUTRAL')
    confidence = signal_output.get('confidence', 0.0)
    signal_label = signal_output.get('signal_label', '')
    stage = vp_result.get('stage', {})

    # VP 策略输出 BUY/SELL/WATCH/HOLD，映射到基础分
    dir_map = {'BUY': 7.0, 'BULLISH': 7.0, 'WATCH': 5.5, 'HOLD': 5.0,
               'NEUTRAL': 5.0, 'SELL': 3.0, 'BEARISH': 3.0}
    base = dir_map.get(director, 5.0)
    score = base * (0.5 + confidence * 0.5)

    # 阶段加分
    current_stage = stage.get('current_stage', '')
    if current_stage in ('UPTREND_ACTIVE',):
        score += 0.5
    elif current_stage in ('DOWNTREND_ACTIVE',):
        score -= 0.5

    # 量价评分引用筹码数据：筹码单峰密集加分（Wiki: 量价形态打分系统中的加分项）
    if symbol is not None:
        try:
            from app.data.enhanced_cache_manager import get_ecm_instance
            ecm = get_ecm_instance()
            chip_df = ecm.get_cached_chip_distribution(symbol) if hasattr(ecm, 'get_cached_chip_distribution') else None
            if chip_df is not None and not chip_df.empty:
                chip_bins = chip_df['chip_ratio'].dropna().values if 'chip_ratio' in chip_df.columns else None
                if chip_bins is not None and len(chip_bins) > 0:
                    max_ratio = chip_bins.max()
                    if max_ratio > 0.15:  # 单峰密集
                        score += 0.5
        except Exception:
            pass

    # ── RPS 相对强弱（需全市场数据） ──
    if symbol is not None and df is not None and len(df) >= 20:
        try:
            from app.data.enhanced_cache_manager import get_ecm_instance
            ecm = get_ecm_instance()
            latest_close = float(df['close'].iloc[-1])
            close_20d = float(df['close'].iloc[-21]) if len(df) >= 21 else latest_close
            ret_20d = (latest_close / close_20d - 1) * 100
            trade_date = str(df['trade_date'].iloc[-1]) if 'trade_date' in df.columns else ''
            if trade_date:
                row = ecm.conn.execute(
                    "SELECT COUNT(*) FROM daily_cache WHERE trade_date=?", [trade_date]
                ).fetchone()
                above = ecm.conn.execute(
                    "SELECT COUNT(*) FROM daily_cache WHERE trade_date=? AND pct_chg > ?",
                    [trade_date, ret_20d]
                ).fetchone()
                if row and row[0] > 0 and above:
                    rps = above[0] / row[0] * 100
                    if rps > 85:
                        score += 1.0
                        signal_label = (signal_label or '') + '+RPS'
                    elif rps > 70:
                        score += 0.5
        except Exception:
            pass

    score = max(0.0, min(10.0, score))
    direction_str = (
        'bullish' if director in ('BUY', 'BULLISH')
        else 'bearish' if director in ('SELL', 'BEARISH')
        else 'neutral'
    )
    signal_text = signal_label if signal_label else director

    return round(score, 2), signal_text, direction_str


def _compute_combined_score(chanlun_score: float, vp_score: float,
                            chanlun_dir: str, vp_dir: str,
                            weights: dict = None,
                            factor_score: float = 0.0,
                            vibe_bonus: float = 0.0) -> float:
    """
    综合评分（L3 多策略共振评分，带权重参数）

    权重参数格式: {'chanlun': 0.35, 'vp': 0.30, 'factor': 0.25, 'vibe': 0.10}
    权重 0 的策略不参与计算，未提供的策略使用默认等权。

    筹码评分已在 L2 独立完成，L3 不做筹码分析。
    """
    # 应用前端传入的权重，未指定的策略使用剩余等权
    default_w = {'chanlun': 0.4, 'vp': 0.4, 'factor': 0.2, 'vibe': 0.0}
    if weights:
        default_w.update(weights)

    w_cl = max(0.0, default_w.get('chanlun', 0.0))
    w_vp = max(0.0, default_w.get('vp', 0.0))
    w_fx = max(0.0, default_w.get('factor', 0.0))
    w_vb = max(0.0, default_w.get('vibe', 0.0))

    total_w = w_cl + w_vp + w_fx + w_vb
    if total_w <= 0:
        return 5.0  # 所有权重为0时返回中性分

    score = (chanlun_score * w_cl + vp_score * w_vp +
             factor_score * w_fx + vibe_bonus * w_vb) / total_w

    # 方向一致性加分: 缠论和量价同向 +1（仅当两者权重都>0时生效）
    if w_cl > 0 and w_vp > 0 and chanlun_dir == vp_dir and chanlun_dir != 'neutral':
        score += 0.5

    return min(10.0, max(0.0, score))


# ── 因子中⽂名 → 计算函数映射表 ──
# 供 _compute_factor_score 将 PRESET_COMBOS 中的因子名映射为实际计算
_FACTOR_COMPUTERS = {}

def _register_factor(name, func):
    _FACTOR_COMPUTERS[name] = func

# ECM 因子注册（需要 symbol + dm 参数）。_compute_factor_score 调用时传入这些参数
def _register_ecm_factor(name, func):
    """注册需要ECM数据源的因子，调用时传入 (c, v, symbol, dm)"""
    _FACTOR_COMPUTERS[name] = func

def _f_momentum(closes, volumes, days=20):
    """动量因子：N日收益率 → 0-10"""
    if len(closes) < days + 1:
        return None
    ret = (closes[-1] / closes[-days-1]) - 1
    return max(0, min(10, (ret * 100 + 10) / 2))

def _f_rsi(closes, volumes, period=14):
    """RSI因子 → 0-10"""
    if len(closes) < period + 2:
        return None
    import numpy as np
    deltas = np.diff(closes[-(period+1):])
    gains = np.sum(deltas[deltas > 0])
    losses = abs(np.sum(deltas[deltas < 0]))
    if losses > 1e-9:
        rsi = 100 - 100 / (1 + gains / losses)
    elif gains > 0:
        rsi = 100
    else:
        rsi = 50
    return max(0, min(10, (rsi - 30) / 4))

def _f_volume_ratio(closes, volumes, period=5):
    """量比因子 → 0-10"""
    if len(volumes) < period + 16:
        return None
    import numpy as np
    vol_recent = np.mean(volumes[-period:])
    vol_base = np.mean(volumes[-(period+15):-period])
    if vol_base < 1e-9:
        return 5.0
    vr = vol_recent / vol_base
    return max(0, min(10, vr * 2.5))

def _f_volatility(closes, volumes, period=20):
    """波动率因子（低波=高分）→ 0-10"""
    import numpy as np
    if len(closes) < period + 1:
        return None
    vol = np.std(closes[-period:]) / max(np.mean(closes[-period:]), 1e-9)
    return max(0, min(10, (1 - vol) * 10))

def _f_reversal(closes, volumes, period=5):
    """反转因子：短期涨多了扣分 → 0-10（与动量反向）"""
    mom = _f_momentum(closes, volumes, period)
    if mom is None:
        return None
    return 10 - mom

def _f_bias(closes, volumes, period=20):
    """均线乖离率 → 0-10"""
    import numpy as np
    if len(closes) < period + 1:
        return None
    ma = np.mean(closes[-period:])
    bias = (closes[-1] - ma) / max(ma, 1e-9)
    # bias -5% ≈ 2.5分, 0% ≈ 5分, +5% ≈ 7.5分
    return max(0, min(10, 5 + bias * 50))

# 注册所有可计算的因子（含 PRESET_COMBOS 中的别名）
_register_factor('20日动量', lambda c, v: _f_momentum(c, v, 20))
_register_factor('5日动量', lambda c, v: _f_momentum(c, v, 5))
_register_factor('动量因子(MOM)', lambda c, v: _f_momentum(c, v, 20))
_register_factor('截面动量', lambda c, v: _f_momentum(c, v, 20))
_register_factor('14日RSI', lambda c, v: _f_rsi(c, v, 14))
_register_factor('5日量比', lambda c, v: _f_volume_ratio(c, v, 5))
_register_factor('量比', lambda c, v: _f_volume_ratio(c, v, 5))
_register_factor('20日波动率', lambda c, v: _f_volatility(c, v, 20))
_register_factor('低波因子', lambda c, v: _f_volatility(c, v, 20))
_register_factor('5日反转因子', lambda c, v: _f_reversal(c, v, 5))
_register_factor('20日均线乖离率', lambda c, v: _f_bias(c, v, 20))

# 动量/量价/乖离的所有别名变体
_register_factor('短期动量', lambda c, v: _f_momentum(c, v, 5))
_register_factor('动量', lambda c, v: _f_momentum(c, v, 20))
_register_factor('均线乖离率', lambda c, v: _f_bias(c, v, 20))
_register_factor('20日换手率', lambda c, v: _f_volume_ratio(c, v, 20))

# BOCIASI 情绪因子（基于四象限的市场情绪感知）
def _f_sentiment(closes, volumes):
    """情绪因子：BOCIASI四象限感知 → 0-10"""
    try:
        from app.engine.framework.bociasi_quadrant import BociasiQuadrantAnalyzer
        bq = BociasiQuadrantAnalyzer()
        q = bq.analyze()
        mult = q.get('weight_multiplier', 1.0)
        return max(0, min(10, (mult - 0.7) * 15 + 5))
    except Exception:
        return 5.0
_register_factor('情绪因子', _f_sentiment)

# BOCIASI 快线（个股级情绪，基于OHLCV，~5ms/只）
def _f_bociasi_quickline(closes, volumes):
    """个股BOCIASI快线：基于短期价量判断情绪 → 0-10"""
    try:
        import numpy as np
        if len(closes) < 20:
            return 5.0
        score = 5.0
        # 价格动量（5日涨幅）
        mom_5 = (closes[-1] / closes[-6] - 1) * 100 if len(closes) >= 6 else 0
        if mom_5 > 3:
            score += 2.0
        elif mom_5 > 1:
            score += 1.0
        elif mom_5 < -3:
            score -= 2.0
        elif mom_5 < -1:
            score -= 1.0
        # 成交量确认
        if len(volumes) >= 20:
            vol_ratio = volumes[-1] / (np.mean(volumes[-20:-1]) + 1e-9)
            if vol_ratio > 1.5 and mom_5 > 0:
                score += 1.0  # 放量上涨
            elif vol_ratio > 1.5 and mom_5 < 0:
                score -= 1.0  # 放量下跌
        # 价格相对均线位置
        ma_5 = np.mean(closes[-5:]) if len(closes) >= 5 else closes[-1]
        if closes[-1] > ma_5:
            score += 0.5
        else:
            score -= 0.5
        return max(0, min(10, score))
    except Exception:
        return 5.0
_register_factor('BOCIASI快线', _f_bociasi_quickline)
# ══════════════════════════════════════════════════════════════════
# ECM 数据源因子（需要 symbol + dm 参数）
# ══════════════════════════════════════════════════════════════════

def _f_ep_ratio(closes, volumes, symbol, dm):
    """市盈率倒数(EP): daily_basic_cache.pe_ttm → 0-10"""
    if dm is None or symbol is None:
        return None
    try:
        basic = dm.get_cached_daily_basic(symbol)
        if basic is not None and not basic.empty and 'pe_ttm' in basic.columns:
            pe = float(basic['pe_ttm'].dropna().iloc[-1])
            if pe > 0 and pe < 1e5:
                return max(0, min(10, (1/pe) * 100))
    except Exception:
        pass
    return None

def _f_roe(closes, volumes, symbol, dm):
    """ROE: fina_indicator_cache.roe → 0-10"""
    if dm is None or symbol is None:
        return None
    try:
        fina = dm.get_cached_fina_indicator(symbol)
        if fina is not None and not fina.empty and 'roe' in fina.columns:
            roe = float(fina['roe'].dropna().iloc[-1])
            # roe (%) 映射: 0%→3, 10%→5, 20%→7, 30%→9
            return max(0, min(10, 3 + roe * 20))
    except Exception:
        pass
    return None

def _f_dividend(closes, volumes, symbol, dm):
    """股息率: daily_basic_cache.dv_ratio → 0-10"""
    if dm is None or symbol is None:
        return None
    try:
        basic = dm.get_cached_daily_basic(symbol)
        if basic is not None and not basic.empty and 'dv_ratio' in basic.columns:
            dv = float(basic['dv_ratio'].dropna().iloc[-1])
            return max(0, min(10, dv * 2))
    except Exception:
        pass
    return None

def _f_big_order(closes, volumes, symbol, dm):
    """大单净买入: moneyflow_cache 5日累计大单净额 → 0-10"""
    if dm is None or symbol is None:
        return None
    try:
        mf = dm.get_cached_moneyflow(symbol)
        if mf is not None and not mf.empty and 'net_lg_amount' in mf.columns:
            net = mf['net_lg_amount'].dropna().tail(5).sum()
            # 归一化: 取绝对值对数 + 正负号
            if abs(net) > 0:
                return max(0, min(10, 5 + (net / (abs(net) + 1e8)) * 5))
    except Exception:
        pass
    return None

def _f_moneyflow_strength(closes, volumes, symbol, dm):
    """资金流向强度: moneyflow_cache 综合 → 0-10"""
    if dm is None or symbol is None:
        return None
    try:
        mf = dm.get_cached_moneyflow(symbol)
        if mf is not None and not mf.empty:
            cols = ['net_lg_amount', 'net_elg_amount']
            cols = [c for c in cols if c in mf.columns]
            if cols:
                total_net = mf[cols].dropna().tail(5).sum().sum()
                total_amount = (mf.get('buy_lg_amount', pd.Series([0]*len(mf))).fillna(0).tail(5).sum() +
                                mf.get('sell_lg_amount', pd.Series([0]*len(mf))).fillna(0).tail(5).sum())
                if total_amount > 0:
                    ratio = total_net / total_amount
                    return max(0, min(10, 5 + ratio * 20))
    except Exception:
        pass
    return None

def _f_turnover_change(closes, volumes, symbol, dm):
    """换手率变化: daily_basic_cache.turnover_rate 环比 → 0-10"""
    if dm is None or symbol is None:
        return None
    try:
        basic = dm.get_cached_daily_basic(symbol)
        if basic is not None and not basic.empty and 'turnover_rate' in basic.columns:
            tr = basic['turnover_rate'].dropna().tail(10)
            if len(tr) >= 5:
                recent = tr.tail(5).mean()
                prev = tr.head(5).mean()
                if prev > 0:
                    change = recent / prev
                    # 换手率上升: >1 加分; 下降: <1 扣分
                    return max(0, min(10, 5 + (change - 1) * 10))
    except Exception:
        pass
    return None

def _f_revenue_growth(closes, volumes, symbol, dm):
    """营收增长率: income_cache 同比 → 0-10"""
    if dm is None or symbol is None:
        return None
    try:
        income = dm.get_cached_income(symbol) if hasattr(dm, 'get_cached_income') else None
        if income is None or income.empty or 'revenue' not in income.columns:
            return None
        revenues = income['revenue'].dropna()
        if len(revenues) >= 2:
            # 最近两期同比
            yoy = (revenues.iloc[-1] - revenues.iloc[-2]) / abs(revenues.iloc[-2]) if revenues.iloc[-2] != 0 else 0
            return max(0, min(10, 5 + yoy * 20))
    except Exception:
        pass
    return None

def _f_profit_growth(closes, volumes, symbol, dm):
    """净利润增长率: fina_indicator_cache 同比 → 0-10"""
    if dm is None or symbol is None:
        return None
    try:
        fina = dm.get_cached_fina_indicator(symbol)
        if fina is not None and not fina.empty:
            # 取净利润增长率（如果直接有则用，否则计算）
            if 'profit_ttm' in fina.columns:
                profits = fina['profit_ttm'].dropna()
                if len(profits) >= 2:
                    yoy = (profits.iloc[-1] - profits.iloc[-2]) / abs(profits.iloc[-2]) if profits.iloc[-2] != 0 else 0
                    return max(0, min(10, 5 + yoy * 10))
    except Exception:
        pass
    return None

def _f_debt_ratio(closes, volumes, symbol, dm):
    """资产负债率: balancesheet_cache → 0-10（越低分越高）"""
    if dm is None or symbol is None:
        return None
    try:
        bs = dm.get_cached_balancesheet(symbol) if hasattr(dm, 'get_cached_balancesheet') else None
        if bs is None or bs.empty:
            return None
        if 'total_liab' in bs.columns and 'total_assets' in bs.columns:
            liab = float(bs['total_liab'].dropna().iloc[-1])
            assets = float(bs['total_assets'].dropna().iloc[-1])
            if assets > 0:
                ratio = liab / assets
                # 资产负债率: 20%→8分, 50%→5分, 80%→2分
                return max(0, min(10, 10 - ratio * 10))
    except Exception:
        pass
    return None

# ── 注册 ECM 因子 ──
_register_ecm_factor('市盈率倒数(EP)', lambda c, v, s=None, d=None: _f_ep_ratio(c, v, s, d))
_register_ecm_factor('ROE', lambda c, v, s=None, d=None: _f_roe(c, v, s, d))
_register_ecm_factor('股息率', lambda c, v, s=None, d=None: _f_dividend(c, v, s, d))
_register_ecm_factor('大单净买入', lambda c, v, s=None, d=None: _f_big_order(c, v, s, d))
_register_ecm_factor('资金流向强度', lambda c, v, s=None, d=None: _f_moneyflow_strength(c, v, s, d))
_register_ecm_factor('换手率变化', lambda c, v, s=None, d=None: _f_turnover_change(c, v, s, d))
_register_ecm_factor('营收增长率', lambda c, v, s=None, d=None: _f_revenue_growth(c, v, s, d))
_register_ecm_factor('净利润增长率', lambda c, v, s=None, d=None: _f_profit_growth(c, v, s, d))
_register_ecm_factor('资产负债率', lambda c, v, s=None, d=None: _f_debt_ratio(c, v, s, d))

# ══════════════════════════════════════════════════════════════════
# Fama-French 五因子（横截面分组计算，需全市场数据）
# ══════════════════════════════════════════════════════════════════

_FF_CACHE = {}  # {date: {factor_name: {ts_code: score}}}

def _refresh_ff_cache(dm, trade_date):
    """刷新 Fama-French 横截面计算结果缓存"""
    if not dm:
        return
    import numpy as np
    cache_key = str(trade_date)
    if cache_key in _FF_CACHE:
        return
    try:
        from app.data.enhanced_cache_manager import get_ecm_instance
        ecm = get_ecm_instance()
        # 获取当日所有股票的基础数据
        daily_df = ecm._query_df(
            "SELECT ts_code, pct_chg, close FROM daily_cache WHERE trade_date=?",
            [cache_key]
        )
        if daily_df is None or daily_df.empty:
            return

        basic_df = ecm._query_df(
            "SELECT ts_code, circ_mv, pe_ttm FROM daily_basic_cache WHERE trade_date=?",
            [cache_key]
        )
        # 获取财务数据（最新一期）
        fina_df = ecm._query_df(
            "SELECT ts_code, roe FROM fina_indicator_cache"
        )
        bs_df = ecm._query_df(
            "SELECT ts_code, total_assets FROM balancesheet_cache"
        )

        # 合并数据
        merged = daily_df.merge(basic_df, on='ts_code', how='left') if basic_df is not None else daily_df
        if fina_df is not None and not fina_df.empty:
            # 取每个股票最新的 ROE
            fina_latest = fina_df.dropna(subset=['roe']).groupby('ts_code').last().reset_index()
            merged = merged.merge(fina_latest[['ts_code', 'roe']], on='ts_code', how='left')
        if bs_df is not None and not bs_df.empty:
            bs_latest = bs_df.dropna(subset=['total_assets']).groupby('ts_code').last().reset_index()
            merged = merged.merge(bs_latest[['ts_code', 'total_assets']], on='ts_code', how='left')

        if merged.empty:
            return

        # 全市场平均收益 (Market Factor)
        all_returns = merged['pct_chg'].dropna().values
        if len(all_returns) == 0:
            return
        market_ret = float(np.mean(all_returns))

        # Market Factor: 每只股票 = 全市场平均收益归一化到 0-10
        market_scores = {}
        # SMB/HML/RMW/CMA: 分组后每组内收益相对市场超额归一化
        # 用 DataFrame 分组
        result = {'市场因子': {}, '规模因子(SMB)': {}, '价值因子(HML)': {},
                  '盈利因子(RMW)': {}, '投资因子(CMA)': {}}

        # 市场因子：个股收益相对于市场的强弱
        for _, row in merged.iterrows():
            ts_code = row['ts_code']
            ret = row.get('pct_chg', 0)
            if pd.isna(ret):
                continue
            # 相对于市场平均，归一化到 0-10
            rel = ret - market_ret
            result['市场因子'][ts_code] = max(0, min(10, 5 + rel * 10))

        # SMB: 按 circ_mv 分组（小盘/大盘）
        merged_mv = merged[merged['circ_mv'].notna()].copy()
        if len(merged_mv) >= 20:
            merged_mv['mv_group'] = pd.qcut(merged_mv['circ_mv'], 4, labels=['small', 'mid_low', 'mid_high', 'big'],
                                            duplicates='drop')
            for _, row in merged_mv.iterrows():
                ts_code = row['ts_code']
                grp = row['mv_group']
                ret = row.get('pct_chg', 0)
                if pd.isna(ret):
                    continue
                if grp == 'small':
                    # 小盘溢价 = 小盘收益 - 大盘收益
                    big_ret = merged_mv[merged_mv['mv_group'] == 'big']['pct_chg'].mean()
                    if pd.notna(big_ret):
                        smb_val = ret - big_ret
                        result['规模因子(SMB)'][ts_code] = max(0, min(10, 5 + smb_val * 10))
                elif grp == 'big':
                    small_ret = merged_mv[merged_mv['mv_group'] == 'small']['pct_chg'].mean()
                    if pd.notna(small_ret):
                        smb_val = small_ret - ret
                        result['规模因子(SMB)'][ts_code] = max(0, min(10, 5 + smb_val * 10))

        # HML: 按 pe_ttm 分组（高PE=成长，低PE=价值）
        merged_pe = merged[merged['pe_ttm'].notna() & (merged['pe_ttm'] > 0) & (merged['pe_ttm'] < 1e4)].copy()
        if len(merged_pe) >= 20:
            merged_pe['pe_group'] = pd.qcut(merged_pe['pe_ttm'], 3, labels=['value', 'neutral', 'growth'],
                                            duplicates='drop')
            for _, row in merged_pe.iterrows():
                ts_code = row['ts_code']
                grp = row['pe_group']
                ret = row.get('pct_chg', 0)
                if pd.isna(ret):
                    continue
                if grp == 'value':
                    # 价值溢价 = 价值股收益 - 成长股收益
                    growth_ret = merged_pe[merged_pe['pe_group'] == 'growth']['pct_chg'].mean()
                    if pd.notna(growth_ret):
                        hml_val = ret - growth_ret
                        result['价值因子(HML)'][ts_code] = max(0, min(10, 5 + hml_val * 10))
                elif grp == 'growth':
                    value_ret = merged_pe[merged_pe['pe_group'] == 'value']['pct_chg'].mean()
                    if pd.notna(value_ret):
                        hml_val = value_ret - ret
                        result['价值因子(HML)'][ts_code] = max(0, min(10, 5 + hml_val * 10))
                else:  # neutral
                    result['价值因子(HML)'][ts_code] = 5.0

        # RMW: 按 ROE 分组（高盈利/低盈利）
        merged_roe = merged[merged['roe'].notna()].copy()
        if len(merged_roe) >= 20:
            merged_roe['roe_group'] = pd.qcut(merged_roe['roe'], 3, labels=['weak', 'neutral', 'robust'],
                                              duplicates='drop')
            for _, row in merged_roe.iterrows():
                ts_code = row['ts_code']
                grp = row['roe_group']
                ret = row.get('pct_chg', 0)
                if pd.isna(ret):
                    continue
                if grp == 'robust':
                    weak_ret = merged_roe[merged_roe['roe_group'] == 'weak']['pct_chg'].mean()
                    if pd.notna(weak_ret):
                        rmw_val = ret - weak_ret
                        result['盈利因子(RMW)'][ts_code] = max(0, min(10, 5 + rmw_val * 10))
                elif grp == 'weak':
                    robust_ret = merged_roe[merged_roe['roe_group'] == 'robust']['pct_chg'].mean()
                    if pd.notna(robust_ret):
                        rmw_val = robust_ret - ret
                        result['盈利因子(RMW)'][ts_code] = max(0, min(10, 5 + rmw_val * 10))
                else:  # neutral
                    result['盈利因子(RMW)'][ts_code] = 5.0

        # CMA: 按 total_assets 增长率分组
        merged_cma = merged[merged['total_assets'].notna()].copy()
        if len(merged_cma) >= 20:
            merged_cma['asset_growth'] = merged_cma.groupby('ts_code')['total_assets'].pct_change()
            merged_cma_valid = merged_cma[merged_cma['asset_growth'].notna()].copy()
            if len(merged_cma_valid) >= 20:
                merged_cma_valid['cma_group'] = pd.qcut(merged_cma_valid['asset_growth'], 3,
                                                        labels=['conservative', 'neutral', 'aggressive'],
                                                        duplicates='drop')
                for _, row in merged_cma_valid.iterrows():
                    ts_code = row['ts_code']
                    grp = row['cma_group']
                    ret = row.get('pct_chg', 0)
                    if pd.isna(ret):
                        continue
                    if grp == 'conservative':
                        agg_ret = merged_cma_valid[merged_cma_valid['cma_group'] == 'aggressive']['pct_chg'].mean()
                        if pd.notna(agg_ret):
                            cma_val = ret - agg_ret
                            result['投资因子(CMA)'][ts_code] = max(0, min(10, 5 + cma_val * 10))
                    elif grp == 'aggressive':
                        cons_ret = merged_cma_valid[merged_cma_valid['cma_group'] == 'conservative']['pct_chg'].mean()
                        if pd.notna(cons_ret):
                            cma_val = cons_ret - ret
                            result['投资因子(CMA)'][ts_code] = max(0, min(10, 5 + cma_val * 10))
                    else:
                        result['投资因子(CMA)'][ts_code] = 5.0

        _FF_CACHE[cache_key] = result
        logger.debug(f"Fama-French 横截面计算完成: {len(merged)} 只股票")
    except Exception as e:
        logger.debug(f"Fama-French 计算失败: {e}")

def _f_market_factor(closes, volumes, symbol, dm):
    """市场因子：全市场加权收益 → 0-10"""
    if dm is None or symbol is None:
        return None
    try:
        # 从 closes 的最后一根 K 线获取 trade_date
        _refresh_ff_cache(dm, _get_latest_date(closes))
        for cache_key in _FF_CACHE:
            scores = _FF_CACHE[cache_key].get('市场因子', {})
            if symbol in scores:
                return scores[symbol]
    except Exception:
        pass
    return None

def _f_smb(closes, volumes, symbol, dm):
    """规模因子(SMB): 小盘股相对大盘超额 → 0-10"""
    if dm is None or symbol is None:
        return None
    try:
        _refresh_ff_cache(dm, _get_latest_date(closes))
        for cache_key in _FF_CACHE:
            scores = _FF_CACHE[cache_key].get('规模因子(SMB)', {})
            if symbol in scores:
                return scores[symbol]
    except Exception:
        pass
    return None

def _f_hml(closes, volumes, symbol, dm):
    """价值因子(HML): 低PE相对高PE超额 → 0-10"""
    if dm is None or symbol is None:
        return None
    try:
        _refresh_ff_cache(dm, _get_latest_date(closes))
        for cache_key in _FF_CACHE:
            scores = _FF_CACHE[cache_key].get('价值因子(HML)', {})
            if symbol in scores:
                return scores[symbol]
    except Exception:
        pass
    return None

def _f_rmw(closes, volumes, symbol, dm):
    """盈利因子(RMW): 高ROE相对低ROE超额 → 0-10"""
    if dm is None or symbol is None:
        return None
    try:
        _refresh_ff_cache(dm, _get_latest_date(closes))
        for cache_key in _FF_CACHE:
            scores = _FF_CACHE[cache_key].get('盈利因子(RMW)', {})
            if symbol in scores:
                return scores[symbol]
    except Exception:
        pass
    return None

def _f_cma(closes, volumes, symbol, dm):
    """投资因子(CMA): 低资产增长相对高资产增长超额 → 0-10"""
    if dm is None or symbol is None:
        return None
    try:
        _refresh_ff_cache(dm, _get_latest_date(closes))
        for cache_key in _FF_CACHE:
            scores = _FF_CACHE[cache_key].get('投资因子(CMA)', {})
            if symbol in scores:
                return scores[symbol]
    except Exception:
        pass
    return None

def _get_latest_date(closes):
    """从 ndarray 推断最新日期（当前场景下返回 today 字符串）"""
    from datetime import date
    return str(date.today())

# ── 注册 Fama-French 因子 ──
_register_ecm_factor('市场因子', _f_market_factor)
_register_ecm_factor('规模因子(SMB)', _f_smb)
_register_ecm_factor('规模因子', _f_smb)  # 别名（用于 p4）
_register_ecm_factor('价值因子(HML)', _f_hml)
_register_ecm_factor('价值因子', _f_hml)  # 别名（用于 p4）
_register_ecm_factor('盈利因子(RMW)', _f_rmw)
_register_ecm_factor('投资因子(CMA)', _f_cma)
_register_ecm_factor('投资因子', _f_cma)  # 别名（用于 p4）

# 质量因子（基于 ROE + 低负债的综合评分）
def _f_quality(closes, volumes, symbol, dm):
    """质量因子: ROE高 + 负债低 → 0-10（综合指标）"""
    if dm is None or symbol is None:
        return None
    try:
        roe_score = _f_roe(closes, volumes, symbol, dm)
        debt_score = _f_debt_ratio(closes, volumes, symbol, dm)
        if roe_score is not None and debt_score is not None:
            return round((roe_score * 0.6 + debt_score * 0.4), 2)
        return roe_score or debt_score or None
    except Exception:
        return None
_register_ecm_factor('质量因子', _f_quality)

# 成长因子（基于营收 + 利润增长的综合评分）
def _f_growth(closes, volumes, symbol, dm):
    """成长因子: 营收增长 + 利润增长 → 0-10"""
    if dm is None or symbol is None:
        return None
    try:
        rev_score = _f_revenue_growth(closes, volumes, symbol, dm)
        profit_score = _f_profit_growth(closes, volumes, symbol, dm)
        scores = [s for s in [rev_score, profit_score] if s is not None]
        if scores:
            return round(sum(scores) / len(scores), 2)
    except Exception:
        pass
    return None
_register_ecm_factor('成长因子', _f_growth)


def _compute_factor_score(df, symbol=None, combo_ids=None, data_dict=None, dm=None):
    """
    根据选中的因子组合计算因子评分（0-10）

    遍历每个选中组合的因子定义，用 _FACTOR_COMPUTERS 逐个计算，
    按权重加权得到每个组合的分，再对所有组合等权平均。

    Args:
        df: 股票的 OHLCV DataFrame
        symbol: 股票代码（用于获取 ECM 数据）
        combo_ids: 选中的组合 ID 列表（如 ['p1','p3']）
        data_dict: {symbol: DataFrame} 全量数据池（当前未使用，预留）
        dm: DataManager 实例（用于 ECM 数据获取）

    Returns:
        float: 0-10 因子评分
    """
    import numpy as np
    closes = df['close'].values
    volumes = (df['vol'].values if 'vol' in df.columns
               else df.get('amount', df['close']).values)

    if not combo_ids:
        return 0.0

    # 导入 PRESET_COMBOS
    try:
        from app.routes.factors import PRESET_COMBOS
    except ImportError:
        logger.warning("PRESET_COMBOS 导入失败，使用通用因子评分")
        return _fallback_factor_score(closes, volumes)

    # 构建组合 ID → 组合定义 的映射
    combo_map = {c['id']: c for c in PRESET_COMBOS}

    combo_scores = []
    for cid in combo_ids:
        combo = combo_map.get(cid)
        if not combo:
            continue
        factors = combo.get('factors', [])
        if not factors:
            continue

        # 逐因子计算
        factor_vals = []
        total_weight = 0
        for f in factors:
            fname = f.get('n', '')
            fweight = f.get('w', 0)
            computer = _FACTOR_COMPUTERS.get(fname)
            if computer:
                try:
                    # ECM 因子需要 symbol+dm，普通因子不需要
                    val = computer(closes, volumes, symbol, dm)
                except TypeError:
                    val = computer(closes, volumes)
                if val is not None:
                    factor_vals.append(val * fweight)
                    total_weight += fweight
            else:
                # 未注册的因子用中性分 5
                factor_vals.append(5.0 * fweight)
                total_weight += fweight

        if total_weight > 0:
            combo_score = sum(factor_vals) / total_weight
            combo_scores.append(combo_score)

    if not combo_scores:
        return 0.0

    # 所有选中的组合等权平均
    base_score = sum(combo_scores) / len(combo_scores)

    # BOCIASI 四象限情绪加权
    try:
        from app.engine.framework.bociasi_quadrant import BociasiQuadrantAnalyzer
        bq = BociasiQuadrantAnalyzer()
        quadrant = bq.analyze()
        mult = quadrant.get('weight_multiplier', 1.0)
        # 只在中性区域(MM)不做调整，极端情绪(LL/HH)做±15%调整
        if abs(mult - 1.0) > 0.01:
            adjusted = base_score * mult
            adjusted = max(0, min(10, adjusted))
            logger.debug(f"BOCIASI情绪加权: {quadrant['quadrant']} mult={mult:.2f} "
                         f"{base_score:.2f}→{adjusted:.2f}")
            return round(adjusted, 2)
    except Exception as e:
        logger.debug(f"BOCIASI情绪加权失败: {e}")

    return round(base_score, 2)


def _fallback_factor_score(closes, volumes):
    """通用因子评分（无组合选择时的回退）"""
    scores = []
    # 动量
    m = _f_momentum(closes, volumes, 20)
    if m is not None: scores.append(m)
    # RSI
    r = _f_rsi(closes, volumes, 14)
    if r is not None: scores.append(r)
    # 量比
    v = _f_volume_ratio(closes, volumes, 5)
    if v is not None: scores.append(v)
    # 波动率
    vol = _f_volatility(closes, volumes, 20)
    if vol is not None: scores.append(vol)
    return sum(scores) / len(scores) if scores else 5.0


def _compute_vibe_bonus(vibe_strategy_ids: list, df=None, strategy_details: list = None) -> float:
    """
    计算 Vibe Coding 策略评分（真实执行模式）

    当提供 df 和 strategy_details 时，真实执行每只股票的策略代码。
    否则回退到差异化加分（无代码可执行时的降级）。

    Args:
        vibe_strategy_ids: 选中的策略 ID 列表（来自前端）
        df: 当前股票的 OHLCV DataFrame（用于代码执行）
        strategy_details: 策略详情（含 code_template）

    Returns:
        float: 0-10 评分
    """
    import numpy as np

    if not vibe_strategy_ids:
        return 0.0

    # ── 真实执行模式 ──
    if df is not None and strategy_details:
        total_score = 0.0
        executed_count = 0
        for sid in vibe_strategy_ids:
            detail = next((s for s in strategy_details if s.get('id') == sid), None)
            if not detail:
                continue
            code = detail.get('code_template') or detail.get('code', '')
            if not code or code.strip() == '':
                continue
            try:
                score = _execute_single_strategy(code, df)
                total_score += score
                executed_count += 1
            except Exception as e:
                logger.debug(f"Vibe策略执行失败 {sid}: {e}")
                _record_engine_error('vibe', sid)
                continue
        if executed_count > 0:
            return min(10.0, total_score / executed_count)
        return 0.0

    # ── 降级模式：无详情时使用默认值 ──
    extra = len(vibe_strategy_ids) * 0.5
    return min(5.0, extra)


def _execute_single_strategy(code: str, df) -> float:
    """
    执行单个 Vibe 策略代码，返回 0-10 评分

    注入变量：
      - open, high, low, close, volume: pandas Series
      - MA(s, n): 移动平均
      - STD(s, n): 标准差
      - 所有 Series 的 .iloc, .values, 标准 pandas 运算

    捕获策略输出的 signal 变量（0/1/-1 或 0-100 数值）
    """
    import numpy as np
    import pandas as pd
    import re

    # 准备数据
    close = df['close'].astype(float)
    high = df['high'].astype(float) if 'high' in df else close
    low = df['low'].astype(float) if 'low' in df else close
    open_p = df['open'].astype(float) if 'open' in df else close
    volume = df['vol'].astype(float) if 'vol' in df else (
        df['amount'].astype(float) if 'amount' in df else pd.Series(np.ones(len(df))))
    date_idx = df['trade_date'] if 'trade_date' in df else pd.Series(range(len(df)))

    # 预计算常用指标
    def _ma(s, n):
        return s.rolling(window=n, min_periods=1).mean()
    def _std(s, n):
        return s.rolling(window=n, min_periods=1).std()
    def _rsi(s, n=14):
        delta = s.diff()
        gain = delta.where(delta > 0, 0).rolling(n).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(n).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))
    def _macd(s):
        ema12 = s.ewm(span=12).mean()
        ema26 = s.ewm(span=26).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9).mean()
        hist = 2 * (dif - dea)
        return dif, dea, hist

    # 注入命名空间
    namespace = {
        'open': open_p, 'high': high, 'low': low,
        'close': close, 'volume': volume,
        'MA': _ma, 'STD': _std, 'RSI': _rsi, 'MACD': _macd,
        'np': np, 'pd': pd,
        'signal': 0,
    }

    # 编译执行
    # AI 生成的代码常以 return signal 结尾，但 module 级 exec 不支持 return
    cleaned_code = re.sub(r'^\s*return\s+', 'pass  # ', code, flags=re.MULTILINE)
    compiled = compile(cleaned_code, '<vibe_strategy>', 'exec')
    exec(compiled, namespace)

    # 捕获输出
    signal = namespace.get('signal', 0)
    if signal is None:
        signal = 0
    signal = float(signal)

    # 归一化到 0-10
    # signal 可能：0/1/-1 分类或 0-100 分值
    if -1 <= signal <= 1:
        # 分类信号：1=buy(7.0), 0=neutral(5.0), -1=sell(3.0)
        return 7.0 if signal > 0 else (3.0 if signal < 0 else 5.0)
    else:
        # 分值信号：0-100 → 0-10
        return max(0.0, min(10.0, signal / 10.0))


def _extract_chanlun_evidence(chanlun_result: Dict) -> List[str]:
    """从缠论结果提取依据文本"""
    evidences = []
    if not chanlun_result or not chanlun_result.get('success'):
        return evidences

    summary = chanlun_result.get('summary', {})
    buy_pts = chanlun_result.get('buy_points', [])

    if buy_pts:
        bp_types = []
        for bp in buy_pts:
            bt = (
                bp.type if hasattr(bp, 'type')
                else bp.get('type', 'unknown') if isinstance(bp, dict)
                else 'unknown'
            )
            bp_types.append(str(bt))
        evidences.append(f"缠论买点: {', '.join(bp_types)}")

    zs_count = summary.get('total_zhongshu', 0)
    if zs_count > 0:
        evidences.append(f"中枢: {zs_count}个")

    trend = chanlun_result.get('trend', '')
    if trend:
        evidences.append(f"趋势: {trend}")

    check = chanlun_result.get('theorem_check', {})
    if isinstance(check, dict):
        t10 = check.get('T10', {})
        t10_score = t10.get('score', 1.0) if isinstance(t10, dict) else 1.0
    else:
        t10_score = 1.0
    if t10_score < 0.8:
        evidences.append("动力结构偏弱")

    return evidences


def _extract_vp_evidence(vp_result: Dict) -> List[str]:
    """从量价结果提取依据文本"""
    evidences = []
    if not vp_result or not vp_result.get('success'):
        return evidences

    signal_output = vp_result.get('signal_output', {})
    signal_label = signal_output.get('signal_label', '')
    if signal_label:
        evidences.append(f"量价信号: {signal_label}")

    stage = vp_result.get('stage', {})
    current_stage = stage.get('current_stage', '')
    stage_note = stage.get('note', '')
    if current_stage:
        evidences.append(f"波段: {current_stage}")
    if stage_note:
        evidences.append(stage_note)

    relation = vp_result.get('relation', {})
    pattern = relation.get('current_pattern', '')
    if pattern:
        evidences.append(f"形态: {pattern}")

    momentum = relation.get('aux_momentum', {})
    mom_level = momentum.get('level', '')
    if mom_level:
        evidences.append(f"动量: {mom_level}")

    return evidences


def _phase_timing_bonus(l2_phase: str, cl_dir: str, cl_signal: str) -> float:
    """
    阶段-时机共振加分（Wiki: 三重过滤系统的核心思想）

    根据 L2 主力阶段和 L3 缠论信号的对齐程度，计算额外加分。

    L2 阶段: accumulating(建仓) | markup(拉升) | washing(洗盘) | distributing(出货) | neutral | unknown
    L3 信号: bullish (买入型) | neutral | bearish (卖出型)

    核心逻辑:
      - 建仓期 + 缠论第一类买点 → 最佳介入时机 (三重过滤全对齐)
      - 拉升期 + 缠论无明确信号 → 趋势延续（可持有/介入）
      - 建仓期 + 缠论卖出信号 → 短期调整（等待二买）
      - 出货期 + 任何信号 → 回避

    Returns: -1.0 到 +2.0 的调整值（加到 0-10 综合评分上）
    """
    # 判断缠论信号是买入型还是卖出型
    cl_bullish = cl_dir == 'bullish' or ('买' in cl_signal and '卖' not in cl_signal)
    cl_bearish = cl_dir == 'bearish' or ('卖' in cl_signal) or 'sell' in cl_signal

    # 阶段-信号对齐矩阵
    if l2_phase == 'accumulating':
        if cl_bullish:
            return 2.0    # 建仓+买点 → 最佳时机
        elif cl_bearish:
            return 0.5    # 建仓+卖点 → 调整期，等待二买
        else:
            return 1.0    # 建仓+中性 → 可以逐步介入

    elif l2_phase == 'markup':
        if cl_bullish:
            return 1.5    # 拉升+买点 → 强势延续
        elif cl_bearish:
            return -0.5   # 拉升+卖点 → 可能见顶，谨慎
        else:
            return 1.0    # 拉升+中性 → 趋势运行中

    elif l2_phase == 'washing':
        if cl_bullish:
            return 1.5    # 洗盘+买点 → 洗盘结束信号
        elif cl_bearish:
            return -1.0   # 洗盘+卖点 → 洗盘可能失败
        else:
            return 0.0    # 洗盘+中性 → 等待

    elif l2_phase == 'distributing':
        return -1.0        # 出货期 → 无论什么信号都回避

    else:
        # unknown / neutral
        if cl_bullish:
            return 0.5
        elif cl_bearish:
            return -0.5
        else:
            return 0.0


def _zscore_normalize(scores: list, new_min: float = 0, new_max: float = 10) -> list:
    """
    z-score 归一化：消除各策略评分均值和标准差差异

    将原始分通过 z = (x-μ)/σ 转换后映射到 [new_min, new_max]，
    保证各策略的均值和标准差一致，权重精确反映预期影响力。

    当样本 < 2 或标准差接近零时返回中性分(5.0)。
    z 值截断到 [-3, 3] 防止极端值主导。
    """
    if len(scores) < 2:
        return [5.0] * len(scores)
    n = len(scores)
    mean = sum(scores) / n
    var = sum((x - mean) ** 2 for x in scores) / n
    std = var ** 0.5
    if std < 1e-6:
        return [5.0] * n
    result = []
    for x in scores:
        z = (x - mean) / std
        z = max(-3.0, min(3.0, z))
        normalized = (z + 3.0) / 6.0 * (new_max - new_min) + new_min
        result.append(round(normalized, 2))
    return result


def screen_l3_candidates(
    candidates: List[Dict],
    data_dict: Dict[str, pd.DataFrame],
    weights: dict = None,
    combinations: list = None,
    vibe_strategies: list = None,
    l2_phase_map: dict = None,
) -> List[Dict]:
    """
    对L2通过的候选股执行L3策略验证（缠论+量价+因子组合共振评分）

    === v2 两阶段归一化评分 ===
    阶段一：对所有候选股逐只计算各策略原始分
    阶段二：对每个策略的评分做 z-score 归一化（消除均值/标准差差异）
    阶段三：用归一化后分数 + 用户权重 + L2阶段感知调整计算综合评分

    权重参数格式: {'chanlun': w1, 'vp': w2, 'factor': w3, 'vibe': w4}
    combinations: 已勾选的因子组合 ID 列表
    vibe_strategies: 已勾选的 Vibe 策略 ID 列表
    l2_phase_map: {symbol: phase} L2 主力阶段（用于阶段-时机共振评分）

    权重为 0 或列表为空的策略不参与评分。
    """
    logger.info(f"L3 策略验证开始: {len(candidates)} 只候选股")
    _L3_ENGINE_HEALTH['total_runs'] += 1
    _L3_ENGINE_HEALTH['last_run_status'] = 'running'
    stocks_processed = 0

    # ── 预处理权重 ──
    default_weights = {'chanlun': 0.4, 'vp': 0.4, 'factor': 0.2, 'vibe': 0.0}
    w = dict(default_weights)
    if isinstance(weights, dict):
        w.update(weights)
    if not combinations:
        w['factor'] = 0
    if not vibe_strategies:
        w['vibe'] = 0
    need_cl = w.get('chanlun', 0) > 0
    need_vp = w.get('vp', 0) > 0
    need_fx = w.get('factor', 0) > 0
    need_vb = w.get('vibe', 0) > 0

    # ── 加载 Vibe 策略代码（从数据库） ──
    _vibe_details = None
    if need_vb and vibe_strategies:
        try:
            from app.models.strategy import StrategyTemplateV2
            # 从 vibe IDs 提取数字 ID
            vibe_ids = []
            for vid in vibe_strategies:
                sid = str(vid).replace('vibe_', '')
                if sid.isdigit():
                    vibe_ids.append(int(sid))
            if vibe_ids:
                records = StrategyTemplateV2.query.filter(
                    StrategyTemplateV2.id.in_(vibe_ids)
                ).all()
                _vibe_details = [{
                    'id': f'vibe_{r.id}',
                    'code_template': r.code_template,
                    'type': 'system' if r.is_system else 'user',
                    'ready': getattr(r, 'ready', True),
                } for r in records]
                logger.info(f"Vibe 策略已加载: {len(_vibe_details)} 个")
        except Exception as e:
            logger.debug(f"Vibe 策略加载失败: {e}")
            _vibe_details = None

    # 构建大盘环境条件
    index_condition = _compute_index_condition(data_dict)

    # ════════════════════════════════════════════════════════════
    # 阶段一：逐只计算原始分
    # ════════════════════════════════════════════════════════════
    raw = []  # [{symbol, df, name, market_context, cl_score, cl_dir, cl_signal, cl_result, vp_*, fx_score, vibe_bonus}]
    for item in candidates:
        symbol = item.get('symbol', item.get('ts_code', ''))
        if not symbol or symbol not in data_dict:
            continue
        df = data_dict[symbol]
        if df.empty or len(df) < 60:
            continue

        r = {'symbol': symbol, 'df': df, 'name': item.get('name', '')}

        # market_context
        market_context = _build_market_context(symbol, df)
        if market_context:
            market_context['index_condition'] = index_condition
        r['market_context'] = market_context

        # ── 量价 ──
        r['vp_result'], r['vp_score'], r['vp_signal'], r['vp_dir'] = None, 0.0, 'N/A', 'neutral'
        if need_vp:
            try:
                from .volume_price_strategy import VolumePriceStrategy
                vp = VolumePriceStrategy(market_env=market_context)
                vp_r = vp.analyze(df)
                if vp_r.get('success'):
                    s, sig, d = _compute_volume_price_score(vp_r, symbol, df)
                    r['vp_result'], r['vp_score'], r['vp_signal'], r['vp_dir'] = vp_r, s, sig, d
            except Exception as e:
                logger.debug(f"量价分析失败 {symbol}: {e}")
                _record_engine_error('volume_price', symbol)

        # ── 缠论 ──
        r['cl_result'], r['cl_score'], r['cl_signal'], r['cl_dir'] = None, 0.0, 'N/A', 'neutral'
        if need_cl:
            try:
                from .chanlun_strategy import analyze_chanlun
                cl_r = analyze_chanlun(df)
                if cl_r.get('success'):
                    s, sig, d = _compute_chanlun_score(cl_r, df)
                    s = _adjust_score_with_context(s, r['market_context'])
                    r['cl_result'], r['cl_score'], r['cl_signal'], r['cl_dir'] = cl_r, s, sig, d
            except Exception as e:
                logger.debug(f"缠论分析失败 {symbol}: {e}")
                _record_engine_error('chanlun', symbol)

        # ── 因子组合评分（按选中的组合真实计算） ──
        r['factor_score'] = _compute_factor_score(df, symbol=symbol, combo_ids=combinations) if need_fx else 0.0

        # ── Vibe Coding 真实执行（每只股票独立计算） ──
        r['vibe_bonus'] = _compute_vibe_bonus(
            vibe_strategies or [],
            df=df,
            strategy_details=_vibe_details,
        ) if need_vb else 0.0

        # ── BOCIASI 快线评分（个股级情绪，C6） ──
        r['bociasi_score'] = 0.0
        try:
            closes_arr = df['close'].values
            volumes_arr = df['vol'].values if 'vol' in df.columns else df['amount'].values
            if len(closes_arr) >= 20:
                bociasi_val = _f_bociasi_quickline(closes_arr, volumes_arr)
                if bociasi_val is not None:
                    r['bociasi_score'] = bociasi_val / 10.0
        except Exception:
            pass

        raw.append(r)
        stocks_processed += 1

    if not raw:
        _L3_ENGINE_HEALTH['last_run_status'] = 'no_results'
        return []

    # ════════════════════════════════════════════════════════════
    # 阶段二：对每个策略的评分做 z-score 归一化
    # ════════════════════════════════════════════════════════════
    raw_cl = [r['cl_score'] for r in raw]
    raw_vp = [r['vp_score'] for r in raw]
    raw_fx = [r['factor_score'] for r in raw]
    raw_bo = [r['bociasi_score'] for r in raw]

    norm_cl = _zscore_normalize(raw_cl) if need_cl else [0.0] * len(raw)
    norm_vp = _zscore_normalize(raw_vp) if need_vp else [0.0] * len(raw)
    norm_fx = _zscore_normalize(raw_fx) if need_fx else [0.0] * len(raw)
    norm_bo = [max(0.0, min(1.0, v)) for v in raw_bo]  # BOCIASI 已归一化 0-1，无需 z-score

    # Vibe 不归一化（加分性质，不区分股票间差异）
    vibe_bonus_values = [r['vibe_bonus'] for r in raw]

    # ════════════════════════════════════════════════════════════
    # 阶段三：用归一化分 + 权重计算综合评分 → 构建结果
    # ════════════════════════════════════════════════════════════
    validated = []
    for i, r in enumerate(raw):
        symbol = r['symbol']
        df = r['df']
        cl_score_n = norm_cl[i]
        vp_score_n = norm_vp[i]
        fx_score_n = norm_fx[i]
        vb = vibe_bonus_values[i]

        # L2 阶段感知评分调整（Wiki: 三重过滤 — 阶段+时机对齐）
        l2_phase = (l2_phase_map or {}).get(symbol, 'unknown')
        phase_bonus = _phase_timing_bonus(l2_phase, r['cl_dir'], r['cl_signal'])

        # 风控→全策略融合: L1 风控标记的股票整体降权10%
        risk_flag = r.get('risk_flag', False)
        risk_mult = 0.9 if risk_flag else 1.0

        # BOCIASI 四象限自适应调节（P0-② 实现后可用）
        try:
            from app.engine.framework.bociasi_quadrant import BociasiQuadrantAnalyzer
            bq = BociasiQuadrantAnalyzer()
            q = bq.analyze()
            # HH(行情尾声): 缠论权重降30%, 因子权重升20%
            # LL(情绪底部): 加大量价权重, 降低因子权重
            if q['quadrant'] == 'HH':
                w_cl *= 0.7; w_fx *= 1.2
            elif q['quadrant'] == 'LL':
                w_vp *= 1.2; w_fx *= 0.8
        except Exception:
            pass

        combined = _compute_combined_score(
            cl_score_n, vp_score_n, r['cl_dir'], r['vp_dir'],
            weights=w,
            factor_score=fx_score_n,
            vibe_bonus=vb,
        )
        # 阶段加分直接加到综合评分上（已归一化到0-10）
        combined = max(0.0, min(10.0, combined + phase_bonus * 0.5))  # phase_bonus 缩放后叠加
        # BOCIASI 情绪调整（-0.15 ~ +0.15）
        bociasi_bonus = (norm_bo[i] - 0.5) * 0.3
        combined = max(0.0, min(10.0, combined + bociasi_bonus))
        # 风控降权因子
        combined = combined * risk_mult
        grade = _score_to_grade(combined)

        # 信号标签（使用原始方向判断，归一化不影响方向）
        triggers = []
        if need_cl and r['cl_dir'] == 'bullish' and r['cl_score'] >= 6:
            triggers.append(r['cl_signal'])
        if need_vp and r['vp_dir'] == 'bullish' and r['vp_score'] >= 6:
            triggers.append(r['vp_signal'])
        if not triggers:
            triggers.append('待观察')

        # 依据
        reasons = []
        if l2_phase != 'unknown':
            _pn = {'accumulating': '建仓期', 'markup': '拉升期', 'washing': '洗盘期', 'distributing': '出货期'}
            reasons.append(f'主力阶段: {_pn.get(l2_phase, l2_phase)}')
        if need_cl:
            reasons.extend(_extract_chanlun_evidence(r['cl_result']))
        if need_vp:
            reasons.extend(_extract_vp_evidence(r['vp_result']))
        if need_fx and fx_score_n > 0:
            reasons.append(f'因子组合评分: {fx_score_n:.1f}')
        if vb > 0:
            reasons.append(f'Vibe 策略加分: +{vb:.1f}')
        if phase_bonus != 0:
            reasons.append(f'阶段共振: {phase_bonus:+.1f}')
        if not reasons:
            reasons.append('基础数据通过验证')

        score_100 = round(combined * 10, 1)

        validated.append({
            'symbol': symbol,
            'name': r['name'],
            'score': score_100,
            'close': round(float(df['close'].iloc[-1]), 2) if 'close' in df.columns else None,
            'pct_chg': round(float(df['pct_chg'].iloc[-1]), 2) if 'pct_chg' in df.columns else None,
            'grade': grade,
            'industry': '',
            'triggers': triggers,
            'reasons': reasons,
            'strategy_detail': {
                'chanlun': {
                    'direction': r['cl_dir'],
                    'score': round(cl_score_n / 10.0, 2),
                    'signal': r['cl_signal'],
                    'raw': round(r['cl_score'], 2),
                },
                'volume_price': {
                    'direction': r['vp_dir'],
                    'score': round(vp_score_n / 10.0, 2),
                    'signal': r['vp_signal'],
                    'raw': round(r['vp_score'], 2),
                    'status_recognition': (r.get('vp_result') or {}).get('signal_output', {}).get('status_recognition'),
                },
                'factor': {
                    'score': round(fx_score_n, 1),
                    'raw': round(r['factor_score'], 2),
                    'grade': grade,
                    'combinations': combinations or [],
                    'combination_note': f'因子评分: {fx_score_n:.1f}' if need_fx else '未启用',
                },
            },
            'chanlun_score': round(cl_score_n, 2),
            'vp_score': round(vp_score_n, 2),
            'factor_score': round(fx_score_n, 2),
        })

    validated.sort(key=lambda x: x['score'], reverse=True)
    _L3_ENGINE_HEALTH['total_stocks_processed'] += stocks_processed
    _L3_ENGINE_HEALTH['last_run_status'] = 'ok' if validated else 'no_results'
    logger.info(f"L3 策略验证完成: {len(validated)} 只通过（共处理 {stocks_processed} 只）")
    return validated


def _compute_index_condition(data_dict: Dict[str, pd.DataFrame]) -> str:
    """从大盘指数数据计算大盘环境条件

    参考 000001.SH（上证指数）近 5 日涨跌幅判断大盘强弱：
      - 涨 > 2% → GOOD
      - 跌 < -2% → POOR
      - 其他 → NORMAL

    Returns:
        'GOOD' / 'POOR' / 'NORMAL'
    """
    try:
        for symbol in data_dict:
            if symbol in ('000001.SH', '上证指数'):
                df = data_dict[symbol]
                if df is not None and not df.empty and len(df) >= 5:
                    pct_chg = df['pct_chg'].tail(5).sum() if 'pct_chg' in df.columns else 0
                    if pct_chg > 2:
                        return 'GOOD'
                    elif pct_chg < -2:
                        return 'POOR'
                    return 'NORMAL'
    except Exception:
        pass
    return 'NORMAL'


def _build_market_context(symbol: str, df: pd.DataFrame) -> Dict:
    """从 DuckDB 缓存构建单只股票的 market_context

    从 daily_basic_cache 获取 turnover_rate,
    从 moneyflow_cache 获取 5 日 net_lg_amount 汇总.

    Returns:
        {'turnover_rate': float, 'net_lg_amount': float} 或 None
    """
    try:
        from app.data import DataManager
        dm = DataManager()
        context = {}

        # 获取换手率（最近交易日）
        try:
            basic_df = dm.get_cached_daily_basic(symbol)
            if not basic_df.empty and 'turnover_rate' in basic_df.columns:
                tr_series = basic_df['turnover_rate'].dropna().tail(5)
                if len(tr_series) > 0:
                    context['turnover_rate'] = float(tr_series.mean())
        except Exception:
            pass

        # 获取 5 日大单净流入汇总
        try:
            mf_df = dm.get_cached_moneyflow(symbol)
            if not mf_df.empty and 'net_lg_amount' in mf_df.columns:
                net_series = mf_df['net_lg_amount'].dropna().tail(5)
                if len(net_series) > 0:
                    context['net_lg_amount'] = float(net_series.sum())
        except Exception:
            pass

        return context if context else None
    except Exception:
        return None


def _adjust_score_with_context(score_0_10: float, market_context: Dict) -> float:
    """根据市场上下文调整缠论评分（0-10 范围）

    等效于 ChanlunScorer.score() 的市场环境调整逻辑，但作用在 0-10 评分上。

    调整项：
      - 换手率 > 10%: +0.5  |  > 5%: +0.3
      - 大单净流入 > 0: +0.3 |  < 0: -0.3
      - 大盘 POOR: -0.5 | GOOD: +0.3

    Args:
        score_0_10: 缠论原始评分 (0-10)
        market_context: 市场上下文字典（可能为 None）

    Returns:
        调整后的评分 (0-10, clamped)
    """
    if not market_context:
        return score_0_10

    adjustment = 0.0

    # 换手率调整
    turnover = market_context.get('turnover_rate')
    if turnover is not None:
        if turnover > 10:
            adjustment += 0.5
        elif turnover > 5:
            adjustment += 0.3

    # 资金流向调整
    net_lg = market_context.get('net_lg_amount')
    if net_lg is not None:
        if net_lg > 0:
            adjustment += 0.3
        elif net_lg < 0:
            adjustment -= 0.3

    # 大盘环境调整
    idx_cond = market_context.get('index_condition')
    if idx_cond == 'POOR':
        adjustment -= 0.5
    elif idx_cond == 'GOOD':
        adjustment += 0.3

    return max(0.0, min(10.0, score_0_10 + adjustment))
