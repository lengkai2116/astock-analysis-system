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
from typing import Optional

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

IC_WEIGHTS_FILE = None  # data_daemon 启动时注入（DATA_DIR/ic_weights.json）


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


def recompute_ic_weights(ecm, lookback_days: int = 180, horizon: int = 20,
                         sample_size: int = 500) -> dict:
    """用历史截面计算各维度 IC，返回归一化权重"""
    try:
        dates = ecm._query_shard('daily_cache',
            "SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date DESC "
            "LIMIT %d" % (lookback_days // 20 * 20 + 1))["trade_date"].tolist()
        if len(dates) < 30:
            return dict(POTENTIAL_DIM_WEIGHTS)
        dates_sorted = sorted(dates)
        ic_acc = {"val": [], "trend": [], "fund": [], "earn": []}
        for i in range(0, len(dates_sorted) - horizon - 20, 20):
            d0 = dates_sorted[i]
            d10 = dates_sorted[i + horizon] if i + horizon < len(dates_sorted) else None
            if not d10:
                continue
            px = ecm._query_shard('daily_cache', "SELECT ts_code, close FROM daily_cache WHERE trade_date=?", [d0])
            px10 = ecm._query_shard('daily_cache', "SELECT ts_code, close FROM daily_cache WHERE trade_date=?", [d10])
            basic = ecm._query_shard('daily_basic_cache', "SELECT ts_code, pe_ttm FROM daily_basic_cache WHERE trade_date=?", [d0])
            mf = ecm._query_shard('moneyflow_cache', """
                SELECT ts_code, SUM(net_lg_amount) net5, SUM(buy_lg_amount+sell_lg_amount) tot5
                FROM (SELECT ts_code, net_lg_amount, buy_lg_amount, sell_lg_amount,
                      ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) rn
                      FROM moneyflow_cache WHERE trade_date <= ?) WHERE rn <= 5 GROUP BY ts_code""", [d0])
            p10_map = dict(zip(px10["ts_code"], px10["close"]))
            b_map = dict(zip(basic["ts_code"], basic["pe_ttm"]))
            px_prev = ecm._query_shard('daily_cache', """
                SELECT ts_code, close FROM (
                    SELECT ts_code, close, ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) rn
                    FROM daily_cache WHERE trade_date <= ?) WHERE rn = 21""", [d0])
            mom_map = dict(zip(px_prev["ts_code"], px_prev["close"]))
            mf_map = {}
            for _, r in mf.iterrows():
                tot = r.get("tot5") or 0
                if tot > 0:
                    mf_map[r["ts_code"]] = (r["net5"] or 0) / tot
            roe_df = ecm._query_shard('fina_indicator_cache', "SELECT ts_code, roe FROM fina_indicator_cache")
            roe_map = dict(zip(roe_df["ts_code"], roe_df["roe"]))
            sample = {"val": [], "trend": [], "fund": [], "earn": []}
            rets = []
            for _, r in px.iterrows():
                c = r["close"]
                c10 = p10_map.get(r["ts_code"])
                if not c or not c10 or c <= 0:
                    continue
                ret = c10 / c - 1
                rets.append(ret)
                sample["val"].append(1.0 / b_map[r["ts_code"]] if b_map.get(r["ts_code"]) else None)
                c0 = r["close"]
                _prev = mom_map.get(r["ts_code"])
                sample["trend"].append((c0 / _prev - 1) if _prev and _prev > 0 else None)
                sample["fund"].append(mf_map.get(r["ts_code"]))
                sample["earn"].append(roe_map.get(r["ts_code"]))
            for dim, vals in sample.items():
                pairs = [(v, rets[j]) for j, v in enumerate(vals) if v is not None]
                if len(pairs) >= 30:
                    a = [p[0] for p in pairs]
                    b = [p[1] for p in pairs]
                    ic_acc[dim].append(_spearman(a, b))
            if len(ic_acc["val"]) >= 3:
                break
        ic_mean = {}
        for dim, arr in ic_acc.items():
            ic_mean[dim] = sum(arr) / len(arr) if arr else 0.0
        pos_ic = {d: ic for d, ic in ic_mean.items() if ic > 0.05}
        if not pos_ic:
            return dict(POTENTIAL_DIM_WEIGHTS)
        new_w = {}
        for dim, w0 in POTENTIAL_DIM_WEIGHTS.items():
            new_w[dim] = pos_ic.get(dim, 0.05)
        total = sum(new_w.values())
        new_w = {k: round(v / total, 4) for k, v in new_w.items()}
        return new_w
    except Exception as e:
        logger.warning(f"IC 重估失败: {e}")
        return dict(POTENTIAL_DIM_WEIGHTS)


def load_ic_weights() -> dict:
    """加载持久化 IC 权重"""
    import json, os
    global IC_WEIGHTS_FILE
    if IC_WEIGHTS_FILE and os.path.exists(IC_WEIGHTS_FILE):
        try:
            with open(IC_WEIGHTS_FILE, encoding="utf-8") as f:
                w = json.load(f)
            if all(k in w for k in POTENTIAL_DIM_WEIGHTS):
                return w
        except Exception:
            pass
    return dict(POTENTIAL_DIM_WEIGHTS)


def save_ic_weights(weights: dict) -> None:
    """持久化 IC 权重"""
    import json, os
    global IC_WEIGHTS_FILE
    if IC_WEIGHTS_FILE:
        try:
            os.makedirs(os.path.dirname(IC_WEIGHTS_FILE), exist_ok=True)
            with open(IC_WEIGHTS_FILE, "w", encoding="utf-8") as f:
                json.dump(weights, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"IC 权重保存失败: {e}")


def compute_fund_strength(ecm, ts_code: str) -> float:
    """5 日主力净流入强度（有向：净流入正/净流出负，范围 -1~1）"""
    try:
        mf = ecm._query_shard('moneyflow_cache',
            "SELECT net_lg_amount, buy_lg_amount, sell_lg_amount FROM ("
            "  SELECT net_lg_amount, buy_lg_amount, sell_lg_amount, "
            "    ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) rn "
            "  FROM moneyflow_cache WHERE ts_code=?) WHERE rn <= 5", [ts_code])
        if mf.empty:
            return None
        net5 = mf["net_lg_amount"].sum()
        tot5 = mf["buy_lg_amount"].sum() + mf["sell_lg_amount"].sum()
        if tot5 <= 0:
            return None
        return max(-1.0, min(1.0, net5 / tot5))
    except Exception:
        return None

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
        """构建全市场 composite_rating 截面百分位基准"""
        try:
            import bisect
            rows = ecm._query_shard('opportunity_tags_cache',
                "SELECT DISTINCT ts_code, tag_value FROM opportunity_tags_cache "
                "WHERE tag_name='composite_rating' AND tag_value IS NOT NULL AND tag_value != '' "
                "AND id IN (SELECT MAX(id) FROM opportunity_tags_cache "
                "WHERE tag_name='composite_rating' GROUP BY ts_code)")
            items = []
            for _, r in rows.iterrows():
                try:
                    items.append((r['ts_code'], float(r['tag_value'])))
                except (TypeError, ValueError):
                    continue
            if len(items) < 100:
                self._comp_percentile = None
                return
            self._industry_mean = {}
            cat_map: dict[str, str] = {}
            try:
                from app.data import DataManager
                dm = DataManager()
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
            def _pct(v: float) -> float:
                import bisect as _b
                idx = _b.bisect_left(vals, v)
                return idx / n
            self._comp_percentile = _pct
        except Exception:
            self._comp_percentile = None

    def build_fcf_percentile(self, ecm) -> None:
        """构建全市场 FCF yield 截面百分位基准"""
        try:
            import bisect
            codes = ecm._query_shard('treemap_snapshot',
                "SELECT ts_code FROM treemap_snapshot")["ts_code"].tolist()
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
            def _pct(v: float) -> float:
                import bisect as _b
                idx = _b.bisect_left(vals, v)
                return idx / n
            self._fcf_percentile = _pct
        except Exception:
            self._fcf_percentile = None

    def build_potential_percentile_tables(self, ecm) -> None:
        """构建潜力引擎的截面百分位基准"""
        import bisect

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

        try:
            dev = ecm._query_shard('treemap_snapshot',
                "SELECT valuation_deviation FROM treemap_snapshot"
            )["valuation_deviation"].dropna().tolist()
            self._potential_tables["val"] = _lookup(sorted(dev))
        except Exception:
            self._potential_tables["val"] = _lookup([])

        try:
            roe = ecm._query_shard('fina_indicator_cache',
                "SELECT roe FROM fina_indicator_cache"
            )["roe"].dropna().tolist()
            self._potential_tables["earn"] = _lookup(sorted(roe))
        except Exception:
            self._potential_tables["earn"] = _lookup([])

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
            n_col = ('net_profit_atsopc' if 'net_profit_atsopc' in df.columns
                     else 'net_profit' if 'net_profit' in df.columns else None)
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
        if 'pe_ttm' in df_basic.columns:
            pe = df_basic['pe_ttm'].dropna()
            pe = pe[pe > 0]
            if len(pe) >= 20:
                cur_pe = pe.iloc[-1]
                pct = (pe < cur_pe).sum() / len(pe) * 100
                pe_score = _pct_rating_narrow(pct)

        has_positive_ni = False
        if not df_income.empty:
            income_sorted = df_income.sort_values('end_date', ascending=False)
            n_col = ('net_profit_atsopc' if 'net_profit_atsopc' in df_income.columns
                     else 'net_profit' if 'net_profit' in df_income.columns else None)
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
        n_col = ('net_profit_atsopc' if 'net_profit_atsopc' in income.columns
                 else 'net_profit' if 'net_profit' in income.columns else None)
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

    def _fina_health(self, ts_code: str, ecm) -> tuple[str, bool]:
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

    def _compute_valuation(self, ts_code: str, ecm) -> dict:
        """四锚加权估值 → 返回完整估值标签"""
        try:
            from app.data import DataManager
            _dm = DataManager()
            industry = _dm.get_stock_industry(ts_code)
        except Exception:
            industry = None
        cat = _category(industry)
        weights = CATEGORY_WEIGHTS.get(cat, CATEGORY_WEIGHTS['微小/亏损'])

        try:
            df_basic = ecm.get_cached_daily_basic(ts_code)
        except Exception:
            df_basic = pd.DataFrame()
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

        fina_health, roce_pass = self._fina_health(ts_code, ecm)
        qa = QUALITY_ADJUST
        if fina_health == 'fail':
            composite -= qa['fail_penalty']
        elif fina_health == 'pass':
            try:
                df_fina = ecm.get_cached_fina_indicator(ts_code)
            except Exception:
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
                growth = self._revenue_yoy(df_income)
                if growth is not None and growth > 0.20:
                    composite += 0.2
            except Exception:
                pass
        composite = max(-2.0, min(2.0, composite))

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

    def evaluate(self, dims: dict, tags: dict, signals: dict = None,
                 lifecycle: dict = None) -> dict:
        """统一评估入口

        Returns:
            {status_description, judgment, audit}
        """
        ecm = self._get_dm().cache
        ts_code = tags.get('ts_code', '')

        # 1. 四锚加权估值
        val = self._compute_valuation(ts_code, ecm)
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
