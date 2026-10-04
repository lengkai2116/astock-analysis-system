"""第4维 资金筹码引擎 — 独立完整文件

369号方案 P1 维度引擎整合：物理合并以下文件为独立完整文件（**508号批次1起逐步收敛**，
已收敛项改 import 外部权威，见 `002-方案存档/508-dim4双副本收敛（物理合入清理）.md`）：
  - phase_detector.py — PhaseDetectionEngine 7维度加权共识（508 批次5 已删内嵌，外部权威）
  - chip_strategy_impl.py — TradingPhaseDetector 五阶段（508 批次4 已删内嵌，外部权威）
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
from app.engine.chip_strategy_impl import TradingPhaseDetector
from app.engine.framework.volume_price_strategy import Stage, StageDetector, ValuationZones
from app.opportunity_atlas.dimensions.enum_cn_map import chip_concentration_cn

# 508批次5：PhaseDetectionEngine 演进版（8 参 data_context）迁入 phase_detector.py 为权威
from app.opportunity_atlas.phase_detector import PhaseDetectionEngine

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

# === phase_detector.py (508批次5 收敛：外部 app/opportunity_atlas/phase_detector.py 为权威) ===
# 演进版（8 参 data_context）已迁入外部文件并覆盖 3 参旧版；dim4 内嵌删除。
# 差异审计见 002-方案存档/508-dim4双副本收敛（物理合入清理）.md §〇·五。
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
