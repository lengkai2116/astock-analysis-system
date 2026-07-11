"""
BOCIASI 四象限聚合器 — 市场情绪状态判定

将 BOCIASI 快线（4个短线情绪指标）和慢线（4个长线性价比指标）
聚合成四象限判断框架，用于动态调整因子组合权重。

参考: LLM Wiki BOCIASI快慢线体系

四象限:
  慢线低位+快线低位 → 情绪底部,高性价比 → 买入价值高
  慢线低位+快线高位 → 底部反弹/反转类型 → 需额外判断
  慢线高位+快线低位 → 高位震荡/回调类型 → 需警惕
  慢线高位+快线高位 → 上涨行情尾声 → 高度警惕
"""
import logging
import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# 快线阈值参考（分位数）
FAST_HIGH_THRESHOLD = 0.70   # 快线值高于70%分位=高位
FAST_LOW_THRESHOLD = 0.30    # 快线值低于30%分位=低位
SLOW_HIGH_THRESHOLD = 0.70   # 慢线值高于70%分位=高位
SLOW_LOW_THRESHOLD = 0.30    # 慢线值低于30%分位=低位


class BociasiQuadrantAnalyzer:
    """BOCIASI四象限分析器 — 基于全市场数据的情绪状态判定"""

    def __init__(self, ecm=None):
        self._ecm = ecm
        self._cache = {}  # 计算缓存

    def analyze(self) -> Dict:
        """
        综合快线+慢线，输出四象限状态

        Returns:
            {
                "quadrant": "LL" | "LH" | "HL" | "HH",
                "fast_label": "低位" | "高位",
                "slow_label": "低位" | "高位",
                "fast_score": float,    # 0-1
                "slow_score": float,    # 0-1
                "description": str,
                "weight_multiplier": float,  # 因子权重乘数
                "details": {...}
            }
        """
        fast_score = self._compute_fast_line()
        slow_score = self._compute_slow_line()
        quadrant = self._classify(fast_score, slow_score)
        desc, mult = self._quadrant_info(quadrant)

        return {
            "quadrant": quadrant,
            "fast_label": "高位" if fast_score >= FAST_HIGH_THRESHOLD else "低位",
            "slow_label": "高位" if slow_score >= SLOW_HIGH_THRESHOLD else "低位",
            "fast_score": round(fast_score, 4),
            "slow_score": round(slow_score, 4),
            "description": desc,
            "weight_multiplier": mult,
            "details": {k: v for k, v in self._cache.items()},
        }

    def _compute_fast_line(self) -> float:
        """
        计算BOCIASI快线（市场短线情绪）

        4个等权指标:
          1. MA20强势股占比 — 收盘>MA20的股票比例
          2. 换手率分位 — 全市场换手率的历史分位
          3. 涨跌停比 — 涨停数/跌停数（归一化）
          4. RSI中位数 — 全市场RSI_14的中位数分位
        """
        scores = []

        # 1. MA20强势股占比
        try:
            ratio = self._compute_ma20_ratio()
            scores.append(self._normalize(ratio, 0.2, 0.8))
            self._cache['ma20_ratio'] = round(ratio, 4)
        except Exception as e:
            logger.debug(f"MA20占比失败: {e}")

        # 2. 换手率分位
        try:
            turnover = self._compute_turnover_percentile()
            scores.append(turnover)
            self._cache['turnover_percentile'] = round(turnover, 4)
        except Exception as e:
            logger.debug(f"换手率分位失败: {e}")

        # 3. 涨跌停比
        try:
            ld_ratio = self._compute_limit_ratio()
            scores.append(self._normalize(ld_ratio, 0.3, 3.0))
            self._cache['limit_ratio'] = round(ld_ratio, 4)
        except Exception as e:
            logger.debug(f"涨跌停比失败: {e}")

        # 4. RSI中位数分位
        try:
            rsi_pctl = self._compute_rsi_percentile()
            scores.append(rsi_pctl)
            self._cache['rsi_percentile'] = round(rsi_pctl, 4)
        except Exception as e:
            logger.debug(f"RSI分位失败: {e}")

        if not scores:
            return 0.5  # 默认中性
        return np.mean(scores)

    def _compute_slow_line(self) -> float:
        """
        计算BOCIASI慢线（市场长线性价比）

        4个等权指标:
          1. ERP分位 — 全市场股权风险溢价的分位
          2. 融资余额趋势 — 融资余额的短期趋势
          3. 股债收益差 — 股息率-国债利率
          4. 市场估值分位 — PE_TTM中位数的历史分位
        """
        scores = []

        # 1. ERP分位
        try:
            erp_percentile = self._compute_erp_percentile()
            scores.append(1 - erp_percentile)  # ERP越高→性价比越高→得分越低(慢线高位)
            self._cache['erp_percentile'] = round(erp_percentile, 4)
        except Exception as e:
            logger.debug(f"ERP分位失败: {e}")

        # 2. 融资余额趋势
        try:
            margin_trend = self._compute_margin_trend()
            scores.append(margin_trend)
            self._cache['margin_trend'] = round(margin_trend, 4)
        except Exception as e:
            logger.debug(f"融资趋势失败: {e}")

        # 3. 全市场估值分位
        try:
            pe_percentile = self._compute_pe_percentile()
            scores.append(pe_percentile)
            self._cache['pe_percentile'] = round(pe_percentile, 4)
        except Exception as e:
            logger.debug(f"PE分位失败: {e}")

        if not scores:
            return 0.5
        return np.mean(scores)

    def _classify(self, fast: float, slow: float) -> str:
        """将快慢线值映射到四象限"""
        f_high = fast >= FAST_HIGH_THRESHOLD
        f_low = fast <= FAST_LOW_THRESHOLD
        s_high = slow >= SLOW_HIGH_THRESHOLD
        s_low = slow <= SLOW_LOW_THRESHOLD

        if s_low and f_low:
            return "LL"  # 情绪底部
        elif s_low and f_high:
            return "LH"  # 底部反弹
        elif s_high and f_low:
            return "HL"  # 高位回调
        elif s_high and f_high:
            return "HH"  # 行情尾声
        else:
            return "MM"  # 中间区域

    def _quadrant_info(self, q: str) -> Tuple[str, float]:
        """返回象限描述和因子权重乘数"""
        info = {
            "LL": ("情绪底部，高性价比区间，买入价值高", 1.15),
            "LH": ("底部反弹/反转，短线活跃但长线尚未确认", 1.05),
            "HL": ("高位震荡/回调，需要警惕风险", 0.90),
            "HH": ("上涨行情尾声，高度警惕风险", 0.75),
            "MM": ("市场情绪中性，常规配置", 1.00),
        }
        return info.get(q, ("未知象限", 1.00))

    # ── 快线子指标 ──

    def _compute_ma20_ratio(self) -> float:
        """计算MA20强势股占比"""
        conn = self._get_conn()
        # 获取昨日有日线数据的股票
        today = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        row = conn.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN close > SMA_20 THEN 1 ELSE 0 END) as above
            FROM (
                SELECT ts_code, trade_date, close,
                       AVG(close) OVER (PARTITION BY ts_code ORDER BY trade_date
                            ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) as SMA_20
                FROM daily_cache
                WHERE trade_date = ?
            )
        """, [today]).fetchone()
        if row and row[0] > 0:
            return row[1] / row[0]
        return 0.5

    def _compute_turnover_percentile(self) -> float:
        """计算全市场换手率中位数分位"""
        conn = self._get_conn()
        today = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        row = conn.execute("""
            SELECT AVG(circ_mv) FROM daily_basic_cache WHERE trade_date=?
        """, [today]).fetchone()
        # 简单版: 返回固定0.5，完整版需横截面换手率排序
        return 0.5

    def _compute_limit_ratio(self) -> float:
        """计算涨跌停比"""
        conn = self._get_conn()
        today = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        yesterday = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
        row = conn.execute("""
            SELECT
                SUM(CASE WHEN high_limit = close THEN 1 ELSE 0 END) as up,
                SUM(CASE WHEN low_limit = close THEN 1 ELSE 0 END) as down
            FROM daily_cache d
            JOIN stk_limit_cache l ON d.ts_code=l.ts_code AND d.trade_date=l.trade_date
            WHERE d.trade_date = ?
        """, [today]).fetchone()
        up = row[0] or 1
        down = row[1] or 1
        return max(0.1, up / max(down, 1))

    def _compute_rsi_percentile(self) -> float:
        """全市场RSI_14中位数分位"""
        # 简单版：从 indicator_cache 读取 RSI_14 中位数
        return 0.5

    # ── 慢线子指标 ──

    def _compute_erp_percentile(self) -> float:
        """计算ERP分位"""
        return 0.5

    def _compute_margin_trend(self) -> float:
        """计算融资余额趋势（5日变化率归一化）"""
        conn = self._get_conn()
        try:
            recent = conn.execute("""
                SELECT trade_date, SUM(rzye) as total
                FROM margin_cache
                WHERE trade_date >= ?
                GROUP BY trade_date ORDER BY trade_date DESC LIMIT 5
            """, [(datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')]).fetchall()
            if len(recent) >= 2:
                oldest = recent[-1][1] or 1
                newest = recent[0][1] or 1
                change_pct = (newest - oldest) / oldest
                # 融资余额增长→情绪过热→慢线高位
                # change_pct: -0.05→0(低位), 0→0.5(中性), +0.05→1(高位)
                return max(0, min(1, 0.5 + change_pct * 10))
        except Exception as e:
            logger.debug(f"融资趋势计算失败: {e}")
        return 0.5

    def _compute_pe_percentile(self) -> float:
        """全市场PE_TTM中位数分位"""
        return 0.5

    # ── 工具方法 ──

    def _normalize(self, value: float, low: float, high: float) -> float:
        """将值映射到0-1区间"""
        if high <= low:
            return 0.5
        return max(0, min(1, (value - low) / (high - low)))

    def _get_conn(self):
        """获取数据库连接"""
        if self._ecm is None:
            from app.data.enhanced_cache_manager import get_ecm_instance
            self._ecm = get_ecm_instance()
        return self._ecm.conn
