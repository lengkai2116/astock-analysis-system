"""第4维 资金筹码引擎 — 独立完整文件

369号方案 P1 维度引擎整合：物理合并以下文件为独立完整文件（**508号批次1起逐步收敛**，
已收敛项改 import 外部权威，见 `002-方案存档/508-dim4双副本收敛（物理合入清理）.md`）：
  - phase_detector.py — PhaseDetectionEngine 7维度加权共识（508 批次5 收敛）
  - chip_strategy_impl.py — TradingPhaseDetector 五阶段（508 批次4 收敛）
  - chip_strategy.py — ChipScorer 6维评分（MainForceScorer 508 批次1 已删，framework 权威）
  - chip_position_manager.py — 筹码位置管理（507 批次6 已删死副本）
  - chip_pre_filter.py — 筹码预筛选（507 批次6 已删死副本）
  - chip_risk_executor.py — 筹码风险执行（507 批次6 已删死副本）
  - crowding_factor.py — 拥挤度评估（508 批次1 删 framework 死副本，本文件内嵌为权威）
  - volume_price_strategy.py — StageDetector/ValuationZones/Stage（508 批次3 已删内嵌，外部完整版权威）
  - chip_distribution_service.py — ChipDistributionEstimator（508 批次3 已删内嵌，外部权威）
  - tag_extractor.py — 筹码深度标签提取
  - fund_chip_builder 输出格式 + 条件稽核

统一接口：Dim4ChipFundEngine.evaluate() → {status_description, judgment, audit}
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# 508批次3：三个物理合入副本收敛为外部权威（ChipDistributionEstimator 算法等价；
# StageDetector/ValuationZones/Stage 外部为完整版超集，dim4 特化 indicator_ma_df 注入
# 按拍板移除，与 phase_detector.py 权威用法对齐）
from app.data.chip_distribution_service import ChipDistributionEstimator
from app.engine.framework.volume_price_strategy import Stage, StageDetector, ValuationZones
from app.opportunity_atlas.dimensions.enum_cn_map import chip_concentration_cn

logger = logging.getLogger(__name__)

# ── 主力阶段常量（369号方案物理合入 phase_detector.py 时遗漏，导致 compute_tags 抛 NameError）──
PHASE_UNKNOWN = "unknown"
# 445-A1 修复：补齐物理合入时遗漏的 4 个阶段常量（对齐 phase_detector.py:20-23 值），
# 否则 _limit_up_cross_check/_fund_flow_to_phase/_volume_signal_to_phase/_chip_distribution_analysis
# 引用 PHASE_* 抛 NameError（被 try 吞）→ 涨停交叉校验 4 规则从未生效
PHASE_BUILDING = "building"
PHASE_WASHING = "washing"
PHASE_LIFTING = "lifting"
PHASE_DISTRIBUTING = "distributing"
# 主力阶段中文名映射（供 evaluate 组装 phase_cn；注意与 dim5 情绪阶段 PHASE_MAP 语义不同）
# 464号：统一拉升期枚举为 lifting（生产链 PhaseDetectionEngine 唯一产出 lifting，无 raising 存量），
# 删除 raising 冗余键，避免历史双枚举并存再次掩盖口径不一致。
PHASE_MAP = {
    'building': {'name': '建仓期', 'desc': '低位吸筹'},
    'washing': {'name': '洗盘期', 'desc': '清洗浮筹'},
    'lifting': {'name': '拉升期', 'desc': '快速上涨'},
    'distributing': {'name': '出货期', 'desc': '高位派发'},
    'support': {'name': '护盘期', 'desc': '支撑维护'},
}


# === ChipIndicators (508批次2 收敛：外部 app/data/chip_indicators.py 为权威) ===
# 369号物理合入副本已删；dim4 特化仅保留 412 C3 v3.0 RSI 预计算（外部无此能力），
# concentration 自动切外部 P95-P5 口径（508 Q2 拍板，行为变更见方案档）

from app.data.chip_indicators import ChipIndicators as _ExternalChipIndicators


class ChipIndicators(_ExternalChipIndicators):
    """dim4 特化子类：外部权威计算 + 412 C3 v3.0 RSI 预计算优先"""

    def _try_read_precomputed_rsi(self, ts_code, indicator_other_df=None):
        """411号Phase 5：尝试从indicator_other_df读取预计算RSI14

        412号方案C3 v3.0：优先从indicator_other_df参数读取（dim1通过data_context提供），
        不再直接调用DataManager。
        """
        if indicator_other_df is not None and not indicator_other_df.empty and 'rsi14' in indicator_other_df.columns:
            rsi_series = indicator_other_df['rsi14'].dropna()
            if not rsi_series.empty:
                return float(rsi_series.iloc[-1])
        return None

    def calculate_all_indicators(self, chip_bins, current_price, kline_data=None,
                                 turnover_rate=None, ts_code=None, indicator_other_df=None):
        """覆写：外部基础计算 + RSI 预计算优先（412 C3 v3.0，dim4 特化）"""
        result = super().calculate_all_indicators(
            chip_bins, current_price, kline_data=kline_data, turnover_rate=turnover_rate)
        if kline_data is not None and len(kline_data) >= 15:
            rsi_val = self._try_read_precomputed_rsi(ts_code, indicator_other_df=indicator_other_df)
            if rsi_val is not None:
                result['rsi'] = rsi_val
        return result


# === DataAwareMixin (app/data/mixins.py) ===

# === engine/framework/__init__.py 基类 ===
from abc import ABC, abstractmethod

from app.data.mixins import DataAwareMixin


class UniverseSelectionModel(ABC):
    @abstractmethod
    def select(self, date_time, data):
        pass

class AlphaModel(ABC):
    @abstractmethod
    def generate_insights(self, data):
        pass

class PortfolioConstructionModel(ABC):
    @abstractmethod
    def create_targets(self, insights, current_targets):
        pass

class RiskManagementModel(ABC):
    def on_data(self, insights, targets, current_holdings):
        pass

class ExecutionModel(ABC):
    @abstractmethod
    def execute(self, targets, current_holdings):
        pass

class Insight:
    def __init__(self, symbol='', direction=0, magnitude=0.0, confidence=0.0, period=None):
        self.symbol = symbol
        self.direction = direction
        self.magnitude = magnitude
        self.confidence = confidence
        self.period = period


# === 缺失的依赖补充 ===

# BenchmarkIndex 常量（简化版，避免依赖 benchmark_service）
class BenchmarkIndex:
    HS300 = '000300.SH'
    CSI500 = '000905.SH'

# DataManager 延迟导入（通过 DataAwareMixin._get_dm() 获取）

# OpportunityLibrary ORM 类（简化版）
class OpportunityLibrary:
    pass

# StrategyPipeline 常量
class StrategyPipeline:
    pass

# === phase_detector.py ===

class PhaseDetectionEngine(DataAwareMixin):
    """统一阶段判定引擎 — 五源融合投票"""

    def __init__(self, data_manager=None):
        self._dm = data_manager  # DataAwareMixin 统一注入点
        self._chip_estimator = None  # 延迟初始化
        self._chip_indicators = None
        self._trading_phase_detector = None
        self._stage_detector = None
        self._last_dim_insufficient = False     # 312号：数据不足标记（unknown 细分）

    # ── 主入口 ──────────────────────────────────────────────
    def compute_tags(self, ts_code: str, df: pd.DataFrame,
                     extra_tags: Optional[Dict] = None,
                     chip_fund_ext: Optional[Dict] = None,
                     moneyflow_df=None,
                     indicator_ma_df=None,
                     indicator_other_df=None,
                     cost_ext: Optional[Dict] = None) -> Dict:
        """计算阶段标签（312号方案：8 维度加权共识，替代原五源等权投票）

        412号方案C1/C3 v3.0：全部数据由dim1通过data_context提供。
        443号R2：新增cost_ext（main_force_cost/margin_cost_price），透传_ssrp维度做洗盘增强。

        Args:
            ts_code: 股票代码
            df: 日线 OHLCV DataFrame
            extra_tags: 可选下游标签
            chip_fund_ext: 筹码预计算值，由data_context提供
            moneyflow_df: 资金流向数据，由data_context提供
            indicator_ma_df: 预计算MA数据，由data_context提供
            indicator_other_df: 预计算RSI/KDJ/BOLL数据，由data_context提供
            cost_ext: 成本价预计算值（main_force_cost/margin_cost_price），由data_context提供

        Returns:
            {main_force_phase, phase_confidence, price_position,
             trend_alignment, fund_flow, phase_conflict, phase_vote_ratio}
        """
        extra_tags = extra_tags or {}
        result = {
            "main_force_phase": PHASE_UNKNOWN,
            "phase_confidence": 0.0,
            "price_position": "mid_zone",
            "trend_alignment": "no_trend",
            "fund_flow": "none",
            "phase_conflict": False,
            "phase_vote_ratio": json.dumps({"unknown_kind": "unknown_insufficient"}, ensure_ascii=False),
        }

        if df is None or df.empty or len(df) < 30:
            return result

        try:
            df_sorted = df.sort_values("trade_date").reset_index(drop=True)
        except Exception:
            return result

        # 基础标签（保持输出契约）
        price_pos, ma_alignment = self._price_position_analysis(df_sorted, ts_code=ts_code, indicator_ma_df=indicator_ma_df)
        result["price_position"] = price_pos
        trend_dir = self._detect_trend_direction(df_sorted)
        result["trend_alignment"] = trend_dir
        fund_flow = self._analyze_fund_flow(ts_code, moneyflow_df)
        result["fund_flow"] = fund_flow

        # ── 8 维度阶段向量（批次1 可计算 7/8，控盘度批次3） ──
        self._last_dim_insufficient = len(df_sorted) < 60   # 数据不足（unknown 细分）
        dims = {
            "chip":  self._dim_chip(ts_code, df_sorted, chip_fund_ext=chip_fund_ext, moneyflow_df=moneyflow_df, indicator_other_df=indicator_other_df),   # 1 筹码形态
            "fund":  self._dim_fund(fund_flow, ts_code, extra_tags),   # 2 资金流向（方向+连续强度）
            "stage": self._dim_stage(df_sorted),           # 3 量价四阶段（CONSOLIDATION 验证）
            "asr":   self._dim_asr(ts_code, df_sorted),    # 4 ASR 筹码分布（去兜底）
            "trend": self._dim_trend(df_sorted),           # 5 趋势方向（斜率连续）
            "ssrp":  self._dim_ssrp(df_sorted, extra_tags, cost_ext=cost_ext),# 6 主力成本锚定（真实 SSRP，从pre_feat_cache读取）
            "chan":  self._dim_chan(extra_tags),           # 8 缠论买点（标签接入）
        }

        # 加权共识 + 修正/环境调整
        main_phase, confidence, conflict, vote_ratio = self._consensus(dims, extra_tags)

        # 涨停交叉校验（保持 298 号规则）
        main_phase = self._limit_up_cross_check(df_sorted, main_phase, price_pos)

        result["main_force_phase"] = main_phase
        result["phase_confidence"] = round(confidence, 4)
        result["phase_conflict"] = conflict
        result["phase_vote_ratio"] = json.dumps(vote_ratio, ensure_ascii=False)
        return result

    # ═══════════════════════════════════════════════════════════
    # 312号：8 维度阶段向量 + 加权共识
    # ═══════════════════════════════════════════════════════════
    # 维度权重（312号 §3.1）
    # 431号 G1 标注（批次13，2026-09-13）：本 8 维权重与
    # phase_detector.py 的同名 _DIM_WEIGHTS 逐字节重复，且**双方均 live**
    # （各由本模块内部共识消费）。收敛需先定权威源并改 import，属行为变更，
    # 本批**仅标注，不改值**。
    _DIM_WEIGHTS = {"chip": 3.0, "fund": 3.0, "stage": 2.5, "asr": 2.0,
                    "trend": 1.5, "ssrp": 2.5, "chan": 2.0}

    def _dim_chip(self, ts_code: str, df: pd.DataFrame,
                  chip_fund_ext: dict = None, moneyflow_df=None,
                  indicator_other_df=None) -> dict:
        """维度1 筹码形态：TradingPhaseDetector 五阶段评分 → 阶段分布向量

        412号方案C1 v3.0：chip_fund_ext和moneyflow_df由data_context提供。

        判定条件收紧（2026-08-02 校准）：
          最低门槛 4.0 → 要求 ≥2 个独立条件确认才投票
        """
        info = self._run_trading_phase_detector_v2(
            ts_code, df, chip_fund_ext=chip_fund_ext, moneyflow_df=moneyflow_df,
            indicator_other_df=indicator_other_df)
        if info is None:
            return {}
        phase, scores = info
        total = sum(scores.values()) or 1.0
        best = max(scores.values())
        if best < 4.0:
            return {}
        mapping = {"BUILDING": "building", "WASHING": "washing", "RAISING": "lifting",
                   "SHIPPING": "distributing", "SUPPORT": "washing"}
        vec = {}
        for k, v in scores.items():
            p = mapping.get(k)
            if p and v > 0:
                vec[p] = round(v / total, 3)
        return vec

    def _dim_fund(self, fund_flow: str, ts_code: str, extra_tags: dict = None) -> dict:
        """维度2 资金流向：方向 + 5日大单净额连续强度（mixed/none 不投票，去 washing 兜底）

        411号Phase 8：优先从extra_tags读取预计算5日资金聚合，回退raw计算。
        """
        strength = 0.0
        # 411号Phase 8：优先使用预计算数据
        extra_tags = extra_tags or {}
        net_lg_5d = extra_tags.get('net_lg_5d')
        if net_lg_5d is not None:
            try:
                net_lg_5d = float(net_lg_5d)
                # 464-15：net_lg_5d 单位为万元（moneyflow net_lg_amount 万元列聚合），
                # ÷1e4 归一化到亿；原 /1e8 按"元"算 → strength≈0（茅台 -16037万→0.0002）
                strength = min(1.0, abs(net_lg_5d) / 1e4)
            except (TypeError, ValueError):
                pass
        else:
            # ponytail: raw计算作为fallback
            try:
                mf_df = self._get_dm().get_cached_moneyflow(ts_code)
                if mf_df is not None and not mf_df.empty:
                    mf5 = mf_df.tail(5)
                    net = mf5["net_lg_amount"].sum()
                    tot = mf5["buy_lg_amount"].sum() + mf5["sell_lg_amount"].sum()
                    if tot > 0:
                        strength = min(1.0, abs(net) / tot)
            except Exception:
                pass
        if fund_flow == "5d_inflow":
            return {"lifting": round(0.3 + 0.5 * strength, 3), "building": 0.2}
        if fund_flow == "5d_outflow":
            return {"distributing": round(0.3 + 0.5 * strength, 3)}
        return {}   # mixed/none：方向不明不投票（312 §3.2 维度2）

    def _dim_stage(self, df: pd.DataFrame) -> dict:
        """维度3 量价四阶段：StageDetector + CONSOLIDATION 证据验证（312 §3.2 维度3）"""
        stage_info = self._run_stage_detector_v2(df)
        if stage_info is None:
            return {}
        stage_name, stage_conf = stage_info
        mapping = {"UPTREND_ACTIVE": ("lifting", 0.7), "UPTREND_TOPPING": ("distributing", 0.6),
                   "DOWNTREND_BOTTOMING": ("building", 0.6), "DOWNTREND_ACTIVE": ("washing", 0.4)}
        if stage_name == "CONSOLIDATION":
            # 证据验证：20 日振幅 < 15% 且 5 日均量 < 10 日均量（无证据 → 全 0，去兜底）
            try:
                closes = df["close"].values
                highs = df["high"].values
                lows = df["low"].values
                vols = df["vol"].values if "vol" in df.columns else np.ones(len(closes))
                if len(closes) < 20:
                    return {}
                amp20 = (max(highs[-20:]) - min(lows[-20:])) / closes[-1]
                vol_shrink = sum(vols[-5:]) < sum(vols[-10:-5]) if sum(vols[-10:-5]) > 0 else False
                if amp20 < 0.15 and vol_shrink:
                    return {"washing": 0.5, "building": 0.3}
                return {}
            except Exception:
                return {}
        if stage_name in mapping:
            p, base = mapping[stage_name]
            return {p: round(base * min(stage_conf + 0.2, 1.0), 3)}
        return {}

    def _dim_asr(self, ts_code: str, df: pd.DataFrame) -> dict:
        """维度4 ASR 筹码分布：统一高 ASR=筹码集中蓄势语义（451 号）

        wiki《ASR指标》权威：ASR 高=筹码集中/突破前蓄势状态，价格脱离
        高浮筹区/ASR 高位滑落才是拉升信号；出货须「高位+放量+浮筹高企」
        组合，孤立高 ASR 不直接判出货。据此：
          - asr>90（高浮筹集中）=筹码集中蓄势 → building（不再直接 lifting）
          - 剔除孤立 'asr>30 高于峰值→distributing'（445「三处三义」相悖分支）
          - asr<15 近峰值=筹码锁定在建仓范围 → building
          - asr<15 大幅高于峰值=脱离密集区、筹码锁定充分 → lifting
        """
        chip = self._chip_distribution_analysis(ts_code, df)
        asr = chip.get("asr", 0.0)
        peak_price = chip.get("peak_position", 0.0)
        current = df["close"].values[-1]
        rel = current / peak_price if peak_price > 0 else 1.0
        # 高浮筹集中 = 筹码集中/突破前蓄势（不直接判拉升）
        if asr > 90:
            return {"building": 0.6}
        # 低浮筹 + 价格锁定在密集峰值附近：主力仍处建仓锁仓蓄势
        if asr < 15 and abs(rel - 1.0) < 0.10:
            return {"building": 0.6}
        # 低浮筹 + 大幅高于峰值：筹码锁定充分、脱离密集区 → 拉升
        if asr < 15 and rel > 1.2:
            return {"lifting": 0.5}
        return {}

    def _dim_trend(self, df: pd.DataFrame) -> dict:
        """维度5 趋势方向：三周期斜率连续强度"""
        closes = df["close"].values
        if len(closes) < 20:
            return {}
        def _slope(k):
            if len(closes) < k + 1 or closes[k] <= 0:
                return 0.0
            return closes[-1] / closes[-k - 1] - 1
        s5 = _slope(5)
        s20 = _slope(20)
        s60 = _slope(60) if len(closes) >= 60 else _slope(20)
        up = sum(1 for x in (s5, s20, s60) if x > 0.01)
        down = sum(1 for x in (s5, s20, s60) if x < -0.01)
        strength = min(1.0, abs(s5) * 15)
        if up >= 2:
            return {"lifting": round(0.3 + 0.4 * strength, 3)}
        if down >= 2:
            return {"distributing": round(0.3 + 0.4 * strength, 3)}
        return {}

    def _dim_ssrp(self, df: pd.DataFrame, extra_tags: Dict = None, cost_ext: Dict = None) -> dict:
        """维度6 主力成本锚定：现价 vs SSRP（真实主力成本，312 §3.2 维度6）

        367号：改为从 extra_tags（pre_feat_cache）读取 SSRP，不再依赖 _last_chip_indicators。
        443号R2：新增 cost_ext 主力成本近距增强（对齐 MainForceScorer.identify_phase 洗盘判定）。
        456号：新增 margin_cost_price（融资成本价）进阶段投票——wiki《融资成本价》：
          融资成本价 = 散户融资平均成本 = 解套压力位；现价在下方→反弹至该位受解套抛压（承压蓄势）；
          站上/突破→上方抛压释放、阻力锐减（做多）。作弱补充投票叠加，不覆盖主规则。

        规则（2026-08-02 抽样校准：原 rel<0.95→building 触发面过宽 77%，收紧）：
          rel < 0.85          → building（深度成本下方，安全边际大）
          0.85 <= rel < 1.10  → washing（成本区/浅套，蓄势待变）
          rel >= 1.20         → lifting（浮盈，拉升动力）
          1.10 <= rel < 1.20  → 无明确阶段（不投票）
        """
        extra_tags = extra_tags or {}
        ssrp = extra_tags.get("ssrp", 0) or 0
        try:
            ssrp = float(ssrp) if ssrp else 0
        except (TypeError, ValueError):
            ssrp = 0
        if not ssrp:
            return {}
        current = df["close"].values[-1]
        if current <= 0 or ssrp <= 0:
            return {}
        # 443号R2：现价距主力成本 5% 内 → 洗盘特征增强（成本区蓄势待变）
        near_cost = False
        if cost_ext:
            mfc = self._cost_value(cost_ext.get("main_force_cost"))
            if mfc and mfc > 0:
                cost_distance = abs(current - mfc) / mfc
                near_cost = cost_distance < 0.05
        if near_cost:
            vec = {"washing": 0.5, "building": 0.2}
            return self._apply_margin_signal(vec, current, cost_ext) if cost_ext else vec
        rel = current / ssrp
        dev = abs(rel - 1.0)
        if rel < 0.85:
            # 成本下方 ≠ 建仓（主力可能被套/阴跌），降级为弱支持（校准：原 0.5+ 过宽）
            vec = {"building": 0.3, "washing": 0.2}
        elif rel < 1.10:
            vec = {"washing": 0.4, "building": 0.2}                         # 成本区/浅套
        elif rel >= 1.20:
            vec = {"lifting": round(0.5 + 0.2 * min(1.0, dev), 3)}          # 浮盈
        else:
            return {}                                                       # 1.10-1.20 模糊带
        return self._apply_margin_signal(vec, current, cost_ext) if cost_ext else vec

    def _cost_value(self, cost_raw) -> float:
        """456号：归一化 cost_ext 成本值。真实库 precompute_raw 存完整返回 dict
        （main_force_cost={'cost_price','distance_pct','near_cost'}，
          margin_cost_price={'cost_price','distance_pct'}），单测用标量。二者取数值。
        """
        if cost_raw is None:
            return 0.0
        if isinstance(cost_raw, dict):
            v = cost_raw.get("cost_price")
            return float(v) if v else 0.0
        try:
            return float(cost_raw)
        except (TypeError, ValueError):
            return 0.0

    def _apply_margin_signal(self, vec: dict, current: float, cost_ext: dict) -> dict:
        """456号：融资成本价（margin_cost_price）进阶段投票——弱补充信号

        wiki《融资成本价》：融资成本价 = 散户融资平均成本价 = 解套压力位。
          - 现价 ≥ 融资成本价×1.05（站上/突破）→ 上方抛压基本释放、阻力锐减 → lifting +
          - 现价 ≤ 融资成本价×0.85（融资盘深套）→ 安全边际大/远期机会 → building +
          - 中间区（成本位下方/附近承压）→ 反弹将遇散户解套抛压 → washing +
        融资方向（暴增+滞涨=危险）属余额方向信号，framework _score_retail_contrarian /
        _assess_margin 已消费，本方法只做成本锚定的压力位弱投票。
        """
        mcp = self._cost_value((cost_ext or {}).get("margin_cost_price"))
        if not mcp or mcp <= 0 or current <= 0:
            return vec
        vec = dict(vec)
        rel_m = current / mcp
        if rel_m >= 1.05:
            vec["lifting"] = vec.get("lifting", 0) + 0.2
        elif rel_m <= 0.85:
            vec["building"] = vec.get("building", 0) + 0.1
        else:
            vec["washing"] = vec.get("washing", 0) + 0.2
        return vec

    def _dim_chan(self, extra_tags: Dict) -> dict:
        """维度8 缠论买点：buy_sell_point 标签（312 §3.2 维度8）

        校准（2026-08-02）：单买点 ≠ 主力建仓，first_buy/third_buy 降为弱支持
        （原 building 0.5 过宽，低位一买大量出现）
        """
        bsp = extra_tags.get("buy_sell_point")
        if bsp in ("first_buy", "first_buy_p", "second_buy", "third_buy", "third_buy_a", "third_buy_b"):
            return {"building": 0.3, "lifting": 0.1}
        if bsp in ("first_sell", "first_sell_p", "second_sell", "third_sell"):
            return {"distributing": 0.6}
        return {}

    def _consensus(self, dims: Dict, extra_tags: Dict):
        """加权共识：阶段总分 → 主判定 + 连续置信度 + 分歧标记（312 §3.3/§四/§五）

        修正维度（条件性）：capital_nature 调置信度
        环境加权：情绪 climax 买入证据×0.7；热点板块 washing×0.7
        """
        phases = ["building", "washing", "lifting", "distributing"]
        total = {p: 0.0 for p in phases}
        w_sum = 0.0
        active = 0
        vote_ratio = {}
        sp = extra_tags.get("sentiment_phase")
        sh = extra_tags.get("sector_heat")
        env_buy = 0.7 if sp == "climax" else 1.0
        hot_wash = 0.7 if sh in ("top_10", "top_20") else 1.0
        for name, vec in dims.items():
            if not vec:
                continue
            active += 1
            w = self._DIM_WEIGHTS.get(name, 1.0)
            w_sum += w
            vote_ratio[name] = vec
            for p, v in vec.items():
                f = env_buy if p in ("building", "lifting") else 1.0
                if p == "washing":
                    f *= hot_wash
                total[p] += w * v * f

        insufficient = self._last_dim_insufficient
        if active == 0 or w_sum == 0:
            kind = "unknown_insufficient" if insufficient else "unknown_no_evidence"
            return PHASE_UNKNOWN, 0.0, False, {"unknown_kind": kind}

        order = sorted(phases, key=lambda p: -total[p])
        top, second = order[0], order[1]
        t_sum = sum(total.values()) or 1.0
        confidence = total[top] / t_sum
        # 2026-08-10 325档案修复：冲突阈值 0.15→0.08（实测 gap∈[0.08,0.15)
        # 为噪声伪冲突，原阈值致冲突率 55.5% 失真；0.08 后约 ~35% 保留真正分歧）
        conflict = (total[top] - total[second]) / t_sum < 0.08
        if conflict:
            confidence *= 0.6

        # 主判定确认门槛（2026-08-02 校准：判定条件不足 → 不判定）
        # 支持阶段 p 的维度数 = 向量中 p 强度 > 0.25 的维度（跨维度 AND 确认，298号 ≥3 源思想的加权版）
        def _supporters(p):
            return [name for name, vec in dims.items() if vec.get(p, 0) > 0.25]
        if len(_supporters(top)) < 2:
            sup_second = _supporters(second)
            if len(sup_second) >= 2 and total[second] > 0:
                # 降级到次高阶段（若次高有 ≥2 维度确认）
                top, second = second, top
                confidence = total[top] / t_sum
                conflict = (total[top] - total[second]) / t_sum < 0.15
                if conflict:
                    confidence *= 0.6
            else:
                # 两阶段均无 ≥2 维度确认 → 条件不足，不判定
                return PHASE_UNKNOWN, 0.0, False, {"unknown_kind": "unknown_no_evidence",
                                                   "reason": "support_insufficient"}

        # 修正维度：资金性质（条件性）
        cap_nature = extra_tags.get("capital_nature")
        if cap_nature == "institutional" and not conflict:
            confidence = min(1.0, confidence + 0.05)
        elif cap_nature == "hot_money":
            confidence *= 0.8
        # 464-17：主力在场软修正（与 phase_detector.py 同步）——有在场证据提信、
        # 无在场证据（none）降信
        presence = extra_tags.get("main_force_presence")
        if presence in ("strong", "moderate"):
            confidence = min(1.0, confidence + 0.05)
        elif presence == "none":
            confidence *= 0.8
        vote_ratio["_conflict"] = bool(conflict)
        vote_ratio["_confidence"] = round(float(confidence), 4)
        vote_ratio["_supporters"] = {top: len(_supporters(top))}
        return top, confidence, conflict, vote_ratio

    def _run_trading_phase_detector_v2(self, ts_code: str, df: pd.DataFrame,
                                        chip_fund_ext: dict = None,
                                        moneyflow_df=None,
                                        indicator_other_df=None):
        """TradingPhaseDetector 阶段评分（返回 phase + scores，供维度1 阶段分布）

        412号方案C1 v3.0：chip_fund_ext由dim1通过data_context提供，
        moneyflow_df由dim1通过data_context提供。不再直接调用DataManager。
        """
        if len(df) < 60:
            self._last_dim_insufficient = True
            return None
        try:
            chip_inds = ChipIndicators()
            detector = TradingPhaseDetector(chip_inds)

            estimator = self._get_chip_estimator()
            chip_dist, min_p, max_p, step = estimator.estimate(df)
            chip_bins = []
            if step > 0:
                total = chip_dist.sum() or 1
                chip_bins = [
                    {"price_bin": round(min_p + i * step, 2),
                     "chip_ratio": float(chip_dist[i] / total)}
                    for i in range(len(chip_dist))
                ]

            indicators = chip_inds.calculate_all_indicators(
                chip_bins, df["close"].values[-1], kline_data=df, ts_code=ts_code,
                indicator_other_df=indicator_other_df)

            # 412号方案C1 v3.0：用data_context中的chip_fund_ext覆盖raw计算结果
            if chip_fund_ext:
                precomputed_map = {
                    'asr': 'asr',
                    'concentration': 'concentration',
                    'profit_ratio': 'profit_ratio',
                    'cyqkl': 'cyqkl',
                }
                for tag_key, ind_key in precomputed_map.items():
                    val = chip_fund_ext.get(tag_key)
                    if val is not None and ind_key in indicators:
                        indicators[ind_key] = val

            # moneyflow_data：优先从data_context，保留ecm fallback
            moneyflow_data = moneyflow_df  # 由调用方从data_context传入
            if moneyflow_data is None:
                try:
                    moneyflow_data = self._get_dm().get_cached_moneyflow(ts_code)
                except Exception:
                    pass

            phase_info = detector.detect_phase(
                df, chip_bins, indicators, moneyflow_data=moneyflow_data
            )
            scores = phase_info.get("scores") or {}
            return phase_info.get("phase", ""), scores
        except Exception:
            return None

    def _run_stage_detector_v2(self, df: pd.DataFrame):
        """StageDetector 阶段（返回 stage 名 + 置信度，供维度3；508批次3 收敛外部完整版）"""
        try:
            detector = StageDetector()
            stage = detector.detect(df)
            return stage.name, float(stage.confidence or 0.0)
        except Exception:
            return None

    # ═══════════════════════════════════════════════════════════
    # Step 1: 价格位置判定
    # ═══════════════════════════════════════════════════════════
    def _price_position_analysis(self, df: pd.DataFrame, ts_code: str = None,
                                  indicator_ma_df=None) -> tuple:
        """120日价格分位 + 均线排列 → (price_position, ma_alignment)

        412号方案C3 v3.0：MA5/10/20/60优先从indicator_ma_df读取（dim1通过data_context提供），
        不再直接调用DataManager。
        """
        closes = df["close"].values
        if len(closes) < 20:
            return "mid_zone", "mixed"

        # 近120日价格分位
        lookback = min(120, len(closes))
        recent_low = np.min(df["low"].values[-lookback:])
        recent_high = np.max(df["high"].values[-lookback:])
        current = closes[-1]
        if recent_high - recent_low > 1e-9:
            pos_ratio = (current - recent_low) / (recent_high - recent_low)
        else:
            pos_ratio = 0.5

        if pos_ratio < 0.3:
            price_pos = "low_zone"
        elif pos_ratio > 0.7:
            price_pos = "high_zone"
        else:
            price_pos = "mid_zone"

        # 均线排列：从indicator_ma_df读取，保留raw fallback
        def _read_ma(period):
            if indicator_ma_df is not None and not indicator_ma_df.empty:
                col = f'ma{period}'
                if col in indicator_ma_df.columns:
                    val = indicator_ma_df[col].iloc[-1]
                    if val is not None:
                        return float(val)
            return None

        ma5 = _read_ma(5)
        if ma5 is None:
            ma5 = np.mean(closes[-5:]) if len(closes) >= 5 else closes[-1]
        ma10 = _read_ma(10)
        if ma10 is None:
            ma10 = np.mean(closes[-10:]) if len(closes) >= 10 else closes[-1]
        ma20 = _read_ma(20)
        if ma20 is None:
            ma20 = np.mean(closes[-20:]) if len(closes) >= 20 else closes[-1]
        ma60 = _read_ma(60)
        if ma60 is None:
            ma60 = np.mean(closes[-60:]) if len(closes) >= 60 else closes[-1]

        if ma5 > ma10 > ma20 > ma60:
            ma_alignment = "bullish"
        elif ma5 < ma10 < ma20 < ma60:
            ma_alignment = "bearish"
        else:
            ma_alignment = "mixed"

        return price_pos, ma_alignment

    # ═══════════════════════════════════════════════════════════
    # Step 2: 量能模式
    # ═══════════════════════════════════════════════════════════
    def _volume_pattern_analysis(self, df: pd.DataFrame) -> Dict:
        """量能模式识别 → {vol_trend, vol_coordination, signal}"""
        vol = df["vol"].values if "vol" in df.columns else df.get("volume", pd.Series([0])).values
        vol = pd.Series(vol).astype(float)
        result = {"vol_trend": "stable", "vol_coordination": "neutral", "signal": "neutral"}

        if len(vol) < 20:
            return result

        ma5_vol = vol.rolling(5).mean().values
        ma20_vol = vol.rolling(20).mean().values

        latest_ma5 = ma5_vol[-1] if not np.isnan(ma5_vol[-1]) else 0
        latest_ma20 = ma20_vol[-1] if not np.isnan(ma20_vol[-1]) else 0

        # 量比趋势
        if latest_ma20 > 0:
            vol_ratio = latest_ma5 / latest_ma20
        else:
            vol_ratio = 1.0

        if vol_ratio > 1.3:
            result["vol_trend"] = "expanding"
        elif vol_ratio < 0.7:
            result["vol_trend"] = "shrinking"
        else:
            result["vol_trend"] = "stable"

        # 量价协调性：最近5日价格方向与量方向
        if len(df) >= 10:
            price_change = df["close"].values[-1] - df["close"].values[-5]
            vol_change = ma5_vol[-1] - ma5_vol[-5] if len(ma5_vol) >= 5 else 0
            if price_change > 0 and vol_change > 0:
                result["vol_coordination"] = "positive"  # 价涨量增 → 健康
                result["signal"] = "lifting"
            elif price_change > 0 and vol_change < 0:
                result["vol_coordination"] = "divergent_up"  # 价涨量缩 → 可疑
                result["signal"] = "distributing"
            elif price_change < 0 and vol_change > 0:
                result["vol_coordination"] = "divergent_down"  # 价跌量增 → 恐慌
                result["signal"] = "washing"
            else:
                result["vol_coordination"] = "neutral"
                result["signal"] = "building"

        return result

    # ═══════════════════════════════════════════════════════════
    # Step 3: 资金流向
    # ═══════════════════════════════════════════════════════════
    def _analyze_fund_flow(self, ts_code: str, moneyflow_df=None) -> str:
        """5日资金流向 → fund_flow 标签"""
        try:
            # 464-9：优先用 dim1 已注入的 moneyflow_df（与 443/dim2 同构接线），
            # 避免 ECM 直读 get_cached_moneyflow 在 daemon 写锁时失败导致整体降级。
            mf_df = moneyflow_df
            if mf_df is None or (hasattr(mf_df, 'empty') and mf_df.empty):
                mf_df = self._get_dm().get_cached_moneyflow(ts_code)
            if mf_df is None or (hasattr(mf_df, 'empty') and mf_df.empty):
                return "none"
            mf_5 = mf_df.tail(5)
            if mf_5.empty:
                return "none"

            net_sum = mf_5["net_lg_amount"].sum()
            pos_days = (mf_5["net_lg_amount"] > 0).sum()
            neg_days = (mf_5["net_lg_amount"] < 0).sum()

            if net_sum > 0 and pos_days >= 3:
                return "5d_inflow"
            elif net_sum < 0 and neg_days >= 3:
                return "5d_outflow"
            elif net_sum > 0:
                return "mixed"
            elif net_sum < 0:
                return "mixed"
            return "none"
        except Exception:
            return "none"

    def _fund_flow_to_phase(self, fund_flow: str) -> str:
        """资金流向 → 阶段映射"""
        mapping = {
            "5d_inflow": PHASE_LIFTING,
            "5d_outflow": PHASE_DISTRIBUTING,
            "mixed": PHASE_WASHING,
            "none": PHASE_UNKNOWN,
        }
        return mapping.get(fund_flow, PHASE_UNKNOWN)

    # ═══════════════════════════════════════════════════════════
    # Step 4: 筹码分布确认
    # ═══════════════════════════════════════════════════════════
    def _get_chip_estimator(self):
        if self._chip_estimator is None:
            # 508批次3：外部权威 ChipDistributionEstimator（算法等价收敛）
            self._chip_estimator = ChipDistributionEstimator()
        return self._chip_estimator

    def _chip_distribution_analysis(self, ts_code: str, df: pd.DataFrame) -> Dict:
        """筹码分布分析 → {asr, peak_position}"""
        result = {"asr": 0.0, "peak_position": 0.0}

        estimator = self._get_chip_estimator()
        try:
            chip_dist, min_p, max_p, step = estimator.estimate(df)
            if step <= 0:
                return result
            current_price = df["close"].values[-1]

            # 计算 ASR (±5%)
            band_pct = 0.05
            price_low = current_price * (1 - band_pct)
            price_high = current_price * (1 + band_pct)

            total_chips = chip_dist.sum()
            if total_chips <= 0:
                return result

            asr = sum(
                chip_dist[i]
                for i in range(len(chip_dist))
                if price_low <= min_p + i * step <= price_high
            ) / total_chips
            # 2026-08-13 知识库对齐：ASR 0-100 量级（原 0-1）
            result["asr"] = round(asr * 100, 2)

            # 筹码主峰
            peak_idx = int(np.argmax(chip_dist))
            peak_price = min_p + peak_idx * step
            result["peak_position"] = peak_price

        except Exception:
            pass

        return result

    # ═══════════════════════════════════════════════════════════
    # 源1: TradingPhaseDetector
    # ═══════════════════════════════════════════════════════════
    def _run_trading_phase_detector(self, ts_code: str, df: pd.DataFrame) -> str:
        """调用 TradingPhaseDetector 获取操盘阶段"""
        if len(df) < 60:
            return PHASE_UNKNOWN
        try:
            # 使用内部定义的 ChipIndicators 和 TradingPhaseDetector（物理合入）
            chip_inds = ChipIndicators()
            detector = TradingPhaseDetector(chip_inds)

            # 构造简化的 chip_bins
            self._chip_distribution_analysis(ts_code, df)
            estimator = self._get_chip_estimator()
            chip_dist, min_p, max_p, step = estimator.estimate(df)
            chip_bins = []
            if step > 0:
                total = chip_dist.sum() or 1
                chip_bins = [
                    {"price_bin": round(min_p + i * step, 2),
                     "chip_ratio": float(chip_dist[i] / total)}
                    for i in range(len(chip_dist))
                ]

            indicators = chip_inds.calculate_all_indicators(
                chip_bins, df["close"].values[-1], kline_data=df, ts_code=ts_code)

            moneyflow_data = None
            try:
                moneyflow_data = self._get_dm().get_cached_moneyflow(ts_code)
            except Exception:
                pass

            phase_info = detector.detect_phase(
                df, chip_bins, indicators, moneyflow_data=moneyflow_data
            )
            phase_raw = phase_info.get("phase", "")
            mapping = {
                "BUILDING": PHASE_BUILDING,
                "WASHING": PHASE_WASHING,
                "RAISING": PHASE_LIFTING,
                "SHIPPING": PHASE_DISTRIBUTING,
                "SUPPORT": PHASE_WASHING,
            }
            return mapping.get(phase_raw, PHASE_UNKNOWN)
        except Exception:
            return PHASE_UNKNOWN

    # ═══════════════════════════════════════════════════════════
    # 源2: StageDetector
    # ═══════════════════════════════════════════════════════════
    def _run_stage_detector(self, df: pd.DataFrame) -> str:
        """调用 StageDetector 获取四阶段"""
        try:
            # 508批次3：外部权威 StageDetector（完整版四阶段）
            detector = StageDetector()
            stage = detector.detect(df)
            name = stage.name
            mapping = {
                "UPTREND_ACTIVE": PHASE_LIFTING,
                "UPTREND_TOPPING": PHASE_DISTRIBUTING,
                "DOWNTREND_BOTTOMING": PHASE_BUILDING,
                "DOWNTREND_ACTIVE": PHASE_BUILDING,
                "CONSOLIDATION": PHASE_WASHING,
            }
            return mapping.get(name, PHASE_UNKNOWN)
        except Exception:
            return PHASE_UNKNOWN

    # ═══════════════════════════════════════════════════════════
    # 趋势方向
    # ═══════════════════════════════════════════════════════════
    def _detect_trend_direction(self, df: pd.DataFrame) -> str:
        """趋势方向判定 (up_aligned / down_aligned / mixed / no_trend)"""
        closes = df["close"].values
        if len(closes) < 20:
            return "no_trend"

        # 三个周期方向一致性
        def _slope(arr):
            return (arr[-1] - arr[0]) / max(arr[0], 1)

        short_up = _slope(closes[-5:]) > 0.01 if len(closes) >= 5 else False
        mid_up = _slope(closes[-20:]) > 0.01 if len(closes) >= 20 else False
        long_up = _slope(closes[-60:]) > 0.01 if len(closes) >= 60 else False

        up_count = sum([short_up, mid_up, long_up])
        if up_count >= 2:
            return "up_aligned"
        elif up_count <= 0:
            return "down_aligned"
        return "mixed"

    # ═══════════════════════════════════════════════════════════
    # 源5: VolumePrice 量价趋势
    # ═══════════════════════════════════════════════════════════
    def _volume_signal_to_phase(self, volume_signal: Dict, trend_dir: str) -> str:
        """量价趋势信号 → 阶段"""
        signal = volume_signal.get("signal", "neutral")
        if signal == "lifting":
            return PHASE_LIFTING
        elif signal == "distributing":
            return PHASE_DISTRIBUTING
        elif signal == "washing":
            return PHASE_WASHING
        elif signal == "building":
            return PHASE_BUILDING
        # 从趋势方向降级
        if trend_dir == "up":
            return PHASE_LIFTING
        elif trend_dir == "down":
            return PHASE_DISTRIBUTING
        return PHASE_UNKNOWN

    # ═══════════════════════════════════════════════════════════
    # 投票决策
    # ═══════════════════════════════════════════════════════════
    def _vote_decision(self, votes: list, source_names: list) -> tuple:
        """
        五源投票 → (final_phase, confidence)

        - ≥3 一致 → 确认
        - 2 一致 → 可疑但采纳最高票
        - 全部不一致 / 无有效票 → unknown
        """
        if not votes:
            return PHASE_UNKNOWN, 0.0

        from collections import Counter
        counter = Counter(votes)
        top_phase, top_count = counter.most_common(1)[0]

        total_sources = len(votes)
        if top_count >= 3:
            # ≥3 源一致 → 确认
            confidence = top_count / max(total_sources, 1)
            return top_phase, min(confidence, 1.0)
        elif top_count == 2 and total_sources >= 4:
            # 4-5源中仅2一致 → 可疑
            confidence = 0.4
            return top_phase, confidence
        elif top_count == 2 and total_sources >= 2:
            confidence = 0.35
            return top_phase, confidence

        # 全部不一致 → unknown
        return PHASE_UNKNOWN, 0.0

    # ═══════════════════════════════════════════════════════════
    # 涨停交叉校验
    # ═══════════════════════════════════════════════════════════
    def _limit_up_cross_check(self, df: pd.DataFrame, current_phase: str,
                              price_position: str) -> str:
        """涨停时校验阶段合理性（298号§三Step5 四种规则）

        规则1/2/4：当日(T)涨停触发，用当日位置/量。
        规则3（464-12 改窗口）：前一日(T-1)高位涨停巨量 + 当日(T)低开≥3% → 当日初判
        lifting 修正为 distributing。忠实 298「放量涨停次日低开=诱多出货」在日终日频
        节奏下的近似——T 结论形成时 T+1 数据尚不存在，故"次日"取 T、涨停日取 T-1，
        **当日无需涨停**（单涨停+次日低开场景不再漏检；双涨停低开高走被本规则覆盖）。
        """
        try:
            if len(df) < 2:
                return current_phase
            latest = df.iloc[-1]
            prev_close = df.iloc[-2]["close"]
            pct_chg = latest.get("pct_chg", None)
            if pct_chg is None:
                pct_chg = (latest["close"] - prev_close) / max(prev_close, 1) * 100

            volumes = df["vol"].values if "vol" in df.columns else None

            # ── 规则3（464-12）：前一日(T-1)高位涨停巨量 + 当日(T)低开≥3% ──
            # 独立于当日涨停（T 无需涨停）；T 涨停时同样适用（双涨停+第二日低开被覆盖）。
            if current_phase == PHASE_LIFTING and len(df) >= 3 and volumes is not None and len(volumes) >= 61:
                pc_prev = (df.iloc[-2]["close"] - df.iloc[-3]["close"]) / max(df.iloc[-3]["close"], 1) * 100
                prev_limit_up = pc_prev > 9.5
                vol_60_avg_prev = np.mean(volumes[-61:-1])  # T-1 之前的 60 日均量
                prev_huge_vol = volumes[-2] > vol_60_avg_prev * 2
                low_open_today = float(latest.get("open", latest["close"])) < prev_close * 0.97
                # 高位以当日 price_position 近似前一日涨停日位置（两日间隔位置变化小）
                if prev_limit_up and prev_huge_vol and price_position == "high_zone" and low_open_today:
                    return PHASE_DISTRIBUTING

            # 以下规则1/2/4：当日(T)涨停才触发
            if not (pct_chg > 9.5):
                return current_phase

            # 价格位置判定
            low_zone = price_position == "low_zone"
            high_zone = price_position == "high_zone"

            # 巨量：当日成交量 > 60日均量 × 2
            huge_vol = False
            shrink_vol = False
            if volumes is not None and len(volumes) >= 60:
                vol_60_avg = np.mean(volumes[-60:])
                today_vol = volumes[-1]
                huge_vol = today_vol > vol_60_avg * 2
                shrink_vol = today_vol < vol_60_avg * 0.6

            # ── 规则1: building + 低位涨停 + not 巨量 → 确认 building
            if current_phase == PHASE_BUILDING and low_zone and not huge_vol:
                return PHASE_BUILDING

            # ── 规则2: building + 高位涨停 → 修正为 distributing
            if current_phase == PHASE_BUILDING and high_zone:
                return PHASE_DISTRIBUTING

            # ── 规则4: distributing + 低位涨停 + 缩量 → 修正为 building/washing
            if current_phase == PHASE_DISTRIBUTING and low_zone and shrink_vol:
                return PHASE_BUILDING

            return current_phase
        except Exception:
            return current_phase


# === chip_strategy_impl.py ===

class TradingPhaseDetector:
    """
    操盘阶段检测器
    识别：建仓期 / 洗盘期 / 拉升期 / 出货期 / 下跌期

    V2改进: 资金流向集成 — 各阶段评分加入 moneyflow 大单维度
    """

    def __init__(self, chip_indicators: ChipIndicators):
        self.chip_indicators = chip_indicators

    def detect_phase(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict,
                    chip_bins_history: Optional[List[List[Dict]]] = None,
                    moneyflow_data: Optional[pd.DataFrame] = None) -> Dict:
        """
        检测当前操盘阶段

        Args:
            kline_data: K线数据
            chip_bins: 筹码分布数据
            indicators: 筹码指标
            chip_bins_history: 历史筹码分布（用于筹码转移方向检测）
            moneyflow_data: 资金流向数据（V2方向5新增）

        Returns:
            阶段信息字典
        """
        if len(kline_data) < 60:
            return {'phase': 'UNKNOWN', 'confidence': 0.0, 'reason': '数据不足'}

        # 计算筹码转移信息（如提供历史数据）
        transfer_info = None
        if chip_bins_history is not None:
            try:
                transfer_info = self.chip_indicators.detect_chip_transfer(chip_bins_history, lookback=20)
            except Exception:
                pass

        # 计算资金流向评分（V2方向5）
        moneyflow_score = self._calc_moneyflow_score(moneyflow_data)

        # 计算各阶段得分
        scores = {
            'BUILDING': self._score_building(kline_data, chip_bins, indicators, transfer_info, moneyflow_score),
            'WASHING': self._score_washing(kline_data, chip_bins, indicators, transfer_info, moneyflow_score),
            'RAISING': self._score_raising(kline_data, chip_bins, indicators, transfer_info, moneyflow_score),
            'SHIPPING': self._score_shipping(kline_data, chip_bins, indicators, transfer_info, moneyflow_score),
            'SUPPORT': self._score_support(kline_data, chip_bins, indicators, transfer_info, moneyflow_score)
        }

        best_phase = max(scores.items(), key=lambda x: x[1])
        total_score = sum(scores.values())

        confidence = best_phase[1] / max(total_score, 1)

        return {
            'phase': best_phase[0],
            'confidence': round(confidence, 4),
            'scores': scores,
            'moneyflow_score': moneyflow_score
        }

    def _calc_moneyflow_score(self, moneyflow_data: Optional[pd.DataFrame], period: int = 5) -> Dict:
        """
        计算资金流向评分 (V2方向5)

        Returns:
            {'avg_net_lg': float, 'positive_ratio': float,
             'is_positive_streak': bool, 'is_negative_streak': bool,
             'direction': int}  # 1=净流入, -1=净流出, 0=中性
        """
        default = {
            'avg_net_lg': 0, 'positive_ratio': 0.0,
            'is_positive_streak': False, 'is_negative_streak': False,
            'direction': 0, 'available': False
        }
        if moneyflow_data is None or moneyflow_data.empty:
            return default
        try:
            recent = moneyflow_data.tail(period)
            net_lg = recent['net_lg_amount'].values
            if len(net_lg) == 0:
                return default
            avg_net = float(np.mean(net_lg))
            positive_days = sum(1 for v in net_lg if v > 0)
            return {
                'avg_net_lg': avg_net,
                'positive_ratio': positive_days / len(net_lg),
                'is_positive_streak': bool(all(v > 0 for v in net_lg)),
                'is_negative_streak': bool(all(v < 0 for v in net_lg)),
                'direction': 1 if avg_net > 0 else (-1 if avg_net < 0 else 0),
                'available': True
            }
        except Exception:
            return default

    def _score_building(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict,
                        transfer_info: Optional[Dict] = None,
                        moneyflow_score: Optional[Dict] = None) -> float:
        """建仓期评分"""
        score = 0.0

        if indicators.get('profit_ratio', 0) < 0.4:
            score += 2.0
        # 2026-08-13 知识库对齐：ASR 0-100 量级（原 0.7）
        if indicators.get('asr', 0) >= 70:
            score += 2.0
        conc = indicators.get('concentration')
        # 集中度数值（前 20% 价位筹码占比，高=集中）。该键由 chip_fund_ext/实时分布产出，
        # concentration_status 中文枚举从未被生产（445「集中度一词两义」惰性分支）→ 接真实数值。
        # wiki《筹码分布分析-主力视角》：筹码从分散到集中=建仓蓄势。
        if conc is not None and float(conc) > 0.3:
            score += 2.0
        if len(kline_data) >= 60:
            closes = kline_data['close'].values
            min_60, max_60 = np.min(closes[-60:]), np.max(closes[-60:])
            if max_60 - min_60 > 0 and (closes[-1] - min_60) / (max_60 - min_60) < 0.4:
                score += 2.0

        # V2方向5: 大单净额持续为正但股价不涨 => 建仓吸筹
        if moneyflow_score and moneyflow_score.get('available'):
            if moneyflow_score['is_positive_streak']:
                closes = kline_data['close'].values
                price_up = (closes[-1] / closes[-min(5, len(closes))] - 1) < 0.03 if len(closes) >= 5 else False
                if price_up:
                    score += 2.0  # 持续净流入但股价不涨 -> 建仓痕迹
                else:
                    score += 1.5  # 持续净流入且慢涨 -> 建仓偏拉升

        return score

    def _score_washing(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict,
                       transfer_info: Optional[Dict] = None,
                       moneyflow_score: Optional[Dict] = None) -> float:
        """洗盘期评分"""
        score = 0.0

        rsi = indicators.get('rsi', 50)
        if 30 <= rsi <= 55:
            score += 2.0
        vol_status = indicators.get('vol_status', '')
        if vol_status in ('缩量', '地量'):
            score += 2.0
        asr = indicators.get('asr', 0)
        # 2026-08-13 知识库对齐：ASR 0-100 量级（原 0.3-0.6）
        if 30 <= asr <= 60:
            score += 1.5
        ssrp = indicators.get('ssrp', 0)
        if ssrp > 0 and len(kline_data) > 0:
            cp = kline_data['close'].iloc[-1]
            if ssrp * 0.9 < cp < ssrp * 1.05:
                score += 1.5

        if transfer_info is not None:
            tr_type = transfer_info.get('transfer_type', '')
            low_chg = transfer_info.get('low_chips_change', 0)
            if tr_type == '稳定' and low_chg >= -0.02:
                score += 2.0
            elif tr_type == '向下转移' and low_chg > 0:
                score += 2.0

        # V2方向5: 大单净额为负后转正企稳 => 洗盘尾声
        if moneyflow_score and moneyflow_score.get('available'):
            if moneyflow_score['direction'] == 1 and moneyflow_score['positive_ratio'] >= 0.6:
                score += 1.5  # 净流入转正 -> 洗盘结束征兆

        return score

    def _score_raising(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict,
                       transfer_info: Optional[Dict] = None,
                       moneyflow_score: Optional[Dict] = None) -> float:
        """拉升期评分"""
        score = 0.0

        ssrp = indicators.get('ssrp', 0)
        if ssrp > 0 and len(kline_data) > 0:
            cp = kline_data['close'].iloc[-1]
            if cp > ssrp * 1.05:
                score += 2.0
        if indicators.get('profit_ratio', 0) >= 0.6:
            score += 2.0
        vol_status = indicators.get('vol_status', '')
        if vol_status in ('放量', '显著放量', '天量'):
            score += 2.0
        if indicators.get('cyqkl_status', '') in ('强', '很强', '极强'):
            score += 1.5

        if transfer_info is not None:
            tr_type = transfer_info.get('transfer_type', '')
            if tr_type == '向上转移':
                score += 2.0
            elif tr_type == '稳定' and indicators.get('profit_ratio', 0) >= 0.5:
                score += 1.0

        # V2方向5: 大单净额持续为正且放大 => 拉升
        if moneyflow_score and moneyflow_score.get('available'):
            if moneyflow_score['is_positive_streak'] and abs(moneyflow_score['avg_net_lg']) > 0:
                score += 2.0

        return score

    def _score_shipping(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict,
                        transfer_info: Optional[Dict] = None,
                        moneyflow_score: Optional[Dict] = None) -> float:
        """出货期评分"""
        score = 0.0

        profit_ratio = indicators.get('profit_ratio', 0)
        if profit_ratio >= 0.7 and len(kline_data) >= 5:
            closes = kline_data['close'].values
            if closes[-1] < closes[-5]:
                score += 2.5
        vol_status = indicators.get('vol_status', '')
        if vol_status in ('缩量', '地量'):
            score += 2.0
        rsi = indicators.get('rsi', 0)
        if rsi >= 70:
            score += 1.5

        # V2方向5: 大单净额为负且小单为正 => 出货
        if moneyflow_score and moneyflow_score.get('available'):
            if moneyflow_score['is_negative_streak']:
                score += 2.0

        return score

    def _score_support(self, kline_data: pd.DataFrame, chip_bins: List[Dict], indicators: Dict,
                       transfer_info: Optional[Dict] = None,
                       moneyflow_score: Optional[Dict] = None) -> float:
        """下跌支撑期评分"""
        score = 0.0
        if indicators.get('profit_ratio', 0) < 0.35:
            score += 2.0
        if indicators.get('rsi', 50) < 30:
            score += 2.0
        ssrp = indicators.get('ssrp', 0)
        if ssrp > 0 and len(kline_data) > 0:
            cp = kline_data['close'].iloc[-1]
            if cp < ssrp * 0.9:
                score += 2.0
        return score


class CrowdingFactor:
    """
    拥挤度因子模型

    从三个维度评估股票的筹码拥挤程度：
    1. 融资余额占比（融资余额/流通市值）
    2. 换手率异常（当前换手率 vs 20日均值）
    3. 波动率压缩（布林带宽度 vs 历史分位）

    综合判断结果为 HIGH_CROWDING / MODERATE / LOW_CROWDING。
    """

    HIGH_CROWDING = 'HIGH_CROWDING'
    MODERATE = 'MODERATE'
    LOW_CROWDING = 'LOW_CROWDING'

    def __init__(self):
        self._name = 'CrowdingFactor'

    @property
    def name(self) -> str:
        return self._name

    def calc_margin_ratio(self, ts_code: str, market_context: Optional[Dict] = None) -> Optional[float]:
        """
        计算融资余额占比。
        融资余额占比 = 融资余额 / 流通市值。

        Args:
            ts_code: 股票代码
            market_context: 市场上下文（可选），含 margin_df（461-5：dim1 data_context 缓存）
                + daily_basic_df（464-6：流通市值 circ_mv 来源）

        Returns:
            Optional[float]: 融资余额占比，数据不可用时返回 None
        """
        # 461-5：优先读 dim1 预载缓存的 margin_df（data_context, market_context），
        # 回退缓存读取 get_cached_margin，最后才 Tushare 实时 API get_margin
        # （原 calc_margin_ratio 恒 API 直查，绕过 dim1 且每次 evaluate 打接口——460 偏差2）。
        try:
            margin_df = market_context.get('margin_df') if market_context else None
            if margin_df is None or (hasattr(margin_df, 'empty') and margin_df.empty):
                from app.data import DataManager
                dm = DataManager()
                margin_df = dm.get_cached_margin(ts_code)
            if margin_df is None or (hasattr(margin_df, 'empty') and margin_df.empty):
                from app.data import DataManager
                dm = DataManager()
                margin_df = dm.get_margin(ts_code)

            if margin_df is None or (hasattr(margin_df, 'empty') and margin_df.empty):
                return None

            # 取最新一条融资数据
            latest = margin_df.iloc[-1]

            # 尝试获取融资余额和流通市值
            margin_balance = None
            circ_mv = None

            if isinstance(latest, (dict, pd.Series)):
                # 464-6：margin_cache 实际列为 Tushare margin_detail 原样——融资余额列是
                # rzye（单位元）；原白名单（marge_balance/融资余额/marge/balance）恒不命中
                # → 融资分项恒 None，crowding 三态退化为恒 MODERATE(0.5)。
                for col in ('rzye', 'marge_balance', '融资余额', 'marge', 'balance'):
                    if col in latest:
                        try:
                            val = float(latest[col])
                            if pd.notna(val) and val > 0:
                                margin_balance = val
                                break
                        except (ValueError, TypeError, KeyError):
                            continue

                for col in ('circ_mv', '流通市值', 'circulating_mv', 'mv'):
                    if col in latest:
                        try:
                            val = float(latest[col])
                            if pd.notna(val) and val > 0:
                                circ_mv = val
                                break
                        except (ValueError, TypeError, KeyError):
                            continue

            # 464-6：margin_cache 无流通市值列（流通市值在 daily_basic_cache）——
            # 从 market_context.daily_basic_df（dim1 预载，单位万元）按最新融资日期的
            # trade_date 对齐取 circ_mv，无精确匹配回退最新一行；daily_basic 兜底读缓存。
            circ_mv_from_daily_basic = False
            if circ_mv is None:
                try:
                    db_df = market_context.get('daily_basic_df') if market_context else None
                    if db_df is None or (hasattr(db_df, 'empty') and db_df.empty):
                        from app.data import DataManager
                        db_df = DataManager().get_cached_daily_basic(ts_code)
                    if db_df is not None and not (hasattr(db_df, 'empty') and db_df.empty) \
                            and 'circ_mv' in db_df.columns:
                        _date = None
                        try:
                            _date = latest.get('trade_date')
                        except Exception:
                            _date = None
                        if _date is not None:
                            _row = db_df[db_df['trade_date'] == _date]
                            if not _row.empty:
                                _circ = float(_row.iloc[-1]['circ_mv'])
                            else:
                                _circ = float(db_df['circ_mv'].dropna().iloc[-1])
                        else:
                            _circ = float(db_df['circ_mv'].dropna().iloc[-1])
                        if pd.notna(_circ) and _circ > 0:
                            circ_mv = _circ
                            circ_mv_from_daily_basic = True
                except Exception:
                    circ_mv = None

            if margin_balance is not None and circ_mv is not None and circ_mv > 0:
                # 464-6：rzye 单位元、daily_basic circ_mv 单位万元 → 统一为元后再比
                # （1.71e10 / (1.5715e8万 * 1e4) ≈ 0.0109，茅台融资占比~1%）
                if circ_mv_from_daily_basic:
                    ratio = margin_balance / (circ_mv * 1e4)
                else:
                    ratio = margin_balance / circ_mv
                return min(1.0, max(0.0, ratio))

            return None

        except Exception:
            return None

    def calc_turnover_crowding(
        self,
        df: pd.DataFrame,
        turnover_data: Optional[pd.Series] = None,
    ) -> str:
        """
        通过换手率评估拥挤度。

        Args:
            df: 行情数据 DataFrame（需含 turnover_rate 或 turn 列）
            turnover_data: 可选的换手率序列，优先使用

        Returns:
            str: 'HIGH_TURNOVER' / 'NORMAL_TURNOVER' / 'LOW_TURNOVER'
        """
        if turnover_data is not None and not turnover_data.empty:
            turn_series = turnover_data
        elif df is not None and not df.empty:
            # 尝试从 df 中获取换手率列
            turn_col = None
            for col in ('turnover_rate', 'turn', 'turnover', '换手率'):
                if col in df.columns:
                    turn_col = col
                    break
            if turn_col is None:
                return 'NORMAL_TURNOVER'
            turn_series = df[turn_col]
        else:
            return 'NORMAL_TURNOVER'

        try:
            # 清理缺失值
            turn_series = turn_series.dropna()
            if len(turn_series) < 5:
                return 'NORMAL_TURNOVER'

            current_turnover = float(turn_series.iloc[-1])
            # 使用最近 20 个交易日计算均值
            lookback = min(20, len(turn_series))
            avg_turnover = float(turn_series.iloc[-lookback:].mean())

            if avg_turnover <= 0:
                return 'NORMAL_TURNOVER'

            ratio = current_turnover / avg_turnover

            if ratio > 1.5:
                return 'HIGH_TURNOVER'
            elif ratio < 0.5:
                return 'LOW_TURNOVER'
            else:
                return 'NORMAL_TURNOVER'

        except Exception:
            return 'NORMAL_TURNOVER'

    def calc_volatility_crowding(self, df: pd.DataFrame) -> str:
        """
        通过波动率（布林带宽度）评估拥挤度。
        压缩窄带 = 潜在的筹码集中（拥挤），
        宽带 = 筹码分散（不拥挤）。

        Args:
            df: 行情数据 DataFrame（需含 close 列，至少 60 个交易日）

        Returns:
            str: 'HIGH_CROWDING' / 'MODERATE_CROWDING' / 'LOW_CROWDING'
        """
        if df is None or df.empty or 'close' not in df.columns:
            return 'MODERATE_CROWDING'

        try:
            close = df['close'].values
            if len(close) < 60:
                return 'MODERATE_CROWDING'

            # 计算 20 日布林带宽度
            bb_widths = []
            for i in range(20, len(close)):
                window = close[i - 20:i]
                mean = np.mean(window)
                std = np.std(window, ddof=1)
                if mean != 0:
                    # 布林带宽度 = (上轨 - 下轨) / 中轨 = 4 * std / mean
                    width = 4.0 * std / mean
                    bb_widths.append(width)

            if len(bb_widths) < 40:
                return 'MODERATE_CROWDING'

            # 当前带宽
            current_width = bb_widths[-1]

            # 历史分位（取最近 60 个交易日的历史窗口）
            history_window = bb_widths[:]
            p20 = np.percentile(history_window, 20)
            p80 = np.percentile(history_window, 80)

            if current_width < p20:
                return 'HIGH_CROWDING'
            elif current_width > p80:
                return 'LOW_CROWDING'
            else:
                return 'MODERATE_CROWDING'

        except Exception:
            return 'MODERATE_CROWDING'

    def evaluate(
        self,
        ts_code: str,
        df: pd.DataFrame,
        market_context: Optional[Dict] = None,
    ) -> Dict:
        """
        综合评估股票筹码拥挤度。

        规则：
        - 至少满足 2/3 条件（高融资比 / 高换手 / 低波动）= HIGH_CROWDING
        - 至少满足 2/3 条件（低融资比 / 低换手 / 高波动）= LOW_CROWDING
        - 否则 MODERATE

        Args:
            ts_code: 股票代码
            df: 行情数据 DataFrame
            market_context: 市场上下文（可选）

        Returns:
            Dict: {
                'crowding_level': str,
                'crowding_score': float,       # 0-1，越高越拥挤
                'risk_advice': str,
                'details': dict,
            }
        """
        details: Dict = {}
        evidence: List[str] = []

        # 1. 融资余额占比
        margin_ratio = None
        try:
            margin_ratio = self.calc_margin_ratio(ts_code, market_context=market_context)
        except Exception:
            pass

        margin_signals = {'high': False, 'low': False}
        if margin_ratio is not None:
            details['margin_ratio'] = round(margin_ratio, 6)
            # 融资余额 > 流通市值 5% 视为偏高
            if margin_ratio > 0.05:
                margin_signals['high'] = True
                evidence.append(f'融资余额占比 {margin_ratio:.4%} > 5%，偏高')
            elif margin_ratio < 0.01:
                margin_signals['low'] = True
                evidence.append(f'融资余额占比 {margin_ratio:.4%} < 1%，偏低')
            else:
                evidence.append(f'融资余额占比 {margin_ratio:.4%}，适中')
        else:
            details['margin_ratio'] = None
            evidence.append('融资数据不可用')

        # 2. 换手率拥挤
        turnover_data = None
        if market_context:
            turnover_data = market_context.get('turnover_data', None)

        turnover_state = 'NORMAL_TURNOVER'
        try:
            turnover_state = self.calc_turnover_crowding(df, turnover_data)
        except Exception:
            pass

        turnover_signals = {'high': False, 'low': False}
        details['turnover_state'] = turnover_state
        if turnover_state == 'HIGH_TURNOVER':
            turnover_signals['high'] = True
            evidence.append('换手率偏高（> 20日均值1.5倍），筹码集中')
        elif turnover_state == 'LOW_TURNOVER':
            turnover_signals['low'] = True
            evidence.append('换手率偏低（< 20日均值0.5倍），筹码分散')
        else:
            evidence.append('换手率正常')

        # 3. 波动率拥挤
        vol_state = 'MODERATE_CROWDING'
        try:
            vol_state = self.calc_volatility_crowding(df)
        except Exception:
            pass

        vol_signals = {'high': False, 'low': False}
        details['volatility_state'] = vol_state
        if vol_state == self.HIGH_CROWDING:
            vol_signals['high'] = True
            evidence.append('波动率压缩（布林带窄），筹码可能集中')
        elif vol_state == self.LOW_CROWDING:
            vol_signals['low'] = True
            evidence.append('波动率扩张（布林带宽），筹码分散')
        else:
            evidence.append('波动率正常')

        # 4. 综合判定
        high_count = sum([margin_signals['high'], turnover_signals['high'], vol_signals['high']])
        low_count = sum([margin_signals['low'], turnover_signals['low'], vol_signals['low']])

        # 464-6：订正为 3 维制——每维仅在实际取得有效信号时计数。
        # 此前换手/波动恒计 1（"总有结果"），融资维死后退化为 2/2 制而非注释的 2/3 制。
        # turnover_data 缺省且 daily_df 无换手列 → 换手维无有效信号；df 不足 60 根 → 波动维无法计算。
        turnover_valid = (
            turnover_data is not None and not turnover_data.empty
        ) or (
            df is not None and not df.empty
            and any(c in df.columns for c in ('turnover_rate', 'turn', 'turnover', '换手率'))
        )
        vol_valid = (
            df is not None and not df.empty and 'close' in df.columns
            and len(pd.Series(df['close']).dropna()) >= 60
        )
        valid_signals = sum([
            1 if margin_ratio is not None else 0,
            1 if turnover_valid else 0,
            1 if vol_valid else 0,
        ])

        if valid_signals < 3:
            evidence.append(f'有效信号维度数 {valid_signals}/3')

        # 至少 2/3 的拥挤信号
        if high_count >= 2 and valid_signals >= 2:
            crowding_level = self.HIGH_CROWDING
            crowding_score = 0.7 + 0.1 * min(high_count, 3)
            risk_advice = '拥挤度高，建议谨慎参与，注意回调风险'
        # 至少 2/3 的低拥挤信号
        elif low_count >= 2 and valid_signals >= 2:
            crowding_level = self.LOW_CROWDING
            crowding_score = 0.1 + 0.1 * max(0, 2 - low_count)
            risk_advice = '拥挤度低，可关注介入机会'
        else:
            crowding_level = self.MODERATE
            crowding_score = 0.5
            risk_advice = '拥挤度适中，正常关注'

        details['margin_signals'] = margin_signals
        details['turnover_signals'] = turnover_signals
        details['volatility_signals'] = vol_signals
        details['valid_signals'] = valid_signals
        details['evidence'] = evidence

        # 裁剪 crowding_score 到 [0, 1]
        crowding_score = max(0.0, min(1.0, crowding_score))

        return {
            'crowding_level': crowding_level,
            'crowding_score': round(crowding_score, 4),
            'risk_advice': risk_advice,
            'details': details,
        }


# === tag_extractor.py ===

def extract_chanlun_deep_tags(ts_code: str) -> dict:
    """从 strategy_signal_detail 缠论信号提取深度字段（缠论结构组）

    Returns:
        {support_resistance: JSON, zhongshu_strength: str, multi_level: JSON,
         near_levels_filtered: JSON, active_signal: str, active_signal_label: str,
         level_upper_limit: str, momentum: JSON, state_label: str, risk_level: str}
        信号缺失时返回空 dict。
    """
    try:
        dm = DataManager()
        cached = dm.cache.get_latest_signal_detail(ts_code)
        if not cached:
            return {}
        signals = cached.get('signals', {})
        chanlun = None
        for name, s in signals.items():
            if '缠论' in name:
                chanlun = s
                break
        if not chanlun:
            return {}
        sr = chanlun.get('status_recognition', {})
        out = {}
        # 缠论结构深度字段（structure 组）
        # 2026-08-10 核查修复：None 值跳过（原 str(None) 产生字面 "None" 假值）
        def _mk(v, is_json=False):
            if v is None:
                return None
            return (json.dumps(v, ensure_ascii=False) if is_json else str(v))
        if 'support_resistance' in sr:
            _v = _mk(sr['support_resistance'], is_json=True)
            if _v is not None:
                out['support_resistance'] = _v
        if 'zhongshu_strength' in sr:
            _v = _mk(sr['zhongshu_strength'])
            if _v is not None:
                out['zhongshu_strength'] = _v
        if 'multi_level' in sr:
            _v = _mk(sr['multi_level'], is_json=True)
            if _v is not None:
                out['multi_level'] = _v
        if 'near_levels_filtered' in sr:
            _v = _mk(sr['near_levels_filtered'], is_json=True)
            if _v is not None:
                out['near_levels_filtered'] = _v
        if 'active_signal' in sr:
            _v = _mk(sr['active_signal'])
            if _v is not None:
                out['active_signal'] = _v
        if 'active_signal_label' in sr:
            _v = _mk(sr['active_signal_label'])
            if _v is not None:
                out['active_signal_label'] = _v
        if 'level_upper_limit' in sr:
            _v = _mk(sr['level_upper_limit'])
            if _v is not None:
                out['level_upper_limit'] = _v
        if 'momentum' in sr:
            _v = _mk(sr['momentum'], is_json=True)
            if _v is not None:
                out['momentum'] = _v
        if 'state_label' in sr:
            _v = _mk(sr['state_label'])
            if _v is not None:
                out['state_label'] = _v
        if 'risk_level' in sr:
            _v = _mk(sr['risk_level'])
            if _v is not None:
                out['risk_level'] = _v
        return out
    except Exception as e:
        logger.debug(f"extract_chanlun_deep_tags 失败 ({ts_code}): {e}")
        return {}


def extract_chip_deep_tags(ts_code: str) -> dict:
    """独立提取筹码深度字段（筹码分布组）——不依赖 phase_detector

    直接调用 ChipDistributionEstimator + ChipIndicators 计算筹码指标，
    产出 asr/cyqkl/concentration/profit_ratio/ssrp/chip_peak 等深度字段。

    重构依据：357号方案决策1（深度字段解耦），消除对 phase_detector._last_chip_indicators 的依赖。

    Returns:
        {chip_peak, asr, cyqkl, concentration, profit_ratio, ssrp, ...}
        计算失败时返回空 dict。
    """
    try:
        from app.data import DataManager
        dm = DataManager()
        df = dm.get_cached_daily_data(ts_code)
        if df is None or df.empty or len(df) < 30:
            return {}

        # 1. 估算筹码分布（508批次3：外部权威 ChipDistributionEstimator）
        estimator = ChipDistributionEstimator()
        chip_dist, min_p, max_p, step = estimator.estimate(df)
        if step <= 0:
            return {}

        # 2. 构建 chip_bins
        total = chip_dist.sum() or 1
        chip_bins = [
            {"price_bin": round(min_p + i * step, 2),
             "chip_ratio": float(chip_dist[i] / total)}
            for i in range(len(chip_dist))
        ]

        # 3. 计算筹码指标
        chip_inds = ChipIndicators()
        current_price = float(df["close"].values[-1])
        ind = chip_inds.calculate_all_indicators(
            chip_bins, current_price, kline_data=df, ts_code=ts_code) or {}

        # 4. 提取深度字段
        out = {}
        if 'main_peak' in ind and isinstance(ind['main_peak'], dict):
            pk_price = ind['main_peak'].get('price')
            if pk_price is not None:
                try:
                    out['chip_peak'] = str(round(float(pk_price), 2))
                except (TypeError, ValueError):
                    pass
        for key in ('asr', 'cyqkl', 'concentration', 'profit_ratio', 'ssrp',
                    'sandwich_zone', 'retail_vs_institutional',
                    'sentiment_crowding', 'sentiment_crowding_label', 'fake_institution',
                    'asr_status', 'concentration_status', 'cyqkl_status',
                    'peak_count', 'peak_type', 'avg_vol_100', 'vol_ratio'):
            if key in ind and ind[key] is not None:
                val = ind[key]
                out[key] = (json.dumps(val, ensure_ascii=False)
                            if isinstance(val, (dict, list)) else str(val))
        return out
    except Exception as e:
        logger.debug(f"extract_chip_deep_tags 失败 ({ts_code}): {e}")
        return {}


# 深度字段 → tag_group 映射（323号 §二 2.2/2.1 清单校准）
DEEP_TAG_GROUPS = {
    # structure 组（缠论结构）
    'support_resistance': 'structure', 'zhongshu_strength': 'structure',
    'multi_level': 'structure', 'near_levels_filtered': 'structure',
    'active_signal': 'structure', 'active_signal_label': 'structure',
    'level_upper_limit': 'structure', 'momentum': 'structure',
    'state_label': 'structure',
    # chip_deep 组（筹码分布）
    'chip_peak': 'chip_deep', 'asr': 'chip_deep', 'cyqkl': 'chip_deep',
    'concentration': 'chip_deep', 'profit_ratio': 'chip_deep', 'ssrp': 'chip_deep',
    'sandwich_zone': 'chip_deep',
    'retail_vs_institutional': 'chip_deep', 'sentiment_crowding': 'chip_deep',
    'sentiment_crowding_label': 'chip_deep', 'fake_institution': 'chip_deep',
    'asr_status': 'chip_deep', 'concentration_status': 'chip_deep', 'cyqkl_status': 'chip_deep',
    'peak_count': 'chip_deep', 'peak_type': 'chip_deep',
    'avg_vol_100': 'chip_deep', 'vol_ratio': 'chip_deep',
    # fund_risk 组（资金/风险）
    'net_lg_amount_5d': 'fund_risk', 'margin_cost_price': 'fund_risk',
    'risk_level': 'fund_risk',
}


def extract_fund_risk_tags(ts_code: str) -> dict:
    """提取资金/风险深度字段（fund_risk 组）

    2026-08-10 325档案修复：弃用 P2 筹码信号路径（覆盖仅 0.77% 致组近空），
    改从 ECM 全市场表直接提取：
    - net_lg_amount_5d：moneyflow_cache 近5日 net_lg_amount 求和（覆盖 5558 只）
    - margin_cost_price：margin_cache rzmje(融资买入额) 加权成本价（覆盖 4414 只）
    Returns: {net_lg_amount_5d, margin_cost_price}，缺失返回空 dict。
    """
    try:
        dm = DataManager()
        out = {}
        # net_lg_amount_5d：moneyflow_cache 近5日大单净额求和
        try:
            mf = dm.cache.get_cached_moneyflow(ts_code)
            if mf is not None and not mf.empty and 'net_lg_amount' in mf.columns:
                net5 = mf['net_lg_amount'].dropna().tail(5).sum()
                if abs(net5) > 0:
                    out['net_lg_amount_5d'] = str(round(float(net5), 2))
        except Exception:
            pass
        # margin_cost_price：margin_cache rzmje 加权均价（近60日融资买入日）
        try:
            margin_df = dm.get_cached_margin(ts_code)
            if margin_df is not None and not margin_df.empty and 'rzmje' in margin_df.columns:
                _df = margin_df.tail(60)
                _buy = _df[_df['rzmje'].fillna(0) > 0]
                if len(_buy) >= 3:
                    # margin 表无 K 线列——用 daily_cache 收盘价近似当日均价
                    _k = dm.get_cached_daily_data(ts_code)
                    _close_map = {}
                    if _k is not None and not _k.empty and 'trade_date' in _k.columns:
                        _close_map = dict(zip(_k['trade_date'].astype(str), _k['close']))
                    _weights = []
                    _prices = []
                    for _i, _row in _buy.iterrows():
                        _w = float(_row.get('rzmje') or 0)
                        if _w <= 0:
                            continue
                        _p = _close_map.get(str(_row.get('trade_date')))
                        if _p is None:
                            continue
                        _weights.append(_w)
                        _prices.append(float(_p))
                    if len(_weights) >= 3 and sum(_weights) > 0:
                        out['margin_cost_price'] = str(round(
                            sum(w * p for w, p in zip(_weights, _prices)) / sum(_weights), 2))
        except Exception:
            pass
        return out
    except Exception as e:
        logger.debug(f"extract_fund_risk_tags 失败 ({ts_code}): {e}")
        return {}

# ═══════════════════════════════════════════════════════════
# 第4维 引擎
# ═══════════════════════════════════════════════════════════

def _assess_phase(tags, dims):
    mfp = str(tags.get('main_force_phase', ''))
    pm = {'building': ('建仓期', '低位吸筹'), 'washing': ('洗盘期', '清洗浮筹'),
          'lifting': ('拉升期', '快速上涨'), 'distributing': ('出货期', '高位派发'), 'support': ('护盘期', '支撑维护')}
    if mfp in pm:
        cn, desc = pm[mfp]
        return {'phase': mfp, 'phase_cn': cn, 'detail': desc}
    return {'phase': 'unknown', 'phase_cn': '未知', 'detail': '主力阶段数据缺失'}

def _assess_fund_flow(tags):
    ff = str(tags.get('fund_flow', ''))
    if ff == '5d_inflow': return {'level': 'strong', 'level_cn': '强流入', 'direction': 'inflow', 'detail': '大单5日净流入'}
    elif ff == '5d_outflow': return {'level': 'strong_out', 'level_cn': '强流出', 'direction': 'outflow', 'detail': '大单5日净流出'}
    return {'level': 'none', 'level_cn': '中性', 'direction': 'neutral', 'detail': '无明确资金流向'}

def _assess_cost_structure(tags):
    """成本分布结构（Wiki筹码分布知识库验证）

    增强：ASR（活跃筹码比率）+ CYQKL（筹码穿透力）+ profit_ratio 综合评估
    """
    parts = []
    c = str(tags.get('chip_concentration', ''))
    if c: parts.append(f"筹码{chip_concentration_cn(c)}")

    # ASR（活跃筹码比率）：Wiki定义 - 衡量筹码活跃程度
    asr = tags.get('asr')
    asr_val = None
    if asr is not None:
        try:
            asr_val = float(asr)
            parts.append(f"ASR={asr_val:.0f}")
        except: pass

    # CYQKL（筹码穿透力指标）：Wiki定义 - 衡量价格穿透筹码的能力
    cyqkl = tags.get('cyqkl')
    if cyqkl is not None:
        try:
            cyqkl_val = float(cyqkl)
            parts.append(f"CYQKL={cyqkl_val:.1f}")
        except: pass

    pr = tags.get('profit_ratio')
    if pr is not None:
        try: parts.append(f"获利盘{float(pr):.0%}")
        except: pass

    # 464-11：删除 quality 死计算（ASR>80 活跃/<30 沉寂 分档）——
    # 实证 2026-09-18 全市场 5550 只：>80 仅 2 只(0%)、<30 占 91%，区分度极低；
    # evaluate 零消费（死计算），ASR 数值已在 detail（如 ASR=29）。
    # 378/383 cost_quality 契约键为早期设计，从未透传；dim8 叙事直读 ASR 数值。
    return {'detail': '，'.join(parts) if parts else '筹码数据不足',
            'concentration': c}

def _assess_signal(tags):
    bsp = str(tags.get('buy_sell_point', ''))
    # 464-16：值域含 third_sell（chanlun_strategy get_chanlun_tags 卖点优先级 second_sell>third_sell>first_sell），
    # 此前缺该键 → 三卖信号被吞为"无明确筹码信号"
    sm = {'first_buy': '一买信号', 'second_buy': '二买信号', 'third_buy': '三买信号',
          'first_sell': '一卖信号', 'second_sell': '二卖信号', 'third_sell': '三卖信号'}
    # 468-④：优先读 tags['active_signal']（462-2 缠论买卖点详情 JSON {type,date,price,confidence,reason}，
    # 同源明细不重算）——补 price/confidence/reason 增强；无 active_signal（数据退化回退枚举）时落单词枚举。
    asig = tags.get('active_signal')
    if asig:
        detail_dict = None
        try:
            if isinstance(asig, str):
                _v = asig.strip()
                try:
                    detail_dict = json.loads(_v)
                except Exception:
                    import ast
                    try:
                        detail_dict = ast.literal_eval(_v)
                    except Exception:
                        detail_dict = None
            elif isinstance(asig, dict):
                detail_dict = asig
        except Exception:
            detail_dict = None
        if isinstance(detail_dict, dict):
            _type = str(detail_dict.get('type', bsp))
            _price = detail_dict.get('price')
            _conf = detail_dict.get('confidence')
            _reason = str(detail_dict.get('reason', '') or '')
            if _type in sm:
                parts = [sm[_type]]
                _price = float(_price) if isinstance(_price, (int, float)) or (isinstance(_price, str) and _price.strip().replace('.', '', 1).isdigit()) else _price
                if isinstance(_price, float):
                    parts.append(f"@{_price:g}元")
                if isinstance(_conf, (int, float)):
                    parts.append(f"置信{_conf:.2f}")
                elif isinstance(_conf, str) and _conf.strip().replace('.', '', 1).isdigit():
                    parts.append(f"置信{float(_conf):.2f}")
                if _reason:
                    parts.append(f"({_reason})")
                return {'detail': ''.join(parts), 'signal': _type,
                        'price': _price if isinstance(_price, (int, float)) else None,
                        'confidence': float(_conf) if isinstance(_conf, (int, float)) or (isinstance(_conf, str) and _conf.strip().replace('.', '', 1).isdigit()) else None,
                        'reason': _reason}
    if bsp in sm: return {'detail': sm[bsp], 'signal': bsp}
    return {'detail': '无明确筹码信号', 'signal': 'none'}


def _assess_fund_price_divergence(fund_flow, price_direction):
    """资金×价格方向背离判定（445 §6.1 dim4「资金×价格背离缺失」补产出）

    wiki《筹码分布分析-主力视角》权威：
      - 连续买超+股价上涨 / 连续卖超+股价下跌 → 同向，无背离。
      - 连续卖超（资金流出）+ 股价上涨 → **拉抬出货/散户接盘**（危险信号，回避）。
      - 连续买超（资金流入）+ 股价下跌 → **底部吸筹/逆势建仓**（看多信号）。

    Args:
        fund_flow: _assess_fund_flow 结果（direction: inflow/outflow/neutral）
        price_direction: 价格方向（'up'/'down'/'mixed'/'no_trend'，取自
            PhaseDetectionEngine trend_alignment，缺失时由调用方兜底）

    Returns:
        {status, label, direction, risk}
          status: 'aligned'（同向）/ 'divergence'（背离）/ 'none'（数据不足）
          label: 中文结论（供 plain / 前端现状描述）
          direction: 'bearish'（背离偏空-出货）/ 'bullish'（背离偏多-吸筹）/ 'neutral'
          risk: '危险' 供 audit 标记
    """
    fd = str(fund_flow.get('direction', 'neutral'))
    pd = str(price_direction or '')
    # 数据不足：资金方向中性 或 价格方向未知 → 无法交叉，不产背离结论
    if fd == 'neutral' or pd not in ('up', 'down'):
        return {'status': 'none', 'label': '资金与价格方向数据不足',
                'direction': 'neutral', 'risk': '无'}
    # 同向
    if (fd == 'inflow' and pd == 'up') or (fd == 'outflow' and pd == 'down'):
        return {'status': 'aligned', 'label': '资金与价格同向（一致性确认）',
                'direction': 'neutral', 'risk': '无'}
    # 背离
    if fd == 'outflow' and pd == 'up':
        return {'status': 'divergence',
                'label': '资金流出+股价上涨（拉抬出货，散户接盘危险信号）',
                'direction': 'bearish', 'risk': '危险'}
    if fd == 'inflow' and pd == 'down':
        return {'status': 'divergence',
                'label': '资金流入+股价下跌（底部吸筹/逆势建仓）',
                'direction': 'bullish', 'risk': '提示'}
    # 理论不可达（inflow+up / outflow+down 已在上方返回），防御性兜底
    return {'status': 'none', 'label': '资金与价格方向数据不足',
            'direction': 'neutral', 'risk': '无'}

def _assess_retail_institution(phase, fund_flow):
    """散户机构博弈话术。469-1 同源化：由 evaluate 传「当前生效的」phase/fund_flow
    （引擎覆盖后取覆盖值、否则取 tags 值），不再自读 tags——消除与 phase 的潜在不一致。"""
    mfp = str(phase or '')
    ff = str(fund_flow or '')
    if mfp == 'building' and ff == '5d_inflow': return {'detail': '主力建仓+资金流入（机构买入）'}
    elif mfp == 'distributing': return {'detail': '主力出货（抛压风险）'}
    return {'detail': '散户与机构博弈中性'}

def _assess_margin(tags, margin_df=None):
    mc = tags.get('margin_change_5d')
    # 442号缺陷②：margin_change_5d 无产出点——改读 data_context.margin_df 计算5日融资余额变化
    if mc is None and margin_df is not None and hasattr(margin_df, 'empty') and not margin_df.empty:
        try:
            if 'rzye' in margin_df.columns and 'trade_date' in margin_df.columns:
                mdf = margin_df[['trade_date', 'rzye']].dropna(subset=['rzye']).copy()
                mdf = mdf.sort_values('trade_date')
                if len(mdf) >= 2:
                    latest = mdf.iloc[-1]['rzye']
                    base = mdf.iloc[-min(6, len(mdf))]['rzye']  # 5个交易日前（不足6行取最早）
                    if base:
                        mc = (latest / base - 1) * 100
        except Exception:
            mc = None
    if mc is not None:
        try:
            mc = float(mc)
            if mc > 10: return {'detail': f'融资余额5日增加{mc:.0f}%（散户杠杆在上升）'}
            elif mc < -10: return {'detail': f'融资余额5日减少{abs(mc):.0f}%（散户在去杠杆）'}
            else: return {'detail': f'融资余额5日变化{mc:+.0f}%（正常范围）'}
        except: pass
    return {'detail': '融资数据不足'}


class Dim4ChipFundEngine(DataAwareMixin):
    """第4维 资金筹码引擎 — 阶段判定 + 6信号 + 拥挤度 + 标签提取"""

    def __init__(self):
        self._dm = None

    def evaluate(self, dims, tags, signals=None, lifecycle=None, data_context=None):
        """411号Phase 6：优先使用data_context预加载数据，回退独立查询。"""
        phase_info = _assess_phase(tags, dims)
        fund_flow_info = _assess_fund_flow(tags)
        cost_structure = _assess_cost_structure(tags)
        signal_info = _assess_signal(tags)
        margin_info = _assess_margin(tags, margin_df=data_context.get('margin_df') if data_context else None)
        # 469-1 同源：retail_institution 用「当前生效的」phase/fund_flow 原枚举
        # （随 PhaseDetectionEngine 覆盖而更新，否则与 phase 潜在不一致）。初始取 tags 兜底值。
        _retail_phase = str(tags.get('main_force_phase', ''))
        _retail_flow = str(tags.get('fund_flow', ''))

        # PhaseDetectionEngine 真实阶段分析（如果df可用）
        ts_code = tags.get('ts_code', '')
        phase_engine_result = None
        df = None
        try:
            # 411号Phase 6：优先使用data_context
            if data_context and 'daily_df' in data_context:
                df = data_context['daily_df']
            else:
                ecm = self._get_dm().cache
                if ts_code:
                    df = ecm.get_cached_daily(ts_code)
            if ts_code and df is not None and not df.empty and len(df) >= 30:
                # 412号方案C1 v3.0：从data_context提取chip_fund_ext和moneyflow_df
                chip_fund_ext = data_context.get('chip_fund_ext') if data_context else None
                moneyflow_df_val = data_context.get('moneyflow_df') if data_context else None
                indicator_ma_df_val = data_context.get('indicator_ma_df') if data_context else None
                indicator_other_df_val = data_context.get('indicator_other_df') if data_context else None
                # 443号R2：补传 cost_ext（main_force_cost/margin_cost_price），此前仅批量 identify_phase 路径消费
                cost_ext_val = data_context.get('cost_ext') if data_context else None
                pde = PhaseDetectionEngine(data_manager=self._get_dm())
                phase_engine_result = pde.compute_tags(
                    ts_code, df, extra_tags=tags,
                    chip_fund_ext=chip_fund_ext,
                    moneyflow_df=moneyflow_df_val,
                    indicator_ma_df=indicator_ma_df_val,
                    indicator_other_df=indicator_other_df_val,
                    cost_ext=cost_ext_val)
                if phase_engine_result and phase_engine_result.get('main_force_phase') != 'unknown':
                    phase_info = {
                        'phase': phase_engine_result['main_force_phase'],
                        'phase_cn': PHASE_MAP.get(phase_engine_result['main_force_phase'], {}).get('name', phase_engine_result['main_force_phase']),
                        'detail': f"PhaseDetector分析（置信度{phase_engine_result.get('phase_confidence', 0):.2f}）",
                        # 464-13：透传阶段置信度供 audit 条件 1 门槛（tags 兜底路径无此键 → 仅看 phase）
                        'confidence': phase_engine_result.get('phase_confidence'),
                    }
                    _retail_phase = str(phase_engine_result['main_force_phase'])
                if phase_engine_result and phase_engine_result.get('fund_flow') != 'none':
                    ff = phase_engine_result['fund_flow']
                    _retail_flow = str(ff)
                    if ff == 'mixed':
                        fund_flow_info = {
                            'level': 'none', 'level_cn': '中性', 'direction': 'neutral',
                            'detail': f"PhaseDetector资金流向={ff}",
                        }
                    else:
                        fund_flow_info = {
                            'level': 'strong' if 'inflow' in ff else 'strong_out',
                            'level_cn': '强流入' if 'inflow' in ff else '强流出',
                            'direction': 'inflow' if 'inflow' in ff else 'outflow',
                            'detail': f"PhaseDetector资金流向={ff}",
                        }

        except Exception as e:
            # 464-7：静默降级改显式告警——阶段分析失败时输出落 tags 兜底，需在日志可见
            logger.warning(f"PhaseDetectionEngine调用异常，阶段/资金流向降级为tags兜底: {e}")

        # 469-1：retail_institution 用覆盖后（或 tags 兜底）的 phase/fund_flow——与 phase 同源
        retail_inst = _assess_retail_institution(_retail_phase, _retail_flow)

        # 拥挤度（真实计算）
        crowding = {'level': 'unknown', 'detail': '拥挤度数据不足', 'score': 0.5}
        try:
            if ts_code:
                if df is None:
                    ecm = self._get_dm().cache
                    df = ecm.get_cached_daily(ts_code)
                if df is not None and not df.empty:
                    cf = CrowdingFactor()
                    # 464-6：daily_basic_df 一并传入——calc_margin_ratio 需 circ_mv（流通市值，
                    # 单位万元；margin_cache 无此列，此前恒 None → 融资分项恒死）
                    _mc = {'margin_df': data_context.get('margin_df'),
                           'daily_basic_df': data_context.get('daily_basic_df')} if data_context else {}
                    # 464-3：换手分项接线——从 data_context.daily_basic_df 提取 turnover_rate 序列传 turnover_data。
                    # 此前恒 NORMAL_TURNOVER：daily_df（前复权 OHLCV）无 turnover 列且 evaluate 未传
                    # turnover_data，拥挤度实际仅融资+波动两维；daily_basic_cache.turnover_rate 为真实生产列
                    # （461-6 已确认），此处接通使换手分项真实参与 2/3 拥挤判定。
                    if data_context:
                        _db = data_context.get('daily_basic_df')
                        if _db is not None and hasattr(_db, 'columns') and 'turnover_rate' in _db.columns:
                            _tr = _db['turnover_rate'].dropna()
                            if not _tr.empty:
                                _mc['turnover_data'] = _tr
                    cr = cf.evaluate(ts_code, df, market_context=_mc)
                    crowding = {'level': cr.get('crowding_level', 'MODERATE_CROWDING'), 'detail': cr.get('risk_advice', ''),
                                 'score': cr.get('crowding_score', 0.5),
                                 # 468-③：透传 CrowdingFactor.details（三信号明细：margin_ratio/turnover_state/volatility_state/valid_signals）
                                 'details': cr.get('details', {}) if isinstance(cr, dict) else {}}
        except Exception as e:
            # 464-7：静默降级改显式告警——拥挤度失败时输出落 unknown 兜底
            logger.warning(f"CrowdingFactor计算异常，拥挤度降级为unknown: {e}")

        # ── 445 §6.1 dim4「资金×价格背离缺失」补产出：资金方向 vs 价格方向交叉判定 ──
        # 价格方向优先取 PhaseDetectionEngine trend_alignment（已算，'*_aligned'/'mixed'/'no_trend'），
        # 归一化为 up/down/mixed/no_trend；无引擎结果时用 df 斜率兜底
        price_direction = 'no_trend'
        if phase_engine_result:
            _ta = str(phase_engine_result.get('trend_alignment', 'no_trend') or 'no_trend')
            price_direction = (_ta.replace('_aligned', '') if _ta.endswith('_aligned') else _ta)
        elif df is not None and not df.empty and len(df) >= 5:
            try:
                _c = df['close'].astype(float).values
                _s5 = (_c[-1] / _c[-6] - 1) if len(_c) >= 6 else 0.0
                # 469-2：兜底路径加中性态——|变化|≤1%（平盘/微涨/微跌）判 no_trend，
                # 与 PhaseEngine 的 up/down/mixed/no_trend 对称，避免一律判 down
                price_direction = 'up' if _s5 > 0.01 else ('down' if _s5 < -0.01 else 'no_trend')
            except Exception:
                price_direction = 'no_trend'
        fund_price_div = _assess_fund_price_divergence(fund_flow_info, price_direction)

        # ── 468-①：透传 phase_vote_ratio（各维投票明细，compute_tags 已算且仅 phase_engine_result 携带）──
        # 取各维强度>0 的主导阶段 + 投票支持者数，生成「维度:阶段(强度)」精简话术供 dim8 叙事。
        phase_vote_detail = ''
        if phase_engine_result:
            try:
                _vr = phase_engine_result.get('phase_vote_ratio')
                if _vr:
                    if isinstance(_vr, str):
                        _vr = json.loads(_vr)
                    if isinstance(_vr, dict):
                        _phase_cn_sh = {'building': '建仓', 'washing': '洗盘', 'lifting': '拉升', 'distributing': '出货'}
                        _votes = []
                        for _name, _vec in _vr.items():
                            if str(_name).startswith('_'):
                                continue
                            if isinstance(_vec, dict):
                                _top_p = max(_vec, key=_vec.get) if _vec else None
                                if _top_p and _vec.get(_top_p, 0) > 0:
                                    _votes.append(f"{_name}={_phase_cn_sh.get(_top_p, _top_p)}({_vec[_top_p]:.2f})")
                        _supp = _vr.get('_supporters') or {}
                        # 486号：_supporters 为 {主导阶段: 支持维度数} 单键 dict——取**值**（支持主导阶段的
                        # 维度数），非 len(dict) 键数（恒 1）。对齐 phase_detector:351 / 本引擎 :797 生产口径。
                        _supp_cnt = next(iter(_supp.values()), 0) if isinstance(_supp, dict) else 0
                        _supp_txt = f"，{int(_supp_cnt)}维支持" if _supp_cnt else ''
                        if _votes:
                            phase_vote_detail = '投票:' + '、'.join(_votes) + _supp_txt
            except Exception:
                phase_vote_detail = ''

        # ── 468-②：透传 net_lg_5d/strength（5日大单净额数值，万元÷1e4归一化亿，464-15口径）──
        # net_lg_5d 来自 tags['net_lg_5d']（fund_5d_ext 预计算）；fund_flow 文本补净额数值。
        _net_txt = ''
        try:
            _nl5 = tags.get('net_lg_5d')
            if _nl5 is not None:
                _nl5 = float(_nl5)
                _yi = _nl5 / 1e4  # 万元 → 亿
                _dir_cn5 = '净流入' if _yi > 0 else '净流出'
                _net_txt = f"，大单5日{_dir_cn5}{abs(_yi):.1f}亿"
        except Exception:
            _net_txt = ''

        # ── 490号（A 类补产出）：390 L1/L2 筹码契约键的取值准备 ──
        #  pde_* 取自 PhaseDetectionEngine 真实产出（compute_tags）：phase_conflict/phase_vote_ratio/
        #  price_position；vote_ratio 为嵌套 {维度: 向量}，_supporters 为 {主导阶段: 支持维度数}——
        #  390 契约语义为「票差」，故优先透传 _supporters（扁平 {阶段: 票数}），缺则透传原始 dict。
        _pde = phase_engine_result or {}
        _pde_vote = None
        _vr_raw = _pde.get('phase_vote_ratio')
        if _vr_raw:
            try:
                _vr = json.loads(_vr_raw) if isinstance(_vr_raw, str) else _vr_raw
                if isinstance(_vr, dict):
                    _pde_vote = _vr.get('_supporters') or _vr
            except Exception:
                _pde_vote = None
        _cost_profit_ratio = None
        try:
            _pr = tags.get('profit_ratio')
            if _pr is not None:
                _cost_profit_ratio = float(_pr)
        except (TypeError, ValueError):
            _cost_profit_ratio = None

        status_description = {
            'phase': f"{phase_info['phase_cn']}（{phase_info['detail']}"
                     + (f"，{phase_vote_detail}" if phase_vote_detail else '') + "）",
            'fund_flow': f"{fund_flow_info['level_cn']}（{fund_flow_info['detail']}{_net_txt}）",
            'cost_structure': cost_structure['detail'], 'signal': signal_info['detail'],
            'retail_institution': retail_inst['detail'], 'margin': margin_info['detail'],
            'crowding': f"拥挤度={crowding['level']}（{crowding['detail']}）",
            # 445 §6.1：资金×价格背离结论
            'fund_price_divergence': fund_price_div['label'],
            'fund_price_divergence_status': fund_price_div['status'],
            'fund_price_divergence_risk': fund_price_div['risk'],
            # ── 490号（A 类补产出）：390 L1/L2 筹码契约键（引擎已算未透传，此前 JUD 取默认）──
            #  phase_confidence：PhaseDetector 阶段置信度（tags 兜底路径无 → None）
            #  pde_conflict / pde_vote_ratio / pde_price_position：PDE 八维共识的真实产出
            #  crowding_level：CrowdingFactor 三信号分档；cost_concentration：筹码集中度枚举；
            #  cost_profit_ratio：获利盘比例（tags.profit_ratio，与 conflict C4++/C8 同源）
            'phase_confidence': phase_info.get('confidence'),
            'pde_conflict': _pde.get('phase_conflict'),
            'pde_vote_ratio': _pde_vote,
            'pde_price_position': _pde.get('price_position'),
            'crowding_level': crowding.get('level'),
            'cost_concentration': cost_structure.get('concentration'),
            'cost_profit_ratio': _cost_profit_ratio,
        }
        # 拥挤度三信号明细并入 crowding 文本（468-③；details 缺失则保持原样）
        try:
            _cd = crowding.get('details') or {}
            if _cd:
                _bits = []
                _mr = _cd.get('margin_ratio')
                if _mr is not None:
                    _bits.append(f"融资占比{_mr:.2%}")
                _ts = _cd.get('turnover_state')
                if _ts:
                    _bits.append('换手' + ('高' if _ts == 'HIGH_TURNOVER' else ('低' if _ts == 'LOW_TURNOVER' else '正常')))
                _vs = _cd.get('volatility_state')
                if _vs:
                    _bits.append('波动' + ('压缩' if _vs == 'HIGH_CROWDING' else ('扩张' if _vs == 'LOW_CROWDING' else '正常')))
                _vsig = _cd.get('valid_signals')
                if _bits:
                    _sig_txt = f"，{_vsig}/3信号可用" if isinstance(_vsig, (int, float)) else ''
                    status_description['crowding'] = f"{status_description['crowding']}（{'、'.join(_bits)}{_sig_txt}）"
        except Exception:
            pass
        judgment = {
            'phase': phase_info['phase'], 'direction': fund_flow_info['direction'],
            'overall_direction': 1 if phase_info['phase'] in ('building', 'lifting') else (-1 if phase_info['phase'] == 'distributing' else 0),
            'continuous_value': round(1.0 - crowding.get('score', 0.5), 4),
        }
        # 464-13：audit「主力阶段」置信门槛 ≥0.3（随 464-17 核查结论拍板）——
        # PhaseEngine 重算路径有 phase_confidence 时应用门槛（低置信不满足 audit）；
        # tags 兜底路径无置信键 → 仅看 phase（保持现状不额外拦截）。
        _phase_conf = phase_info.get('confidence')
        conditions = [
            {'name': '主力阶段', 'satisfied': phase_info['phase'] in ('building', 'lifting', 'distributing')
             and (_phase_conf is None or _phase_conf >= 0.3),
             'actual': phase_info['phase_cn'], 'threshold': '有明确阶段判定且置信≥0.3'},
            # 464-14：判定集与实现产出对齐——实现只产 strong(强流入)/strong_out(强流出)/none；
            # 原集含 very_strong/medium/weak 死枚举（从不产生）且漏 strong_out →
            # 资金强流出时 audit 恒 False（与强流入不对称，失真）。
            {'name': '资金流向', 'satisfied': fund_flow_info['level'] in ('strong', 'strong_out'),
             'actual': fund_flow_info['level_cn'], 'threshold': '有明确流向'},
            {'name': '筹码集中', 'satisfied': cost_structure.get('concentration') == 'concentrating', 'actual': cost_structure.get('concentration', '未知') or '未知', 'threshold': '集中度=concentrating'},
            {'name': '拥挤度合理', 'satisfied': crowding['level'] not in ('HIGH_CROWDING', 'unknown'), 'actual': crowding['level'], 'threshold': '非高拥挤'},
            {'name': '资金×价格无危险背离', 'satisfied': fund_price_div['risk'] not in ('危险',), 'actual': fund_price_div['label'], 'threshold': '无拉抬出货/顶背离'},
        ]
        sc = sum(1 for c in conditions if c['satisfied'])
        audit = {'conditions': conditions, 'satisfied_count': sc, 'total_count': len(conditions), 'confidence': sc / len(conditions) if conditions else 0}
        return {'status_description': status_description, 'judgment': judgment, 'audit': audit}

    def get_data_dependencies(self):
        return ['tags (pre_feat_cache)', 'dims (StatusEngine)', 'daily_cache (market_cache.db)', 'moneyflow_cache (market_cache.db)']
