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
from typing import Any, Optional

from app.services.account_risk_status import get_account_risk_status
from app.services.status_config import get_signal_registry, get_status_engine_config

logger = logging.getLogger(__name__)


def _norm_date(d: Optional[str], compact: bool) -> Optional[str]:
    """归一化日期为统一格式（pre_feat_cache 用 YYYY-MM-DD、strategy_signal_detail 用 YYYYMMDD）

    507批次7 #S6：evaluate(asof_date) 跨表读历史快照时格式对齐。
    """
    if not d:
        return None
    s = str(d).strip().replace('-', '').replace('/', '')
    if len(s) < 8:
        return None
    if compact:
        return f'{s[0:4]}{s[4:6]}{s[6:8]}'
    return f'{s[0:4]}-{s[4:6]}-{s[6:8]}'

# ── 维度方向映射（336号 §2.2：L1 十维状态 → +1/0/-1 计票） ──
_DIM_DIRECTION: dict[str, dict[str, int]] = {
    'valuation': {'极度低估': 2, '低估': 1, '合理': 0, '高估': -1, '极度高估': -2},
    'structure': {'上升': 1, '盘整': 0, '下降': -1},
    'vp': {'强健康': 2, '健康': 1, '中性': 0, '背离': -1, '严重背离': -2},
    'position': {'站上防守位': 1, '中位': 0, '跌破': -1},
    'chip_fund': {'流入': 1, '中性': 0, '流出': -1},
    # 491号：emotion 行与 dim_adapter.DIM_DIRECTION / 生效表 _EMOTION_DIRECTION 统一（逆势口径）
    'emotion': {'冰点': 1, '萌芽': 1, '发酵': 1, '复苏': 1, '正常': 0, '中性': 0,
                '回归': 0, '退潮': 0, '退潮·高潮': 0, '消极': 0, '高潮': -1, '积极': -1},
    'finance': {'健康': 1, '关注': 0, '风险': -1},
    'event': {'正向': 1, '中性': 0, '负面': -1},
    'time': {'初期': 1, '中期': 0, '已延伸': -1, '回撤': -1},
    'risk': {'低': 1, '中': 0, '高': -1},
    'factor': {'看多': 1, '中性': 0, '看空': -1},
}
# 491号（R5）：_DIM_LIGHT 定义后全仓无任何消费点（灯色由各维 judgment.overall_light 提供），已删。
_DIM_ORDER = ['valuation', 'structure', 'vp', 'position', 'chip_fund', 'emotion',
              'finance', 'event', 'time', 'risk', 'factor']


# ══════════════════════════════════════════════════════════
# 492号（K2/K3）：市场情绪阶段归一化 SSOT
#   背景：L0b2 情绪仓位上限与 L3 STATE_WEIGHTS 原均读 tags['emotion_phase']，
#   而 RAW 真实生产键为 flatten(pre_feat['sentiment']) → tags['sentiment_phase']
#   （值域 = get_sentiment_phase 的 ice/sprout/ferment/climax/ebb/regression/neutral），
#   emotion_phase 全仓无生产者 → 两处情绪耦合机制恒取 normal、永不生效。
#   口径（用户 2026-09-27 拍板「就近归并」）：sprout→recovery、ferment→positive、
#   regression/neutral→normal；其余同名。不新增键、不改既有权重值。
# ══════════════════════════════════════════════════════════
_SENTIMENT_TO_STATE_PHASE: dict[str, str] = {
    'ice': 'ice',
    'ebb': 'ebb',
    'climax': 'climax',
    'recovery': 'recovery',
    'positive': 'positive',
    'sprout': 'recovery',      # 萌芽 ≈ 复苏（情绪初起）
    'ferment': 'positive',     # 发酵 ≈ 积极（赚钱效应扩散）
    'regression': 'normal',    # 回归 ≈ 正常
    'neutral': 'normal',       # 数据不足 ≈ 正常
    '正常': 'normal', '中性': 'normal', '萌芽': 'recovery',
    '发酵': 'positive', '复苏': 'recovery', '积极': 'positive',
    '冰点': 'ice', '退潮': 'ebb', '高潮': 'climax', '回归': 'normal',
}


def _normalize_emotion_phase(tags: dict) -> str:
    """情绪阶段 → STATE_WEIGHTS / emotion_position_cap 键（492号 K2/K3 共用）。

    优先读生效生产键 `sentiment_phase`，兼容已废弃键 `emotion_phase`（若上游补产）。
    未命中一律回落 'normal'（旧行为兜底）。
    """
    _raw = tags.get('sentiment_phase', tags.get('emotion_phase', 'normal'))
    _raw = str(_raw or 'normal').lower().strip()
    return _SENTIMENT_TO_STATE_PHASE.get(_raw, 'normal')


# ══════════════════════════════════════════════════════════
# 493号（P2-c）：冰点末期（反转入场窗）识别
#   依据：知识库《华泰A股情绪指数》「触及10%恐慌区间不买，**回归10%之上再买入（右侧确认）**」；
#   《共振冰点策略》冰点确认后「复苏确认」渐进加仓。市场仍处 ice、但个股已出现**右侧确认**
#   （强确认/基础确认）时，视为「冰点末期」——解除冰点 10% 仓位上限，放开至正常档。
#   仅用已存在键（derived.right_side_confirm 扁平为 tags['right_side_confirm']），不新增数据源。
# ══════════════════════════════════════════════════════════
_EMOTION_RECOVERING_RSC = {'强确认', '基础确认'}

# 494号（R-1）：冰点末期回升阈值（市场级温度）
#   依据《华泰A股情绪指数》「回归 10% 之上再买入」+《情绪周期-仓位联动》冰点 10%/空仓；
#   阈值口径 = 温度五档「冰冷<20 / 偏冷20-40 / 中性40-60」的偏冷区中值。
#   校准（全市场市场级温度，09-24 真值）：ice 真冰点（涨停 0/封板低/广度低）≈27.5 不触发；
#   ice 但热度已起（涨停52/封板84%/广度39%）≈42.6 触发。
ICE_RECOVERY_TEMP = 35.0


def _market_level_temperature(tags: dict, raw_pre_feat: dict = None) -> float:
    """494号（R-1/R-9）：市场级情绪温度 —— gate 用「市场级」而非个股级回升。

    R-9 取数口径（用户 2026-09-28 拍板「直读市场级源 + R-9 兜底」）：
      1. `raw_pre_feat['sentiment']` 的 `limit_up_count`/`sealing_rate`（R-9 兜底；实测仅
         488-2 定向重算的少数股有，全市场覆盖低）；
      2. `raw_pre_feat['market_stats']['ma20_ratio']` 作 `breadth`（5544/5552，主源）；
      3. flat tags 的 `limit_up_count`/`sealing_rate`/`breadth`（若上游补产）。
    个股/板块级输入（sector_rank / volume_price_fit）统一置中性——见 `market_level_temperature`。
    直读 `sentiment_pool_cache`/`market_stats_cache` 兜底由 `_apply_l0` 完成（无 raw 场景）。
    """
    from app.opportunity_atlas.emotion_temperature import market_level_temperature
    tags = tags or {}
    raw = raw_pre_feat if isinstance(raw_pre_feat, dict) else {}
    _sent = raw.get('sentiment') if isinstance(raw.get('sentiment'), dict) else {}
    _ms = raw.get('market_stats') if isinstance(raw.get('market_stats'), dict) else {}
    _lu = _sent.get('limit_up_count', tags.get('limit_up_count'))
    _sr = _sent.get('sealing_rate', tags.get('sealing_rate'))
    _br = _ms.get('ma20_ratio', tags.get('breadth'))
    return market_level_temperature(
        sentiment_phase=_normalize_emotion_phase(tags),
        limit_up_count=_lu if isinstance(_lu, int) else None,
        sealing_rate=_sr if isinstance(_sr, (int, float)) else None,
        breadth=_br if isinstance(_br, (int, float)) else None,
        margin_change_pct=None,
    )


def _emotion_is_recovering(tags: dict, raw_pre_feat: dict = None) -> bool:
    """494号（R-1）：冰点末期判定 = **市场级**情绪仍处冰点（ice）且市场级温度已回升。

    口径（对齐《华泰A股情绪指数》「触及10%恐慌不买，回归10%之上再买入」）：
      `sentiment_phase == 'ice'` 且 `mkt_temp ≥ ICE_RECOVERY_TEMP`。
    市场级温度经 `market_level_temperature`（个股/板块输入置中性后重算）。

    ⚠️ 493 原实现读**个股级** `right_side_confirm`，与市场级 ice gate 维度错位（全市场 ice
    样本 0 → 组合 0 可达）。个股 `right_side_confirm` 降级为 **evidence 附注**（另产
    `emotion_recovering_basis`），不进 gate。
    """
    _phase = _normalize_emotion_phase(tags or {})
    if _phase != 'ice':
        return False
    try:
        return _market_level_temperature(tags, raw_pre_feat) >= ICE_RECOVERY_TEMP
    except Exception:
        return False


def _market_level_inputs_via_dm(dm) -> dict:
    """494号（R-1）：无 raw pre_feat 时，JUD 侧直读市场级源（封板率 / 涨停家数 / 广度）。

    源：`sentiment_pool_cache`（`stock_cache.db`；涨停 up / 炸板 zha）+ `market_stats_cache`
    （`compute_cache.db`；`ma20_ratio` 作 breadth）。任一取不到 → 对应项置 None（中性兜底）。
    失败静默（返回可用项），不阻塞 L0。
    """
    out: dict = {}
    try:
        ecm = getattr(dm, 'cache', None)
        if ecm is None:
            return out
        _pool = None
        for meth in ('get_cached_sentiment_pool', 'get_sentiment_pool'):
            fn = getattr(ecm, meth, None)
            if not callable(fn):
                continue
            try:
                _pool = fn()
            except TypeError:
                continue
            if _pool is not None and hasattr(_pool, 'empty') and not _pool.empty:
                break
        if _pool is not None and hasattr(_pool, 'columns') and 'limit_type' in _pool.columns:
            _up = int((_pool['limit_type'] == 'up').sum())
            _zha = int((_pool['limit_type'] == 'zha').sum()) if 'zha' in set(_pool['limit_type']) else 0
            if _up > 0:
                out['limit_up_count'] = _up
                if _up + _zha > 0:
                    out['sealing_rate'] = round(_up / (_up + _zha) * 100, 1)
        _fn = getattr(ecm, 'get_market_ma20_ratio', None)
        if callable(_fn):
            _r = _fn()
            if isinstance(_r, (int, float)):
                out['breadth'] = float(_r)
    except Exception as _mk_err:
        # 509号：市场情绪池读取失败 → debug 日志（原静默空 dict）
        logger.debug("市场情绪池读取失败（返回空）: %s", _mk_err)
    return out



def _dim_state_for_signal(key: str, judg: dict, sd: dict) -> str:
    """490号：dim2-dim7 引擎输出 → signal_analyzer 期望的 state（中文，契约键对齐）。

    classify_attribute 读 dims[structure/vp/chip_fund/valuation].state，判定信号属性
    （右侧确认/趋势运行/左侧试探/盘整待变）。各维 state 的真实位置与词表不同：
      structure  → judgment.structure（中文 上升/盘整/下降）
      volume_price → judgment.state（中文 五态 强健康/健康/中性/背离/严重背离）
      chip_fund  → judgment.direction（inflow/outflow/neutral → 流入/流出/中性）
      emotion    → status_description.market_phase（英文枚举 → 中文）
      risk       → judgment.risk_level / level
      valuation  → judgment.valuation_level.value（英文枚举 → 中文）
    取不到返回 ''（调用方回退「中性」）。
    """
    try:
        from app.opportunity_atlas.dim_adapter import ENGINE_STATE_TO_CN as _T
    except Exception:
        return ''
    judg = judg or {}
    sd = sd or {}
    if key == 'structure':
        return str(judg.get('structure', ''))
    if key == 'volume_price':
        return str(judg.get('state', ''))
    if key == 'chip_fund':
        return _T.get('chip_fund', {}).get(str(judg.get('direction', '')), '')
    if key == 'emotion':
        return _T.get('emotion', {}).get(str(sd.get('market_phase', '')), '')
    if key == 'risk':
        return str(judg.get('risk_level', judg.get('level', '')))
    if key == 'valuation':
        _lv = judg.get('valuation_level') or {}
        _val = _lv.get('value', '') if isinstance(_lv, dict) else ''
        return _T.get('valuation', {}).get(str(_val), '')
    return ''


class StatusEngine:
    """现状判定生产环节引擎（单只股票 evaluate，全市场由日终批量驱动）"""

    def __init__(self, dm=None):
        if dm is None:
            from app.data import DataManager
            dm = DataManager()
        self.dm = dm
        self.cfg = get_status_engine_config()
        self.registry = get_signal_registry().get('signals', {})
        # 485号（431 G1 收口）：权重矩阵迁 yaml——yaml 有值即覆盖实例属性（值不变，零行为变更）；
        # yaml 缺失/非 dict 时保留类属性兜底（与 yaml 同值）。类属性同时兼容 test_418 覆盖逻辑。
        _mrw = self.cfg.get('market_regime_weights')
        if isinstance(_mrw, dict) and _mrw:
            self.MARKET_REGIME_WEIGHTS = _mrw

    # ══════════════════════════════════════════════════════════
    # 主入口
    # ══════════════════════════════════════════════════════════

    def evaluate(self, ts_code: str, dim_results: Optional[dict] = None,
                 asof_date: Optional[str] = None) -> Optional[dict]:
        """生产环节主流程：原料 → L1 → L0 → L2 → 成品仓行

        366号步骤3：重构为调用维度引擎，通过兼容层保持下游兼容。
        370号修正：支持传入预计算的 dim_results（从 strategy_signal_detail.dim_results_json），
        跳过重复的维度引擎计算，提升JUD步骤性能。
        418号方案：jud_engine_version 配置分支（v390 新管线 / legacy 旧管线）。
        507批次7（#S6）：新增 asof_date——回测历史求值，按该日期读 pre_feat/
            signal_detail 历史快照（消除逐日调用返回同一「当前」状态的前视偏差）；
            缺省读最新（日终管道行为不变）。

        Args:
            ts_code: 股票代码
            dim_results: 预计算的维度引擎结果（可选），跳过 _build_dim_engine_results
            asof_date: 历史求值日期（YYYY-MM-DD/YYYYMMDD 兼容；可选）

        Returns: status_snapshot 行 dict（或 None 数据缺失）
        """
        tags = self._load_tags(ts_code, asof_date=asof_date)
        signals = self._load_signals(ts_code, asof_date=asof_date)
        if not tags and not signals:
            return None

        lifecycle = self._signal_lifecycle(ts_code, tags, signals, asof_date=asof_date)

        # 370号修正：优先使用预计算的维度引擎结果，避免重复计算
        if dim_results:
            dim_engine_results = dim_results
        else:
            # 366号步骤3：用维度引擎替代_build_dimensions()
            dim_engine_results = self._build_dim_engine_results(tags, signals, {}, lifecycle, ts_code=ts_code)

        # 兼容层：将维度引擎输出转为旧dims格式
        dims = self._convert_to_dims_format(dim_engine_results, tags)

        # 494号（R-1/R-9）：L0 市场级温度回升需 raw pre_feat 子组（sentiment/market_stats），
        #   由 _load_tags 同源读取并透传（`_apply_l0` 缺省时自取，此处传递避免重复读）。
        try:
            _raw_pre_feat = self.dm.cache.get_pre_feat(
                ts_code, trade_date=_norm_date(asof_date, compact=False) if asof_date else None)
        except Exception:
            _raw_pre_feat = None
        l0 = self._apply_l0(ts_code, tags, lifecycle, raw_pre_feat=_raw_pre_feat,
                            asof_date=asof_date)

        # 418号方案：jud_engine_version 配置分支（v390 新管线 / legacy 旧管线）
        _jud_ver = str((self.cfg or {}).get('jud_engine_version', 'legacy'))
        if _jud_ver == 'v390':
            l2 = self._aggregate_v390(tags, dims, l0, lifecycle, dim_engine_results, ts_code)
        else:
            l2 = self._aggregate(tags, dims, l0, lifecycle)

        # dim8 状态总结：读取 dim1-dim7 输出，组装综合报告。
        # 495号（A1/A2）：在判定（l2）**之后**调用，经 lifecycle['jud_result'] 注入判定层
        #   结果——dim8 展示层**单向消费判定权威**（v390=判定、dim8=展示派生），
        #   共识率/状态条/方向不再自算第二口径（单源化，消除矛盾组合）。
        try:
            from app.opportunity_atlas.dimensions.dim8_summary_engine import Dim8SummaryEngine
            dim8 = Dim8SummaryEngine()
            dim_engine_results['summary'] = dim8.evaluate(
                dims={}, tags=tags,
                lifecycle={'dim_results': dim_engine_results, 'jud_result': l2})
        except Exception as e:
            logger.warning(f"dim8 状态总结失败: {e}")
            dim_engine_results['summary'] = None

        hits = self._detect_registered_signals(tags, signals)

        return self._assemble(ts_code, dims, lifecycle, l0, l2, hits, dim_engine_results)

    # ══════════════════════════════════════════════════════════
    # 原料加载（存储层只读）
    # ══════════════════════════════════════════════════════════

    def _load_tags(self, ts_code: str, asof_date: Optional[str] = None) -> dict:
        """加载原料标签（357号方案：读pre_feat_cache）

        pre_feat_cache 是嵌套JSON（11组特征），需扁平化为下游期望的flat dict格式。
        P4已废弃，不再回退opportunity_tags_cache。
        507批次7（#S6）：asof_date 提供时按该日期读历史 pre_feat（回测消除前视）。
        """
        try:
            pre_feat = self.dm.cache.get_pre_feat(
                ts_code, trade_date=_norm_date(asof_date, compact=False) if asof_date else None)
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

        461-8：market_stats 组（全市场共享，非个股属性）不摊进 flat tags——
        它的真正消费方（dim5/bociasi）均经 dim1 data_context 子 dict 读取嵌套 pre_feat，
        扁平层无任何市场级键消费者，摊进会污染个股 flat 命名空间
        （如 `pe_percentile`/`rsi_percentile` 唯一来源是 market_stats 组，非个股级估值分位）。
        """
        flat = {}
        for group_name, group_data in pre_feat.items():
            if not isinstance(group_data, dict):
                continue
            # 461-8：market_stats 组跳过扁平化（全市场共享，保留在 data_context 子 dict 供 dim1/dim5/bociasi 读）
            if group_name == 'market_stats':
                continue
            for key, value in group_data.items():
                if value is not None:
                    flat[key] = value
        return flat

    def _load_signals(self, ts_code: str, asof_date: Optional[str] = None) -> dict:
        try:
            if asof_date:
                # 507批次7（#S6）：读该日期 strategy_signal_detail 历史快照
                cached = self.dm.cache.get_signal_detail(
                    ts_code, trade_date=_norm_date(asof_date, compact=True))
            else:
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
                return ('背离', ['顶背离（MACD未创新高）' if macd_ok else '顶背离（量缩，未MACD确认）'], conf)
            # bottom 底背离：知识库=看多反转，非"背离/看空"
            return ('健康', ['底背离（下跌衰竭，反转信号）'], conf)

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
                                   dims: dict, lifecycle: Optional[dict] = None,
                                   ts_code: str = None) -> dict:
        """411号方案Phase 4：重构维度引擎调用流程

        新流程：
        1. dim1数据门禁（独立调用）→ 获取data_context
        2. dim2-dim7执行（注入data_context）
        3. signal_analyzer信号分析（依赖dim2-dim7输出）

        Returns:
            {'signal': {...}, 'structure': {...}, 'volume_price': {...},
             'chip_fund': {...}, 'emotion': {...}, 'risk': {...}, 'valuation': {...}}
        """
        results = {}

        # Step 1: dim1数据门禁（独立调用，获取data_context）
        data_context = None
        try:
            from app.opportunity_atlas.dimensions.dim1_signal_engine import Dim1SignalEngine
            dim1_engine = Dim1SignalEngine()
            # 419号方案：显式传 ts_code（tags 扁平化后无此键）
            dim1_result = dim1_engine.evaluate(dims, tags, signals, lifecycle, ts_code=ts_code)
            results['signal'] = dim1_result
            data_context = dim1_result.get('data_context')
        except Exception as e:
            logger.warning(f"dim1数据门禁调用失败: {e}")
            results['signal'] = None

        # Step 2: dim2-dim7执行（注入data_context）
        engine_map = {
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
                # 411号Phase 4：注入data_context参数（默认值None，兼容旧调用）
                # 442号缺陷①：tags（pre_feat扁平化）无 ts_code 键，dim2-dim7 内部均 tags.get('ts_code')
                #   → 显式注入，对齐 dim1 的 419号 ts_code 传递（否则 ts_code 相关分支全部跳过）
                _tags_for_dims = dict(tags)
                if ts_code:
                    _tags_for_dims['ts_code'] = ts_code
                results[dim_name] = engine.evaluate(dims, _tags_for_dims, signals, lifecycle,
                                                    data_context=data_context)
            except Exception as e:
                logger.warning(f"维度引擎 {dim_name} 调用失败: {e}")
                results[dim_name] = None

        # Step 3: signal_analyzer信号分析（依赖dim2-dim7输出）
        # 用classify_attribute等函数替代原dim1的分析功能
        signal_analysis = None
        try:
            from app.opportunity_atlas.signal_analyzer import analyze_signal
            # 构建dims格式（从dim2-dim7结果提取）
            # 490号（B 类修正：形态错位）：原实现取「judgment 中第一个 dict 型值的 value」作 state，
            #   而 dim2/3/5/6 的 judgment 全为标量（仅 dim7 是嵌套 dict）→ 除 valuation 外 state
            #   恒「中性」，classify_attribute 收到的 structure/chip_fund/risk 全为中性 → 信号属性
            #   恒 neutral（signal_confirm 恒"中性观望"）。改为按各维真实契约键显式取 state。
            dims_for_signal = {}
            for key in ['structure', 'volume_price', 'chip_fund', 'emotion', 'risk', 'valuation']:
                r = results.get(key)
                if r and isinstance(r, dict):
                    judg = r.get('judgment', {}) or {}
                    sd = r.get('status_description', {}) or {}
                    state_val = _dim_state_for_signal(key, judg, sd) or '中性'
                    # 键契约对齐：signal_analyzer（411迁移自 dim1）期望旧键 vp，
                    # dim3 现产 volume_price——映射回 vp，避免共振键错位（vp 恒缺→共振恒 25 分）。
                    _sig_key = 'vp' if key == 'volume_price' else key
                    dims_for_signal[_sig_key] = {
                        'state': state_val,
                        'confidence': judg.get('continuous_value', 0.5),
                    }
            # factor 维无独立引擎（359 §1.4 四维共振之一），沿用旧契约中性常量兜底
            dims_for_signal.setdefault('factor', {'state': '中性', 'confidence': 0.5})
            signal_analysis = analyze_signal(dims_for_signal, tags, lifecycle or {})
            results['signal_analysis'] = signal_analysis

            # 418号方案Step 1：signal判定结果并入results['signal']，
            # 修复JUD消费链键名错位（dim_adapter/reliability_assessor/dim8读取'signal'键）。
            # results['signal']仍保留dim1门禁结果（data_context/status_quality），
            # 叠加signal_analysis的status_description/judgment/audit子结构。
            if signal_analysis and isinstance(signal_analysis, dict):
                _sig = results.get('signal') or {}
                if isinstance(_sig, dict):
                    results['signal'] = {**_sig, **signal_analysis}
                else:
                    results['signal'] = signal_analysis
        except Exception as e:
            logger.warning(f"signal_analyzer调用失败: {e}")
            results['signal_analysis'] = None

        return results

    def _convert_to_dims_format(self, dim_results: dict, tags: dict) -> dict:
        """366号步骤3：将维度引擎输出转为旧dims格式，保持下游兼容

        411号方案Phase 2：signal_confirm由classify_attribute()分析结果生成，
        替代原tags.right_side_confirm路径。

        Args:
            dim_results: 维度引擎的输出结果
            tags: 原始标签数据

        Returns:
            与旧_build_dimensions()输出格式兼容的dims字典
        """
        dims = {}
        # 490号（B 类修正：键名/形态错位）：本方法此前按旧键读 judgment（vp_state/flow_direction/
        # phase），而 dim3/dim4/dim5 的真实键分别是 judgment.state / judgment.direction（phase 为英文
        # 枚举）、sd.market_phase → 量价/筹码/情绪三维 state 恒默认值。此处对齐真实键 + 英文转中文。
        from app.opportunity_atlas.dim_adapter import ENGINE_STATE_TO_CN as _T

        # 439-A-1：灯色改由派生 SSOT 计算（不再读各维自产 judgment.light/overall_light）
        from app.opportunity_atlas.light_derive import dim_light as _dl

        # 结构维：从dim2_structure_engine输出提取
        s = dim_results.get('structure')
        if s and isinstance(s, dict):
            judg = s.get('judgment', {})
            _sd = s.get('status_description', {}) or {}
            # plain 已删除（dim8 唯一叙事口径）：evidence 改取结构维结构化详情
            _ev = _sd.get('vs_ma') or _sd.get('vs_zhongshu') or _sd.get('vs_support_resistance') or ''
            dims['structure'] = {
                'state': judg.get('structure', tags.get('state_label', '盘整')),
                'light': _dl(dim_results, 'structure'),
                'confidence': 0.7,
                'evidence': [_ev] if _ev else [],
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
            _vp_sd = vp.get('status_description', {}) or {}
            dims['vp'] = {
                # 490号：dim3 五态在 judgment.state（原读 judgment.vp_state 恒缺 → 恒"中性"）
                'state': judg.get('state') or _vp_sd.get('vp_state') or '中性',
                'light': _dl(dim_results, 'volume_price'),
                'confidence': 0.6,
                'evidence': [],
            }
        else:
            dims['vp'] = {'state': '中性', 'light': 'yellow', 'confidence': 0.5, 'evidence': []}

        # 筹码维
        cf = dim_results.get('chip_fund')
        if cf and isinstance(cf, dict):
            judg = cf.get('judgment', {})
            # 490号：资金方向枚举在 judgment.direction（inflow/outflow/neutral）；
            # 原读 judgment.flow_direction（不存在）→ 恒"中性"。此处取 direction 以对齐
            # 本模块 _DIM_DIRECTION['chip_fund']（流入/中性/流出）与 classify_attribute 的口径。
            _cf_dir = str(judg.get('direction', ''))
            dims['chip_fund'] = {
                'state': _T.get('chip_fund', {}).get(_cf_dir, _cf_dir or '中性'),
                'light': _dl(dim_results, 'chip_fund'),
                'confidence': 0.5,
                'evidence': [],
            }
        else:
            dims['chip_fund'] = {'state': '中性', 'light': 'yellow', 'confidence': 0.5, 'evidence': []}

        # 情绪维
        em = dim_results.get('emotion')
        if em and isinstance(em, dict):
            judg = em.get('judgment', {})
            _emo_sd = em.get('status_description', {}) or {}
            # 490号：情绪阶段枚举在 sd.market_phase（ice/sprout/ferment/climax/ebb/regression/neutral）；
            # 原读 judgment.phase（不存在）→ 恒"正常"
            _emo_phase = str(_emo_sd.get('market_phase', ''))
            dims['emotion'] = {
                'state': _T.get('emotion', {}).get(_emo_phase, _emo_phase or '正常'),
                'light': _dl(dim_results, 'emotion'),
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
                'light': _dl(dim_results, 'risk'),
                'confidence': 0.6,
                'evidence': [],
            }
        else:
            dims['risk'] = {'state': '中', 'light': 'yellow', 'confidence': 0.5, 'evidence': []}

        # 补充旧体系需要的其他维度（490号：优先取 dim7 引擎结论，缺失回退 tags）
        _val_judg = (dim_results.get('valuation') or {}).get('judgment', {}) or {}
        _val_lv = _val_judg.get('valuation_level') or {}
        _val_en = str(_val_lv.get('value', '')) if isinstance(_val_lv, dict) else ''
        _fh = _val_judg.get('fina_health') or {}
        _fh_en = str(_fh.get('value', '')) if isinstance(_fh, dict) else ''
        dims['valuation'] = {
            'state': _T.get('valuation', {}).get(_val_en) or tags.get('valuation_level', '合理'),
            'light': 'yellow',
            'confidence': 0.5,
            'evidence': [],
        }
        dims['finance'] = {
            'state': _T.get('finance', {}).get(_fh_en) or tags.get('fina_health', '关注'),
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

        # 411号Phase 2：signal_confirm由classify_attribute()分析结果生成
        # 替代原tags.right_side_confirm路径
        try:
            # 439-A-1：灯色由派生 SSOT 计算（原 signal_analyzer.LIGHT_MAP 已随灯色迁出 SIG）
            from app.opportunity_atlas.light_derive import derive_light as _pl
            from app.opportunity_atlas.signal_analyzer import classify_attribute
            lifecycle_data = {}
            attr_result = classify_attribute(dims, tags, lifecycle_data)
            attr_code = attr_result.get('code', 'neutral')
            dims['signal_confirm'] = {
                'state': attr_result.get('name', '中性观望'),
                'light': _pl('signal', attr_code),
                'confidence': 0.6,
                'evidence': [attr_result.get('detail', '')],
            }
        except Exception:
            # 降级：回退到tags.right_side_confirm
            dims['signal_confirm'] = {
                'state': tags.get('right_side_confirm', '未确认'),
                'light': 'yellow',
                'confidence': 0.5,
                'evidence': [],
            }

        return dims

    # 信号生命周期（334号 §5.3：active_signal + 当前价 → 初期/中期/已延伸）
    # ══════════════════════════════════════════════════════════

    def _signal_lifecycle(self, ts_code: str, tags: dict, signals: dict,
                          asof_date: Optional[str] = None) -> Optional[dict]:
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
            if asof_date:
                # 507批次7（#S6）：历史求值用截至该日的收盘价（回测消除前视）
                if 'trade_date' not in df.columns:
                    return None
                _sub = df[df['trade_date'].astype(str).str[:10] <= str(asof_date)[:10]]
                if _sub.empty:
                    return None
                price = float(_sub['close'].iloc[-1])
            else:
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

    def _apply_l0(self, ts_code: str, tags: dict, lifecycle: Optional[dict],
                  raw_pre_feat: dict = None, asof_date: Optional[str] = None) -> dict:
        """L0 风险分级（335号：L0a 硬否决 / L0b 软约束 / L0c 持有期）。

        492号（P1-4）：原第 3 形参 `dims` 实测**从未被使用**（判定全部读 tags +
        daily_basic）——L0 在 dim 引擎之后生成（T42 时序，见 dim6_risk_engine:202），
        与 dims 无因果关系。移除该形参，消除「L0 依赖维度判定」的误导。

        509号 #J11：新增 asof_date——回测历史求值（507批次7 #S6 引入 asof_date 后，
        L0 内部回退读 get_pre_feat/get_cached_daily_basic 仍读最新，致情绪上限/流动性
        L0b 引入前视偏差）；asof_date 提供时按该日期读历史快照。
        """
        l0: dict[str, Any] = {
            'hard_veto': False, 'hard_reason': '',
            'soft_risks': [], 'position_coeff': 1.0,
            'hold_only': False,
        }
        _l0_cfg = self.cfg.get('l0', {}) or {}
        # L0a 硬否决（不可逆：命中 yaml l0.hard_risks 登记项，如监管立案）
        ce = str(tags.get('catalyst_event', ''))
        if ce in (_l0_cfg.get('hard_risks') or ['regulatory']):
            l0['hard_veto'] = True
            l0['hard_reason'] = '监管立案（L0a 硬否决）' if ce == 'regulatory' else f'L0a 硬否决：{ce}'
        # L0a 硬否决（448号 PIERS 永久黑名单）：直读 event_details.event_type，不依赖 catalyst_event 单值
        # （catalyst_event 取 |direction| 最大事件，fraud_sign=-2 常被 breakout/regulatory 等覆盖 → 单值标签不可靠）
        _hard_labels = {
            'fraud_sign': '财务造假/重大财务异常（L0a 硬否决）',
            'delist_risk': '退市风险（L0a 硬否决）',
            # 453号：st_warning 仅在 direction<=-2（*ST/退市整理）时硬否决，普通 ST（=-1）走 L0b 软风险
            'st_warning': 'ST/退市整理（L0a 硬否决）',
        }
        _st_extreme_dir = -2
        if not l0['hard_veto']:
            _ev_details = tags.get('event_details')
            if isinstance(_ev_details, list):
                _hit = None
                for e in _ev_details:
                    if not isinstance(e, dict):
                        continue
                    _et = str(e.get('event_type', ''))
                    if _et not in _hard_labels:
                        continue
                    # 509号 #J10：direction 非数值（'st'/'' 等）时 int() 抛 ValueError 会
                    #   中断整个 _apply_l0（硬否决/软风险/仓位上限全失）；对齐下方 ST 块
                    #   的 try 守卫——非数值按 0 处理（不触发 ST 特判）。
                    try:
                        _e_dir = int(e.get('direction', 0))
                    except (TypeError, ValueError):
                        _e_dir = 0
                    if _et == 'st_warning' and _e_dir > _st_extreme_dir:
                        continue  # 普通 ST 不进硬否决
                    _hit = e
                    break
                if _hit:
                    l0['hard_veto'] = True
                    l0['hard_reason'] = _hard_labels[str(_hit.get('event_type'))]
        # L0b 软约束（可逆：仓位系数，对齐 cross_validate._evaluate_gate）
        coeff = _l0_cfg.get('soft_risk_coeff', {})
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
            # 509号 #J11：asof_date 提供时按该日期读（回测无前视）
            _basic_kw = {}
            if asof_date:
                _basic_kw['end_date'] = _norm_date(asof_date, compact=False)
            df = self.dm.get_cached_daily_basic(ts_code, **_basic_kw)
            if df is not None and not df.empty and 'turnover_rate' in df.columns:
                tr = df['turnover_rate'].dropna()
                if not tr.empty and float(tr.iloc[-1]) < 1.0:
                    l0['soft_risks'].append('low_liquidity')
                    l0['position_coeff'] *= float(coeff.get('low_liquidity', 0.7))
        except Exception:
            pass
        # 453号：普通 ST（direction=-1）未硬否决者 → L0b 软风险（仓位压制；*ST/退市整理已硬否决，不过此分支）
        if not l0['hard_veto']:
            try:
                _st = next((e for e in (tags.get('event_details') or []) if isinstance(e, dict)
                            and str(e.get('event_type', '')) == 'st_warning'), None)
                if _st is not None and int(_st.get('direction', 0)) == -1:
                    l0['soft_risks'].append('st_warning')
                    l0['position_coeff'] *= float(coeff.get('st_warning', 0.8))
            except (TypeError, ValueError):
                pass
        # L0b2 情绪周期总仓位上限（387号§5.4；消费方 advice_engine Step 3）
        # 492号（K2）：改读归一化情绪阶段——原读 tags['emotion_phase']（无生产者）恒 normal
        # 493号（P2-c）：新增「冰点末期」——冰点期（ice）仓位上限 0.10 仅在**情绪未回升**时生效；
        #   若市场级情绪已转出冰点（回升信号）→ 放开至正常档，对齐知识库《华泰A股情绪指数》
        #   「回归10%之上再买入（右侧确认）」。详见 _emotion_is_recovering。
        _caps = _l0_cfg.get('emotion_position_cap', {})
        if _caps:
            _phase = _normalize_emotion_phase(tags)
            _rec = False
            if _phase == 'ice':
                # 494号（R-1）：gate 用**市场级**温度回升；raw pre_feat 无市场级输入时，
                #   直读 sentiment_pool_cache/market_stats_cache（封板率/涨停家数/广度）兜底。
                if not isinstance(raw_pre_feat, dict):
                    try:
                        # 509号 #J11：asof_date 提供时按该日期读历史 pre_feat（无前视）
                        _raw = self.dm.cache.get_pre_feat(
                            ts_code,
                            trade_date=_norm_date(asof_date, compact=False) if asof_date else None)
                        raw_pre_feat = _raw if isinstance(_raw, dict) else None
                    except Exception:
                        raw_pre_feat = None
                _rec = _emotion_is_recovering(tags, raw_pre_feat)
                if not _rec:
                    _mi = _market_level_inputs_via_dm(getattr(self, 'dm', None))
                    if _mi.get('limit_up_count') is not None or _mi.get('breadth') is not None:
                        _t = tags if not isinstance(tags, dict) else dict(tags)
                        for _k in ('limit_up_count', 'sealing_rate', 'breadth'):
                            if _mi.get(_k) is not None:
                                _t[_k] = _mi[_k]
                        _rec = _emotion_is_recovering(_t, raw_pre_feat)
            if _phase == 'ice' and _rec:
                l0['emotion_phase'] = 'ice_recovering'      # 冰点末期（区分标记）
                l0['emotion_position_cap'] = float(
                    _caps.get('recovery', _caps.get('normal', 0.6)))
                l0['emotion_recovering_basis'] = (
                    f"市场级温度回升≥{ICE_RECOVERY_TEMP:.0f}"
                    f"（个股右侧确认={tags.get('right_side_confirm', '') or '无'}，仅附注）")
            else:
                l0['emotion_position_cap'] = float(_caps.get(_phase, _caps.get('normal', 0.6)))
        else:
            # 507批次5 #S29：yaml 缺 emotion_position_cap 时原不产 l0 键 → 下游 advice_engine
            #   `l0.get('emotion_position_cap')` 得 None（非默认 0.6）；补显式默认键防缺口
            l0['emotion_position_cap'] = 0.6
        # L0c 持有期（阶段登记于 yaml l0.hold_only_stages → 只可持有、不新开仓）
        _hold_stages = _l0_cfg.get('hold_only_stages') or ['已延伸']
        if lifecycle and lifecycle['stage'] in _hold_stages:
            l0['hold_only'] = True
        return l0

    # ══════════════════════════════════════════════════════════
    # L2 聚合（336号：维度共识 + conflict_evidence + opportunity_state）
    # 370号S7：P3动态权重（MARKET_REGIME_WEIGHTS 矩阵替代等权投票）
    # ══════════════════════════════════════════════════════════

    # 358号§5.1 市场状态×维度权重矩阵
    # 431号 G1 标注（批次13，2026-09-13）+ 485号收口（2026-09-26）：本矩阵已迁入
    # status_engine.yaml `market_regime_weights` 段（值逐字节不变）——此处为**类属性兜底**，
    # 仅当 yaml 缺失/非 dict 时生效（__init__ 有 cfg 则覆盖实例属性）。
    # 消费于 StatusEngine._aggregate 与 _aggregate_v390
    # （`weights = self.MARKET_REGIME_WEIGHTS.get(regime, ...)`）。
    # weight_engine.py 的 STATIC_WEIGHTS 死码孪生已随 485-1 删除（该模块零消费方）。
    # 调整权重取值属「果」侧判定，445 冻结，留待 JUD 阶段（485-5）。
    MARKET_REGIME_WEIGHTS = {
        'trending_up':    {'signal': 0.15, 'structure': 0.20, 'vp': 0.15, 'chip_fund': 0.10, 'emotion': 0.10, 'risk': 0.15, 'valuation': 0.15},
        'ranging':        {'signal': 0.10, 'structure': 0.15, 'vp': 0.20, 'chip_fund': 0.10, 'emotion': 0.10, 'risk': 0.20, 'valuation': 0.15},
        'trending_down':  {'signal': 0.10, 'structure': 0.10, 'vp': 0.10, 'chip_fund': 0.10, 'emotion': 0.10, 'risk': 0.30, 'valuation': 0.20},
        'extreme_panic':  {'signal': 0.05, 'structure': 0.05, 'vp': 0.05, 'chip_fund': 0.10, 'emotion': 0.10, 'risk': 0.40, 'valuation': 0.25},
    }

    @staticmethod
    def _detect_market_regime(tags: dict, dims: dict) -> str:
        """市场状态推导（370号 S7；493号 P2-g 基准修正）。

        493号 P2-g 实测：原实现的 `tags['status_bar']` 分支**恒不可达**（RAW 扁平层
        无该键 = 0/300 样本；`status_bar` 是 status_snapshot 成品列，不回灌 tags）；
        300 只实测 regime 仅 ranging 65.3% / trending_down 34.7%，**trending_up 与
        extreme_panic 恒 0** → MARKET_REGIME_WEIGHTS 实为 2 档。

        修正基准（用户拍板，依据 Wiki《市场状态感知因子》：个股信号与**市场级状态信号**
        耦合；《情绪周期-仓位联动》五阶段表：萌芽 30%/发酵 60%/高潮 80% 属上升参与期、
        退潮 ≤30% 防守、冰点 10%/空仓）：
          市场级 `market_emotion`（情绪周期六段论）→ regime
            萌芽/发酵/高潮 → trending_up（做多参与期，结构/量价权重高）
            退潮          → trending_down（防守，风险权重高）
            冰点          → extreme_panic（极端恐慌，风险权重最高）
            回归/正常/未知 → 个股/维度回退
        注意：须用**市场级** `market_emotion`，非个股 `stock_emotion`（后者恒 neutral）。
        缺失时回退原「dim5 引擎结论 → risk 维度 → 默认震荡」链（对齐「不额外引入
        大盘级数据源」约束：只用已存在的 tags 键）。
        """
        # 1) 市场级情绪阶段（真实生产者；旧 status_bar 分支已废弃移除）
        _mkt = str(tags.get('market_emotion', '') or '').lower()
        if _mkt in ('sprout', 'ferment', 'climax', '萌芽', '发酵', '高潮'):
            return 'trending_up'
        if _mkt in ('ebb', '退潮'):
            return 'trending_down'
        if _mkt in ('ice', '冰点'):
            return 'extreme_panic'
        # 2) 回退：dim5 引擎结论（实时可达；存量 dim_results 缺 market_phase 时为空）
        emotion_state = str(dims.get('emotion', {}).get('state', ''))
        if '高潮' in emotion_state:
            return 'trending_up'
        if '退潮' in emotion_state:
            return 'trending_down'
        if '冰点' in emotion_state:
            return 'extreme_panic'
        # 3) 回退：从risk维度推导
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
            # 509号 #J9：平票（bull==bear>0）判 neutral 而非 bearish
            #   （原首分支 `'bearish' if bull > bear else 'bearish'` 平票恒判空头；
            #   且下方 `elif bull == bear and bull > 0` 因前序 total_w>0 恒先命中而不可达）
            direction = 'bullish' if bull > bear else ('bearish' if bear > bull else 'neutral')
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

    def _aggregate_v390(self, tags: dict, dims: dict, l0: dict, lifecycle: Optional[dict],
                        dim_results: dict, ts_code: str) -> dict:
        """390号方案 v390 多因子决策管线（L1-L6）

        由 evaluate() 在 jud_engine_version == 'v390' 时调用。
        逐层 try/except 降级，单层失败不中断管道。
        """
        from app.opportunity_atlas.advice_engine import compute_advice
        from app.opportunity_atlas.conflict_matrix import detect as conflict_detect
        from app.opportunity_atlas.consensus_engine import compute as consensus_compute
        from app.opportunity_atlas.dim_adapter import convert_to_factors
        from app.opportunity_atlas.factor_arbiter import arbitrate as factor_arbitrate
        from app.opportunity_atlas.reliability_assessor import assess

        dim_results = dim_results or {}

        # L1: 维度因子提取
        try:
            dims_factor = convert_to_factors(dim_results, tags)
        except Exception as e:
            logger.warning("v390 L1 convert_to_factors失败: %s", e)
            dims_factor = {}

        # L2: 可靠性评估
        try:
            reliability = assess(dims_factor, dim_results)
        except Exception as e:
            logger.warning("v390 L2 reliability评估失败: %s", e)
            reliability = {}

        # L3: 共识聚合（weights 取 MARKET_REGIME_WEIGHTS[regime]）
        regime = self._detect_market_regime(tags, dims)
        weights = self.MARKET_REGIME_WEIGHTS.get(regime, self.MARKET_REGIME_WEIGHTS['ranging'])
        # 492号（K3）：情绪阶段经归一化 SSOT（读 sentiment_phase，sprout/ferment 就近归并）
        emotion_phase = _normalize_emotion_phase(tags)
        try:
            consensus = consensus_compute(dims_factor, reliability, weights, emotion_phase)
        except Exception as e:
            logger.warning("v390 L3 consensus失败: %s", e)
            consensus = {'consensus_rate': 0.0, 'raw_consensus_rate': 0.0,
                         'reliability_factor': 0.0, 'direction': 'neutral',
                         'bull_score': 0.0, 'bear_score': 0.0, 'group_details': {}}

        # L4: 冲突检测
        try:
            conflict = conflict_detect(dims_factor, tags, dim_results,
                                       consensus.get('consensus_rate', 0.0))
        except Exception as e:
            logger.warning("v390 L4 conflict检测失败: %s", e)
            conflict = {'fatal_to_veto': [], 'warn_for_semantic': [],
                        'semantic_type': '', 'semantic_adjustment': 1.0, 'all_conflicts': []}

        # ⚡ 硬否决检查（对齐 legacy _aggregate 行为）
        if l0.get('hard_veto'):
            return self._v390_result('avoid', [l0.get('hard_reason', 'L0a 硬否决')],
                                     consensus, conflict, 0.0, reliability)

        # ⚡ L4 致命冲突 → wait
        if conflict.get('fatal_to_veto'):
            return self._v390_result('wait', conflict['fatal_to_veto'],
                                     consensus, conflict, 30.0, reliability)

        # L5: 多因子仲裁
        # 494号（R-2/R-10）：周线（背景周期）方向须从 dim_results（dim2 多级别联立）取——
        #   主链 tags 来自 pre_feat、不含 multi_level（实证命中 0/600），故不能读 tags。
        try:
            from app.opportunity_atlas.dim_adapter import weekly_direction_from_dim_results
            _weekly_dir = weekly_direction_from_dim_results(dim_results)
        except Exception:
            _weekly_dir = ''
        try:
            arb_result = factor_arbitrate(consensus, conflict, tags, dims_factor,
                                          reliability, weekly_direction=_weekly_dir)
        except Exception as e:
            logger.warning("v390 L5 factor仲裁失败: %s", e)
            arb_result = {'opportunity_state': 'wait', 'final_score': 50.0,
                          'state_evidence': ['L5仲裁不可用'], 'conflict_evidence': []}

        # L6: 操作建议
        advice = {}
        try:
            # 492号（K1）：entry_price 供 2% 风险预算仓位使用。优先 dim_results['daily_df']，
            #   回退 self.dm 日线缓存（与 :560 同源；不读分库表，避免被 daemon 写锁阻塞）。
            entry_price = None
            daily = dim_results.get('daily_df')
            if not (hasattr(daily, 'empty') and not daily.empty and 'close' in daily.columns):
                try:
                    daily = self.dm.get_cached_daily_data(ts_code)
                except Exception:
                    daily = None
            if hasattr(daily, 'empty') and not daily.empty and 'close' in daily.columns:
                entry_price = float(daily['close'].iloc[-1])
            advice = compute_advice(arb_result.get('final_score', 50.0), dims_factor,
                                    l0, dim_results, ts_code, entry_price)
        except Exception as e:
            logger.debug("v390 L6 advice失败: %s", e)

        return self._v390_result(arb_result.get('opportunity_state', 'wait'),
                                 arb_result.get('state_evidence', []),
                                 consensus, conflict,
                                 arb_result.get('final_score', 50.0), reliability,
                                 advice=advice)

    @staticmethod
    def _v390_result(state: str, evidence: list, consensus: dict, conflict: dict,
                     final_score: float, reliability: dict, advice: dict = None) -> dict:
        """v390 输出组装（兼容 _assemble 消费的 l2 结构 + 390号新增字段）"""
        return {
            'opportunity_state': state,
            'state_evidence': evidence,
            'consensus_rate': consensus.get('consensus_rate', 0.0),
            'direction': consensus.get('direction', 'neutral'),
            'bullish_dims': consensus.get('bull_score', 0.0),
            'bearish_dims': consensus.get('bear_score', 0.0),
            'conflict_evidence': conflict.get('all_conflicts', [])[:8],
            # 390号新增字段
            'final_score': final_score,
            'semantic_type': conflict.get('semantic_type', ''),
            'reliability_summary': reliability,
            'consensus_detail': consensus.get('group_details', {}),
            'advice': advice or {},
        }

    def _detect_registered_signals(self, tags: dict, signals: dict) -> list:
        """334号 §5：信号注册表触发检测（5 类信号 → 触发列表，供七维模板①信号确认）

        signal_registry.yaml 登记触发条件（此处为判定实现；验证条件=N 日站稳由
        signal_records 回算分群验证——334 §6 校准机制）。

        491号（R4-②/B）：411号 Phase 1 后 signal_json.signals 恒空（设计），原 vp 分支读
        signals['量价分析策略'].signal_label → 恒失效。改读活 tags（334 §5.2「引用现有标签」）：
        pattern_signal 含突破=已突破且为「预涨型」（EnhancedPatternDetector 预跌型优先）；
        突破前60日高点用 shared_support_resistance.signal_days（站上前60日高点后天数）；
        量比用 volume_price.volume_ratio。仅 volume_breakout 原走废弃容器，其余 4 类本就读 tags。
        """
        hits: list[dict] = []
        bsp = str(tags.get('buy_sell_point', ''))
        if '三买' in bsp or 'third_buy' in bsp:
            hits.append({'type': 'chan_third_buy', 'name': '缠论三买', 'source': 'buy_sell_point'})
        # volume_breakout：放量突破（334 §5.2：pattern_signal=突破 + 量比≥1.5 + 突破前高）
        if '突破' in str(tags.get('pattern_signal', '')):
            try:
                _vr = float(tags.get('volume_ratio') or 0)
            except (TypeError, ValueError):
                _vr = 0.0
            try:
                _sd = int(tags.get('signal_days') or 0)
            except (TypeError, ValueError):
                _sd = 0
            if _vr >= 1.5 and _sd > 0:
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
        """364a Phase 1：status_bar 5态扩展（493号 P2-a：reduce 档归入「风险区」）"""
        green = sum(1 for d in dims.values() if d.get('light') == 'green')
        red = sum(1 for d in dims.values() if d.get('light') == 'red')
        l0 = l0 or {}
        # 优先级1：不可交易
        if state == 'avoid':
            return '不可交易'
        # 优先级2：风险区（硬否决 / 红灯>=6 / 减仓档）
        if l0.get('hard_veto') or red >= 6 or state == 'reduce':
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

    def _status_bar_v390_or_legacy(self, l2: dict, dims: dict, l0: dict) -> str:
        """497号（批次4，P5）：status_bar 单源化——优先由判定层（v390）派生中文展示态。

        与 dim8 展示层同源（`_derive_status_bar_v390` + `STATUS_BAR_STATES` 中文映射），
        消除「快照 legacy 5 态」与「dim8 派生 8 态」双口径并存（492 P2 的最后一处残留）。
        legacy 路径（l2 无 final_score 键）或派生失败 → 回退 legacy `_status_bar` 自算。
        """
        try:
            if 'final_score' in l2:  # v390 特有键（_v390_result）
                from app.opportunity_atlas.dimensions.dim8_summary_engine import (
                    STATUS_BAR_STATES,
                    _derive_status_bar_v390,
                )
                _bar = _derive_status_bar_v390(l2)
                if _bar:
                    return STATUS_BAR_STATES.get(_bar, _bar)
        except Exception:
            pass
        return self._status_bar(dims, l2['opportunity_state'], l0)

    def _assemble(self, ts_code: str, dims: dict, lifecycle: Optional[dict],
                  l0: dict, l2: dict, hits: Optional[list] = None,
                  dim_engine_results: Optional[dict] = None) -> dict:
        # 337号 §6.2：建议规则参数（套算输入——仓位上限经 L0 系数、持有期限制、软风险）
        # 493号 P2-a：wait（45-64 持有观望）维持 0.2；reduce（30-44 减仓）新开仓 0
        _state = l2['opportunity_state']
        _base = 0.6 if _state in ('enter', 'light') else (0.2 if _state == 'wait' else 0.0)
        advice_params = {
            'max_position_ratio': round(_base * l0['position_coeff'], 2),
            'hold_only': l0['hold_only'],
            'soft_risks': l0['soft_risks'],
            'hard_veto': l0['hard_veto'],
        }
        # 493号（P2-d）：账户级月度风险预算状态（月度 6% / 连亏 3 笔）——**只读** daemon 预计算
        #   快照（<DATA_DIR>/account_risk_status.json），仅产出标记字段供前端/消费方，
        #   **本批不改 opportunity_state/仓位**（用户 2026-09-28 拍板「仅产出标记字段」）。
        _mrs = get_account_risk_status(cfg=getattr(self, 'cfg', None))
        advice_params['monthly_halt'] = _mrs.get('monthly_halt', False)
        advice_params['monthly_loss_pct'] = _mrs.get('monthly_loss_pct', 0.0)
        advice_params['consecutive_losses'] = _mrs.get('consecutive_losses', 0)
        result = {
            'ts_code': ts_code,
            'dim_states': json.dumps(dims, ensure_ascii=False),
            'status_bar': self._status_bar_v390_or_legacy(l2, dims, l0),
            'opportunity_state': l2['opportunity_state'],
            'state_evidence': json.dumps(l2['state_evidence'], ensure_ascii=False),
            'conflict_evidence': json.dumps(l2['conflict_evidence'], ensure_ascii=False),
            'consensus_rate': l2['consensus_rate'],
            'direction': l2['direction'],
            'l0': json.dumps(l0, ensure_ascii=False),
            'lifecycle': json.dumps(lifecycle, ensure_ascii=False) if lifecycle else None,
            'advice_params': json.dumps(advice_params, ensure_ascii=False),
            # 493号（P2-d）：账户月度风险标记（顶层便捷字段；同 advice_params 同源）
            'monthly_halt': _mrs.get('monthly_halt', False),
            'monthly_loss_pct': _mrs.get('monthly_loss_pct', 0.0),
            'consecutive_losses': _mrs.get('consecutive_losses', 0),
            # 492号（P1-3）：注册表触发列表。此前仅落库、无任何消费方（P4）；
            #   现作为 status_verdict 只读字段接前端（同一 status_row，不再额外查询）。
            'signals': json.dumps(hits or [], ensure_ascii=False),  # 334号 §5：注册表触发列表
        }
        # 365号批次C：维度引擎结果附加字段
        if dim_engine_results:
            result['dim_engine_results'] = json.dumps(dim_engine_results, ensure_ascii=False, default=str)

        # 418号方案：v390 路径追加 390号 新字段（仅新增，不改旧键）
        if 'final_score' in l2:
            result['final_score'] = l2['final_score']
            result['semantic_type'] = l2.get('semantic_type', '')
            result['reliability_summary'] = json.dumps(
                l2.get('reliability_summary', {}), ensure_ascii=False, default=str)
            result['consensus_detail'] = json.dumps(
                l2.get('consensus_detail', {}), ensure_ascii=False, default=str)
            # L6 advice 参数并入 advice_params（保持 337号 键名兼容）
            _advice = l2.get('advice') or {}
            if _advice:
                # 509号 #J12：advice_params 落库内容异常（非 JSON）时 json.loads 抛错
                #   会中断整个 _assemble（丢 status_snapshot 行）；防御解析失败则重建空 dict。
                try:
                    _ap = json.loads(result['advice_params']) if result.get('advice_params') else {}
                except (TypeError, ValueError):
                    _ap = {}
                    logger.warning("advice_params 非 JSON（ts_code=%s），已重建", ts_code)
                _ap.update({k: v for k, v in _advice.items()
                            if k in ('max_position_ratio', 'stop_loss_price', 'target_price',
                                     'risk_reward_ratio', 'invalidation_conditions',
                                     # 492号（K4/K1）：L6 已产出的入场/目标区间与 2% 风险预算
                                     #   仓位，原白名单漏收 → advice_params 落库缺失
                                     'entry_zone', 'target_zone', 'risk_budget_position',
                                     # 494号（R-4）：L6 已产出的止损来源与 50/30/20 分批止盈
                                     #   原白名单漏收 → advice_params 落库缺失
                                     'profit_tiers', 'stop_loss_basis')})
                result['advice_params'] = json.dumps(_ap, ensure_ascii=False, default=str)
        return result


def apply_advice_params(params: dict, price: Optional[float],
                        df=None, rr_gate: float = 2.0) -> dict:
    """337号 §6.3：实时操作建议轻量套算（日频成品 advice_params + 现价）

    套算 = 盈亏比门禁 + L0 软风险仓位（不含完整 K 线重算）；
    止损位（结构位）由调用方从 K 线提供（advice_builder._geometric 同源）。

    493号（P2-b）：rr_gate 默认 1.0 → 2.0（知识库《R-R筛选规则》「R:R<2:1 直接放弃」，
    与 dim6 稽核门槛「盈亏比≥2R」及 advice_engine.RR_GATE 对齐）。
    """
    if not params:
        return {'state': 'wait', 'max_position_ratio': 0.0, 'reason': '无建议参数'}
    state = 'enter' if params.get('max_position_ratio', 0) > 0 else 'wait'
    if params.get('hard_veto'):
        return {'state': 'avoid', 'max_position_ratio': 0.0, 'reason': 'L0a 硬否决'}
    if params.get('hold_only'):
        return {'state': 'wait', 'max_position_ratio': 0.0, 'reason': '信号已延伸：只可持有、不新开仓（L0c）'}
    # 盈亏比门禁（493号 P2-b：《R-R筛选规则》rr<2:1 放弃 → 降级观望 + 仓位减半）
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


def build_seven_dim_from_dim_results(dim_results: dict | None,
                                     tags: dict | None = None,
                                     lifecycle: dict | None = None,
                                     ts_code: str | None = None,
                                     jud_result: dict | None = None) -> dict | None:
    """SIG 文字类产出（seven_dim_json）整体归集入口（436号 B1）

    委派 dim8（Dim8SummaryEngine.build_seven_dim_report）组装前端契约的七维现状描述：
      7 键 signal/structure/volume_price/fund_chip/emotion/risk/summary，
      顶层 light emoji、每段 judgment/audit/plain（align 两端 dimOrder/segOrder）。
    ts_code：462-3 相对强弱环境定位句（summary 前置）用；不传则跳过。
    jud_result：可选（495号 A1）——判定层结果，传入时 summary 段由判定层派生（单源化）。
    dim_results 为空/非 dict → 返回 None（data_daemon 写 NULL，门禁跳过）。
    """
    if not dim_results or not isinstance(dim_results, dict):
        return None
    try:
        from app.opportunity_atlas.dimensions.dim8_summary_engine import Dim8SummaryEngine
        return Dim8SummaryEngine().build_seven_dim_report(dim_results, tags=tags,
                                                          ts_code=ts_code,
                                                          jud_result=jud_result)
    except Exception as e:
        logger.warning(f"build_seven_dim_from_dim_results 失败: {e}")
        return None


def build_status_engine() -> StatusEngine:
    return StatusEngine()
