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
                      cat: str, df_income, engine) -> float:
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
        """四锚加权估值 → 返回完整估值标签"""
        try:
            from app.data import DataManager
            _dm = DataManager()
            industry = _dm.get_stock_industry(ts_code)
        except Exception:
            industry = None
        cat = _category(industry)
        CATEGORY_WEIGHTS.get(cat, CATEGORY_WEIGHTS['微小/亏损'])

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
        """
        ts_code = tags.get('ts_code', '')

        # 411号Phase 6：优先使用data_context中的数据
        ecm = self._get_dm().cache

        # 1. 四锚加权估值（传入data_context以减少DB调用）
        val = self._compute_valuation(ts_code, ecm, data_context=data_context)
        val['valuation_level']
        val['valuation_deviation']

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
