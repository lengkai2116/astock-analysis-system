"""status_engine.py — 现状判定引擎·生产环节核心（332总纲 §5，338号 S2.1）

落地分档：334（L1 维度判定+信号注册表+生命周期）、335（L0 风险分级）、
         336（L2 聚合：维度共识+conflict_evidence）、337（成品仓输出 status_snapshot 行）

流水线（357号方案v2.1更新）：
  原料仓（pre_feat_cache + P2 信号 strategy_signal_detail）
  → L1 十二维判定（每维 {state, light, confidence, evidence, conclusion, plain}）
  → L0 风险分级（L0a 硬否决 / L0b 软约束 / L0c 持有期）
  → L2 聚合（维度共识 + conflict_evidence + opportunity_state 仲裁）
  → 成品仓输出（dim_states/status_bar/consensus/conflict/advice_params）

调用层合规：仅读存储层（DataManager 网关），不触碰数据源（292 红线）。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from app.services.status_config import get_status_engine_config, get_signal_registry

logger = logging.getLogger(__name__)

# ── 维度方向映射（336号 §2.2：L1 十维状态 → +1/0/-1 计票） ──
_DIM_DIRECTION: dict[str, dict[str, int]] = {
    'valuation': {'极度低估': 2, '低估': 1, '合理': 0, '高估': -1, '极度高估': -2},
    'structure': {'上升': 1, '盘整': 0, '下降': -1},
    'vp': {'强健康': 2, '健康': 1, '中性': 0, '背离': -1, '严重背离': -2},
    'position': {'站上防守位': 1, '中位': 0, '跌破': -1},
    'chip_fund': {'流入': 1, '中性': 0, '流出': -1},
    'emotion': {'复苏': 1, '正常': 0, '退潮·高潮': -1},
    'finance': {'健康': 1, '关注': 0, '风险': -1},
    'event': {'正向': 1, '中性': 0, '负面': -1},
    'time': {'初期': 1, '中期': 0, '已延伸': -1, '回撤': -1},
    'risk': {'低': 1, '中': 0, '高': -1},
    'factor': {'看多': 1, '中性': 0, '看空': -1},
}
_DIM_LIGHT: dict[str, dict[str, str]] = {
    dim: {s: ('green' if v > 0 else ('yellow' if v == 0 else 'red'))
          for s, v in mapping.items()}
    for dim, mapping in _DIM_DIRECTION.items()
}
_DIM_ORDER = ['valuation', 'structure', 'vp', 'position', 'chip_fund', 'emotion',
              'finance', 'event', 'time', 'risk', 'factor']


class StatusEngine:
    """现状判定生产环节引擎（单只股票 evaluate，全市场由日终批量驱动）"""

    def __init__(self, dm=None):
        if dm is None:
            from app.data import DataManager
            dm = DataManager()
        self.dm = dm
        self.cfg = get_status_engine_config()
        self.registry = get_signal_registry().get('signals', {})

    # ══════════════════════════════════════════════════════════
    # 主入口
    # ══════════════════════════════════════════════════════════

    def evaluate(self, ts_code: str) -> Optional[dict]:
        """生产环节主流程：原料 → L1 → L0 → L2 → 成品仓行

        366号步骤3：重构为调用维度引擎，通过兼容层保持下游兼容。

        Returns: status_snapshot 行 dict（或 None 数据缺失）
        """
        tags = self._load_tags(ts_code)
        signals = self._load_signals(ts_code)
        if not tags and not signals:
            return None

        lifecycle = self._signal_lifecycle(ts_code, tags, signals)

        # 366号步骤3：用维度引擎替代_build_dimensions()
        dim_engine_results = self._build_dim_engine_results(tags, signals, {}, lifecycle)

        # dim8 状态总结：读取 dim1-dim7 输出，组装综合报告
        try:
            from app.opportunity_atlas.dimensions.dim8_summary_engine import Dim8SummaryEngine
            dim8 = Dim8SummaryEngine()
            dim_engine_results['summary'] = dim8.evaluate(dims={}, tags=tags, lifecycle={'dim_results': dim_engine_results})
        except Exception as e:
            logger.warning(f"dim8 状态总结失败: {e}")
            dim_engine_results['summary'] = None

        # 兼容层：将维度引擎输出转为旧dims格式
        dims = self._convert_to_dims_format(dim_engine_results, tags)

        l0 = self._apply_l0(ts_code, tags, dims, lifecycle)
        l2 = self._aggregate(tags, dims, l0, lifecycle)
        hits = self._detect_registered_signals(tags, signals)

        return self._assemble(ts_code, dims, lifecycle, l0, l2, hits, dim_engine_results)

    # ══════════════════════════════════════════════════════════
    # 原料加载（存储层只读）
    # ══════════════════════════════════════════════════════════

    def _load_tags(self, ts_code: str) -> dict:
        """加载原料标签（357号方案：读pre_feat_cache）

        pre_feat_cache 是嵌套JSON（11组特征），需扁平化为下游期望的flat dict格式。
        P4已废弃，不再回退opportunity_tags_cache。
        """
        try:
            pre_feat = self.dm.cache.get_pre_feat(ts_code)
            if pre_feat:
                return self._flatten_pre_feat(pre_feat)
        except Exception as e:
            logger.debug("pre_feat 读取失败 %s: %s", ts_code, e)
        return {}

    @staticmethod
    def _flatten_pre_feat(pre_feat: dict) -> dict:
        """将 pre_feat_cache 嵌套JSON扁平化为下游期望的flat dict格式

        pre_feat 结构: {valuation: {...}, sentiment: {...}, ..., depth: {...}}
        输出: {valuation_level: 'fair', sentiment_phase: 'cautious', ...}
        """
        flat = {}
        for group_name, group_data in pre_feat.items():
            if not isinstance(group_data, dict):
                continue
            for key, value in group_data.items():
                if value is not None:
                    flat[key] = value
        return flat

    def _load_signals(self, ts_code: str) -> dict:
        try:
            cached = self.dm.cache.get_latest_signal_detail(ts_code)
            return (cached or {}).get('signals', {}) or {}
        except Exception as e:
            logger.debug("signals 读取失败 %s: %s", ts_code, e)
            return {}

    # ══════════════════════════════════════════════════════════
    # L1 维度判定（334号 §2：10 维 → {state, light, confidence, evidence}）
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _derive_vp_state(vp_signal: dict, tags: dict) -> tuple[str, list, float]:
        """量价维状态推导（342号核查修复 2026-08-16）

        修复"trend.direction=='down' → 背离"的概念误用（趋势向下≠背离）。
        数据源优先级：
          ① P2 真实背离检测（volume_price_detail.量价关系.divergence_type + macd_confirmed）
          ② P2 阶段×量价结构交叉矩阵（trend.stage × volume.structure）
          ③ 回退 volume_price_fit 标签
        """
        sr = vp_signal.get('status_recognition') or {}
        evidence = [str(e) for e in (vp_signal.get('evidence') or [])[:3]]
        conf = vp_signal.get('confidence', 0.5)

        # ① 真实背离检测（量价关系 divergence: top/bottom + MACD 确认）
        # volume_price_detail 位于 raw_detail（unified_core 转换后）；旧版在信号顶层
        vpd = vp_signal.get('volume_price_detail') or (vp_signal.get('raw_detail') or {}).get('volume_price_detail') or {}
        rel = (vpd.get('量价关系') or {}) if isinstance(vpd, dict) else {}
        div_type = str(rel.get('divergence', 'none'))
        macd_ok = bool(rel.get('divergence_macd_confirmed'))
        if div_type in ('top', 'bottom') and div_type != '无':
            # 顶背离=看空（量价不配合）；底背离=看多反转信号（知识库《50种量价形态》）
            if div_type == 'top':
                return ('背离', [f'顶背离（MACD未创新高）' if macd_ok else f'顶背离（量缩，未MACD确认）'], conf)
            # bottom 底背离：知识库=看多反转，非"背离/看空"
            return ('健康', [f'底背离（下跌衰竭，反转信号）'], conf)

        # ② 阶段×量价结构交叉矩阵（trend.stage × volume.structure）
        stage = str((sr.get('trend') or {}).get('stage', ''))
        vol_struct = str((sr.get('volume') or {}).get('structure', ''))
        vp_num = next((p for p in ('VP-1', 'VP-2', 'VP-3', 'VP-4', 'VP-5', 'VP-6', 'VP-7', 'VP-8', 'VP-9')
                       if p in vol_struct), '')
        if stage and vp_num:
            # 知识库量价阶段矩阵（volume_price_strategy.CROSS_MATRIX 语义精简版）
            if stage == 'UPTREND_TOPPING' and vp_num == 'VP-3':
                return ('背离', [f'{stage} 顶背离预警（{vol_struct}）'], conf)
            healthy_stages = {
                'UPTREND_ACTIVE': ('VP-1', 'VP-2'),
                'DOWNTREND_BOTTOMING': ('VP-9', 'VP-4'),
                'UPTREND_TOPPING': ('VP-9',),  # 健康回调
            }
            if vp_num in healthy_stages.get(stage, ()):
                return ('健康', [f'{stage} {vol_struct}'], conf)
            if stage == 'DOWNTREND_ACTIVE' and vp_num in ('VP-7', 'VP-8'):
                return ('中性', [f'{stage} {vol_struct}（下跌中量价正常）'], conf)
            return ('中性', [f'{stage} {vol_struct}'], conf)

        # ③ 回退 volume_price_fit 标签（350号五态扩展）
        vpf = str(tags.get('volume_price_fit', ''))
        if vpf:
            return ({'strong_healthy': '强健康', 'healthy': '健康',
                     'diverging': '背离', 'severe_diverging': '严重背离'}.get(vpf, '中性'),
                    [f'volume_price_fit={vpf}'], conf)
        return ('中性', evidence or ['量价信号缺失'], conf)

    def _build_dim_engine_results(self, tags: dict, signals: dict,
                                   dims: dict, lifecycle: Optional[dict] = None) -> dict:
        """365号批次C：调用6个维度引擎，返回结构化结果

        与旧 _build_dimensions() 并行运行。结果作为附加字段写入 status_snapshot，
        不影响旧仲裁路径。

        Returns:
            {'signal': {...}, 'structure': {...}, 'volume_price': {...},
             'chip_fund': {...}, 'emotion': {...}, 'risk': {...}}
        """
        results = {}
        engine_map = {
            'signal': ('app.opportunity_atlas.dimensions.dim1_signal_engine', 'Dim1SignalEngine'),
            'structure': ('app.opportunity_atlas.dimensions.dim2_structure_engine', 'Dim2StructureEngine'),
            'volume_price': ('app.opportunity_atlas.dimensions.dim3_vp_engine', 'Dim3VPEngine'),
            'chip_fund': ('app.opportunity_atlas.dimensions.dim4_chip_fund_engine', 'Dim4ChipFundEngine'),
            'emotion': ('app.opportunity_atlas.dimensions.dim5_emotion_engine', 'Dim5EmotionEngine'),
            'risk': ('app.opportunity_atlas.dimensions.dim6_risk_engine', 'Dim6RiskEngine'),
            'valuation': ('app.opportunity_atlas.dimensions.dim7_valuation_engine', 'Dim7ValuationEngine'),
        }
        for dim_name, (module_path, class_name) in engine_map.items():
            try:
                import importlib
                mod = importlib.import_module(module_path)
                engine_cls = getattr(mod, class_name)
                engine = engine_cls()
                # 所有引擎统一接口：evaluate(dims, tags, signals, lifecycle)
                # 各引擎内部按需取用，多余参数忽略
                results[dim_name] = engine.evaluate(dims, tags, signals, lifecycle)
            except Exception as e:
                logger.warning(f"维度引擎 {dim_name} 调用失败: {e}")
                results[dim_name] = None
        return results

    def _convert_to_dims_format(self, dim_results: dict, tags: dict) -> dict:
        """366号步骤3：将维度引擎输出转为旧dims格式，保持下游兼容

        Args:
            dim_results: 6个维度引擎的输出结果
            tags: 原始标签数据

        Returns:
            与旧_build_dimensions()输出格式兼容的dims字典
        """
        dims = {}

        # 结构维：从dim2_structure_engine输出提取
        s = dim_results.get('structure')
        if s and isinstance(s, dict):
            judg = s.get('judgment', {})
            dims['structure'] = {
                'state': judg.get('structure', tags.get('state_label', '盘整')),
                'light': judg.get('light', 'yellow'),
                'confidence': 0.7,
                'evidence': [s.get('status_description', {}).get('plain', '')],
            }
        else:
            # 回退到tags推断
            dims['structure'] = {
                'state': tags.get('state_label', '盘整'),
                'light': 'yellow',
                'confidence': 0.5,
                'evidence': [],
            }

        # 量价维：从dim3_vp_engine输出提取
        vp = dim_results.get('volume_price')
        if vp and isinstance(vp, dict):
            judg = vp.get('judgment', {})
            dims['vp'] = {
                'state': judg.get('vp_state', '中性'),
                'light': judg.get('light', 'yellow'),
                'confidence': 0.6,
                'evidence': [],
            }
        else:
            dims['vp'] = {'state': '中性', 'light': 'yellow', 'confidence': 0.5, 'evidence': []}

        # 筹码维
        cf = dim_results.get('chip_fund')
        if cf and isinstance(cf, dict):
            judg = cf.get('judgment', {})
            dims['chip_fund'] = {
                'state': judg.get('flow_direction', '中性'),
                'light': judg.get('light', 'yellow'),
                'confidence': 0.5,
                'evidence': [],
            }
        else:
            dims['chip_fund'] = {'state': '中性', 'light': 'yellow', 'confidence': 0.5, 'evidence': []}

        # 情绪维
        em = dim_results.get('emotion')
        if em and isinstance(em, dict):
            judg = em.get('judgment', {})
            dims['emotion'] = {
                'state': judg.get('phase', '正常'),
                'light': judg.get('overall_light', 'yellow'),
                'confidence': 0.6,
                'evidence': [],
            }
        else:
            dims['emotion'] = {'state': '正常', 'light': 'yellow', 'confidence': 0.5, 'evidence': []}

        # 风险维
        r = dim_results.get('risk')
        if r and isinstance(r, dict):
            judg = r.get('judgment', {})
            dims['risk'] = {
                'state': judg.get('risk_level', '中'),
                'light': judg.get('light', 'yellow'),
                'confidence': 0.6,
                'evidence': [],
            }
        else:
            dims['risk'] = {'state': '中', 'light': 'yellow', 'confidence': 0.5, 'evidence': []}

        # 补充旧体系需要的其他维度（从tags直接推断）
        dims['valuation'] = {
            'state': tags.get('valuation_level', '合理'),
            'light': 'yellow',
            'confidence': 0.5,
            'evidence': [],
        }
        dims['finance'] = {
            'state': tags.get('fina_health', '关注'),
            'light': 'yellow',
            'confidence': 0.5,
            'evidence': [],
        }
        dims['event'] = {
            'state': tags.get('catalyst_event', '中性'),
            'light': 'yellow',
            'confidence': 0.5,
            'evidence': [],
        }
        dims['time'] = {
            'state': '中期',
            'light': 'yellow',
            'confidence': 0.5,
            'evidence': [],
        }
        dims['position'] = {
            'state': tags.get('price_position', '中位'),
            'light': 'yellow',
            'confidence': 0.5,
            'evidence': [],
        }
        dims['factor'] = {
            'state': '中性',
            'light': 'yellow',
            'confidence': 0.5,
            'evidence': [],
        }
        dims['signal_confirm'] = {
            'state': tags.get('right_side_confirm', '未确认'),
            'light': 'yellow',
            'confidence': 0.5,
            'evidence': [],
        }

        return dims

    # 信号生命周期（334号 §5.3：active_signal + 当前价 → 初期/中期/已延伸）
    # ══════════════════════════════════════════════════════════

    def _signal_lifecycle(self, ts_code: str, tags: dict, signals: dict) -> Optional[dict]:
        try:
            active = tags.get('active_signal') or {}
            if isinstance(active, str) and active:
                # 标签值为 Python 单引号字面量（非标准 JSON），用 ast.literal_eval 兼容
                try:
                    active = json.loads(active)
                except Exception:
                    import ast
                    try:
                        active = ast.literal_eval(active)
                    except Exception:
                        active = {}
            sig_date = active.get('date') or ''
            sig_price = float(active.get('price') or 0)
            if not sig_date or sig_price <= 0:
                return None
            # 当前价（最新收盘；ts_code 显式传入——tags dict 无 ts_code 键）
            df = self.dm.get_cached_daily_data(ts_code)
            if df is None or df.empty:
                return None
            price = float(df['close'].iloc[-1])
            dist_pct = (price - sig_price) / sig_price * 100
            # 阶段阈值（signal_registry.yaml 生命周期；统一模板，334号 §5.3）
            _lc = self.registry.get('chan_third_buy', {}).get('lifecycle', {})
            init_d = float(_lc.get('initial', {}).get('dist_pct', 0.05))
            ext_d = float(_lc.get('extended', {}).get('dist_pct', 0.12))
            if dist_pct < 0:
                # 实测修订：现价跌破信号价 → "回撤"（信号有效性受损），非"初期"
                stage = '回撤'
                evidence_txt = f'信号价已跌破（距突破位 {dist_pct:+.1f}%，信号有效性受损）'
            elif dist_pct <= init_d * 100:
                stage = '初期'
                evidence_txt = f'信号距突破位 {dist_pct:+.1f}%（初期，刚脱离成本区）'
            elif dist_pct > ext_d * 100:
                stage = '已延伸'
                evidence_txt = f'信号距突破位 {dist_pct:+.1f}%（已延伸，追高风险大）'
            else:
                stage = '中期'
                evidence_txt = f'信号距突破位 {dist_pct:+.1f}%（中期）'
            return {
                'stage': stage,
                'dist_pct': round(dist_pct, 1),
                'confidence': 0.7,
                'evidence': [evidence_txt],
            }
        except Exception as e:
            logger.debug("生命周期计算失败: %s", e)
            return None

    # ══════════════════════════════════════════════════════════
    # L0 风险分级（335号：L0a 硬否决 / L0b 软约束 / L0c 持有期）
    # ══════════════════════════════════════════════════════════

    def _apply_l0(self, ts_code: str, tags: dict, dims: dict, lifecycle: Optional[dict]) -> dict:
        l0: dict[str, Any] = {
            'hard_veto': False, 'hard_reason': '',
            'soft_risks': [], 'position_coeff': 1.0,
            'hold_only': False,
        }
        # L0a 硬否决（不可逆：监管立案 / ST·退市）
        ce = str(tags.get('catalyst_event', ''))
        if ce == 'regulatory':
            l0['hard_veto'] = True
            l0['hard_reason'] = '监管立案（L0a 硬否决）'
        # L0b 软约束（可逆：仓位系数，对齐 cross_validate._evaluate_gate）
        coeff = self.cfg.get('l0', {}).get('soft_risk_coeff', {})
        if str(tags.get('fina_health', '')) == 'fail':
            l0['soft_risks'].append('fina_fail')
            l0['position_coeff'] *= float(coeff.get('fina_fail', 0.5))
        if str(tags.get('catalyst_event', '')) == 'fraud_sign':
            l0['soft_risks'].append('fina_weak')
            l0['position_coeff'] *= float(coeff.get('fina_weak', 0.5))
        if str(tags.get('main_force_phase', '')) == 'distributing':
            l0['soft_risks'].append('distributing')
            l0['position_coeff'] *= float(coeff.get('distributing', 0.7))
        if str(tags.get('valuation_level', '')) in ('high', 'extreme_high'):
            l0['soft_risks'].append('deep_valuation')
            l0['position_coeff'] *= float(coeff.get('deep_position_cap', 0.3))
        # 流动性：换手率 <1%（daily_basic 最新，对齐 cross_validate._evaluate_gate / 335号 L0b）
        try:
            df = self.dm.get_cached_daily_basic(ts_code)
            if df is not None and not df.empty and 'turnover_rate' in df.columns:
                tr = df['turnover_rate'].dropna()
                if not tr.empty and float(tr.iloc[-1]) < 1.0:
                    l0['soft_risks'].append('low_liquidity')
                    l0['position_coeff'] *= float(coeff.get('low_liquidity', 0.7))
        except Exception:
            pass
        # L0c 持有期（信号已延伸 → 只可持有、不新开仓）
        if lifecycle and lifecycle['stage'] == '已延伸':
            l0['hold_only'] = True
        return l0

    # ══════════════════════════════════════════════════════════
    # L2 聚合（336号：维度共识 + conflict_evidence + opportunity_state）
    # 370号S7：P3动态权重（MARKET_REGIME_WEIGHTS 矩阵替代等权投票）
    # ══════════════════════════════════════════════════════════

    # 358号§5.1 市场状态×维度权重矩阵
    MARKET_REGIME_WEIGHTS = {
        'trending_up':    {'signal': 0.15, 'structure': 0.20, 'vp': 0.15, 'chip_fund': 0.10, 'emotion': 0.10, 'risk': 0.15, 'valuation': 0.15},
        'ranging':        {'signal': 0.10, 'structure': 0.15, 'vp': 0.20, 'chip_fund': 0.10, 'emotion': 0.10, 'risk': 0.20, 'valuation': 0.15},
        'trending_down':  {'signal': 0.10, 'structure': 0.10, 'vp': 0.10, 'chip_fund': 0.10, 'emotion': 0.10, 'risk': 0.30, 'valuation': 0.20},
        'extreme_panic':  {'signal': 0.05, 'structure': 0.05, 'vp': 0.05, 'chip_fund': 0.10, 'emotion': 0.10, 'risk': 0.40, 'valuation': 0.25},
    }

    @staticmethod
    def _detect_market_regime(tags: dict, dims: dict) -> str:
        """从tags/dims推导当前市场状态（370号S7）"""
        # 优先从status_bar推导
        status_bar = str(tags.get('status_bar', ''))
        if '强确认' in status_bar or '趋势确认' in status_bar:
            return 'trending_up'
        if '谨慎' in status_bar or '观望' in status_bar:
            return 'ranging'
        if '风险' in status_bar or '看空' in status_bar:
            return 'trending_down'
        # 回退：从emotion维度推导
        emotion_state = str(dims.get('emotion', {}).get('state', ''))
        if '退潮' in emotion_state or '高潮' in emotion_state:
            return 'extreme_panic'
        # 回退：从risk维度推导
        risk_state = str(dims.get('risk', {}).get('state', ''))
        if risk_state == '高':
            return 'trending_down'
        return 'ranging'  # 默认震荡

    def _aggregate(self, tags: dict, dims: dict, l0: dict, lifecycle: Optional[dict]) -> dict:
        # 370号S7：P3动态权重（替代等权投票）
        regime = self._detect_market_regime(tags, dims)
        weights = self.MARKET_REGIME_WEIGHTS.get(regime, self.MARKET_REGIME_WEIGHTS['ranging'])

        bull = bear = 0.0
        for dim in _DIM_ORDER:
            state = dims.get(dim, {}).get('state', '')
            v = _DIM_DIRECTION[dim].get(state, 0)
            w = weights.get(dim, 0.1)
            if v > 0:
                bull += w
            elif v < 0:
                bear += w

        # 归一化（总权重=1）
        total_w = bull + bear
        if total_w > 0:
            consensus_rate = round(max(bull, bear) / total_w, 3)
            direction = 'bullish' if bull > bear else 'bearish'
        elif bull == bear and bull > 0:
            consensus_rate = 0.0
            direction = 'neutral'
        else:
            consensus_rate = 0.0
            direction = 'neutral'

        # conflict_evidence（336号 §4：现有 4 条 + 扩展 2 条）
        core_conflict: list[str] = []
        sl = str(tags.get('state_label', ''))
        ta = str(tags.get('trend_alignment', ''))
        if '下降' in sl and ta == 'up_aligned':
            core_conflict.append('缠论趋势下降 vs 多周期趋势向上（方向分歧）')
        if '上升' in sl and ta == 'down_aligned':
            core_conflict.append('缠论趋势上升 vs 多周期趋势向下（方向分歧）')
        try:
            pr = float(tags.get('profit_ratio') or 0)
            if pr >= 0.8 and str(tags.get('price_position', '')) == 'high_zone':
                core_conflict.append(f'获利盘 {pr:.0%} 高位（追涨风险大）')
            if pr >= 0.8 and str(tags.get('main_force_presence', '')) == 'none':
                core_conflict.append(f'获利盘 {pr:.0%} 高位且无主力在场证据（接续乏力风险）')
        except (TypeError, ValueError):
            pass
        if str(tags.get('main_force_phase', '')) == 'distributing':
            core_conflict.append('主力出货阶段 vs 右侧确认看多（资金分歧）')
        if str(tags.get('risk_level', '')) == 'HIGH':
            core_conflict.append('结构风险 HIGH vs 右侧确认（风险收益不匹配）')

        # opportunity_state（复用 arbiter P0-P7 状态机；gate 从 L0 推导）
        state = 'wait'
        evidence: list[str] = []
        try:
            from app.opportunity_atlas.arbiter import arbitrate
            gate = {
                'valuation': 'deep' if 'deep_valuation' in l0['soft_risks'] else 'none',
                'hard_risks': ['event_negative'] if l0['hard_veto'] else [],
                'soft_risks': l0['soft_risks'],
            }
            arb = arbitrate(tags, gate=gate,
                            consensus={'direction': direction,
                                       'consensus_rate': consensus_rate})
            state = arb['opportunity_state']
            evidence = arb['state_evidence']
            arb_conflict = arb.get('conflict_evidence', [])
        except Exception as e:
            logger.debug("仲裁失败 %s: %s", tags.get('ts_code', ''), e)
            evidence = ['仲裁不可用']
            arb_conflict = []
        if l0['hard_veto']:
            state, evidence = 'avoid', [l0['hard_reason']]
        if l0['hold_only'] and state in ('enter', 'light'):
            state, evidence = 'wait', ['信号已延伸：只可持有、不新开仓（L0c）']

        return {
            'opportunity_state': state,
            'state_evidence': evidence,
            'consensus_rate': consensus_rate,
            'direction': direction,
            'bullish_dims': bull,
            'bearish_dims': bear,
            'conflict_evidence': core_conflict[:4] + arb_conflict[:4],
        }

    def _detect_registered_signals(self, tags: dict, signals: dict) -> list:
        """334号 §5：信号注册表触发检测（5 类信号 → 触发列表，供七维模板①信号确认）

        signal_registry.yaml 登记触发条件（此处为判定实现；验证条件=N 日站稳由
        signal_records 回算分群验证——334 §6 校准机制）。
        """
        hits: list[dict] = []
        bsp = str(tags.get('buy_sell_point', ''))
        if '三买' in bsp or 'third_buy' in bsp:
            hits.append({'type': 'chan_third_buy', 'name': '缠论三买', 'source': 'buy_sell_point'})
        vp = signals.get('量价分析策略') or {}
        if '突破' in str(vp.get('signal_label', '')):
            hits.append({'type': 'volume_breakout', 'name': '放量突破', 'source': '量价信号'})
        if '多头' in str(tags.get('ma_alignment', '')):
            hits.append({'type': 'ma_bullish', 'name': '均线多头', 'source': 'ma_alignment'})
        ps = str(tags.get('pattern_signal', ''))
        if '突破' in ps:
            hits.append({'type': 'platform_breakout', 'name': '平台突破', 'source': 'pattern_signal'})
        if ps and ps != 'none':
            hits.append({'type': 'pattern_up', 'name': '量价强势形态', 'source': 'pattern_signal'})
        return hits

    # ══════════════════════════════════════════════════════════
    # 成品仓输出（337号：status_snapshot 行结构）
    # ══════════════════════════════════════════════════════════

    def _status_bar(self, dims: dict, state: str, l0: dict = None) -> str:
        """364a Phase 1：status_bar 5态扩展"""
        green = sum(1 for d in dims.values() if d.get('light') == 'green')
        red = sum(1 for d in dims.values() if d.get('light') == 'red')
        l0 = l0 or {}
        # 优先级1：不可交易
        if state == 'avoid':
            return '不可交易'
        # 优先级2：风险区（硬否决或红灯>=6）
        if l0.get('hard_veto') or red >= 6:
            return '风险区'
        # 优先级3：持有观望
        if l0.get('hold_only'):
            return '持有观望'
        # 优先级4：强趋势
        if green >= 6:
            return '强趋势'
        # 优先级5：趋势确认
        if green >= 4:
            return '趋势确认'
        # 优先级6：趋势转弱
        if red >= 4:
            return '趋势转弱'
        # 默认：趋势不明
        return '趋势不明'

    def _assemble(self, ts_code: str, dims: dict, lifecycle: Optional[dict],
                  l0: dict, l2: dict, hits: Optional[list] = None,
                  dim_engine_results: Optional[dict] = None) -> dict:
        # 337号 §6.2：建议规则参数（套算输入——仓位上限经 L0 系数、持有期限制、软风险）
        _state = l2['opportunity_state']
        _base = 0.6 if _state in ('enter', 'light') else (0.2 if _state == 'wait' else 0.0)
        advice_params = {
            'max_position_ratio': round(_base * l0['position_coeff'], 2),
            'hold_only': l0['hold_only'],
            'soft_risks': l0['soft_risks'],
            'hard_veto': l0['hard_veto'],
        }
        result = {
            'ts_code': ts_code,
            'dim_states': json.dumps(dims, ensure_ascii=False),
            'status_bar': self._status_bar(dims, l2['opportunity_state'], l0),
            'opportunity_state': l2['opportunity_state'],
            'state_evidence': json.dumps(l2['state_evidence'], ensure_ascii=False),
            'conflict_evidence': json.dumps(l2['conflict_evidence'], ensure_ascii=False),
            'consensus_rate': l2['consensus_rate'],
            'direction': l2['direction'],
            'l0': json.dumps(l0, ensure_ascii=False),
            'lifecycle': json.dumps(lifecycle, ensure_ascii=False) if lifecycle else None,
            'advice_params': json.dumps(advice_params, ensure_ascii=False),
            'signals': json.dumps(hits or [], ensure_ascii=False),  # 334号 §5：注册表触发列表
        }
        # 365号批次C：维度引擎结果附加字段
        if dim_engine_results:
            result['dim_engine_results'] = json.dumps(dim_engine_results, ensure_ascii=False, default=str)
        return result


def apply_advice_params(params: dict, price: Optional[float],
                        df=None, rr_gate: float = 1.0) -> dict:
    """337号 §6.3：实时操作建议轻量套算（日频成品 advice_params + 现价）

    套算 = 盈亏比门禁 + L0 软风险仓位（不含完整 K 线重算）；
    止损位（结构位）由调用方从 K 线提供（advice_builder._geometric 同源）。
    """
    if not params:
        return {'state': 'wait', 'max_position_ratio': 0.0, 'reason': '无建议参数'}
    state = 'enter' if params.get('max_position_ratio', 0) > 0 else 'wait'
    if params.get('hard_veto'):
        return {'state': 'avoid', 'max_position_ratio': 0.0, 'reason': 'L0a 硬否决'}
    if params.get('hold_only'):
        return {'state': 'wait', 'max_position_ratio': 0.0, 'reason': '信号已延伸：只可持有、不新开仓（L0c）'}
    # 盈亏比门禁（知识库：rr<1 降级观望）
    if df is not None and not df.empty and price:
        try:
            from app.opportunity_atlas.advice_builder import _geometric
            geo = _geometric(df)
            sup = geo.get('support_price')
            res = geo.get('resistance_price')
            if sup and res and (price - sup) > 0:
                rr = (res - price) / (price - sup)
                if rr < rr_gate:
                    return {'state': 'wait',
                            'max_position_ratio': round(params.get('max_position_ratio', 0) * 0.5, 2),
                            'reason': f'盈亏比不足（≈{rr:.2f}<{rr_gate}），止损过宽'}
        except Exception:
            pass
    return {'state': state, 'max_position_ratio': params.get('max_position_ratio', 0.0),
            'reason': '可入场' if state == 'enter' else '观望'}


def build_seven_dim_report(snapshot_row: dict, tags: dict = None,
                           geo: dict = None, l0: dict = None, df=None) -> dict:
    """[已废弃] 旧Path B七维描述生成 — 370号方案确认由SIG直接产出seven_dim_json替代

    保留空壳函数避免管道崩溃，待S6步骤（OUT简化）完成后彻底删除。
    """
    return {}


def generate_seven_dim_from_signals(signal_json: dict) -> dict:
    """370号方案S5：SIG环节直接产出七维现状描述（替代旧build_seven_dim_report）

    从strategy_signal_detail.signal_json中的5引擎信号提取七维描述。
    产出直接透传到OUT写入one_liner_detail，不经过JUD。

    Returns: {dim_key: {title, light, text, evidence}} 的七维字典
    """
    signals = signal_json.get('signals', {}) or {}

    def _extract(engine_name, dim_key, title):
        sig = signals.get(engine_name, {})
        if not sig:
            return None
        direction = sig.get('direction', 'neutral')
        confidence = sig.get('confidence', 0.5)
        evidence = sig.get('evidence', [])
        status_rec = sig.get('status_recognition', {})

        # 方向→灯色映射
        if direction in ('bullish', 'BUY'):
            light = 'green'
        elif direction in ('bearish', 'SELL'):
            light = 'red'
        else:
            light = 'yellow'

        # 状态文本
        state = status_rec.get('stage', '') or status_rec.get('trend', {}).get('direction', '')
        text = f"{title}: {direction} (置信度 {confidence:.0%})"
        if state:
            text += f" [{state}]"

        return {
            'title': title,
            'light': light,
            'text': text,
            'evidence': evidence[:5],
            'confidence': round(confidence, 2),
        }

    result = {}
    # dim1: 信号确认（从right_side_confirm标签推导）
    rsc = signal_json.get('data_availability', {}).get('right_side_confirm', '')
    if rsc:
        result['signal_confirm'] = {
            'title': '信号确认状态',
            'light': 'green' if rsc in ('强确认', '基础确认') else ('red' if rsc == '否决' else 'yellow'),
            'text': f"信号确认: {rsc}",
            'evidence': [],
            'confidence': 0.8 if rsc == '强确认' else 0.5,
        }
    # dim2: 结构位置（缠论）
    seg = _extract('缠论走势分析', 'structure', '结构位置状态')
    if seg:
        result['structure'] = seg
    # dim3: 量价健康
    seg = _extract('量价分析策略', 'volume_price', '量价健康度')
    if seg:
        result['volume_price'] = seg
    # dim4: 资金筹码
    seg = _extract('筹码主力分析', 'chip_fund', '资金与筹码状态')
    if seg:
        result['chip_fund'] = seg
    # dim5: 情绪环境
    seg = _extract('BOCIASI快线', 'emotion', '情绪环境状态')
    if not seg:
        seg = _extract('BOCIASI慢线(情绪-跨市场)', 'emotion', '情绪环境状态')
    if seg:
        result['emotion'] = seg
    # dim6: 风险边界（综合多个信号）
    risk_evidence = []
    risk_light = 'yellow'
    for ename in ('筹码主力分析', '量价分析策略', '缠论走势分析'):
        sig = signals.get(ename, {})
        if sig.get('direction') in ('bearish', 'SELL'):
            risk_evidence.append(f"{ename}看空")
            risk_light = 'red'
    result['risk'] = {
        'title': '风险边界状态',
        'light': risk_light,
        'text': f"风险边界: {'高' if risk_light == 'red' else '中' if risk_light == 'yellow' else '低'}",
        'evidence': risk_evidence,
        'confidence': 0.6,
    }
    # dim7: 状态总结
    total = len([v for v in result.values() if v.get('light') == 'green'])
    reds = len([v for v in result.values() if v.get('light') == 'red'])
    if total > reds:
        summary_light = 'green'
        summary_text = f"整体偏多（{total}维看多/{reds}维看空）"
    elif reds > total:
        summary_light = 'red'
        summary_text = f"整体偏空（{reds}维看空/{total}维看多）"
    else:
        summary_light = 'yellow'
        summary_text = f"多空均衡（{total}维看多/{reds}维看空）"
    result['summary'] = {
        'title': '状态总结',
        'light': summary_light,
        'text': summary_text,
        'evidence': [],
        'confidence': 0.5,
    }
    return result
    """364a Phase 1 / 365号修订：生成一句话总结"""
    import json as _json
    try:
        dims = _json.loads(snapshot_row.get('dim_states') or '{}')
    except Exception:
        dims = {}
    st = snapshot_row.get('status_bar', '')
    cr = snapshot_row.get('consensus_rate', 0) or 0
    dim_parts = []
    for dim_key, name in [('structure', '结构'), ('vp', '量价'), ('chip_fund', '资金'), ('emotion', '情绪')]:
        s = dims.get(dim_key, {}).get('state', '')
        if s:
            dim_parts.append(f'{name}{s}')
    risk = dims.get('risk', {}).get('state', '')
    if risk:
        dim_parts.append(f'风险{risk}')
    dims_text = '，'.join(dim_parts) if dim_parts else '各维数据不足'
    return f'{st}（共识{cr:.0%}）——{dims_text}'


def build_status_engine() -> StatusEngine:
    return StatusEngine()
