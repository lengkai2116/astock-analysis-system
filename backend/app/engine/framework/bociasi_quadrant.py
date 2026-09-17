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
from datetime import datetime, timedelta
from typing import Dict, Tuple

import numpy as np

from app.data.mixins import DataAwareMixin

logger = logging.getLogger(__name__)


# 快线阈值参考（分位数）
FAST_HIGH_THRESHOLD = 0.70   # 快线值高于70%分位=高位
FAST_LOW_THRESHOLD = 0.30    # 快线值低于30%分位=低位
SLOW_HIGH_THRESHOLD = 0.70   # 慢线值高于70%分位=高位
SLOW_LOW_THRESHOLD = 0.30    # 慢线值低于30%分位=低位


class BociasiQuadrantAnalyzer(DataAwareMixin):
    """BOCIASI四象限分析器 — 基于全市场数据的情绪状态判定"""

    def __init__(self, ecm=None, market_stats: dict = None):
        """412号方案B2 v3.0：market_stats由dim1通过data_context传入，不再读daemon内存。"""
        self._dm = None
        self._ecm = ecm
        self._cache = {}
        self._market_stats = market_stats or {}  # 计算缓存

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

        411号Phase 10：优先从_market_stats_cache读取预计算值，回退SQL查询。
        4个等权指标:
          1. MA20强势股占比 — 收盘>MA20的股票比例
          2. 换手率分位 — 全市场换手率的历史分位
          3. 涨跌停比 — 涨停数/跌停数（归一化）
          4. RSI中位数 — 全市场RSI_14的中位数分位
        """
        scores = []

        # 1. MA20强势股占比
        try:
            ratio = self._market_stats.get('ma20_ratio')
            if ratio is not None:
                scores.append(self._normalize(ratio, 0.2, 0.8))
                self._cache['ma20_ratio'] = round(ratio, 4)
            else:
                ratio = self._compute_ma20_ratio()
                scores.append(self._normalize(ratio, 0.2, 0.8))
                self._cache['ma20_ratio'] = round(ratio, 4)
        except Exception as e:
            logger.debug(f"MA20占比失败: {e}")

        # 2. 换手率分位
        try:
            turnover = self._market_stats.get('turnover_percentile')
            if turnover is not None:
                scores.append(turnover)
                self._cache['turnover_percentile'] = round(turnover, 4)
            else:
                turnover = self._compute_turnover_percentile()
                scores.append(turnover)
                self._cache['turnover_percentile'] = round(turnover, 4)
        except Exception as e:
            logger.debug(f"换手率分位失败: {e}")

        # 3. 涨跌停比
        try:
            ld_ratio = self._market_stats.get('limit_ratio')
            if ld_ratio is not None:
                scores.append(self._normalize(ld_ratio, 0.3, 3.0))
                self._cache['limit_ratio'] = round(ld_ratio, 4)
            else:
                ld_ratio = self._compute_limit_ratio()
                scores.append(self._normalize(ld_ratio, 0.3, 3.0))
                self._cache['limit_ratio'] = round(ld_ratio, 4)
        except Exception as e:
            logger.debug(f"涨跌停比失败: {e}")

        # 4. RSI中位数分位
        try:
            rsi_pctl = self._market_stats.get('rsi_percentile')
            if rsi_pctl is not None:
                scores.append(rsi_pctl)
                self._cache['rsi_percentile'] = round(rsi_pctl, 4)
            else:
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

        4个等权指标（知识库 research-bociasicscv190a:58-60）:
          1. ERP分位 — 全市场股权风险溢价分位（= 1/PE - 10年国债）
          2. 融资余额趋势 — 融资余额的短期趋势
          3. 股债收益差 — 全市场中位股息率 - 10年国债利率
          4. 股债位置差 — 混合基金指数净值缩放后的趋势线（知识库定义；
             系统暂无混合基金净值数据源，T3a-2 降级声明未落地）
        """
        scores = []

        # 1. ERP分位（= 1/PE - 国债；daemon 预计算已减国债）
        try:
            erp_percentile = self._market_stats.get('erp_percentile')
            if erp_percentile is not None:
                scores.append(1 - erp_percentile)
                self._cache['erp_percentile'] = round(erp_percentile, 4)
            else:
                erp_percentile = self._compute_erp_percentile()
                scores.append(1 - erp_percentile)  # ERP越高→性价比越高→得分越低(慢线高位)
                self._cache['erp_percentile'] = round(erp_percentile, 4)
        except Exception as e:
            logger.debug(f"ERP分位失败: {e}")

        # 2. 融资余额趋势
        try:
            margin_trend = self._market_stats.get('margin_trend')
            if margin_trend is not None:
                scores.append(margin_trend)
                self._cache['margin_trend'] = round(margin_trend, 4)
            else:
                margin_trend = self._compute_margin_trend()
                scores.append(margin_trend)
                self._cache['margin_trend'] = round(margin_trend, 4)
        except Exception as e:
            logger.debug(f"融资趋势失败: {e}")

        # 3. 股债收益差分位（= 中位股息率 - 国债；收益差越高→性价比越高→得分越低=慢线高位，
        #    与 ERP 同方向处理用 1-x；daemon 预计算键 dv_bond_diff）
        try:
            dv_bond = self._market_stats.get('dv_bond_diff')
            if dv_bond is not None:
                scores.append(1 - dv_bond)
                self._cache['dv_bond_diff'] = round(dv_bond, 4)
            else:
                dv_bond = self._compute_dv_bond_diff()
                scores.append(1 - dv_bond)   # 股债收益差越高→性价比越高→得分越低（慢线高位）
                self._cache['dv_bond_diff'] = round(dv_bond, 4)
        except Exception as e:
            logger.debug(f"股债收益差失败: {e}")

        # 4. 股债位置差（知识库=混合基金指数净值缩放后的趋势线）。
        #    447号 T3a-2：系统无混合基金净值数据源，降级声明——不落地该项，
        #    慢线实际 3 项（ERP/融资/股债收益差），与知识库 4 项构成存在已知缺口。

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

    # ── 分库连接（458号 R1）：回退查询目标表已分库（daily_basic_cache/daily_cache/
    #    stk_limit_cache/margin_cache→market_cache.db；indicator_other→compute_cache.db），
    #    主库 conn（stock_cache.db 总库）无此类表 → 经 sharding_manager 取分库 conn。
    #    458号前用 self._get_dm().cache.conn（主库）查分库表，恒抛 no such table → 静默 0.5。
    #    变更仅修复数据读取路由，不改变判定逻辑/阈值/输出契约（445 §6.2 dim5 慢线冻结项）。
    @staticmethod
    def _shard_conn(table_name: str):
        from app.data.sharding_manager import sharding_manager
        db_name = sharding_manager.get_db_for_table(table_name)
        return sharding_manager.get_connection(db_name)

    # ── 快线子指标 ──

    def _compute_ma20_ratio(self) -> float:
        """计算MA20强势股占比"""
        conn = self._shard_conn('daily_cache')
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
        """全市场换手率分位（364d修复）"""
        conn = self._shard_conn('daily_basic_cache')
        today = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        try:
            row = conn.execute("""
                SELECT AVG(turnover_rate) FROM daily_basic_cache WHERE trade_date=?
            """, [today]).fetchone()
            if row and row[0] is not None:
                avg_turnover = float(row[0])
                hist = conn.execute("""
                    SELECT AVG(turnover_rate) FROM daily_basic_cache
                    WHERE trade_date >= date(?, '-60 days')
                """, [today]).fetchone()
                hist_avg = float(hist[0]) if hist and hist[0] else avg_turnover
                if hist_avg > 0:
                    return max(0, min(1, avg_turnover / hist_avg))
        except Exception as e:
            logger.warning(f"换手率分位计算失败，回退0.5: {e}")
        return 0.5

    def _compute_limit_ratio(self) -> float:
        """计算涨跌停比（daily_cache JOIN stk_limit_cache 同库 market_cache.db）"""
        conn = self._shard_conn('daily_cache')
        today = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
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
        """全市场RSI_14中位数分位（364d修复）"""
        conn = self._shard_conn('indicator_other')
        today = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        try:
            row = conn.execute("""
                SELECT AVG(rsi14) FROM indicator_other WHERE trade_date=? AND rsi14 IS NOT NULL
            """, [today]).fetchone()
            if row and row[0] is not None:
                avg_rsi = float(row[0])
                hist = conn.execute("""
                    SELECT AVG(rsi14) FROM indicator_other
                    WHERE trade_date >= date(?, '-60 days') AND rsi14 IS NOT NULL
                """, [today]).fetchone()
                float(hist[0]) if hist and hist[0] else 50.0
                return max(0, min(1, (avg_rsi - 30) / 40))
        except Exception as e:
            logger.warning(f"RSI分位计算失败，回退0.5: {e}")
        return 0.5

    # ── 慢线子指标 ──

    def _compute_erp_percentile(self) -> float:
        """计算ERP分位（447号 T3a-2/归一化：ERP=1/PE_TTM-10年国债利率的历史绝对分位）

        归一化口径（447号 用户拍板）：A股盈利收益率普遍低于国债，ERP 绝对值恒为负，
        比值归一化对负值失效 → 改为「当日 ERP 绝对值在近252交易日历史中的分位(rank%)」。
        daemon 预计算（market_stats['erp_percentile']）缺省时回退本方法。
        """
        from app.opportunity_atlas.valuation_estimator import CN_10Y_BOND_YIELD_PCT
        bond_yield = float(CN_10Y_BOND_YIELD_PCT)
        conn = self._shard_conn('daily_basic_cache')
        today = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        try:
            rows = conn.execute("""
                SELECT d.trade_date, AVG(c.pe_ttm) FROM (
                    SELECT DISTINCT trade_date FROM daily_basic_cache
                    WHERE trade_date <= ? AND pe_ttm > 0
                    ORDER BY trade_date DESC LIMIT 252
                ) d JOIN daily_basic_cache c ON c.trade_date = d.trade_date AND c.pe_ttm > 0
                GROUP BY d.trade_date ORDER BY d.trade_date
            """, [today]).fetchall()
            erp_series = []
            for _, pe in rows:
                if pe is not None and float(pe) > 0:
                    erp_series.append(1 / float(pe) * 100 - bond_yield)
            if not erp_series:
                return 0.5
            erp_today = erp_series[-1]  # trade_date 升序，最后一条即当日
            # 历史绝对分位：当日值在「当日+历史」序列中小于它的占比
            count_less = sum(1 for v in erp_series if v < erp_today)
            return max(0, min(1, count_less / len(erp_series)))
        except Exception as e:
            logger.warning(f"ERP分位计算失败，回退0.5: {e}")
        return 0.5

    def _compute_dv_bond_diff(self) -> float:
        """计算股债收益差分位（447号：中位股息率-10年国债利率的历史绝对分位）

        归一化口径（447号 用户拍板）：股息率普遍低于国债，收益差绝对值恒为负，
        比值归一化对负值失效 → 改为「当日中位股息率-国债 在近252交易日历史中的分位(rank%)」。
        daemon 预计算（market_stats['dv_bond_diff']）缺省时回退本方法。
        """
        from app.opportunity_atlas.valuation_estimator import CN_10Y_BOND_YIELD_PCT
        bond_yield = float(CN_10Y_BOND_YIELD_PCT)
        conn = self._shard_conn('daily_basic_cache')
        today = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        try:
            rows = conn.execute("""
                SELECT d.trade_date, AVG(m.dv_median) FROM (
                    SELECT DISTINCT trade_date FROM daily_basic_cache
                    WHERE trade_date <= ? AND dv_ttm > 0
                    ORDER BY trade_date DESC LIMIT 252
                ) d JOIN (
                    SELECT trade_date, AVG(dv_ttm) AS dv_median FROM (
                        SELECT trade_date, dv_ttm,
                               ROW_NUMBER() OVER (PARTITION BY trade_date
                                                  ORDER BY dv_ttm) rn,
                               COUNT(*) OVER (PARTITION BY trade_date) cnt
                        FROM daily_basic_cache WHERE dv_ttm > 0
                    ) WHERE rn BETWEEN cnt * 0.5 AND cnt * 0.5 + 1
                    GROUP BY trade_date
                ) m ON m.trade_date = d.trade_date
                GROUP BY d.trade_date ORDER BY d.trade_date
            """, [today]).fetchall()
            diff_series = []
            for _, dv in rows:
                if dv is not None and float(dv) > 0:
                    diff_series.append(float(dv) - bond_yield)
            if not diff_series:
                return 0.5
            diff_today = diff_series[-1]  # trade_date 升序，最后一条即当日
            # 历史绝对分位：当日值在「当日+历史」序列中小于它的占比
            count_less = sum(1 for v in diff_series if v < diff_today)
            return max(0, min(1, count_less / len(diff_series)))
        except Exception as e:
            logger.warning(f"股债收益差计算失败，回退0.5: {e}")
        return 0.5

    def _compute_margin_trend(self) -> float:
        """计算融资余额趋势（5日变化率归一化）"""
        conn = self._shard_conn('margin_cache')
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
            logger.warning(f"融资趋势计算失败，回退0.5: {e}")
        return 0.5

    # ── 工具方法 ──

    def _normalize(self, value: float, low: float, high: float) -> float:
        """将值映射到0-1区间"""
        if high <= low:
            return 0.5
        return max(0, min(1, (value - low) / (high - low)))
