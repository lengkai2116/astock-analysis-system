import logging

"""
筹码分布策略 - 模块化实现
参考 Algorithm Framework 的设计
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from . import (
    AlphaModel,
    Insight,
    RiskManagementModel,
    UniverseSelectionModel,
)

logger = logging.getLogger(__name__)
class ChipUniverseSelectionModel(UniverseSelectionModel):
    """
    筹码分布股票池选择模型
    筛选出具备主力资金条件的股票
    """

    def __init__(self, lookback_period: int = 120, top_n: int = 50):
        """
        Args:
            lookback_period: 回看周期
            top_n: 返回前N只股票
        """
        self.lookback_period = lookback_period
        self.top_n = top_n
        self.chip_scorer = ChipScorer()

    def select(self, date_time: datetime, data: Any) -> List[str]:
        """
        筛选股票池

        Args:
            date_time: 时间戳
            data: 市场数据，格式为 {symbol: DataFrame}

        Returns:
            股票代码列表，按分数降序排列
        """
        if not isinstance(data, dict):
            return []

        results = []
        for symbol, df in data.items():
            try:
                if len(df) < 60:
                    continue

                # 计算筹码评分
                score = self.chip_scorer.score(df)
                if score > 0:
                    results.append((symbol, score))

            except Exception as e:
                logger.error(f"筛选股票 {symbol} 时出错: {e}")

        # 按分数排序，返回前N只
        results.sort(key=lambda x: x[1], reverse=True)
        return [item[0] for item in results[:self.top_n]]


class ChipAlphaModel(AlphaModel):
    """
    筹码分布信号生成模型
    生成交易信号洞察
    """

    def __init__(self, lookback_period: int = 120):
        self.lookback_period = lookback_period
        # 简化实现，移除外部依赖
        self.chip_service = None
        self.chip_indicators = None

    def generate_insights(self, data: any) -> List[Insight]:
        """
        生成筹码分布交易信号洞察

        Args:
            data: 可以是DataFrame或字典格式的OHLCV数据

        Returns:
            洞察信号列表
        """
        insights = []

        # 处理不同类型的数据输入
        data_dict = data if isinstance(data, dict) else {'data': data}

        for symbol, df in data_dict.items():
            try:
                if isinstance(df, pd.DataFrame):
                    if df.empty or len(df) < 120:
                        continue

                    # 使用评分器分析
                    scorer = ChipScorer()
                    score = scorer.score(df)

                    # 根据评分生成信号
                    if score >= 7.0:
                        # 高分 - 强力买入
                        direction = Insight.LONG
                        confidence = min(0.9, score / 10.0)
                        weight = 0.8
                        reason = f"高评分筹码策略信号: {symbol} (评分: {score:.2f})"
                    elif score >= 5.0:
                        # 中分 - 买入
                        direction = Insight.LONG
                        confidence = min(0.7, score / 10.0)
                        weight = 0.5
                        reason = f"中等评分筹码策略信号: {symbol} (评分: {score:.2f})"
                    elif score >= 3.0:
                        # 低分 - 观望
                        direction = Insight.FLAT
                        confidence = 0.5
                        weight = 0.0
                        reason = f"观望信号: {symbol} (评分: {score:.2f})"
                    else:
                        # 极低分 - 做空
                        direction = Insight.SHORT
                        confidence = min(0.6, (10.0 - score) / 10.0)
                        weight = 0.3
                        reason = f"卖出信号: {symbol} (评分: {score:.2f})"

                    insights.append(
                        Insight(
                            symbol=symbol,
                            direction=direction,
                            confidence=confidence,
                            weight=weight,
                            reason=reason
                        )
                    )
            except Exception as e:
                logger.error(f"处理 {symbol} 时失败: {e}")

        return insights


class ChipRiskManagementModel(RiskManagementModel):
    """
    筹码分布风险管理模型
    提供止损止盈和风险控制逻辑
    """

    def __init__(self,
                 stop_loss_pct: float = 0.08,  # 止损8%
                 take_profit_pct: float = 0.15,  # 止盈15%
                 max_single_position_pct: float = 0.2,  # 单只股票最大20%仓位
                 max_total_exposure: float = 0.8):  # 总仓位不超过80%
        """
        Args:
            stop_loss_pct: 止损百分比
            take_profit_pct: 止盈百分比
            max_single_position_pct: 单只股票最大仓位比例
            max_total_exposure: 总暴露风险上限
        """
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.max_single_position_pct = max_single_position_pct
        self.max_total_exposure = max_total_exposure
        self.entry_prices: Dict[str, float] = {}  # 记录入场价格

    def on_data(self, insights: List[Insight], targets: Dict[str, float],
                current_portfolio: Dict[str, float]) -> Dict[str, float]:
        """
        应用风险管理规则

        Args:
            insights: 洞察信号列表
            targets: 目标仓位
            current_portfolio: 当前持仓 {symbol: position_pct}

        Returns:
            调整后的目标仓位
        """
        adjusted_targets = targets.copy()

        # 1. 检查止损止盈
        for symbol, entry_price in self.entry_prices.items():
            if symbol not in current_portfolio:
                continue

            # 这里简化实现，实际需要获取当前价格
            # 假设通过某种方式获取当前价格，这里简化逻辑
            position = current_portfolio.get(symbol, 0)

            if position != 0:
                # 有持仓的情况下，检查是否需要止损或止盈
                # 这里需要真实的价格数据，暂时简化逻辑
                pass

        # 2. 控制单只股票最大仓位
        for symbol, target in adjusted_targets.items():
            if target > self.max_single_position_pct:
                adjusted_targets[symbol] = self.max_single_position_pct
            elif target < -self.max_single_position_pct:
                adjusted_targets[symbol] = -self.max_single_position_pct

        # 3. 控制总仓位风险
        total_exposure = sum(abs(t) for t in adjusted_targets.values())
        if total_exposure > self.max_total_exposure:
            # 按比例缩减所有仓位
            scale_factor = self.max_total_exposure / total_exposure
            for symbol in adjusted_targets:
                adjusted_targets[symbol] *= scale_factor

        return adjusted_targets

    def set_entry_price(self, symbol: str, price: float):
        """记录入场价格"""
        self.entry_prices[symbol] = price

    def clear_entry_price(self, symbol: str):
        """清仓时移除价格记录"""
        if symbol in self.entry_prices:
            del self.entry_prices[symbol]


class ChipScorer:
    """
    筹码分布选股评分器 — V2 方向正确版

    用于 L2 批量筛选 4000+ 只股票的场景。
    通过四维 OHLCV-only 评分评估主力资金吸引力。

    Returns:
        float: 0-10 评分，越高越看多
    """

    def get_available_windows(self) -> list:
        """返回筹码分析支持的回看周期"""
        return [60, 120]

    def score(self, data: pd.DataFrame) -> float:
        if data.empty or len(data) < 120:
            return 0.0

        try:
            return self._calculate_v2_score(data)
        except Exception as e:
            logger.error(f"ChipScorer V2 评分失败: {e}")
            return 0.0

    def _calculate_v2_score(self, data: pd.DataFrame) -> float:
        closes = data['close'].values
        volumes = data['vol'].values if 'vol' in data.columns else (
            data['amount'].values if 'amount' in data.columns
            else np.ones(len(data))
        )

        score = 0.0
        details = {}

        # ─── 维度1: 成本位置 (0-3分) ───
        # VWAP(120) 作为主力平均成本代理
        # 价格在成本附近 → 安全；价格远离成本 → 谨慎
        vwap_120 = np.average(closes, weights=volumes) if len(closes) >= 20 else closes[-1]
        current_price = closes[-1]
        cost_deviation = (current_price - vwap_120) / vwap_120 if vwap_120 > 0 else 0

        if -0.05 <= cost_deviation <= 0.10:
            # 价格在成本 ±10% 内 → 安全区，主力未大幅盈利
            cost_score = 3.0
        elif -0.10 <= cost_deviation < -0.05:
            # 略低于成本 → 洗盘/建仓末期，机会
            cost_score = 2.5
        elif 0.10 < cost_deviation <= 0.25:
            # 已脱离成本区 10-25% → 拉升中段
            cost_score = 2.0
        elif cost_deviation < -0.10:
            # 深跌低于成本
            cost_score = 1.0
        else:
            # 大幅高于成本 > 25% → 出货风险区
            cost_score = 0.5
        details['cost_position'] = round(cost_deviation, 4)
        score += cost_score

        # ─── 维度2: 量能剖面 (0-3分) ───
        # 比较 5日 → 20日 → 60日 均量，判断量能趋势
        # 低位放量 = 建仓 ✓  高位放量 = 出货 ✗
        vol_5 = np.mean(volumes[-5:]) if len(volumes) >= 5 else 0
        vol_20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else 0
        vol_60 = np.mean(volumes[-60:]) if len(volumes) >= 60 else 0

        # 计算价格在 120 日区间的位置
        price_high = np.max(closes[-120:])
        price_low = np.min(closes[-120:])
        price_range = price_high - price_low if price_high > price_low else 1.0
        price_position = (current_price - price_low) / price_range

        # 量比指标
        vol_ratio_5_20 = vol_5 / vol_20 if vol_20 > 0 else 1.0
        vol_ratio_20_60 = vol_20 / vol_60 if vol_60 > 0 else 1.0

        if price_position < 0.4 and 1.0 <= vol_ratio_5_20 <= 2.0:
            # 低位放量（非暴量）→ 建仓特征
            volume_score = 3.0
        elif price_position >= 0.7 and vol_ratio_5_20 >= 1.5:
            # 高位放量 → 出货特征
            volume_score = 0.5
        elif price_position < 0.3 and vol_ratio_20_60 < 1.0:
            # 低位缩量 → 洗盘后期
            volume_score = 2.5
        elif vol_ratio_5_20 < 0.7:
            # 短期极度缩量 → 交投不活跃
            volume_score = 1.0
        elif price_position >= 0.8 and vol_ratio_5_20 < 1.0:
            # 高位缩量 → 追高意愿不足
            volume_score = 0.5
        else:
            # 中性
            volume_score = 2.0
        details['volume_signal'] = round(vol_ratio_5_20, 2)
        score += volume_score

        # ─── 维度3: 趋势健康度 (0-2分) ───
        # 短中期趋势方向一致性
        if len(closes) >= 60:
            ma_5 = np.mean(closes[-5:])
            ma_20 = np.mean(closes[-20:])
            ma_60 = np.mean(closes[-60:])
            # 多头排列: MA5 > MA20 > MA60
            if ma_5 > ma_20 > ma_60:
                trend_score = 2.0
            # 空头排列: MA5 < MA20 < MA60
            elif ma_5 < ma_20 < ma_60:
                # 但价格已靠近底部 → 可能底部区域
                if price_position < 0.3:
                    trend_score = 1.5  # 底部区域空头排列是机会
                else:
                    trend_score = 0.5
            # 短期上穿中期 → 拐点
            elif ma_5 > ma_20 and ma_20 <= ma_60:
                trend_score = 1.5
            # 短期下穿中期 → 调整
            elif ma_5 < ma_20 and ma_20 > ma_60:
                if price_position < 0.4:
                    trend_score = 1.0  # 回调但未破位
                else:
                    trend_score = 0.5
            else:
                trend_score = 1.0
        else:
            trend_score = 1.0
        score += trend_score

        # ─── 维度4: 价格稳定性 (0-2分) ───
        # 窄幅震荡在低位 = 吸筹  |  宽幅波动在高位 = 出货
        if len(closes) >= 20:
            recent_volatility = np.std(closes[-20:]) / np.mean(closes[-20:])
            if price_position < 0.4 and recent_volatility < 0.05:
                # 低位窄幅 → 吸筹特征
                stability_score = 2.0
            elif price_position >= 0.7 and recent_volatility > 0.08:
                # 高位宽幅 → 出货特征
                stability_score = 0.5
            elif recent_volatility < 0.03:
                # 极低波动 → 变盘前兆
                stability_score = 1.5
            else:
                stability_score = 1.0
        else:
            stability_score = 1.0
        score += stability_score

        return min(10.0, max(0.0, score))


class MainForceScorer:
    """
    主力资金关注度评分器 — 替代 ChipScorer 用于 L2 筛选

    =================================================================
    设计理念：L2 的目标是识别「市场主力资金正在关注的股票」。

    主力资金的典型行为特征：
      1. 大单持续净流入（资金流向）
      2. 低位吸筹（价平量增，窄幅震荡）
      3. 筹码集中（股东户数减少）

    数据源优先级：
      [P0] moneyflow_cache — 大单/超大单净流入（核心指标）
      [P1] daily_cache — 价量特征（OHLCV）
      [P2] stk_holder_cache — 股东户数变化（辅助）

    评分范围 0-10，阈值建议 ≥6 分视为"有主力关注"。
    =================================================================
    """

    def __init__(self):
        self._dm = None
        self._chip_indicators: Optional[dict] = None
        self._chip_bins: Optional[list] = None

    @property
    def dm(self):
        if self._dm is None:
            from app.data import DataManager
            self._dm = DataManager()
        return self._dm

    def score(self, data: pd.DataFrame, symbol: str = None,
              chip_fund_ext: dict = None) -> float:
        """
        综合评分：0-10，越高代表主力关注度越强

        Args:
            data: OHLCV DataFrame（120 天以上）
            symbol: 股票代码（传入后可获取资金流向和股东数据）
            chip_fund_ext: 可选，筹码预计算聚合指标（424号§10决策②，避免重复计算完整分布）

        Returns:
            0-10 分
        """
        if data.empty or len(data) < 60:
            return 0.0

        try:
            closes = data['close'].values
            volumes = data['vol'].values if 'vol' in data.columns else (
                data['amount'].values if 'amount' in data.columns
                else np.ones(len(data))
            )
            price_high = np.max(closes[-120:])
            price_low = np.min(closes[-120:])
            price_range = price_high - price_low if price_high > price_low else 1.0
            price_position = (closes[-1] - price_low) / price_range

            score_a = self._score_moneyflow(symbol)
            score_b = self._score_volume_price(closes, volumes, price_position)
            score_c = self._score_concentration(symbol, closes, price_position)
            score_d = self._score_retail_contrarian(symbol, price_position)

            # E: 龙虎榜席位加分（包含假机构识别）
            score_e = self._score_lhb(symbol, data)

            # F: 筹码分布维度（424号§10决策②：优先消费 chip_fund_ext 预计算聚合指标）
            score_f = self._score_chip_distribution(symbol, data, chip_fund_ext=chip_fund_ext)

            total = score_a + score_b + score_c + score_d + score_e + score_f
            return min(10.0, max(0.0, total))
        except Exception as e:
            logger.error(f"MainForceScorer 评分失败 {symbol}: {e}")
            return 0.0

    def get_sub_scores(self, data: pd.DataFrame, symbol: str = None,
                       chip_fund_ext: dict = None) -> dict:
        """返回各子维度独立评分（364c Phase 3）"""
        if data.empty or len(data) < 60:
            return {'total': 0.0, 'moneyflow': 0.0, 'volume_price': 0.0,
                    'concentration': 0.0, 'retail_contrarian': 0.0,
                    'lhb': 0.0, 'chip_distribution': 0.0, 'sub_details': {}}
        try:
            closes = data['close'].values
            volumes = data['vol'].values if 'vol' in data.columns else np.ones(len(data))
            price_high = np.max(closes[-120:]) if len(closes) >= 120 else np.max(closes)
            price_low = np.min(closes[-120:]) if len(closes) >= 120 else np.min(closes)
            price_range = price_high - price_low if price_high > price_low else 1.0
            price_position = (closes[-1] - price_low) / price_range

            score_a = self._score_moneyflow(symbol)
            score_b = self._score_volume_price(closes, volumes, price_position)
            score_c = self._score_concentration(symbol, closes, price_position)
            score_d = self._score_retail_contrarian(symbol, price_position)
            score_e = self._score_lhb(symbol, data)
            score_f = self._score_chip_distribution(symbol, data, chip_fund_ext=chip_fund_ext)
            total = score_a + score_b + score_c + score_d + score_e + score_f

            return {
                'total': round(min(10.0, max(0.0, total)), 2),
                'moneyflow': round(score_a, 2),
                'volume_price': round(score_b, 2),
                'concentration': round(score_c, 2),
                'retail_contrarian': round(score_d, 2),
                'lhb': round(score_e, 2),
                'chip_distribution': round(score_f, 2),
                'sub_details': {},
            }
        except Exception:
            return {'total': 0.0, 'moneyflow': 0.0, 'volume_price': 0.0,
                    'concentration': 0.0, 'retail_contrarian': 0.0,
                    'lhb': 0.0, 'chip_distribution': 0.0, 'sub_details': {}}

    def get_fund_flow_strength(self, symbol: str) -> dict:
        """资金流向5级强度分层（364c Phase 3）"""
        if not symbol:
            return {'level': 'none', 'level_cn': '中性', 'direction': 'neutral', 'detail': '无数据'}
        try:
            mf_df = self._dm.get_cached_moneyflow(symbol)
            if mf_df is None or mf_df.empty:
                return {'level': 'none', 'level_cn': '中性', 'direction': 'neutral', 'detail': '无资金数据'}
            mf_5 = mf_df.tail(5)
            net_lg_5d = float(mf_5['net_lg_amount'].sum())
            pos_days = int((mf_5['net_lg_amount'] > 0).sum())
            positive_ratio = pos_days / max(len(mf_5), 1)

            if pos_days >= 3 and net_lg_5d > 100000000:
                return {'level': 'very_strong', 'level_cn': '极强', 'direction': 'inflow',
                        'detail': f'连续{pos_days}日净流入，累计{net_lg_5d/1e8:.1f}亿'}
            elif positive_ratio > 0.6:
                return {'level': 'strong', 'level_cn': '强', 'direction': 'inflow',
                        'detail': f'多数日净流入（{pos_days}/5日）'}
            elif positive_ratio > 0.4:
                return {'level': 'medium', 'level_cn': '中等', 'direction': 'mixed',
                        'detail': f'流入流出交替（{pos_days}/5日净流入）'}
            elif net_lg_5d < 0:
                return {'level': 'weak', 'level_cn': '弱', 'direction': 'outflow',
                        'detail': f'净流出（累计{net_lg_5d/1e4:.0f}万）'}
            else:
                return {'level': 'none', 'level_cn': '中性', 'direction': 'neutral',
                        'detail': '无明确资金方向'}
        except Exception:
            return {'level': 'none', 'level_cn': '中性', 'direction': 'neutral', 'detail': '计算异常'}

    def get_chip_transfer(self, symbol: str) -> dict:
        """筹码转移方向检测（364c Phase 3）"""
        if not symbol:
            return {'direction': 'unknown', 'speed': 'unknown', 'detail': '无数据'}
        try:
            indicators = self._chip_indicators or {}
            asr = indicators.get('asr') or indicators.get('ASR')
            indicators.get('concentration')
            if asr is not None:
                asr_val = float(asr)
                if asr_val > 70:
                    return {'direction': '集中', 'speed': '快速', 'detail': f'筹码高度集中（ASR={asr_val:.0f}）'}
                elif asr_val > 50:
                    return {'direction': '集中', 'speed': '中等', 'detail': f'筹码中等集中（ASR={asr_val:.0f}）'}
                else:
                    return {'direction': '分散', 'speed': '中等', 'detail': f'筹码分散（ASR={asr_val:.0f}）'}
        except Exception:
            pass
        return {'direction': 'unknown', 'speed': 'unknown', 'detail': '筹码数据不足'}

    def get_control_degree(self, symbol: str) -> dict:
        """控盘度计算（364c Phase 3：三维度加权）"""
        if not symbol:
            return {'level': 'unknown', 'score': 0, 'detail': '无数据'}
        try:
            indicators = self._chip_indicators or {}
            asr = float(indicators.get('asr') or indicators.get('ASR') or 0)
            concentration = float(indicators.get('concentration') or 0)
            main_flow = 1.0 if str(tags.get('fund_flow', '')) == '5d_inflow' else 0.5
            score = (asr / 100 * 0.4) + (concentration * 0.3 if concentration else 0.5 * 0.3) + (main_flow * 0.3)
            if score > 0.7:
                level = '高控盘'
            elif score > 0.4:
                level = '中等控盘'
            else:
                level = '低控盘'
            return {'level': level, 'score': round(score, 2), 'detail': f'{level}（{score:.2f}）'}
        except Exception:
            return {'level': 'unknown', 'score': 0, 'detail': '计算异常'}

    # ─── A: 资金流向维度 (0-3分) ───────────────────────────────
    # Wiki 核心思想：大单连续性 > 单日强度；融资暴增+股价不动=危险信号
    def _score_moneyflow(self, symbol: str) -> float:
        """
        评估主力资金净流入强度（基于 LLM Wiki 主力行为分析）

        使用 moneyflow_cache 分析：
          1. 5日累积大单净额（净流入率）
          2. 大单成交占比（大单主导程度）
          3. **资金连续性**（Wiki: "连续买超+股价上涨=机构看多"）

        Returns: 0-3 分（无数据时返回 0）
        """
        if not symbol:
            return 0.0

        try:
            end_str = datetime.now().strftime('%Y-%m-%d')
            start_str = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
            mf_df = self.dm.get_cached_moneyflow(
                symbol, start_date=start_str, end_date=end_str
            )
            if mf_df.empty:
                mf_df = self.dm.get_cached_moneyflow(symbol)
                if mf_df.empty:
                    return 0.0
            mf_5 = mf_df.tail(5)

            # 1. 5日累积大单净额 (0-1.0分)
            net_lg_sum = mf_5['net_lg_amount'].sum()
            abs_big = (mf_5['buy_lg_amount'].abs().sum()
                       + mf_5['sell_lg_amount'].abs().sum()
                       + mf_5['buy_elg_amount'].abs().sum()
                       + mf_5['sell_elg_amount'].abs().sum())
            net_ratio = net_lg_sum / max(abs_big, 1)
            flow_score = min(1.0, max(0, net_ratio * 4))

            # 2. 大单成交占比 (0-0.5分) — Wiki: 机构主导程度
            total_small = (mf_5['buy_sm_amount'].abs().sum()
                           + mf_5['sell_sm_amount'].abs().sum())
            if abs_big + total_small > 0:
                lg_ratio = abs_big / (abs_big + total_small)
                ratio_score = min(0.5, lg_ratio * 1.0)  # 大单占50%得0.5
            else:
                ratio_score = 0.0

            # 3. 资金连续性 (0-1.5分) — Wiki 重点：连续性比绝对量更重要
            pos_days = (mf_5['net_lg_amount'] > 0).sum()
            neg_days = (mf_5['net_lg_amount'] < 0).sum()
            # 连续净流入加分：连续2天以上净流入+0.5
            streak = 0
            max_streak = 0
            for _, row in mf_5.iterrows():
                if row['net_lg_amount'] > 0:
                    streak += 1
                    max_streak = max(max_streak, streak)
                else:
                    streak = 0
            continuity = min(1.0, max_streak * 0.3)
            # 净胜天数
            net_days_score = min(0.5, max(0, pos_days - neg_days) * 0.15)

            return min(3.0, flow_score + ratio_score + continuity + net_days_score)
        except Exception:
            return 0.0

    # ─── B: 价量主力信号 (0-3分) ───────────────────────────────
    # Wiki 核心思想：主力四阶段（建仓/洗盘/拉升/出货）各有专属价量特征
    def _score_volume_price(self, closes, volumes, price_position) -> float:
        """
        从价量关系识别主力操盘阶段（Wiki: 筹码分析+主力行为四阶段）

        建仓: 低位价平量增        → 高分
        洗盘: 价跌量减，缩量企稳  → 中分（即将结束）
        拉升: 价涨量增，多头排列  → 最高分
        出货: 高位放量滞涨/量价背离 → 低分/负分

        Returns: 0-3 分
        """
        if len(closes) < 20:
            return 1.0

        vol_5 = np.mean(volumes[-5:]) if len(volumes) >= 5 else 0
        vol_20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else 0
        vol_60 = np.mean(volumes[-60:]) if len(volumes) >= 60 else 0
        vol_ratio_5_20 = vol_5 / max(vol_20, 1)
        vol_ratio_20_60 = vol_20 / max(vol_60, 1) if vol_60 > 0 else 1.0

        # 均线排列
        ma_5 = np.mean(closes[-5:])
        ma_20 = np.mean(closes[-20:])
        ma_60 = np.mean(closes[-60:]) if len(closes) >= 60 else closes[-1]
        bull_market = ma_5 > ma_20 > ma_60

        # ── 拉升阶段 (2.5-3分) — 价涨量增 + 多头排列
        if bull_market and vol_ratio_5_20 >= 1.1:
            return 3.0 if price_position < 0.7 else 2.5

        # ── 建仓阶段 (1.5-2.5分) — 低位价平量增
        if price_position < 0.5 and 1.1 <= vol_ratio_5_20 <= 2.0:
            if vol_ratio_20_60 >= 1.15:
                return 2.5  # 低位放量且有持续增量
            return 2.0

        # ── 洗盘后期 (1.0-1.5分) — 价跌量减后缩量企稳
        if price_position < 0.4 and vol_ratio_5_20 < 0.8:
            if vol_ratio_20_60 < 0.9:
                return 1.5  # 长期缩量→洗盘临近结束
            return 1.0

        # ── 出货嫌疑 (0-0.5分) — 高位放量不涨
        if price_position >= 0.7 and vol_ratio_5_20 >= 1.5:
            return 0.0
        if price_position >= 0.8 and vol_ratio_5_20 < 0.7:
            return 0.5  # 高位缩量→追高意愿不足

        # ── 中性 (1.0分)
        return 1.0

    # ─── C: 筹码集中度 (0-2分) ───────────────────────────────
    # Wiki 核心思想：筹码从分散到集中=建仓；股东户数下降+稳定价格=吸筹
    def _score_concentration(self, symbol: str, closes, price_position) -> float:
        """
        评估筹码集中度

        Wiki 核心理念：
          - 大户比例上升+散户比例下降=筹码集中→后续拉升
          - 低位窄幅震荡=吸筹特征
          也可参考"主力集中价"概念：VWAP(仅大单日)与当前价的偏离

        Returns: 0-2 分
        """
        # 1. 优先使用股东户数数据
        if symbol:
            try:
                holder_df = self.dm.get_cached_stk_holder(symbol)
                if not holder_df.empty and 'holder_number' in holder_df.columns:
                    h = holder_df.dropna(subset=['holder_number']).sort_values('end_date')
                    if len(h) >= 2:
                        latest = float(h['holder_number'].iloc[-1])
                        earliest = float(h['holder_number'].iloc[0])
                        if earliest > 0 and latest > 0:
                            change = (latest - earliest) / earliest
                            if change <= -0.05: return 2.0
                            elif change <= -0.02: return 1.5
                            elif change <= 0: return 1.0
                            else: return 0.5
            except Exception:
                pass

        # 2. 回退：OHLCV 稳定性评估
        if len(closes) < 20:
            return 1.0
        recent_vol = np.std(closes[-20:]) / max(np.mean(closes[-20:]), 1e-9)
        if price_position < 0.5 and recent_vol < 0.05:
            return 1.5
        elif price_position >= 0.7 and recent_vol > 0.08:
            return 0.0
        elif recent_vol < 0.03:
            return 1.0
        else:
            return 0.5

    # ─── D: 散户反向指标 (0-2分) ───────────────────────────────
    # Wiki 核心思想：散户接盘=危险信号；融资暴增+股价不涨=出货
    def _score_retail_contrarian(self, symbol: str, price_position) -> float:
        """
        散户反向指标（Wiki: "散户行为模式通常是追涨杀跌，其集体行为常被用作反向指标"）
        含融资融券信号（Wiki: "融资余额过高是危险的，而非繁荣的信号"）

        逻辑：
          - 散户净买入（small_order）偏高且价格在高位 → 散户接盘 → 负分
          - 散户净卖出且价格在低位 → 散户割肉 → 正分
          - 融资余额暴增+股价横盘 → 散户杠杆接盘 → 负分
          - 融资余额骤降+股价下跌 → 恐慌杀跌 → 正分

        Returns: 0-2 分
        """
        if not symbol:
            return 1.0
        try:
            mf_df = self.dm.get_cached_moneyflow(symbol)
            if mf_df.empty or len(mf_df) < 3:
                return 1.0
            mf_5 = mf_df.tail(5)

            # 散户5日累积净额（buy_sm - sell_sm）
            retail_net = (mf_5['buy_sm_amount'].sum()
                          - mf_5['sell_sm_amount'].sum())
            total_flow = (mf_5['buy_sm_amount'].abs().sum()
                          + mf_5['sell_sm_amount'].abs().sum())

            if total_flow < 1:
                return 1.0

            retail_ratio = retail_net / total_flow  # -1 ~ 1

            score = 1.0  # 基础分

            # 散户在高位大量买入 → 危险
            if price_position >= 0.7 and retail_ratio > 0.2:
                score = 0.0
            # 散户在低位大量卖出 → 机会
            elif price_position < 0.4 and retail_ratio < -0.2:
                score = 2.0
            elif retail_ratio < -0.1:
                score = 1.5
            elif retail_ratio > 0.1:
                score = 0.5

            # ── 融资融券反向信号（D1 margin_detail 修复后可用）──
            try:
                mrg = self.dm.get_cached_margin(symbol)
                if mrg is not None and len(mrg) >= 5:
                    mrg_5 = mrg.tail(5)
                    rzye_series = mrg_5['rzye'].dropna().values
                    if len(rzye_series) >= 3:
                        # 融资余额趋势
                        margin_change = (rzye_series[-1] - rzye_series[0]) / max(rzye_series[0], 1)
                        # 融资暴增(>10%) + 股价不涨 → 散户杠杆接盘
                        if margin_change > 0.10 and price_position >= 0.5:
                            score -= 0.5  # 扣分
                        # 融资骤降(<-10%) + 股价下跌 → 恐慌杀跌，中期底部
                        elif margin_change < -0.10 and price_position <= 0.3:
                            score += 0.3  # 加分的左侧机会
            except Exception:
                pass  # margin数据不可用时不调整

            return max(0.0, min(2.0, score))
        except Exception:
            return 1.0


    def _score_lhb(self, symbol: str, data: pd.DataFrame = None) -> float:
        """龙虎榜席位加分（-0.5 至 +1.0 分）

        使用 _detect_fake_institution 识别假机构信号，
        真机构大额买入加分，假机构信号扣分。
        """
        if not symbol:
            return 0.0
        try:
            # 假机构检测
            fake_result = self._detect_fake_institution(symbol, data)
            if fake_result['suspected']:
                return -fake_result['confidence']  # 假机构扣分

            # 真机构加分
            lhb = self.dm.get_cached_lhb(symbol)
            if lhb is not None and not lhb.empty and len(lhb) > 0:
                recent = lhb.tail(10)
                buy_amounts = recent['buy_amount'].dropna()
                if len(buy_amounts) > 0:
                    total_buy = buy_amounts.sum()
                    if total_buy > 1e7:  # 千万级买入
                        return min(1.0, total_buy / 5e8 * 1.0)  # 5亿→1.0分
            return 0.0
        except Exception:
            return 0.0

    def _detect_fake_institution(self, symbol: str, data: pd.DataFrame) -> dict:
        """假机构识别（基于 LLM Wiki 假机构识别概念）

        检查龙虎榜数据中疑似假机构的行为特征：
        1. 买入金额占比过高（>30%）→ 警惕
        2. 价格处于高位/下跌反弹途中 → 警惕
        3. 机构集中单日大额买入 → 警惕

        Returns:
            {"suspected": bool, "reason": str, "confidence": float}
        """
        result = {"suspected": False, "reason": "", "confidence": 0.0}
        try:
            # 优先使用股票级 lhb_cache；若为空则回退到席位级 lhb_detail_cache
            lhb = self.dm.get_cached_lhb(symbol)
            use_detail_only = False
            if lhb is not None and not lhb.empty and len(lhb) > 0:
                recent = lhb.tail(10)
                if 'buy_amount' not in recent.columns or 'sell_amount' not in recent.columns:
                    use_detail_only = True
                    recent = None
            else:
                use_detail_only = True
                recent = None

            # 价格位置（低位=0.0, 高位=1.0）
            closes = data['close'].values if data is not None and not data.empty else None
            price_pos = None
            if closes is not None and len(closes) >= 60:
                p_high = np.max(closes[-120:])
                p_low = np.min(closes[-120:])
                p_range = p_high - p_low if p_high > p_low else 1.0
                price_pos = (closes[-1] - p_low) / p_range

            if not use_detail_only and recent is not None:
                for _, row in recent.iterrows():
                    buy_amt = row.get('buy_amount', 0) or 0
                    sell_amt = row.get('sell_amount', 0) or 0
                    total = buy_amt + sell_amt
                    if total <= 0:
                        continue
                    buy_ratio = buy_amt / total

                    # 买入占比 > 30% + 高位 → 假机构信号
                    if buy_ratio > 0.3 and price_pos is not None and price_pos > 0.6:
                        result['suspected'] = True
                        result['reason'] = f'高位(分位{price_pos:.0%})买入占比{buy_ratio:.0%}>30%'
                        result['confidence'] = min(1.0, result['confidence'] + 0.5)

                    # 2026-08-10 修复：单日买入占比 >40% 仅在高位才判疑似
                    # （原无论位置裸阈值误伤低位吸筹真机构——000426 低位55%买入被误判；
                    #  低位高买入占比是机构吸筹特征，由 :772 连续买入缓解逻辑处理）
                    if buy_ratio > 0.4 and price_pos is not None and price_pos > 0.6:
                        result['suspected'] = True
                        detail = f'高位(分位{price_pos:.0%})买入占比{buy_ratio:.0%}>40%'
                        result['reason'] = result['reason'] + ('; ' + detail if result['reason'] else detail)
                        result['confidence'] = min(1.0, result['confidence'] + 0.3)

                # 多日连续买入+价格未涨 → 可能是真机构吸货，降低怀疑
                if result['suspected'] and len(recent) >= 3:
                    buy_days = (recent['buy_amount'].fillna(0) > 1e6).sum()
                    if buy_days >= 3 and price_pos is not None and price_pos < 0.5:
                        result['confidence'] = max(0.0, result['confidence'] - 0.3)
                        result['reason'] += '（连续买入+低位，可能真机构）'

            # 278号方案：席位级数据增强检测
            try:
                detail_df = self.dm.get_lhb_detail(symbol)
                if detail_df is not None and not detail_df.empty:
                    detail_recent = detail_df.tail(50)
                    if 'seat_type' in detail_recent.columns and 'buy_amount' in detail_recent.columns:
                        inst_mask = detail_recent['seat_type'] == 'institution'
                        inst_buy = detail_recent[inst_mask]['buy_amount'].sum()
                        broker_buy = detail_recent[~inst_mask]['buy_amount'].sum()
                        total_buy_seat = inst_buy + broker_buy
                        if total_buy_seat > 1e6:
                            inst_ratio = inst_buy / total_buy_seat
                            # 机构买入占比极低 + 买入额很大 → 可能是营业部冒充
                            if inst_ratio < 0.15 and inst_buy < broker_buy * 0.2:
                                result['suspected'] = True
                                result['confidence'] = min(1.0, result['confidence'] + 0.4)
                                detail_msg = f'机构买入仅{inst_ratio:.0%}(席位明细)'
                                result['reason'] = result['reason'] + ('; ' + detail_msg if result['reason'] else detail_msg)
                            # 机构买入占比高 → 真机构，降低怀疑
                            elif inst_ratio > 0.6 and result['suspected']:
                                result['confidence'] = max(0.0, result['confidence'] - 0.3)
                                result['reason'] += '（机构买入占比高，真机构可能大）'
            except Exception:
                pass

            return result
        except Exception:
            return result

    def _score_chip_distribution(self, symbol: str, data: pd.DataFrame,
                                 chip_fund_ext: dict = None) -> float:
        """
        筹码分布维度（0-1.5分）

        424号§10决策②：优先消费 chip_fund_ext 预计算聚合指标（SSRP/ASR/CYQKL/concentration），
        避免重复计算完整筹码分布（RAW-2 已用 cde.estimate 算过一次 chip_bins）。
        仅当 chip_fund_ext 缺失时回退实时计算完整分布。

        Returns: 0-1.5 分
        """
        if not symbol or data is None or len(data) < 30:
            return 0.0
        try:
            indicators = None
            chip_bins = None
            if chip_fund_ext:
                # 424号§10决策②：消费预计算聚合指标
                indicators = {
                    'asr': chip_fund_ext.get('asr'),
                    'ssrp': chip_fund_ext.get('ssrp'),
                    'cyqkl': chip_fund_ext.get('cyqkl'),
                    'concentration': chip_fund_ext.get('concentration'),
                }
            else:
                # 回退：实时计算完整分布（chart 路由按需触发场景）
                from app.data.chip_distribution_service import ChipDistributionService
                cds = ChipDistributionService()
                result = cds.calculate_chip_distribution(symbol, data)
                if not result or not result.get('success'):
                    return 0.0
                indicators = result.get('indicators', {})
                chip_bins = result.get('chip_bins', [])
            # 缓存筹码数据供本类筹码评估后续消费（framework 实时路径）
            self._chip_indicators = indicators
            self._chip_bins = chip_bins

            score = 0.5  # 基础分

            # ASR 评估（浮筹比例）——451号统一：高 ASR=筹码集中/突破前蓄势（wiki《ASR指标》），
            # 不再判抛压减分（孤立高 ASR 与「浮筹高企=出货」相悖，出货须组合高位+放量）；
            # 低 ASR=筹码锁定良好。语义与 dim4 _dim_asr 一致。
            asr = indicators.get('asr', indicators.get('ASR', 50))
            if asr > 90:
                score += 0.2  # 筹码高度集中，突破前蓄势
            elif asr < 20:
                score += 0.1  # 浮筹极低，筹码锁定良好

            # SSRP 评估：当前价接近市场平均成本时加分
            ssrp = indicators.get('ssrp', indicators.get('SSRP', 0))
            current_price = float(data['close'].iloc[-1])
            if ssrp > 0:
                ssrp_deviation = abs(current_price - ssrp) / ssrp
                if ssrp_deviation < 0.03:
                    score += 0.3  # 价格在SSRP ±3%内 → 成本附近，抛压小
                elif ssrp_deviation < 0.1:
                    score += 0.1  # 价格在SSRP ±10%内
                # 价格在SSRP上方且未远离 → 做多信号
                if current_price > ssrp and ssrp_deviation < 0.15:
                    score += 0.1

            # 456号：融资成本价（margin_cost_price）进主力评分——wiki《融资成本价》解套压力位。
            # 现价站上融资成本价 → 上方融资盘抛压释放、阻力锐减 → 做多加 0.2（双份同步 dim4 _apply_margin_signal）。
            margin_cost = self._calc_margin_cost_price(symbol, current_price)
            mcp = margin_cost.get('cost_price') if margin_cost else None
            if mcp and mcp > 0:
                if current_price > mcp * 1.05:
                    score += 0.2

            # CYQKL 评估：高CYQKL = 突破确认信号
            cyqkl = indicators.get('cyqkl', indicators.get('CYQKL', 0))
            if cyqkl >= 0.5:
                score += 0.3  # 极强穿越
            elif cyqkl >= 0.3:
                score += 0.2  # 强穿越
            elif cyqkl >= 0.2:
                score += 0.1  # 中等穿越（达标）

            # 筹码峰检测（单峰密集=主力控盘）
            if chip_bins and len(chip_bins) > 0:
                ratios = [b.get('chip_ratio', 0) for b in chip_bins]
                max_ratio = max(ratios) if ratios else 0
                if max_ratio > 0.15:
                    score += 0.3  # 单峰密集

            return max(0.0, min(1.5, score))
        except Exception as e:
            logger.debug(f"筹码分布评分失败 {symbol}: {e}")
            return 0.0

    def _calc_main_force_cost(self, symbol: str, latest_close: float) -> dict:
        """
        主力集中价计算（Wiki: 主力集中价是大户平均买入成本）

        基于 moneyflow_cache 大单买入金额估算主力加权成本价。
        当股价接近主力集中价时加分，远离时扣分。

        Returns:
            {"cost_price": float, "distance_pct": float, "near_cost": bool}
        """
        try:
            mf = self.dm.get_cached_moneyflow(symbol)
            if mf is None or mf.empty or len(mf) < 3:
                return {"cost_price": 0, "distance_pct": 0, "near_cost": False}
            recent = mf.tail(20)
            # 估算主力买入总金额和总成交量
            buy_total = (recent['buy_lg_amount'].sum() + recent['buy_elg_amount'].sum())
            sell_total = (recent['sell_lg_amount'].sum() + recent['sell_elg_amount'].sum())
            net_buy = buy_total - sell_total
            if net_buy <= 0:
                return {"cost_price": 0, "distance_pct": 0, "near_cost": False}
            # 从 moneyflow_cache 估算主力加权均价
            # Tushare moneyflow 字段单位：
            #   buy_lg_vol: 手（1手=100股）
            #   buy_lg_amount / buy_elg_amount: 万元（需×10000转元）
            has_lg_vol = 'buy_lg_vol' in recent.columns
            has_lg_amt = 'buy_lg_amount' in recent.columns

            if has_lg_vol and has_lg_amt:
                lg_sum_vol = recent['buy_lg_vol'].sum() * 100  # 手→股
                lg_sum_amt = recent['buy_lg_amount'].sum() * 10000  # 万元→元
                if lg_sum_vol > 0 and lg_sum_amt > 0:
                    # 大单均价（元/股）
                    unit_price = lg_sum_amt / lg_sum_vol
                    # 超大单成交量 = 金额 / 大单均价
                    elg_sum_amt = recent['buy_elg_amount'].sum() * 10000  # 万元→元
                    est_elg_vol = elg_sum_amt / unit_price if unit_price > 0 else 0
                    total_vol = lg_sum_vol + est_elg_vol
                    avg_price = (lg_sum_amt + elg_sum_amt) / total_vol if total_vol > 0 else latest_close
                else:
                    avg_price = latest_close
            else:
                # 退回到用 open/high/low/close 均值估算
                avg_prices = (recent['open'] + recent['high'] + recent['low'] + recent['close']) / 4
                avg_price = float(avg_prices.tail(5).mean()) if not avg_prices.empty else latest_close
            avg_price = float(avg_price) if avg_price > 0 else latest_close
            distance = (latest_close - avg_price) / avg_price if avg_price > 0 else 0
            return {
                "cost_price": round(avg_price, 2),
                "distance_pct": round(distance * 100, 2),
                "near_cost": abs(distance) < 0.05,  # 5%内视为接近主力成本
            }
        except Exception:
            return {"cost_price": 0, "distance_pct": 0, "near_cost": False}

    def _calc_margin_cost_price(self, symbol: str, latest_close: float) -> dict:
        """计算融资成本价（散户融资买入的平均成本）
        基于 margin_cache 的 rzmje(融资买入额) 和当日均价估算。
        Returns:
            {"cost_price": float | None, "distance_pct": float | None}
        """
        try:
            margin_df = self.dm.get_cached_margin(symbol)
            if margin_df is None or margin_df.empty:
                return {"cost_price": None, "distance_pct": None}
            df = margin_df.tail(60).copy()
            if 'rzye' not in df.columns:
                return {"cost_price": None, "distance_pct": None}
            buy_mask = df['rzmje'].fillna(0) > 0 if 'rzmje' in df.columns else None
            if buy_mask is None or buy_mask.sum() < 3:
                return {"cost_price": None, "distance_pct": None}
            df_buy = df[buy_mask].copy()
            avg_prices = (df_buy['open'].fillna(latest_close)
                         + df_buy['high'].fillna(latest_close)
                         + df_buy['low'].fillna(latest_close)
                         + df_buy['close'].fillna(latest_close)) / 4
            weights = df_buy['rzmje'].fillna(0)
            if weights.sum() <= 0:
                return {"cost_price": None, "distance_pct": None}
            cost_price = (weights * avg_prices).sum() / weights.sum()
            distance_pct = (latest_close - cost_price) / cost_price * 100 if cost_price > 0 else None
            return {
                "cost_price": round(float(cost_price), 2),
                "distance_pct": round(float(distance_pct), 2) if distance_pct is not None else None,
            }
        except Exception:
            return {"cost_price": None, "distance_pct": None}

    def get_tags(self, symbol: str) -> dict:
        """返回主力资金标签"""
        tags = {}
        try:
            mf_score = self._score_moneyflow(symbol)
            if mf_score >= 2.0:
                tags['fund_flow'] = '5d_inflow'
            elif mf_score >= 1.0:
                tags['fund_flow'] = 'mixed'
            else:
                tags['fund_flow'] = 'none'

            # 2026-08-10 修复：传入真实 K 线（原传空 DataFrame 致 price_pos=None，
            # 假机构检测的"高位"约束失效 + 连续买入缓解逻辑失效 → capital_nature 全 unknown）
            try:
                _df = self.dm.get_cached_daily_data(symbol)
            except Exception:
                _df = pd.DataFrame()
            lhb_score = self._score_lhb(symbol, _df)
            if lhb_score >= 0.5:
                tags['capital_nature'] = 'institutional'
            elif lhb_score >= 0.2:
                tags['capital_nature'] = 'hot_money'
            elif lhb_score > -0.5:
                # 2026-08-10 修复：轻微怀疑（-0.5~0.2）给 hot_money（营业部/游资特征），
                # 不再一律 unknown——保留区分度（原 suspected 扣分后全落 unknown）
                tags['capital_nature'] = 'hot_money'
            else:
                tags['capital_nature'] = 'unknown'
        except Exception:
            pass
        return tags


