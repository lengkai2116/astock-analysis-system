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

import bisect

import pandas as pd

from app.data.mixins import DataAwareMixin
from app.opportunity_atlas.potential_engine import DIM_WEIGHTS as POTENTIAL_DIM_WEIGHTS
from app.opportunity_atlas.potential_engine import (
    EVENT_SCORE,
    SENTIMENT_WEIGHT,
    TREND_SCORE,
)
# 476号（双份方法体收敛）：ValuationEngine（daemon RAW-2 权威，四锚委托）+ 百分位/合成 helper
from app.opportunity_atlas.valuation_estimator import (
    CATEGORY_WEIGHTS,
    CN_10Y_BOND_YIELD_PCT,
    EASTMONEY_CATEGORY,
    INDUSTRY_CATEGORY,
    QUALITY_ADJUST,
    ValuationEngine,
    _pct_rating_narrow,
    _pct_rating_wide,
    _sum3_to_2,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 常量与配置（从 valuation_estimator.py 迁移）
# ═══════════════════════════════════════════════════════════

# 431号 G1（批次13 收敛）：以下 8 个常量原为本文件与 valuation_estimator.py /
# potential_engine.py 的**字节级副本**，现改为单向导入，权威源唯一化——
#   CN_10Y_BOND_YIELD_PCT / QUALITY_ADJUST / INDUSTRY_CATEGORY / CATEGORY_WEIGHTS
#       ← app.opportunity_atlas.valuation_estimator
#   POTENTIAL_DIM_WEIGHTS（← potential_engine.DIM_WEIGHTS）/ SENTIMENT_WEIGHT /
#   EVENT_SCORE / TREND_SCORE ← app.opportunity_atlas.potential_engine
# 见文件头 import 块。此处不再保留本地定义，避免双份 live 值漂移。
# （注：potential_engine.DIM_WEIGHTS 与 dim8_summary_engine.DIM_WEIGHTS 同名异义，
#   勿混淆；本文件只对潜力维 6 权重别名导入。）

# 估值分级 → 中文（本模块独有，非重复；勿删）
LEVEL_CN = {
    'extreme_low': '极度低估', 'low': '低估', 'fair': '合理',
    'high': '高估', 'extreme_high': '极度高估',
}

# 估值分级 → 红绿灯（本模块独有，非重复；勿删）
LEVEL_LIGHT = {
    'extreme_low': 'green', 'low': 'green', 'fair': 'yellow',
    'high': 'red', 'extreme_high': 'red',
}


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════







def _category(industry: str | None) -> str:
    if not industry:
        return '微小/亏损'
    # 477号：优先东财行业映射（Stock.industry 实际口径），其次申万，最后兜底
    if industry in EASTMONEY_CATEGORY:
        return EASTMONEY_CATEGORY[industry]
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






# ═══════════════════════════════════════════════════════
# 476号（D2）：截面基准进程级缓存（模块级惰性单例）
#   StatusEngine 每请求新建 Dim7ValuationEngine 实例（strategy_analyze/cross_validate），
#   分位表全市场构建成本高（5000+ 只遍历）——进程内构建一次、各实例共享闭包。
# ═══════════════════════════════════════════════════════

_BENCHMARKS = None  # {'comp': fn, 'fcf': fn, 'industry_mean': dict, 'potential': dict}


def _ensure_benchmarks(engine: 'Dim7ValuationEngine', ecm) -> None:
    """惰性构建截面基准一次并注入引擎实例（进程级缓存；evaluate 入口调用）"""
    global _BENCHMARKS
    if _BENCHMARKS is None:
        engine.build_composite_percentile(ecm)
        engine.build_fcf_percentile(ecm)
        engine.build_potential_percentile_tables(ecm)
        bench = {
            'comp': engine._comp_percentile,
            'fcf': engine._fcf_percentile,
            'industry_mean': engine._industry_mean,
            'potential': engine._potential_tables,
        }
        # 全部构建失败（如 ecm 不可用/库空）不缓存，下次 evaluate 重试；
        # 部分成功也缓存（避免重复全市场遍历）。
        if (bench['comp'] is not None or bench['fcf'] is not None
                or bench['potential']):
            _BENCHMARKS = bench
    if _BENCHMARKS is not None:
        engine._comp_percentile = _BENCHMARKS['comp']
        engine._fcf_percentile = _BENCHMARKS['fcf']
        engine._industry_mean = _BENCHMARKS['industry_mean']
        engine._potential_tables = _BENCHMARKS['potential']


def _reset_benchmarks() -> None:
    """清空进程级基准缓存（测试隔离用）"""
    global _BENCHMARKS
    _BENCHMARKS = None


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
        """构建全市场 composite_rating 截面百分位基准

        476号：对齐 RAW 侧（valuation_estimator 同法）——从 opportunity_tags_cache
        分库 SQL 直读 composite_rating（每只取最新 id）；原 dm.get_tags_batch 不存在
        （DataManager 仅 get_tags_by_date/get_tags_by_group）→ AttributeError 恒失败。
        """
        try:
            rows = ecm._query_shard(
                'opportunity_tags_cache',
                "SELECT DISTINCT ts_code, tag_value FROM opportunity_tags_cache "
                "WHERE tag_name='composite_rating' AND tag_value IS NOT NULL AND tag_value != '' "
                "AND id IN (SELECT MAX(id) FROM opportunity_tags_cache "
                "WHERE tag_name='composite_rating' GROUP BY ts_code)"
            )
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
                                # 476号：与消费口径对齐（_anchor_cashflow/compute_tags 均 fcf/(mv*1e4)*100）；
                                # 原 fcf/mv*100 差 1e4 倍 → 查询值落在分布低端，现金流锚系统性偏低
                                vals.append(float(fcf.iloc[0]) / (float(mv.iloc[-1]) * 1e4) * 100)
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

        # 476号（D4）：val 表改 valuation_deviation 截面分布（与 _compute_potential 查询同口径）。
        # 原用 pe_ttm 分位 → 查询传 dev（-40~40）塞进 PE 分布（0~数百）→ val 维系统性失真。
        # 失败时不设键（缺键 → _compute_potential 默认 0.5；_ensure_benchmarks 判空不缓存）。
        try:
            dev_rows = ecm._query_shard(
                'opportunity_tags_cache',
                "SELECT tag_value FROM opportunity_tags_cache "
                "WHERE tag_name='valuation_deviation' AND tag_value IS NOT NULL AND tag_value != '' "
                "AND id IN (SELECT MAX(id) FROM opportunity_tags_cache "
                "WHERE tag_name='valuation_deviation' GROUP BY ts_code)"
            )
            dev_vals = dev_rows["tag_value"].dropna().astype(float).tolist()
            if dev_vals:
                self._potential_tables["val"] = _lookup(sorted(dev_vals))
        except Exception:
            pass

        # B3修复：从fina_indicator_cache读取ROE（通过DataManager的分库路由）
        try:
            roe = ecm._query_shard('fina_indicator_cache',
                "SELECT roe FROM fina_indicator_cache")["roe"].dropna().tolist()
            if roe:
                self._potential_tables["earn"] = _lookup(sorted(roe))
        except Exception:
            pass

        # 476号：不再 setdefault 空表（sector/trend/fund）——_compute_potential 仅 val/earn
        # 查表（缺键走默认 0.5），空表占位会让 _ensure_benchmarks 误判构建成功。

    def _compute_valuation(self, ts_code: str, ecm, data_context: dict = None, tags: dict = None) -> dict:
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
        # 476号（双份方法体收敛）：四锚实算委托 ValuationEngine（daemon RAW-2 权威单实现，
        #   449/476 已双侧同步判定逻辑；本处仅数据上下文注入 dim7 的现金流分位基准）。
        _ve = ValuationEngine()
        _ve._fcf_percentile = self._fcf_percentile
        a1 = _ve._anchor_pb(df_basic)
        a2, peg_gt2 = _ve._anchor_earnings(df_basic, df_income)
        a3 = _ve._anchor_cashflow(df_basic, df_cf, df_bs, cat)
        a4 = _ve._anchor_adjusted_pe(df_basic, df_income, cat)
        a5 = _ve._anchor_bond_stock(df_basic)

        w1, w2, w3, w4, w5 = weights

        # Wiki 周期股陷阱：周期股在周期顶点PE最低，需自动切换至PB锚（449 改为纯PB归一）
        if cat == '周期':
            # 检查PE分位数是否异常低（<20%），可能是周期顶点
            if not df_basic.empty and 'pe_ttm' in df_basic.columns:
                pe = df_basic['pe_ttm'].dropna()
                pe = pe[pe > 0]
                if len(pe) >= 20:
                    cur_pe = pe.iloc[-1]
                    pe_pct = (pe < cur_pe).sum() / len(pe) * 100
                    if pe_pct < 20:
                        # PE处于极低分位 → 疑似周期顶点 → 权重归一为纯资产锚(PB)，其余锚清零
                        w1, w2, w3, w4, w5 = 1.0, 0.0, 0.0, 0.0, 0.0

        if not df_basic.empty and 'total_mv' in df_basic.columns:
            mv = df_basic['total_mv'].dropna()
            # 445-A2 修复：total_mv 单位为万元（见 _anchor_cashflow fcf/1e4 换算），
            # <50亿元 应为 5e5 万元；原 5e9 万元=50万亿元 → 全市场恒触发资产锚权重减半
            if not mv.empty and mv.iloc[-1] < 5e5:
                w1 *= 0.5
                total = w1 + w2 + w3 + w4 + w5
                if total > 0:
                    w1, w2, w3, w4, w5 = w1/total, w2/total, w3/total, w4/total, w5/total

        composite = w1 * a1 + w2 * a2 + w3 * a3 + w4 * a4 + w5 * a5
        composite = max(-2.0, min(2.0, composite))

        # ── 461-2：fina_health 双生产统一——SSOT = RAW 侧 tags（ve.compute_tags 预计算，daemon 白名单取）。
        #    原 dim7 运行时 `self._fina_health(ts_code, ecm)` 独立重算五表，绕过 dim1 且与 RAW 打架。
        #    现改为优先读 tags.fina_health/roce_pass/value_trap（ve 已产；roce_pass/value_trap 461-2 补进白名单）。
        #    兜底：tags 缺 fina_health（直接 evaluate / 旧调用）时保留运行时重算，保持兼容。 ──
        if tags:
            fina_health = str(tags.get('fina_health', '') or '')
            _rcp = tags.get('roce_pass')
            _vt = tags.get('value_trap')
            if not fina_health:
                fina_health, _rcp_u, _rna_u, _df_u = _ve._fina_health(ts_code)
                if _rcp is None: _rcp = _rcp_u
                if _vt is None: _vt = (not _rcp_u and not _rna_u)
            roce_pass = bool(_rcp) if _rcp is not None else (fina_health and fina_health not in ('',))
            try: value_trap = bool(_vt) if _vt is not None else False
            except Exception: value_trap = False
        else:
            fina_health, roce_pass, roce_na, _df_u = _ve._fina_health(ts_code)
            value_trap = (not roce_pass and not roce_na)

        # 449 估值陷阱惩罚（对齐外部 wiki：价值陷阱结合 ROCE、成长陷阱 PEG>2 自动降级）
        # ROCE 惩罚仅在有数据且<15%时触发（无数据默认通过，对齐 dim4 _check_roce）
        if value_trap:
            composite -= 0.3  # 价值陷阱：ROCE<15% 惩罚
        if peg_gt2:
            composite -= 0.5  # 成长陷阱：PEG>2 自动降级
        composite = max(-2.0, min(2.0, composite))

        composite = _adjust_composite(composite, fina_health, ecm, ts_code, cat,
                                      df_income, _ve, data_context=data_context)

        # ── 476号（D1）：SSOT = RAW 预计算最终值优先（461-2 fina_health 同构）──
        #    tags.composite_rating/valuation_level/valuation_deviation 为 daemon RAW 预计算
        #    （截面分位 + 行业中性化口径，已含全部陷阱/质量/成长修正）；SIG 实算仅兜底。
        #    tags 缺失时保留下方实算判定路径。
        _ssot = False
        if tags:
            try:
                if tags.get('composite_rating') is not None:
                    composite = max(-2.0, min(2.0, float(tags['composite_rating'])))
                    _ssot = True
            except (TypeError, ValueError):
                pass

        # level 判定（comp_percentile 优先，缺失时用阈值；476号：tags.valuation_level SSOT 优先）
        if _ssot and tags.get('valuation_level'):
            level = str(tags['valuation_level'])
        elif self._comp_percentile is not None:
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

        if _ssot and tags.get('valuation_deviation') is not None:
            try:
                deviation = round(float(tags['valuation_deviation']), 1)
            except (TypeError, ValueError):
                deviation = round(composite * 20.0, 1)
        else:
            deviation = round(composite * 20.0, 1)

        # 476号（D3）：pe/pb/ps 5年分位 SSOT = RAW 预计算（tags.pe_percentile_5y 等，与 composite/level 同构），
        #   本地 df_basic 实算降为纯兜底（直接 evaluate / tags 缺失时），消除双份方法与 RAW 输出漂移（479-9-①）。
        pe_pct = pb_pct = ps_pct = None
        if tags is not None:
            try:
                if tags.get('pe_percentile_5y') is not None:
                    pe_pct = round(float(tags['pe_percentile_5y']), 1)
            except (TypeError, ValueError):
                pass
            try:
                if tags.get('pb_percentile_5y') is not None:
                    pb_pct = round(float(tags['pb_percentile_5y']), 1)
            except (TypeError, ValueError):
                pass
            try:
                if tags.get('ps_percentile_5y') is not None:
                    ps_pct = round(float(tags['ps_percentile_5y']), 1)
            except (TypeError, ValueError):
                pass
        # 兜底：tags 缺失时本地 df_basic 实算
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
        # 487号（P2-3）：与 VE.compute_tags 同口径——金融类 FCF 不适用（四锚恒 0）→ None 降级跳过；
        # 非金融优先「经营资产FCF=经营现金流−折旧摊销」（449 口径），缺则回退教科书 free_cashflow。
        if cat != '金融':
            _fcf = None
            if not df_cf.empty:
                _cfs = df_cf.sort_values('end_date', ascending=False)
                if 'cashflow_oper' in _cfs.columns and 'depr_fa_coga_dpba' in _cfs.columns:
                    _r0 = _cfs.iloc[0]
                    _op, _depr = _r0.get('cashflow_oper'), _r0.get('depr_fa_coga_dpba')
                    try:
                        if _op is not None and _depr is not None and _op == _op and _depr == _depr:
                            _fcf = float(_op) - float(_depr)
                    except (TypeError, ValueError):
                        _fcf = None
                if _fcf is None and 'free_cashflow' in _cfs.columns:
                    _cf = _cfs['free_cashflow'].dropna()
                    if not _cf.empty:
                        _fcf = float(_cf.iloc[0])
            if _fcf is not None and not df_basic.empty and 'total_mv' in df_basic.columns:
                mv = df_basic['total_mv'].dropna()
                if not mv.empty and mv.iloc[-1] > 0:
                    # total_mv 单位为万元、现金流单位为元——换算对齐（476 D3 口径）
                    fcf_yield = round(_fcf / (mv.iloc[-1] * 1e4) * 100, 4)

        div_yield = None
        if not df_basic.empty and 'dv_ttm' in df_basic.columns:
            dv = df_basic['dv_ttm'].dropna()
            if not dv.empty:
                div_yield = round(float(dv.iloc[-1]), 2)

        revenue_growth = None
        if not df_income.empty and 'revenue' in df_income.columns:
            # 476号收敛：营收同比委托 ValuationEngine（_revenue_yoy 已收敛至权威实现）
            _g = _ve._revenue_yoy(df_income)
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
            'value_trap': value_trap,
            'growth_trap': peg_gt2,
            'composite_rating': round(composite, 4),
            'asset_anchor_rating': round(a1, 1),
            'earnings_anchor_rating': round(a2, 1),
            'cashflow_anchor_rating': round(a3, 1),
            'adjusted_anchor_rating': round(a4, 1),
        }

    # ── 潜力评分（从 PotentialEngine 迁移） ──────────

    def _compute_potential(self, tags: dict) -> dict:
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

        # 476号 P2：mf_strength 死参数删除（唯一调用方 :694 不传）——fund 维由 tags.fund_flow 驱动
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

        # 476号（D2）：进程级惰性构建截面基准（首次 evaluate 构建一次，各实例共享）
        _ensure_benchmarks(self, ecm)

        # 1. 四锚加权估值（传入data_context以减少DB调用）
        val = self._compute_valuation(ts_code, ecm, data_context=data_context, tags=tags)
        level = val['valuation_level']
        deviation = val['valuation_deviation']

        # 2. 潜力评分
        potential = self._compute_potential(tags)

        # 3. status_description
        level_cn = LEVEL_CN.get(level, '未知')
        pe_str = f"{val['pe_percentile_5y']}%" if val['pe_percentile_5y'] is not None else '无数据'
        pb_str = f"{val['pb_percentile_5y']}%" if val['pb_percentile_5y'] is not None else '无数据'
        # 487号（P2-3）：fcf 不适用（金融类/无数据）时整键置 None——dim8 `_get` 判空跳过，
        #   不再输出"自由现金流收益率无数据"（437 缺则降级；与四锚金融=0 口径一致）
        fcf_str = f"{val['fcf_yield']}%" if val['fcf_yield'] is not None else None
        div_str = f"{val['dividend_yield']}%" if val['dividend_yield'] is not None else '无数据'
        strength = potential['signal_strength']

        status_description = {
            'valuation_level': f"{level_cn}（composite={val['composite_rating']}）",
            'pe_percentile': f"PE近5年{pe_str}分位",
            'pb_percentile': f"PB近5年{pb_str}分位",
            # 479-9-③：补 _5y 数字键（SIG 展示层仍用中文串键；reliability_assessor L2 读 _5y 数字键做 PE存在性/PB+PS极端加成，此前缺失致 dim7 可靠性恒 0.3）
            'pe_percentile_5y': val['pe_percentile_5y'],
            'pb_percentile_5y': val['pb_percentile_5y'],
            'ps_percentile_5y': val['ps_percentile_5y'],
            'fcf_yield': f"自由现金流收益率{fcf_str}" if fcf_str is not None else None,
            'dividend_yield': f"股息率{div_str}",
            'revenue_growth': f"营收同比增长{val['revenue_growth']}%" if val['revenue_growth'] is not None else '营收数据缺失',
            'fina_health': f"财务健康{'✅' if val['fina_health'] == 'pass' else '⚠️' if val['fina_health'] == 'suspicious' else '🚫'}({val['fina_health']})",
            # 449 估值陷阱标注（对齐 wiki：成长陷阱 PEG>2 / 价值陷阱 ROCE<15%）
            'value_trap': 'ROCE低于15%，存在价值陷阱风险' if val.get('value_trap', False) else None,
            'growth_trap': 'PEG>2，存在成长陷阱风险' if val.get('growth_trap', False) else None,
            'potential_score': f"潜力评分{strength}/100",
            'potential_strength': strength,  # 数字字段（dim_adapter factor/valuation维消费，与judgment.potential_strength同值）
            'potential_breakdown': potential['potential_breakdown'],
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
        # 479-9-⑤：ROCE actual 对齐 tags.roce 真实数值展示（判定仍用 val['roce_pass']，阈值不动——仅展示口径统一）
        roce_actual = None
        if tags is not None:
            _roce_v = tags.get('roce')
            if _roce_v is not None and not isinstance(_roce_v, str):
                try:
                    roce_actual = float(_roce_v)
                except (TypeError, ValueError):
                    roce_actual = None
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
             'actual': val['fina_health'], 'threshold': 'ROE近3年均值>6%且负债率<70%(金融除外)且现金流覆盖净利>0.8'},
            {'name': '营收正增长', 'satisfied': val['revenue_growth'] is not None and val['revenue_growth'] > 0,
             'actual': f"{val['revenue_growth']}%" if val['revenue_growth'] is not None else 'N/A',
             'threshold': '营收正增长'},
            {'name': 'ROCE达标', 'satisfied': val['roce_pass'],
             'actual': f"{roce_actual:.2f}%" if isinstance(roce_actual, (int, float)) else ('通过' if val['roce_pass'] else 'ROCE<15%'),
             'threshold': 'ROCE近3年均值>15%'},
            {'name': '无成长陷阱', 'satisfied': not val['growth_trap'],
             'actual': 'PEG>2' if val['growth_trap'] else 'PEG<=2', 'threshold': 'PEG<=2'},
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