"""
交易与策略信号匹配服务 — P3.2

功能：
  1. 对每笔交易查找其交易日前后的系统策略信号
  2. 计算匹配度评分（0-100）
  3. 返回匹配详情（信号方向、置信度、价格区间）
"""
import logging
from typing import Dict, List, Optional
from datetime import date, timedelta

from app import db
from app.models.trade import Trade
from app.models.strategy import StrategyOutput
from app.models.verification import SignalRecord

logger = logging.getLogger(__name__)


class SignalMatchService:
    """交易-策略信号匹配服务"""

    MATCH_WINDOW_DAYS = 3  # 交易日前 N 天内查找信号

    def match_trade(self, trade: Trade) -> Optional[Dict]:
        """
        对单笔交易进行信号匹配

        Returns:
            {
                'matched': bool,
                'signal_id': int or None,
                'signal_type': str or None,
                'signal_confidence': float or None,
                'match_score': float (0-100),
                'match_detail': str,
            }
        """
        # 查找交易日前 N 天内的策略信号
        start = trade.trade_date - timedelta(days=self.MATCH_WINDOW_DAYS)
        end = trade.trade_date

        # 先从 StrategyOutput 表查找
        signals = StrategyOutput.query.filter(
            StrategyOutput.ts_code == trade.ts_code,
            StrategyOutput.signal_date >= start,
            StrategyOutput.signal_date <= end,
        ).order_by(StrategyOutput.signal_date.desc()).all()

        # 再从 SignalRecord 表补充
        if not signals:
            sig_records = SignalRecord.query.filter(
                SignalRecord.ts_code == trade.ts_code,
                SignalRecord.signal_date >= start,
                SignalRecord.signal_date <= end,
            ).order_by(SignalRecord.signal_date.desc()).all()
        else:
            sig_records = []

        result = {
            'matched': False,
            'signal_id': None,
            'signal_type': None,
            'signal_confidence': None,
            'match_score': 0.0,
            'match_detail': '未找到附近信号',
        }

        # 评估买入匹配
        if trade.direction == '买入':
            best = None
            for s in signals:
                if s.signal.value in ('bullish', 'watch'):
                    score = self._calc_buy_score(trade, s)
                    if best is None or score > best['score']:
                        best = {'id': s.id, 'type': s.signal.value,
                                'confidence': float(s.confidence or 0),
                                'score': score,
                                'detail': f'StrategyOutput BULLISH({score:.0f}分)'}
            if best:
                return best

            for r in sig_records:
                if r.signal_type in ('BULLISH', 'WATCH'):
                    score = 60.0  # SignalRecord 匹配基础分
                    if best is None or score > best.get('score', 0):
                        best = {'id': r.id, 'type': r.signal_type,
                                'confidence': float(r.confidence or 0),
                                'score': score,
                                'detail': f'SignalRecord {r.signal_type}({score:.0f}分)'}
            if best:
                return best

            # 无信号：非策略交易
            return {
                'matched': False, 'signal_id': None,
                'signal_type': None, 'signal_confidence': None,
                'match_score': 20.0,
                'match_detail': '无策略信号支持（非策略交易）',
            }

        # 评估卖出匹配
        elif trade.direction == '卖出':
            best = None
            for s in signals:
                if s.signal.value in ('bearish', 'neutral'):
                    score = self._calc_sell_score(trade, s)
                    if best is None or score > best['score']:
                        best = {'id': s.id, 'type': s.signal.value,
                                'confidence': float(s.confidence or 0),
                                'score': score,
                                'detail': f'StrategyOutput {s.signal.value}({score:.0f}分)'}

            if not best:
                # 检查是否有止盈/止损触发（同方向买入信号已有盈利）
                buy_signals = StrategyOutput.query.filter(
                    StrategyOutput.ts_code == trade.ts_code,
                    StrategyOutput.signal.value.in_(['bullish', 'watch']),
                    StrategyOutput.signal_date >= start,
                    StrategyOutput.signal_date <= trade.trade_date,
                ).order_by(StrategyOutput.signal_date.desc()).limit(1).all()

                if buy_signals:
                    s = buy_signals[0]
                    entry_low = float(s.entry_zone_low or trade.price * 0.97)
                    profit_pct = (float(trade.price) - entry_low) / entry_low
                    score = min(70 + profit_pct * 100, 95)
                    best = {
                        'id': s.id, 'type': '止盈' if profit_pct > 0.05 else '止损',
                        'confidence': float(s.confidence or 0),
                        'score': round(score, 1),
                        'detail': f'基于买入信号{s.id}的{"止盈" if profit_pct > 0.05 else "止损"}操作',
                    }

            if best:
                return best

            return {
                'matched': False, 'signal_id': None,
                'signal_type': None, 'signal_confidence': None,
                'match_score': 30.0,
                'match_detail': '卖出无直接信号匹配（可能是自主决策）',
            }

        return result

    def _calc_buy_score(self, trade: Trade, signal: StrategyOutput) -> float:
        """计算买入匹配得分"""
        score = 60.0  # 基础分
        # 日期接近加分
        days_diff = abs((trade.trade_date - signal.signal_date).days)
        score += max(0, (self.MATCH_WINDOW_DAYS - days_diff) * 10)
        # 价格在 entry_zone 内加分
        if signal.entry_zone_low and signal.entry_zone_high:
            low, high = float(signal.entry_zone_low), float(signal.entry_zone_high)
            if low <= float(trade.price) <= high:
                score += 15
            elif abs(float(trade.price) - low) / low < 0.03:
                score += 8
        # 高置信度加分
        if signal.confidence and float(signal.confidence) > 0.6:
            score += 10
        return round(min(score, 100), 1)

    def _calc_sell_score(self, trade: Trade, signal: StrategyOutput) -> float:
        """计算卖出匹配得分"""
        score = 60.0
        days_diff = abs((trade.trade_date - signal.signal_date).days)
        score += max(0, (self.MATCH_WINDOW_DAYS - days_diff) * 8)
        # 价格在 target_zone 内加分
        if signal.target_zone_low and signal.target_zone_high:
            low, high = float(signal.target_zone_low), float(signal.target_zone_high)
            if low <= float(trade.price) <= high:
                score += 20
            elif abs(float(trade.price) - high) / high < 0.05:
                score += 10
        return round(min(score, 100), 1)

    def match_all_pending(self) -> int:
        """批量匹配所有未匹配的信号"""
        pending = Trade.query.filter(Trade.matched_signal_id.is_(None)).all()
        count = 0
        for t in pending:
            result = self.match_trade(t)
            if result.get('signal_id'):
                t.matched_signal_id = result['signal_id']
                t.matched_signal_type = result.get('signal_type', '')
                t.matched_signal_confidence = result.get('signal_confidence')
                t.match_score = result.get('match_score')
                count += 1
        if count:
            db.session.commit()
        return count
