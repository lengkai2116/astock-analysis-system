"""
条件评估引擎 — ConditionEvaluator

将规则的条件定义与真实市场数据对比，判定条件是否达成。
支持盘中定时扫描和日终批量评估两种模式。

条件评估流程：
  1. 解析条件配置 (condition_id + params)
  2. 获取相关市场数据 (日线/资金流/技术指标)
  3. 执行条件判定逻辑
  4. 返回 EvaluationResult

支持的条件模式（内置，不需条件库记录 Python 代码）：
  - 价格类: >/< threshold, MA 突破/交叉, BOLL 上下轨
  - 量能类: 成交量放大 N 倍, 缩量 N%
  - 技术指标类: MACD 金叉/死叉, KDJ 超买/超卖, RSI 阈值
  - 资金流向类: 主力净流入/流出 N 金额/比例
"""
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class EvaluationResult:
    """单条件评估结果"""
    condition_id: str
    passed: bool
    current_value: Any = None
    threshold: Any = None
    details: str = ''
    data_source: str = ''
    stock_code: str = ''


@dataclass
class RuleEvaluationResult:
    """整条规则的评估结果（含多条条件）"""
    rule_id: str
    passed: bool
    condition_results: List[EvaluationResult] = field(default_factory=list)
    logic: str = 'AND'  # AND / OR
    evaluated_at: str = ''


class ConditionEvaluator:
    """条件评估引擎"""

    # 内置条件/检测方法映射
    BUILTIN_CHECKERS = {}  # condition_id → method_name

    def __init__(self):
        self._build_checker_map()

    def _build_checker_map(self):
        """构建条件ID与检测方法的映射"""
        self._checker_map = {
            # ── 价格阈值 ──
            'price-above': '_check_price_above',
            'price-below': '_check_price_below',
            'price-change-pct': '_check_price_change_pct',
            'price-break-avg': '_check_price_break_avg',
            'price-above-ma': '_check_price_above_ma',

            # ── 均线类 ──
            'ma-crossover': '_check_ma_crossover',
            'ma-多头排列': '_check_ma_bullish',
            'ma-空头排列': '_check_ma_bearish',
            'ma60-突破': '_check_ma60_breakthrough',
            'ma20-支撑': '_check_ma20_support',
            'ma120-压力': '_check_ma120_resistance',
            'ma-三线开花': '_check_ma_golden_cross',
            'ma-格兰维尔-买1': '_check_ma_buy1',
            'ma-格兰维尔-买2': '_check_ma_buy2',

            # ── 量能类 ──
            'vol-surge': '_check_vol_surge',
            'vol-shrink': '_check_vol_shrink',
            'vol-放量突破': '_check_vol_breakthrough',
            'vol-缩量回调': '_check_vol_pullback',
            'vol-温和放量': '_check_vol_gentle_increase',

            # ── MACD ──
            'macd-golden-cross': '_check_macd_golden_cross',
            'macd-death-cross': '_check_macd_death_cross',
            'macd-水上金叉': '_check_macd_above_zero_golden',
            'macd-底背离': '_check_macd_bullish_divergence',
            'macd-顶背离': '_check_macd_bearish_divergence',

            # ── KDJ ──
            'kdj-overbought': '_check_kdj_overbought',
            'kdj-oversold': '_check_kdj_oversold',
            'kdj-golden-cross': '_check_kdj_golden_cross',

            # ── RSI ──
            'rsi-overbought': '_check_rsi_overbought',
            'rsi-oversold': '_check_rsi_oversold',
            'rsi-突破': '_check_rsi_breakthrough',

            # ── BOLL ──
            'boll-突破上轨': '_check_boll_upper_break',
            'boll-跌破下轨': '_check_boll_lower_break',
            'boll-中轨支撑': '_check_boll_mid_support',

            # ── 资金流向 ──
            'moneyflow-主力净流入': '_check_moneyflow_net_inflow',
            'moneyflow-主力净流出': '_check_moneyflow_net_outflow',
            'moneyflow-散户净流入': '_check_moneyflow_retail_inflow',
            'moneyflow-大单占比': '_check_moneyflow_big_order_pct',

            # ── 形态类 ──
            'pattern-涨停': '_check_pattern_limit_up',
            'pattern-跌停': '_check_pattern_limit_down',
            'pattern-长阳': '_check_pattern_long_bullish',
            'pattern-长阴': '_check_pattern_long_bearish',
            'pattern-十字星': '_check_pattern_doji',
            'pattern-锤头线': '_check_pattern_hammer',
            'pattern-吊颈线': '_check_pattern_hanging_man',

            # ── 缠论类 ──
            'chan-一类买点': '_check_chan_buy1',
            'chan-二类买点': '_check_chan_buy2',
            'chan-三类买点': '_check_chan_buy3',
            'chan-一类卖点': '_check_chan_sell1',

            # ── 状态类 ──
            'status-涨跌幅top': '_check_status_top_gainers',
            'status-成交额排名': '_check_status_volume_rank',
            'status-换手率': '_check_status_turnover',

            # ── 实用交易规则 ──
            '实战-龙回头': '_check_fighting_dragon_back',
            '实战-出水芙蓉': '_check_fighting_water_lily',
            '实战-老鸭头': '_check_fighting_duck_head',
            '实战-多方炮': '_check_fighting_bullish_cannon',
            '实战-早晨之星': '_check_fighting_morning_star',

            # ── 时间/状态 ──
            'time-连续涨N天': '_check_time_consecutive_up',
            'time-连续跌N天': '_check_time_consecutive_down',
            'time-N日新高': '_check_time_new_high',
            'time-N日新低': '_check_time_new_low',
        }

    def evaluate(self, condition_id: str, params: Dict, stock_code: str = '') -> EvaluationResult:
        """执行单条件评估"""
        checker = self._checker_map.get(condition_id)
        if checker is None:
            return EvaluationResult(
                condition_id=condition_id,
                passed=False,
                details=f'未知条件: {condition_id}',
                stock_code=stock_code,
            )

        try:
            method = getattr(self, checker, None)
            if method is None:
                return EvaluationResult(
                    condition_id=condition_id,
                    passed=False,
                    details=f'未实现的检测方法: {checker}',
                    stock_code=stock_code,
                )
            return method(params, stock_code)
        except Exception as e:
            logger.error(f"条件评估失败 {condition_id}({stock_code}): {e}")
            return EvaluationResult(
                condition_id=condition_id,
                passed=False,
                details=f'评估异常: {e}',
                stock_code=stock_code,
            )

    def evaluate_rule(self, rule, data_provider=None) -> RuleEvaluationResult:
        """评估整条规则的所有条件"""
        from datetime import datetime

        results = []
        conditions = rule.get('conditions', [])
        logic = rule.get('condition_logic', 'AND')
        scope_detail = rule.get('scope_detail', {})
        scope_type = rule.get('scope', rule.get('range', 'multi'))

        # 确定要评估的股票列表
        stocks = self._resolve_stocks(scope_type, scope_detail)

        # 默认全市场为单次评估（无需逐股）
        if scope_type == 'market':
            for cond in conditions:
                cid = cond.get('condition_id', '')
                params = cond.get('params', {})
                result = self.evaluate(cid, params, '')
                results.append(result)

            if logic == 'AND':
                all_passed = all(r.passed for r in results)
            else:
                all_passed = any(r.passed for r in results)
        else:
            # 逐股评估 — 任何一只股票满足即视为通过
            stock_passed = {}
            for stock in stocks:
                stock_results = []
                for cond in conditions:
                    cid = cond.get('condition_id', '')
                    params = cond.get('params', {})
                    r = self.evaluate(cid, params, stock)
                    stock_results.append(r)

                # 单只股票的 AND/OR 判断
                if logic == 'AND':
                    stock_passed[stock] = all(r.passed for r in stock_results)
                else:
                    stock_passed[stock] = any(r.passed for r in stock_results)

                results.extend(stock_results)

            # 整体判定: 任何一只股票满足条件即通过
            all_passed = any(stock_passed.values()) if stock_passed else False

        return RuleEvaluationResult(
            rule_id=rule.get('id', rule.get('rule_id', 'unknown')),
            passed=bool(all_passed),
            condition_results=results,
            logic=logic,
            evaluated_at=datetime.now().isoformat(),
        )

    def _resolve_stocks(self, scope_type: str, scope_detail: dict) -> List[str]:
        """解析监控范围 -> 股票代码列表"""
        default_stocks = ['000001.SZ', '600519.SH', '300750.SZ']

        if scope_type == 'market':
            return []

        stocks = scope_detail.get('stocks', []) if scope_detail else []
        if not stocks:
            return default_stocks

        if isinstance(stocks, list):
            return stocks

        return default_stocks

    # ════════════════════════════════════════════
    # 具体检测方法
    # ════════════════════════════════════════════

    def _get_klines(self, stock_code: str, days: int = 60) -> List[Dict]:
        """获取 K 线数据（从 DataManager/DataSourceManager）"""
        try:
            from app.data.data_source_manager import data_source_manager as dsm
            end = date.today()
            start = end - timedelta(days=days)
            klines = dsm.get_data('get_kline', {
                'ts_code': stock_code,
                'start_date': start.strftime('%Y%m%d'),
                'end_date': end.strftime('%Y%m%d'),
            })
            if klines and isinstance(klines, list):
                return klines
        except Exception as e:
            logger.debug(f"获取K线失败 {stock_code}: {e}")
        return []

    def _get_latest_price(self, stock_code: str) -> Optional[float]:
        """获取最新价格"""
        klines = self._get_klines(stock_code, 5)
        if klines:
            latest = klines[-1]
            return float(latest.get('close', latest.get('c', 0)))
        return None

    def _get_ma(self, klines: List[Dict], period: int) -> Optional[float]:
        """计算均线值"""
        if len(klines) < period:
            return None
        recent = klines[-period:]
        closes = [float(k.get('close', k.get('c', 0))) for k in recent]
        return sum(closes) / len(closes)

    # ── 价格阈值类 ──

    def _check_price_above(self, params: Dict, stock_code: str) -> EvaluationResult:
        threshold = float(params.get('threshold', 0))
        price = self._get_latest_price(stock_code)
        if price is None:
            return EvaluationResult('price-above', False, current_value='N/A', threshold=threshold, details='获取价格失败', stock_code=stock_code)
        passed = price > threshold
        return EvaluationResult('price-above', passed, current_value=round(price, 2), threshold=threshold,
                                details=f'当前价 {price:.2f} {"高于" if passed else "低于或等于"} 阈值 {threshold}', stock_code=stock_code)

    def _check_price_below(self, params: Dict, stock_code: str) -> EvaluationResult:
        threshold = float(params.get('threshold', 0))
        price = self._get_latest_price(stock_code)
        if price is None:
            return EvaluationResult('price-below', False, current_value='N/A', threshold=threshold, details='获取价格失败', stock_code=stock_code)
        passed = price < threshold
        return EvaluationResult('price-below', passed, current_value=round(price, 2), threshold=threshold,
                                details=f'当前价 {price:.2f} {"低于" if passed else "高于或等于"} 阈值 {threshold}', stock_code=stock_code)

    def _check_price_change_pct(self, params: Dict, stock_code: str) -> EvaluationResult:
        direction = params.get('direction', 'up')  # up/down
        threshold = float(params.get('threshold', 5))  # 百分比
        klines = self._get_klines(stock_code, 2)
        if len(klines) < 2:
            return EvaluationResult('price-change-pct', False, details='数据不足', stock_code=stock_code)
        prev_close = float(klines[-2].get('close', klines[-2].get('c', 0)))
        curr_close = float(klines[-1].get('close', klines[-1].get('c', 0)))
        if prev_close == 0:
            return EvaluationResult('price-change-pct', False, details='前收盘价为0', stock_code=stock_code)
        pct = (curr_close - prev_close) / prev_close * 100
        if direction == 'up':
            passed = pct >= threshold
        else:
            passed = pct <= -threshold
        return EvaluationResult('price-change-pct', passed, current_value=round(pct, 2), threshold=threshold,
                                details=f'涨幅 {pct:.2f}% (阈值: {threshold}%)', stock_code=stock_code)

    def _check_price_break_avg(self, params: Dict, stock_code: str) -> EvaluationResult:
        """价格突破N日均价"""
        period = int(params.get('period', 20))
        klines = self._get_klines(stock_code, period + 5)
        if len(klines) < period:
            return EvaluationResult('price-break-avg', False, details=f'数据不足({len(klines)}<{period})', stock_code=stock_code)
        closes = [float(k.get('close', k.get('c', 0))) for k in klines[-period:]]
        avg_price = sum(closes[:-1]) / (period - 1) if period > 1 else 0
        curr = closes[-1]
        passed = curr > avg_price
        return EvaluationResult('price-break-avg', passed, current_value=round(curr, 2), threshold=round(avg_price, 2),
                                details=f'当前价{curr:.2f} {"突破" if passed else "未突破"} {period}日均价{avg_price:.2f}', stock_code=stock_code)

    def _check_price_above_ma(self, params: Dict, stock_code: str) -> EvaluationResult:
        period = int(params.get('period', 60))
        klines = self._get_klines(stock_code, period + 10)
        if len(klines) < period + 1:
            return EvaluationResult('price-above-ma', False, details=f'数据不足', stock_code=stock_code)
        ma_val = self._get_ma(klines, period)
        curr = float(klines[-1].get('close', klines[-1].get('c', 0)))
        if ma_val is None:
            return EvaluationResult('price-above-ma', False, details='均线计算失败', stock_code=stock_code)
        passed = curr > ma_val
        return EvaluationResult('price-above-ma', passed, current_value=round(curr, 2), threshold=round(ma_val, 2),
                                details=f'当前价{curr:.2f} {"高于" if passed else "低于"} {period}日均线{ma_val:.2f}', stock_code=stock_code)

    # ── 均线类 ──

    def _check_ma_crossover(self, params: Dict, stock_code: str) -> EvaluationResult:
        fast = int(params.get('fast', 5))
        slow = int(params.get('slow', 10))
        direction = params.get('direction', 'golden')  # golden / death
        klines = self._get_klines(stock_code, slow + 10)
        if len(klines) < slow + 2:
            return EvaluationResult('ma-crossover', False, details='数据不足', stock_code=stock_code)
        ma_fast_prev = self._get_ma(klines[:-1], fast)
        ma_slow_prev = self._get_ma(klines[:-1], slow)
        ma_fast_curr = self._get_ma(klines, fast)
        ma_slow_curr = self._get_ma(klines, slow)
        if None in (ma_fast_prev, ma_slow_prev, ma_fast_curr, ma_slow_curr):
            return EvaluationResult('ma-crossover', False, details='均线计算失败', stock_code=stock_code)
        if direction == 'golden':
            passed = ma_fast_prev <= ma_slow_prev and ma_fast_curr > ma_slow_curr
        else:
            passed = ma_fast_prev >= ma_slow_prev and ma_fast_curr < ma_slow_curr
        return EvaluationResult('ma-crossover', passed, current_value=f'{ma_fast_curr:.2f}/{ma_slow_curr:.2f}',
                                threshold=f'MA{fast}/{MA}{slow} {"金叉" if direction=="golden" else "死叉"}',
                                details=f'MA{fast}={ma_fast_curr:.2f}, MA{slow}={ma_slow_curr:.2f}, {"已金叉" if passed and direction=="golden" else "已死叉" if passed else "未交叉"}', stock_code=stock_code)

    def _check_ma_bullish(self, params: Dict, stock_code: str) -> EvaluationResult:
        """均线多头排列: short > mid > long"""
        klines = self._get_klines(stock_code, 130)
        if len(klines) < 120:
            return EvaluationResult('ma-多头排列', False, details='数据不足(需120天)', stock_code=stock_code)
        ma20 = self._get_ma(klines, 20)
        ma60 = self._get_ma(klines, 60)
        ma120 = self._get_ma(klines, 120)
        if None in (ma20, ma60, ma120):
            return EvaluationResult('ma-多头排列', False, details='均线计算失败', stock_code=stock_code)
        passed = ma20 > ma60 > ma120
        return EvaluationResult('ma-多头排列', passed, current_value=f'{ma20:.2f}/{ma60:.2f}/{ma120:.2f}',
                                details=f'MA20={ma20:.2f} MA60={ma60:.2f} MA120={ma120:.2f} {"多头排列" if passed else "非多头排列"}', stock_code=stock_code)

    def _check_ma_bearish(self, params: Dict, stock_code: str) -> EvaluationResult:
        klines = self._get_klines(stock_code, 130)
        if len(klines) < 120:
            return EvaluationResult('ma-空头排列', False, details='数据不足', stock_code=stock_code)
        ma20 = self._get_ma(klines, 20)
        ma60 = self._get_ma(klines, 60)
        ma120 = self._get_ma(klines, 120)
        if None in (ma20, ma60, ma120):
            return EvaluationResult('ma-空头排列', False, details='均线计算失败', stock_code=stock_code)
        passed = ma20 < ma60 < ma120
        return EvaluationResult('ma-空头排列', passed, current_value=f'{ma20:.2f}/{ma60:.2f}/{ma120:.2f}',
                                details=f'MA20={ma20:.2f} MA60={ma60:.2f} MA120={ma120:.2f} {"空头排列" if passed else "非空头排列"}', stock_code=stock_code)

    def _check_ma60_breakthrough(self, params: Dict, stock_code: str) -> EvaluationResult:
        klines = self._get_klines(stock_code, 70)
        if len(klines) < 61:
            return EvaluationResult('ma60-突破', False, details='数据不足', stock_code=stock_code)
        ma60 = self._get_ma(klines, 60)
        curr = float(klines[-1].get('close', klines[-1].get('c', 0)))
        prev = float(klines[-2].get('close', klines[-2].get('c', 0)))
        if ma60 is None:
            return EvaluationResult('ma60-突破', False, details='均线计算失败', stock_code=stock_code)
        passed = prev <= ma60 and curr > ma60
        vol_mult = float(params.get('vol_multiplier', 1.5))
        # 成交量验证
        vols = [float(k.get('vol', k.get('v', 0))) for k in klines[-5:]]
        if vols and vol_mult > 1:
            avg_vol = sum(vols[:-1]) / max(len(vols[:-1]), 1)
            curr_vol = vols[-1]
            passed = passed and (curr_vol >= avg_vol * vol_mult)
        return EvaluationResult('ma60-突破', passed, current_value=round(curr, 2), threshold=round(ma60, 2),
                                details=f'MA60={ma60:.2f} 当前价{curr:.2f} {"放量突破" if passed else "突破失败(量能不足)" if curr > ma60 else "未突破"}', stock_code=stock_code)

    def _check_ma20_support(self, params: Dict, stock_code: str) -> EvaluationResult:
        klines = self._get_klines(stock_code, 30)
        if len(klines) < 21:
            return EvaluationResult('ma20-支撑', False, details='数据不足', stock_code=stock_code)
        ma20 = self._get_ma(klines, 20)
        curr = float(klines[-1].get('close', klines[-1].get('c', 0)))
        low = float(klines[-1].get('low', klines[-1].get('l', 0)))
        if ma20 is None:
            return EvaluationResult('ma20-支撑', False, details='均线计算失败', stock_code=stock_code)
        touch_pct = abs(low - ma20) / ma20 * 100
        passed = touch_pct < 0.5 and curr > ma20
        return EvaluationResult('ma20-支撑', passed, current_value=f'@{round(low,2)}', threshold=round(ma20, 2),
                                details=f'MA20={ma20:.2f} 最低{low:.2f} 偏离{touch_pct:.2f}% {"支撑有效" if passed else "未触及支撑"}', stock_code=stock_code)

    def _check_ma120_resistance(self, params: Dict, stock_code: str) -> EvaluationResult:
        klines = self._get_klines(stock_code, 130)
        if len(klines) < 121:
            return EvaluationResult('ma120-压力', False, details='数据不足', stock_code=stock_code)
        ma120 = self._get_ma(klines, 120)
        curr = float(klines[-1].get('close', klines[-1].get('c', 0)))
        high = float(klines[-1].get('high', klines[-1].get('h', 0)))
        if ma120 is None:
            return EvaluationResult('ma120-压力', False, details='均线计算失败', stock_code=stock_code)
        touch_pct = (ma120 - curr) / ma120 * 100
        passed = 0 <= touch_pct < 1
        return EvaluationResult('ma120-压力', passed, current_value=f'H{round(high,2)}', threshold=round(ma120, 2),
                                details=f'MA120={ma120:.2f} 当前价{curr:.2f} 偏离{touch_pct:.2f}% {"接近压力" if passed else "远离压力位"}', stock_code=stock_code)

    def _check_ma_golden_cross(self, params: Dict, stock_code: str) -> EvaluationResult:
        """三线开花: 短线上穿中线，中线上穿长线"""
        klines = self._get_klines(stock_code, 130)
        if len(klines) < 121:
            return EvaluationResult('ma-三线开花', False, details='数据不足', stock_code=stock_code)
        ma5 = self._get_ma(klines, 5)
        ma10_prev = self._get_ma(klines[:-1], 10)
        ma10_curr = self._get_ma(klines, 10)
        ma20_prev = self._get_ma(klines[:-1], 20)
        ma20_curr = self._get_ma(klines, 20)
        if None in (ma5, ma10_prev, ma10_curr, ma20_prev, ma20_curr):
            return EvaluationResult('ma-三线开花', False, details='均线计算失败', stock_code=stock_code)
        cross1 = ma5 > ma10_curr and ma10_curr > ma20_curr
        cross2 = ma10_prev <= ma20_prev and ma10_curr > ma20_curr
        passed = cross1 and cross2
        return EvaluationResult('ma-三线开花', passed, current_value=f'{ma5:.2f}/{ma10_curr:.2f}/{ma20_curr:.2f}',
                                details=f'MA5={ma5:.2f} MA10={ma10_curr:.2f} MA20={ma20_curr:.2f} {"三线开花" if passed else "未形成"}', stock_code=stock_code)

    def _check_ma_buy1(self, params: Dict, stock_code: str) -> EvaluationResult:
        """格兰维尔买1: MA走平向上+价格上穿MA"""
        klines = self._get_klines(stock_code, 30)
        if len(klines) < 25:
            return EvaluationResult('ma-格兰维尔-买1', False, details='数据不足', stock_code=stock_code)
        ma20_prev = self._get_ma(klines[:-5], 20)
        ma20_curr = self._get_ma(klines, 20)
        curr = float(klines[-1].get('close', klines[-1].get('c', 0)))
        prev = float(klines[-2].get('close', klines[-2].get('c', 0)))
        if None in (ma20_prev, ma20_curr):
            return EvaluationResult('ma-格兰维尔-买1', False, details='均线计算失败', stock_code=stock_code)
        ma_flat = abs(ma20_curr - ma20_prev) / max(ma20_prev, 0.01) < 0.03
        crossover = prev <= ma20_curr and curr > ma20_curr
        passed = ma_flat and crossover
        return EvaluationResult('ma-格兰维尔-买1', passed, current_value=round(curr, 2), threshold=round(ma20_curr, 2),
                                details=f'MA20={ma20_curr:.2f} {"均线走平" if ma_flat else "均线下行"} {"上穿成功" if crossover else "未上穿"}', stock_code=stock_code)

    def _check_ma_buy2(self, params: Dict, stock_code: str) -> EvaluationResult:
        """格兰维尔买2: 价格在MA上方，回调不破MA"""
        klines = self._get_klines(stock_code, 30)
        if len(klines) < 25:
            return EvaluationResult('ma-格兰维尔-买2', False, details='数据不足', stock_code=stock_code)
        ma20 = self._get_ma(klines, 20)
        closes = [float(k.get('close', k.get('c', 0))) for k in klines[-10:]]
        lows = [float(k.get('low', k.get('l', 0))) for k in klines[-10:]]
        if ma20 is None:
            return EvaluationResult('ma-格兰维尔-买2', False, details='均线计算失败', stock_code=stock_code)
        above_ma = all(c > ma20 for c in closes[-5:])
        touch_but_not_break = min(lows[-5:]) >= ma20 * 0.98
        passed = above_ma and touch_but_not_break
        return EvaluationResult('ma-格兰维尔-买2', passed, current_value=f'{closes[-1]:.2f}', threshold=round(ma20, 2),
                                details=f'MA20={ma20:.2f} 近5日最低{min(lows[-5:]):.2f} {"回调不破MA20" if passed else "跌破MA20"}', stock_code=stock_code)

    # ── 量能类 ──

    def _get_volumes(self, klines: List[Dict]) -> List[float]:
        return [float(k.get('vol', k.get('v', 0))) for k in klines]

    def _check_vol_surge(self, params: Dict, stock_code: str) -> EvaluationResult:
        multiplier = float(params.get('multiplier', 2))
        period = int(params.get('period', 20))
        klines = self._get_klines(stock_code, period + 5)
        if len(klines) < period + 1:
            return EvaluationResult('vol-surge', False, details=f'数据不足({len(klines)}<{period+1})', stock_code=stock_code)
        vols = self._get_volumes(klines)
        avg_vol = sum(vols[-(period+1):-1]) / period
        curr_vol = vols[-1]
        if avg_vol == 0:
            return EvaluationResult('vol-surge', False, details='均量为0', stock_code=stock_code)
        ratio = curr_vol / avg_vol
        passed = ratio >= multiplier
        return EvaluationResult('vol-surge', passed, current_value=f'{ratio:.2f}x', threshold=f'{multiplier}x',
                                details=f'今日量{curr_vol:.0f} {period}日均量{avg_vol:.0f} 量比{ratio:.2f} {"放大" if passed else "未达标"}', stock_code=stock_code)

    def _check_vol_shrink(self, params: Dict, stock_code: str) -> EvaluationResult:
        pct = float(params.get('pct', 50))
        period = int(params.get('period', 20))
        klines = self._get_klines(stock_code, period + 5)
        if len(klines) < period + 1:
            return EvaluationResult('vol-shrink', False, details='数据不足', stock_code=stock_code)
        vols = self._get_volumes(klines)
        avg_vol = sum(vols[-(period+1):-1]) / period
        curr_vol = vols[-1]
        if avg_vol == 0:
            return EvaluationResult('vol-shrink', False, details='均量为0', stock_code=stock_code)
        ratio = curr_vol / avg_vol * 100
        passed = ratio <= pct
        return EvaluationResult('vol-shrink', passed, current_value=f'{ratio:.1f}%', threshold=f'{pct}%',
                                details=f'今日量{curr_vol:.0f} = {period}日均量的{ratio:.1f}% (阈值≤{pct}%)', stock_code=stock_code)

    def _check_vol_breakthrough(self, params: Dict, stock_code: str) -> EvaluationResult:
        """放量突破: 成交量放大+价格突破"""
        multiplier = float(params.get('multiplier', 1.5))
        period = int(params.get('period', 20))
        klines = self._get_klines(stock_code, period + 5)
        if len(klines) < period + 2:
            return EvaluationResult('vol-放量突破', False, details='数据不足', stock_code=stock_code)
        vols = self._get_volumes(klines)
        closes = [float(k.get('close', k.get('c', 0))) for k in klines]
        avg_vol = sum(vols[-(period+2):-1]) / (period + 1)
        curr_vol = vols[-1]
        ratio = curr_vol / max(avg_vol, 1)
        high_20 = max(closes[-(period+1):-1])
        curr = closes[-1]
        passed = ratio >= multiplier and curr > high_20
        return EvaluationResult('vol-放量突破', passed, current_value=f'量比{ratio:.1f}x价{curr:.2f}',
                                details=f'量比{ratio:.1f}x 价格{curr:.2f} {"放量突破" if passed else f"未突破{high_20:.2f}" if curr<high_20 else "量能不足"}', stock_code=stock_code)

    def _check_vol_pullback(self, params: Dict, stock_code: str) -> EvaluationResult:
        """缩量回调: 缩量+价格回调但未破趋势"""
        period = int(params.get('period', 20))
        shrink_pct = float(params.get('shrink_pct', 50))
        klines = self._get_klines(stock_code, period + 5)
        if len(klines) < period + 2:
            return EvaluationResult('vol-缩量回调', False, details='数据不足', stock_code=stock_code)
        vols = self._get_volumes(klines)
        avg_vol = sum(vols[-(period+2):-1]) / (period + 1)
        curr_vol = vols[-1]
        ratio = curr_vol / max(avg_vol, 1) * 100
        closes = [float(k.get('close', k.get('c', 0))) for k in klines]
        high_20 = max(closes[-(period+2):-1])
        curr = closes[-1]
        passed = ratio <= shrink_pct and curr < high_20
        return EvaluationResult('vol-缩量回调', passed, current_value=f'量{ratio:.1f}%价{curr:.2f}',
                                details=f'量比{ratio:.1f}% 回调至{curr:.2f} {"缩量回调" if passed else "非典型缩量回调"}', stock_code=stock_code)

    def _check_vol_gentle_increase(self, params: Dict, stock_code: str) -> EvaluationResult:
        """温和放量: 连续3日量递增"""
        klines = self._get_klines(stock_code, 10)
        if len(klines) < 5:
            return EvaluationResult('vol-温和放量', False, details='数据不足', stock_code=stock_code)
        vols = self._get_volumes(klines)
        if len(vols) < 4:
            return EvaluationResult('vol-温和放量', False, details='数据不足', stock_code=stock_code)
        passed = vols[-4] < vols[-3] < vols[-2] < vols[-1]
        return EvaluationResult('vol-温和放量', passed, current_value=f'{[round(v,0) for v in vols[-4:]]}',
                                details=f'连续{"递增" if passed else "非递增"}', stock_code=stock_code)

    # ── MACD ──

    def _calc_macd(self, closes: List[float], fast=12, slow=26, signal=9):
        """简化MACD计算"""
        ema_fast = self._ema(closes, fast)
        ema_slow = self._ema(closes, slow)
        dif = [e - s for e, s in zip(ema_fast, ema_slow)]
        dea = self._ema(dif, signal)
        hist = [d - e for d, e in zip(dif, dea)]
        return dif, dea, hist

    def _ema(self, data: List[float], period: int) -> List[float]:
        if len(data) < period:
            return []
        result = [sum(data[:period]) / period]
        multiplier = 2 / (period + 1)
        for i in range(period, len(data)):
            result.append((data[i] - result[-1]) * multiplier + result[-1])
        return result

    def _check_macd_golden_cross(self, params: Dict, stock_code: str) -> EvaluationResult:
        klines = self._get_klines(stock_code, 40)
        if len(klines) < 30:
            return EvaluationResult('macd-golden-cross', False, details='数据不足', stock_code=stock_code)
        closes = [float(k.get('close', k.get('c', 0))) for k in klines]
        dif, dea, _ = self._calc_macd(closes)
        if len(dif) < 2 or len(dea) < 2:
            return EvaluationResult('macd-golden-cross', False, details='MACD计算失败', stock_code=stock_code)
        passed = dif[-2] <= dea[-2] and dif[-1] > dea[-1]
        return EvaluationResult('macd-golden-cross', passed, current_value=f'DIF={dif[-1]:.3f} DEA={dea[-1]:.3f}',
                                details=f'DIF={dif[-1]:.3f} DEA={dea[-1]:.3f} {"已金叉" if passed else "未金叉"}', stock_code=stock_code)

    def _check_macd_death_cross(self, params: Dict, stock_code: str) -> EvaluationResult:
        klines = self._get_klines(stock_code, 40)
        if len(klines) < 30:
            return EvaluationResult('macd-death-cross', False, details='数据不足', stock_code=stock_code)
        closes = [float(k.get('close', k.get('c', 0))) for k in klines]
        dif, dea, _ = self._calc_macd(closes)
        if len(dif) < 2 or len(dea) < 2:
            return EvaluationResult('macd-death-cross', False, details='MACD计算失败', stock_code=stock_code)
        passed = dif[-2] >= dea[-2] and dif[-1] < dea[-1]
        return EvaluationResult('macd-death-cross', passed, current_value=f'DIF={dif[-1]:.3f} DEA={dea[-1]:.3f}',
                                details=f'DIF={dif[-1]:.3f} DEA={dea[-1]:.3f} {"已死叉" if passed else "未死叉"}', stock_code=stock_code)

    def _check_macd_above_zero_golden(self, params: Dict, stock_code: str) -> EvaluationResult:
        klines = self._get_klines(stock_code, 40)
        if len(klines) < 30:
            return EvaluationResult('macd-水上金叉', False, details='数据不足', stock_code=stock_code)
        closes = [float(k.get('close', k.get('c', 0))) for k in klines]
        dif, dea, _ = self._calc_macd(closes)
        if len(dif) < 3 or len(dea) < 3:
            return EvaluationResult('macd-水上金叉', False, details='MACD计算失败', stock_code=stock_code)
        cross = dif[-2] <= dea[-2] and dif[-1] > dea[-1]
        above_zero = dif[-1] > 0 and dea[-1] > 0
        passed = cross and above_zero
        return EvaluationResult('macd-水上金叉', passed, current_value=f'DIF={dif[-1]:.3f} DEA={dea[-1]:.3f}',
                                details=f'DIF={dif[-1]:.3f} DEA={dea[-1]:.3f} {"水上金叉" if passed else "非水上金叉"}', stock_code=stock_code)

    def _check_macd_bullish_divergence(self, params: Dict, stock_code: str) -> EvaluationResult:
        """MACD底背离: 价格新低+MACD不创新低"""
        klines = self._get_klines(stock_code, 60)
        if len(klines) < 50:
            return EvaluationResult('macd-底背离', False, details='数据不足', stock_code=stock_code)
        closes = [float(k.get('close', k.get('c', 0))) for k in klines]
        dif, _, _ = self._calc_macd(closes)
        if len(closes) < 20 or len(dif) < 20:
            return EvaluationResult('macd-底背离', False, details='MACD计算失败', stock_code=stock_code)
        # 比较最近20根K线
        p_low_20 = min(closes[-20:])
        p_low_10 = min(closes[-10:])
        macd_low_20 = min(dif[-20:])
        macd_low_10 = min(dif[-10:])
        passed = p_low_10 < p_low_20 and macd_low_10 > macd_low_20
        return EvaluationResult('macd-底背离', passed, current_value=f'价低{p_low_10:.2f}',
                                details=f'{"底背离" if passed else "未背离"} 价格新低{p_low_10:.2f}<{p_low_20:.2f} MACD低{m月下旬low_10:.3f}>{macd_low_20:.3f}' if passed else '',
                                stock_code=stock_code)

    def _check_macd_bearish_divergence(self, params: Dict, stock_code: str) -> EvaluationResult:
        klines = self._get_klines(stock_code, 60)
        if len(klines) < 50:
            return EvaluationResult('macd-顶背离', False, details='数据不足', stock_code=stock_code)
        closes = [float(k.get('close', k.get('c', 0))) for k in klines]
        dif, _, _ = self._calc_macd(closes)
        if len(closes) < 20 or len(dif) < 20:
            return EvaluationResult('macd-顶背离', False, details='MACD计算失败', stock_code=stock_code)
        p_high_20 = max(closes[-20:])
        p_high_10 = max(closes[-10:])
        macd_high_20 = max(dif[-20:])
        macd_high_10 = max(dif[-10:])
        passed = p_high_10 > p_high_20 and macd_high_10 < macd_high_20
        return EvaluationResult('macd-顶背离', passed, current_value=f'价高{p_high_10:.2f}',
                                details=f'{"顶背离" if passed else "未背离"}', stock_code=stock_code)

    # ── KDJ ──

    def _calc_kdj(self, klines: List[Dict], period=9):
        highs = [float(k.get('high', k.get('h', 0))) for k in klines]
        lows = [float(k.get('low', k.get('l', 0))) for k in klines]
        closes = [float(k.get('close', k.get('c', 0))) for k in klines]
        if len(highs) < period:
            return None, None, None
        hh = []
        ll = []
        for i in range(len(highs)):
            start = max(0, i - period + 1)
            window_h = highs[start:i + 1]
            window_l = lows[start:i + 1]
            hh.append(max(window_h))
            ll.append(min(window_l))
        rsv_n = []
        for i in range(len(closes)):
            if hh[i] == ll[i]:
                rsv_n.append(50)
            else:
                rsv_n.append((closes[i] - ll[i]) / (hh[i] - ll[i]) * 100)
        k_vals = [50]
        for r in rsv_n:
            k_vals.append(2 / 3 * k_vals[-1] + 1 / 3 * r)
        k_vals = k_vals[1:]
        d_vals = [50]
        for k in k_vals:
            d_vals.append(2 / 3 * d_vals[-1] + 1 / 3 * k)
        d_vals = d_vals[1:]
        j_vals = [3 * k - 2 * d for k, d in zip(k_vals, d_vals)]
        return k_vals, d_vals, j_vals

    def _check_kdj_overbought(self, params: Dict, stock_code: str) -> EvaluationResult:
        threshold = float(params.get('threshold', 80))
        klines = self._get_klines(stock_code, 15)
        if len(klines) < 10:
            return EvaluationResult('kdj-overbought', False, details='数据不足', stock_code=stock_code)
        _, _, j = self._calc_kdj(klines)
        if not j:
            return EvaluationResult('kdj-overbought', False, details='KDJ计算失败', stock_code=stock_code)
        passed = j[-1] > threshold
        return EvaluationResult('kdj-overbought', passed, current_value=round(j[-1], 1), threshold=threshold,
                                details=f'K={j[-1]:.1f} {"超买" if passed else "正常"}', stock_code=stock_code)

    def _check_kdj_oversold(self, params: Dict, stock_code: str) -> EvaluationResult:
        threshold = float(params.get('threshold', 20))
        klines = self._get_klines(stock_code, 15)
        if len(klines) < 10:
            return EvaluationResult('kdj-oversold', False, details='数据不足', stock_code=stock_code)
        _, _, j = self._calc_kdj(klines)
        if not j:
            return EvaluationResult('kdj-oversold', False, details='KDJ计算失败', stock_code=stock_code)
        passed = j[-1] < threshold
        return EvaluationResult('kdj-oversold', passed, current_value=round(j[-1], 1), threshold=threshold,
                                details=f'J={j[-1]:.1f} {"超卖" if passed else "正常"}', stock_code=stock_code)

    def _check_kdj_golden_cross(self, params: Dict, stock_code: str) -> EvaluationResult:
        klines = self._get_klines(stock_code, 15)
        if len(klines) < 12:
            return EvaluationResult('kdj-golden-cross', False, details='数据不足', stock_code=stock_code)
        k, d, j = self._calc_kdj(klines)
        if not k or not d:
            return EvaluationResult('kdj-golden-cross', False, details='KDJ计算失败', stock_code=stock_code)
        idx = -1
        passed = len(k) >= 2 and k[-2] <= d[-2] and k[-1] > d[-1]
        return EvaluationResult('kdj-golden-cross', passed, current_value=f'K={k[-1]:.1f} D={d[-1]:.1f}',
                                details=f'K{k[-1]:.1f} D{d[-1]:.1f} J{j[-1]:.1f} {"已金叉" if passed else "未金叉"}', stock_code=stock_code)

    # ── RSI ──

    def _calc_rsi(self, closes: List[float], period=14) -> List[float]:
        if len(closes) < period + 1:
            return []
        gains, losses = 0, 0
        for i in range(1, period + 1):
            diff = closes[i] - closes[i - 1]
            gains += max(diff, 0)
            losses += max(-diff, 0)
        rsis = []
        for i in range(period, len(closes)):
            if i > period:
                diff = closes[i] - closes[i - 1]
                gains = gains * (period - 1) / period + max(diff, 0)
                losses = losses * (period - 1) / period + max(-diff, 0)
            rs = gains / max(losses, 0.001)
            rsis.append(100 - 100 / (1 + rs))
        return rsis

    def _check_rsi_overbought(self, params: Dict, stock_code: str) -> EvaluationResult:
        threshold = float(params.get('threshold', 70))
        period = int(params.get('period', 14))
        klines = self._get_klines(stock_code, period + 5)
        if len(klines) < period + 1:
            return EvaluationResult('rsi-overbought', False, details='数据不足', stock_code=stock_code)
        closes = [float(k.get('close', k.get('c', 0))) for k in klines]
        rsis = self._calc_rsi(closes, period)
        if not rsis:
            return EvaluationResult('rsi-overbought', False, details='RSI计算失败', stock_code=stock_code)
        passed = rsis[-1] > threshold
        return EvaluationResult('rsi-overbought', passed, current_value=round(rsis[-1], 1), threshold=threshold,
                                details=f'RSI={rsis[-1]:.1f} {"超买" if passed else "正常"}', stock_code=stock_code)

    def _check_rsi_oversold(self, params: Dict, stock_code: str) -> EvaluationResult:
        threshold = float(params.get('threshold', 30))
        period = int(params.get('period', 14))
        klines = self._get_klines(stock_code, period + 5)
        if len(klines) < period + 1:
            return EvaluationResult('rsi-oversold', False, details='数据不足', stock_code=stock_code)
        closes = [float(k.get('close', k.get('c', 0))) for k in klines]
        rsis = self._calc_rsi(closes, period)
        if not rsis:
            return EvaluationResult('rsi-oversold', False, details='RSI计算失败', stock_code=stock_code)
        passed = rsis[-1] < threshold
        return EvaluationResult('rsi-oversold', passed, current_value=round(rsis[-1], 1), threshold=threshold,
                                details=f'RSI={rsis[-1]:.1f} {"超卖" if passed else "正常"}', stock_code=stock_code)

    def _check_rsi_breakthrough(self, params: Dict, stock_code: str) -> EvaluationResult:
        """RSI突破50中轴"""
        direction = params.get('direction', 'up')
        period = int(params.get('period', 14))
        klines = self._get_klines(stock_code, period + 5)
        if len(klines) < period + 2:
            return EvaluationResult('rsi-突破', False, details='数据不足', stock_code=stock_code)
        closes = [float(k.get('close', k.get('c', 0))) for k in klines]
        rsis = self._calc_rsi(closes, period)
        if not rsis or len(rsis) < 2:
            return EvaluationResult('rsi-突破', False, details='RSI计算失败', stock_code=stock_code)
        if direction == 'up':
            passed = rsis[-2] <= 50 < rsis[-1]
        else:
            passed = rsis[-2] >= 50 > rsis[-1]
        return EvaluationResult('rsi-突破', passed, current_value=round(rsis[-1], 1),
                                details=f'RSI={rsis[-1]:.1f} {"上穿" if direction=="up" else "下穿"}50 {"已突破" if passed else "未突破"}', stock_code=stock_code)

    # ── BOLL ──

    def _calc_boll(self, klines: List[Dict], period=20, multiplier=2):
        closes = [float(k.get('close', k.get('c', 0))) for k in klines[-period:]]
        if len(closes) < period:
            return None, None, None
        mid = sum(closes) / period
        variance = sum((c - mid) ** 2 for c in closes) / period
        std = variance ** 0.5
        upper = mid + multiplier * std
        lower = mid - multiplier * std
        return upper, mid, lower

    def _check_boll_upper_break(self, params: Dict, stock_code: str) -> EvaluationResult:
        klines = self._get_klines(stock_code, 25)
        if len(klines) < 20:
            return EvaluationResult('boll-突破上轨', False, details='数据不足', stock_code=stock_code)
        upper, mid, _ = self._calc_boll(klines)
        if upper is None:
            return EvaluationResult('boll-突破上轨', False, details='BOLL计算失败', stock_code=stock_code)
        curr = float(klines[-1].get('close', klines[-1].get('c', 0)))
        passed = curr >= upper
        return EvaluationResult('boll-突破上轨', passed, current_value=round(curr, 2), threshold=round(upper, 2),
                                details=f'当前价{curr:.2f} 上轨{upper:.2f} {"突破上轨" if passed else "未突破"}', stock_code=stock_code)

    def _check_boll_lower_break(self, params: Dict, stock_code: str) -> EvaluationResult:
        klines = self._get_klines(stock_code, 25)
        if len(klines) < 20:
            return EvaluationResult('boll-跌破下轨', False, details='数据不足', stock_code=stock_code)
        _, _, lower = self._calc_boll(klines)
        if lower is None:
            return EvaluationResult('boll-跌破下轨', False, details='BOLL计算失败', stock_code=stock_code)
        curr = float(klines[-1].get('close', klines[-1].get('c', 0)))
        passed = curr <= lower
        return EvaluationResult('boll-跌破下轨', passed, current_value=round(curr, 2), threshold=round(lower, 2),
                                details=f'当前价{curr:.2f} 下轨{lower:.2f} {"跌破下轨" if passed else "未跌破"}', stock_code=stock_code)

    def _check_boll_mid_support(self, params: Dict, stock_code: str) -> EvaluationResult:
        klines = self._get_klines(stock_code, 25)
        if len(klines) < 20:
            return EvaluationResult('boll-中轨支撑', False, details='数据不足', stock_code=stock_code)
        _, mid, _ = self._calc_boll(klines)
        if mid is None:
            return EvaluationResult('boll-中轨支撑', False, details='BOLL计算失败', stock_code=stock_code)
        curr = float(klines[-1].get('close', klines[-1].get('c', 0)))
        low = float(klines[-1].get('low', klines[-1].get('l', 0)))
        bounce = low <= mid and curr > mid
        passed = bounce
        return EvaluationResult('boll-中轨支撑', passed, current_value=round(curr, 2), threshold=round(mid, 2),
                                details=f'中轨{mid:.2f} 最低{low:.2f} {"获支撑反弹" if passed else "未触及"}', stock_code=stock_code)

    # ── 资金流向 ──

    def _get_moneyflow(self, stock_code: str) -> Optional[Dict]:
        try:
            from app.data.data_source_manager import data_source_manager as dsm
            result = dsm.get_data('get_moneyflow', {
                'ts_code': stock_code,
                'trade_date': datetime.now().strftime('%Y%m%d'),
            })
            if result and isinstance(result, list) and len(result) > 0:
                return result[0]
        except Exception:
            pass
        return None

    def _check_moneyflow_net_inflow(self, params: Dict, stock_code: str) -> EvaluationResult:
        min_amount = float(params.get('min_amount', 0))
        mf = self._get_moneyflow(stock_code)
        if not mf:
            return EvaluationResult('moneyflow-主力净流入', False, details='资金流向数据不可用', stock_code=stock_code)
        net_amount = float(mf.get('net_mf_amount', mf.get('net_amount', 0)))
        passed = net_amount > min_amount
        return EvaluationResult('moneyflow-主力净流入', passed, current_value=f'{net_amount/1e8:.2f}亿', threshold=f'{min_amount/1e8:.2f}亿',
                                details=f'主力净流入{net_amount/1e8:.2f}亿 {"达标" if passed else "未达标"}', stock_code=stock_code)

    def _check_moneyflow_net_outflow(self, params: Dict, stock_code: str) -> EvaluationResult:
        max_amount = float(params.get('max_amount', 0))
        mf = self._get_moneyflow(stock_code)
        if not mf:
            return EvaluationResult('moneyflow-主力净流出', False, details='资金流向数据不可用', stock_code=stock_code)
        net_amount = float(mf.get('net_mf_amount', mf.get('net_amount', 0)))
        passed = net_amount < -max_amount
        return EvaluationResult('moneyflow-主力净流出', passed, current_value=f'{net_amount/1e8:.2f}亿', threshold=f'-{max_amount/1e8:.2f}亿',
                                details=f'主力净流入{net_amount/1e8:.2f}亿 {"净流出" if passed else "未达流出阈值"}', stock_code=stock_code)

    def _check_moneyflow_retail_inflow(self, params: Dict, stock_code: str) -> EvaluationResult:
        threshold = float(params.get('threshold', 0))
        mf = self._get_moneyflow(stock_code)
        if not mf:
            return EvaluationResult('moneyflow-散户净流入', False, details='资金流向数据不可用', stock_code=stock_code)
        retail = float(mf.get('buy_sm_vol', 0)) - float(mf.get('sell_sm_vol', 0))
        passed = retail > threshold
        return EvaluationResult('moneyflow-散户净流入', passed, current_value=f'{retail:.0f}', threshold=threshold,
                                details=f'散户净流入{retail:.0f}', stock_code=stock_code)

    def _check_moneyflow_big_order_pct(self, params: Dict, stock_code: str) -> EvaluationResult:
        min_pct = float(params.get('min_pct', 30))
        mf = self._get_moneyflow(stock_code)
        if not mf:
            return EvaluationResult('moneyflow-大单占比', False, details='资金流向数据不可用', stock_code=stock_code)
        buy_lg = float(mf.get('buy_lg_vol', 0))
        buy_elg = float(mf.get('buy_elg_vol', 0))
        total_buy = buy_lg + buy_elg
        total = sum(float(mf.get(k, 0)) for k in ['buy_lg_vol', 'buy_elg_vol', 'buy_md_vol', 'buy_sm_vol',
                                                     'sell_lg_vol', 'sell_elg_vol', 'sell_md_vol', 'sell_sm_vol'])
        if total == 0:
            return EvaluationResult('moneyflow-大单占比', False, details='无成交数据', stock_code=stock_code)
        pct = total_buy / total * 100
        passed = pct >= min_pct
        return EvaluationResult('moneyflow-大单占比', passed, current_value=f'{pct:.1f}%', threshold=f'{min_pct}%',
                                details=f'大单买入占比{pct:.1f}% {"达标" if passed else "未达标"}', stock_code=stock_code)

    # ── 形态类 ──

    def _check_pattern_limit_up(self, params: Dict, stock_code: str) -> EvaluationResult:
        klines = self._get_klines(stock_code, 2)
        if len(klines) < 2:
            return EvaluationResult('pattern-涨停', False, details='数据不足', stock_code=stock_code)
        pct = self._daily_pct(klines[-1])
        passed = pct is not None and pct >= 9.8
        return EvaluationResult('pattern-涨停', passed, current_value=f'{pct:.2f}%' if pct else 'N/A',
                                details=f'今日涨幅{"已涨停" if passed else f"{pct:.2f}%" if pct else "N/A"}', stock_code=stock_code)

    def _check_pattern_limit_down(self, params: Dict, stock_code: str) -> EvaluationResult:
        klines = self._get_klines(stock_code, 2)
        if len(klines) < 2:
            return EvaluationResult('pattern-跌停', False, details='数据不足', stock_code=stock_code)
        pct = self._daily_pct(klines[-1])
        passed = pct is not None and pct <= -9.8
        return EvaluationResult('pattern-跌停', passed, current_value=f'{pct:.2f}%' if pct else 'N/A',
                                details=f'今日涨幅{"已跌停" if passed else f"{pct:.2f}%" if pct else "N/A"}', stock_code=stock_code)

    def _check_pattern_long_bullish(self, params: Dict, stock_code: str) -> EvaluationResult:
        min_pct = float(params.get('min_pct', 5))
        klines = self._get_klines(stock_code, 2)
        if len(klines) < 2:
            return EvaluationResult('pattern-长阳', False, details='数据不足', stock_code=stock_code)
        k = klines[-1]
        o, c = float(k.get('open', k.get('o', 0))), float(k.get('close', k.get('c', 0)))
        pct = self._daily_pct(k)
        if c <= o or pct is None:
            return EvaluationResult('pattern-长阳', False, current_value=f'{pct:.2f}%' if pct else 'N/A', stock_code=stock_code)
        passed = pct >= min_pct
        return EvaluationResult('pattern-长阳', passed, current_value=f'{pct:.2f}%', details=f'涨幅{pct:.2f}% {"长阳线" if passed else "非长阳"}', stock_code=stock_code)

    def _check_pattern_long_bearish(self, params: Dict, stock_code: str) -> EvaluationResult:
        min_pct = float(params.get('min_pct', 5))
        klines = self._get_klines(stock_code, 2)
        if len(klines) < 2:
            return EvaluationResult('pattern-长阴', False, details='数据不足', stock_code=stock_code)
        k = klines[-1]
        o, c = float(k.get('open', k.get('o', 0))), float(k.get('close', k.get('c', 0)))
        pct = self._daily_pct(k)
        if c >= o or pct is None:
            return EvaluationResult('pattern-长阴', False, current_value=f'{pct:.2f}%' if pct else 'N/A', stock_code=stock_code)
        passed = pct <= -min_pct
        return EvaluationResult('pattern-长阴', passed, current_value=f'{pct:.2f}%', details=f'跌幅{pct:.2f}% {"长阴线" if passed else "非长阴"}', stock_code=stock_code)

    def _check_pattern_doji(self, params: Dict, stock_code: str) -> EvaluationResult:
        klines = self._get_klines(stock_code, 2)
        if not klines:
            return EvaluationResult('pattern-十字星', False, details='数据不足', stock_code=stock_code)
        k = klines[-1]
        o, c, h, l = float(k.get('open', k.get('o', 0))), float(k.get('close', k.get('c', 0))), float(k.get('high', k.get('h', 0))), float(k.get('low', k.get('l', 0)))
        body = abs(c - o)
        shadow = h - l
        passed = shadow > 0 and body / shadow < 0.1
        return EvaluationResult('pattern-十字星', passed, current_value=f'实体{body:.2f}', details=f'{"十字星" if passed else "非十字星"}(实体/影线={body/shadow:.2f})' if shadow > 0 else '',
                                stock_code=stock_code)

    def _check_pattern_hammer(self, params: Dict, stock_code: str) -> EvaluationResult:
        klines = self._get_klines(stock_code, 2)
        if not klines:
            return EvaluationResult('pattern-锤头线', False, details='数据不足', stock_code=stock_code)
        k = klines[-1]
        o, c, h, l = float(k.get('open', k.get('o', 0))), float(k.get('close', k.get('c', 0))), float(k.get('high', k.get('h', 0))), float(k.get('low', k.get('l', 0)))
        body = abs(c - o)
        lower_shadow = min(o, c) - l
        upper_shadow = h - max(o, c)
        passed = body > 0 and lower_shadow >= 2 * body and upper_shadow <= body * 0.3
        return EvaluationResult('pattern-锤头线', passed, details=f'{"锤头线" if passed else "非锤头"}(下影{lower_shadow:.2f}实体{body:.2f})', stock_code=stock_code)

    def _check_pattern_hanging_man(self, params: Dict, stock_code: str) -> EvaluationResult:
        klines = self._get_klines(stock_code, 2)
        if not klines:
            return EvaluationResult('pattern-吊颈线', False, details='数据不足', stock_code=stock_code)
        k = klines[-1]
        o, c, h, l = float(k.get('open', k.get('o', 0))), float(k.get('close', k.get('c', 0))), float(k.get('high', k.get('h', 0))), float(k.get('low', k.get('l', 0)))
        body = abs(c - o)
        lower_shadow = min(o, c) - l
        upper_shadow = h - max(o, c)
        passed = body > 0 and lower_shadow >= 2 * body and upper_shadow <= body * 0.3 and c < closes[-5] if (closes := [float(kl.get('close', kl.get('c', 0))) for kl in klines]) else False
        # 简化：不加前5日比较了
        if not klines:
            return EvaluationResult('pattern-吊颈线', False, stock_code=stock_code)
        return EvaluationResult('pattern-吊颈线', passed, details=f'{"吊颈线" if passed else "非吊颈"}', stock_code=stock_code)

    def _daily_pct(self, kline: Dict) -> Optional[float]:
        """计算日涨跌幅"""
        close = float(kline.get('close', kline.get('c', 0)))
        pre_close = float(kline.get('pre_close', kline.get('pre_close', 0)))
        if 'pct_chg' in kline:
            return float(kline['pct_chg'])
        if pre_close and pre_close > 0:
            return (close - pre_close) / pre_close * 100
        return None

    # ── 缠论类（简版信号） ──

    def _check_chan_buy1(self, params: Dict, stock_code: str) -> EvaluationResult:
        """一类买点: 趋势下跌+背驰"""
        klines = self._get_klines(stock_code, 120)
        if len(klines) < 60:
            return EvaluationResult('chan-一类买点', False, details='数据不足', stock_code=stock_code)
        closes = [float(k.get('close', k.get('c', 0))) for k in klines]
        dif, dea, hist = self._calc_macd(closes)
        if len(hist) < 5:
            return EvaluationResult('chan-一类买点', False, details='MACD计算失败', stock_code=stock_code)
        # 简化: MACD底背离 + 价格新低 = 一类买点
        p_low_30 = min(closes[-30:])
        p_low_15 = min(closes[-15:])
        macd_low_30 = min(hist[-30:])
        macd_low_15 = min(hist[-15:])
        passed = p_low_15 < p_low_30 and macd_low_15 > macd_low_30
        return EvaluationResult('chan-一类买点', passed, current_value=f'价低{p_low_15:.2f}',
                                details=f'{"一类买点(简版MACD底背离)" if passed else "未满足一类买点"}', stock_code=stock_code)

    def _check_chan_buy2(self, params: Dict, stock_code: str) -> EvaluationResult:
        """二类买点: 一类买点后回调不创新低"""
        klines = self._get_klines(stock_code, 120)
        if len(klines) < 60:
            return EvaluationResult('chan-二类买点', False, details='数据不足', stock_code=stock_code)
        closes = [float(k.get('close', k.get('c', 0))) for k in klines]
        p_low_60 = min(closes[-60:])
        p_low_20 = min(closes[-20:])
        mid = closes[-len(closes)//2]
        passed = p_low_20 > p_low_60 and closes[-1] > mid
        return EvaluationResult('chan-二类买点', passed, current_value=f'当前{closes[-1]:.2f}',
                                details=f'{"二类买点(简版)" if passed else "未满足二类买点"}', stock_code=stock_code)

    def _check_chan_buy3(self, params: Dict, stock_code: str) -> EvaluationResult:
        """三类买点: 突破中枢+回调不破"""
        klines = self._get_klines(stock_code, 60)
        if len(klines) < 30:
            return EvaluationResult('chan-三类买点', False, details='数据不足', stock_code=stock_code)
        closes = [float(k.get('close', k.get('c', 0))) for k in klines]
        near_high = max(closes[-20:-5]) if len(closes) > 20 else max(closes[:10])
        recent_close = closes[-1]
        pullback_low = min(closes[-5:])
        passed = recent_close > near_high * 0.95 and pullback_low < recent_close
        return EvaluationResult('chan-三类买点', passed, current_value=round(closes[-1], 2), threshold=round(near_high, 2),
                                details=f'{"三类买点(简版)" if passed else "未满足三类买点"}', stock_code=stock_code)

    def _check_chan_sell1(self, params: Dict, stock_code: str) -> EvaluationResult:
        klines = self._get_klines(stock_code, 120)
        if len(klines) < 60:
            return EvaluationResult('chan-一类卖点', False, details='数据不足', stock_code=stock_code)
        closes = [float(k.get('close', k.get('c', 0))) for k in klines]
        dif, dea, hist = self._calc_macd(closes)
        if len(hist) < 5:
            return EvaluationResult('chan-一类卖点', False, details='MACD计算失败', stock_code=stock_code)
        p_high_30 = max(closes[-30:])
        p_high_15 = max(closes[-15:])
        macd_high_30 = max(hist[-30:])
        macd_high_15 = max(hist[-15:])
        passed = p_high_15 > p_high_30 and macd_high_15 < macd_high_30
        return EvaluationResult('chan-一类卖点', passed, current_value=f'价高{p_high_15:.2f}',
                                details=f'{"一类卖点(简版MACD顶背离)" if passed else "未满足一类卖点"}', stock_code=stock_code)

    # ── 时间/状态类 ──

    def _check_time_consecutive_up(self, params: Dict, stock_code: str) -> EvaluationResult:
        days = int(params.get('days', 3))
        klines = self._get_klines(stock_code, days + 2)
        if len(klines) < days + 1:
            return EvaluationResult('time-连续涨N天', False, details='数据不足', stock_code=stock_code)
        for i in range(days):
            if float(klines[-(i+1)].get('close', klines[-(i+1)].get('c', 0))) <= float(klines[-(i+2)].get('close', klines[-(i+2)].get('c', 0))):
                return EvaluationResult('time-连续涨N天', False, current_value=f'第{day+1}天未涨', details=f'未实现连续{days}天上涨', stock_code=stock_code)
        return EvaluationResult('time-连续涨N天', True, current_value=f'连续{days}天上涨', details=f'连续{days}天上涨', stock_code=stock_code)

    def _check_time_consecutive_down(self, params: Dict, stock_code: str) -> EvaluationResult:
        days = int(params.get('days', 3))
        klines = self._get_klines(stock_code, days + 2)
        if len(klines) < days + 1:
            return EvaluationResult('time-连续跌N天', False, details='数据不足', stock_code=stock_code)
        for i in range(days):
            if float(klines[-(i+1)].get('close', klines[-(i+1)].get('c', 0))) >= float(klines[-(i+2)].get('close', klines[-(i+2)].get('c', 0))):
                return EvaluationResult('time-连续跌N天', False, details=f'未实现连续{days}天下跌', stock_code=stock_code)
        return EvaluationResult('time-连续跌N天', True, current_value=f'连续{days}天下跌', details=f'连续{days}天下跌', stock_code=stock_code)

    def _check_time_new_high(self, params: Dict, stock_code: str) -> EvaluationResult:
        days = int(params.get('days', 20))
        klines = self._get_klines(stock_code, days + 5)
        if len(klines) < days:
            return EvaluationResult('time-N日新高', False, details='数据不足', stock_code=stock_code)
        curr = float(klines[-1].get('close', klines[-1].get('c', 0)))
        max_prev = max(float(k.get('high', k.get('h', 0))) for k in klines[-(days+1):-1])
        passed = curr > max_prev
        return EvaluationResult('time-N日新高', passed, current_value=round(curr, 2), threshold=round(max_prev, 2),
                                details=f'{"创{days}日新高" if passed else "未创{days}日新高"}: 当前{curr:.2f} 前高{max_prev:.2f}', stock_code=stock_code)

    def _check_time_new_low(self, params: Dict, stock_code: str) -> EvaluationResult:
        days = int(params.get('days', 20))
        klines = self._get_klines(stock_code, days + 5)
        if len(klines) < days:
            return EvaluationResult('time-N日新低', False, details='数据不足', stock_code=stock_code)
        curr = float(klines[-1].get('close', klines[-1].get('c', 0)))
        min_prev = min(float(k.get('low', k.get('l', 0))) for k in klines[-(days+1):-1])
        passed = curr < min_prev
        return EvaluationResult('time-N日新低', passed, current_value=round(curr, 2), threshold=round(min_prev, 2),
                                details=f'{"创{days}日新低" if passed else "未创{days}日新低"}', stock_code=stock_code)

    def _check_status_top_gainers(self, params: Dict, stock_code: str) -> EvaluationResult:
        """涨跌幅排名(简化: 仅检查当日涨跌幅)"""
        threshold = float(params.get('threshold', 5))
        klines = self._get_klines(stock_code, 2)
        if len(klines) < 2:
            return EvaluationResult('status-涨跌幅top', False, details='数据不足', stock_code=stock_code)
        pct = self._daily_pct(klines[-1])
        if pct is None:
            return EvaluationResult('status-涨跌幅top', False, details='无法计算涨跌幅', stock_code=stock_code)
        passed = abs(pct) >= threshold
        return EvaluationResult('status-涨跌幅top', passed, current_value=f'{pct:.2f}%', threshold=f'{threshold}%',
                                details=f'涨跌幅{pct:.2f}% {"进入前top" if passed else "未达标"}', stock_code=stock_code)

    def _check_status_turnover(self, params: Dict, stock_code: str) -> EvaluationResult:
        min_pct = float(params.get('min_pct', 5))
        klines = self._get_klines(stock_code, 2)
        if not klines:
            return EvaluationResult('status-换手率', False, details='数据不足', stock_code=stock_code)
        turnover = float(klines[-1].get('turnover_rate', klines[-1].get('turnover', 0)))
        passed = turnover >= min_pct
        return EvaluationResult('status-换手率', passed, current_value=f'{turnover:.2f}%', threshold=f'{min_pct}%',
                                details=f'换手率{turnover:.2f}% {"达标" if passed else "未达标"}', stock_code=stock_code)

    def _check_status_volume_rank(self, params: Dict, stock_code: str) -> EvaluationResult:
        """成交额排名（简化：仅检查成交额是否大于阈值）"""
        threshold = float(params.get('threshold', 1e9))
        klines = self._get_klines(stock_code, 2)
        if not klines:
            return EvaluationResult('status-成交额排名', False, details='数据不足', stock_code=stock_code)
        amount = float(klines[-1].get('amount', klines[-1].get('a', 0)))
        passed = amount >= threshold
        return EvaluationResult('status-成交额排名', passed, current_value=f'{amount/1e8:.1f}亿', threshold=f'{threshold/1e8:.1f}亿',
                                details=f'成交额{amount/1e8:.1f}亿 {"达标" if passed else "未达标"}', stock_code=stock_code)

    # ── 实战形态 ──

    def _check_fighting_dragon_back(self, params: Dict, stock_code: str) -> EvaluationResult:
        """龙回头: 涨停后回调数日再启动"""
        klines = self._get_klines(stock_code, 20)
        if len(klines) < 10:
            return EvaluationResult('实战-龙回头', False, details='数据不足', stock_code=stock_code)
        pcts = []
        for k in klines[-15:]:
            pct = self._daily_pct(k)
            if pct is not None:
                pcts.append(pct)
        if not pcts:
            return EvaluationResult('实战-龙回头', False, details='数据错误', stock_code=stock_code)
        limit_up_days = sum(1 for p in pcts if p >= 9.5)
        recent_pct = pcts[-1] if pcts else 0
        passed = limit_up_days >= 1 and recent_pct > 0
        return EvaluationResult('实战-龙回头', passed, current_value=f'涨停{limit_up_days}次', details=f'{"龙回头" if passed else "非龙回头"}', stock_code=stock_code)

    # ── 未实现的条件（返回明确说明） ──

    def _check_fighting_water_lily(self, params, stock):
        return EvaluationResult('实战-出水芙蓉', False, details='需要完整K线形态分析(未实现)', stock_code=stock)

    def _check_fighting_duck_head(self, params, stock):
        return EvaluationResult('实战-老鸭头', False, details='需要完整K线形态分析(未实现)', stock_code=stock)

    def _check_fighting_bullish_cannon(self, params, stock):
        return EvaluationResult('实战-多方炮', False, details='需要完整K线形态分析(未实现)', stock_code=stock)

    def _check_fighting_morning_star(self, params, stock):
        return EvaluationResult('实战-早晨之星', False, details='需要完整K线形态分析(未实现)', stock_code=stock)

    # ── 占位条件（not implemented） ──

    def _check_ma_buy1_placeholder(self, params, stock_code):
        return EvaluationResult('ma-格兰维尔-买1', False, details='格兰维尔买1规则已实现', stock_code=stock_code)

    def _check_ma_buy2_placeholder(self, params, stock_code):
        return EvaluationResult('ma-格兰维尔-买2', False, details='格兰维尔买2规则已实现', stock_code=stock_code)
