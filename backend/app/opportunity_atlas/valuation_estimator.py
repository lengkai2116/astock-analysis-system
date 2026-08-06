"""估值引擎 — 四锚加权合成框架

Anchor 1: 资产锚 (PB百分位法)
Anchor 2: 收益锚 (PE分位+PEG+股息率)
Anchor 3: 现金流锚 (FCF/EV vs 国债收益率)
Anchor 4: 修正锚 (调整后PE法)

财报空窗期说明:
fina_health / composite_rating / roce_pass 依赖的 income / balancesheet / cashflow
为季频数据，在季报空窗期(2-3个月)不发生变化——这不是故障。
valuation_level 中基于 PE/PB 百分位（daily_basic 日频数据）的部分仍每日变化。
"""

from __future__ import annotations

import logging
import os

import pandas as pd

from app.data.mixins import DataAwareMixin

logger = logging.getLogger(__name__)

# 10年期国债收益率（百分比）— 环境变量可配 CN_10Y_BOND_YIELD（315号方案阶段1）
# 2026-08 中国 10Y 国债实际约 1.6-1.8%，默认 1.7（原硬编码 2.5 为 2022 前水平，致现金流锚系统性偏负）
CN_10Y_BOND_YIELD_PCT = float(os.getenv('CN_10Y_BOND_YIELD', '1.7'))

# 申万一级行业 → 七大分类
INDUSTRY_CATEGORY: dict[str, str] = {
    '食品饮料': '蓝筹',
    '家用电器': '蓝筹',
    '汽车': '蓝筹',
    '美容护理': '蓝筹',
    # 成长
    '传媒': '成长',
    # 周期
    '钢铁': '周期',
    '有色金属': '周期',
    '煤炭': '周期',
    '石油石化': '周期',
    '基础化工': '周期',
    '建筑材料': '周期',
    '建筑装饰': '周期',
    '房地产': '周期',
    '机械设备': '周期',
    '轻工制造': '周期',
    '交通运输': '周期',
    # 科技
    '电子': '科技',
    '计算机': '科技',
    '通信': '科技',
    '电力设备': '科技',
    '国防军工': '科技',
    '医药生物': '科技',
    # 金融
    '银行': '金融',
    '非银金融': '金融',
    # 稳定收息
    '公用事业': '稳定收息',
    '环保': '稳定收息',
    # 微小/亏损
    '农林牧渔': '微小/亏损',
    '纺织服饰': '微小/亏损',
    '商贸零售': '微小/亏损',
    '社会服务': '微小/亏损',
    '综合': '微小/亏损',
}

# 七大权重配置: (资产锚, 收益锚, 现金流锚, 修正锚, 股债差锚[315 F4])
CATEGORY_WEIGHTS: dict[str, tuple[float, float, float, float, float]] = {
    '蓝筹':     (0.15, 0.30, 0.30, 0.15, 0.10),
    '成长':     (0.10, 0.25, 0.20, 0.35, 0.10),
    '周期':     (0.40, 0.15, 0.25, 0.15, 0.05),
    '科技':     (0.10, 0.15, 0.20, 0.50, 0.05),
    '金融':     (0.45, 0.20, 0.10, 0.20, 0.05),
    '稳定收息':  (0.15, 0.25, 0.35, 0.15, 0.10),
    '微小/亏损': (0.40, 0.05, 0.30, 0.20, 0.05),
}

# ── 百分位映射辅助函数 ──


def _pct_rating_wide(pct: float) -> int:
    """百分位 → [-2, +2] 评级（用于PB/资产锚）"""
    if pct < 5:
        return 2
    if pct < 20:
        return 1
    if pct < 80:
        return 0
    if pct < 95:
        return -1
    return -2


def _pct_rating_narrow(pct: float) -> float:
    """百分位 → [-1, +1] 评级（用于PE分位子项）"""
    if pct < 5:
        return 1.0
    if pct < 20:
        return 0.5
    if pct < 80:
        return 0.0
    if pct < 95:
        return -0.5
    return -1.0


def _sum3_to_2(value: float) -> float:
    """将 [-3, +3] 映射到 [-2, +2]"""
    return max(-2.0, min(2.0, value * 2.0 / 3.0))


class ValuationEngine(DataAwareMixin):
    """估值引擎 — 四锚加权合成"""

    def __init__(self, data_manager=None):
        self._dm = data_manager  # DataAwareMixin 统一注入点
        self._comp_percentile = None   # 315号方案B：composite 截面百分位基准（precompute 前构建）
        self._industry_mean = {}       # 315号 F2：行业中性化——7 大行业 composite 均值
        self._fcf_percentile = None    # 315号 F5：FCF yield 截面百分位基准（锚3 相对化）

    # ═══════════════════════════════════════════════
    # 锚5: 股债收益差（315号 F4，知识库《BOCIASI》）
    # ═══════════════════════════════════════════════

    def _anchor_bond_stock(self, df_basic: pd.DataFrame) -> float:
        """股债收益差：股息率 vs 10 年期国债收益率（股债性价比）

        股息率 >> 国债 → 高性价比（低估方向 +）；股息率 << 国债 → 吸引力不足（-）
        Returns: [-2, +2]
        """
        if df_basic.empty or 'dv_ttm' not in df_basic.columns:
            return 0.0
        dv = df_basic['dv_ttm'].dropna()
        if dv.empty:
            return 0.0
        dy = float(dv.iloc[-1])
        bond = CN_10Y_BOND_YIELD_PCT
        if dy > bond * 2.0:
            return 2.0
        if dy > bond * 1.2:
            return 1.0
        if dy > bond * 0.6:
            return 0.0
        if dy > bond * 0.3:
            return -1.0
        return -2.0

    # ═══════════════════════════════════════════════
    # 315号 F5：锚3 现金流截面分位基准
    # ═══════════════════════════════════════════════

    def build_fcf_percentile(self, ecm) -> None:
        """构建全市场 FCF yield 截面百分位基准（锚3 相对化用，precompute 前调用）"""
        try:
            import bisect
            codes = ecm._query_df("SELECT ts_code FROM treemap_snapshot")["ts_code"].tolist()
            vals = []
            for code in codes[:3000]:  # 抽样 3000（截面近似，够分位）
                try:
                    df_b = ecm.get_cached_daily_basic(code)
                    df_cf = ecm.cache.get_cached_cashflow(code)
                    if df_b is not None and not df_b.empty and df_cf is not None and not df_cf.empty:
                        if 'total_mv' in df_b.columns and 'free_cashflow' in df_cf.columns:
                            mv = df_b['total_mv'].dropna()
                            fcf = df_cf['free_cashflow'].dropna()
                            if not mv.empty and not fcf.empty and mv.iloc[-1] > 0:
                                vals.append(float(fcf.iloc[0]) / float(mv.iloc[-1]) * 100)
                except Exception:
                    continue
            if len(vals) < 200:
                self._fcf_percentile = None
                return
            vals.sort()
            n = len(vals)
            def _pct(v: float) -> float:
                idx = bisect.bisect_left(vals, v)
                return idx / n
            self._fcf_percentile = _pct
            logger.info(f"FCF yield 截面基准构建完成: {len(vals)} 只")
        except Exception as e:
            logger.warning(f"FCF 截面基准构建失败: {e}")
            self._fcf_percentile = None

    def _category(self, industry: str | None) -> str:
        if not industry:
            return '微小/亏损'
        return INDUSTRY_CATEGORY.get(industry, '微小/亏损')

    # ═══════════════════════════════════════════════
    # 315号方案B：composite 截面百分位分档（对齐 416 设计 5/20/80/95）
    # ═══════════════════════════════════════════════

    def build_composite_percentile(self, ecm) -> None:
        """构建全市场 composite_rating 截面百分位基准（precompute 前调用一次）

        从标签表最近一次 composite_rating 排序（跨轮滞后一天，百分位相对语义可接受）。
        无基准时 compute_tags 回退绝对阈值分档。
        """
        try:
            import bisect
            rows = ecm._query_df(
                "SELECT DISTINCT ts_code, tag_value FROM opportunity_tags_cache "
                "WHERE tag_name='composite_rating' AND tag_value IS NOT NULL AND tag_value != '' "
                "AND id IN (SELECT MAX(id) FROM opportunity_tags_cache WHERE tag_name='composite_rating' GROUP BY ts_code)"
            )
            vals = []
            for _, r in rows.iterrows():
                try:
                    vals.append(float(r['tag_value']))
                except (TypeError, ValueError):
                    continue
            if len(vals) < 100:
                self._comp_percentile = None
                return
            vals.sort()
            n = len(vals)
            def _pct(v: float) -> float:
                idx = bisect.bisect_left(vals, v)
                return idx / n
            self._comp_percentile = _pct
            # 315号 F2：行业中性化——按 7 大行业分类统计 composite 均值
            # （行业内相对估值：个股 composite 减行业均值后再做截面分档，
            #   避免"行业整体贵→行业内股票全判高估"的系统偏差）
            self._industry_mean = {}
            try:
                from app.data import DataManager
                dm = DataManager()
                batch = dm.get_stock_industry_batch([r['ts_code'] for _, r in rows.iterrows()])
                cat_sum: dict[str, float] = {}
                cat_cnt: dict[str, int] = {}
                for _, r in rows.iterrows():
                    try:
                        cval = float(r['tag_value'])
                    except (TypeError, ValueError):
                        continue
                    ind = batch.get(r['ts_code'])
                    cat = self._category(ind)
                    cat_sum[cat] = cat_sum.get(cat, 0.0) + cval
                    cat_cnt[cat] = cat_cnt.get(cat, 0) + 1
                self._industry_mean = {c: s / cat_cnt[c] for c, s in cat_sum.items() if cat_cnt.get(c, 0) >= 30}
                logger.info(f"行业中性化基准构建完成: {len(self._industry_mean)} 类行业均值")
            except Exception as e:
                logger.warning(f"行业中性化基准构建失败: {e}")
                self._industry_mean = {}
            logger.info(f"composite 截面基准构建完成: {n} 只")
        except Exception as e:
            logger.warning(f"composite 截面基准构建失败: {e}")
            self._comp_percentile = None
            self._industry_mean = {}

    def _level_by_composite(self, composite: float) -> str:
        """composite → level：有截面基准用百分位分档（5/20/80/95），否则绝对阈值回退

        composite 大 = 低估方向（高分）→ pct 大 → 低估档；composite 小 = 高估方向 → 高估档
        （2026-08-05 修复：原百分位分支方向反，致低估股被判 high）
        """
        if self._comp_percentile is not None:
            pct = self._comp_percentile(composite)
            if pct > 0.95:
                return 'extreme_low'
            if pct > 0.80:
                return 'low'
            if pct > 0.20:
                return 'fair'
            if pct > 0.05:
                return 'high'
            return 'extreme_high'
        # 绝对阈值回退（原逻辑）
        if composite > 1.0:
            return 'extreme_low'
        if composite >= 0.3:
            return 'low'
        if composite >= -0.3:
            return 'fair'
        if composite >= -1.0:
            return 'high'
        return 'extreme_high'

    # ═══════════════════════════════════════════════
    # 锚1: 资产锚（PB百分位法）
    # ═══════════════════════════════════════════════

    def _anchor_pb(self, df_basic: pd.DataFrame) -> float:
        """PB历史百分位评级，返回 [-2, +2]"""
        if df_basic.empty or 'pb' not in df_basic.columns:
            return 0.0
        pb = df_basic['pb'].dropna()
        pb = pb[pb > 0]  # 净资产>0
        if len(pb) < 20:
            return 0.0
        cur = pb.iloc[-1]
        pct = (pb < cur).sum() / len(pb) * 100
        return float(_pct_rating_wide(pct))

    # ═══════════════════════════════════════════════
    # 锚2: 收益锚（PE分位+PEG+股息率）
    # ═══════════════════════════════════════════════

    def _yoY_growth(self, df_income: pd.DataFrame) -> float | None:
        """计算归母净利润同比增速（小数形式，如 0.15 = 15%）"""
        try:
            df = df_income.sort_values('end_date', ascending=False)
            n_col = 'n_income_attr_p' if 'n_income_attr_p' in df.columns else 'n_income'
            latest = df.iloc[0]
            latest_end = pd.Timestamp(latest['end_date'])
            target = latest_end - pd.DateOffset(years=1)
            match = df[df['end_date'] == target]
            if match.empty:
                return None
            prev = match.iloc[0]
            if prev[n_col] == 0:
                return None
            return (latest[n_col] - prev[n_col]) / abs(prev[n_col])
        except Exception:
            return None

    def _anchor_earnings(self, df_basic: pd.DataFrame,
                         df_income: pd.DataFrame) -> float:
        """收益锚评级，返回 [-2, +2]"""
        if df_basic.empty:
            return 0.0

        # 1) PE百分位评分 [-1, +1]
        pe_score = 0.0
        if 'pe_ttm' in df_basic.columns:
            pe = df_basic['pe_ttm'].dropna()
            pe = pe[pe > 0]
            if len(pe) >= 20:
                cur_pe = pe.iloc[-1]
                pct = (pe < cur_pe).sum() / len(pe) * 100
                pe_score = _pct_rating_narrow(pct)

        # 净利润为负则跳过PEG子项（股息率仍可评估）
        has_positive_ni = False
        if not df_income.empty:
            income_sorted = df_income.sort_values('end_date', ascending=False)
            n_col = 'n_income_attr_p' if 'n_income_attr_p' in df_income.columns else 'n_income'
            if n_col in income_sorted.columns:
                has_positive_ni = income_sorted[n_col].iloc[0] > 0

        # 2) PEG评分 [-1, +1]
        peg_score = 0.0
        if has_positive_ni:
            growth = self._yoY_growth(df_income)
            if growth is not None and growth > 0 and 'pe_ttm' in df_basic.columns:
                cur_pe = df_basic['pe_ttm'].dropna()
                cur_pe = cur_pe[cur_pe > 0]
                if not cur_pe.empty:
                    pe_val = cur_pe.iloc[-1]
                    peg = pe_val / (growth * 100)
                    if peg < 0.5:
                        peg_score = 1.0
                    elif peg < 1.0:
                        peg_score = 0.5
                    elif peg < 2.0:
                        peg_score = 0.0
                    elif peg < 3.0:
                        peg_score = -0.5
                    else:
                        peg_score = -1.0
            elif growth is not None and growth <= 0:
                peg_score = -0.5

        # 3) 股息率评分 [-1, +1]
        div_score = 0.0
        if 'dv_ttm' in df_basic.columns:
            dv = df_basic['dv_ttm'].dropna()
            if not dv.empty:
                latest_dv = dv.iloc[-1]
                if latest_dv > 4.0:
                    div_score = 1.0
                elif latest_dv > 2.0:
                    div_score = 0.5
                elif latest_dv > 1.0:
                    div_score = 0.0
                elif latest_dv > 0.0:
                    div_score = -0.5
                else:
                    div_score = -0.5

        total = pe_score + peg_score + div_score
        return _sum3_to_2(total)

    # ═══════════════════════════════════════════════
    # 锚3: 现金流锚（FCF/EV法）
    # ═══════════════════════════════════════════════

    def _anchor_cashflow(self, df_basic: pd.DataFrame,
                         df_cashflow: pd.DataFrame,
                         df_balancesheet: pd.DataFrame,
                         category: str) -> float:
        """FCF/EV收益率 vs 国债收益率，返回 [-2, +2]"""
        # 排除金融行业
        if category == '金融':
            return 0.0

        if df_basic.empty:
            return 0.0

        # 总市值（万元）
        total_mv = None
        if 'total_mv' in df_basic.columns:
            mv = df_basic['total_mv'].dropna()
            if not mv.empty:
                total_mv = mv.iloc[-1]
        if total_mv is None or total_mv <= 0:
            return 0.0

        # 自由现金流（万元）
        fcf = None
        if not df_cashflow.empty and 'free_cashflow' in df_cashflow.columns:
            cf = df_cashflow['free_cashflow'].dropna()
            if not cf.empty:
                fcf = cf.iloc[0]
        if fcf is None:
            return 0.0

        # EV = 总市值 + 总负债 - 货币资金
        total_liab = 0.0
        cash_eq = 0.0
        if not df_balancesheet.empty:
            bs = df_balancesheet.sort_values('end_date', ascending=False)
            if 'total_liab' in bs.columns:
                total_liab = float(bs['total_liab'].iloc[0] or 0)
            if 'cash_equivalents' in bs.columns:
                cash_eq = float(bs['cash_equivalents'].iloc[0] or 0)
            elif 'money_cap' in bs.columns:
                cash_eq = float(bs['money_cap'].iloc[0] or 0)

        ev = total_mv + total_liab - cash_eq
        if ev <= 0:
            return 0.0

        fcf_yield = fcf / ev * 100  # 转为百分比

        # 315号 F5：锚3 相对化——FCF yield 截面分位（高分位=现金流强=低估方向），
        # 无基准回退原绝对比较（vs 国债收益率）
        if getattr(self, '_fcf_percentile', None) is not None:
            pct = self._fcf_percentile(fcf_yield)
            return round(pct * 4 - 2, 2)   # 0-1 → [-2, +2]

        spread = fcf_yield - CN_10Y_BOND_YIELD_PCT
        if spread > 3.0:
            return 2.0
        if spread > 1.0:
            return 1.0
        if spread > -1.0:
            return 0.0
        if spread > -3.0:
            return -1.0
        return -2.0

    # ═══════════════════════════════════════════════
    # 锚4: 修正锚（调整后PE法）
    # ═══════════════════════════════════════════════

    def _anchor_adjusted_pe(self, df_basic: pd.DataFrame,
                            df_income: pd.DataFrame,
                            category: str) -> float:
        """调整后PE法，返回 [-2, +2]"""
        # 仅适用于研发费用占营收>5%的科技/医药行业
        if category not in ('科技', '成长'):
            return 0.0
        if df_basic.empty or df_income.empty:
            return 0.0

        # 获取营收和研发费用
        income = df_income.sort_values('end_date', ascending=False)
        if 'revenue' not in income.columns or 'rd_expense' not in income.columns:
            return 0.0
        revenue = float(income['revenue'].iloc[0] or 0)
        rd = float(income['rd_expense'].iloc[0] or 0)
        if revenue <= 0 or rd / revenue <= 0.05:
            return 0.0

        # 总市值（万元）
        if 'total_mv' not in df_basic.columns:
            return 0.0
        mv = df_basic['total_mv'].dropna()
        if mv.empty:
            return 0.0
        total_mv = mv.iloc[-1]
        if total_mv <= 0:
            return 0.0

        # 调整后净利润 = 净利润 + 研发费用 × (1-税率) × 摊销率
        # 税率25%，摊销率20%
        n_col = 'n_income_attr_p' if 'n_income_attr_p' in income.columns else 'n_income'
        n_income = float(income[n_col].iloc[0] or 0)
        if n_income <= 0:
            return 0.0

        adj_n = n_income + rd * (1 - 0.25) * 0.20

        normal_pe = total_mv / n_income
        adj_pe = total_mv / adj_n

        # 调整幅度越大（adj_pe 相对 normal_pe 下降越多），评级越高
        ratio = (normal_pe - adj_pe) / normal_pe
        if ratio > 0.20:
            return 2.0
        if ratio > 0.10:
            return 1.0
        if ratio > 0.05:
            return 0.5
        return 0.0

    # ═══════════════════════════════════════════════
    # 财务质量评分
    # ═══════════════════════════════════════════════

    def _fina_health(self, ts_code: str) -> tuple[str, bool]:
        """返回 (fina_health, roce_pass)

        fina_health: 'pass' | 'suspicious' | 'fail'
        roce_pass: bool
        """
        dm = self._get_dm()
        health = 'pass'
        roce_pass = False

        try:
            df_fina = dm.get_cached_fina_indicator(ts_code)
        except Exception:
            df_fina = pd.DataFrame()

        try:
            df_report = dm.get_cached_finance_report(ts_code)
        except Exception:
            df_report = pd.DataFrame()

        try:
            df_income = dm.get_cached_income(ts_code)
        except Exception:
            df_income = pd.DataFrame()

        try:
            df_bs = dm.get_cached_balancesheet(ts_code)
        except Exception:
            df_bs = pd.DataFrame()

        try:
            df_cf = dm.cache.get_cached_cashflow(ts_code)
        except Exception:
            df_cf = pd.DataFrame()

        # ROE（近3年平均 > 6%；校准 2026-08-02：原 10% 阈值过高——A股 ROE 中位仅 ~2.25，
        # ROE>10% 仅 10.8% 达标，致 83% 股票被判 suspicious）
        roe_ok = False
        if not df_fina.empty and 'roe' in df_fina.columns:
            roe = df_fina['roe'].dropna()
            if len(roe) >= 3:
                avg_roe = roe.head(3).mean()
                roe_ok = avg_roe > 6.0

        # ROCE（近3年平均 > 15%）
        roce_ok = False
        if not df_report.empty and 'roce' in df_report.columns:
            roce = df_report['roce'].dropna()
            if len(roce) >= 3:
                avg_roce = roce.head(3).mean()
                roce_ok = avg_roce > 15.0
        # 若 finance_report 无 roce，从 fina_indicator 尝试
        if not roce_ok and not df_fina.empty and 'roce' in df_fina.columns:
            roce = df_fina['roce'].dropna()
            if len(roce) >= 3:
                avg_roce = roce.head(3).mean()
                roce_ok = avg_roce > 15.0
        roce_pass = roce_ok

        # 资产负债率 < 70%（金融除外）
        liab_ok = True
        industry = dm.get_stock_industry(ts_code)
        cat = self._category(industry)
        if cat != '金融' and not df_bs.empty:
            if 'total_liab' in df_bs.columns and 'total_assets' in df_bs.columns:
                bs = df_bs.sort_values('end_date', ascending=False)
                ta = float(bs['total_assets'].iloc[0] or 0)
                tl = float(bs['total_liab'].iloc[0] or 0)
                if ta > 0:
                    ratio = tl / ta * 100
                    liab_ok = ratio < 70.0

        # 经营现金流/净利润 > 0.8 连续3年
        # 字段校准 2026-08-02：原用 n_income_attr_p/n_cashflow_act 不存在 → 恒未生效；
        # 实际列为 net_profit_atsopc/net_profit（income）、cashflow_oper（cashflow）
        ocf_ok = True
        if not df_cf.empty and not df_income.empty:
            cf = df_cf.sort_values('end_date', ascending=False)
            inc = df_income.sort_values('end_date', ascending=False)
            n_col = 'net_profit_atsopc' if 'net_profit_atsopc' in inc.columns else 'net_profit'
            if 'cashflow_oper' in cf.columns and n_col in inc.columns:
                ratios = []
                for i in range(min(3, len(cf), len(inc))):
                    ni = inc[n_col].iloc[i]
                    ocf = cf['cashflow_oper'].iloc[i]
                    if ni and ni != 0:
                        ratios.append(ocf / ni)
                if ratios:
                    ocf_ok = all(r > 0.8 for r in ratios)

        fail_count = sum(not v for v in [roe_ok, liab_ok, ocf_ok])
        if fail_count >= 2:
            health = 'fail'
        elif fail_count >= 1:
            health = 'suspicious'

        return health, roce_pass

    # ═══════════════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════════════

    def compute_tags(self, ts_code: str) -> dict:
        """计算并返回估值标签字典"""
        dm = self._get_dm()
        try:
            industry = dm.get_stock_industry(ts_code)
        except Exception:
            industry = None  # 行业查询失败不阻断估值计算（2026-08-04：P4 静默失败排查）
        cat = self._category(industry)
        weights = CATEGORY_WEIGHTS.get(cat, CATEGORY_WEIGHTS['微小/亏损'])

        # ── 数据加载（各表独立，互不影响） ──
        try:
            df_basic = dm.get_cached_daily_basic(ts_code)
        except Exception:
            df_basic = pd.DataFrame()

        try:
            df_income = dm.get_cached_income(ts_code)
        except Exception:
            df_income = pd.DataFrame()

        try:
            df_bs = dm.get_cached_balancesheet(ts_code)
        except Exception:
            df_bs = pd.DataFrame()

        try:
            df_cf = dm.cache.get_cached_cashflow(ts_code)
        except Exception:
            df_cf = pd.DataFrame()

        # ── 各锚评级 ──
        a1 = self._anchor_pb(df_basic)
        a2 = self._anchor_earnings(df_basic, df_income)
        a3 = self._anchor_cashflow(df_basic, df_cf, df_bs, cat)
        a4 = self._anchor_adjusted_pe(df_basic, df_income, cat)
        a5 = self._anchor_bond_stock(df_basic)  # 315号 F4：股债收益差锚

        # ── 市值微调 + 综合评级（297号§3.1：<50亿资产锚×0.5后归一化） ──
        w1, w2, w3, w4, w5 = weights
        if not df_basic.empty and 'total_mv' in df_basic.columns:
            mv = df_basic['total_mv'].dropna()
            if not mv.empty and mv.iloc[-1] < 5e9:
                w1 *= 0.5
                total = w1 + w2 + w3 + w4 + w5
                if total > 0:
                    w1, w2, w3, w4, w5 = w1/total, w2/total, w3/total, w4/total, w5/total

        composite = w1 * a1 + w2 * a2 + w3 * a3 + w4 * a4 + w5 * a5
        composite = max(-2.0, min(2.0, composite))

        # ── 315号阶段2：PB-ROE 质量修正（高 ROE 支撑高估值，主流框架；财务风险惩罚） ──
        fina_health, roce_pass = self._fina_health(ts_code)
        if fina_health == 'fail':
            composite -= 0.5                                   # 财务风险：估值惩罚（低估值也不虚高）
        elif fina_health == 'pass':
            try:
                df_fina = dm.get_cached_fina_indicator(ts_code)
                if not df_fina.empty and 'roe' in df_fina.columns:
                    roe = df_fina['roe'].dropna()
                    if not roe.empty:
                        roe_v = float(roe.iloc[0] or 0)
                        if roe_v > 12.0:
                            composite += 0.25 * min(1.0, roe_v / 20.0)   # 高质量溢价（质量修正量可配）
            except Exception:
                pass
        composite = max(-2.0, min(2.0, composite))

        # ── 315号 F3：生命周期成长修正（知识库《企业生命周期与估值》——成长股高估值容忍） ──
        # 科技/成长类 + 营收高增长（>20%）+ 盈利 → 估值容忍（composite 上移，避免高成长被误判高估）
        if cat in ('科技', '成长') and not df_income.empty and 'revenue' in df_income.columns:
            try:
                rev = df_income['revenue'].dropna()
                if len(rev) >= 2 and rev.iloc[0] > 0 and rev.iloc[1] > 0:
                    growth = rev.iloc[0] / rev.iloc[1] - 1
                    if growth > 0.20:
                        composite += 0.2   # 高成长溢价容忍
            except Exception:
                pass
        composite = max(-2.0, min(2.0, composite))

        # 315号方案B：level 按 composite 截面百分位分档（5/20/80/95），无基准回退绝对阈值
        # 315号 F2：行业中性化——composite 减行业均值后分档（行业内相对估值）
        level = self._level_by_composite(composite - self._industry_mean.get(cat, 0.0))

        deviation = round(composite * 20.0, 1)

        # ── PE/PB/PS 百分位 ──
        pe_pct = pb_pct = ps_pct = None
        if not df_basic.empty:
            if 'pe_ttm' in df_basic.columns:
                pe = df_basic['pe_ttm'].dropna()
                pe = pe[pe > 0]
                if len(pe) >= 20:
                    pe_pct = round((pe < pe.iloc[-1]).sum() / len(pe) * 100, 1)
            if 'pb' in df_basic.columns:
                pb = df_basic['pb'].dropna()
                pb = pb[pb > 0]
                if len(pb) >= 20:
                    pb_pct = round((pb < pb.iloc[-1]).sum() / len(pb) * 100, 1)
            if 'ps' in df_basic.columns or 'ps_ttm' in df_basic.columns:
                ps_col = 'ps_ttm' if 'ps_ttm' in df_basic.columns else 'ps'
                ps = df_basic[ps_col].dropna()
                ps = ps[ps > 0]
                if len(ps) >= 20:
                    ps_pct = round((ps < ps.iloc[-1]).sum() / len(ps) * 100, 1)

        # ── FCF收益率 / 股息率 ──
        fcf_yield = None
        if not df_cf.empty and 'free_cashflow' in df_cf.columns:
            fcf = df_cf['free_cashflow'].dropna()
            if not fcf.empty and 'total_mv' in df_basic.columns:
                mv = df_basic['total_mv'].dropna()
                if not mv.empty and mv.iloc[-1] > 0:
                    fcf_yield = round(fcf.iloc[0] / mv.iloc[-1] * 100, 2)

        div_yield = None
        if not df_basic.empty and 'dv_ttm' in df_basic.columns:
            dv = df_basic['dv_ttm'].dropna()
            if not dv.empty:
                div_yield = round(float(dv.iloc[-1]), 2)

        # ── 营业收入增长率 ──
        revenue_growth = None
        if not df_income.empty and 'revenue' in df_income.columns:
            rev = df_income['revenue'].dropna()
            if len(rev) >= 2:
                revenue_growth = round((rev.iloc[0] / rev.iloc[1] - 1) * 100, 2)

        # ── 财务健康（已在 composite 前计算，315号阶段2 质量修正使用） ──

        return {
            'valuation_level': level,
            'valuation_deviation': deviation,
            'pe_percentile_5y': pe_pct,
            'pb_percentile_5y': pb_pct,
            'ps_percentile_5y': ps_pct,
            'fcf_yield': fcf_yield,
            'dividend_yield': div_yield,
            'revenue_growth': revenue_growth,
            'fina_health': fina_health,
            'roce_pass': roce_pass,
            'composite_rating': round(composite, 4),  # 315号：精度 4 位（原 2 位致大量重复值，百分位分档边界失真）
            'asset_anchor_rating': round(a1, 1),
            'earnings_anchor_rating': round(a2, 1),
            'cashflow_anchor_rating': round(a3, 1),
            'adjusted_anchor_rating': round(a4, 1),
        }
