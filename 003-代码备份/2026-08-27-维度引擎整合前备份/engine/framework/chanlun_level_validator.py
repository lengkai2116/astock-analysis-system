"""
ChanlunLevelValidator — 缠论级别递归验证器

基于缠中说禅买卖点级别定理:
  "大级别买卖点必然是次级别以下某一级别的买卖点"

实现:
  - 将日线K线重采样为周线/月线
  - 对每个级别运行 ChanlunAnalyzer
  - 跨级别验证买卖点有效性
  - 输出级别递归评分调整
"""
import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ChanlunLevelValidator:
    """缠论级别递归验证器"""

    # 买卖点类型权重（高级别信号权重更高）
    LEVEL_WEIGHTS = {
        'monthly': 3.0,
        'weekly': 2.0,
        'daily': 1.0,
    }

    def validate(self, daily_df: pd.DataFrame) -> Dict:
        """
        多级别缠论分析 + 级别定理验证

        Args:
            daily_df: 日线OHLCV DataFrame（含 trade_date/open/high/low/close/vol）

        Returns:
            {
                "signals": { "daily": {...}, "weekly": {...}, "monthly": {...} },
                "validation": { "confirmed": bool, "level": str, "adjustment": float },
                "cross_score": float,  # 级别验证后的综合评分调整
                "details": [...],
            }
        """
        if daily_df is None or len(daily_df) < 30:
            return self._empty_result("数据不足")

        results = {}

        # 1. 日线级别分析
        try:
            daily_cl = self._analyze_level(daily_df)
            results['daily'] = daily_cl
        except Exception as e:
            logger.debug(f"日线缠论分析失败: {e}")
            results['daily'] = {}

        # 2. 周线级别（从日线重采样）
        try:
            weekly_df = self._resample_to_weekly(daily_df)
            if len(weekly_df) >= 10:
                weekly_cl = self._analyze_level(weekly_df)
                results['weekly'] = weekly_cl
        except Exception as e:
            logger.debug(f"周线缠论分析失败: {e}")
            results['weekly'] = {}

        # 3. 月线级别
        try:
            monthly_df = self._resample_to_monthly(daily_df)
            if len(monthly_df) >= 6:
                monthly_cl = self._analyze_level(monthly_df)
                results['monthly'] = monthly_cl
        except Exception as e:
            logger.debug(f"月线缠论分析失败: {e}")
            results['monthly'] = {}

        # 4. 级别定理验证
        validation = self._cross_validate(results)
        cross_score = self._compute_cross_score(results, validation)

        return {
            "signals": results,
            "validation": validation,
            "cross_score": round(cross_score, 4),
            "details": self._build_details(results, validation),
        }

    def _resample_to_weekly(self, df: pd.DataFrame) -> pd.DataFrame:
        """日线→周线重采样"""
        df = df.copy()
        if 'trade_date' in df.columns:
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            df = df.set_index('trade_date')
        elif not isinstance(df.index, pd.DatetimeIndex):
            return df

        # 按周聚合
        weekly = df.resample('W').agg({
            'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last',
            'vol': 'sum', 'amount': 'sum',
        }).dropna(subset=['close'])
        weekly = weekly.reset_index()
        weekly['trade_date'] = weekly['trade_date'].dt.strftime('%Y-%m-%d')
        return weekly

    def _resample_to_monthly(self, df: pd.DataFrame) -> pd.DataFrame:
        """日线→月线重采样"""
        df = df.copy()
        if 'trade_date' in df.columns:
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            df = df.set_index('trade_date')
        elif not isinstance(df.index, pd.DatetimeIndex):
            return df

        monthly = df.resample('M').agg({
            'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last',
            'vol': 'sum', 'amount': 'sum',
        }).dropna(subset=['close'])
        monthly = monthly.reset_index()
        monthly['trade_date'] = monthly['trade_date'].dt.strftime('%Y-%m-%d')
        return monthly

    def _analyze_level(self, df: pd.DataFrame) -> Dict:
        """对单个级别的K线运行缠论分析"""
        from app.engine.framework.chanlun_strategy import ChanlunAnalyzer, ChanlunScorer

        analyzer = ChanlunAnalyzer()
        result = analyzer.analyze(df)

        scorer = ChanlunScorer()
        latest_close = float(df['close'].iloc[-1])
        score_result = scorer.score(result, latest_close)

        return {
            "score": score_result.get('score', 50),
            "signal": score_result.get('signal', 'HOLD'),
            "buy_points": result.get('buy_points', []),
            "sell_points": result.get('sell_points', []),
            "zhongshu_count": len(result.get('zhongshu_list', [])),
            "trend": result.get('trend', {}).get('direction', 'unknown'),
        }

    def _cross_validate(self, signals: Dict) -> Dict:
        """级别定理验证

        核心逻辑:
        - 如果日线有买点且月线趋势向上 → 买点有效 ↑
        - 如果日线有买点但月线趋势向下 → 买点待验证 ↓
        - 如果日线和周线同时有买点 → 共振确认 ↑↑
        """
        daily = signals.get('daily', {})
        weekly = signals.get('weekly', {})
        monthly = signals.get('monthly', {})

        daily_signal = daily.get('signal', 'HOLD')
        weekly_signal = weekly.get('signal', 'HOLD')
        monthly_signal = monthly.get('signal', 'HOLD')

        daily_score = daily.get('score', 50)
        weekly_score = weekly.get('score', 50)
        monthly_score = monthly.get('score', 50)

        # 判断趋势方向
        monthly_trend = monthly.get('trend', 'unknown')
        weekly_trend = weekly.get('trend', 'unknown')

        # 买点确认
        buy_confirmed = False
        sell_confirmed = False
        level = 'daily'
        adjustment = 0.0
        reasons = []

        # 检查各级别的买卖点数量
        daily_buy = len(daily.get('buy_points', []))
        weekly_buy = len(weekly.get('buy_points', []))
        monthly_buy = len(monthly.get('buy_points', []))
        daily_sell = len(daily.get('sell_points', []))
        weekly_sell = len(weekly.get('sell_points', []))

        # 级别定理: 大级别趋势决定小级别买卖点有效性
        if monthly_trend == 'up' and daily_buy > 0:
            buy_confirmed = True
            level = 'monthly'
            adjustment = 0.10
            reasons.append("月线趋势向上+日线买点→买点确认")
        elif weekly_trend == 'up' and daily_buy > 0:
            buy_confirmed = True
            level = 'weekly'
            adjustment = 0.05
            reasons.append("周线趋势向上+日线买点→买点确认")

        # 多级别共振
        if weekly_buy > 0 and daily_buy > 0:
            buy_confirmed = True
            adjustment += 0.08
            reasons.append("周线+日线同时有买点→共振加强")
            level = 'weekly'

        if monthly_trend == 'down' and daily_buy > 0:
            adjustment -= 0.10
            reasons.append("月线趋势向下，日线买点待验证")

        if daily_sell > 0 and weekly_sell > 0:
            sell_confirmed = True
            adjustment -= 0.08
            reasons.append("日线+周线同时有卖点→卖出确认")

        return {
            "confirmed": buy_confirmed or sell_confirmed,
            "buy_confirmed": buy_confirmed,
            "sell_confirmed": sell_confirmed,
            "level": level,
            "adjustment": round(adjustment, 4),
            "reasons": reasons,
        }

    def _compute_cross_score(self, signals: Dict, validation: Dict) -> float:
        """计算级别验证后的综合评分调整

        结合各级别评分，按级别权重加权，再加上验证调整。
        """
        weighted_sum = 0
        total_weight = 0

        for level, weight in self.LEVEL_WEIGHTS.items():
            sig = signals.get(level, {})
            score = sig.get('score', 50)
            if score > 0:
                weighted_sum += (score / 100.0) * weight  # 归一化到0-1
                total_weight += weight

        if total_weight == 0:
            return 0.5

        base = weighted_sum / total_weight
        adj = validation.get('adjustment', 0)
        return max(0, min(1, base + adj))

    def _build_details(self, signals: Dict, validation: Dict) -> List[str]:
        """构建人类可读的验证细节"""
        details = []
        for level in ['monthly', 'weekly', 'daily']:
            sig = signals.get(level, {})
            if sig:
                n_buy = len(sig.get('buy_points', []))
                n_sell = len(sig.get('sell_points', []))
                details.append(
                    f"{level}: score={sig.get('score', '-')} "
                    f"{'↑' if sig.get('trend')=='up' else '↓' if sig.get('trend')=='down' else '→'} "
                    f"买{n_buy}卖{n_sell}"
                )
        details.extend(validation.get('reasons', []))
        return details

    def _empty_result(self, reason: str) -> Dict:
        return {
            "signals": {},
            "validation": {"confirmed": False, "level": "none",
                           "adjustment": 0.0, "reasons": [reason]},
            "cross_score": 0.5,
            "details": [reason],
        }
