"""
机会潜力强度引擎（313号 v4：机会信号强度与时机识别体系 §四）

方块大小 = 机会潜力强度（0-100）：
  7 维潜力（估值/业绩/板块/事件/资金/趋势/主力成本可选）× 截面百分位 + IC 加权
  + 关联修正（估值×质量/资金×板块/情绪动态权重）+ 质量系数 + 风险否决（慢变量）+ 共振奖励

设计要点（313号）：
- 潜力侧只用慢变量与持续性数据（§6.4 数据源唯一归属）
- 剔除时机型信号（突破确认/买点/量价共振归颜色）
- 数据缺失维度给 0.5 中性分，不拉低其他维度
- 主力成本潜力为可选维度（无行为证据不参与）

综合公式（§4.3）：
  机会强度 = 质量系数 × Σ(wᵢ × 维度百分位 × 关联修正 × 情绪权重) × 共振奖励
"""

import json
import logging
import math

logger = logging.getLogger(__name__)

# 初始维度权重（IC 加权待滚动重估——方案 §4.2 第三层，实施先按初始值，权重可配置）
DIM_WEIGHTS = {
    "val": 0.20,      # 估值潜力
    "earn": 0.15,     # 业绩潜力
    "sector": 0.15,   # 板块潜力
    "event": 0.10,    # 事件潜力
    "fund": 0.20,     # 资金潜力
    "trend": 0.20,    # 趋势潜力
}

# 情绪动态权重矩阵（§4.2 关联修正：复苏 1.0 / 冰点 0.8 / 高潮 0.5 / 退潮 0.3）
# 校准 2026-08-04：climax 0.5 → 0.8——实测真实高潮日（2026-08-04 涨停 243 家）0.5 使
# 98.6% 股票 <40 分（唯一值 64），机会地图全灰、丧失个股差异性（违背三硬性要求 2）。
# 0.8 保留"高潮打折"语义且保持分布（80+ 1.4% / 40-60 22.4% / 唯一值 98）。
SENTIMENT_WEIGHT = {"recovery": 1.0, "ice": 0.8, "climax": 0.8, "ebb": 0.3, "": 1.0, None: 1.0}

# 事件强度映射（catalyst_event 类型 → 0-1；业绩/政策/突破强于题材）
EVENT_SCORE = {
    "earnings": 0.9, "lhb": 0.7, "breakout": 0.8, "concept": 0.6, "buyback": 0.6,
    "pledge": 0.3, "float": 0.2, "reduce": 0.2, "fraud_sign": 0.1, "regulatory": 0.1,
    "none": 0.5, "": 0.5,
}

# 趋势方向映射（趋势潜力：方向/斜率慢变量，不含突破确认）
TREND_SCORE = {"up_aligned": 0.8, "mixed": 0.5, "no_trend": 0.5, "down_aligned": 0.2, "": 0.5, None: 0.5}


def _percentile_lookup(sorted_vals: list) -> callable:
    """构建值→百分位查找函数（0-1，值越小百分位越低）"""
    import bisect
    n = len(sorted_vals)
    if n == 0:
        return lambda v: 0.5
    def _pct(v):
        if v is None:
            return 0.5
        idx = bisect.bisect_left(sorted_vals, v)
        return idx / n
    return _pct


def _map_score(score: float) -> float:
    """机会潜力 score → 0-100 混合映射（2026-08-09 修复拉伸饱和）

    原线性映射 (score-0.14)/0.52 在 score>=0.66 即饱和 100（全市场 98 只满分 1.79%）。
    修复为混合映射：
      - 线性段：score 0.14→0 分, 0.58→85 分（保留中低分区分度）
      - 顶部渐近：score >0.58 → 85 + 15×(1-e^(-3×(score-0.58)))，永不饱和（仅极高分接近 100）
    实测分布（5584 只）：满分 0 / 80+ 5.2% / 中位 40（达成 313 号目标）。
    """
    if score is None or score <= 0.14:
        return 0.0
    if score <= 0.58:
        return (score - 0.14) / (0.58 - 0.14) * 85.0
    return 85.0 + 15.0 * (1 - math.exp(-3.0 * (score - 0.58)))


class PotentialEngine:
    """机会潜力强度引擎（截面百分位基准 + 单只评分）"""

    def __init__(self):
        self._tables = {}   # 截面百分位基准：{dim: lookup_fn}
        self._weights = load_ic_weights()   # IC 加权（313 §4.2 第三层：持久化，月度滚动重估）

    # ── 截面基准构建（precompute 前调用一次） ──────────────
    def build_percentile_tables(self, ecm) -> None:
        """全市场截面百分位基准（313号 §4.2 第一层）"""
        try:
            dev = ecm._query_df(
                "SELECT valuation_deviation FROM treemap_snapshot")["valuation_deviation"].dropna().tolist()
            self._tables["val"] = _percentile_lookup(sorted(dev))
        except Exception as e:
            logger.warning(f"估值截面构建失败: {e}")
            self._tables["val"] = _percentile_lookup([])

        try:
            roe = ecm._query_df(
                "SELECT roe FROM fina_indicator_cache")["roe"].dropna().tolist()
            self._tables["earn"] = _percentile_lookup(sorted(roe))
        except Exception:
            self._tables["earn"] = _percentile_lookup([])

        try:
            # 资金强度：5 日主力净流入占主力成交额比例（周级持续性）
            mf = ecm._query_df("""
                SELECT ts_code, SUM(net_lg_amount) as net5,
                       SUM(buy_lg_amount + sell_lg_amount) as tot5 FROM (
                    SELECT ts_code, net_lg_amount, buy_lg_amount, sell_lg_amount,
                           ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) rn
                    FROM moneyflow_cache) WHERE rn <= 5 GROUP BY ts_code
            """)
            strengths = []
            for _, r in mf.iterrows():
                tot = r.get("tot5") or 0
                net = r.get("net5") or 0
                if tot > 0:
                    strengths.append(net / tot)   # 有向（净流入正/流出负），与 compute_fund_strength 一致
            self._tables["fund"] = _percentile_lookup(sorted(strengths))
        except Exception:
            self._tables["fund"] = _percentile_lookup([])

        # 板块/趋势为离散映射，无需截面表
        self._tables["sector"] = _percentile_lookup([])
        self._tables["trend"] = _percentile_lookup([])

    # ── 单只潜力评分 ─────────────────────────────────────
    def compute_potential(self, tags: dict, mf_strength: float = None) -> dict:
        """7 维潜力评分（313号 §4）→ {signal_strength, potential_breakdown}

        Args:
            tags: L2 标签（valuation_deviation/valuation_level/fina_health/sector_heat/
                  catalyst_event/trend_alignment/sentiment_phase）
            mf_strength: 5 日资金净流入强度（0-1，由调用方从 moneyflow 计算；None 时用 fund_flow 近似）
        """
        dims = {}

        # 1. 估值潜力（valuation_deviation 正=低估、负=高估（valuation_estimator 口径）；
        #    正偏离（低估）→ 截面百分位高 → 高分。2026-08-04 修复：原 1.0-val_pct 方向反（负偏离被当低估））
        dev = tags.get("valuation_deviation")
        try:
            dev_f = float(dev)
        except (TypeError, ValueError):
            dev_f = None
        val_pct = self._tables["val"](dev_f) if dev_f is not None else 0.5
        fina = tags.get("fina_health")
        if fina == "suspicious":
            val_pct *= 0.7               # 估值×质量：财务存疑降权（价值陷阱）
        dims["val"] = round(val_pct, 3)

        # 2. 业绩潜力（ROE 截面百分位；无数据 0.5 中性）
        roe = tags.get("roe")
        try:
            roe_f = float(roe)
        except (TypeError, ValueError):
            roe_f = None
        dims["earn"] = round(self._tables["earn"](roe_f), 3)

        # 3. 板块潜力（sector_heat 映射；无截面表用标签值）
        sh = tags.get("sector_heat")
        sector_map = {"top_10": 0.9, "top_20": 0.75, "normal": 0.5, "none": 0.5, None: 0.5}
        dims["sector"] = sector_map.get(sh, 0.5)

        # 4. 事件潜力（catalyst_event 类型映射）
        ce = tags.get("catalyst_event")
        dims["event"] = EVENT_SCORE.get(ce, 0.5)

        # 5. 资金潜力（5 日净流入强度截面百分位；无数据用 fund_flow 近似）
        if mf_strength is not None:
            dims["fund"] = round(self._tables["fund"](mf_strength), 3)
        else:
            ff = tags.get("fund_flow")
            fund_map = {"5d_inflow": 0.7, "5d_outflow": 0.3, "mixed": 0.5, "none": 0.5, None: 0.5}
            dims["fund"] = fund_map.get(ff, 0.5)

        # 6. 趋势潜力（trend_alignment 映射，慢变量）
        ta = tags.get("trend_alignment")
        dims["trend"] = TREND_SCORE.get(ta, 0.5)

        # 7. 主力成本潜力（可选：无行为证据不参与，方案 §4.1 #7）

        # ── 关联修正：资金×板块共振（§4.2） ──
        sector, fund = dims["sector"], dims["fund"]
        if sector >= 0.75 and fund >= 0.6:
            dims["sector"] = round(min(1.0, sector * 1.1), 3)
            dims["fund"] = round(min(1.0, fund * 1.1), 3)

        # ── 情绪动态权重（环境变量，§4.2） ──
        sp = tags.get("sentiment_phase")
        env_w = SENTIMENT_WEIGHT.get(sp, 1.0)

        # ── 综合公式（§4.3：质量系数 × Σ + 共振奖励 + 风险否决） ──
        quality = 1.0
        # 质量系数（实施校准 2026-08-02：fina_health 判定标尺偏严，83% 股票为 suspicious——
        # "未达高质量标准"非"有风险"；suspicious 0.6→0.92 缓解乘法天花板（全维度满分 ×0.92=92 分，80+ 可达）
        # fail 仍 0.2 风险否决）
        if fina == "suspicious":
            quality = 0.88
        elif fina == "fail":
            quality = 0.2            # 风险否决：财务 fail 封顶

        w_sum = sum(self._weights.get(k, 0.1) for k in dims)
        weighted = sum(self._weights.get(k, 0.1) * v for k, v in dims.items())
        score = weighted / max(w_sum, 0.01) * env_w * quality

        # 风险否决：极端泡沫（正偏离过大）
        if dev_f is not None and dev_f > 30:
            score *= 0.3

        # 共振奖励（§4.3 校准）：优势维度（≥0.7）≥2 即触发（多源确认加分）
        adv = sum(1 for v in dims.values() if v >= 0.7)
        if adv >= 2:
            score *= (1 + 0.08 * (adv - 1))

        # 拉伸映射（2026-08-09 修复饱和：原线性 0.66 封顶致 98 只满分；改混合渐近，见 _map_score）
        mapped = _map_score(score)
        breakdown = {k: v for k, v in sorted(dims.items())}

        return {
            "signal_strength": round(mapped),   # _map_score 已返回 0-100 分数（勿再 ×100）
            "potential_breakdown": json.dumps(breakdown, ensure_ascii=False),
        }


def compute_fund_strength(ecm, ts_code: str) -> float:
    """5 日主力净流入强度（有向：净流入正 / 净流出负，范围 -1~1）；无数据返回 None

    2026-08-09 修复：原 abs(net5)/tot5 抹掉资金方向——净流出股票强度照样得正高分
    （常润股份 603201.SH：5日净流出却 fund=0.816，导致 signal_strength 满分）。
    修复后净流出 → 负强度 → fund 维低分。
    """
    try:
        mf = ecm._query_df(
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
        return max(-1.0, min(1.0, net5 / tot5))   # 有向：净流入正 / 净流出负
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
# IC 滚动重估（313号 §4.2 第三层：维度权重按历史有效性实证，滚动月度重估）
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
    """用历史截面计算各维度 IC，返回归一化权重（313 §4.2 第三层，月度滚动）

    可重算维度（历史数据可得）：
      val   = EP（1/pe_ttm，值越高越便宜）→ 预测未来 10 日收益
      trend = 20 日动量 → 动量因子 IC
      fund  = 5 日主力净流入强度 → 资金因子 IC
      earn  = ROE → 质量因子 IC
    sector/event 历史截面不可得，保持配置权重（按 IC 中位处理）。

    每 20 交易日取一个历史截面，聚合各截面 Spearman 均值 = 维度 IC。
    """
    try:
        # 历史截面时点：近 lookback_days 天，每 20 交易日一个
        dates = ecm._query_df(
            "SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date DESC "
            "LIMIT %d" % (lookback_days // 20 * 20 + 1))["trade_date"].tolist()
        if len(dates) < 30:
            return dict(DIM_WEIGHTS)
        # 取"截面日 + 10 日后的收益日"配对
        dates_sorted = sorted(dates)
        ic_acc = {"val": [], "trend": [], "fund": [], "earn": []}
        for i in range(0, len(dates_sorted) - horizon - 20, 20):
            d0 = dates_sorted[i]
            d10 = dates_sorted[i + horizon] if i + horizon < len(dates_sorted) else None
            if not d10:
                continue
            # 该截面：收盘价 + pe + 10 日后收盘 + 5 日资金 + roe
            px = ecm._query_df(
                "SELECT ts_code, close FROM daily_cache WHERE trade_date=?", [d0])
            px10 = ecm._query_df(
                "SELECT ts_code, close FROM daily_cache WHERE trade_date=?", [d10])
            basic = ecm._query_df(
                "SELECT ts_code, pe_ttm FROM daily_basic_cache WHERE trade_date=?", [d0])
            mf = ecm._query_df("""
                SELECT ts_code, SUM(net_lg_amount) net5, SUM(buy_lg_amount+sell_lg_amount) tot5
                FROM (SELECT ts_code, net_lg_amount, buy_lg_amount, sell_lg_amount,
                      ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) rn
                      FROM moneyflow_cache WHERE trade_date <= ?) WHERE rn <= 5 GROUP BY ts_code""",
                               [d0])
            p10_map = dict(zip(px10["ts_code"], px10["close"]))
            b_map = dict(zip(basic["ts_code"], basic["pe_ttm"]))
            # 动量：d0 前 20 个交易日的收盘（第 21 行）
            px_prev = ecm._query_df("""
                SELECT ts_code, close FROM (
                    SELECT ts_code, close, ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) rn
                    FROM daily_cache WHERE trade_date <= ?) WHERE rn = 21""", [d0])
            mom_map = {}
            for _, rr in px_prev.iterrows():
                mom_map[rr["ts_code"]] = rr["close"]
            mf_map = {}
            for _, r in mf.iterrows():
                tot = r.get("tot5") or 0
                if tot > 0:
                    mf_map[r["ts_code"]] = (r["net5"] or 0) / tot   # 有向（与 compute_fund_strength 一致）
            # 各股票维度值 + 收益（与 roe 对齐填充，避免索引越界）
            roe_df = ecm._query_df("SELECT ts_code, roe FROM fina_indicator_cache")
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
            # 聚合 IC（该截面）
            for dim, vals in sample.items():
                pairs = [(v, rets[j]) for j, v in enumerate(vals) if v is not None]
                if len(pairs) >= 30:
                    a = [p[0] for p in pairs]
                    b = [p[1] for p in pairs]
                    ic_acc[dim].append(_spearman(a, b))
            if len(ic_acc["val"]) >= 3:
                break  # 至少 3 个截面即可
        # 聚合各截面 IC 均值
        ic_mean = {}
        for dim, arr in ic_acc.items():
            ic_mean[dim] = sum(arr) / len(arr) if arr else 0.0
        # 归一化权重（校准：仅当窗口内存在正 IC 才调整——负/无预测力的因子不劣化原权重）
        pos_ic = {d: ic for d, ic in ic_mean.items() if ic > 0.05}
        if not pos_ic:
            logger.info(f"IC 重估：窗口内无正 IC（{ic_mean}），保留原权重")
            return dict(DIM_WEIGHTS)
        new_w = {}
        for dim, w0 in DIM_WEIGHTS.items():
            new_w[dim] = pos_ic.get(dim, 0.05)
        total = sum(new_w.values())
        new_w = {k: round(v / total, 4) for k, v in new_w.items()}
        logger.info(f"IC 重估完成: {ic_mean} → {new_w}")
        return new_w
    except Exception as e:
        logger.warning(f"IC 重估失败: {e}")
        return dict(DIM_WEIGHTS)


def load_ic_weights() -> dict:
    """加载持久化 IC 权重（data/ic_weights.json）；无则用初始权重"""
    import json
    import os
    global IC_WEIGHTS_FILE
    if IC_WEIGHTS_FILE and os.path.exists(IC_WEIGHTS_FILE):
        try:
            with open(IC_WEIGHTS_FILE, encoding="utf-8") as f:
                w = json.load(f)
            if all(k in w for k in DIM_WEIGHTS):
                return w
        except Exception:
            pass
    return dict(DIM_WEIGHTS)


def save_ic_weights(weights: dict) -> None:
    """持久化 IC 权重"""
    import json
    import os
    global IC_WEIGHTS_FILE
    if IC_WEIGHTS_FILE:
        try:
            os.makedirs(os.path.dirname(IC_WEIGHTS_FILE), exist_ok=True)
            with open(IC_WEIGHTS_FILE, "w", encoding="utf-8") as f:
                json.dump(weights, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"IC 权重保存失败: {e}")
