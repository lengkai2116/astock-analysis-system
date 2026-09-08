"""第5维 情绪环境引擎

358号方案 v4.1：第5维情绪环境维度引擎。

整合源：
  - emotion_builder.py（182行）：三层面输出（市场/板块/个股）+ 条件稽核
  - bociasi_quickline.py（131行）：BOCIASI快线4指标
  - bociasi_slowline.py（171行）：BOCIASI慢线ERP
  - bociasi_quadrant.py（347行）：四象限市场情绪判定
  - emotion_temperature.py（103行）：情绪温度0-100
  - sector_rotation_model.py（144行）：板块热度 top_10/top_20/normal/none
  - time_rhythm_engine.py（103行）：时间节奏 BOLL带宽+中枢横盘

统一接口：evaluate(dims, tags, signals, lifecycle) → {status_description, judgment, audit}
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from app.data.mixins import DataAwareMixin
from app.engine.framework.bociasi_quadrant import BociasiQuadrantAnalyzer

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# BOCIASI快线常量
# ═══════════════════════════════════════════════════════════

FAST_HIGH_THRESHOLD = 0.70
FAST_LOW_THRESHOLD = 0.30
SLOW_HIGH_THRESHOLD = 0.70
SLOW_LOW_THRESHOLD = 0.30


# ═══════════════════════════════════════════════════════════
# 情绪温度常量
# ═══════════════════════════════════════════════════════════

PHASE_BASE_TEMP = {
    'ice': 10, 'sprout': 30, 'regression': 40, 'ferment': 60,
    'climax': 85, 'ebb': 25, 'neutral': 50,
}

TEMP_WEIGHTS = {
    'market_phase': 0.25, 'limit_up': 0.15, 'blast_rate': 0.10,
    'sector_heat': 0.15, 'volume_price': 0.15, 'margin': 0.10, 'breadth': 0.10,
}


# ═══════════════════════════════════════════════════════════
# 时间节奏常量
# ═══════════════════════════════════════════════════════════

BANDWIDTH_TIGHT = 5
BANDWIDTH_NARROW = 10
RANGE_TIGHT = 10
CONSOLIDATION_MIN_DAYS = 15

# 板块热度枚举
HEAT_TOP10 = 'top_10'
HEAT_TOP20 = 'top_20'
HEAT_NORMAL = 'normal'
HEAT_NONE = 'none'

# 六段论阶段映射
PHASE_MAP = {
    'ice': ('冰点', '市场极度低迷', 'red'),
    'sprout': ('萌芽', '市场情绪开始萌芽，出现连板龙头', 'yellow'),
    'ferment': ('发酵', '市场情绪发酵中，板块轮动活跃', 'green'),
    'climax': ('高潮', '市场情绪过热', 'red'),
    'ebb': ('退潮', '市场情绪开始降温', 'yellow'),
    'regression': ('回归', '市场情绪回归常态', 'yellow'),
    'recovery': ('复苏', '市场情绪开始回暖', 'green'),
}


# ═══════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════

def _normalize(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.5
    return max(0, min(1, (value - low) / (high - low)))


# ═══════════════════════════════════════════════════════════
# BOCIASI快线（从 bociasi_quickline.py 迁移）
# ═══════════════════════════════════════════════════════════

def _bociasi_quickline(df: pd.DataFrame) -> dict:
    """BOCIASI快线4指标评估"""
    if df is None or df.empty or len(df) < 6:
        return {"signal": "NEUTRAL", "confidence": 0.0, "pass_count": 0,
                "indicators": {}, "details": {}}

    closes = df['close'].values
    highs = df['high'].values
    lows = df['low'].values
    volumes = df['vol'].values if 'vol' in df.columns else df['amount'].values
    latest_close = float(closes[-1])

    vol_ma5 = np.mean(volumes[-6:-1])
    fast_vol = bool(volumes[-1] > vol_ma5 * 1.5)
    vol_ratio = float(volumes[-1] / vol_ma5) if vol_ma5 > 0 else 0.0

    price_ma5 = np.mean(closes[-6:-1])
    fast_price = bool(latest_close > price_ma5)
    price_offset = float((latest_close / price_ma5 - 1) * 100) if price_ma5 > 0 else 0.0

    close_5d_ago = float(closes[-6]) if len(closes) >= 6 else latest_close
    mom_5d = (latest_close / close_5d_ago - 1) * 100
    fast_mom = bool(mom_5d > 3.0)

    daily_amplitude = (highs[-1] - lows[-1]) / latest_close * 100
    fast_breadth = bool(daily_amplitude > 3.0)

    indicators = {"fast_vol": fast_vol, "fast_price": fast_price,
                  "fast_mom": fast_mom, "fast_breadth": fast_breadth}
    pass_count = sum(1 for v in indicators.values() if v)

    if pass_count >= 3:
        signal, base_conf = "BUY", 0.65
    elif pass_count >= 2:
        signal, base_conf = "WATCH", 0.50
    elif not fast_price and mom_5d < -3:
        signal, base_conf = "BEARISH", 0.35
    else:
        signal, base_conf = "NEUTRAL", 0.35

    if fast_vol and fast_mom:
        base_conf += 0.05
    if fast_breadth and not fast_price:
        base_conf -= 0.05
    confidence = max(0.1, min(0.9, base_conf))

    return {
        "signal": signal, "confidence": round(confidence, 2),
        "indicators": indicators, "pass_count": pass_count,
        "details": {"vol_ratio": round(vol_ratio, 2), "price_offset_pct": round(price_offset, 2),
                    "mom_5d_pct": round(mom_5d, 2), "amplitude_pct": round(daily_amplitude, 2)},
    }


# ═══════════════════════════════════════════════════════════
# BOCIASI慢线（从 bociasi_slowline.py 迁移）
# ═══════════════════════════════════════════════════════════

def _bociasi_slowline(df: pd.DataFrame, bond_yield: float = 2.85,
                      index_df: pd.DataFrame = None) -> dict:
    """BOCIASI慢线ERP评估"""
    if df is None or df.empty or len(df) < 60:
        return {'signal': 'NEUTRAL', 'confidence': 0.0, 'details': {'error': '数据不足'}}

    pe_ttm = None
    for col in ['pe_ttm', 'pe']:
        if col in df.columns and not df[col].empty:
            val = df[col].iloc[-1]
            if val is not None and val > 0:
                pe_ttm = float(val)
                break

    if pe_ttm is not None and pe_ttm > 0:
        erp = 1.0 / pe_ttm * 100 - bond_yield
        if erp > 5.0:
            erp_signal, erp_conf = 'BULLISH', 0.75
        elif erp > 3.0:
            erp_signal, erp_conf = 'BULLISH', 0.60
        elif erp < 0.5:
            erp_signal, erp_conf = 'BEARISH', 0.75
        elif erp < 1.5:
            erp_signal, erp_conf = 'BEARISH', 0.60
        else:
            erp_signal, erp_conf = 'NEUTRAL', 0.0
    else:
        erp = None
        erp_signal, erp_conf = 'NEUTRAL', 0.0

    sb_signal, sb_conf = 'NEUTRAL', 0.0
    if index_df is not None and not index_df.empty:
        idx_close = index_df['close'].astype(float)
        stock_close = df['close'].astype(float)
        if len(idx_close) >= 20 and len(stock_close) >= 21:
            idx_ret = idx_close.iloc[-1] / idx_close.iloc[-20] - 1
            stock_ret = stock_close.iloc[-1] / stock_close.iloc[-21] - 1
            rel_strength = stock_ret - idx_ret
            if rel_strength > 0.05:
                sb_signal = 'BULLISH'
                sb_conf = min(0.7, 0.5 + abs(rel_strength))
            elif rel_strength < -0.05:
                sb_signal = 'BEARISH'
                sb_conf = min(0.7, 0.5 + abs(rel_strength))

    signals = []
    confs = []
    if erp_signal != 'NEUTRAL':
        signals.append(erp_signal)
        confs.append(erp_conf)
    if sb_signal != 'NEUTRAL':
        signals.append(sb_signal)
        confs.append(sb_conf)

    if not signals:
        final_signal, final_conf = 'NEUTRAL', 0.3
    else:
        bullish = signals.count('BULLISH')
        bearish = signals.count('BEARISH')
        avg_conf = np.mean(confs) if confs else 0.3
        if bullish > bearish:
            final_signal = 'BULLISH'
            final_conf = min(0.8, avg_conf * 1.1)
        elif bearish > bullish:
            final_signal = 'BEARISH'
            final_conf = min(0.8, avg_conf * 1.1)
        else:
            final_signal = 'NEUTRAL'
            final_conf = 0.3

    return {
        'signal': final_signal, 'confidence': round(final_conf, 2),
        'details': {'erp': round(erp, 4) if erp is not None else None,
                     'erp_signal': erp_signal, 'sb_signal': sb_signal},
    }


# ═══════════════════════════════════════════════════════════
# BOCIASI四象限（从 bociasi_quadrant.py 简化迁移）
# ═══════════════════════════════════════════════════════════

def _bociasi_quadrant(quick_result: dict, slow_result: dict) -> dict:
    """四象限判定：快线+慢线交叉"""
    q_signal = quick_result.get('signal', 'NEUTRAL')
    s_signal = slow_result.get('signal', 'NEUTRAL')

    q_conf = quick_result.get('confidence', 0.5)
    slow_result.get('confidence', 0.5)

    q_high = q_signal == 'BUY' or (q_signal == 'WATCH' and q_conf > 0.5)
    s_high = s_signal == 'BULLISH'

    if not s_high and not q_high:
        quadrant, desc, mult = 'LL', '情绪底部，高性价比区间', 1.15
    elif not s_high and q_high:
        quadrant, desc, mult = 'LH', '底部反弹，短线活跃', 1.05
    elif s_high and not q_high:
        quadrant, desc, mult = 'HL', '高位震荡，需警惕风险', 0.90
    elif s_high and q_high:
        quadrant, desc, mult = 'HH', '上涨尾声，高度警惕', 0.75
    else:
        quadrant, desc, mult = 'MM', '市场情绪中性', 1.00

    return {'quadrant': quadrant, 'description': desc, 'weight_multiplier': mult,
            'fast_signal': q_signal, 'slow_signal': s_signal}


# ═══════════════════════════════════════════════════════════
# 情绪温度（从 emotion_temperature.py 迁移）
# ═══════════════════════════════════════════════════════════

def calc_emotion_temperature(sentiment_phase='neutral', limit_up_count=0,
                             sealing_rate=50.0, sector_rank=None,
                             volume_price_fit='neutral',
                             margin_change_pct=None, breadth=None) -> float:
    scores = {}
    scores['market_phase'] = PHASE_BASE_TEMP.get(sentiment_phase, 50)
    scores['limit_up'] = min(100, max(0, limit_up_count))
    scores['blast_rate'] = min(100, max(0, sealing_rate))
    scores['sector_heat'] = max(0, min(100, 100 - sector_rank * 2)) if sector_rank else 50
    vp_map = {'healthy': 80, 'diverging': 20, 'neutral': 50}
    scores['volume_price'] = vp_map.get(volume_price_fit, 50)
    scores['margin'] = min(100, max(0, 50 + margin_change_pct * 600)) if margin_change_pct is not None else 50
    scores['breadth'] = min(100, max(0, breadth * 100)) if breadth is not None else 50
    total = sum(scores[k] * TEMP_WEIGHTS[k] for k in TEMP_WEIGHTS)
    return round(min(100, max(0, total)), 1)


# ═══════════════════════════════════════════════════════════
# 时间节奏（从 time_rhythm_engine.py 迁移）
# ═══════════════════════════════════════════════════════════

def _time_rhythm(df: pd.DataFrame) -> dict:
    """BOLL带宽 + 中枢横盘时长 → 变盘窗口判定

    411号Phase 5：MA20/BOLL优先读预计算表，回退raw计算。
    """
    result = {'time_rhythm': 'unknown'}
    try:
        if df is None or len(df) < 30:
            return result
        close = df['close'].values

        # 411号Phase 5：尝试从预计算表读取MA20/BOLL
        ma20 = None
        std20 = None
        try:
            ts_code = ''
            if hasattr(df, 'columns') and 'ts_code' in df.columns:
                ts_code = str(df['ts_code'].iloc[0])
            if ts_code:
                from app.data import DataManager
                dm = DataManager()
                indicators_df = dm.get_cached_indicators(ts_code)
                if indicators_df is not None and not indicators_df.empty:
                    if 'ma20' in indicators_df.columns:
                        ma20_pre = indicators_df['ma20'].dropna()
                        if not ma20_pre.empty:
                            # 构建MA20数组（对齐到close长度）
                            ma20_vals = ma20_pre.values
                            if len(ma20_vals) >= len(close):
                                ma20 = ma20_vals[-len(close):]
                            else:
                                # 填充前部为NaN
                                ma20 = np.full(len(close), np.nan)
                                ma20[-len(ma20_vals):] = ma20_vals
                    if 'boll_upper' in indicators_df.columns and 'boll_mid' in indicators_df.columns:
                        boll_upper_pre = indicators_df['boll_upper'].dropna()
                        boll_mid_pre = indicators_df['boll_mid'].dropna()
                        if not boll_upper_pre.empty and not boll_mid_pre.empty:
                            # std ≈ (upper - mid) / 2
                            upper_vals = boll_upper_pre.values
                            mid_vals = boll_mid_pre.values
                            min_len = min(len(upper_vals), len(mid_vals))
                            std_approx = (upper_vals[-min_len:] - mid_vals[-min_len:]) / 2
                            if len(std_approx) >= len(close):
                                std20 = std_approx[-len(close):]
                            else:
                                std20 = np.full(len(close), np.nan)
                                std20[-len(std_approx):] = std_approx
        except Exception:
            pass

        # 回退到raw计算
        if ma20 is None or std20 is None:
            close_series = pd.Series(close)
            ma20 = close_series.rolling(20).mean().values
            std20 = close_series.rolling(20).std().values

        bandwidth = np.where(ma20 > 1e-9, std20 / ma20 * 100, np.zeros_like(ma20))
        high_30 = np.max(df['high'].values[-30:])
        low_30 = np.min(df['low'].values[-30:])
        range_pct = (high_30 - low_30) / low_30 * 100 if low_30 > 0 else 0
        current_bw = bandwidth[-1] if len(bandwidth) > 0 else 100

        consolidation_days = 0
        if len(close) >= 30:
            ref_low = np.min(df['low'].values[-30:])
            ref_high = np.max(df['high'].values[-30:])
            ref_mid = (ref_low + ref_high) / 2
            threshold = ref_mid * 0.05
            for i in range(min(60, len(close))):
                price = close[-(i + 1)]
                if abs(price - ref_mid) < threshold:
                    consolidation_days += 1
                else:
                    break

        if current_bw < BANDWIDTH_TIGHT and range_pct < RANGE_TIGHT:
            if consolidation_days >= CONSOLIDATION_MIN_DAYS:
                result['time_rhythm'] = 'approaching_turn'
            elif consolidation_days >= 5:
                result['time_rhythm'] = 'mid_consolidation'
            else:
                result['time_rhythm'] = 'early_consolidation'
        elif current_bw < BANDWIDTH_NARROW and range_pct < RANGE_TIGHT * 1.5:
            if consolidation_days >= CONSOLIDATION_MIN_DAYS:
                result['time_rhythm'] = 'approaching_turn'
            elif consolidation_days >= 5:
                result['time_rhythm'] = 'mid_consolidation'
            else:
                result['time_rhythm'] = 'early_consolidation'
    except Exception:
        pass
    return result


# ═══════════════════════════════════════════════════════════
# 情绪三层面评估（从 emotion_builder.py 迁移）
# ═══════════════════════════════════════════════════════════

def _assess_market_emotion(tags: dict, dims: dict) -> dict:
    dim_emotion = str(dims.get('emotion', {}).get('state', ''))
    dim_light = str(dims.get('emotion', {}).get('light', ''))
    if dim_emotion:
        light = 'red' if dim_light == 'red' else ('green' if dim_light == 'green' else 'yellow')
        return {'phase': dim_emotion, 'detail': f'L1判定情绪={dim_emotion}', 'light': light}

    sp = str(tags.get('sentiment_phase', ''))
    if sp in PHASE_MAP:
        name, desc, light = PHASE_MAP[sp]
        return {'phase': name, 'detail': desc, 'light': light}
    return {'phase': '正常', 'detail': '情绪数据不足', 'light': 'yellow'}


def _assess_sector_emotion(tags: dict, dims: dict) -> dict:
    heat = str(tags.get('sector_heat', ''))
    heat_map = {
        'top_10': ('top_10', '板块排名前10（强势板块）', 'green'),
        'top_20': ('top_20', '板块排名11-20（活跃板块）', 'green'),
        'normal': ('normal', '板块排名20以外', 'yellow'),
        'none': ('none', '板块数据不足', 'yellow'),
    }
    if heat in heat_map:
        name, desc, light = heat_map[heat]
        return {'heat': name, 'detail': desc, 'light': light}
    return {'heat': 'normal', 'detail': '板块数据不足', 'light': 'yellow'}


def _assess_stock_emotion(tags: dict, dims: dict) -> dict:
    vp = str(dims.get('vp', {}).get('state', ''))
    if vp in ('强健康', '健康'):
        return {'emotion': '健康', 'detail': f"量价状态{vp}，趋势确认强势", 'light': 'green'}
    elif vp in ('背离', '严重背离'):
        return {'emotion': '关注', 'detail': f"量价状态{vp}，需警惕", 'light': 'yellow'}
    return {'emotion': '中性', 'detail': '量价数据不足', 'light': 'yellow'}


def _overall_light(market_light: str, sector_light: str, stock_light: str) -> str:
    lights = [market_light, sector_light, stock_light]
    if 'red' in lights:
        return 'red'
    if lights.count('green') >= 2:
        return 'green'
    return 'yellow'


def _emotion_plain(market: dict, sector: dict, stock: dict,
                   quadrant: dict = None, temperature: float = None) -> str:
    parts = []
    phase = market.get('phase', '')
    if phase in ('冰点',):
        parts.append(f'市场极度低迷（{market.get("detail", "")}）')
    elif phase in ('萌芽',):
        parts.append(f'市场开始回暖（{market.get("detail", "")}）')
    elif phase in ('发酵',):
        parts.append(f'市场氛围偏暖（{market.get("detail", "")}）')
    elif phase in ('高潮',):
        parts.append(f'市场情绪过热（{market.get("detail", "")}）')
    elif phase in ('退潮',):
        parts.append(f'市场情绪降温（{market.get("detail", "")}）')
    elif phase in ('回归', '复苏'):
        parts.append(f'市场情绪{phase}（{market.get("detail", "")}）')
    elif phase:
        parts.append(f'市场情绪{phase}')
    else:
        parts.append('市场情绪数据不足')

    if quadrant:
        parts.append(f'四象限={quadrant.get("quadrant","")}({quadrant.get("description","")})')

    if temperature is not None:
        parts.append(f'情绪温度{temperature}/100')

    heat = sector.get('heat', '')
    if heat == 'top_10':
        parts.append(f'所在板块在风口（{sector.get("detail", "")}）')
    elif heat == 'top_20':
        parts.append(f'所在板块较活跃（{sector.get("detail", "")}）')

    stock_emo = stock.get('emotion', '')
    if stock_emo == '健康':
        parts.append('个股情绪健康')
    elif stock_emo == '关注':
        parts.append('个股需关注')

    return '，'.join(parts)


# ═══════════════════════════════════════════════════════════
# 第5维 引擎
# ═══════════════════════════════════════════════════════════


# === bociasi_quadrant.py 完整版（含DB查询） ===

pass  # 412号方案B2：已改为import from app.engine.framework.bociasi_quadrant


# === sector_rotation_model.py 完整版 ===

class SectorRotationModel:
    """板块轮动模型

    核心算法 —— 缠中说禅板块强弱指标法：
    1. 对每个申万一级行业，取该行业下全部个股列表
    2. 统计各股的 MA5 > MA20（女上位=上涨）或 MA5 < MA20（男上位=下跌）
    3. 板块强弱值 = (女上位数量 - 男上位数量) / 板块总股数
    4. 对所有板块的强弱值排序
    5. top_10(前10名) / top_20(11-20名) / normal(21-40名) / none(40名以外)
    """

    HEAT_TOP10 = 'top_10'
    HEAT_TOP20 = 'top_20'
    HEAT_NORMAL = 'normal'
    HEAT_NONE = 'none'

    def __init__(self, data_manager=None):
        self._dm = data_manager
        self._cache = TTLCache(maxsize=1, ttl=1800)  # 30分钟缓存

    @property
    def dm(self):
        if self._dm is None:
            from app.data import DataManager
            self._dm = DataManager()
        return self._dm

    def _get_ma(self, indicator_ma: pd.DataFrame, period: int):
        """从indicator_ma读取MA值，失败返回None（412号方案B3 v3.0）

        不再直接调用DataManager——数据由调用方通过参数传入。
        """
        if indicator_ma is not None and not indicator_ma.empty:
            col = f'ma{period}'
            if col in indicator_ma.columns:
                val = indicator_ma[col].iloc[-1]
                if val is not None:
                    return float(val)
        return None

    def compute_all_heat(self, all_data: dict[str, pd.DataFrame],
                         indicator_ma_dict: dict[str, pd.DataFrame] = None) -> dict:
        """全量预计算，返回 {行业: 排序结果}

        412号方案B3 v3.0：MA值从indicator_ma_dict读取，不再直接调用DataManager。

        Args:
            all_data: 全市场日线数据 {ts_code: df}
            indicator_ma_dict: 预计算MA数据 {ts_code: indicator_ma_df}，由调用方提供

        Returns:
            {industry_name: {'heat_level': ..., 'strength': ..., 'rank': ..., 'stock_count': ...}}
        """
        indicator_ma_dict = indicator_ma_dict or {}
        ts_codes = list(all_data.keys())
        industry_map = self.dm.get_stock_industry_batch(ts_codes)

        # 按行业分组
        industry_stocks: dict[str, list[str]] = {}
        for ts_code, ind in industry_map.items():
            if ind:
                industry_stocks.setdefault(ind, []).append(ts_code)

        industry_strength: dict[str, float] = {}
        industry_counts: dict[str, int] = {}

        for ind, codes in industry_stocks.items():
            if len(codes) < 3:
                continue
            up_count = 0
            down_count = 0
            for code in codes:
                df = all_data.get(code)
                if df is None or df.empty or 'close' not in df.columns:
                    continue
                close = df['close']
                if len(close) < 20:
                    continue
                # 从indicator_ma_dict读取MA，保留raw fallback
                ma5 = self._get_ma(indicator_ma_dict.get(code), 5)
                if ma5 is None:
                    ma5 = close.rolling(window=5).mean().iloc[-1]
                ma20 = self._get_ma(indicator_ma_dict.get(code), 20)
                if ma20 is None:
                    ma20 = close.rolling(window=20).mean().iloc[-1]
                if pd.isna(ma5) or pd.isna(ma20):
                    continue
                if ma5 > ma20:
                    up_count += 1
                else:
                    down_count += 1

            total = up_count + down_count
            if total == 0:
                continue
            strength = (up_count - down_count) / total
            industry_strength[ind] = strength
            industry_counts[ind] = total

        sorted_industries = sorted(industry_strength.items(), key=lambda x: x[1], reverse=True)

        result = {}
        for rank, (ind, strength) in enumerate(sorted_industries, 1):
            if rank <= 10:
                heat = self.HEAT_TOP10
            elif rank <= 20:
                heat = self.HEAT_TOP20
            elif rank <= 40:
                heat = self.HEAT_NORMAL
            else:
                heat = self.HEAT_NONE
            result[ind] = {
                'heat_level': heat,
                'strength': round(strength, 4),
                'rank': rank,
                'stock_count': industry_counts.get(ind, 0),
            }

        self._cache['all_heat'] = result
        return result

    def evaluate(self, ts_code: str) -> dict:
        """评估目标股票所在行业的板块热度（需先调用 compute_all_heat 预热缓存）

        Args:
            ts_code: 目标股票代码

        Returns:
            {'sector_heat': ..., 'sector_name': ..., 'strength': ..., 'rank': ...}
        """
        industry = self.dm.get_stock_industry(ts_code)
        if not industry:
            return {'sector_heat': self.HEAT_NONE, 'sector_name': '', 'strength': 0.0, 'rank': -1}

        all_heat = self._cache.get('all_heat')
        if all_heat is None:
            return {
                'sector_heat': self.HEAT_NONE, 'sector_name': industry,
                'strength': 0.0, 'rank': -1,
            }

        sector_info = all_heat.get(industry)
        if sector_info is None:
            return {
                'sector_heat': self.HEAT_NONE, 'sector_name': industry,
                'strength': 0.0, 'rank': -1,
            }

        return {
            'sector_heat': sector_info['heat_level'],
            'sector_name': industry,
            'strength': sector_info['strength'],
            'rank': sector_info['rank'],
        }


class Dim5EmotionEngine(DataAwareMixin):
    """第5维 情绪环境引擎 — BOCIASI快慢线 + 四象限 + 温度 + 板块热度 + 时间节奏"""

    def __init__(self):
        self._dm = None

    def evaluate(self, dims: dict, tags: dict, signals: dict = None,
                 lifecycle: dict = None, data_context: dict = None) -> dict:
        """统一评估入口

        411号Phase 6：优先使用data_context预加载数据，回退独立查询。
        """

        # 1. BOCIASI快慢线 + 四象限（先于情绪评估，结果回写market）
        quick_result = {"signal": "NEUTRAL", "confidence": 0.3, "pass_count": 0}
        slow_result = {"signal": "NEUTRAL", "confidence": 0.3}
        quadrant = {'quadrant': 'MM', 'description': '市场情绪中性', 'weight_multiplier': 1.0}

        try:
            ecm = self._get_dm().cache
            ts_code = tags.get('ts_code', '')

            # 快线：从日线数据计算4指标
            if ts_code:
                try:
                    # 411号Phase 6：优先使用data_context
                    if data_context and 'daily_df' in data_context:
                        df = data_context['daily_df']
                    else:
                        df = ecm.get_cached_daily(ts_code)
                    if df is not None and not df.empty and len(df) >= 6:
                        quick_result = _bociasi_quickline(df)
                except Exception:
                    pass

            # 慢线：从日线数据计算ERP（413 P2 T7：优先data_context）
            if ts_code:
                try:
                    df_basic = data_context.get('daily_basic_df') if data_context else None
                    if df_basic is None:
                        df_basic = ecm.get_cached_daily_basic(ts_code)
                    if df_basic is not None and not df_basic.empty:
                        slow_result = _bociasi_slowline(df_basic)
                except Exception:
                    pass

            # 四象限：使用完整 BociasiQuadrantAnalyzer（含全市场DB查询）
            try:
                market_stats = data_context.get('market_stats') if data_context else None
                analyzer = BociasiQuadrantAnalyzer(ecm=ecm, market_stats=market_stats)
                full_quadrant = analyzer.analyze()
                quadrant = {
                    'quadrant': full_quadrant.get('quadrant', 'MM'),
                    'description': full_quadrant.get('description', '市场情绪中性'),
                    'weight_multiplier': full_quadrant.get('weight_multiplier', 1.0),
                    'fast_score': full_quadrant.get('fast_score', 0.5),
                    'slow_score': full_quadrant.get('slow_score', 0.5),
                    'fast_signal': quick_result.get('signal', 'NEUTRAL'),
                    'slow_signal': slow_result.get('signal', 'NEUTRAL'),
                }
            except Exception:
                quadrant = _bociasi_quadrant(quick_result, slow_result)

        except Exception:
            pass

        # 2. 三层面情绪评估（BOCIASI quadrant 结果回写 market）
        market = _assess_market_emotion(tags, dims)
        sector = _assess_sector_emotion(tags, dims)
        stock = _assess_stock_emotion(tags, dims)

        # 2b. BOCIASI四象限修正 market 情绪判定
        q = quadrant.get('quadrant', 'MM')
        if q == 'HH':
            if market['light'] == 'green':
                market = {'phase': '高位风险', 'detail': f"BOCIASI四象限={q}（{quadrant['description']}）", 'light': 'red'}
        elif q == 'LL':
            if market['light'] == 'red':
                market = {'phase': '情绪底部', 'detail': f"BOCIASI四象限={q}（{quadrant['description']}）", 'light': 'green'}
        elif q == 'HL':
            if market['light'] == 'green':
                market = {'phase': '高位震荡', 'detail': f"BOCIASI四象限={q}（{quadrant['description']}）", 'light': 'yellow'}
        elif q == 'LH':
            if market['light'] == 'red':
                market = {'phase': '底部反弹', 'detail': f"BOCIASI四象限={q}（{quadrant['description']}）", 'light': 'yellow'}

        # 3. 板块热度（使用完整 SectorRotationModel，复用已有DataManager）
        if tags.get('ts_code'):
            try:
                sr_model = SectorRotationModel(data_manager=self._get_dm())
                heat_result = sr_model.evaluate(tags['ts_code'])
                if heat_result.get('sector_heat') and heat_result['sector_heat'] != 'none':
                    sector['heat'] = heat_result['sector_heat']
                    sector['detail'] = f"板块{heat_result.get('sector_name', '')}(排名{heat_result.get('rank', '?')})"
            except Exception:
                pass

        # 4. 情绪温度（融合BOCIASI真实计算分数 + P10融资余额变化率）
        sp = tags.get('sentiment_phase', 'neutral')
        vp_fit = tags.get('volume_price_fit', 'neutral')

        # P10: 获取融资余额变化率
        margin_change_pct = None
        try:
            if ts_code:
                # 413 P2 T7：优先从data_context读取margin_df
                margin_df = data_context.get('margin_df') if data_context else None
                if margin_df is None:
                    margin_df = ecm.get_cached_margin(ts_code) if ecm else None
                if margin_df is not None and not margin_df.empty and len(margin_df) >= 5:
                    rzye = margin_df['rzye'].dropna().astype(float)
                    if len(rzye) >= 5:
                        margin_change_pct = (rzye.iloc[-1] / rzye.iloc[0] - 1) if rzye.iloc[0] > 0 else None
        except Exception:
            pass

        temperature = calc_emotion_temperature(sentiment_phase=sp, volume_price_fit=vp_fit,
                                               margin_change_pct=margin_change_pct)

        # BOCIASI修正：用快慢线分数加权修正温度
        fast_score = quadrant.get('fast_score', None)
        slow_score = quadrant.get('slow_score', None)
        if fast_score is not None and slow_score is not None:
            bociasi_temp = (float(fast_score) * 0.6 + float(slow_score) * 0.4) * 100
            temperature = round(temperature * 0.4 + bociasi_temp * 0.6, 1)

        # 5. 综合灯色
        overall = _overall_light(market['light'], sector['light'], stock['light'])

        # 6. status_description
        plain = _emotion_plain(market, sector, stock, quadrant, temperature)
        status_description = {
            'market': f"市场处于{market['phase']}（{market['detail']}）",
            'sector': f"板块{sector['heat']}（{sector['detail']}）",
            'stock': f"个股{stock['emotion']}（{stock['detail']}）",
            'bociasi_quick': f"快线={quick_result.get('signal','N/A')}（{quick_result.get('confidence',0)}）",
            'bociasi_slow': f"慢线={slow_result.get('signal','N/A')}（{slow_result.get('confidence',0)}）",
            'quadrant': f"{quadrant.get('quadrant','')} — {quadrant.get('description','')}",
            'temperature': f"{temperature}/100",
            'plain': plain,
        }

        # 7. judgment
        judgment = {
            'market_light': market['light'],
            'sector_light': sector['light'],
            'stock_light': stock['light'],
            'overall_light': overall,
            'overall_direction': 1 if overall == 'green' else (-1 if overall == 'red' else 0),
            'continuous_value': round(temperature / 100, 4),
        }

        # 8. audit
        conditions = [
            {'name': '市场情绪', 'satisfied': market['phase'] not in ('退潮', '冰点'),
             'actual': market['phase'], 'threshold': '非退潮/冰点'},
            {'name': '板块热度', 'satisfied': sector['heat'] in ('top_10', 'top_20'),
             'actual': sector['heat'], 'threshold': 'top_20以内'},
            {'name': '个股情绪', 'satisfied': stock['emotion'] not in ('极度消极',),
             'actual': stock['emotion'], 'threshold': '非极度消极'},
            {'name': 'BOCIASI快线非看空', 'satisfied': quick_result.get('signal') != 'BEARISH',
             'actual': quick_result.get('signal', 'N/A'), 'threshold': '非BEARISH'},
            {'name': '四象限非高风险', 'satisfied': quadrant.get('quadrant') != 'HH',
             'actual': quadrant.get('quadrant', ''), 'threshold': '非HH'},
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
            'tags (pre_feat_cache) — sentiment_phase / sector_heat / volume_price_fit / volume_ratio / trend_alignment',
            'dims (StatusEngine) — emotion / vp',
        ]
