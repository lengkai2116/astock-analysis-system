"""status_engine.py — 现状判定引擎·生产环节核心（332总纲 §5，338号 S2.1）

落地分档：334（L1 维度判定+信号注册表+生命周期）、335（L0 风险分级）、
         336（L2 聚合：维度共识+conflict_evidence）、337（成品仓输出 status_snapshot 行）

流水线：原料仓（标签 opportunity_tags_cache + P2 信号 strategy_signal_detail）
  → L1 十维判定（每维 {state, light, confidence, evidence, conclusion, plain}）
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

        Returns: status_snapshot 行 dict（或 None 数据缺失）
        """
        tags = self._load_tags(ts_code)
        signals = self._load_signals(ts_code)
        if not tags and not signals:
            return None

        lifecycle = self._signal_lifecycle(ts_code, tags, signals)
        dims = self._build_dimensions(ts_code, tags, signals, lifecycle)
        l0 = self._apply_l0(ts_code, tags, dims, lifecycle)
        l2 = self._aggregate(tags, dims, l0, lifecycle)
        hits = self._detect_registered_signals(tags, signals)

        return self._assemble(ts_code, dims, lifecycle, l0, l2, hits)

    # ══════════════════════════════════════════════════════════
    # 原料加载（存储层只读）
    # ══════════════════════════════════════════════════════════

    def _load_tags(self, ts_code: str) -> dict:
        try:
            return self.dm.cache.get_tags(ts_code) or {}
        except Exception as e:
            logger.debug("tags 读取失败 %s: %s", ts_code, e)
            return {}

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

    def _build_dimensions(self, ts_code: str, tags: dict, signals: dict,
                          lifecycle: Optional[dict] = None) -> dict[str, dict]:
        s = lambda *names: next((signals[n] for n in names if n in signals), None)  # noqa: E731
        chan = s('缠论走势分析')
        vp = s('量价分析策略')
        chip = s('筹码主力分析')
        bociasi = s('BOCIASI快线', 'BOCIASI慢线(情绪-跨市场)')
        factor = s('因子评分系统')

        dims: dict[str, dict] = {}

        def put(dim: str, state: str, conf: float, evidence: list):
            mapping = _DIM_DIRECTION[dim]
            state = state if state in mapping else list(mapping.keys())[1]
            dims[dim] = {
                'state': state,
                'light': _DIM_LIGHT[dim][state],
                'confidence': round(float(conf), 2),
                'evidence': evidence[:5],
            }

        # 1 估值（标签原料，350号五级分档）
        vl = str(tags.get('valuation_level', ''))
        put('valuation', {'extreme_low': '极度低估', 'low': '低估', 'fair': '合理',
                          'high': '高估', 'extreme_high': '极度高估'}.get(vl, '合理'),
            0.7, [f'valuation_level={vl}'] if vl else ['估值数据缺失'])

        # 2 结构（P2 缠论）
        if chan:
            td = ((chan.get('status_recognition') or {}).get('trend') or {}).get('direction', '')
            put('structure', '上升' if td == 'up' else ('下降' if td == 'down' else '盘整'),
                chan.get('confidence', 0.5),
                [str(e) for e in (chan.get('evidence') or [])[:3]])
        else:
            put('structure', '盘整', 0.3, ['缠论信号缺失'])

        # 2b 量价（P2 量价信号；332 §5.2 量价→量价维，334 表遗漏本次修订补入）
        # 342号核查修复（2026-08-16）：原 `trend.direction=='down' → 背离` 为概念误用
        # （趋势向下≠背离）。改为三重数据源按优先级：
        #   ① P2 真实背离检测（volume_price_detail.量价关系.divergence_type + MACD 确认）
        #   ② P2 阶段×量价结构交叉矩阵（trend.stage × volume.structure）
        #   ③ 回退 volume_price_fit 标签
        if vp:
            vp_state, vp_ev, vp_conf = StatusEngine._derive_vp_state(vp, tags)
            put('vp', vp_state, vp_conf, vp_ev)
        else:
            vpf = str(tags.get('volume_price_fit', ''))
            put('vp', {'healthy': '健康', 'diverging': '背离'}.get(vpf, '中性'),
                0.5, [f'volume_price_fit={vpf}'] if vpf else ['量价信号缺失'])

        # 3 位置（标签原料，350号：中枢上沿覆盖）
        pp = str(tags.get('price_position', ''))
        pos_state = {'low_zone': '站上防守位', 'high_zone': '跌破'}.get(pp, '中位')
        # 350号：价格高于中枢上沿时覆盖为"站上防守位"（知识库《右侧交易框架》）
        # 从 support_resistance 标签读取中枢上沿（resistance），从 daily_cache 读取当前价格
        if pos_state == '中位':
            try:
                import json as _json
                sr_raw = tags.get('support_resistance', '{}')
                sr = _json.loads(sr_raw) if isinstance(sr_raw, str) else (sr_raw or {})
                resistance = float(sr.get('resistance', 0) or 0)
                if resistance > 0:
                    df = self.dm.get_cached_daily_data(ts_code)
                    if df is not None and not df.empty:
                        current_price = float(df['close'].iloc[-1])
                        if current_price > resistance:
                            pos_state = '站上防守位'
            except Exception:
                pass
        put('position', pos_state, 0.6, [f'price_position={pp}'] if pp else ['位置数据缺失'])

        # 4 筹码资金（P2 筹码 + 标签资金）
        if chip:
            cst = str((chip.get('status_recognition') or {}).get('state', ''))
            put('chip_fund', '流入' if ('拉升' in cst or '建仓' in cst)
                else ('流出' if '出货' in cst else '中性'),
                chip.get('confidence', 0.5), [str(e) for e in (chip.get('evidence') or [])[:3]])
        else:
            ff = str(tags.get('fund_flow', ''))
            put('chip_fund', '流入' if ff == '5d_inflow' else ('流出' if ff == '5d_outflow' else '中性'),
                0.5, [f'fund_flow={ff}'] if ff else ['筹码/资金数据缺失'])

        # 5 情绪（P2 BOCIASI + 标签情绪）
        sp = str(tags.get('sentiment_phase', ''))
        emo_state = {'recovery': '复苏', 'climax': '退潮·高潮', 'ebb': '退潮·高潮'}.get(sp, '正常')
        if bociasi:
            esig = str(bociasi.get('signal', ''))
            if esig in ('bullish', 'BULLISH'):
                emo_state = '复苏'
            elif esig in ('bearish', 'BEARISH'):
                emo_state = '退潮·高潮'
        put('emotion', emo_state, bociasi.get('confidence', 0.5) if bociasi else 0.5,
            [f'sentiment_phase={sp}'] if sp else ['情绪数据缺失'])

        # 6 财务（标签原料）
        fh = str(tags.get('fina_health', ''))
        put('finance', {'pass': '健康', 'suspicious': '关注', 'fail': '风险'}.get(fh, '关注'),
            0.7, [f'fina_health={fh}'] if fh else ['财务数据缺失'])

        # 7 事件（标签原料）
        ce = str(tags.get('catalyst_event', ''))
        _neg = {'pledge', 'float', 'reduce', 'fraud_sign', 'regulatory', 'lawsuit', 'decline'}
        _pos = {'earnings', 'lhb', 'concept', 'buyback', 'breakout', 'new_high', 'profit_growth'}
        ev = '正向' if ce in _pos else ('负面' if ce in _neg else '中性')
        put('event', ev, 0.7, [f'catalyst_event={ce}'] if ce else ['事件数据缺失'])

        # 8 时间（标签 time_rhythm + 信号生命周期）
        put('time', lifecycle['stage'] if lifecycle else '中期',
            lifecycle['confidence'] if lifecycle else 0.5,
            lifecycle['evidence'] if lifecycle else ['无有效信号，时间维度中性'])

        # 9 风险（标签 risk_level + 波动率）
        rl = str(tags.get('risk_level', ''))
        vl_lv = str(tags.get('volatility_level', ''))
        risk_state = '高' if (rl == 'HIGH' or vl_lv == 'high') else ('低' if rl == 'LOW' else '中')
        put('risk', risk_state, 0.6, [f'risk_level={rl}', f'volatility_level={vl_lv}'])

        # 10 因子（P2 因子信号，校验维）
        if factor:
            fd = str(factor.get('signal', '')).lower()
            put('factor', '看多' if fd in ('bullish', 'up')
                else ('看空' if fd in ('bearish', 'down') else '中性'),
                factor.get('confidence', 0.5), [str(e) for e in (factor.get('evidence') or [])[:3]])
        else:
            put('factor', '中性', 0.3, ['因子信号缺失'])

        # 332号§5.5 + 352号G1：信号确认维度（不参与九维平均计票，仅输出状态+证据+红绿灯）
        rsc = str(tags.get('right_side_confirm', ''))
        bsp = str(tags.get('buy_sell_point', ''))
        if rsc == '否决':
            _sc_state, _sc_conf, _sc_ev = '否决', 0.7, [f'right_side_confirm=否决', f'buy_sell_point={bsp}']
            _sc_light = 'red'
        elif rsc == '强确认':
            _sc_state, _sc_conf, _sc_ev = '强确认', 0.8, [f'right_side_confirm=强确认']
            _sc_light = 'green'
        elif rsc == '基础确认':
            _sc_state, _sc_conf, _sc_ev = '基础确认', 0.6, [f'right_side_confirm=基础确认']
            _sc_light = 'green'
        else:
            _sc_state, _sc_conf, _sc_ev = '未确认', 0.5, [f'right_side_confirm={rsc or "无"}']
            _sc_light = 'yellow'
        dims['signal_confirm'] = {'state': _sc_state, 'light': _sc_light,
                                   'confidence': _sc_conf, 'evidence': _sc_ev}

        return dims

    # ══════════════════════════════════════════════════════════
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
    # ══════════════════════════════════════════════════════════

    def _aggregate(self, tags: dict, dims: dict, l0: dict, lifecycle: Optional[dict]) -> dict:
        # 维度共识（方向票：中性不稀释，口径与 L4 一致）
        weights = self.cfg.get('dimension_weights', {})
        bull = bear = 0
        for dim in _DIM_ORDER:
            state = dims.get(dim, {}).get('state', '')
            v = _DIM_DIRECTION[dim].get(state, 0)
            if v > 0:
                bull += 1
            elif v < 0:
                bear += 1
        # 336号§2.2 + 352号G7：多空打平→consensus_rate=0.0（无优势方向）
        if bull == bear and bull > 0:
            consensus_rate = 0.0
            direction = 'neutral'
        elif bull + bear > 0:
            consensus_rate = round(max(bull, bear) / (bull + bear), 3)
            direction = 'bullish' if bull > bear else 'bearish'
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

    def _status_bar(self, dims: dict, state: str) -> str:
        green = sum(1 for d in dims.values() if d['light'] == 'green')
        red = sum(1 for d in dims.values() if d['light'] == 'red')
        if state == 'avoid':
            return '风险区'
        if green >= 6:
            return '强趋势'
        if green >= 4:
            return '趋势确认'
        if red >= 4:
            return '趋势转弱'
        return '趋势确认'

    def _assemble(self, ts_code: str, dims: dict, lifecycle: Optional[dict],
                  l0: dict, l2: dict, hits: Optional[list] = None) -> dict:
        # 337号 §6.2：建议规则参数（套算输入——仓位上限经 L0 系数、持有期限制、软风险）
        _state = l2['opportunity_state']
        _base = 0.6 if _state in ('enter', 'light') else (0.2 if _state == 'wait' else 0.0)
        advice_params = {
            'max_position_ratio': round(_base * l0['position_coeff'], 2),
            'hold_only': l0['hold_only'],
            'soft_risks': l0['soft_risks'],
            'hard_veto': l0['hard_veto'],
        }
        return {
            'ts_code': ts_code,
            'dim_states': json.dumps(dims, ensure_ascii=False),
            'status_bar': self._status_bar(dims, l2['opportunity_state']),
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


def build_seven_dim_report(snapshot_row: dict) -> dict:
    """337号 §5：七维现状描述模板按需组装（个股页详述版，素材=status_snapshot.dim_states）

    七段模板：信号确认/结构位置/量价健康/资金筹码/情绪环境/风险边界/状态总结。
    """
    import json as _json
    try:
        dims = _json.loads(snapshot_row.get('dim_states') or '{}')
    except Exception:
        dims = {}
    st = snapshot_row.get('status_bar', '')
    state = snapshot_row.get('opportunity_state', 'wait')
    _l = {'green': '✅', 'yellow': '⚠️', 'red': '🚫'}

    def _seg(title: str, light: str, text: str, plain: str = '') -> dict:
        return {'title': title, 'light': _l.get(light, '⚠️'), 'text': text, 'plain': plain}

    segments = {
        'signal': _seg('信号确认状态', dims.get('time', {}).get('light', 'yellow'),
                       f"信号生命周期：{dims.get('time', {}).get('state', '中期')}"
                       f"{'（' + dims.get('time', {}).get('evidence', [''])[0] + '）' if dims.get('time', {}).get('evidence') else ''}",
                       '最近信号的介入贵贱'),
        'structure': _seg('结构位置状态', dims.get('structure', {}).get('light', 'yellow'),
                          f"走势结构：{dims.get('structure', {}).get('state', '盘整')}；"
                          f"价格位置：{dims.get('position', {}).get('state', '中位')}",
                          '价格站在哪里、趋势方向'),
        'volume_price': _seg('量价健康度', dims.get('vp', {}).get('light', 'yellow'),
                             f"量价健康度：{dims.get('vp', {}).get('state', '中性')}"
                             f"{'（' + dims.get('vp', {}).get('evidence', [''])[0] + '）' if dims.get('vp', {}).get('evidence') else ''}",
                             '涨得结不结实（量价配合/背离）'),
        'fund_chip': _seg('资金与筹码状态', dims.get('chip_fund', {}).get('light', 'yellow'),
                          f"筹码资金：{dims.get('chip_fund', {}).get('state', '中性')}",
                          '谁在买、筹码状态'),
        'emotion': _seg('情绪环境状态', dims.get('emotion', {}).get('light', 'yellow'),
                        f"市场情绪：{dims.get('emotion', {}).get('state', '正常')}；"
                        f"事件：{dims.get('event', {}).get('state', '中性')}",
                        '现在是不是好时候'),
        'risk': _seg('风险边界状态', dims.get('risk', {}).get('light', 'yellow'),
                     f"风险等级：{dims.get('risk', {}).get('state', '中')}；"
                     f"估值：{dims.get('valuation', {}).get('state', '合理')}；"
                     f"财务：{dims.get('finance', {}).get('state', '关注')}",
                     '错了在哪认错'),
        'summary': _seg('状态总结（仪表盘）', 'green' if state in ('enter', 'light') else 'yellow',
                        f"{st}（{state}）——维度共识 {snapshot_row.get('consensus_rate', 0):.0%}",
                        '综合状态条'),
    }
    return segments


def build_status_engine() -> StatusEngine:
    return StatusEngine()
