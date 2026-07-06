import logging
"""
筹码分布策略 - 模块化实现
参考 Algorithm Framework 的设计
"""
from typing import Dict, List, Optional, Any
from datetime import datetime
import pandas as pd
import numpy as np
import logging

from . import (
    UniverseSelectionModel,
    AlphaModel,
    PortfolioConstructionModel,
    RiskManagementModel,
    ExecutionModel,
    Insight
)


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
