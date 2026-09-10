"""第7维 价值估算引擎

358号方案 v4.1 新增维度：独立的价值估算维度，
为机会图谱板块提供股票估值核算，输出三轨结构。

整合源：
  - valuation_estimator.py（843行）：四锚加权合成估值 + 财务质量评分
  - potential_engine.py（406行）：7维潜力评分 + IC加权 + 截面百分位

数据依赖：daily_basic_cache / fina_indicator_cache / income_cache /
         balancesheet_cache / cashflow_cache / pre_feat_cache(估值标签)
"""

from __future__ import annotations

import json
import logging
import math
import os

import pandas as pd

from app.data.mixins import DataAwareMixin

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 常量与配置（从 valuation_estimator.py 迁移）
# ═══════════════════════════════════════════════════════════

CN_10Y_BOND_YIELD_PCT = float(os.getenv('CN_10Y_BOND_YIELD', '1.7'))

QUALITY_ADJUST = {
    'roe_threshold': float(os.getenv('QUALITY_ROE_THRESHOLD', '12.0')),
    'roe_norm': float(os.getenv('QUALITY_ROE_NORM', '20.0')),
    'premium': float(os.getenv('QUALITY_PREMIUM', '0.25')),
    'fail_penalty': float(os.getenv('QUALITY_FAIL_PENALTY', '0.5')),
}

INDUSTRY_CATEGORY: dict[str, str] = {
    '食品饮料': '蓝筹', '家用电器': '蓝筹', '汽车': '蓝筹', '美容护理': '蓝筹',
    '传媒': '成长',
    '钢铁': '周期', '有色金属': '周期', '煤炭': '周期', '石油石化': '周期',
    '基础化工': '周期', '建筑材料': '周期', '建筑装饰': '周期',
    '房地产': '周期', '机械设备': '周期', '轻工制造': '周期', '交通运输': '周期',
    '电子': '科技', '计算机': '科技', '通信': '科技', '电力设备': '科技',
    '国防军工': '科技', '医药生物': '科技',
    '银行': '金融', '非银金融': '金融',
    '公用事业': '稳定收息', '环保': '稳定收息',
    '农林牧渔': '微小/亏损', '纺织服饰': '微小/亏损', '商贸零售': '微小/亏损',
    '社会服务': '微小/亏损', '综合': '微小/亏损',
}

CATEGORY_WEIGHTS: dict[str, tuple[float, float, float, float, float]] = {
    '蓝筹': (0.15, 0.30, 0.30, 0.15, 0.10),
    '成长': (0.10, 0.25, 0.20, 0.35, 0.10),
    '周期': (0.40, 0.15, 0.25, 0.15, 0.05),
    '科技': (0.10, 0.15, 0.20, 0.50, 0.05),
    '金融': (0.45, 0.20, 0.10, 0.20, 0.05),
    '稳定收息': (0.15, 0.25, 0.35, 0.15, 0.10),
    '微小/亏损': (0.40, 0.05, 0.30, 0.20, 0.05),
}

# 估值分级 → 中文
LEVEL_CN = {
    'extreme_low': '极度低估', 'low': '低估', 'fair': '合理',
    'high': '高估', 'extreme_high': '极度高估',
}

# 估值分级 → 红绿灯
LEVEL_LIGHT = {
    'extreme_low': 'green', 'low': 'green', 'fair': 'yellow',
    'high': 'red', 'extreme_high': 'red',
}

# 潜力权重（从 potential_engine.py 迁移）
POTENTIAL_DIM_WEIGHTS = {
    "val": 0.20, "earn": 0.15, "sector": 0.15,
    "event": 0.10, "fund": 0.20, "trend": 0.20,
}

SENTIMENT_WEIGHT = {
    "recovery": 1.0, "ice": 0.8, "climax": 0.8,
    "ebb": 0.3, "": 1.0, None: 1.0,
}

EVENT_SCORE = {
    "earnings": 0.9, "lhb": 0.7, "breakout": 0.8, "concept": 0.6,
    "buyback": 0.6, "pledge": 0.3, "float": 0.2, "reduce": 0.2,
    "fraud_sign": 0.1, "regulatory": 0.1, "none": 0.5, "": 0.5,
}

TREND_SCORE = {
    "up_aligned": 0.8, "mixed": 0.5, "no_trend": 0.5,
    "down_aligned": 0.2, "": 0.5, None: 0.5,
}


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════

def _pct_rating_wide(pct: float) -> int:
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
    return max(-2.0, min(2.0, value * 2.0 / 3.0))


def _category(industry: str | None) -> str:
    if not industry:
        return '微小/亏损'
    return INDUSTRY_CATEGORY.get(industry, '微小/亏损')


def _map_score(score: float) -> float:
    """潜力score → 0-100 混合映射"""
    if score is None or score <= 0.14:
        return 0.0
    if score <= 0.58:
        return (score - 0.14) / (0.58 - 0.14) * 85.0
    return 85.0 + 15.0 * (1 - math.exp(-3.0 * (score - 0.58)))


def _safe_float(v, default=None):
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


# ═══════════════════════════════════════════════════════════
# 第7维 引擎
# ═══════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════
# IC 权重重估（313号 §4.2 第三层：维度权重按历史有效性实证）
# ═══════════════════════════════════════════════════════════




def _spearman(a: list, b: list) -> float:
    """Spearman 秩相关"""
    n = len(a)
    if n < 10:
        return 0.0
    import statistics
    ra = {v: i for i, v in enumerate(sorted(set(a)))}
    rb = {v: i for i, v in enumerate(sorted(set(b)))}
    pa = [ra[x] for x in a]
    pb = [rb[x] for x in b]
    ma, mb = statistics.mean(pa), statistics.mean(pb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(pa, pb))
    va = sum((x - ma) ** 2 for x in pa) ** 0.5
    vb = sum((y - mb) ** 2 for y in pb) ** 0.5
    return cov / (va * vb) if va and vb else 0.0









import bisect


def _adjust_composite(composite: float, fina_health: str, ecm, ts_code: str,
                      cat: str, df_income, engine, data_context: dict = None) -> float:
    """composite_rating 的质量调整和营收增长加分逻辑"""
    qa = QUALITY_ADJUST
    if fina_health == 'fail':
        composite -= qa['fail_penalty']
    elif fina_health == 'pass':
        try:
            # 413 P3 T14：优先从data_context读取fina_df
            df_fina = data_context.get('fina_df') if data_context else None
            if df_fina is None:
                df_fina = ecm.get_cached_fina_indicator(ts_code)
        except Exception:
            df_fina = pd.DataFrame()
        if df_fina is None:
            df_fina = pd.DataFrame()
        if not df_fina.empty and 'roe' in df_fina.columns:
            roe = df_fina['roe'].dropna()
            if not roe.empty:
                roe_v = float(roe.iloc[0] or 0)
                if roe_v > qa['roe_threshold']:
                    composite += qa['premium'] * min(1.0, roe_v / qa['roe_norm'])
    composite = max(-2.0, min(2.0, composite))

    if cat in ('科技', '成长') and not df_income.empty and 'revenue' in df_income.columns:
        try:
            growth = engine._revenue_yoy(df_income)
            if growth is not None and growth > 0.20:
                composite += 0.2
        except Exception:
            pass
    return max(-2.0, min(2.0, composite))


def _build_valuation_plain(level_cn: str, val: dict, strength: int) -> str:
    """构建估值白话文本"""
    parts = [f"估值{level_cn}，PE近5年{val.get('pe_percentile_5y') or '无'}%分位"]
    if val.get('fcf_yield') is not None:
        parts.append(f"FCF收益率{val['fcf_yield']:.2f}%")
    if val.get('dividend_yield') is not None:
        parts.append(f"股息率{val['dividend_yield']:.2f}%")
    parts.append(f"潜力{strength}/100")
    return '，'.join(parts)


def _net_profit_col(df) -> str | None:
    """检测 net_profit_atsopc / net_profit 列名（复用逻辑：4处重复 → 1个helper）"""
    if df is None or df.empty:
        return None
    if 'net_profit_atsopc' in df.columns:
        return 'net_profit_atsopc'
    if 'net_profit' in df.columns:
        return 'net_profit'
    return None


def _pe_percentile(df_basic) -> float | None:
    """计算当前PE在历史中的百分位（复用逻辑：3处重复 → 1个helper）"""
    if df_basic is None or df_basic.empty or 'pe_ttm' not in df_basic.columns:
        return None
    pe = df_basic['pe_ttm'].dropna()
    pe = pe[pe > 0]
    if len(pe) < 20:
        return None
    return (pe < pe.iloc[-1]).sum() / len(pe) * 100


class Dim7ValuationEngine(DataAwareMixin):
    """第7维 价值估算引擎 — 四锚加权估值 + 7维潜力评分"""

    def __init__(self):
        self._dm = None
        self._comp_percentile = None
        self._industry_mean: dict[str, float] = {}
        self._fcf_percentile = None
        self._potential_tables: dict = {}

    # ── 截面基准构建（供 precompute 调用） ──────────────

    def build_composite_percentile(self, ecm) -> None:
        """构建全市场 composite_rating 截面百分位基准（B1修复：通过DataManager读取）"""
        try:
            # B1修复：通过get_tags_batch获取composite_rating，而非直接SQL
            from app.data import DataManager
            dm = DataManager()
            # 获取全市场最新交易日的所有股票
            try:
                latest_date = ecm._query_shard('daily_cache',
                    "SELECT MAX(trade_date) as d FROM daily_cache").iloc[0]['d']
            except Exception:
                self._comp_percentile = None
                return
            codes_df = ecm._query_shard('daily_cache',
                "SELECT DISTINCT ts_code FROM daily_cache WHERE trade_date=?", [latest_date])
            if codes_df is None or codes_df.empty:
                self._comp_percentile = None
                return
            all_codes = codes_df['ts_code'].tolist()
            # 批量获取标签（通过DataManager抽象层）
            all_tags = dm.get_tags_batch(all_codes)
            items = []
            for code, tag_dict in all_tags.items():
                cr = tag_dict.get('composite_rating')
                if cr is not None:
                    try:
                        items.append((code, float(cr)))
                    except (TypeError, ValueError):
                        continue
            if len(items) < 100:
                self._comp_percentile = None
                return
            self._industry_mean = {}
            cat_map: dict[str, str] = {}
            try:
                batch = dm.get_stock_industry_batch([code for code, _ in items])
                cat_sum: dict[str, float] = {}
                cat_cnt: dict[str, int] = {}
                for code, cval in items:
                    ind = batch.get(code)
                    cat = _category(ind)
                    cat_map[code] = cat
                    cat_sum[cat] = cat_sum.get(cat, 0.0) + cval
                    cat_cnt[cat] = cat_cnt.get(cat, 0) + 1
                self._industry_mean = {
                    c: s / cat_cnt[c]
                    for c, s in cat_sum.items() if cat_cnt.get(c, 0) >= 30
                }
            except Exception:
                self._industry_mean = {}
            vals = sorted(
                cval - self._industry_mean.get(cat_map.get(code, '微小/亏损'), 0.0)
                for code, cval in items
            )
            n = len(vals)
            self._comp_percentile = lambda v: bisect.bisect_left(vals, v) / n
        except Exception:
            self._comp_percentile = None

    def build_fcf_percentile(self, ecm) -> None:
        """构建全市场 FCF yield 截面百分位基准（B2修复：从daily_cache获取股票列表）"""
        try:
            # B2修复：从daily_cache获取股票列表，而非treemap_snapshot（跨层）
            try:
                latest_date = ecm._query_shard('daily_cache',
                    "SELECT MAX(trade_date) as d FROM daily_cache").iloc[0]['d']
            except Exception:
                self._fcf_percentile = None
                return
            codes_df = ecm._query_shard('daily_cache',
                "SELECT DISTINCT ts_code FROM daily_cache WHERE trade_date=?", [latest_date])
            codes = codes_df['ts_code'].tolist() if codes_df is not None and not codes_df.empty else []
            vals = []
            for code in codes:
                try:
                    df_b = ecm.get_cached_daily_basic(code)
                    df_cf = ecm.get_cached_cashflow(code)
                    if (df_b is not None and not df_b.empty
                            and df_cf is not None and not df_cf.empty):
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
            self._fcf_percentile = lambda v: bisect.bisect_left(vals, v) / n
        except Exception:
            self._fcf_percentile = None

    def build_potential_percentile_tables(self, ecm) -> None:
        """构建潜力引擎的截面百分位基准（B3修复：通过DataManager获取数据）"""

        def _lookup(sorted_vals):
            nn = len(sorted_vals)
            if nn == 0:
                return lambda v: 0.5
            def _p(v):
                if v is None:
                    return 0.5
                idx = bisect.bisect_left(sorted_vals, v)
                return idx / nn
            return _p

        # B3修复：从daily_basic_cache计算PE分位代替treemap_snapshot的valuation_deviation
        try:
            pe_vals = ecm._query_shard('daily_basic_cache',
                "SELECT pe_ttm FROM daily_basic_cache WHERE pe_ttm > 0")["pe_ttm"].dropna().tolist()
            self._potential_tables["val"] = _lookup(sorted(pe_vals)) if pe_vals else _lookup([])
        except Exception:
            self._potential_tables["val"] = _lookup([])

        # B3修复：从fina_indicator_cache读取ROE（通过DataManager的分库路由）
        try:
            roe = ecm._query_shard('fina_indicator_cache',
                "SELECT roe FROM fina_indicator_cache")["roe"].dropna().tolist()
            self._potential_tables["earn"] = _lookup(sorted(roe)) if roe else _lookup([])
        except Exception:
            self._potential_tables["earn"] = _lookup([])

        # ponytail: sector/trend/fund 无跨截面percentile基准，始终返回0.5；dict lookup路径正常工作
        self._potential_tables.setdefault("sector", _lookup([]))
        self._potential_tables.setdefault("trend", _lookup([]))
        self._potential_tables.setdefault("fund", _lookup([]))

    # ── 四锚估值计算（从 ValuationEngine 迁移） ──────────

    def _anchor_pb(self, df_basic: pd.DataFrame) -> float:
        if df_basic.empty or 'pb' not in df_basic.columns:
            return 0.0
        pb = df_basic['pb'].dropna()
        pb = pb[pb > 0]
        if len(pb) < 20:
            return 0.0
        cur = pb.iloc[-1]
        pct = (pb < cur).sum() / len(pb) * 100
        return float(_pct_rating_wide(pct))

    def _yoY_growth(self, df_income: pd.DataFrame) -> float | None:
        try:
            df = df_income.sort_values('end_date', ascending=False)
            n_col = _net_profit_col(df)
            if n_col is None:
                return None
            latest = df.iloc[0]
            target = pd.Timestamp(latest['end_date']) - pd.DateOffset(years=1)
            match = df[df['end_date'] == target]
            if match.empty:
                return None
            prev = match.iloc[0]
            if prev[n_col] == 0:
                return None
            return (latest[n_col] - prev[n_col]) / abs(prev[n_col])
        except Exception:
            return None

    def _revenue_yoy(self, df_income: pd.DataFrame) -> float | None:
        try:
            df = df_income.sort_values('end_date', ascending=False)
            if 'revenue' not in df.columns:
                return None
            latest = df.iloc[0]
            target = pd.Timestamp(latest['end_date']) - pd.DateOffset(years=1)
            match = df[df['end_date'].apply(lambda d: pd.Timestamp(d) == target)]
            if match.empty:
                return None
            prev = match.iloc[0]['revenue']
            cur = latest['revenue']
            if pd.isna(cur) or pd.isna(prev) or prev == 0:
                return None
            return (float(cur) - float(prev)) / abs(float(prev))
        except Exception:
            return None

    def _anchor_earnings(self, df_basic, df_income) -> float:
        if df_basic.empty:
            return 0.0
        pe_score = 0.0
        pe_pct_val = _pe_percentile(df_basic)
        if pe_pct_val is not None:
            pe_score = _pct_rating_narrow(pe_pct_val)

        has_positive_ni = False
        if not df_income.empty:
            income_sorted = df_income.sort_values('end_date', ascending=False)
            n_col = _net_profit_col(df_income)
            if n_col is not None and n_col in income_sorted.columns:
                _ni = income_sorted[n_col].dropna()
                has_positive_ni = bool(not _ni.empty and _ni.iloc[0] > 0)

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
                else:
                    div_score = -0.5

        return _sum3_to_2(pe_score + peg_score + div_score)

    def _anchor_cashflow(self, df_basic, df_cashflow, df_balancesheet, cat) -> float:
        if cat == '金融' or df_basic.empty:
            return 0.0
        total_mv = None
        if 'total_mv' in df_basic.columns:
            mv = df_basic['total_mv'].dropna()
            if not mv.empty:
                total_mv = mv.iloc[-1]
        if total_mv is None or total_mv <= 0:
            return 0.0
        fcf = None
        if not df_cashflow.empty and 'free_cashflow' in df_cashflow.columns:
            cf = df_cashflow['free_cashflow'].dropna()
            if not cf.empty:
                fcf = cf.iloc[0]
        if fcf is None:
            return 0.0
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
        fcf_yield = fcf / 1e4 / ev * 100
        if self._fcf_percentile is not None:
            pct = self._fcf_percentile(fcf_yield)
            return round(pct * 4 - 2, 2)
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

    def _anchor_adjusted_pe(self, df_basic, df_income, cat) -> float:
        if cat not in ('科技', '成长') or df_basic.empty or df_income.empty:
            return 0.0
        income = df_income.sort_values('end_date', ascending=False)
        if 'revenue' not in income.columns or 'rd_expense' not in income.columns:
            return 0.0
        revenue = float(income['revenue'].iloc[0] or 0)
        rd = float(income['rd_expense'].iloc[0] or 0)
        if revenue <= 0 or rd / revenue <= 0.05:
            return 0.0
        if 'total_mv' not in df_basic.columns:
            return 0.0
        mv = df_basic['total_mv'].dropna()
        if mv.empty or mv.iloc[-1] <= 0:
            return 0.0
        total_mv = mv.iloc[-1]
        n_col = _net_profit_col(income)
        if n_col is None:
            return 0.0
        _ni = income[n_col].dropna()
        if _ni.empty:
            return 0.0
        n_income = float(_ni.iloc[0] or 0)
        if n_income <= 0:
            return 0.0
        adj_n = n_income + rd * (1 - 0.25) * 0.20
        normal_pe = total_mv / n_income
        adj_pe = total_mv / adj_n
        ratio = (normal_pe - adj_pe) / normal_pe
        if ratio > 0.20:
            return 2.0
        if ratio > 0.10:
            return 1.0
        if ratio > 0.05:
            return 0.5
        return 0.0

    def _fina_health(self, ts_code: str, ecm) -> tuple:
        """财务健康检查（418号修复：从旧版恢复，2a34db1 截断时丢失）

        四维检查：ROE均值>6% / ROCE均值>15% / 负债率<70%（金融除外） / 经营现金流覆盖净利润。
        任一维度不满足累积：≥2 fail、≥1 suspicious。
        """
        health = 'pass'
        roce_pass = False
        try:
            df_fina = ecm.get_cached_fina_indicator(ts_code)
        except Exception:
            df_fina = pd.DataFrame()
        try:
            df_report = ecm.get_cached_finance_report(ts_code)
        except Exception:
            df_report = pd.DataFrame()
        try:
            df_income = ecm.get_cached_income(ts_code)
        except Exception:
            df_income = pd.DataFrame()
        try:
            df_bs = ecm.get_cached_balancesheet(ts_code)
        except Exception:
            df_bs = pd.DataFrame()
        try:
            df_cf = ecm.get_cached_cashflow(ts_code)
        except Exception:
            df_cf = pd.DataFrame()

        roe_ok = False
        if not df_fina.empty and 'roe' in df_fina.columns:
            roe = df_fina['roe'].dropna()
            if len(roe) >= 3:
                roe_ok = roe.head(3).mean() > 6.0

        roce_ok = False
        if not df_report.empty and 'roce' in df_report.columns:
            roce = df_report['roce'].dropna()
            if len(roce) >= 3:
                roce_ok = roce.head(3).mean() > 15.0
        if not roce_ok and not df_fina.empty and 'roce' in df_fina.columns:
            roce = df_fina['roce'].dropna()
            if len(roce) >= 3:
                roce_ok = roce.head(3).mean() > 15.0
        if not roce_ok and not df_income.empty and not df_bs.empty:
            try:
                _incs = df_income.sort_values('end_date', ascending=False)
                _bs = df_bs.sort_values('end_date', ascending=False)
                _roc_list = []
                for _i in range(min(3, len(_incs), len(_bs))):
                    _op = float(_incs.iloc[_i].get('operating_profit') or 0)
                    _ta = float(_bs.iloc[_i].get('total_assets') or 0)
                    _cl = float(_bs.iloc[_i].get('current_liab') or 0)
                    if _op and _ta and (_ta - _cl) > 0:
                        _roc_list.append(_op / (_ta - _cl) * 100)
                if _roc_list:
                    roce_ok = (sum(_roc_list) / len(_roc_list)) > 15.0
            except Exception:
                pass
        roce_pass = roce_ok

        liab_ok = True
        industry = None
        try:
            from app.data import DataManager
            _dm = DataManager()
            industry = _dm.get_stock_industry(ts_code)
        except Exception:
            pass
        cat = _category(industry)
        if cat != '金融' and not df_bs.empty:
            if 'total_liab' in df_bs.columns and 'total_assets' in df_bs.columns:
                bs = df_bs.sort_values('end_date', ascending=False)
                ta = float(bs['total_assets'].iloc[0] or 0)
                tl = float(bs['total_liab'].iloc[0] or 0)
                if ta > 0:
                    liab_ok = (tl / ta * 100) < 70.0

        ocf_ok = True
        if not df_cf.empty and not df_income.empty:
            cf = df_cf.sort_values('end_date', ascending=False)
            inc = df_income.sort_values('end_date', ascending=False)
            n_col = ('net_profit_atsopc' if 'net_profit_atsopc' in inc.columns
                     else 'net_profit' if 'net_profit' in inc.columns else None)
            if n_col is not None and 'cashflow_oper' in cf.columns:
                ratios = []
                for i in range(min(3, len(cf), len(inc))):
                    ni = inc[n_col].iloc[i]
                    ocf = cf['cashflow_oper'].iloc[i]
                    if ni is not None and not pd.isna(ni) and ni != 0 and ocf is not None:
                        ratios.append(ocf / ni)
                if ratios:
                    ocf_ok = all(r > 0.8 for r in ratios)

        fail_count = sum(not v for v in [roe_ok, liab_ok, ocf_ok])
        if fail_count >= 2:
            health = 'fail'
        elif fail_count >= 1:
            health = 'suspicious'
        return health, roce_pass

    def _anchor_bond_stock(self, df_basic) -> float:
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


    def _compute_valuation(self, ts_code: str, ecm, data_context: dict = None) -> dict:
        """四锚加权估值 → 返回完整估值标签

        418号修复：恢复 2a34db1 提交中被截断的主体（a1-a5 四锚加权 + 质量调整 +
        level/deviation + 分位统计 + return），保留 data_context-first 数据加载。
        """
        try:
            from app.data import DataManager
            _dm = DataManager()
            industry = _dm.get_stock_industry(ts_code)
        except Exception:
            industry = None
        cat = _category(industry)
        weights = CATEGORY_WEIGHTS.get(cat, CATEGORY_WEIGHTS['微小/亏损'])

        # 411号Phase 6：优先使用data_context预加载数据
        data_context = data_context or {}
        try:
            df_basic = data_context.get('daily_basic_df') if data_context.get('daily_basic_df') is not None else ecm.get_cached_daily_basic(ts_code)
            if df_basic is None:
                df_basic = pd.DataFrame()
        except Exception:
            df_basic = pd.DataFrame()
        # 412号方案B4：data_context-first + ecm fallback
        try:
            df_income = (data_context.get('income_df')
                         if data_context.get('income_df') is not None
                         and not (hasattr(data_context.get('income_df'), 'empty') and data_context['income_df'].empty)
                         else ecm.get_cached_income(ts_code))
            if df_income is None:
                df_income = pd.DataFrame()
        except Exception:
            df_income = pd.DataFrame()
        try:
            df_bs = (data_context.get('balancesheet_df')
                      if data_context.get('balancesheet_df') is not None
                      and not (hasattr(data_context.get('balancesheet_df'), 'empty') and data_context['balancesheet_df'].empty)
                      else ecm.get_cached_balancesheet(ts_code))
            if df_bs is None:
                df_bs = pd.DataFrame()
        except Exception:
            df_bs = pd.DataFrame()
        try:
            df_cf = (data_context.get('cashflow_df')
                      if data_context.get('cashflow_df') is not None
                      and not (hasattr(data_context.get('cashflow_df'), 'empty') and data_context['cashflow_df'].empty)
                      else ecm.get_cached_cashflow(ts_code))
            if df_cf is None:
                df_cf = pd.DataFrame()
        except Exception:
            df_cf = pd.DataFrame()

        # ── 四锚加权（a1资产/PB、a2收益/PE、a3现金流、a4调整PE、a5股债）──
        a1 = self._anchor_pb(df_basic)
        a2 = self._anchor_earnings(df_basic, df_income)
        a3 = self._anchor_cashflow(df_basic, df_cf, df_bs, cat)
        a4 = self._anchor_adjusted_pe(df_basic, df_income, cat)
        a5 = self._anchor_bond_stock(df_basic)

        w1, w2, w3, w4, w5 = weights

        # Wiki 周期股陷阱：周期股在周期顶点PE最低，需自动切换至PB锚
        if cat == '周期':
            # 检查PE分位数是否异常低（<20%），可能是周期顶点
            if not df_basic.empty and 'pe_ttm' in df_basic.columns:
                pe = df_basic['pe_ttm'].dropna()
                pe = pe[pe > 0]
                if len(pe) >= 20:
                    cur_pe = pe.iloc[-1]
                    pe_pct = (pe < cur_pe).sum() / len(pe) * 100
                    if pe_pct < 20:
                        # PE处于极低分位 → 可能是周期顶点 → 提高PB权重
                        w1 = w1 * 2.0  # 资产锚(PB)权重翻倍
                        w2 = w2 * 0.5  # 收益锚(PE)权重减半
                        total = w1 + w2 + w3 + w4 + w5
                        w1, w2, w3, w4, w5 = w1/total, w2/total, w3/total, w4/total, w5/total

        if not df_basic.empty and 'total_mv' in df_basic.columns:
            mv = df_basic['total_mv'].dropna()
            if not mv.empty and mv.iloc[-1] < 5e9:
                w1 *= 0.5
                total = w1 + w2 + w3 + w4 + w5
                if total > 0:
                    w1, w2, w3, w4, w5 = w1/total, w2/total, w3/total, w4/total, w5/total

        composite = w1 * a1 + w2 * a2 + w3 * a3 + w4 * a4 + w5 * a5
        composite = max(-2.0, min(2.0, composite))

        # 财务健康质量调整 + 科技/成长营收增长加分（418号：接线 _adjust_composite）
        fina_health, roce_pass = self._fina_health(ts_code, ecm)
        composite = _adjust_composite(composite, fina_health, ecm, ts_code, cat,
                                      df_income, self, data_context=data_context)

        # level 判定（comp_percentile 优先，缺失时用阈值）
        if self._comp_percentile is not None:
            pct = self._comp_percentile(composite - self._industry_mean.get(cat, 0.0))
            if pct > 0.95:
                level = 'extreme_low'
            elif pct > 0.80:
                level = 'low'
            elif pct > 0.20:
                level = 'fair'
            elif pct > 0.05:
                level = 'high'
            else:
                level = 'extreme_high'
        else:
            c = composite
            if c > 1.0:
                level = 'extreme_low'
            elif c >= 0.3:
                level = 'low'
            elif c >= -0.3:
                level = 'fair'
            elif c >= -1.0:
                level = 'high'
            else:
                level = 'extreme_high'

        deviation = round(composite * 20.0, 1)

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
            ps_col = 'ps_ttm' if 'ps_ttm' in df_basic.columns else 'ps'
            if ps_col in df_basic.columns:
                ps = df_basic[ps_col].dropna()
                ps = ps[ps > 0]
                if len(ps) >= 20:
                    ps_pct = round((ps < ps.iloc[-1]).sum() / len(ps) * 100, 1)

        fcf_yield = None
        if not df_cf.empty and 'free_cashflow' in df_cf.columns:
            fcf = df_cf['free_cashflow'].dropna()
            if not fcf.empty and 'total_mv' in df_basic.columns:
                mv = df_basic['total_mv'].dropna()
                if not mv.empty and mv.iloc[-1] > 0:
                    fcf_yield = round(fcf.iloc[0] / (mv.iloc[-1] * 1e4) * 100, 4)

        div_yield = None
        if not df_basic.empty and 'dv_ttm' in df_basic.columns:
            dv = df_basic['dv_ttm'].dropna()
            if not dv.empty:
                div_yield = round(float(dv.iloc[-1]), 2)

        revenue_growth = None
        if not df_income.empty and 'revenue' in df_income.columns:
            _g = self._revenue_yoy(df_income)
            if _g is not None:
                revenue_growth = round(_g * 100, 2)

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
            'composite_rating': round(composite, 4),
            'asset_anchor_rating': round(a1, 1),
            'earnings_anchor_rating': round(a2, 1),
            'cashflow_anchor_rating': round(a3, 1),
            'adjusted_anchor_rating': round(a4, 1),
        }

    # ── 潜力评分（从 PotentialEngine 迁移） ──────────

    def _compute_potential(self, tags: dict, mf_strength: float = None) -> dict:
        dims = {}
        dev = _safe_float(tags.get("valuation_deviation"))
        val_pct = self._potential_tables.get("val", lambda v: 0.5)(dev) if dev is not None else 0.5
        fina = tags.get("fina_health")
        if fina == "suspicious":
            val_pct *= 0.7
        dims["val"] = round(val_pct, 3)

        roe = _safe_float(tags.get("roe"))
        dims["earn"] = round(self._potential_tables.get("earn", lambda v: 0.5)(roe), 3)

        sh = tags.get("sector_heat")
        dims["sector"] = {"top_10": 0.9, "top_20": 0.75, "normal": 0.5, "none": 0.5, None: 0.5}.get(sh, 0.5)

        ce = tags.get("catalyst_event")
        dims["event"] = EVENT_SCORE.get(ce, 0.5)

        if mf_strength is not None:
            dims["fund"] = round(self._potential_tables.get("fund", lambda v: 0.5)(mf_strength), 3)
        else:
            ff = tags.get("fund_flow")
            dims["fund"] = {"5d_inflow": 0.7, "5d_outflow": 0.3, "mixed": 0.5, "none": 0.5, None: 0.5}.get(ff, 0.5)

        ta = tags.get("trend_alignment")
        dims["trend"] = TREND_SCORE.get(ta, 0.5)

        if dims["sector"] >= 0.75 and dims["fund"] >= 0.6:
            dims["sector"] = round(min(1.0, dims["sector"] * 1.1), 3)
            dims["fund"] = round(min(1.0, dims["fund"] * 1.1), 3)

        sp = tags.get("sentiment_phase")
        env_w = SENTIMENT_WEIGHT.get(sp, 1.0)

        quality = 1.0
        if fina == "suspicious":
            quality = 0.88
        elif fina == "fail":
            quality = 0.2

        w_sum = sum(POTENTIAL_DIM_WEIGHTS.get(k, 0.1) for k in dims)
        weighted = sum(POTENTIAL_DIM_WEIGHTS.get(k, 0.1) * v for k, v in dims.items())
        score = weighted / max(w_sum, 0.01) * env_w * quality

        if dev is not None and dev > 30:
            score *= 0.3

        adv = sum(1 for v in dims.values() if v >= 0.7)
        if adv >= 2:
            score *= (1 + 0.08 * (adv - 1))

        mapped = _map_score(score)
        return {
            'signal_strength': round(mapped),
            'potential_breakdown': json.dumps(dims, ensure_ascii=False),
        }

    # ═══════════════════════════════════════════════════════
    # 统一接口
    # ═══════════════════════════════════════════════════════

    # ponytail: dims/signals/lifecycle 参数从未读取，保留签名仅因外部调用方传入
    def evaluate(self, dims: dict, tags: dict, signals: dict = None,
                 lifecycle: dict = None, data_context: dict = None) -> dict:
        """统一评估入口

        411号Phase 6：优先使用data_context预加载数据，回退独立查询。
        418号修复：恢复 2a34db1 提交中被截断的完整输出（status_description/judgment/audit）。
        """
        ts_code = tags.get('ts_code', '')

        # 411号Phase 6：优先使用data_context中的数据
        ecm = self._get_dm().cache

        # 1. 四锚加权估值（传入data_context以减少DB调用）
        val = self._compute_valuation(ts_code, ecm, data_context=data_context)
        level = val['valuation_level']
        deviation = val['valuation_deviation']

        # 2. 潜力评分
        potential = self._compute_potential(tags)

        # 3. status_description
        level_cn = LEVEL_CN.get(level, '未知')
        pe_str = f"{val['pe_percentile_5y']}%" if val['pe_percentile_5y'] is not None else '无数据'
        pb_str = f"{val['pb_percentile_5y']}%" if val['pb_percentile_5y'] is not None else '无数据'
        fcf_str = f"{val['fcf_yield']}%" if val['fcf_yield'] is not None else '无数据'
        div_str = f"{val['dividend_yield']}%" if val['dividend_yield'] is not None else '无数据'
        strength = potential['signal_strength']

        plain_parts = [f"估值{level_cn}"]
        if val['pe_percentile_5y'] is not None:
            plain_parts.append(f"PE处于近5年{pe_str}分位")
        if val['fcf_yield'] is not None:
            plain_parts.append(f"FCF收益率{fcf_str}")
        if val['dividend_yield'] is not None and val['dividend_yield'] > 0:
            plain_parts.append(f"股息率{div_str}")
        plain_parts.append(f"潜力评分{strength}/100")
        plain = '，'.join(plain_parts)

        status_description = {
            'valuation_level': f"{level_cn}（composite={val['composite_rating']}）",
            'pe_percentile': f"PE近5年{pe_str}分位",
            'pb_percentile': f"PB近5年{pb_str}分位",
            'fcf_yield': f"自由现金流收益率{fcf_str}",
            'dividend_yield': f"股息率{div_str}",
            'revenue_growth': f"营收同比增长{val['revenue_growth']}%" if val['revenue_growth'] is not None else '营收数据缺失',
            'fina_health': f"财务健康{'✅' if val['fina_health'] == 'pass' else '⚠️' if val['fina_health'] == 'suspicious' else '🚫'}({val['fina_health']})",
            'potential_score': f"潜力评分{strength}/100",
            'potential_strength': strength,  # 数字字段（dim_adapter factor/valuation维消费，与judgment.potential_strength同值）
            'potential_breakdown': potential['potential_breakdown'],
            'plain': plain,
        }

        # 4. judgment
        judgment = {
            'valuation_level': {'value': level, 'light': LEVEL_LIGHT.get(level, 'yellow')},
            'valuation_deviation': {'value': deviation, 'light': 'green' if deviation > 10 else 'red' if deviation < -10 else 'yellow'},
            'fina_health': {'value': val['fina_health'], 'light': 'green' if val['fina_health'] == 'pass' else 'red' if val['fina_health'] == 'fail' else 'yellow'},
            'potential_strength': {'value': strength, 'light': 'green' if strength >= 60 else 'red' if strength < 30 else 'yellow'},
            'overall_light': LEVEL_LIGHT.get(level, 'yellow'),
            'overall_direction': 1 if level in ('extreme_low', 'low') else (-1 if level in ('high', 'extreme_high') else 0),
            'continuous_value': round(max(0, min(1, (val['composite_rating'] + 2) / 4)), 4),  # P2: composite [-2,2]→[0,1]
        }

        # 5. audit（统一格式：conditions列表 + satisfied_count + total_count + confidence）
        conditions = [
            {'name': 'PE数据可用', 'satisfied': val['pe_percentile_5y'] is not None,
             'actual': pe_str, 'threshold': 'PE近5年百分位'},
            {'name': 'PB数据可用', 'satisfied': val['pb_percentile_5y'] is not None,
             'actual': pb_str, 'threshold': 'PB近5年百分位'},
            {'name': 'FCF数据可用', 'satisfied': val['fcf_yield'] is not None,
             'actual': fcf_str, 'threshold': 'FCF收益率'},
            {'name': '股息率>0', 'satisfied': val['dividend_yield'] is not None and val['dividend_yield'] > 0,
             'actual': div_str, 'threshold': '股息率>0'},
            {'name': '财务健康', 'satisfied': val['fina_health'] == 'pass',
             'actual': val['fina_health'], 'threshold': 'ROE>6%近3年平均'},
            {'name': '营收正增长', 'satisfied': val['revenue_growth'] is not None and val['revenue_growth'] > 0,
             'actual': f"{val['revenue_growth']}%" if val['revenue_growth'] is not None else 'N/A',
             'threshold': '营收正增长'},
        ]
        satisfied_count = sum(1 for c in conditions if c['satisfied'])
        total_count = len(conditions)
        audit = {
            'conditions': conditions,
            'satisfied_count': satisfied_count,
            'total_count': total_count,
            'confidence': satisfied_count / total_count if total_count > 0 else 0,
        }

        return {
            'status_description': status_description,
            'judgment': judgment,
            'audit': audit,
        }

    def get_data_dependencies(self) -> list:
        return [
            'daily_basic_cache (market_cache.db)',
            'fina_indicator_cache (financial_cache.db)',
            'income_cache (financial_cache.db)',
            'balancesheet_cache (financial_cache.db)',
            'cashflow_cache (financial_cache.db)',
            'pre_feat_cache (compute_cache.db) — 估值标签',
            'treemap_snapshot (snapshot_cache.db) — 截面基准',
            'opportunity_tags_cache (compute_cache.db) — composite截面',
        ]
