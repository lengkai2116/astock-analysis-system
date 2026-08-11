"""
策略信号实时计算服务
从真实 K 线数据中实时计算 Chip / Chanlun / Factor 等多维度信号
当数据库缓存的策略输出为空时，通过此服务实时计算并返回
"""
import logging
from typing import Dict, List, Optional
from datetime import datetime, date
import pandas as pd
import numpy as np

from app import db
from app.data import DataManager
from app.engine.framework.chip_strategy import ChipScorer
from app.data.chip_indicators import ChipIndicators
from app.models import Signal as SignalModel
from app.models.strategy import StrategySignal
from app.services.strategy_output_service import StrategyOutputService
from app.services.backtest_evidence_service import BacktestEvidenceService
from app.services.benchmark_service import BenchmarkService, BenchmarkIndex
from app.factors.calculator import FactorCalculator

logger = logging.getLogger(__name__)


# ── FMZ 10态 → 情绪周期四阶段映射 ──
_FMZ_TO_EMOTION = {
    "WOLF": "情绪冰点",
    "MACRO": "情绪中性",
    "MEAN_REV": "情绪复苏",
    "MOMENTUM": "情绪高潮",
    "BOX": "情绪中性",
    "EAGLE": "情绪复苏",
    "HIGH_VOL": "情绪高潮",
    "TRENDING_BEAR": "情绪衰退",
    "TRENDING_BULL": "情绪高潮",
    "RANGING": "情绪中性",
}


def _fmz_to_emotion_cycle(market_state: str) -> str:
    """将 FMZ 10态市场状态映射到情绪周期四阶段。"""
    return _FMZ_TO_EMOTION.get(market_state, "情绪中性")


def _dedupe_near_levels(levels: List[Dict]) -> List[Dict]:
    """near_levels 按级别去重，每级别只保留最新一个中枢（zhongshu_list 最新在前）。"""
    seen = set()
    result = []
    for lv in levels:
        level_name = lv.get('level', '')
        if level_name not in seen:
            seen.add(level_name)
            result.append(lv)
    return result


# 买卖点类型中文映射（模块级常量，供 _build_active_signal / _build_active_label 使用）
BP_TYPE_CN = {
    'first_buy': '第一类买点', 'first_buy_p': '盘整背驰第一类买点',
    'second_buy': '第二类买点', 'second_buy_s': '类第二类买点',
    'third_buy': '第三类买点', 'third_buy_a': '第三类买点(一类后)', 'third_buy_b': '第三类买点(一类前)',
    'first_sell': '第一类卖点', 'first_sell_p': '盘整背驰第一类卖点',
    'second_sell': '第二类卖点', 'second_sell_s': '类第二类卖点',
    'third_sell': '第三类卖点', 'third_sell_a': '第三类卖点(一类后)', 'third_sell_b': '第三类卖点(一类前)',
}

# 周期→级别标签映射
_LEVEL_LABELS = {
    'long': '日线',
    'medium': '30分钟',   # medium的决策级别是30分钟
    'short': '5分钟',     # short的决策级别是5分钟
}
def _level_label(period: str) -> str:
    """返回周期对应的中文级别标签"""
    return _LEVEL_LABELS.get(period, '日线')

# Phase 1 P1-2: 构建有效信号（取买卖点中时序最新的一个，过滤过时信号）
def _build_active_signal(best_buy, best_sell, trade_date: str = None, latest_close: float = None) -> dict:
    """从 best_buy / best_sell 中选取时序最新的信号。
    
    过滤规则：
    - 信号日期超过3个月且当前价偏离信号价>20% → 标记为historical，不作为active_signal
    """
    def _is_stale(signal_date: str, signal_price: float) -> bool:
        """判断信号是否过时"""
        if not trade_date or not signal_date or not latest_close or not signal_price:
            return False
        # 计算时间差（月）
        try:
            from datetime import datetime
            sig_dt = datetime.strptime(signal_date[:10], '%Y-%m-%d')
            cur_dt = datetime.strptime(trade_date[:10], '%Y-%m-%d')
            months = (cur_dt.year - sig_dt.year) * 12 + (cur_dt.month - sig_dt.month)
            # 超过3个月且价格偏离>20% → 过时
            if months > 3:
                deviation = abs(latest_close - signal_price) / max(signal_price, 0.01)
                if deviation > 0.20:
                    return True
        except (ValueError, TypeError):
            pass
        return False

    def _make_signal(bp, historical=False):
        return {
            'type': bp.type, 'label': BP_TYPE_CN.get(bp.type, bp.type),
            'date': str(bp.position.get('date', ''))[:10],
            'price': round(bp.position.get('price', 0), 2),
            'current_price': round(latest_close, 2) if latest_close else None,
            'historical': historical,
        }

    if best_buy and best_sell:
        buy_date = str(best_buy.position.get('date', ''))[:10]
        sell_date = str(best_sell.position.get('date', ''))[:10]
        buy_price = round(best_buy.position.get('price', 0), 2)
        sell_price = round(best_sell.position.get('price', 0), 2)
        buy_stale = _is_stale(buy_date, buy_price)
        sell_stale = _is_stale(sell_date, sell_price)
        # 如果两个都过时，返回historical标记
        if buy_stale and sell_stale:
            result = _make_signal(best_sell if sell_date >= buy_date else best_buy, historical=True)
            result['historical'] = True
            return result
        # 取最新且不过时的信号
        if buy_date >= sell_date and not buy_stale:
            return _make_signal(best_buy)
        elif sell_date >= buy_date and not sell_stale:
            return _make_signal(best_sell)
        # 最新信号过时，用另一个
        return _make_signal(best_buy if not buy_stale else best_sell)
    elif best_buy:
        buy_date = str(best_buy.position.get('date', ''))[:10]
        buy_price = round(best_buy.position.get('price', 0), 2)
        if _is_stale(buy_date, buy_price):
            return _make_signal(best_buy, historical=True)
        return _make_signal(best_buy)
    elif best_sell:
        sell_date = str(best_sell.position.get('date', ''))[:10]
        sell_price = round(best_sell.position.get('price', 0), 2)
        if _is_stale(sell_date, sell_price):
            return _make_signal(best_sell, historical=True)
        return _make_signal(best_sell)
    return None


def _build_active_label(best_buy, best_sell, divergence) -> str:
    """构建有效信号的中文描述标签"""
    if best_buy and best_sell:
        buy_label = BP_TYPE_CN.get(best_buy.type, best_buy.type)
        sell_label = BP_TYPE_CN.get(best_sell.type, best_sell.type)
        buy_date = str(best_buy.position.get('date', ''))[:10]
        sell_date = str(best_sell.position.get('date', ''))[:10]
        if buy_date >= sell_date:
            return f'{buy_label}({buy_date})'
        return f'{sell_label}({sell_date})'
    elif best_buy:
        return f'{BP_TYPE_CN.get(best_buy.type, best_buy.type)}({str(best_buy.position.get("date", ""))[:10]})'
    elif best_sell:
        return f'{BP_TYPE_CN.get(best_sell.type, best_sell.type)}({str(best_sell.position.get("date", ""))[:10]})'
    elif divergence:
        return f'{divergence.direction}背驰(置信度:{round(divergence.confidence, 2)})'
    return ''


def _build_filtered_levels(zhongshu_list, latest_close) -> list:
    """构建中枢降级列表：展开expanded中枢为子中枢，偏离 > 30% 标记为 historical"""
    # 先展开: expanded 中枢替换为子中枢链
    refined = []
    for zs in zhongshu_list:
        if zs.type == 'expanded' and zs.sub_zhongshu_list:
            for sub_zs in zs.sub_zhongshu_list:
                if sub_zs.type == 'normal':
                    refined.append(sub_zs)
        else:
            refined.append(zs)
    result = []
    for zs in refined:
        center = float(zs.center) if zs.center else None
        distance_pct = round((latest_close - center) / center * 100, 1) if latest_close and center else None
        is_historical = distance_pct is not None and abs(distance_pct) > 30
        result.append({
            'level': zs.level, 'price': round(float(zs.center), 2) if zs.center else None,
            'support': round(float(zs.low), 2), 'resistance': round(float(zs.high), 2),
            'type': zs.type, 'duration': zs.duration,
            'start_date': str(zs.start_date)[:10] if zs.start_date else '',
            'end_date': str(zs.end_date)[:10] if zs.end_date else '',
            'distance_pct': distance_pct,
            'historical': is_historical,
        })
    return result


# ═══ Phase 2: 量价分析辅助函数 ═══

def _classify_vp_basic(closes, volumes) -> tuple:
    """P2-4: 八种基本量价形态分类 + 确认/异常判断

    Returns:
        (basic_form: str, confirmation: str)
    """
    if len(closes) < 5 or len(volumes) < 5:
        return ('', '')
    try:
        import numpy as np
        price_chg = (closes[-1] / closes[-5] - 1) * 100 if len(closes) >= 5 else 0
        vol_ma5 = np.mean(volumes[-5:])
        vol_ma20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else vol_ma5
        vol_ratio = vol_ma5 / max(vol_ma20, 1)

        # 八种基本形态（阈值可调）
        if price_chg > 3 and vol_ratio > 1.3:
            form = '量增价涨'
        elif price_chg > 3 and vol_ratio < 0.7:
            form = '量缩价涨'
        elif price_chg < -3 and vol_ratio > 1.3:
            form = '量增价跌'
        elif price_chg < -3 and vol_ratio < 0.7:
            form = '量缩价跌'
        elif abs(price_chg) <= 3 and vol_ratio > 1.3:
            form = '量增价平'
        elif abs(price_chg) <= 3 and vol_ratio < 0.7:
            form = '量缩价平'
        elif price_chg > 6 and vol_ratio > 2.5:
            form = '天量天价'
        elif price_chg < -6 and vol_ratio < 0.4:
            form = '地量地价'
        else:
            form = '量平'

        # 确认/异常判断
        if price_chg > 0 and vol_ratio >= 1.3:
            confirmation = 'confirmed'
        elif price_chg > 0 and vol_ratio <= 0.6:
            confirmation = 'abnormal'
        elif price_chg < 0 and vol_ratio > 1.5:
            confirmation = 'confirmed'
        elif price_chg < 0 and vol_ratio < 0.5:
            confirmation = 'abnormal'
        else:
            confirmation = 'normal'

        return (form, confirmation)
    except Exception:
        return ('', '')


def _calc_zhongshu_strength(df, zhongshu_list, chip_signal=None) -> Optional[str]:
    """P2-6: 形态量化中枢 (V1) — 中枢区间+量价集中度+筹码锁定 → 中枢强度评分

    Args:
        df: K线 DataFrame (含 close, vol, high, low)
        zhongshu_list: 中枢列表
        chip_signal: 可选，筹码信号 status_recognition（含 asr 字段）

    Returns:
        "strong" / "weak" / None（数据不足时）
    """
    if df is None or df.empty or not zhongshu_list:
        return None
    try:
        latest_zs = zhongshu_list[0]
        zs_low = float(latest_zs.low)
        zs_high = float(latest_zs.high)
        if zs_low <= 0 or zs_high <= 0 or zs_low >= zs_high:
            return None

        closes = df['close'].astype(float).values
        volumes = df['vol'].astype(float).values
        if len(closes) < 20:
            return None

        # 1) 量价集中度: 落在中枢区间的K线中，成交量占比
        in_zone = (closes >= zs_low) & (closes <= zs_high)
        vol_in_zone = volumes[in_zone].sum() if in_zone.any() else 0
        total_vol = volumes.sum()
        vol_concentration = vol_in_zone / total_vol if total_vol > 0 else 0

        # 2) 筹码锁定程度 (ASR): 低 ASR → 筹码锁定好 → 中枢稳固
        asr = None
        if chip_signal:
            asr_val = chip_signal.get('asr') if isinstance(chip_signal, dict) else None
            if asr_val is not None:
                try:
                    asr = float(asr_val)
                except (ValueError, TypeError):
                    asr = None

        # 3) 中枢宽度（宽中枢不如窄中枢稳固）
        zs_center = (zs_low + zs_high) / 2
        range_pct = (zs_high - zs_low) / zs_center if zs_center > 0 else 0

        # 评分规则
        score = 0.0
        # 量价集中度 > 40% → +1 分
        if vol_concentration > 0.4:
            score += 1.0
        elif vol_concentration > 0.25:
            score += 0.5

        # ASR < 30% (筹码锁定) → +1 分; ASR > 60% (松散) → -0.5
        if asr is not None:
            if asr < 0.3:
                score += 1.0
            elif asr < 0.45:
                score += 0.5
            elif asr > 0.6:
                score -= 0.5

        # 窄中枢 < 5% → +0.5 分; 宽中枢 > 15% → -0.5
        if range_pct < 0.05:
            score += 0.5
        elif range_pct > 0.15:
            score -= 0.5

        return "strong" if score >= 1.0 else "weak"
    except Exception:
        return None


def _calc_vap_support_resistance(closes, highs, lows, volumes, latest_close, n_buckets=50) -> Dict:
    """P2-9: VAP 支撑/阻力 (V4) — OHLCV → 成交量密集价格区

    Args:
        closes: 收盘价序列
        highs: 最高价序列
        lows: 最低价序列
        volumes: 成交量序列
        latest_close: 最新收盘价
        n_buckets: 价格桶数量

    Returns:
        {'vap_support': float|None, 'vap_resistance': float|None}
    """
    if len(closes) < 30 or latest_close <= 0:
        return {'vap_support': None, 'vap_resistance': None}
    try:
        # 取最近 120 根K线
        n = min(120, len(closes))
        closes = closes[-n:]
        highs = highs[-n:]
        lows = lows[-n:]
        volumes = volumes[-n:]

        price_min = min(lows)
        price_max = max(highs)
        if price_max <= price_min:
            return {'vap_support': None, 'vap_resistance': None}

        bucket_size = (price_max - price_min) / n_buckets

        # 初始化桶
        buckets = [0.0] * n_buckets

        # 每根K线的成交量按价格区间分配到桶
        for i in range(len(closes)):
            vol = float(volumes[i])
            h = float(highs[i])
            l = float(lows[i])
            # 粗略分配: 将成交量均分到高-低跨越的每个桶
            start_bucket = max(0, int((l - price_min) / bucket_size))
            end_bucket = min(n_buckets - 1, int((h - price_min) / bucket_size))
            span = max(1, end_bucket - start_bucket + 1)
            vol_per_bucket = vol / span
            for b in range(start_bucket, end_bucket + 1):
                buckets[b] += vol_per_bucket

        # 找到成交量最大的桶 -> 价格中心
        total_vol_all = sum(buckets)
        if total_vol_all <= 0:
            return {'vap_support': None, 'vap_resistance': None}

        # 将桶按成交量排序，取前 20% 的桶的中心价
        threshold = 0.02  # 最低成交量阈值（占总量的比例）
        significant_prices = []
        for b in range(n_buckets):
            ratio = buckets[b] / total_vol_all
            if ratio >= threshold:
                price = price_min + (b + 0.5) * bucket_size
                significant_prices.append({'price': round(price, 2), 'weight': ratio})

        if not significant_prices:
            return {'vap_support': None, 'vap_resistance': None}

        # 按价格排序
        significant_prices.sort(key=lambda x: x['price'])

        # 支撑: 低于当前价的最大成交量密集区
        support = None
        resistance = None
        for sp in significant_prices:
            if sp['price'] < latest_close * 0.98:
                if support is None or sp['weight'] > support.get('weight', 0):
                    support = sp
            elif sp['price'] > latest_close * 1.02:
                if resistance is None or sp['weight'] > resistance.get('weight', 0):
                    resistance = sp

        return {
            'vap_support': support['price'] if support else None,
            'vap_resistance': resistance['price'] if resistance else None,
        }
    except Exception:
        return {'vap_support': None, 'vap_resistance': None}


def _calc_cross_compare(
    net_lg_amount_5d: Optional[float],
    main_force_cost_price: float,
    margin_cost_price: Optional[float],
    latest_close: float,
    sentiment_crowding_label: Optional[str] = None,
    price_position: Optional[float] = None,
) -> dict:
    """P2-2: 交叉比对比法 — 主力资金+散户情绪+股价位置三维交叉

    知识库定义（筹码分布分析-主力视角.md）：
      - 做多场景：法人持续买超 + 股价站稳主力集中价 + 融资在低位
      - 卖出场景：融资急剧增加 + 股价滞涨 / 开始下跌
      - 分歧信号：主力买 vs 法人卖 → 保持谨慎

    Args:
        net_lg_amount_5d: 近5日大单净额（正=主力流入，负=主力流出）
        main_force_cost_price: 主力集中价
        margin_cost_price: 融资成本价（散户买入均价）
        latest_close: 当前收盘价
        sentiment_crowding_label: 情绪拥挤度标签 (overheat/cooling/normal)
        price_position: 价格在120日区间中的分位 (0.0-1.0)

    Returns:
        {"conclusion": str, "detail": str, "score": float}
        conclusion: consensus_bullish / consensus_bearish / divergence_main_strong
                    / divergence_retail_danger / neutral
    """
    result = {"conclusion": "neutral", "detail": "", "score": 0.0}
    try:
        # === 维度1：主力资金方向 ===
        main_bullish = None  # True=看多, False=看空, None=中性
        main_detail = ""
        if net_lg_amount_5d is not None and abs(net_lg_amount_5d) > 1e5:
            if net_lg_amount_5d > 0:
                main_bullish = True
                main_detail = f"主力净流入{net_lg_amount_5d / 1e4:.0f}万"
            else:
                main_bullish = False
                main_detail = f"主力净流出{abs(net_lg_amount_5d) / 1e4:.0f}万"

        # === 维度2：散户情绪（融资成本 vs 情绪拥挤度）===
        retail_danger = False  # 散户危险信号
        retail_detail = ""
        # 情绪拥挤度：overheat = 散户过热 → 危险
        if sentiment_crowding_label == 'overheat':
            retail_danger = True
            retail_detail = "情绪过热"
        elif sentiment_crowding_label == 'cooling':
            retail_detail = "情绪冷却"

        # 融资成本价：股价接近/低于融资成本 → 散户亏损，抛压减轻
        margin_position = None  # 'above' / 'below' / 'near'
        if margin_cost_price and margin_cost_price > 0 and latest_close > 0:
            margin_distance = (latest_close - margin_cost_price) / margin_cost_price
            if margin_distance < -0.03:
                margin_position = 'below'  # 股价低于融资成本，散户套牢
                retail_detail += " 散户套牢"
            elif margin_distance < 0.03:
                margin_position = 'near'  # 接近融资成本
                retail_detail += " 接近融资成本"
            else:
                margin_position = 'above'  # 股价高于融资成本
                retail_detail += " 散户盈利"

        # === 维度3：股价位置 vs 主力成本 ===
        main_pos_detail = ""
        main_force_protected = False  # 股价在主力成本附近，有支撑
        if main_force_cost_price > 0 and latest_close > 0:
            cost_distance = (latest_close - main_force_cost_price) / main_force_cost_price
            if abs(cost_distance) < 0.05:
                main_force_protected = True
                main_pos_detail = "站稳主力成本"
            elif cost_distance > 0.15:
                main_pos_detail = "偏离主力成本过高"
            elif cost_distance < -0.1:
                main_pos_detail = "跌破主力成本"
            else:
                main_pos_detail = "在主力成本上方"

        # === 综合判断 ===
        details = [d for d in [main_detail, retail_detail, main_pos_detail] if d]
        result['detail'] = '; '.join(details)

        if main_bullish is True and not retail_danger and main_force_protected:
            result['conclusion'] = 'consensus_bullish'
            result['score'] = 1.0
            result['detail'] += " → 一致看多"
        elif main_bullish is False and retail_danger:
            result['conclusion'] = 'consensus_bearish'
            result['score'] = -1.0
            result['detail'] += " → 一致看空"
        elif main_bullish is True and retail_danger:
            result['conclusion'] = 'divergence_retail_danger'
            result['score'] = -0.3
            result['detail'] += " → 分歧:主力做多但散户过热"
        elif main_bullish is False and main_force_protected:
            result['conclusion'] = 'divergence_main_strong'
            result['score'] = 0.2
            result['detail'] += " → 分歧:主力流出但成本有支撑"
        elif main_bullish is True and margin_position == 'above':
            result['conclusion'] = 'divergence_main_bullish'
            result['score'] = 0.5
            result['detail'] += " → 分歧:主力做多但散户已盈利"
        elif not retail_danger and main_force_protected:
            result['conclusion'] = 'consensus_bullish'
            result['score'] = 0.5
            result['detail'] += " → 温和看多"

        return result
    except Exception:
        return result


def _calc_lhb_high_success_strategy(
    symbol: str,
    lhb_detail_df,
    df,
    concept_name: str = None,
    idx_5d_ret: float = None,
    idx_20d_ret: float = None,
) -> dict:
    """P3-1: 龙虎榜高成功率战法 — 四条件评分

    知识库定义（龙虎榜高成功率战法.md）：
      条件1: 机构重金 — 机构席位买入占比高
      条件2: 攻击形态 — 突破性K线形态
      条件3: 板块效应 — 所属板块近期强势
      条件4: 大盘环境 — 大盘趋势稳定或向上

    Args:
        symbol: 股票代码
        lhb_detail_df: 席位级龙虎榜数据
        df: OHLCV K线数据
        concept_name: 所属行业/概念名称
        idx_5d_ret: 大盘5日收益率(%)
        idx_20d_ret: 大盘20日收益率(%)

    Returns:
        {"score": float, "conditions": dict, "detail": str}
        score: 0-100分，>=60表示高成功率战法机会
    """
    result = {"score": 0.0, "conditions": {}, "detail": ""}
    try:
        conditions = []
        details = []

        # 条件1: 机构重金 (0-40分)
        inst_score = 0.0
        if lhb_detail_df is not None and not lhb_detail_df.empty:
            if 'seat_type' in lhb_detail_df.columns and 'buy_amount' in lhb_detail_df.columns:
                inst_mask = lhb_detail_df['seat_type'] == 'institution'
                inst_buy = lhb_detail_df[inst_mask]['buy_amount'].sum()
                total_buy = lhb_detail_df['buy_amount'].sum()
                if total_buy > 0:
                    inst_ratio = inst_buy / total_buy
                    if inst_ratio > 0.5:
                        inst_score = 40.0
                        details.append("机构重金:机构买入占比{:.0%}>50%".format(inst_ratio))
                    elif inst_ratio > 0.3:
                        inst_score = 30.0
                        details.append("机构重金:机构买入占比{:.0%}>30%".format(inst_ratio))
                    elif inst_ratio > 0.1:
                        inst_score = 15.0
                        details.append("机构重金:机构买入占比{:.0%}>10%".format(inst_ratio))
                    else:
                        details.append("机构重金:机构买入仅{:.0%}，力度不足".format(inst_ratio))
                else:
                    details.append("机构重金:龙虎榜无买入数据")
            else:
                details.append("机构重金:无席位明细数据")
        else:
            inst_score = 0.0
            details.append("机构重金:未上龙虎榜")
        result['conditions']['institutional_money'] = inst_score

        # 条件2: 攻击形态 (0-30分)
        shape_score = 0.0
        if df is not None and len(df) >= 30:
            try:
                from app.engine.framework.volume_price_strategy import VolumePriceStrategy
                vp = VolumePriceStrategy()
                vp_result = vp.analyze(df)
                if vp_result and vp_result.get('success'):
                    signal = vp_result.get('signal', '')
                    if signal in ('BUY', 'STRONG_BUY'):
                        shape_score = 30.0
                        details.append("攻击形态:量价给出买入信号({})".format(signal))
                    elif signal in ('WATCH',):
                        shape_score = 15.0
                        details.append("攻击形态:量价信号中性({})".format(signal))
                    else:
                        details.append("攻击形态:量价信号{}，非买入时机".format(signal))
                else:
                    details.append("攻击形态:量价分析未成功")
            except Exception:
                # 降级：用简单价格突破判断
                closes = df['close'].values
                ma_20 = float(pd.Series(closes[-20:]).mean()) if len(closes) >= 20 else closes[-1]
                ma_60 = float(pd.Series(closes[-60:]).mean()) if len(closes) >= 60 else closes[-1]
                if closes[-1] > ma_20 > ma_60:
                    shape_score = 25.0
                    details.append("攻击形态:价格站上MA20>MA60，多头排列")
                elif closes[-1] > ma_20:
                    shape_score = 15.0
                    details.append("攻击形态:价格站上MA20，短期偏多")
                else:
                    details.append("攻击形态:价格在MA20下方，形态偏弱")
        else:
            details.append("攻击形态:数据不足")
        result['conditions']['attack_shape'] = shape_score

        # 条件3: 板块效应 (0-20分)
        sector_score = 0.0
        if concept_name and concept_name != 'nan':
            try:
                # 从 InMemoryStateStore 获取板块排行
                from app.data.in_memory_store import store as mem_store
                sectors = mem_store.get_concepts()
                if sectors:
                    for s in sectors:
                        if s.get('concept_name') == concept_name or s.get('name') == concept_name:
                            pct = float(s.get('change_pct', 0))
                            if pct > 3:
                                sector_score = 20.0
                                details.append("板块效应:{}涨幅{:.1f}%领先".format(concept_name, pct))
                            elif pct > 1:
                                sector_score = 10.0
                                details.append("板块效应:{}涨幅{:.1f}%".format(concept_name, pct))
                            else:
                                details.append("板块效应:{}涨幅{:.1f}%偏弱".format(concept_name, pct))
                            break
                    else:
                        details.append("板块效应:{}未在活跃板块排行中".format(concept_name))
                else:
                    details.append("板块效应:板块排行数据暂不可用(非交易时段)")
            except Exception:
                details.append("板块效应:板块排行查询异常")
        else:
            details.append("板块效应:无行业分类")
        result['conditions']['sector_momentum'] = sector_score

        # 条件4: 大盘环境 (0-10分)
        env_score = 0.0
        if idx_5d_ret is not None and idx_20d_ret is not None:
            try:
                idx_5d = float(idx_5d_ret)
                idx_20d = float(idx_20d_ret)
                if idx_5d > 2 or idx_20d > 5:
                    env_score = 10.0
                    details.append("大盘环境:偏强(5日{:.1f}%/20日{:.1f}%)".format(idx_5d, idx_20d))
                elif idx_5d > 0 or idx_20d > 0:
                    env_score = 5.0
                    details.append("大盘环境:中性(5日{:.1f}%/20日{:.1f}%)".format(idx_5d, idx_20d))
                else:
                    details.append("大盘环境:偏弱(5日{:.1f}%/20日{:.1f}%)".format(idx_5d, idx_20d))
            except Exception:
                details.append("大盘环境:收益率数据异常")
        else:
            details.append("大盘环境:无大盘数据")
        result['conditions']['market_environment'] = env_score

        # 总评
        total = inst_score + shape_score + sector_score + env_score
        result['score'] = round(total, 1)
        result['detail'] = '; '.join(details)

        return result
    except Exception:
        return result


def _calc_chip_concentration_factor(symbol: str, dm=None) -> dict:
    """P2-1: 筹码集中度因子 — 大股东持仓比例变化率

    知识库定义（筹码集中度因子.md）：
      正值增加：筹码在集中，大股东在增持 → 利好
      负值减少：筹码在分散，大股东在减持 → 利空

    数据路径：
      主路径: top10_holders_cache.hold_ratio → 前十大股东合计持仓变化率
      降级路径: stk_holder_cache.holder_number → 股东户数变化率

    Args:
        symbol: 股票代码
        dm: DataManager 实例

    Returns:
        {"factor": float, "change_pct": float, "source": str, "detail": str}
        factor: 因子值 >0 集中，<0 分散，0 无数据
        change_pct: 变化率（%）
        source: 'top10_holders' / 'stk_holder' / 'none'
        detail: 文字说明
    """
    result = {"factor": 0.0, "change_pct": 0.0, "source": "none", "detail": "数据不足"}
    if not symbol or dm is None:
        return result
    try:
        # 主路径: top10_holders_cache 计算前十大持仓变化率
        top10_df = dm.get_cached_top10_holders(symbol)
        if top10_df is not None and not top10_df.empty and 'hold_ratio' in top10_df.columns:
            # 按 end_date 分组聚合，计算每个季度前十大合计持仓比例
            top10_df = top10_df.dropna(subset=['hold_ratio'])
            if not top10_df.empty:
                grouped = top10_df.groupby('end_date')['hold_ratio'].sum().reset_index()
                grouped = grouped.sort_values('end_date')
                if len(grouped) >= 2:
                    latest = float(grouped['hold_ratio'].iloc[-1])
                    earliest = float(grouped['hold_ratio'].iloc[-2])
                    if earliest > 0:
                        change_pct = round((latest - earliest) / earliest * 100, 2)
                        factor = round(change_pct / 10, 2)  # 归一化：10%变化→1.0
                        detail = "前十大合计持仓{:.2f}%→{:.2f}%（变化{:+.2f}%）".format(
                            earliest, latest, change_pct)
                        return {"factor": factor, "change_pct": change_pct,
                                "source": "top10_holders", "detail": detail}
                elif len(grouped) == 1:
                    # 只有一期数据，输出绝对值
                    latest = float(grouped['hold_ratio'].iloc[-1])
                    factor = round(latest / 100, 2)  # 50% → 0.5
                    return {"factor": factor, "change_pct": 0.0,
                            "source": "top10_holders",
                            "detail": "前十大持仓{:.2f}%（仅一期数据，无变化率）".format(latest)}

        # 降级路径: stk_holder_cache 股东户数变化率
        holder_df = dm.get_cached_stk_holder(symbol)
        if holder_df is not None and not holder_df.empty and 'holder_number' in holder_df.columns:
            h = holder_df.dropna(subset=['holder_number']).sort_values('end_date')
            if len(h) >= 2:
                latest = float(h['holder_number'].iloc[-1])
                prev = float(h['holder_number'].iloc[-2])
                if prev > 0:
                    change_pct = round((latest - prev) / prev * 100, 2)
                    factor = round(-change_pct / 10, 2)  # 户数减少=集中→正因子
                    return {"factor": factor, "change_pct": change_pct,
                            "source": "stk_holder",
                            "detail": "股东户数{:.0f}→{:.0f}（变化{:+.2f}%，减少=集中）".format(
                                prev, latest, change_pct)}

        return result
    except Exception:
        dm.request_data('top10_holders', symbol)
        dm.request_data('stk_holder', symbol)
        return result


def _apply_phase_weight(result: dict, chip_phase: str, market_state: str) -> dict:
    """P2-5/P2-8: 主力阶段权重 + 市场状态动态调整 (C4/V3)

    根据主力操盘阶段和市场状态调整量价信号置信度。
    """
    adjustment = {'phase': chip_phase, 'market_state': market_state, 'delta': 0}
    confidence = result.get('confidence', 0.5)
    delta = 0.0

    # P2-5: 主力阶段权重
    phase_map = {
        'accumulating': 0.10,  # 建仓→预涨增信
        'markup': 0.15,        # 拉升→趋势增信
        'washing': -0.05,      # 洗盘→降信
        'distributing': -0.10, # 出货→降信
    }
    delta += phase_map.get(chip_phase, 0)

    # P2-8: 市场状态动态权重
    if market_state == 'RANGING':
        delta -= 0.10  # 震荡市所有信号减半
    elif market_state == 'TRENDING_BULL':
        delta += 0.05  # 牛市轻微增信
    elif market_state == 'HIGH_VOL':
        delta -= 0.15  # 高波动减信

    adjustment['delta'] = round(delta, 2)
    result['confidence'] = round(max(0.05, min(1.0, confidence + delta)), 2)
    return adjustment


def _detect_volume_reversal_sequence(closes, volumes, highs, lows) -> Optional[str]:
    """P2-7: 放量止跌/放量止涨序列检测 (V2)

    检测4步反转序列：
    放量止跌: 暴跌+高量 → 长下影+高量 → 低实体+高量 → 锤头线
    放量止涨: 上涨+高量 → 长上影+高量 → 低实体+高量 → 射击之星
    """
    if len(closes) < 8:
        return None
    try:
        import numpy as np
        recent = slice(-8, None)
        c, v, h, lo = closes[recent], volumes[recent], highs[recent], lows[recent]
        vol_ma20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else np.mean(volumes)

        # 检查最后4根K线是否满足放量止跌序列
        last4_v = v[-4:] / max(vol_ma20, 1)
        last4_body = abs(c[-4:] - np.where(c[-4:] > 0, 
            np.array([l[0] for l in zip(*(lo[-4:], h[-4:]))]), c[-4:]))  # 简化为收盘价

        # 简化检测：最近一根K线为锤头线且前3根中有2根放量
        last_body = abs(c[-1] - lo[-1])
        last_upper = h[-1] - max(c[-1], lo[-1])
        last_lower = min(c[-1], lo[-1]) - lo[-1]
        is_hammer = last_lower > last_body * 2 and last_upper < last_body * 0.3
        is_shooting = last_upper > last_body * 2 and last_lower < last_body * 0.3

        high_vol_days = sum(1 for r in last4_v[:-1] if r > 1.5)
        recent_down = c[-1] < c[-5]
        recent_up = c[-1] > c[-5]

        if is_hammer and high_vol_days >= 2 and recent_down:
            return 'accumulation'  # 放量止跌→局内人吸筹
        if is_shooting and high_vol_days >= 2 and recent_up:
            return 'distribution'  # 放量止涨→局内人派筹

        return None
    except Exception:
        return None


class SignalComputationService:
    """策略信号计算服务"""

    def __init__(self):
        self._data_manager = None
        self._chip_strategy = None
        self._benchmark_service = None
        self.last_data_availability = {}  # 上次计算的扩展数据可用性状态

    @property
    def data_manager(self):
        if self._data_manager is None:
            self._data_manager = DataManager()
        return self._data_manager

    @property
    def chip_strategy(self):
        if self._chip_strategy is None:
            from app.engine.pipeline import ChipDistributionStrategy
            self._chip_strategy = ChipDistributionStrategy(data_manager=self.data_manager)
        return self._chip_strategy

    @property
    def benchmark_service(self):
        if self._benchmark_service is None:
            self._benchmark_service = BenchmarkService()
        return self._benchmark_service

    # [P1-#27] 各策略独立取数窗口配置
    STRATEGY_WINDOWS = {
        'chanlun': 130,      # 缠论需要足量数据构建笔段中枢
        'volume_price': 130, # 量价策略需要120根完整MA计算
        'chip': 70,          # 筹码分析70根已足够
        'factor': 30,        # 因子大多14-20周期
        'bociasi': 30,       # BOCIASI快线30根
        'long_term': 260,    # 长线锚点需250日线
    }

    def compute_for_stock(self, ts_code: str, limit: int = 5, period: str = 'long') -> List[Dict]:
        """
        对单只股票计算多维策略信号
        
        Args:
            period: 分析周期 'long'(长线)/'medium'(中线)/'short'(短线)
                    对应数据：
                    long:   周线/日线/60分钟
                    medium: 日线/30分钟/5分钟
                    short:  30分钟/5分钟/1分钟

        Returns:
            信号列表，格式与 StrategyOutput.to_dict() 一致
        """
        df = self.data_manager.get_cached_daily_data(ts_code, adj='hfq')
        if df.empty or len(df) < 60:
            # 即使日线不足，也独立检测资金流向数据可用性
            mf_available = False
            try:
                mf_check = self.data_manager.get_cached_moneyflow(ts_code)
                mf_available = mf_check is not None and not mf_check.empty
            except Exception:
                self.data_manager.request_data('full_moneyflow', ts_code)
            self.last_data_availability = {
                'ts_code': ts_code,
                'kline': len(df) >= 60,
                'daily_basic': False,
                'moneyflow': mf_available,
                'index': False,
                'market_state': False,
            }
            return []

        # 确保列名统一
        for col in ['open', 'high', 'low', 'close', 'vol']:
            if col in df.columns:
                df[col] = df[col].astype(float)
        if 'vol' not in df.columns and 'amount' in df.columns:
            df['vol'] = df['amount']

        # ── 加载扩展数据：基本面 + 资金流向 + 大盘环境 ──
        market_context, da = self._load_market_context(ts_code, df)
        signals = []

        # ── L2: 筹码主力分析信号 ──
        try:
            chip_signal = self._compute_chip_signal(ts_code, df, market_context)
            if chip_signal:
                signals.append(chip_signal)
        except Exception as e:
            logger.debug(f"{ts_code} Chip 信号计算失败: {e}")

        # ── L3: 缠论信号（优先读缓存） ──
        try:
            from app.services.analysis_cache import get_analysis_cache
            cache = get_analysis_cache()
            cl_key = f"chanlun:{ts_code}:{len(df)}"
            chanlun_signal = cache.get(cl_key)
            if chanlun_signal is None:
                chanlun_signal = self._compute_chanlun_signal(ts_code, df, market_context, period=period)
                if chanlun_signal:
                    cache.set(cl_key, chanlun_signal)
            if chanlun_signal:
                signals.append(chanlun_signal)
        except Exception as e:
            logger.debug(f"{ts_code} 缠论信号计算失败: {e}")

        # ── L3: 因子评分信号 ──
        try:
            factor_signal = self._compute_factor_signal(ts_code, df, market_context)
            if factor_signal:
                signals.append(factor_signal)
        except Exception as e:
            logger.debug(f"{ts_code} 因子信号计算失败: {e}")

        # ── L3: 量价分析信号（优先读缓存） ──
        try:
            from app.services.analysis_cache import get_analysis_cache
            cache = get_analysis_cache()
            vp_key = f"vp:{ts_code}:{len(df)}"
            volume_price_signal = cache.get(vp_key)
            if volume_price_signal is None:
                volume_price_signal = self._compute_volume_price_signal(ts_code, df, market_context, market_env)
                if volume_price_signal:
                    cache.set(vp_key, volume_price_signal)
            if volume_price_signal:
                signals.append(volume_price_signal)
        except Exception as e:
            logger.debug(f"{ts_code} 量价信号计算失败: {e}")

        # ── BOCIASI 快线（情绪层）──
        try:
            bociasi_signal = self._compute_bociasi_signal(ts_code, df, market_context)
            if bociasi_signal:
                signals.append(bociasi_signal)
        except Exception as e:
            logger.debug(f"{ts_code} BOCIASI 信号计算失败: {e}")

        # ── BOCIASI 慢线（情绪层跨市场）[P1-#22] ──
        try:
            from app.engine.framework.bociasi_slowline import BociasiSlowLine
            bsl = BociasiSlowLine()
            # 获取指数数据
            try:
                index_data = self.benchmark_service.get_index_daily() if self.benchmark_service else None
            except Exception:
                index_data = None
                # 指数数据日终 15:30 同步覆盖
            bociasi_slow = bsl.evaluate(df, index_df=index_data)
            if bociasi_slow:
                signals.append({
                    'strategy_name': 'BOCIASI慢线(情绪-跨市场)',
                    'status_recognition': {
                        'state': 'ACCUMULATING' if bociasi_slow.get('signal') == 'BULLISH' else ('DISTRIBUTING' if bociasi_slow.get('signal') == 'BEARISH' else 'RANGING'),
                        'state_label': _fmz_to_emotion_cycle(market_context.get('market_state', '')),
                        'trend': {'direction': 'up' if bociasi_slow.get('signal') == 'BULLISH' else ('down' if bociasi_slow.get('signal') == 'BEARISH' else ''), 'strength': '', 'stage': ''},
                        'momentum': {'level': bociasi_slow.get('signal', ''), 'score': bociasi_slow.get('confidence', 0.0)},
                        'volume': {'state': '', 'structure': ''},
                        'support_resistance': {'support': 0.0, 'resistance': 0.0},
                        'risk_level': 'MEDIUM',
                    },
                    'signal': bociasi_slow.get('signal', 'NEUTRAL').lower(),
                    'signal_label': '做多' if bociasi_slow.get('signal') == 'BULLISH' else ('做空' if bociasi_slow.get('signal') == 'BEARISH' else '中性'),
                    'confidence': bociasi_slow.get('confidence', 0.3),
                    'evidence': [f"ERP={bociasi_slow['details'].get('erp','N/A')}", f"相对强度={bociasi_slow['details'].get('sb_details',{}).get('relative_strength','N/A')}%"],
                    'risk_notes': ['模型依赖PE数据和国债收益率近似值'],
                })
        except Exception as e:
            logger.debug(f"{ts_code} BOCIASI慢线跳过: {e}")

        # [P1-#26] 主决策周期方向约束: 周线(120日)看空时日线买入信号降权
        if market_context.get('market_state') == 'TRENDING_BEAR' or market_context.get('ma_trend') == 'bearish':
            for sig in signals:
                if sig.get('signal') == 'bullish':
                    sig['signal'] = 'watch'
                    sig['signal_label'] = '暂缓买入(周线偏空)'
                    sig['confidence'] = sig.get('confidence', 0.5) * 0.7
                    if 'evidence' in sig:
                        sig['evidence'].append('⚠️ 周线偏空，买入信号降权')
                elif sig.get('signal') == 'neutral':
                    sig['signal'] = 'watch'

        # ── Vibe 策略分析（渠道二新增） ──
        try:
            vibe_signal = self._compute_vibe_signal(ts_code, df)
            if vibe_signal:
                signals.append(vibe_signal)
        except Exception as e:
            logger.debug(f"{ts_code} Vibe 策略跳过: {e}")

        return self._apply_post_processing(signals, market_context, ts_code, df, limit)


    def _load_market_context(self, ts_code: str, df: pd.DataFrame):
        """加载扩展数据（daily_basic/moneyflow/index/market_state）+ 构建市场上下文

        从 compute_for_stock 提取的数据加载模块（P3重构）。
        返回 (market_context, da) 二元组供策略计算使用。
        """
        market_context: Dict = {}
        da: Dict = {'daily_basic': False, 'moneyflow': False, 'index': False, 'market_state': False}

        # 1) daily_basic: 换手率、市值、PE/PB
        try:
            df_basic = self.data_manager.get_cached_daily_basic(ts_code)
            if df_basic is not None and not df_basic.empty:
                latest_basic = df_basic.iloc[-1].to_dict()
                market_context['turnover_rate'] = latest_basic.get('turnover_rate', None)
                market_context['turnover_rate_f'] = latest_basic.get('turnover_rate_f', None)
                market_context['total_mv'] = latest_basic.get('total_mv', None)
                market_context['circ_mv'] = latest_basic.get('circ_mv', None)
                market_context['pe'] = latest_basic.get('pe', None)
                market_context['pe_ttm'] = latest_basic.get('pe_ttm', None)
                market_context['pb'] = latest_basic.get('pb', None)
                market_context['volume_ratio'] = latest_basic.get('volume_ratio', None)
                da['daily_basic'] = True
                logger.debug(f"{ts_code} 已加载 daily_basic: 换手率={market_context.get('turnover_rate')}, "
                             f"市值={market_context.get('circ_mv')}")
        except Exception as e:
            logger.debug(f"{ts_code} daily_basic 加载跳过: {e}")
            self.data_manager.request_data('full_basic', ts_code)

        # 1.5) 价格位置计算：乖离率、历史分位、BOLL带宽、均线粘合
        try:
            closes = df['close'].values
            n = len(closes)
            if n >= 60:
                latest_c = float(closes[-1])
                ma5 = float(np.mean(closes[-5:])) if n >= 5 else latest_c
                ma20 = float(np.mean(closes[-20:])) if n >= 20 else latest_c
                ma60 = float(np.mean(closes[-60:])) if n >= 60 else latest_c
                market_context['bias_ma5'] = round((latest_c - ma5) / ma5 * 100, 2) if ma5 else None
                market_context['bias_ma20'] = round((latest_c - ma20) / ma20 * 100, 2) if ma20 else None
                market_context['bias_ma60'] = round((latest_c - ma60) / ma60 * 100, 2) if ma60 else None
                lookback = min(n, 250)
                recent = closes[-lookback:]
                rank = sum(1 for v in recent if v <= latest_c)
                market_context['percentile_250d'] = round(rank / lookback * 100, 1) if lookback else None
                if n >= 20:
                    ma20_arr = float(np.mean(closes[-20:]))
                    std20 = float(np.std(closes[-20:]))
                    if ma20_arr:
                        boll_upper = ma20_arr + 2 * std20
                        boll_lower = ma20_arr - 2 * std20
                        market_context['boll_bandwidth'] = round((boll_upper - boll_lower) / ma20_arr * 100, 2)
                if n >= 60:
                    ma10 = float(np.mean(closes[-10:]))
                    mas = [ma5, ma10, ma20, ma60]
                    ma_min = min(mas)
                    ma_max = max(mas)
                    market_context['ma_convergence'] = round((ma_max - ma_min) / ma_min * 100, 2) if ma_min else None
        except Exception as e:
            logger.debug(f"{ts_code} 价格位置计算跳过: {e}")

        # 2) 资金流向
        try:
            df_mf = self.data_manager.get_cached_moneyflow(ts_code)
            if df_mf is not None and not df_mf.empty:
                recent_mf = df_mf.tail(5)
                market_context['net_lg_amount'] = float(recent_mf['net_lg_amount'].sum())
                market_context['net_mf_amount'] = float(recent_mf['net_mf_amount'].sum()) if 'net_mf_amount' in recent_mf.columns else 0
                market_context['buy_lg_amount'] = float(recent_mf['buy_lg_amount'].sum())
                market_context['sell_lg_amount'] = float(recent_mf['sell_lg_amount'].sum())
                market_context['net_elg_amount'] = float(recent_mf['net_elg_amount'].sum())
                market_context['net_sm_amount'] = float(recent_mf['net_sm_amount'].sum())
                da['moneyflow'] = True
                logger.debug(f"{ts_code} 已加载资金流向: 近5日大单净额={market_context.get('net_lg_amount')}")
        except Exception as e:
            logger.debug(f"{ts_code} 资金流向加载跳过: {e}")
            self.data_manager.request_data('full_moneyflow', ts_code)

        # 3) 大盘环境: 通过沪深300最近N日收益率判断
        try:
            idx_df = self.benchmark_service.get_index_daily(BenchmarkIndex.HS300)
            if idx_df is not None and not idx_df.empty:
                idx_close_series = idx_df['close'].astype(float)
                idx_5d_ret = (idx_close_series.iloc[-1] / idx_close_series.iloc[-5] - 1) if len(idx_close_series) >= 5 else 0
                idx_20d_ret = (idx_close_series.iloc[-1] / idx_close_series.iloc[-20] - 1) if len(idx_close_series) >= 20 else 0
                if idx_5d_ret > 0.03 or idx_20d_ret > 0.05:
                    market_context['index_condition'] = 'GOOD'
                elif idx_5d_ret < -0.03 or idx_20d_ret < -0.05:
                    market_context['index_condition'] = 'POOR'
                else:
                    market_context['index_condition'] = 'NEUTRAL'
                market_context['idx_5d_ret'] = round(float(idx_5d_ret * 100), 2)
                market_context['idx_20d_ret'] = round(float(idx_20d_ret * 100), 2)
                try:
                    if df is not None and not df.empty and len(df) >= 20:
                        stock_close = df['close'].astype(float)
                        stock_20d_ret = (stock_close.iloc[-1] / stock_close.iloc[-20] - 1) * 100
                        market_context['stock_vs_index_20d'] = round(float(stock_20d_ret - idx_20d_ret * 100), 2)
                except Exception:
                    pass
                da['index'] = True
                logger.debug(f"{ts_code} 大盘环境: {market_context.get('index_condition')}, "
                             f"5日={market_context.get('idx_5d_ret')}%, 20日={market_context.get('idx_20d_ret')}%")
        except Exception as e:
            logger.debug(f"{ts_code} 大盘环境加载跳过: {e}")

        # 4) 基础市场状态识别 [P1-#25]
        try:
            from app.engine.framework.volume_price_strategy import StageDetector
            sd = StageDetector()
            market_state = sd.recognize_market_condition(df)
            market_context['market_state'] = market_state.get('market_state', 'UNKNOWN')
            market_context['ma_trend'] = market_state.get('ma_trend', 'neutral')
            market_context['market_volatility'] = market_state.get('bb_width', 0)
            da['market_state'] = True
            logger.debug(f"{ts_code} 市场状态: {market_context.get('market_state')}")
        except Exception as e:
            logger.debug(f"{ts_code} 市场状态识别跳过: {e}")
            market_context['market_state'] = 'UNKNOWN'

        # [P2-#57] 状态依赖动态周期权重
        _state = market_context.get('market_state', 'UNKNOWN')
        if _state == 'TRENDING_BULL':
            cycle_weights = {'primary': 0.8, 'secondary': 0.2, 'execution': 0.0}
        elif _state == 'TRENDING_BEAR':
            cycle_weights = {'primary': 0.4, 'secondary': 0.6, 'execution': 0.0}
        elif _state == 'HIGH_VOL':
            cycle_weights = {'primary': 0.3, 'secondary': 0.3, 'execution': 0.4}
        elif _state == 'RANGING':
            cycle_weights = {'primary': 0.6, 'secondary': 0.4, 'execution': 0.0}
        else:
            cycle_weights = {'primary': 0.6, 'secondary': 0.3, 'execution': 0.1}
        market_context['cycle_weights'] = cycle_weights

        # 构建 market_env 字典（供量价/缠论策略使用）
        if market_context.get('index_condition'):
            market_context.setdefault('market_env', {})['condition'] = market_context['index_condition']
        if market_context.get('idx_5d_ret') is not None:
            market_context.setdefault('market_env', {})['index_return_5d'] = market_context['idx_5d_ret']

        # ── Phase 1: 新增市场上下文计算字段 ──
        # P1-4: 散户反向指标 — 大小单对比
        try:
            net_lg = market_context.get('net_lg_amount', 0) or 0
            net_sm = market_context.get('net_sm_amount', 0) or 0
            net_elg = market_context.get('net_elg_amount', 0) or 0
            main_net = net_lg + net_elg
            if da.get('moneyflow') and abs(main_net) > 0 and abs(net_sm) > 0:
                if net_sm < 0 and main_net > 0:
                    market_context['retail_vs_institutional'] = 'healthy'
                elif net_sm > 0 and main_net < 0:
                    market_context['retail_vs_institutional'] = 'danger'
                elif net_sm > 0 and main_net > 0:
                    market_context['retail_vs_institutional'] = 'overheat'
                else:
                    market_context['retail_vs_institutional'] = 'panic'
            else:
                market_context['retail_vs_institutional'] = None
        except Exception:
            market_context['retail_vs_institutional'] = None

        # P1-5: 情绪拥挤度因子 — 融资余额增长率 vs 股价涨幅
        try:
            from app.data import DataManager
            _dm = DataManager()
            margin_df = _dm.get_cached_margin(ts_code)
            if margin_df is not None and not margin_df.empty and len(margin_df) >= 5:
                recent_margin = margin_df.tail(5)
                if 'mrz' in recent_margin.columns:
                    margin_vals = recent_margin['mrz'].dropna().values
                    if len(margin_vals) >= 5:
                        margin_growth = (margin_vals[-1] / margin_vals[0] - 1) * 100
                    elif len(margin_vals) >= 2:
                        margin_growth = (margin_vals[-1] / margin_vals[0] - 1) * 100
                    else:
                        margin_growth = 0.0
                    if df is not None and not df.empty and len(df) >= 5:
                        stock_5d = (df['close'].iloc[-1] / df['close'].iloc[-5] - 1) * 100
                    else:
                        stock_5d = 0.0
                    crowding = round(float(margin_growth - stock_5d), 2)
                    market_context['sentiment_crowding'] = crowding
                    if crowding > 15:
                        market_context['sentiment_crowding_label'] = 'overheat'
                    elif crowding < -5:
                        market_context['sentiment_crowding_label'] = 'cooling'
                    else:
                        market_context['sentiment_crowding_label'] = 'normal'
        except Exception:
            self.data_manager.request_data('margin', ts_code)
            market_context['sentiment_crowding'] = None
            market_context['sentiment_crowding_label'] = None

        # P1-6: 乖离率 + 历史分位
        try:
            if df is not None and not df.empty:
                closes = df['close'].astype(float).values
                latest_close = closes[-1]
                if len(closes) >= 5:
                    market_context['bias_ma5'] = round(float((latest_close / np.mean(closes[-5:]) - 1) * 100), 2)
                if len(closes) >= 20:
                    market_context['bias_ma20'] = round(float((latest_close / np.mean(closes[-20:]) - 1) * 100), 2)
                if len(closes) >= 60:
                    market_context['bias_ma60'] = round(float((latest_close / np.mean(closes[-60:]) - 1) * 100), 2)
                lookback = min(len(closes), 250)
                if lookback >= 20:
                    low_250 = np.min(closes[-lookback:])
                    high_250 = np.max(closes[-lookback:])
                    if high_250 > low_250:
                        market_context['percentile_250d'] = round(float((latest_close - low_250) / (high_250 - low_250) * 100), 1)
        except Exception:
            pass

        # P1-7: BOLL带宽 + 均线粘合
        try:
            if df is not None and not df.empty and len(df) >= 26:
                closes = df['close'].astype(float).values
                ma_20 = np.mean(closes[-20:])
                std_20 = np.std(closes[-20:])
                upper = ma_20 + 2 * std_20
                lower = ma_20 - 2 * std_20
                bb_width = (upper - lower) / ma_20 if ma_20 > 0 else 0
                market_context['boll_bandwidth'] = 'contracted' if bb_width < 0.08 else ('expanding' if bb_width > 0.15 else 'normal')
                if len(closes) >= 60:
                    ma5 = np.mean(closes[-5:])
                    ma20 = np.mean(closes[-20:])
                    ma60 = np.mean(closes[-60:])
                    ma_spread = max(ma5, ma20, ma60) - min(ma5, ma20, ma60)
                    ma_avg = (ma5 + ma20 + ma60) / 3
                    if ma_avg > 0 and ma_spread / ma_avg < 0.03:
                        market_context['ma_convergence'] = True
                    else:
                        market_context['ma_convergence'] = False
        except Exception:
            pass

        return market_context, da

    def _apply_post_processing(self, signals: List[Dict], market_context: Dict,
                                 ts_code: str, df: pd.DataFrame, limit: int) -> List[Dict]:
        """信号后处理：新闻修正、VAP支撑阻力、中枢强度、持久化、数据可用性

        从 compute_for_stock 提取的后处理模块（P3重构）。
        包含策略信号计算完成后的所有修正、补充和持久化逻辑。
        """
        # ── 新闻情绪修正因子（C2） ──
        try:
            from app.data.news_provider import NewsProvider as NP
            np_provider = NP()
            news_items = np_provider.get_news(ts_code, days_back=3, max_count=5)
            if news_items:
                sentiments = [n.sentiment for n in news_items if n.sentiment is not None]
                if sentiments:
                    avg_sentiment = sum(sentiments) / len(sentiments)
                    clipped = max(-0.15, min(0.15, avg_sentiment))
                    modifier = 1.0 + (clipped * 0.33)
                    for sig in signals:
                        sig['confidence'] = min(1.0, sig.get('confidence', 0.5) * modifier)
                        label = '正面' if clipped > 0 else ('负面' if clipped < 0 else '中性')
                        sig['evidence'] = sig.get('evidence', []) + [
                            f"新闻情绪: {label} (修正{modifier:.2f}x, {len(sentiments)}条)"
                        ]
                    logger.debug(f"{ts_code} 新闻情绪修正: avg={avg_sentiment:.3f} -> modifier={modifier:.3f}")
        except Exception as e:
            logger.debug(f"{ts_code} 新闻情绪修正跳过: {e}")

        # ═══ Phase 2 P2-9: VAP 支撑/阻力 ═══
        try:
            if df is not None and not df.empty and len(df) >= 30:
                closes = df['close'].astype(float).values
                highs = df['high'].astype(float).values if 'high' in df.columns else closes
                lows = df['low'].astype(float).values if 'low' in df.columns else closes
                volumes = df['vol'].astype(float).values if 'vol' in df.columns else df['amount'].astype(float).values
                latest_close = float(closes[-1])
                vap = _calc_vap_support_resistance(closes, highs, lows, volumes, latest_close)
                market_context['vap_support'] = vap.get('vap_support')
                market_context['vap_resistance'] = vap.get('vap_resistance')
        except Exception:
            pass

        # ═══ Phase 2 P2-6: 中枢强度 — 注入 chanlun signal ═══
        try:
            chip_signal = next((s for s in signals if s.get('strategy_name', '').startswith('筹码')), None)
            chip_sr = chip_signal.get('status_recognition', {}) if chip_signal else None
            for sig in signals:
                if sig.get('strategy_name') == '缠论走势分析':
                    cl_sr = sig.get('status_recognition', {})
                    cl_detail = sig.get('chanlun_analysis_detail', {})
                    zs_list_raw = cl_detail.get('zhongshu_list', [])
                    if zs_list_raw:
                        ZS = type('ZS', (), {})
                        zhongshu_objs = []
                        for z in zs_list_raw:
                            obj = ZS()
                            obj.low = z.get('low', 0)
                            obj.high = z.get('high', 0)
                            obj.center = z.get('center', 0)
                            zhongshu_objs.append(obj)
                        strength = _calc_zhongshu_strength(df, zhongshu_objs, chip_sr)
                        if strength:
                            cl_sr['zhongshu_strength'] = strength
                    break
        except Exception:
            pass

        # 持久化到数据库
        try:
            self._persist_signals(ts_code, signals)
        except Exception as e:
            logger.debug(f"{ts_code}: 信号持久化到数据库跳过 (非关键): {e}")

        # 记录数据可用性
        da = next((s for s in signals if isinstance(s, dict) and s.get('data_availability')), None)
        kline_ok = df is not None and len(df) >= 60
        self.last_data_availability = {
            'ts_code': ts_code,
            'kline': kline_ok,
            'daily_basic': bool(market_context.get('turnover_rate')),
            'moneyflow': bool(market_context.get('net_lg_amount')),
            'index': bool(market_context.get('index_condition')),
            'market_state': bool(market_context.get('market_state')),
        }

        return signals[:limit]


    def _compute_chip_signal(self, ts_code: str, df: pd.DataFrame, market_context: Optional[Dict] = None) -> Optional[Dict]:
        """计算筹码主力分析信号 (L2) — 使用完整 ChipDistributionStrategy"""
        # 确保 K 线数据包含 ts_code
        if 'ts_code' not in df.columns:
            df = df.copy()
            df['ts_code'] = ts_code

        # 预检: 大盘指数数据不可用时 MarketEnvironmentFilter 会挂起，跳过完整分析
        idx_available = market_context and (
            market_context.get('idx_5d_ret') is not None or
            market_context.get('idx_20d_ret') is not None
        )
        if not idx_available:
            logger.debug(f"{ts_code} 大盘指数数据不可用，跳过筹码PreFilter，使用默认空信号")
            # 直接构建一个空信号(无筹码数据)，避免数据源挂起
            return self._build_default_chip_signal(ts_code, df, market_context)

        # 运行完整筹码分析（带超时保护）
        analysis = {}
        try:
            analysis = self.chip_strategy.analyze(df)
        except Exception as e:
            logger.debug(f"{ts_code} 筹码分析异常: {e}")
            return None
        
        # 检查 PreFilter 结果
        if not analysis.get('pre_filter_passed', True):
            logger.info(f"{ts_code} PreFilter未通过: {analysis.get('pre_filter_reason', '')}")
            return None
        
        recommendation = analysis.get('recommendation', {})
        phase_info = analysis.get('phase_info', {})
        signals = analysis.get('signals', {})
        market_env = analysis.get('market_environment', {})
        stock_filter = analysis.get('stock_filter', {})
        
        action = recommendation.get('action', 'HOLD')
        latest_close = float(df['close'].iloc[-1])
        latest_date = df.index[-1] if isinstance(df.index, pd.DatetimeIndex) else df.iloc[-1].get('trade_date', date.today())
        
        # 映射为统一信号格式
        if action == 'BUY':
            signal = StrategySignal.BULLISH.value
            signal_label = '买入'
        elif action == 'SELL':
            signal = StrategySignal.BEARISH.value
            signal_label = '卖出'
        else:
            signal = StrategySignal.NEUTRAL.value
            signal_label = '观望'
        
        # 从 recommendation 或信号细节中提取入场/止损/目标
        target_position = recommendation.get('target_position')
        if target_position is None:
            # 根据信号类型设置默认仓位
            if action == 'BUY':
                target_position = 0.5
            elif action == 'SELL':
                target_position = 0.0
            else:
                target_position = 0.1
        
        # 入场区间: 从信号细节获取或默认
        entry_low = round(latest_close * 0.97, 2)
        entry_high = round(latest_close * 1.02, 2)
        risk_line = round(latest_close * 0.92, 2)
        target_high = round(latest_close * 1.12, 2)
        
        # 构建分析证据
        evidence = []
        
        # 阶段信息
        phase = phase_info.get('phase_name', '未知')
        phase_confidence = phase_info.get('confidence', 0)
        evidence.append(f"阶段判定: {phase}({phase_confidence:.0%})")
        
        # 触发信号详情
        triggered_signals = []
        for sig_name in ['S_BUY', 'S_WASH_END', 'S_BOUNCE', 'S_SELL', 'S_WASH_STOP', 'S_DIVERG_SELL']:
            sig_detail = signals.get(sig_name, {})
            if sig_detail.get('triggered'):
                triggered_signals.append(sig_name)
        if triggered_signals:
            evidence.append(f"触发信号: {', '.join(triggered_signals)}")
        
        # K线形态
        patterns = signals.get('patterns', [])
        if patterns:
            evidence.append(f"K线形态: {', '.join(p.get('name', '') for p in patterns[:3])}")
        
        # 指标摘要
        indicators = analysis.get('indicators', {})
        if indicators:
            ind_parts = []
            if indicators.get('asr') is not None:
                ind_parts.append(f"ASR={indicators['asr']:.0%}")
            if indicators.get('profit_ratio') is not None:
                ind_parts.append(f"获利={indicators['profit_ratio']:.0%}")
            if indicators.get('vol_ratio') is not None:
                ind_parts.append(f"量比={indicators['vol_ratio']:.1f}")
            if ind_parts:
                evidence.append(f"指标: {' | '.join(ind_parts)}")
        
        # 大盘环境
        env = market_env.get('environment', {})
        if env.get('condition'):
            evidence.append(f"大盘: {env['condition']}({env.get('reason', '')[:30]})")

        # 市场扩展数据（换手率/资金流向）
        if market_context:
            tr = market_context.get('turnover_rate')
            if tr is not None:
                evidence.append(f"换手率: {tr:.2f}%")
            net_lg = market_context.get('net_lg_amount')
            if net_lg is not None and abs(net_lg) > 0:
                evidence.append(f"近5日大单净额: {net_lg:+.0f}")
            idx_cond = market_context.get('index_condition')
            if idx_cond:
                evidence.append(f"大盘环境: {idx_cond}")
            mv = market_context.get('circ_mv')
            if mv is not None:
                evidence.append(f"流通市值: {mv/1e8:.1f}亿")
        
        # 市值适配
        cap = stock_filter.get('cap_level', '')
        if cap:
            evidence.append(f"市值适配: {cap}")
        
        # 构建风险提示
        risk_notes = ['大盘系统性风险']
        if stock_filter.get('turnover_rate', 0) > 10:
            risk_notes.append('换手率极高，注意出货风险')
        if cap == 'MEGA':
            risk_notes.append('超大盘股流动性有限')
        
        # 信号置信度
        confidence = recommendation.get('confidence', 0.5)
        if confidence is None:
            confidence = 0.5

        # 筹码策略现状识别
        indicators = analysis.get('indicators', {})
        chip_dist = analysis.get('chip_distribution', {})
        chip_bins = chip_dist.get('chip_bins', [])
        asr_val = indicators.get('asr', indicators.get('ASR'))
        chip_peak = 0.0
        concentration = 0.0
        if chip_bins and len(chip_bins) > 0:
            ratios = [b.get('chip_ratio', 0) for b in chip_bins]
            peak_idx = int(np.argmax(ratios)) if ratios else 0
            chip_peak = round(float(chip_bins[peak_idx].get('price', 0)), 2) if peak_idx < len(chip_bins) else 0.0
            concentration = round(float(max(ratios)), 4) if ratios else 0.0

        # 主力集中价
        main_force_cost = {"cost_price": 0, "distance_pct": 0, "near_cost": False}
        scorer = None
        try:
            from app.engine.framework.chip_strategy import MainForceScorer
            scorer = MainForceScorer()
            mf_result = scorer._calc_main_force_cost(ts_code, latest_close)
            if mf_result and mf_result.get('cost_price', 0) > 0:
                main_force_cost = mf_result
        except Exception:
            self.data_manager.request_data('top10_holders', ts_code)
            pass

        # Phase 1 P1-3: 融资成本价估算 + 夹层区间（C1）
        margin_cost_price = None
        sandwich_zone = None
        if scorer:
            try:
                margin_result = scorer._calc_margin_cost_price(ts_code, latest_close)
                if margin_result.get('cost_price'):
                    margin_cost_price = margin_result['cost_price']
                # 夹层区间判断
                mc = main_force_cost.get('cost_price', 0)
                if mc > 0 and margin_cost_price and latest_close > 0:
                    if latest_close < min(mc, margin_cost_price):
                        sandwich_zone = 'both_loss'
                    elif mc < latest_close < margin_cost_price:
                        sandwich_zone = 'main_force_profitable'
                    elif latest_close > max(mc, margin_cost_price):
                        sandwich_zone = 'both_profitable'
                    else:
                        sandwich_zone = 'transition'
            except Exception:
                pass

        # Phase 1 P1-4/P1-8: 暴露资金博弈字段
        net_elg = market_context.get('net_elg_amount', 0) or 0
        net_sm = market_context.get('net_sm_amount', 0) or 0
        net_lg = market_context.get('net_lg_amount', 0) or 0
        retail_vs_inst = market_context.get('retail_vs_institutional')
        sentiment_crowding = market_context.get('sentiment_crowding')
        sentiment_crowding_label = market_context.get('sentiment_crowding_label')

        # P2-2: 交叉比对比法
        price_position = None
        try:
            closes_arr = df['close'].values
            if len(closes_arr) >= 60:
                p_high = np.max(closes_arr[-120:])
                p_low = np.min(closes_arr[-120:])
                p_range = p_high - p_low if p_high > p_low else 1.0
                price_position = (closes_arr[-1] - p_low) / p_range
        except Exception:
            pass
        cross_compare = _calc_cross_compare(
            net_lg_amount_5d=net_lg,
            main_force_cost_price=main_force_cost.get('cost_price', 0),
            margin_cost_price=margin_cost_price,
            latest_close=latest_close,
            sentiment_crowding_label=sentiment_crowding_label,
            price_position=price_position,
        )

        # P2-1: 筹码集中度因子
        concentration_factor = _calc_chip_concentration_factor(ts_code, self.data_manager)

        # P3-1: 查询股票行业用于板块效应判断
        concept_name = None
        try:
            con_df = self.data_manager.get_cached_concept(ts_code=ts_code)
            if con_df is not None and not con_df.empty:
                concept_name = str(con_df.iloc[0]['concept_name'])
        except Exception:
            self.data_manager.request_data('concept', ts_code)

        chip_status = {
            'state': 'ACCUMULATING' if action == 'BUY' else ('DISTRIBUTING' if action == 'SELL' else 'RANGING'),
            'state_label': signal_label,
            'trend': {'direction': '', 'strength': '', 'stage': phase},
            'momentum': {'level': action, 'score': round(float(confidence), 2)},
            'volume': {'state': '', 'structure': ''},
            'support_resistance': {
                'support': round(float(chip_peak), 2) if chip_peak > 0 else 0.0,
                'resistance': round(float(chip_peak), 2) if chip_peak > 0 else 0.0,
            },
            'risk_level': 'HIGH' if cap else 'MEDIUM',
            'chip_peak': chip_peak,
            'concentration': concentration,
            'asr': asr_val,
            # P1-4: CYQKL（筹码盈亏比例）
            'cyqkl': round((latest_close - chip_peak) / chip_peak, 4) if chip_peak > 0 else None,
            'main_force_cost': main_force_cost,
            # Phase 1 P1-3: 融资成本价 + 夹层区间（C1）
            'margin_cost_price': margin_cost_price,
            'sandwich_zone': sandwich_zone,
            # Phase 1 P1-4/P1-8: 资金博弈字段（C2）
            'retail_vs_institutional': retail_vs_inst,
            'net_lg_amount_5d': net_lg,
            'net_elg_amount_5d': net_elg,
            'net_sm_amount_5d': net_sm,
            'sentiment_crowding': sentiment_crowding,
            'sentiment_crowding_label': sentiment_crowding_label,
            # P1-3: 假机构识别
            'fake_institution': scorer._detect_fake_institution(ts_code, df) if (scorer and idx_available)
                                else {"suspected": False, "reason": "大盘数据不可用" if not idx_available else "scorer初始化失败", "confidence": 0.0},
            # P2-2: 交叉比对比法结论
            'cross_compare': cross_compare,
            # P2-1: 筹码集中度因子
            'concentration_factor': concentration_factor,
            # P3-1: 龙虎榜高成功率战法
            'lhb_high_success': _calc_lhb_high_success_strategy(
                ts_code,
                self.data_manager.get_lhb_detail(ts_code=ts_code),
                df,
                concept_name=concept_name,
                idx_5d_ret=market_context.get('idx_5d_ret') if market_context else None,
                idx_20d_ret=market_context.get('idx_20d_ret') if market_context else None,
            ),
        }

        return {
            'strategy_name': '筹码主力分析',
            'status_recognition': chip_status,
            'signal': signal,
            'signal_label': signal_label,
            'confidence': round(float(confidence), 2),
            'entry_zone': [entry_low, entry_high],
            'risk_line': risk_line,
            'target_zone': [entry_high, target_high],
            'position_suggestion': f'{int(target_position * 100)}%',
            'holding_period': '1-3个月',
            'evidence': evidence,
            'risk_notes': risk_notes,
            'signal_date': latest_date if isinstance(latest_date, str) else latest_date.strftime('%Y-%m-%d'),
            'backtest_win_rates': self._get_signal_win_rates(signal),

            'signal_source_detail': {
                'phase': phase,
                'triggered_signals': triggered_signals,
                'patterns': [p.get('name', '') for p in patterns],
                'market_condition': env.get('condition', ''),
                'cap_level': cap,
                'pre_filter_pass': True,
            },
        }

    def _compute_chanlun_signal(self, ts_code: str, df: pd.DataFrame, 
                                market_context: Optional[Dict] = None,
                                period: str = 'long') -> Optional[Dict]:
        """计算缠论策略建议 — 基于缠论决策树的全中文分析报告
        
        Args:
            period: 'long'(周线/日线/60min) / 'medium'(日线/30min/5min) / 'short'(30min/5min/1min)
        """
        from app.engine.framework.chanlun_strategy import ChanlunScorer, BuySellPoint
        from app.engine.framework.chanlun_multi_level import MultiLevelChanlunAnalyzer

        if df.empty or len(df) < 60:
            return None

        latest_close = float(df['close'].iloc[-1])
        latest_date = df.index[-1] if isinstance(df.index, pd.DatetimeIndex) else df.iloc[-1].get('trade_date', date.today())
        if not isinstance(latest_date, str):
            latest_date = str(latest_date)[:10]

        # 根据分析周期确定级别组合
        # 映射到 MultiLevelChanlunAnalyzer 期望的级别名称
        period_levels = {
            'long':  {'names': ('weekly', 'daily', 'hourly'),       'periods': ('W', 'D', '60m')},
            'medium':{'names': ('daily', '30min', '5min'),           'periods': ('D', '30m', '5m')},
            'short': {'names': ('30min', '5min', '1min'),           'periods': ('30m', '5m', '1m')},
        }
        pl = period_levels.get(period, period_levels['long'])
        
        # 获取多级别K线数据
        df_dict = {}
        for level_name, period_name in zip(pl['names'], pl['periods']):
            try:
                if period_name == 'D':
                    src_df = df if period != 'short' else self.data_manager.get_kline_data(ts_code, period='30m')
                else:
                    src_df = self.data_manager.get_kline_data(ts_code, period=period_name)
                if src_df is not None and not src_df.empty:
                    df_proc = src_df.copy()
                    if 'vol' in df_proc.columns and 'volume' not in df_proc.columns:
                        df_proc['volume'] = df_proc['vol']
                    if 'trade_date' not in df_proc.columns:
                        if isinstance(df_proc.index, pd.DatetimeIndex):
                            df_proc['trade_date'] = df_proc.index.strftime('%Y-%m-%d')
                        else:
                            df_proc['trade_date'] = ''
                    df_dict[level_name] = df_proc
            except Exception:
                self.data_manager.request_data('per_stock', ts_code)
                continue
        
        # 动态配置 MultiLevelChanlunAnalyzer 的级别列表
        from app.engine.framework.chanlun_config import ChanlunConfig
        chanlun_cfg = ChanlunConfig.default()
        chanlun_cfg.multi_level.levels = pl['names']
        # S2: 按周期配置笔参数——短线用宽笔(3K线)，长线用严格笔(5K线)
        bi_min_klines = 5 if period == 'long' else 3
        chanlun_cfg.bi.min_klines = bi_min_klines

        try:
            analyzer = MultiLevelChanlunAnalyzer(config=chanlun_cfg)
            multi_result = analyzer.analyze(df_dict)
            # 根据period选择主分析级别：long→daily, medium→daily(背景), short→5min(决策)
            primary_level = 'daily'
            if period == 'short':
                primary_level = '5min'  # short的决策级别是5分钟
            elif period == 'medium':
                primary_level = 'daily'  # medium的背景级别是日线
            daily_result = multi_result.get('levels', {}).get(primary_level, {})
            result = analyzer.results.get(primary_level, {}) if hasattr(analyzer, 'results') else {}
        except Exception as e:
            logger.warning(f"{ts_code} 多级别缠论分析异常，降级到单级别: {e}")
            try:
                from app.engine.framework.chanlun_strategy import ChanlunAnalyzer
                daily_df_proc = df_dict.get('daily', df)
                if isinstance(daily_df_proc, pd.DataFrame) and not daily_df_proc.empty:
                    single = ChanlunAnalyzer()
                    result = single.analyze(daily_df_proc)
                    multi_result = {}
                else:
                    return None
            except Exception as e2:
                logger.warning(f"{ts_code} 单级别降级也失败: {e2}")
                return None
        except Exception as e:
            logger.warning(f"{ts_code} ChanlunAnalyzer 异常: {e}")
            return None


        # L3 评分：缠论评分系统量化置信度
        try:
            score_result = ChanlunScorer.score(result, latest_close=latest_close, market_context=market_context)
            chanlun_score = score_result.get("score", 50)
            score_details = score_result.get("details", [])
            score_recommendation = score_result.get("recommendation", "HOLD")
        except Exception as e:
            logger.warning(f"{ts_code} ChanlunScorer 异常: {e}")
            chanlun_score = 50
            score_details = []
            score_recommendation = "HOLD"

        if not result.get('success') or 'error' in result:
            return None

        summary = result.get('summary', {})
        strokes = result.get('strokes', [])
        segments = result.get('segments', [])
        zhongshu_list = result.get('zhongshu', [])
        divergence = result.get('divergence')
        buy_points: List[BuySellPoint] = result.get('buy_points', [])
        sell_points: List[BuySellPoint] = result.get('sell_points', [])
        trend = result.get('trend', 'unknown')

        if not strokes:
            return None

        # ─── 1. 走势结构 ───
        last_stroke = strokes[-1]
        prev_stroke = strokes[-2] if len(strokes) >= 2 else None

        ls_end_price = float(last_stroke.end_price)
        price_offset = (latest_close / ls_end_price - 1) * 100

        seg_count = summary.get('total_segments', 0)
        zs_count = summary.get('total_zhongshu', 0)

        if last_stroke.direction == 'up':
            if price_offset >= -2:
                phase_detail = f"最后一笔为上升笔(至{last_stroke.end_date}@{ls_end_price:.2f}), 当前{price_offset:+.2f}%, 仍在笔终点附近"
                last_bi_status = 'up_延续'
            else:
                phase_detail = f"最后一笔为上升笔(至{last_stroke.end_date}@{ls_end_price:.2f}), 当前回落{abs(price_offset):.1f}%, 新下跌笔未确认"
                last_bi_status = 'up_结束_回调'
                if prev_stroke and prev_stroke.direction == 'down':
                    phase_detail += f"，前序下跌笔低点@{prev_stroke.end_price:.2f}"
        else:
            if price_offset <= 2:
                phase_detail = f"最后一笔为下降笔(至{last_stroke.end_date}@{ls_end_price:.2f}), 当前{price_offset:+.2f}%, 仍在笔终点附近"
                last_bi_status = 'down_延续'
            else:
                phase_detail = f"最后一笔为下降笔(至{last_stroke.end_date}@{ls_end_price:.2f}), 当前反弹{price_offset:.1f}%, 新上涨笔未确认"
                last_bi_status = 'down_结束_反弹'
                if prev_stroke and prev_stroke.direction == 'up':
                    phase_detail += f"，前序上涨笔高点@{prev_stroke.end_price:.2f}"

        # ─── 2. 中枢分析 ───
        latest_zhongshu = zhongshu_list[-1] if zhongshu_list else None
        # 批次2b: 查找最适合作为位置基准的中枢
        # 优先级: normal(标准) > expanded(扩张→子中枢中找normal) > newborn(新生→列表中找上一个normal)
        if latest_zhongshu:
            if latest_zhongshu.type == 'expanded' and latest_zhongshu.sub_zhongshu_list:
                sub_list = latest_zhongshu.sub_zhongshu_list
                normal_zs = [zs for zs in sub_list if zs.type == 'normal']
                if normal_zs:
                    latest_zhongshu = normal_zs[-1]
            elif latest_zhongshu.type == 'newborn':
                # newborn中枢是脱离后形成的次级结构，回溯到上一个normal中枢做位置基准
                # 这样position_detail能反映价格相对于主中枢的位置，而非仅对新生中枢
                for zs in reversed(zhongshu_list):
                    if zs.type == 'normal':
                        latest_zhongshu = zs
                        break
        zs_high = float(latest_zhongshu.high) if latest_zhongshu else None
        zs_low = float(latest_zhongshu.low) if latest_zhongshu else None
        zs_center = float(latest_zhongshu.center) if latest_zhongshu else None

        if latest_zhongshu and latest_close > zs_high:
            position_vs_zs = '上方'
            pct_from_zs = (latest_close / zs_high - 1) * 100
            position_detail = f"价格{latest_close:.2f}高于中枢上沿{zs_high:.2f}(+{pct_from_zs:.1f}%)"
        elif latest_zhongshu and latest_close < zs_low:
            position_vs_zs = '下方'
            pct_from_zs = (zs_low / latest_close - 1) * 100
            position_detail = f"价格{latest_close:.2f}低于中枢下沿{zs_low:.2f}(-{pct_from_zs:.1f}%)"
        elif latest_zhongshu:
            position_vs_zs = '内部'
            pct_from_zs = 0
            position_detail = f"价格{latest_close:.2f}在中枢区间[{zs_low:.2f}, {zs_high:.2f}]内"
        else:
            position_vs_zs = '无中枢'
            pct_from_zs = 0
            position_detail = '尚未形成中枢结构'

        # ─── 3. 买卖点过滤（当前中枢之后） ───
        recent_buy = []
        recent_sell = []

        # 级别间背驰对比验证
        level_cross_info = ""
        level_cross_score = 0.0
        level_details = {}
        try:
            from app.engine.framework.chanlun_level_validator import ChanlunLevelValidator
            validator = ChanlunLevelValidator()
            lv_result = validator.validate(df)
            # 始终提取各级别基础数据
            cross_score = lv_result.get('cross_score', 0.5)
            level_cross_score = cross_score
            details = lv_result.get('details', [])
            level_cross_info = "；".join(details[:3]) if details else ""
            # 仅在 cross_score ≠ 0.5 时追加验证结论
            if cross_score != 0.5:
                validation = lv_result.get('validation', {})
                reasons = validation.get('reasons', [])
                if reasons:
                    level_cross_info = level_cross_info + " | " + "；".join(reasons[:2]) if level_cross_info else "；".join(reasons[:2])
            # 提取各级别信号详情（评分/趋势/买卖点数）
            for level_name in ('monthly', 'weekly', 'daily'):
                sig_data = lv_result.get('signals', {}).get(level_name, {})
                if sig_data:
                    level_details[level_name] = {
                        'score': sig_data.get('score', 50),
                        'trend': sig_data.get('trend', 'unknown'),
                        'signal': sig_data.get('signal', 'HOLD'),
                        'buy_count': len(sig_data.get('buy_points', [])),
                        'sell_count': len(sig_data.get('sell_points', [])),
                        'zhongshu_count': sig_data.get('zhongshu_count', 0),
                    }
        except Exception:
            pass
        zs_formed_date = str(latest_zhongshu.start_date)[:10] if latest_zhongshu and hasattr(latest_zhongshu, 'start_date') else None

        for p in buy_points:
            p_date = str(p.position.get('date', ''))[:10] if p.position else ''
            if zs_formed_date and p_date >= zs_formed_date:
                recent_buy.append(p)
            elif not zs_formed_date:
                recent_buy.append(p)

        for p in sell_points:
            p_date = str(p.position.get('date', ''))[:10] if p.position else ''
            if zs_formed_date and p_date >= zs_formed_date:
                recent_sell.append(p)
            elif not zs_formed_date:
                recent_sell.append(p)

        # 买卖点类型映射（已提升为模块级常量 BP_TYPE_CN）
        BP_ORDER = {'first_buy': 1, 'second_buy': 2, 'third_buy': 3,
                    'first_sell': 1, 'second_sell': 2, 'third_sell': 3}

        # ─── 4. 缠论决策树 ───
        trend_cn = {'up': '上升', 'down': '下降', 'unknown': '待定'}
        trend_str = trend_cn.get(trend, '待定')
        
        # 初始化决策变量
        action = '静待观察'
        action_reason_parts = []
        confidence = 0.5
        
        # 建仓策略
        position_plan = []  # 分档建仓描述列表
        stop_loss_settings = []  # 止损设置
        target_reference = []  # 止盈参考
        
        # 等待信号
        watch_signals = []
        
        # 统计买卖点类型
        buy_types = set(p.type for p in recent_buy)
        sell_types = set(p.type for p in recent_sell)
        has_first_buy = 'first_buy' in buy_types
        has_second_buy = 'second_buy' in buy_types
        has_third_buy = 'third_buy' in buy_types
        has_first_sell = 'first_sell' in sell_types
        has_second_sell = 'second_sell' in sell_types
        has_third_sell = 'third_sell' in sell_types
        
        # 最近买点和卖点
        best_buy = max(recent_buy, key=lambda p: BP_ORDER.get(p.type, 0)) if recent_buy else None
        best_sell = max(recent_sell, key=lambda p: BP_ORDER.get(p.type, 0)) if recent_sell else None
        
        # 最近买点距当前价的涨幅
        buy_price_pct = None
        if best_buy:
            bp = best_buy.position.get('price', latest_close)
            buy_price_pct = (latest_close / bp - 1) * 100
        
        # 最近卖点距当前价的跌幅
        sell_price_pct = None
        if best_sell:
            sp = best_sell.position.get('price', latest_close)
            sell_price_pct = (sp / latest_close - 1) * 100

        # ========== 决策树 ==========
        if trend == 'up':
            # 趋势向上
            if position_vs_zs == '上方':
                if has_first_buy:
                    action = '买入建仓'
                    confidence = 0.75
                    action_reason_parts.append(f"上升趋势中出现第一类买点(背驰点)，趋势转折早期信号")
                    position_plan = [
                        "第一档(试探): 当前价附近建仓 5%，确认背驰有效",
                        "第二档(确认): 回调不破买点价时加仓至 10%",
                        "第三档(加仓): 突破前高且5日线上穿10日线时加仓至 15%",
                    ]
                    stop_loss_settings = [
                        f"硬止损: 跌破买点价下方 5%",
                        "移动止损: 第二类买点确认后，止损上移至二买价下方",
                        "缠论结构止损: 若出现第三类卖点则清仓",
                    ]
                    target_reference = [
                        f"第一目标: 前笔终点 {last_stroke.end_price:.2f}",
                        "第二目标: 突破前高后看线段延伸",
                    ]
                elif has_third_buy and buy_price_pct is not None and 0 <= buy_price_pct < 20:
                    action = '买入建仓'
                    confidence = 0.70
                    action_reason_parts.append(f"上升趋势+三类买点@最近买点价, 当前涨幅{buy_price_pct:.0f}%仍具性价比")
                    position_plan = [
                        f"第一档(追击): 当前价 {latest_close:.2f} 建仓 10%",
                        f"第二档(确认): 若回调不进入中枢(>={zs_high:.2f})则加仓至 15%",
                        "第三档(加仓): 等待新一笔上涨确认后再评估",
                    ]
                    stop_loss_settings = [
                        f"硬止损: 跌破中枢上沿 {zs_high:.2f} (-{(1 - zs_high/latest_close)*100:.0f}%)",
                        "移动止损: 沿5日线持有，拐头向下减半仓",
                        "缠论结构止损: 本级别出现第二类卖点",
                    ]
                    target_reference = [
                        f"第一目标: 前笔终点 {last_stroke.end_price:.2f}",
                        "第二目标: 突破前高后看线段延伸情况",
                    ]
                elif buy_price_pct is not None and buy_price_pct >= 30:
                    action = '静待观察'
                    confidence = 0.65
                    action_reason_parts.append(f"最近买点已上涨 {buy_price_pct:.0f}%，已远离买点区域，当前性价比较低")
                    watch_signals = [
                        "信号A: 若回调出现盘整背驰 → 可考虑第一类买点试探建仓",
                        f"信号B: 若回调至中枢上沿 {zs_high:.2f} 附近企稳 → 可考虑中枢内操作",
                        "信号C: 若直接跌破中枢 → 趋势转弱，继续等待",
                    ]
                elif buy_price_pct is not None and buy_price_pct < 0:
                    action = '静待观察'
                    confidence = 0.55
                    action_reason_parts.append(f"最近买点价 {best_buy.position.get('price',0):.2f}，当前价 {latest_close:.2f} 已跌破买点价 {abs(buy_price_pct):.1f}%，回调深度超预期，等待企稳")
                    watch_signals = [
                        f"信号A: 回调在中枢上沿 {zs_high:.2f} 上方企稳 → 可等待第二类买点",
                        f"信号B: 若继续跌破中枢上沿 {zs_high:.2f} → 观察中枢内部是否盘整背驰",
                        "信号C: 出现新低后观察下跌背驰 → 第一类买点试探建仓",
                    ]
                elif last_bi_status == 'up_延续':
                    action = '持仓观察'
                    confidence = 0.55
                    action_reason_parts.append("上升趋势中，最后一笔向上延续，持仓等待卖点信号")
                    watch_signals = [
                        "注意: 关注是否出现背驰信号，一旦出现第一类卖点考虑减仓",
                        "若持续上涨无背驰，可继续持有",
                    ]
                elif last_bi_status == 'up_结束_回调':
                    action = '静待观察'
                    confidence = 0.55
                    action_reason_parts.append(f"上升趋势中，上涨笔结束, 回调{abs(price_offset):.1f}%，等待企稳信号")
                    watch_signals = [
                        f"信号A: 回调在中枢上沿 {zs_high:.2f} 上方企稳 → 可关注第二类买点",
                        f"信号B: 回调进入中枢内部 → 需观察中枢下沿 {zs_low:.2f} 支撑",
                        "信号C: 出现下跌背驰 → 第一类买点试探建仓",
                    ]
                else:
                    action = '静待观察'
                    confidence = 0.50
                    action_reason_parts.append(f"上升趋势中, 当前状态待确认 ({last_bi_status})")
                    watch_signals = ["等待新一笔方向确认后再评估"]
            
            elif position_vs_zs == '内部':
                if has_first_buy:
                    action = '买入建仓'
                    confidence = 0.65
                    action_reason_parts.append("中枢内出现第一类买点(背驰)，可试探建仓")
                    position_plan = [
                        f"第一档(试探): 当前价 {latest_close:.2f} 建仓 5%",
                        "第二档(确认): 突破中枢上沿后加仓至 10%",
                    ]
                    stop_loss_settings = [
                        f"硬止损: 跌破中枢下沿 {zs_low:.2f}",
                        "缠论结构止损: 若出现第三类卖点则清仓",
                    ]
                    target_reference = [
                        f"第一目标: 中枢上沿 {zs_high:.2f}",
                        "第二目标: 突破中枢后看上沿上方",
                    ]
                elif has_third_buy:
                    action = '买入建仓'
                    confidence = 0.70
                    action_reason_parts.append("中枢内出现第三类买点，趋势即将突破")
                    position_plan = [
                        f"第一档(追击): 当前价 {latest_close:.2f} 建仓 10%",
                        "第二档(确认): 确认突破中枢后加仓至 15%",
                    ]
                    stop_loss_settings = [
                        f"硬止损: 重回中枢内部(跌破 {zs_high:.2f})",
                        "缠论结构止损: 本级别出现第二类卖点",
                    ]
                    target_reference = [
                        f"第一目标: 突破中枢上沿 {zs_high:.2f}",
                    ]
                else:
                    action = '静待观察'
                    confidence = 0.45
                    action_reason_parts.append("中枢内震荡，等待方向突破")
                    watch_signals = [
                        f"信号A: 向上突破中枢上沿 {zs_high:.2f} → 第三类买点追击",
                        f"信号B: 向下突破中枢下沿 {zs_low:.2f} → 防第三类卖点",
                    ]
            else:
                action = '静待观察'
                confidence = 0.50
                action_reason_parts.append("上升趋势但价格低于中枢，走势结构有矛盾，需等待确认")
                watch_signals = ["等待价格回到中枢内再评估"]

        elif trend == 'down':
            if has_third_sell:
                action = '清仓'
                confidence = 0.75
                action_reason_parts.append("下降趋势+第三类卖点，趋势确认向下，建议清仓规避")
                stop_loss_settings = ["已持仓: 立即止损清仓", "未持仓: 不参与下降趋势"]
                watch_signals = [
                    "等待信号: 出现下跌背驰+第一类买点后才考虑介入",
                ]
            elif has_first_buy:
                action = '买入建仓'
                confidence = 0.60
                action_reason_parts.append("下降趋势中出现第一类买点(背驰)，可试探建仓，严格止损")
                position_plan = [
                    f"第一档(试探): 当前价 {latest_close:.2f} 轻仓 5%",
                    "第二档(确认): 回调不创新低(第二类买点)时加仓至 10%",
                ]
                stop_loss_settings = [
                    f"硬止损: 跌破第一类买点价下方 5%",
                    f"止损参考: 买点价格 (可参考最近买点)",
                    "缠论结构止损: 若继续下跌出现第三类卖点则清仓",
                ]
                target_reference = [
                    f"第一目标: 中枢下沿 {zs_low:.2f}",
                    "第二目标: 中枢中心区域",
                ]
            elif has_second_buy:
                action = '买入建仓'
                confidence = 0.65
                action_reason_parts.append("下降趋势中出现第二类买点(回调确认)，底部区域")
                position_plan = [
                    f"第一档(试探): 当前价 {latest_close:.2f} 建仓 5%",
                    "第二档(确认): 确认反弹后加仓至 10%",
                ]
                stop_loss_settings = [
                    f"硬止损: 跌破最近低点",
                    "缠论结构止损: 若出现第三类卖点则清仓",
                ]
                target_reference = [
                    f"第一目标: 中枢下沿 {zs_low:.2f}",
                ]
            elif last_bi_status in ('down_延续',):
                action = '静待观察'
                confidence = 0.55
                action_reason_parts.append("下降趋势中，下跌笔延续，等待底部确认")
                watch_signals = [
                    "信号A: 出现下跌背驰+第一类买点 → 可试探建仓",
                    "信号B: 在下方形成新的中枢后再评估",
                ]
            else:
                action = '静待观察'
                confidence = 0.50
                action_reason_parts.append("下降趋势中，等待趋势转折信号")
                watch_signals = [
                    "信号A: 出现下跌背驰 → 第一类买点可试探",
                    f"信号B: 回到中枢内部 → 需重新评估",
                ]
        else:
            action = '静待观察'
            confidence = 0.35
            action_reason_parts.append("趋势不明朗，无可靠信号，建议观望")
            watch_signals = [
                "等待至少形成新的线段后判断方向",
            ]

        # ─── 5. 构建英文兼容字段（供系统消费） ───
        signal_map = {
            '买入建仓': StrategySignal.BULLISH.value,
            '持仓观察': StrategySignal.WATCH.value,
            '静待观察': StrategySignal.WATCH.value,
            '清仓': StrategySignal.BEARISH.value,
        }
        signal_label_map = {
            '买入建仓': '买入',
            '持仓观察': '观望',
            '静待观察': '观望',
            '清仓': '卖出',
        }
        internal_signal = signal_map.get(action, StrategySignal.NEUTRAL.value)
        internal_label = signal_label_map.get(action, '中性')

        entry_low = round(latest_close * 0.97, 2)
        entry_high = round(latest_close * 1.03, 2)
        risk_line = round(latest_close * 0.92, 2)
        target_val = round(latest_close * 1.12, 2)

        # 构建证据列表（英文兼容）
        evidence_list = []
        evidence_list.append(f"当前趋势: {trend_str} ({seg_count}段, {zs_count}中枢)")
        evidence_list.append(f"当前笔阶段: {phase_detail}")
        evidence_list.append(f"价格位置: {position_detail}")
        if latest_zhongshu:
            evidence_list.append(f"中枢区间: [{zs_low:.2f}, {zs_high:.2f}] 中心={zs_center:.2f}")
        if recent_buy:
            bt = [BP_TYPE_CN.get(p.type, p.type) for p in recent_buy]
            evidence_list.append(f"中枢形成后买点: {len(recent_buy)}个 ({', '.join(sorted(set(bt)))})")
        if recent_sell:
            st = [BP_TYPE_CN.get(p.type, p.type) for p in recent_sell]
            evidence_list.append(f"中枢形成后卖点: {len(recent_sell)}个 ({', '.join(sorted(set(st)))})")
        if divergence:
            div_dir = {'up': '上涨', 'down': '下跌'}.get(divergence.direction, '')
            div_type_map = {'trend': '趋势', 'consolidation': '盘整', 'zhongshu': '中枢破坏'}
            div_type = div_type_map.get(divergence.type, divergence.type)
            evidence_list.append(f"背驰: {div_dir}{div_type}背驰 (置信度={divergence.confidence:.2f})")
        evidence_list.append(f"分析建议: {action}")

        risk_notes = ['缠论信号具有滞后性']
        if buy_price_pct is not None and buy_price_pct > 20:
            risk_notes.append(f"最近买点已上涨 {buy_price_pct:.0f}%，追高风险较大")
        if pct_from_zs and abs(pct_from_zs) > 40:
            risk_notes.append(f"价格距中枢较远({abs(pct_from_zs):.0f}%)，回归中枢的可能性存在")
        if trend == 'unknown':
            risk_notes.append('趋势不明朗，建议控制仓位')

        # ─── 6. 构建全中文分析报告 ───
        report_lines = []
        report_lines.append(f"{ts_code} — {latest_date} 缠论分析报告")
        report_lines.append("")
        report_lines.append("【走势结构】")
        report_lines.append(f"  趋势方向：{trend_str}（{seg_count}段, {zs_count}中枢）")
        report_lines.append(f"  当前笔阶段：{phase_detail}")
        report_lines.append("")
        report_lines.append("【中枢分析】")
        if latest_zhongshu:
            report_lines.append(f"  最新中枢区间：[{zs_low:.2f}, {zs_high:.2f}]，中心 {zs_center:.2f}")
            report_lines.append(f"  价格相对中枢：{position_vs_zs}（{position_detail}）")
        else:
            report_lines.append("  尚未形成中枢结构")
        report_lines.append("")
        report_lines.append("【买卖点信号】")
        if recent_buy or recent_sell:
            if recent_buy:
                for p in recent_buy:
                    p_price = p.position.get('price', 0)
                    p_date = str(p.position.get('date', ''))[:10]
                    p_type_cn = BP_TYPE_CN.get(p.type, p.type)
                    p_pct = (latest_close / p_price - 1) * 100 if p_price else 0
                    report_lines.append(f"  买入: {p_type_cn} @{p_price:.2f} ({p_date}), 距当前+{p_pct:.0f}%")
            if recent_sell:
                for p in recent_sell:
                    p_price = p.position.get('price', 0)
                    p_date = str(p.position.get('date', ''))[:10]
                    p_type_cn = BP_TYPE_CN.get(p.type, p.type)
                    p_pct = (p_price / latest_close - 1) * 100 if p_price else 0
                    report_lines.append(f"  卖出: {p_type_cn} @{p_price:.2f} ({p_date}), 距当前-{p_pct:.0f}%")
            report_lines.append("")
        else:
            report_lines.append("  中枢形成后无买卖点信号")
            report_lines.append("")
        if divergence:
            div_dir = {'up': '上涨', 'down': '下跌'}.get(divergence.direction, '')
            div_type_map = {'trend': '趋势', 'consolidation': '盘整', 'zhongshu': '中枢破坏'}
            div_type = div_type_map.get(divergence.type, divergence.type)
            report_lines.append(f"  背驰: {div_dir}{div_type}背驰 (置信度={divergence.confidence:.2f})")
            report_lines.append("")
        
        report_lines.append("【操作建议】")
        report_lines.append(f"建议动作：{action}")
        report_lines.append(f"建议置信度：{confidence:.0%}")
        report_lines.append("")
        if action == '买入建仓':
            report_lines.append(f"买入依据：{'；'.join(action_reason_parts)}")
            report_lines.append("")
            report_lines.append("建仓策略：")
            for plan_line in position_plan:
                report_lines.append(f"  {plan_line}")
            report_lines.append("")
            report_lines.append("止损设置：")
            for sl_line in stop_loss_settings:
                report_lines.append(f"  {sl_line}")
            report_lines.append("")
            if target_reference:
                report_lines.append("止盈参考：")
                for tr_line in target_reference:
                    report_lines.append(f"  {tr_line}")
        elif action == '清仓':
            report_lines.append(f"清仓理由：{'；'.join(action_reason_parts)}")
            if stop_loss_settings:
                report_lines.append("")
                report_lines.append("操作策略：")
                for sl_line in stop_loss_settings:
                    report_lines.append(f"  {sl_line}")
        elif action == '持仓观察':
            report_lines.append(f"当前状态：{'；'.join(action_reason_parts)}")
        else:
            report_lines.append(f"等待理由：{'；'.join(action_reason_parts)}")
            report_lines.append("")
            report_lines.append("等待信号：")
            for ws in watch_signals:
                report_lines.append(f"  {ws}")
        
        report_lines.append("")
        # L3 评分汇总
        report_lines.append(f"缠论评分: {chanlun_score:.0f}/100 ({score_recommendation})")
        if score_details:
            report_lines.append("评分明细:")
            for sd in score_details[:5]:
                report_lines.append(f"  {sd}")
        report_lines.append("")

        report_lines.append("风险提示：")
        for rn in risk_notes:
            report_lines.append(f"  注意: {rn}")
        if pct_from_zs and abs(pct_from_zs) > 20:
            report_lines.append(f"  注意: 当前价格距中枢{abs(pct_from_zs):.0f}%，趋势一旦反转回调空间大")

        analysis_report = '\n'.join(report_lines)

        # 仓位和建议周期（兼容字段）
        if action == '买入建仓':
            pos_sug = '15%'
            hold_period = '1~3个月(等待上升段走完)'
        elif action == '清仓':
            pos_sug = '0%'
            hold_period = '立即'
        else:
            pos_sug = '0%'
            hold_period = '观望'

        # Phase 1 P1-7: 级别经验性上限检查
        _level_limit = False
        try:
            if zhongshu_list:
                _top_zs = zhongshu_list[0]
                _top_dur = _top_zs.duration or ''
                import re
                _dm = re.search(r'([\d.]+)\s*(月|周|天)', _top_dur)
                if _dm:
                    _val = float(_dm.group(1))
                    _unit = _dm.group(2)
                    _months = _val if _unit == '月' else (_val / 4.3 if _unit == '周' else _val / 30)
                    _level_limit = (_top_zs.level == 'daily' and _months >= 6) or (_top_zs.level == 'weekly' and _months >= 12)
        except Exception:
            pass

        return {
            'strategy_name': '缠论走势分析',
            'period': period,
            'status_recognition': {
                'state': 'ACCUMULATING' if trend_str == '上升' else ('BEARISH' if trend_str == '下降' else 'RANGING'),
                'state_label': trend_str or '方向待定',
                'trend': {
                    'direction': 'up' if trend_str == '上升' else ('down' if trend_str == '下降' else ''),
                    'strength': 'strong' if '延续' in (last_bi_status or '') else 'weakening',
                    'stage': f'{_level_label(period)}{last_bi_status}' if last_bi_status else '',
                },
                'momentum': {
                    'level': '/'.join(
                        [BP_TYPE_CN.get(t, t) for t in buy_types | sell_types]
                    ) if (buy_types or sell_types) else (str(divergence.direction) if divergence else '无信号'),
                    'score': round(divergence.confidence, 4) if divergence else 0.0,
                    'level_cross': level_cross_info,
                    'level_cross_score': round(level_cross_score, 4),
                },
                'volume': {'state': '', 'structure': '/'.join(BP_TYPE_CN.get(t, t) for t in buy_types) if buy_types else ''},
                'buy_sell_point': {
                    'buy': [BP_TYPE_CN.get(t, t) for t in buy_types],
                    'sell': [BP_TYPE_CN.get(t, t) for t in sell_types],
                },
                'support_resistance': {
                    # 2026-08-10 修复：无中枢时返回 None（原 0.0 假值——
                    # 104/4974 只 support=0 被消费端误判支撑位为 0）
                    'support': round(float(zs_low), 2) if zs_low else None,
                    'resistance': round(float(zs_high), 2) if zs_high else None,
                },
                # 2026-08-10 核查修复：risk_level 公式退化（原条件不同源恒 MEDIUM）——
                # 改用缠论结构自身风险信号组合（卖点/下降趋势+弱动量=HIGH；上升+背驰向上=LOW）
                'risk_level': (
                    'HIGH' if (bool(sell_types)
                               or (trend_str == '下降'
                                   and not (divergence is not None
                                            and divergence.confidence < 0.5)))
                    else ('LOW' if (not sell_types and trend_str == '上升'
                                    and divergence is not None
                                    and divergence.direction == 'up')
                          else 'MEDIUM')),
                # Phase 1 P1-2: 时序过滤后的有效信号（取买卖点中时序最新的一个）
                'active_signal': _build_active_signal(best_buy, best_sell, latest_date, latest_close) if (best_buy or best_sell) else None,
                'active_signal_label': _build_active_label(best_buy, best_sell, divergence),
                # Phase 1 P1-2: 中枢降级标记（偏离 > 30% 标记为 historical）
                'near_levels_filtered': _build_filtered_levels(zhongshu_list, latest_close) if zhongshu_list else [],
                # Phase 1 P1-7: 级别经验性上限
                'level_upper_limit': _level_limit,
                'multi_level': {
                    'direction_text': level_cross_info or '',
                    'level_cross_score': round(level_cross_score, 4),
                    'position_vs_zs': position_vs_zs,
                    'position_detail': position_detail,
                    'near_levels': _dedupe_near_levels([
                        {'level': zs.level, 'price': round(float(zs.center), 2),
                         'support': round(float(zs.low), 2),
                         'resistance': round(float(zs.high), 2),
                         'type': zs.type, 'duration': zs.duration,
                         'start_date': str(zs.start_date)[:10] if zs.start_date else '',
                         'end_date': str(zs.end_date)[:10] if zs.end_date else '',
                         'distance_pct': round((latest_close - zs.center) / zs.center * 100, 1) if latest_close and zs.center else None}
                        for zs in zhongshu_list
                    ]) if zhongshu_list else [],
                    'level_details': level_details,
                    # 批次3: 多级别联立数据
                    'levels': multi_result.get('levels', {}),
                    'direction_map': multi_result.get('direction_map', {}),
                    'cross_direction_text': multi_result.get('direction_text', ''),
                },
            },
            'signal': internal_signal,
            'signal_label': internal_label,
            'confidence': round(confidence, 2),
            'entry_zone': [entry_low, entry_high],
            'risk_line': risk_line,
            'target_zone': [entry_high, target_val],
            'position_suggestion': pos_sug,
            'holding_period': hold_period,
            'evidence': evidence_list,
            'risk_notes': risk_notes,
            'signal_date': latest_date,
            'backtest_win_rates': self._get_signal_win_rates(internal_signal),
            # L3 缠论评分
            'chanlun_score': chanlun_score,
            'chanlun_recommendation': score_recommendation,
            'score_details': score_details,


            # 缠论结构化分析详情（供前端结构化展示）
            'chanlun_analysis_detail': {
                '走势结构': {
                    '趋势方向': trend_str,
                    '线段数量': seg_count,
                    '中枢数量': zs_count,
                    '当前笔阶段': last_bi_status,
                    '笔阶段详情': phase_detail,
                },
                '中枢分析': {
                    '最新中枢区间': [zs_low, zs_high],
                    '中枢中心': zs_center,
                    '价格相对位置': position_vs_zs,
                    '价格详情': position_detail,
                } if latest_zhongshu else {},
                'zhongshu_list': [
                    {'low': round(float(zs.low), 2), 'high': round(float(zs.high), 2),
                     'center': round(float(zs.center), 2) if zs.center else None,
                     'type': zs.type, 'level': zs.level,
                     'direction': zs.direction, 'duration': zs.duration,
                     'start_date': str(zs.start_date)[:10] if zs.start_date else '',
                     'end_date': str(zs.end_date)[:10] if zs.end_date else '',
                     'range_width': round(float(zs.range_width), 2) if zs.range_width else None,
                     'seg_count': len(zs.segments) if zs.segments else 0}
                    for zs in zhongshu_list
                ] if zhongshu_list else [],
                '买卖点信号': {
                    '中枢形成后买点数': len(recent_buy),
                    '中枢形成后卖点数': len(recent_sell),
                    '最近买点': {
                        '类型': BP_TYPE_CN.get(best_buy.type, best_buy.type),
                        '日期': str(best_buy.position.get('date', ''))[:10],
                        '价格': round(best_buy.position.get('price', 0), 2),
                        '当前涨幅': round(buy_price_pct, 1),
                    } if best_buy else None,
                    '最近卖点': {
                        '类型': BP_TYPE_CN.get(best_sell.type, best_sell.type),
                        '日期': str(best_sell.position.get('date', ''))[:10],
                        '价格': round(best_sell.position.get('price', 0), 2),
                        '当前跌幅': round(sell_price_pct, 1),
                    } if best_sell else None,
                    '背驰信号': {
                        '方向': divergence.direction,
                        '类型': divergence.type,
                        '置信度': round(divergence.confidence, 2),
                    } if divergence else None,
                },
                '操作建议': {
                    '建议动作': action,
                    '建议置信度': round(confidence, 2),
                    '依据': '; '.join(action_reason_parts) if action_reason_parts else None,
                    '建仓策略': position_plan if position_plan else None,
                    '止损设置': stop_loss_settings if stop_loss_settings else None,
                    '止盈参考': target_reference if target_reference else None,
                    '等待信号': watch_signals if watch_signals else None,
                },
            },
            
            # 全中文分析报告（主要用户输出）
            '分析报告': analysis_report,
            'latest_close': latest_close,
        }
    def _compute_factor_signal(self, ts_code: str, df: pd.DataFrame, market_context: Optional[Dict] = None) -> Optional[Dict]:
        """计算因子评分信号 (L3) — 优先使用 FactorRegistry"""
        closes = df['close'].values
        volumes = df['vol'].values if 'vol' in df.columns else df['amount'].values
        latest_close = float(closes[-1])
        latest_date = df.index[-1] if isinstance(df.index, pd.DatetimeIndex) else df.iloc[-1].get('trade_date', date.today())

        if len(closes) < 20:
            return None

        # 优先从 factor_cache 读取预计算因子值
        from app.data import get_data_manager
        try:
            dm = get_data_manager()
            cached_factors = dm.get_cached_factors(ts_code)
            if cached_factors is not None and not cached_factors.empty:
                # cached_factors: [factor_name, value, trade_date]
                latest = cached_factors.loc[cached_factors.groupby('factor_name')['trade_date'].idxmax()]
                scores = {row['factor_name']: float(row['value']) for _, row in latest.iterrows()}
                weights = {'ROC': 0.15, 'VOL_RATIO': 0.15, 'ATR': 0.10, 'RSI': 0.15, 'LINEARREG_SLOPE': 0.10,
                           'MFI': 0.10, 'MA_CROSS': 0.15, 'ACCEL': 0.10}
                valid = {k: v for k, v in scores.items() if k in weights}
                if valid:
                    composite = sum(valid[k] * weights[k] for k in valid)
                    evidence_keys = list(valid.keys())
                    registry_ok = True
                    registry_scores = scores
                    scores['source'] = 'cache'
                    logger.debug(f"{ts_code} 使用 factor_cache 预计算因子 ({len(valid)} 因子)")
                else:
                    raise ValueError("缓存因子不匹配")
            else:
                raise ValueError("无缓存因子")
        except Exception:
            # 回退到 FactorRegistry 实时计算
            self.data_manager.request_data('factor_precompute', ts_code)
            registry_scores, registry_ok = self._compute_via_registry(df)
        if registry_ok:
            scores = registry_scores
            weights = {'ROC': 0.15, 'VOL_RATIO': 0.15, 'ATR': 0.10, 'RSI': 0.15, 'LINEARREG_SLOPE': 0.10,
                       'MFI': 0.10, 'MA_CROSS': 0.15, 'ACCEL': 0.10}
            composite = sum(scores.get(k, 0.5) * weights[k] for k in weights)
            evidence_keys = list(scores.keys())

            # [P2-#55] 状态依赖动态权重矩阵
            try:
                from app.engine.framework.state_dependent_factor_weight import StateDependentFactorWeight
                market_state = (market_context or {}).get('market_state', 'UNKNOWN') if market_context else 'UNKNOWN'
                # 映射因子分数到4个语义类别
                mapped_scores = {
                    'momentum': (scores.get('ROC', 0.5) + scores.get('LINEARREG_SLOPE', 0.5)) / 2,
                    'reversal': 1 - abs(scores.get('RSI', 0.5) - 0.5) * 2,  # RSI偏离0.5越远=反转信号越强
                    'sentiment': scores.get('VOL_RATIO', 0.5),
                    'chip': scores.get('ATR', 0.5),
                }
                dyn = StateDependentFactorWeight().compute_weighted_score(mapped_scores, market_state)
                if abs(dyn['score'] - composite) > 0.2:
                    scores['dynamic_weight_adjusted'] = True
                scores['dynamic_weight_detail'] = dyn['weight_detail']
                scores['dynamic_weighted_score'] = dyn['score']
                scores['dynamic_market_state'] = market_state
            except Exception:
                pass
        else:
            # 降级到内联计算
            scores, composite = self._compute_factor_signal_inline(closes, volumes)
            evidence_keys = list(scores.keys())

        # 信号判定
        if composite >= 0.6:
            signal = StrategySignal.BULLISH.value
            signal_label = '买入'
        elif composite >= 0.4:
            signal = StrategySignal.WATCH.value
            signal_label = '关注'
        else:
            signal = StrategySignal.NEUTRAL.value
            signal_label = '观望'

        return {
            'strategy_name': '因子评分系统',
            'status_recognition': {
                'state': 'ACCUMULATING' if composite >= 0.6 else ('BEARISH' if composite < 0.4 else 'RANGING'),
                'state_label': signal_label,
                'trend': {
                    'direction': 'up' if composite >= 0.6 else ('down' if composite < 0.4 else ''),
                    'strength': 'strong' if composite >= 0.7 else ('moderate' if composite >= 0.4 else 'weak'),
                    'stage': '',
                },
                'momentum': {
                    'level': signal,
                    'score': round(max(scores.values()), 4) if scores else round(composite, 4),
                },
                'volume': {'state': '', 'structure': ''},
                'support_resistance': {'support': 0.0, 'resistance': 0.0},
                'risk_level': 'HIGH' if composite < 0.4 else 'LOW',
            },
            'signal': signal,
            'signal_label': signal_label,
            'confidence': round(composite, 2),
            'entry_zone': [round(latest_close * 0.97, 2), round(latest_close * 1.02, 2)],
            'risk_line': round(latest_close * 0.90, 2),
            'target_zone': [round(latest_close * 1.05, 2), round(latest_close * 1.18, 2)],
            'position_suggestion': '10%',
            'holding_period': '2-4周',
            'evidence': [f"{k}: {scores[k]:.2f}" for k in evidence_keys],
            'risk_notes': ['因子模型假设偏差', '市场风格切换风险'],
            'signal_date': latest_date if isinstance(latest_date, str) else latest_date.strftime('%Y-%m-%d'),
            'backtest_win_rates': self._get_signal_win_rates(signal),
        }

    def _compute_via_registry(self, df: pd.DataFrame) -> tuple:
        """通过 FactorRegistry 计算因子评分"""
        try:
            calculator = FactorCalculator()
            factor_configs = [
                {'name': 'ROC', 'params': {'period': 20}},
                {'name': 'VOL_RATIO', 'params': {'period': 5}},
                {'name': 'ATR', 'params': {'period': 14}},
                {'name': 'RSI', 'params': {'period': 14}},
                {'name': 'LINEARREG_SLOPE', 'params': {'period': 20}},
            ]
            scores = {}
            for cfg in factor_configs:
                series = calculator.calculate_single_factor(df, cfg['name'], **cfg['params'])
                if series is not None and not series.empty:
                    val = float(series.iloc[-1])
                    name = cfg['name']
                    if name == 'ROC':
                        scores[name] = min(max(val * 5 + 0.5, 0), 1)
                    elif name == 'VOL_RATIO':
                        scores[name] = min(val * 0.4, 1)
                    elif name == 'ATR':
                        scores[name] = min(val / (float(df['close'].iloc[-1]) * 0.1 + 1e-9), 1)
                    elif name == 'RSI':
                        scores[name] = 1 - abs(val - 50) / 50
                    elif name == 'LINEARREG_SLOPE':
                        scores[name] = min(max(val * 10 + 0.5, 0), 1)

            # 扩展因子：直接在 OHLCV 上计算（不依赖 FactorRegistry）
            closes = df['close'].values
            volumes = df['vol'].values if 'vol' in df.columns else df['amount'].values

            # MFI (资金流强度) — 用价量关系估算
            if len(closes) >= 14 and len(volumes) >= 14:
                typical_prices = (df['high'].values[-14:] + df['low'].values[-14:] + closes[-14:]) / 3
                vol_slice = volumes[-14:]
                pos_flow = sum(vol_slice[i] for i in range(1, 14) if typical_prices[i] > typical_prices[i-1])
                neg_flow = sum(vol_slice[i] for i in range(1, 14) if typical_prices[i] < typical_prices[i-1])
                if neg_flow > 0:
                    mfi = 100 - (100 / (1 + pos_flow / neg_flow))
                    scores['MFI'] = min(mfi / 100, 1)
                else:
                    scores['MFI'] = 0.6

            # MA 交叉强度 (5日 vs 20日)
            if len(closes) >= 20:
                ma_5 = np.mean(closes[-5:])
                ma_20 = np.mean(closes[-20:])
                cross_ratio = (ma_5 - ma_20) / (ma_20 + 1e-9)
                scores['MA_CROSS'] = min(max(cross_ratio * 20 + 0.5, 0), 1)

            # 价格加速度 (对比近5日 vs 近20日涨幅)
            if len(closes) >= 20:
                mom_5 = (closes[-1] / closes[-6] - 1) if len(closes) >= 6 else 0
                mom_20 = (closes[-1] / closes[-21] - 1) if len(closes) >= 21 else 0
                accel = mom_5 - mom_20 / 4  # 近5日动量 vs 近20日平均动量
                scores['ACCEL'] = min(max(accel * 20 + 0.5, 0), 1)

            # 扩展因子通过 FactorRegistry 计算（C5）
            # 旧 _FACTOR_COMPUTERS 已废弃（287号方案 v2.3）

            if len(scores) >= 3:
                return scores, True
        except Exception as e:
            logger.debug(f"FactorRegistry 计算降级: {e}")
        return {}, False

    def _compute_factor_signal_inline(self, closes: np.ndarray, volumes: np.ndarray) -> tuple:
        """内联因子计算（降级后备）"""
        scores = {}

        # 动量因子
        mom_20 = (closes[-1] - closes[-20]) / closes[-20]
        scores['momentum'] = min(max(mom_20 * 5 + 0.5, 0), 1)

        # 成交量因子
        if len(volumes) >= 20:
            vol_ratio = volumes[-1] / (np.mean(volumes[-20:-1]) + 1e-9)
            scores['volume'] = min(vol_ratio * 0.4, 1)
        else:
            scores['volume'] = 0.5

        # 波动率因子
        vol_20 = np.std(closes[-20:]) / np.mean(closes[-20:])
        scores['volatility'] = min(vol_20 * 10, 1)

        # RSI 因子
        if len(closes) >= 15:
            deltas = np.diff(closes[-15:])
            gains = np.sum(deltas[deltas > 0])
            losses = abs(np.sum(deltas[deltas < 0]))
            rsi = 50 if losses == 0 else (100 - 100 / (1 + gains / losses))
            scores['rsi'] = 1 - abs(rsi - 50) / 50
        else:
            scores['rsi'] = 0.5

        weights = {'momentum': 0.3, 'volume': 0.25, 'volatility': 0.2, 'rsi': 0.25}
        composite = sum(scores[k] * weights[k] for k in weights)
        return scores, composite

    def _build_chip_evidence(self, df: pd.DataFrame, score: float,
                              turnover_rate: Optional[float] = None,
                              turnover_status: Optional[str] = None) -> List[str]:
        """构建筹码分析依据"""
        closes = df['close'].values
        volumes = df['vol'].values if 'vol' in df.columns else df['amount'].values
        evidence = []

        # 换手率证据
        if turnover_rate is not None and turnover_status is not None:
            evidence.append(f"换手率{turnover_rate:.2f}%，{turnover_status}")
        elif turnover_rate is not None:
            evidence.append(f"换手率{turnover_rate:.2f}%")

        # 价格位置
        if len(closes) >= 60:
            pos = (closes[-1] - np.min(closes[-60:])) / (np.max(closes[-60:]) - np.min(closes[-60:]) + 1e-9)
            if pos <= 0.3:
                evidence.append('股价处于60日低位区')
            elif pos >= 0.7:
                evidence.append('股价处于60日高位区')
            else:
                evidence.append('股价处于60日中位区')

        # 量比
        if len(volumes) >= 5:
            vr = volumes[-1] / (np.mean(volumes[-5:-1]) + 1e-9)
            if vr >= 1.5:
                evidence.append(f'成交量放大({vr:.1f}倍)')
            elif vr >= 1.2:
                evidence.append(f'成交量温和放量({vr:.1f}倍)')

        # 评分说明
        if score >= 7:
            evidence.append('筹码评分高，主力资金活跃')
        elif score >= 5:
            evidence.append('筹码评分中等，主力资金介入')

        if not evidence:
            evidence.append('基础技术分析信号')

        return evidence

    def _build_default_chip_signal(self, ts_code: str, df: pd.DataFrame,
                                    market_context: Optional[Dict] = None) -> Dict:
        """构建空筹码信号（大盘数据不可用时降级使用）"""
        latest_close = float(df['close'].iloc[-1])
        latest_date = df.index[-1] if isinstance(df.index, pd.DatetimeIndex) else df.iloc[-1].get('trade_date', '')
        evidence = []
        if market_context:
            tr = market_context.get('turnover_rate')
            if tr: evidence.append(f"换手率: {tr:.2f}%")
            net_lg = market_context.get('net_lg_amount')
            if net_lg: evidence.append(f"近5日大单净额: {net_lg:+.0f}")
        chip_status = {
            'state': 'RANGING', 'state_label': '观望',
            'trend': {'direction': '', 'strength': '', 'stage': '未知'},
            'momentum': {'level': 'HOLD', 'score': 0.5},
            'volume': {'state': '', 'structure': ''},
            'support_resistance': {'support': 0.0, 'resistance': 0.0},
            'risk_level': 'MEDIUM',
            'chip_peak': 0.0, 'concentration': 0.0, 'asr': None,
            'main_force_cost': {"cost_price": 0, "distance_pct": 0, "near_cost": False},
            'margin_cost_price': None, 'sandwich_zone': None,
            'retail_vs_institutional': None,
            'net_lg_amount_5d': None, 'net_elg_amount_5d': None, 'net_sm_amount_5d': None,
            'sentiment_crowding': None, 'sentiment_crowding_label': None,
            'cyqkl': None,
            'fake_institution': {"suspected": False, "reason": "大盘数据不可用", "confidence": 0.0},
            'cross_compare': {"conclusion": "neutral", "detail": "大盘数据不可用", "score": 0.0},
            'lhb_high_success': {"score": 0.0, "conditions": {}, "detail": "大盘数据不可用"},
            'concentration_factor': {"factor": 0.0, "change_pct": 0.0, "source": "none", "detail": "大盘数据不可用"},
        }
        return {
            'strategy_name': '筹码主力分析',
            'status_recognition': chip_status,
            'signal': 'neutral', 'signal_label': '观望',
            'confidence': 0.5,
            'entry_zone': [round(latest_close * 0.97, 2), round(latest_close * 1.02, 2)],
            'risk_line': round(latest_close * 0.92, 2),
            'target_zone': [round(latest_close * 1.02, 2), round(latest_close * 1.12, 2)],
            'position_suggestion': '10%', 'holding_period': '1-3个月',
            'evidence': evidence, 'risk_notes': ['大盘数据不可用，筹码信号降级'],
            'signal_date': latest_date if isinstance(latest_date, str) else str(latest_date)[:10],
        }

    def _build_chip_status(self, chip_signal: Dict) -> Dict:
        """构建筹码策略的现状识别"""
        phase = chip_signal.get('signal_source_detail', {}).get('phase', '')
        signal = chip_signal.get('signal', 'NEUTRAL')

        # 状态判定
        if '吸筹' in phase or '吸筹' in str(chip_signal.get('evidence', [])):
            state, label = 'ACCUMULATING', '主力吸筹'
        elif '出货' in phase or '派发' in phase:
            state, label = 'DISTRIBUTING', '主力出货'
        elif signal in ('BULLISH',):
            state, label = 'ACCUMULATING', '偏向看多'
        elif signal in ('BEARISH',):
            state, label = 'DISTRIBUTING', '偏向看空'
        else:
            state, label = 'RANGING', '方向不明'

        cap_level = chip_signal.get('signal_source_detail', {}).get('cap_level', '')
        risk_level = 'HIGH' if cap_level in ('MEGA',) else 'MEDIUM'

        return {
            'state': state,
            'state_label': label,
            'trend': {'direction': '', 'strength': '', 'stage': phase},
            'momentum': {'level': signal, 'score': chip_signal.get('confidence', 0.5)},
            'volume': {'state': '', 'structure': ''},
            'support_resistance': {'support': 0.0, 'resistance': 0.0},
            'risk_level': risk_level,
        }

    def _build_chanlun_status(self, chanlun_signal: Dict) -> Dict:
        """构建缠论策略的现状识别"""
        detail = chanlun_signal.get('chanlun_analysis_detail', {})
        structure = detail.get('走势结构', {})
        zhongshu = detail.get('中枢分析', {})
        ops = detail.get('操作建议', {})

        trend_str = structure.get('趋势方向', '')
        if trend_str == '上升':
            state, label = 'ACCUMULATING', '上升趋势'
        elif trend_str == '下降':
            state, label = 'BEARISH', '下降趋势'
        else:
            state, label = 'RANGING', '方向待定'

        bi_status = structure.get('当前笔阶段', '')
        trend = {
            'direction': 'up' if trend_str == '上升' else ('down' if trend_str == '下降' else ''),
            'strength': 'strong' if '延续' in bi_status else 'weakening',
            'stage': bi_status,
        }

        zs_interval = zhongshu.get('最新中枢区间', [])
        support_resistance = {
            'support': round(float(zs_interval[0]), 2) if len(zs_interval) > 0 else 0.0,
            'resistance': round(float(zs_interval[1]), 2) if len(zs_interval) > 1 else 0.0,
        }

        div = detail.get('买卖点信号', {}).get('背驰信号')
        momentum = {
            'level': str(div.get('方向', '')) if div else '',
            'score': float(div.get('置信度', 0)) if div else 0.0,
        }

        score = chanlun_signal.get('chanlun_score', 50)
        risk_level = 'HIGH' if (score < 30 or state == 'BEARISH') else 'MEDIUM'

        return {
            'state': state,
            'state_label': label,
            'trend': trend,
            'momentum': momentum,
            'volume': {'state': '', 'structure': ''},
            'support_resistance': support_resistance,
            'risk_level': risk_level,
        }

    def _build_factor_status(self, factor_signal: Dict) -> Dict:
        """构建因子策略的现状识别"""
        signal = factor_signal.get('signal', 'NEUTRAL')
        confidence = factor_signal.get('confidence', 0.5)

        if confidence >= 0.6 and signal in ('BULLISH',):
            state, label = 'ACCUMULATING', '因子看多'
        elif confidence < 0.4 or signal in ('BEARISH',):
            state, label = 'BEARISH', '因子看空'
        else:
            state, label = 'RANGING', '因子中性'

        # 从 evidence 提取因子得分
        ev = factor_signal.get('evidence', [])
        scores = {}
        for e in ev:
            parts = e.split(':')
            if len(parts) == 2:
                try:
                    scores[parts[0].strip()] = float(parts[1].strip())
                except ValueError:
                    pass

        max_score = max(scores.values()) if scores else 0.0
        momentum = {'level': signal, 'score': round(max_score, 4)}

        risk_level = 'HIGH' if state == 'BEARISH' else 'LOW'

        return {
            'state': state,
            'state_label': label,
            'trend': {'direction': '', 'strength': '', 'stage': ''},
            'momentum': momentum,
            'volume': {'state': '', 'structure': ''},
            'support_resistance': {'support': 0.0, 'resistance': 0.0},
            'risk_level': risk_level,
        }

    def _compute_bociasi_signal(self, ts_code: str, df: pd.DataFrame, market_context: Optional[Dict] = None) -> Optional[Dict]:
        """计算 BOCIASI 快线情绪信号"""
        from app.engine.framework.bociasi_quickline import BociasiQuickLine
        try:
            bql = BociasiQuickLine()
            result = bql.evaluate(df)
            if result['pass_count'] == 0:
                return None

            signal_map = {'BUY': 'BULLISH', 'WATCH': 'WATCH', 'NEUTRAL': 'NEUTRAL', 'BEARISH': 'BEARISH'}
            label_map = {'BUY': '情绪积极', 'WATCH': '情绪中性', 'NEUTRAL': '情绪平淡', 'BEARISH': '情绪低迷看空'}
            ind = result['indicators']

            evidence = []
            if ind.get('fast_vol'):
                evidence.append(f"放量确认: 量比{result['details']['vol_ratio']:.1f}x")
            if ind.get('fast_price'):
                evidence.append(f"价格强势: 收于5日均价之上(+{result['details']['price_offset_pct']:.1f}%)")
            if ind.get('fast_mom'):
                evidence.append(f"短期动量: 5日涨幅{result['details']['mom_5d_pct']:.1f}%")
            if ind.get('fast_breadth'):
                evidence.append(f"波动活跃: 日内振幅{result['details']['amplitude_pct']:.1f}%")

            # 注入情绪周期信息
            emotion_cycle = _fmz_to_emotion_cycle((market_context or {}).get('market_state', ''))
            state_label = label_map.get(result['signal'], '')
            if emotion_cycle and emotion_cycle != '情绪中性':
                state_label = f'{emotion_cycle}·{state_label}'

            return {
                'strategy_name': 'BOCIASI快线',
                'status_recognition': {
                    'state': ('ACCUMULATING' if result['signal'] == 'BUY' else
                          'BEARISH' if result['signal'] == 'BEARISH' else
                          'DISTRIBUTING' if result['signal'] == 'WATCH' and (result['confidence'] < 0.5 or not ind.get('fast_price')) else
                          'RANGING'),
                    'state_label': state_label,
                    'trend': {'direction': '', 'strength': '', 'stage': ''},
                    'momentum': {'level': result['signal'], 'score': result['confidence']},
                    'volume': {'state': '放量' if ind.get('fast_vol') else '平量', 'structure': ''},
                    'support_resistance': {'support': 0.0, 'resistance': 0.0},
                    'risk_level': 'LOW' if result['signal'] == 'BUY' else ('HIGH' if result['signal'] == 'NEUTRAL' else 'MEDIUM'),
                },
                'signal': signal_map.get(result['signal'], 'NEUTRAL'),
                'signal_label': label_map.get(result['signal'], '情绪中性'),
                'confidence': result['confidence'],
                'entry_zone': [0, 0],
                'risk_line': 0,
                'target_zone': [0, 0],
                'position_suggestion': '0%',
                'holding_period': '短期（3-5日）',
                'evidence': evidence,
                'risk_notes': ['情绪指标偏短期，需结合其他策略使用'],
                'signal_date': '',
            }
        except Exception as e:
            logger.debug(f"{ts_code} BOCIASI 信号异常: {e}")
            return None

    def _compute_volume_price_signal(self, ts_code: str, df: pd.DataFrame,
                                      market_context: Optional[Dict] = None,
                                      market_env: Optional[Dict] = None) -> Optional[Dict]:
        """计算量价分析信号 (L3) — 完整四阶段分析链 + Phase 2 增强"""
        from app.engine.framework.volume_price_strategy import compute_volume_price_signal
        try:
            # [P2-#57] 注入动态周期权重
            env = dict(market_env or {})
            if market_context and 'cycle_weights' in market_context:
                env['cycle_weights'] = market_context['cycle_weights']

            result = compute_volume_price_signal(ts_code, df, market_env=env)
            if result and market_context and 'cycle_weights' in market_context:
                cw = market_context['cycle_weights']
                result['cycle_weights'] = cw
                # 根据周期权重微调信号置信度
                if cw.get('execution', 0) >= 0.3:
                    result['confidence'] = round(result.get('confidence', 0.5) * 0.85, 2)
                    result.setdefault('evidence', []).append(
                        f"[周期权重] 执行层{cw['execution']:.0%}，保守处理"
                    )

            # ═══ Phase 2 量价增强 ═══
            if result is not None and df is not None and not df.empty:
                closes = df['close'].astype(float).values
                volumes = df['vol'].astype(float).values if 'vol' in df.columns else df['amount'].astype(float).values
                latest_close = float(closes[-1])

                # P2-4: 八种基本量价形态分类
                basic_form, confirmation = _classify_vp_basic(closes, volumes)
                result['basic_form'] = basic_form
                result['vp_confirmation'] = confirmation

                # P2-5/P2-8: 主力阶段权重 + 市场状态动态调整 (C4/V3)
                chip_phase = (market_context or {}).get('phase', '')
                market_state = (market_context or {}).get('market_state', 'UNKNOWN')
                phase_adjustment = _apply_phase_weight(result, chip_phase, market_state)
                if phase_adjustment:
                    result['phase_weight'] = phase_adjustment

                # P2-7: 放量止跌/止涨序列检测 (V2)
                insider = _detect_volume_reversal_sequence(closes, volumes,
                                                          df['high'].values if 'high' in df.columns else closes,
                                                          df['low'].values if 'low' in df.columns else closes)
                if insider:
                    result['insider_behavior'] = insider

            return result
        except Exception as e:
            logger.debug(f"{ts_code} 量价信号异常: {e}")
            return None

    def _get_signal_win_rates(self, signal_type: str) -> dict:
        """从缓存获取信号类型的回测赢率数据"""
        try:
            wr = self.data_manager.cache.get_cached_win_rate(signal_type)
            if wr:
                return {
                    'signal_type': wr.get('signal_type', signal_type),
                    'samples': wr.get('samples', 0),
                    'win_rate_5d': float(wr.get('win_rate_5d', 0)),
                    'win_rate_10d': float(wr.get('win_rate_10d', 0)),
                    'win_rate_20d': float(wr.get('win_rate_20d', 0)),
                    'avg_return_5d': float(wr.get('avg_return_5d', 0)),
                    'avg_return_20d': float(wr.get('avg_return_20d', 0)),
                    'sharpe_5d': float(wr.get('sharpe_5d', 0)),
                    'sharpe_20d': float(wr.get('sharpe_20d', 0)),
                }
        except Exception:
            pass
        return {}
    def _persist_signals(self, ts_code: str, signals: List[Dict]):
        """将实时计算的信号持久化到数据库"""
        if not signals:
            return
        try:
            for sig in signals:
                entry = sig.get('entry_zone', [None, None])
                target = sig.get('target_zone', [None, None])
                reason_parts = []
                if sig.get('evidence'):
                    reason_parts.extend(sig['evidence'])
                if sig.get('risk_notes'):
                    reason_parts.append('风险: ' + '; '.join(sig['risk_notes']))
                record = SignalModel(
                    ts_code=ts_code,
                    signal_date=datetime.now(),
                    signal_type=sig.get('signal', 'NEUTRAL'),
                    confidence=sig.get('confidence', 0.5),
                    entry_price=entry[0],
                    stop_loss=sig.get('risk_line'),
                    take_profit=target[-1] if target else None,
                    indicators={
                        'strategy_name': sig.get('strategy_name'),
                        'signal_label': sig.get('signal_label'),
                        'position_suggestion': sig.get('position_suggestion'),
                        'holding_period': sig.get('holding_period'),
                    },
                    reason='; '.join(reason_parts) if reason_parts else None,
                    status='active' if sig.get('signal') in ('BULLISH', 'WATCH') else 'pending',
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
                db.session.add(record)
            db.session.commit()
            # 同步写入 StrategyOutput 表
            self._sync_to_strategy_output(ts_code, signals)
            logger.info(f"{ts_code}: 已持久化 {len(signals)} 条信号")
        except Exception as e:
            db.session.rollback()
            logger.warning(f"{ts_code}: 信号持久化失败: {e}")



    def _sync_to_strategy_output(self, ts_code: str, signals: list):
        """同步信号到 StrategyOutput 表（账户管理系统读取用）"""
        if not signals:
            return
        try:
            # signal_date already imported at module level
            for sig in signals:
                entry_zone = sig.get('entry_zone', [None, None])
                target_zone = sig.get('target_zone', [None, None])
                sig_date = sig.get('signal_date', '')
                if isinstance(sig_date, str):
                    try:
                        sig_date = datetime.strptime(sig_date[:10], '%Y-%m-%d').date()
                    except ValueError:
                        sig_date = datetime.now().date()
                else:
                    sig_date = datetime.now().date()

                signal_val = sig.get('signal', 'NEUTRAL')
                
                # 合并 evidence 和 signal_source_detail（方案二完整版用）
                full_evidence = list(sig.get('evidence', []))
                sig_detail = sig.get('signal_source_detail', {})
                if sig_detail:
                    for k, v in sig_detail.items():
                        if v and (isinstance(v, str) or (isinstance(v, list) and v)):
                            full_evidence.append(f"[{k}] {v if isinstance(v, str) else ', '.join(v)}")

                StrategyOutputService.create_strategy_output(
                    ts_code=ts_code,
                    strategy_name=sig.get('strategy_name', '筹码策略'),
                    signal=signal_val,
                    signal_date=sig_date,
                    confidence=sig.get('confidence', 0.5),
                    entry_zone=entry_zone,
                    risk_line=sig.get('risk_line'),
                    target_zone=target_zone,
                    position_suggestion=sig.get('position_suggestion'),
                    holding_period=sig.get('holding_period'),
                    evidence=full_evidence,
                    risk_notes=sig.get('risk_notes', []),
                    status_recognition=sig.get('status_recognition'),
                )

                # 同步记录到 SignalRecord（轨A·后台自动）
                try:
                    entry_zone_list = sig.get("entry_zone", [None, None])
                    target_zone_list = sig.get("target_zone", [None, None])
                    BacktestEvidenceService().record_signal(
                        ts_code=ts_code,
                        strategy_name=sig.get("strategy_name", "筹码策略"),
                        signal_type=signal_val,
                        confidence=sig.get("confidence", 0.5),
                        entry_price=entry_zone_list[0],
                        risk_line=sig.get("risk_line"),
                        target_price=target_zone_list[-1] if target_zone_list else None,
                        entry_zone_low=entry_zone_list[0],
                        entry_zone_high=entry_zone_list[1],
                        signal_snapshot={
                            "direction": sig.get("signal_label"),
                            "evidence": full_evidence,
                            "risk_notes": sig.get("risk_notes", []),
                        },
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"{ts_code}: 同步到StrategyOutput失败: {e}")

    def _compute_vibe_signal(self, ts_code: str, df: pd.DataFrame) -> Optional[Dict]:
        """
        计算 Vibe 策略信号（渠道二新增）

        从 strategy_template_v2 加载 vibe=True 的策略，执行 code_template。
        将执行结果转化为"现状解读文本"而非加分值。

        Returns: 信号 dict 或 None
        """
        import pandas as pd
        try:
            from app import db
            from app.models.strategy_template import StrategyTemplateV2
            from sqlalchemy import and_

            templates = db.session.query(StrategyTemplateV2).filter(
                and_(StrategyTemplateV2.vibe == True, StrategyTemplateV2.status != 'disabled')
            ).all()
            if not templates:
                return None

            descriptions = []
            max_confidence = 0.0
            best_dir = 'NEUTRAL'

            for tmpl in templates:
                code = tmpl.code_template or ''
                if not code or 'return' not in code:
                    continue
                try:
                    import re
                    cleaned = re.sub(r'^\s*return\s+', 'pass  # ', code)
                    local_vars = {'df': df, 'closes': df['close'].values, 'volumes': df['vol'].values if 'vol' in df.columns else df['amount'].values}
                    exec(compile(cleaned, '<vibe_strategy>', 'exec'), local_vars)
                    result = local_vars.get('signal', {})
                    if isinstance(result, dict) and result.get('signal'):
                        conf = result.get('confidence', 0.3)
                        if conf > max_confidence:
                            max_confidence = conf
                            best_dir = result['signal']
                        desc = f"{tmpl.name}: {result.get('signal_label', result['signal'])}"
                        descriptions.append(desc)
                except Exception:
                    continue

            if not descriptions:
                return None

            return {
                'strategy_name': 'Vibe策略',
                'signal': best_dir.lower(),
                'signal_label': best_dir,
                'confidence': round(max_confidence, 2),
                'evidence': descriptions,
                'description': '; '.join(descriptions),
                'risk_notes': ['Vibe策略由AI生成，仅供参考'],
                'entry_zone': [0, 0],
                'risk_line': 0,
                'target_zone': [0, 0],
            }
        except Exception as e:
            logger.debug(f"{ts_code} Vibe策略计算失败: {e}")
            return None
