"""
趋势结构检测器（308号 P3 / 309号 S7 二期）
========================================
实现 308号§3.2 的右侧反转确认信号：
  1. 123法则（做多三步）：
     假设1：价格向上突破下降趋势线 → 下跌趋势结束
     假设2：回调但不创新低（回调不破前低）→ 底部抬高
     假设3：向上突破前期反弹高点 → 反向推动浪形成
  2. 趋势线突破二日原则：当日收盘突破 + 次日仍在外 = 突破确认

输出：
  signal: '123_buy_breakout' | 'higher_low' | 'none'
  strength: 'strong'（假设1+2+3 齐备）| 'basic'（部分满足）
  供闸门2 `_check_right_side_confirm` STEP 3 增强确认消费
"""
import numpy as np
import pandas as pd


class TrendStructureDetector:
    """基于日线高低点序列的趋势结构/123法则检测器"""

    def detect(self, df: pd.DataFrame) -> dict | None:
        """检测趋势结构信号

        Args:
            df: 日线 DataFrame（需含 close/high/low）

        Returns:
            {signal, strength, detail} 或 None（数据不足）
        """
        try:
            if df is None or len(df) < 30:
                return None
            closes = df['close'].astype(float).values
            highs = df['high'].astype(float).values if 'high' in df.columns else closes
            lows = df['low'].astype(float).values if 'low' in df.columns else closes

            # ── 假设2：回调不创新低（近3日低点 vs 近40日最低点，底部抬高 ≥1%） ──
            recent_low = float(np.min(lows[-3:]))
            older_low = float(np.min(lows[-40:-3])) if len(lows) >= 43 else float(np.min(lows[:-3]))
            higher_low = recent_low > older_low * 1.01  # 底部抬高 ≥1%

            # ── 假设3：突破前期反弹高点（反转前最近一次反弹的高点） ──
            base_highs = highs[-40:-3]
            # 取反转前最近10日的局部高点（排除下降趋势起点，避免参照整段最高点）
            if len(base_highs) >= 10:
                prev_swing_high = float(np.max(base_highs[-10:]))
            else:
                prev_swing_high = float(np.max(base_highs))
            breakout_high = closes[-1] > prev_swing_high * 1.01

            # ── 假设1 + 二日原则：突破下降趋势线 ──
            trend_break = self._check_trendline_break(highs, lows, closes)

            signal, strength, detail = 'none', 'basic', []
            if trend_break:
                detail.append('假设1:突破下降趋势线')
            if higher_low:
                detail.append('假设2:回调不创新低')
            if breakout_high:
                detail.append('假设3:突破前期反弹高点')

            if trend_break and higher_low and breakout_high:
                signal, strength = '123_buy_breakout', 'strong'
            elif trend_break and higher_low:
                signal, strength = 'higher_low', 'basic'
            elif higher_low and breakout_high:
                signal, strength = 'higher_low', 'basic'

            return {'signal': signal, 'strength': strength, 'detail': detail}
        except Exception:
            return None

    def _check_trendline_break(self, highs, lows, closes) -> bool:
        """下降趋势线突破检测（二日原则）

        在排除最近3日的窗口中找两个显著高点连下降趋势线，
        判断最后两日收盘是否连续在趋势线上方（突破确认）。
        """
        n = len(closes)
        if n < 25:
            return False
        # 排除最近 3 日（反转段），在前段找下降趋势线
        base = highs[:-3]
        if len(base) < 10:
            return False
        if len(base) > 20:
            p2 = int(np.argmax(base[-20:])) + (len(base) - 20)  # 前段最近高点（绝对下标）
        else:
            p2 = int(np.argmax(base))
        if p2 <= 2:
            return False
        p1 = int(np.argmax(base[:p2]))  # 更早的高点
        h1, h2 = base[p1], base[p2]
        # 下降趋势线要求高点递减：h1 > h2
        if h1 <= h2:
            return False
        # 线性外推趋势线到最新日（用前段坐标 → 全序列坐标）
        slope = (h2 - h1) / (p2 - p1)
        trend_val_at_now = h2 + slope * (n - 3 - p2)  # 前段最后位置 = n-3-1，再外推1步到 n-2
        trend_val_yesterday = h2 + slope * (n - 4 - p2)
        # 二日原则：最后两日收盘均在趋势线上方
        return closes[-1] > trend_val_at_now and closes[-2] > trend_val_yesterday
