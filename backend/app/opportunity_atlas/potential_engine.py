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
            # 421号：treemap_snapshot 归 snapshot_cache.db 分库，改走 _query_shard 路由
            dev = ecm._query_shard(
                'treemap_snapshot', "SELECT valuation_deviation FROM treemap_snapshot")["valuation_deviation"].dropna().tolist()
            self._tables["val"] = _percentile_lookup(sorted(dev))
        except Exception as e:
            logger.warning(f"估值截面构建失败: {e}")
            self._tables["val"] = _percentile_lookup([])

        try:
            # 2026-09-13（356号分库）：fina_indicator_cache 属 financial_cache.db，
            # 经总库连接（_query_df）读恒空 → earn 基准恒中性 0.5，改走分库路由
            roe = ecm._query_shard(
                'fina_indicator_cache', "SELECT roe FROM fina_indicator_cache")["roe"].dropna().tolist()
            self._tables["earn"] = _percentile_lookup(sorted(roe))
        except Exception:
            self._tables["earn"] = _percentile_lookup([])

        try:
            # 资金强度：5 日主力净流入占主力成交额比例（周级持续性）
            # 2026-09-13（356号分库）：moneyflow_cache 属 market_cache.db，同上改分库路由
            mf = ecm._query_shard('moneyflow_cache', """
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

    2026-09-13 修复（356号分库）：moneyflow_cache 属 market_cache.db，
    经总库连接（_query_df）读取恒失败 → 资金维恒 None。改走 _query_shard 分库路由。
    """
    try:
        mf = ecm._query_shard(
            'moneyflow_cache',
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
                         sig_t_crit: float = 1.0, smooth_alpha: float = 0.4,
                         prev_earn: float = None) -> dict:
    """earn-only IC 重估（433 批次0 口径定稿，2026-09-14；批次3 显著性+平滑）

    仅 earn 维度参与重估：用历史截面计算 ROE 对后续 horizon 收益的 Spearman IC，
    据此调整 earn 权重；val/trend/fund 因评分信号无历史截面/样本不足暂停重估
    （433 §二 v1.2 口径定稿 4 条），权重保持配置值；sector/event 同样无历史截面。

    返回 dict：{"status", "weights", "ic_report"}
      status = "ok" | "no_signal" | "insufficient_data" | "error"
      - ok                : earn IC 为正且统计显著 → weights 为 earn 调整后的 6 键归一化权重
      - no_signal         : earn IC <= 0 或统计不显著（W1 门槛）→ weights = DIM_WEIGHTS（不劣化原权重）
      - insufficient_data : 截面 < 3 或窗口日期不足 → weights = DIM_WEIGHTS
      - error             : 异常 → weights = DIM_WEIGHTS
      ic_report           : 窗口/截面数/earn IC 均值与标准差/标准误/显著性/样本量

    433 §3.6 落地项：
      W1 显著性门槛：earn IC 须 > sig_t_crit × ic_std/√n 才视为有效正预测力（默认 1 倍标准误）
      W4 权重平滑：earn 权重 = smooth_alpha × w_ic + (1-smooth_alpha) × prev_earn（prev_earn 由调用方传当前文件值）
      W5 截面门槛：已批次1 落地（≥6）；W2 负 IC 告警由门面 run_monthly_ic_recalc 区分；W3 sector/event 等比缩放语义（其余 5 维相对比例不变）

    收益窗口 20 交易日（horizon=20，与采样间隔一致）。每 20 交易日取一个历史截面。
    """
    try:
        # 窗口内交易日（一次性拉取，F11 优化：避免逐截面 5 次查询）
        dates = ecm._query_shard(
            'daily_cache',
            "SELECT DISTINCT trade_date FROM daily_cache ORDER BY trade_date DESC "
            "LIMIT %d" % (lookback_days // 20 * 20 + 1))["trade_date"].tolist()
        if len(dates) < 30:
            return {"status": "insufficient_data", "weights": dict(DIM_WEIGHTS),
                    "ic_report": {"earn": None, "reason": "trading_days < 30"}}
        dates_sorted = sorted(dates)
        d_start, d_end = dates_sorted[0], dates_sorted[-1]

        # 一次性拉窗口内 daily 收盘（earn 收益计算）
        px_all = ecm._query_shard(
            'daily_cache',
            "SELECT ts_code, trade_date, close FROM daily_cache "
            "WHERE trade_date >= ? AND trade_date <= ?", [d_start, d_end])
        px_by_date = {d: g.set_index("ts_code")["close"]
                      for d, g in px_all.groupby("trade_date")}

        # fina 一次加载：截面日"当时可得"的最新报告期 ROE（披露滞后近似，433 批次0）
        fina = ecm._query_shard(
            'fina_indicator_cache', "SELECT ts_code, end_date, roe FROM fina_indicator_cache")
        if fina.empty or "roe" not in fina.columns or "end_date" not in fina.columns:
            return {"status": "insufficient_data", "weights": dict(DIM_WEIGHTS),
                    "ic_report": {"earn": None, "reason": "fina empty"}}
        fina = fina[fina["roe"].notna() & fina["end_date"].notna()].copy()

        def _avail(end_date: str) -> str:
            # 披露滞后近似：Q1≤4月底 / 半年≤8月底 / Q3≤10月底 / 年报≤次年4月底
            y, m, d = end_date.split("-")
            lag = {"03": 1, "06": 2, "09": 1, "12": 4}.get(m, 2)
            mm = int(m) + lag
            yy = int(y) + (mm - 1) // 12
            mm = (mm - 1) % 12 + 1
            return f"{yy:04d}-{mm:02d}-{d}"

        fina["avail"] = fina["end_date"].map(_avail)

        # 各截面 earn IC
        ic_list = []
        n_samples_list = []
        n_sections_used = 0
        for i in range(0, len(dates_sorted) - horizon - 20, 20):
            d0 = dates_sorted[i]
            d10 = dates_sorted[i + horizon] if i + horizon < len(dates_sorted) else None
            if not d10 or d0 not in px_by_date or d10 not in px_by_date:
                continue
            c0, c10 = px_by_date[d0], px_by_date[d10]
            common = c0.index.intersection(c10.index)
            if len(common) < 30:
                continue
            ret = (c10[common] / c0[common] - 1)
            # 截面日当时可得：end_date + 披露滞后 <= d0，取每只最新一期
            avail = fina[fina["avail"] <= d0]
            if avail.empty:
                continue
            avail = avail.sort_values("end_date").drop_duplicates("ts_code", keep="last")
            roe_map = avail.set_index("ts_code")["roe"]
            common2 = common.intersection(roe_map.index)
            if len(common2) < 30:
                continue
            a = [roe_map[c] for c in common2]
            b = [float(ret[c]) for c in common2]
            ic_list.append(_spearman(a, b))
            n_samples_list.append(len(common2))
            n_sections_used += 1
            if n_sections_used >= 6:   # 433 §3.6 W5：截面门槛提升至 ≥5-6
                break

        if len(ic_list) < 3:
            return {"status": "insufficient_data", "weights": dict(DIM_WEIGHTS),
                    "ic_report": {"earn": {"n_sections": len(ic_list)},
                                  "reason": "sections < 3"}}
        ic_mean = sum(ic_list) / len(ic_list)
        ic_std = (sum((x - ic_mean) ** 2 for x in ic_list) / len(ic_list)) ** 0.5
        n_samples = sum(n_samples_list)

        ic_report = {
            "window": {"start": dates_sorted[0], "end": dates_sorted[-1],
                       "n_sections": n_sections_used, "n_samples": n_samples},
            "earn": {"ic_mean": round(ic_mean, 4), "ic_std": round(ic_std, 4),
                     "n_sections": n_sections_used, "n_samples": n_samples},
        }

        # W1 显著性门槛（433 §3.6）：earn IC 须为正且 > sig_t_crit × ic_std/√n
        se = ic_std / (len(ic_list) ** 0.5)
        ic_report["earn"]["se"] = round(se, 4)
        significant = ic_mean > 0.0 and ic_mean > sig_t_crit * se
        ic_report["earn"]["significant"] = bool(significant)
        base = DIM_WEIGHTS["earn"]
        if not significant:
            logger.info(f"IC 重估：earn IC={ic_mean:.4f} 非正或统计不显著（se={se:.4f}），保留配置权重")
            ic_report["status"] = "no_signal"
            return {"status": "no_signal", "weights": dict(DIM_WEIGHTS),
                    "ic_report": ic_report}

        # earn 权重映射（earn 生效，其余 5 维按 DIM_WEIGHTS 相对比例缩放补足 1.0）
        w_e = min(0.35, max(base, base * (1 + 2.0 * ic_mean)))   # [0.15, 0.35]
        # W4 权重平滑（433 §3.6）：earn_new = α·w_ic + (1-α)·prev_earn
        if prev_earn is not None:
            w_e = smooth_alpha * w_e + (1 - smooth_alpha) * prev_earn
            w_e = min(0.35, max(0.15, w_e))
        scale = (1.0 - w_e) / (1.0 - base)
        weights = {k: round(DIM_WEIGHTS[k] * scale, 4) for k in DIM_WEIGHTS if k != "earn"}
        weights["earn"] = round(w_e, 4)
        total = sum(weights.values())
        weights = {k: round(v / total, 4) for k, v in weights.items()}
        ic_report["status"] = "ok"
        logger.info(f"IC 重估完成（earn-only）: {ic_mean} → {weights}")
        return {"status": "ok", "weights": weights, "ic_report": ic_report}
    except Exception as e:
        logger.warning(f"IC 重估失败: {e}")
        return {"status": "error", "weights": dict(DIM_WEIGHTS),
                "ic_report": {"earn": None, "reason": str(e)}}


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
    """持久化 IC 权重（433 批次1：原子写 + last_recalc 幂等标记）

    写入 tmp 文件后 os.replace 原子替换，防止 daemon 双实例/中断写坏文件；
    json 内附带 last_recalc 时间戳供月度钩子判断「本月已算」（load 侧只要求 6 键齐全，extra 字段无影响）。
    """
    import json
    import os
    from datetime import datetime
    global IC_WEIGHTS_FILE
    if IC_WEIGHTS_FILE:
        tmp = IC_WEIGHTS_FILE + ".tmp"
        payload = dict(weights)
        payload["last_recalc"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        try:
            os.makedirs(os.path.dirname(IC_WEIGHTS_FILE), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, IC_WEIGHTS_FILE)
        except Exception as e:
            logger.warning(f"IC 权重保存失败: {e}")
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass


def write_ic_report(report: dict) -> None:
    """写 ic_report.json（433 §3.5 可观测性：窗口/IC/status/新旧权重，与 ic_weights.json 同目录）

    每次重估（含 no_signal）都写；report 带 recalc_at 时间戳，供 daemon 月度钩子做幂等
    判断（no_signal 不写 ic_weights.json.last_recalc，须以 report.recalc_at 兜底，否则
    每 30s tick 重复触发——433 批次4 端到端发现）。
    """
    import json
    import os
    from datetime import datetime
    global IC_WEIGHTS_FILE
    if not IC_WEIGHTS_FILE:
        return
    report = dict(report)
    report["recalc_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    report_file = os.path.splitext(IC_WEIGHTS_FILE)[0] + "_report.json"
    tmp = report_file + ".tmp"
    try:
        os.makedirs(os.path.dirname(report_file), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        os.replace(tmp, report_file)
    except Exception as e:
        logger.warning(f"IC 报告保存失败: {e}")


def run_monthly_ic_recalc(ecm, data_dir: str = None) -> dict:
    """433 批次1 门面：月度 IC 重估（earn-only）并落盘/写报告，供 daemon 轻钩子调用。

    流程：
      recompute_ic_weights → 按 status 处置：
        - ok            : save_ic_weights（原子写 + last_recalc）→ 写 ic_report.json
        - no_signal     : 不覆盖权重文件（保留旧权重），仅写 ic_report.json（监控证据）
        - insufficient_data / error : 不落盘，写 ic_report.json + 告警
    返回 recompute 结果（含 status）。
    """
    import os
    global IC_WEIGHTS_FILE
    if data_dir:
        IC_WEIGHTS_FILE = os.path.join(data_dir, "ic_weights.json")
    if not IC_WEIGHTS_FILE:
        logger.warning("run_monthly_ic_recalc: IC_WEIGHTS_FILE 未注入，跳过")
        return {"status": "error", "weights": dict(DIM_WEIGHTS),
                "ic_report": {"earn": None, "reason": "IC_WEIGHTS_FILE not set"}}

    res = recompute_ic_weights(ecm, prev_earn=_load_current_weights().get("earn"))
    status = res.get("status")
    report = dict(res.get("ic_report") or {})
    report["status"] = status
    report["old_weights"] = _load_current_weights()
    report["new_weights"] = res.get("weights") or dict(DIM_WEIGHTS)

    if status == "ok":
        save_ic_weights(res["weights"])
        logger.info(f"月度 IC 重估（earn-only）已落盘: {res['weights']}")
    elif status == "no_signal":
        # W2（433 §3.6）：负 IC 告警 / 不显著仅记录，均不覆盖权重文件
        ic = (res.get("ic_report") or {}).get("earn") or {}
        if (ic.get("ic_mean") or 0) < 0:
            logger.warning(f"月度 IC 重估：earn IC 为负（{ic.get('ic_mean')}），因子近期反向，保留配置权重（写报告不覆盖）")
        else:
            logger.info("月度 IC 重估：earn IC 不显著，保留配置权重（写报告不覆盖）")
    else:
        logger.warning(f"月度 IC 重估未落盘（status={status}）: {report.get('reason', '')}")
    write_ic_report(report)
    return res


def _load_current_weights() -> dict:
    """读取当前 ic_weights.json 内容（供报告记录旧权重）；无则用 DIM_WEIGHTS"""
    import json
    import os
    global IC_WEIGHTS_FILE
    if IC_WEIGHTS_FILE and os.path.exists(IC_WEIGHTS_FILE):
        try:
            with open(IC_WEIGHTS_FILE, encoding="utf-8") as f:
                w = json.load(f)
            if all(k in w for k in DIM_WEIGHTS):
                return {k: w[k] for k in DIM_WEIGHTS}
        except Exception:
            pass
    return dict(DIM_WEIGHTS)
