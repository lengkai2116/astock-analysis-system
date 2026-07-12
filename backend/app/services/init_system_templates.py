"""
系统预设策略模板种子数据
精确匹配原型 _ui-prototype/strategy-templates.html 中 11 个 A 股领域策略
在应用启动时自动执行（经由 __init__.py），支持 schema 迁移和更新覆盖
"""

import logging
from datetime import datetime
from sqlalchemy import text

from app import db
from app.models.strategy import StrategyTemplateV2, StrategyTemplateType

logger = logging.getLogger(__name__)

# ── 新增列定义（用于 ALTER TABLE 迁移） ──
NEW_COLUMNS = {
    'cat': 'VARCHAR(50)',
    'catLabel': 'VARCHAR(50)',
    'catCN': 'VARCHAR(50)',
    'icon': 'VARCHAR(10)',
    'nameCN': 'VARCHAR(100)',
    'tags': 'JSON',
    'ready': 'BOOLEAN DEFAULT 1',
    'vibe': 'BOOLEAN DEFAULT 0',
    'devLabel': 'VARCHAR(50)',
    'devPriority': 'VARCHAR(10)',
    'inputs': 'JSON',
    'wiki': 'JSON',
    'updated': 'VARCHAR(20)',
    'iconLarge': 'VARCHAR(10)',
}

# ── 11 个 A 股领域策略 ──
SYSTEM_TEMPLATES = [
    # ── vp: 量价策略 ──
    {
        'cat': 'vp',
        'catLabel': '量价策略',
        'catCN': '量价策略',
        'name': 'VolumePriceStrategy',
        'nameCN': '量价策略',
        'icon': '📈',
        'iconLarge': '📈',
        'description': '基于成交量与价格的50+形态检测规则，识别主力资金介入、趋势突破、背离等信号。单一独立策略，使用时作为一个整体。',
        'template_type': 'indicator',
        'tags': ['量价', '形态', '突破', '背离'],
        'ready': True,
        'vibe': False,
        'devLabel': None,
        'devPriority': None,
        'parameters': [
            {'key': 'volume_ratio', 'label': '放量倍数', 'val': 1.5, 'min': 1, 'max': 5, 'step': 0.1},
            {'key': 'breakout_period', 'label': '突破周期', 'val': 20, 'min': 5, 'max': 60, 'step': 1},
            {'key': 'trend_strength', 'label': '趋势强度阈值', 'val': 25, 'min': 10, 'max': 50, 'step': 1}
        ],
        'inputs': ['日线K线数据 (open/high/low/close/volume)', '复权因子 (adj_factor)', '板块分类数据'],
        'output_schema': {
            'signal': {'type': 'enum', 'values': ['买入', '卖出', '持有', '观望']},
            'score': {'type': 'number', 'range': '0-100'},
            'patterns': {'type': 'array', 'desc': '检测到的形态列表'}
        },
        'wiki': ['量价关系理论', '成交量分析方法'],
        'code_template': '''class VolumePriceStrategy:
    def __init__(self, ctx):
        self.volume_ratio = ctx.params.volume_ratio
        self.breakout_period = ctx.params.breakout_period

    def analyze(self, data):
        # 检测50+量价形态
        patterns = self._detect_patterns(data)
        score = self._score_patterns(patterns)
        return {"score": score, "patterns": patterns}''',
        'is_system': True,
        'author': 'System',
        'updated': '2026-06-20',
    },

    # ── chanlun: 缠论策略 ──
    {
        'cat': 'chanlun',
        'catLabel': '缠论策略',
        'catCN': '缠论策略',
        'name': 'ChanlunStrategy',
        'nameCN': '缠论策略',
        'icon': '🧩',
        'iconLarge': '🧩',
        'description': '基于笔-段-中枢体系，识别三类买卖点和8种形态，配合决策树评分。单一独立策略，使用时作为一个整体。',
        'template_type': 'indicator',
        'tags': ['缠论', '买卖点', '中枢', '全周期'],
        'ready': True,
        'vibe': False,
        'devLabel': None,
        'devPriority': None,
        'parameters': [
            {'key': 'di_k_type', 'label': '底分型K线数', 'val': 3, 'min': 2, 'max': 5, 'step': 1},
            {'key': 'ding_k_type', 'label': '顶分型K线数', 'val': 3, 'min': 2, 'max': 5, 'step': 1},
            {'key': 'bi_min_bars', 'label': '最小笔K线数', 'val': 5, 'min': 3, 'max': 10, 'step': 1}
        ],
        'inputs': ['日线K线数据 (open/high/low/close)', '分笔数据 (笔的起止点)', '中枢区间数据'],
        'output_schema': {
            'signal': {'type': 'enum', 'values': ['一买', '二买', '三买', '一卖', '二卖', '三卖', '中枢震荡', '无信号']},
            'score': {'type': 'number', 'range': '0-100'},
            'confidence': {'type': 'string', 'values': ['高', '中', '低']}
        },
        'wiki': ['缠论原著', '笔-段-中枢定义', '三类买卖点分类'],
        'code_template': '''class ChanlunStrategy:
    def __init__(self, ctx):
        self.bi_min_bars = ctx.params.bi_min_bars

    def analyze(self, data):
        bi = self._find_bi(data)
        zhongshu = self._find_zhongshu(bi)
        signal = self._check_buy_sell(zhongshu, bi[-1])
        return {"signal": signal, "confidence": self._calc_confidence(signal)}''',
        'is_system': True,
        'author': 'System',
        'updated': '2026-06-20',
    },

    # ── chip: 筹码策略 ──
    {
        'cat': 'chip',
        'catLabel': '筹码策略',
        'catCN': '筹码策略',
        'name': 'ChipStrategy',
        'nameCN': '筹码策略',
        'icon': '📦',
        'iconLarge': '📦',
        'description': '基于筹码分布分析主力成本区间，识别吸筹/洗盘/拉升/出货各阶段信号。单一独立策略，使用作为一个整体。',
        'template_type': 'indicator',
        'tags': ['筹码', '主力', '资金流', '支撑'],
        'ready': True,
        'vibe': False,
        'devLabel': None,
        'devPriority': None,
        'parameters': [
            {'key': 'chip_window', 'label': '筹码计算周期', 'val': 60, 'min': 20, 'max': 120, 'step': 5},
            {'key': 'dense_threshold', 'label': '密集区阈值%', 'val': 70, 'min': 50, 'max': 95, 'step': 5},
            {'key': 'asr_period', 'label': 'ASR计算周期', 'val': 20, 'min': 5, 'max': 60, 'step': 5}
        ],
        'inputs': ['日线K线数据', '逐笔成交数据 (tick)', '大单资金流数据 (moneyflow)'],
        'output_schema': {
            'signal': {'type': 'enum', 'values': ['吸筹', '洗盘', '拉升', '出货', '无信号']},
            'chip_cost': {'type': 'number', 'desc': '主力成本区间'},
            'concentration': {'type': 'number', 'desc': '筹码集中度 0-1'}
        },
        'wiki': ['筹码分布理论', 'ASR指标计算方法'],
        'code_template': '''class ChipStrategy:
    def __init__(self, ctx):
        self.chip_window = ctx.params.chip_window

    def analyze(self, data):
        dist = self._calc_chip_distribution(data)
        phase = self._identify_phase(dist)
        return {"phase": phase, "chip_cost": dist.cost, "concentration": dist.concentration}''',
        'is_system': True,
        'author': 'System',
        'updated': '2026-06-20',
    },

    # ── darwin: 达尔文风险策略 ──
    {
        'cat': 'darwin',
        'catLabel': '达尔文风险策略',
        'catCN': '达尔文风险策略',
        'name': 'DarwinRiskStrategy',
        'nameCN': '达尔文风险策略',
        'icon': '🧬',
        'iconLarge': '🧬',
        'description': '系统级L1层过滤器，基于多维度风险指标剔除高风险股票。作为选股系统第一道防线。',
        'template_type': 'selection',
        'tags': ['风险', '筛选', '系统级'],
        'ready': True,
        'vibe': False,
        'devLabel': None,
        'devPriority': None,
        'parameters': [
            {'key': 'pe_max', 'label': '最大PE', 'val': 200, 'min': 50, 'max': 500, 'step': 10},
            {'key': 'st_min_days', 'label': 'ST观察天数', 'val': 5, 'min': 1, 'max': 20, 'step': 1},
            {'key': 'liquidity_min', 'label': '最小日成交额(亿)', 'val': 0.5, 'min': 0.1, 'max': 5, 'step': 0.1}
        ],
        'inputs': ['日线K线数据', 'ST/退市风险标签', '财务数据（PE/PB/营收）', '日成交额'],
        'output_schema': {
            'pass': {'type': 'boolean', 'desc': '是否通过风险过滤'},
            'risk_factors': {'type': 'array', 'desc': '触发的风险因素列表'},
            'risk_score': {'type': 'number', 'range': '0-100'}
        },
        'wiki': ['风险管理理论', 'A股风险警示规则'],
        'code_template': '''class DarwinRiskStrategy:
    def __init__(self, ctx):
        self.pe_max = ctx.params.pe_max

    def filter(self, universe):
        passed = []
        for stock in universe:
            if self._check_risk(stock):
                passed.append(stock)
        return passed''',
        'is_system': True,
        'author': 'System',
        'updated': '2026-06-20',
    },

    # ── s1: 市场情绪周期策略 ──
    {
        'cat': 's1',
        'catLabel': '情绪周期策略',
        'catCN': '市场情绪周期策略',
        'name': 'MarketSentimentCycleStrategy',
        'nameCN': '市场情绪周期策略',
        'icon': '🔄',
        'iconLarge': '🔄',
        'description': '基于市场广度数据（涨跌比/涨停数/跌停数/连板高度）识别情绪周期阶段，判断市场热度与拐点。',
        'template_type': 'indicator',
        'tags': ['情绪', '周期', '市场广度'],
        'ready': False,
        'vibe': False,
        'devLabel': 'P0 开发中',
        'devPriority': 'P0',
        'parameters': [
            {'key': 'updown_ratio_period', 'label': '涨跌比周期', 'val': 5, 'min': 3, 'max': 20, 'step': 1},
            {'key': 'limitup_surge_threshold', 'label': '涨停潮阈值', 'val': 50, 'min': 20, 'max': 100, 'step': 5},
            {'key': 'sentiment_smooth', 'label': '情绪平滑因子', 'val': 3, 'min': 1, 'max': 10, 'step': 1}
        ],
        'inputs': ['全市场涨跌家数', '涨停/跌停列表', '连板高度数据', '成交量能'],
        'output_schema': {
            'phase': {'type': 'enum', 'values': ['冰点', '回暖', '高潮', '退潮']},
            'sentiment_score': {'type': 'number', 'range': '0-100'},
            'signal': {'type': 'enum', 'values': ['积极', '谨慎', '观望', '回避']}
        },
        'wiki': ['市场情绪周期理论', 'A股情绪指标研究'],
        'code_template': '''# S1 市场情绪周期策略 — 真实实现
# 基于个股价格行为推断市场情绪阶段
import numpy as np

ret = np.diff(close.values) / np.maximum(close.values[:-1], 1e-10)
ret = np.append(ret, 0.0)

vol_short = pd.Series(ret).rolling(5, min_periods=3).std().fillna(0).values
vol_long = pd.Series(ret).rolling(20, min_periods=8).std().fillna(0).values
vol_ratio = np.where(vol_long > 1e-10, vol_short / vol_long, 1.0)

n = len(close)
recent_ret = ret[-20:] if n >= 20 else ret
direction = np.sign(recent_ret)
consistency = abs(direction.mean())

momentum = (close.iloc[-1] / max(close.iloc[-20], 1e-10) - 1) if n >= 20 else 0.0
momentum = np.clip(momentum, -0.2, 0.2)

vol_ratio_latest = vol_ratio[-1] if len(vol_ratio) > 0 else 1.0
consistency_latest = float(consistency)
vol_long_latest = vol_long[-1] if len(vol_long) > 0 else 0.0
vol_long_median = float(np.median(vol_long[-20:])) if len(vol_long) >= 20 else vol_long_latest
vol_regime = vol_long_latest > vol_long_median * 1.2

if consistency_latest > 0.6 and momentum > 0.03 and vol_regime:
    signal = 1
elif consistency_latest > 0.4 and momentum > 0.0 and not vol_regime:
    signal = 1 if momentum > 0.02 else 0
elif consistency_latest < 0.2 and abs(momentum) < 0.02:
    signal = 0
else:
    signal = -1 if momentum < -0.03 else 0
signal = int(np.clip(signal, -1, 1))''',
        'is_system': True,
        'author': 'System',
        'updated': '2026-06-24',
    },

    # ── s2: 主力行为追踪策略 ──
    {
        'cat': 's2',
        'catLabel': '主力行为策略',
        'catCN': '主力行为追踪策略',
        'name': 'MainForceTrackingStrategy',
        'nameCN': '主力行为追踪策略',
        'icon': '🔍',
        'iconLarge': '🔍',
        'description': '追踪主力资金动向，识别大单净流入/流出、主力持仓变化、对倒行为等异常交易信号。',
        'template_type': 'indicator',
        'tags': ['主力', '资金', '大单', '持仓'],
        'ready': False,
        'vibe': False,
        'devLabel': 'P1 待开发',
        'devPriority': 'P1',
        'parameters': [
            {'key': 'big_order_threshold', 'label': '大单阈值(万元)', 'val': 100, 'min': 50, 'max': 500, 'step': 10},
            {'key': 'net_flow_period', 'label': '净流计算周期', 'val': 5, 'min': 1, 'max': 20, 'step': 1},
            {'key': 'position_change_threshold', 'label': '持仓变动阈值%', 'val': 1, 'min': 0.1, 'max': 5, 'step': 0.1}
        ],
        'inputs': ['逐笔成交数据', '大单资金流', '机构持仓数据', '龙虎榜数据'],
        'output_schema': {
            'mainforce_signal': {'type': 'enum', 'values': ['主力吸筹', '主力出货', '对倒', '无明显信号']},
            'net_flow': {'type': 'number', 'desc': '净流入金额(万元)'},
            'position_change': {'type': 'number', 'desc': '主力持仓变动%'}
        },
        'wiki': ['主力行为学', '大单资金流向分析'],
        'code_template': '''# S2 主力行为追踪策略
# 状态: P1 待开发 — 规格预览
class MainForceTrackingStrategy:
    def __init__(self, ctx):
        self.big_order_threshold = ctx.params.big_order_threshold

    def analyze(self, data):
        big_orders = self._filter_big_orders(data)
        signal = self._detect_mainforce(big_orders)
        return {"mainforce_signal": signal, "net_flow": big_orders.net_sum}''',
        'is_system': True,
        'author': 'System',
        'updated': '2026-06-24',
    },

    # ── s3: 趋势通道识别策略 ──
    {
        'cat': 's3',
        'catLabel': '趋势通道策略',
        'catCN': '趋势通道识别策略',
        'name': 'TrendChannelStrategy',
        'nameCN': '趋势通道识别策略',
        'icon': '📐',
        'iconLarge': '📐',
        'description': '自动识别上升/下降/横盘趋势通道，检测通道突破、趋势加速/减速等信号。',
        'template_type': 'indicator',
        'tags': ['趋势', '通道', '突破'],
        'ready': False,
        'vibe': False,
        'devLabel': 'P1 待开发',
        'devPriority': 'P1',
        'parameters': [
            {'key': 'channel_period', 'label': '通道计算周期', 'val': 20, 'min': 10, 'max': 60, 'step': 5},
            {'key': 'breakout_confirm_bars', 'label': '突破确认K线数', 'val': 3, 'min': 1, 'max': 10, 'step': 1},
            {'key': 'trend_slope_min', 'label': '最小趋势斜率', 'val': 0.5, 'min': 0.1, 'max': 2, 'step': 0.1}
        ],
        'inputs': ['日线K线数据', '均线数据(MA5/MA10/MA20/MA60)'],
        'output_schema': {
            'channel_type': {'type': 'enum', 'values': ['上升通道', '下降通道', '横盘通道']},
            'channel_bound': {'type': 'object', 'desc': '通道上下轨'},
            'signal': {'type': 'enum', 'values': ['通道突破', '趋势加速', '趋势减速', '无信号']}
        },
        'wiki': ['趋势通道理论', '唐奇安通道'],
        'code_template': '''# S3 趋势通道识别策略 — 真实实现
# 识别上升/下降/横盘通道，检测通道突破
import numpy as np

n_period = 20
confirm = 3

if len(close) < n_period + confirm:
    signal = 0
else:
    recent_high = high.iloc[-n_period:].max()
    recent_low = low.iloc[-n_period:].min()
    channel_height = recent_high - recent_low

    pos = (close.iloc[-1] - recent_low) / max(channel_height, 1e-10)

    x = np.arange(n_period)
    y = close.iloc[-n_period:].values
    slope = np.polyfit(x, y, 1)[0] / max(np.mean(y), 1e-10)

    last_n_close = close.iloc[-confirm:].values
    breakout_up = all(c > recent_high * 0.99 for c in last_n_close[-2:]) and slope > 0.005
    breakout_down = all(c < recent_low * 1.01 for c in last_n_close[-2:]) and slope < -0.005

    if breakout_up:
        signal = 1
    elif breakout_down:
        signal = -1
    elif slope > 0.003:
        signal = 1 if pos > 0.5 else 0
    elif slope < -0.003:
        signal = -1 if pos < 0.5 else 0
    else:
        signal = 0
signal = int(np.clip(signal, -1, 1))''',
        'is_system': True,
        'author': 'System',
        'updated': '2026-06-24',
    },

    # ── s4: 涨停板短线策略 ──
    {
        'cat': 's4',
        'catLabel': '涨停板策略',
        'catCN': '涨停板短线策略',
        'name': 'LimitUpShortTermStrategy',
        'nameCN': '涨停板短线策略',
        'icon': '⚡',
        'iconLarge': '⚡',
        'description': '分析涨停板质量（封板时间/封单量/换手率/板块带动效应），识别连板潜力和短线机会。',
        'template_type': 'indicator',
        'tags': ['涨停', '短线', '封板', '连板'],
        'ready': False,
        'vibe': False,
        'devLabel': 'P2 待开发',
        'devPriority': 'P2',
        'parameters': [
            {'key': 'seal_ratio_min', 'label': '最低封成比', 'val': 1.5, 'min': 0.5, 'max': 5, 'step': 0.1},
            {'key': 'limitup_time_before', 'label': '封板时间早于', 'val': 1030, 'min': 930, 'max': 1500, 'step': 30},
            {'key': 'consecutive_limit_max', 'label': '最大连板数', 'val': 5, 'min': 1, 'max': 10, 'step': 1}
        ],
        'inputs': ['涨停板实时数据', '封单量/封成比数据', '板块联动数据', '换手率数据'],
        'output_schema': {
            'quality': {'type': 'enum', 'values': ['强板', '中板', '弱板']},
            'consecutive_potential': {'type': 'number', 'desc': '连板潜力评分 0-100'},
            'signal': {'type': 'enum', 'values': ['打板', '排板', '观望']}
        },
        'wiki': ['涨停板交易策略', 'A股涨停板制度'],
        'code_template': '''# S4 涨停板短线策略 — 真实实现
# 基于OHLCV检测涨停板质量和连板潜力
import numpy as np

if len(close) < 5:
    signal = 0
else:
    limit_up_threshold = 0.095
    prev_close = close.shift(1)

    is_limit_up = (close / prev_close - 1) >= limit_up_threshold

    consecutive = 0
    for i in range(len(is_limit_up) - 1, -1, -1):
        if is_limit_up.iloc[i]:
            consecutive += 1
        else:
            break

    if consecutive > 0:
        avg_vol = volume.iloc[-min(20, len(volume)):-1].mean() if len(volume) > 1 else volume.iloc[-1]
        vol_ratio_today = volume.iloc[-1] / max(avg_vol, 1)

        if consecutive >= 3:
            signal = 0
        elif vol_ratio_today < 1.2:
            signal = 1
        else:
            signal = 0
    else:
        signal = 0
signal = int(np.clip(signal, -1, 1))''',
        'is_system': True,
        'author': 'System',
        'updated': '2026-06-24',
    },

    # ── s5: 多层次风险控制策略 ──
    {
        'cat': 's5',
        'catLabel': '风控策略',
        'catCN': '多层次风险控制策略',
        'name': 'MultiLevelRiskControlStrategy',
        'nameCN': '多层次风险控制策略',
        'icon': '🛡️',
        'iconLarge': '🛡️',
        'description': '系统级叠加层，从账户/组合/个股三个层次控制风险敞口，设置动态止损止盈阈值。',
        'template_type': 'portfolio',
        'tags': ['风控', '止损', '敞口', '系统级'],
        'ready': False,
        'vibe': False,
        'devLabel': 'P2 待开发',
        'devPriority': 'P2',
        'parameters': [
            {'key': 'max_drawdown', 'label': '最大回撤阈值%', 'val': 15, 'min': 5, 'max': 30, 'step': 1},
            {'key': 'single_stock_limit', 'label': '个股仓位上限%', 'val': 20, 'min': 5, 'max': 50, 'step': 5},
            {'key': 'stop_loss_a', 'label': '止损比例A', 'val': -5, 'min': -20, 'max': -1, 'step': 1}
        ],
        'inputs': ['账户资产数据', '持仓市值数据', '市场波动率数据', '个股实时行情'],
        'output_schema': {
            'risk_level': {'type': 'enum', 'values': ['正常', '预警', '警戒', '强制平仓']},
            'actions': {'type': 'array', 'desc': '建议操作列表'},
            'max_exposure': {'type': 'number', 'desc': '建议最大敞口%'}
        },
        'wiki': ['风险管理框架', '动态止损策略'],
        'code_template': '''# S5 多层次风险控制策略
# 状态: P2 待开发 — 规格预览
class MultiLevelRiskControlStrategy:
    def __init__(self, ctx):
        self.max_drawdown = ctx.params.max_drawdown

    def analyze(self, portfolio):
        level = self._assess_risk_level(portfolio)
        return {"risk_level": level, "actions": self._gen_actions(level)}''',
        'is_system': True,
        'author': 'System',
        'updated': '2026-06-24',
    },

    # ── s6: 波浪理论阶段识别策略 ──
    {
        'cat': 's6',
        'catLabel': '波浪理论策略',
        'catCN': '波浪理论阶段识别策略',
        'name': 'WaveTheoryStrategy',
        'nameCN': '波浪理论阶段识别策略',
        'icon': '🌊',
        'iconLarge': '🌊',
        'description': '基于艾略特波浪理论，识别价格走势中的驱动浪和调整浪，判断当前所处波浪阶段。',
        'template_type': 'indicator',
        'tags': ['波浪理论', '驱动浪', '调整浪'],
        'ready': False,
        'vibe': False,
        'devLabel': 'P3 待开发',
        'devPriority': 'P3',
        'parameters': [
            {'key': 'wave_min_bars', 'label': '波浪最小K线数', 'val': 5, 'min': 3, 'max': 20, 'step': 1},
            {'key': 'fib_retrace_threshold', 'label': '回调比例阈值', 'val': 0.618, 'min': 0.382, 'max': 0.886, 'step': 0.001},
            {'key': 'impulse_confirm', 'label': '驱动浪确认幅度%', 'val': 1, 'min': 0.5, 'max': 5, 'step': 0.1}
        ],
        'inputs': ['日线/周线K线数据', '波段高低点数据'],
        'output_schema': {
            'wave_phase': {'type': 'enum', 'values': ['浪1', '浪2', '浪3', '浪4', '浪5', '浪A', '浪B', '浪C']},
            'trend': {'type': 'enum', 'values': ['上升驱动', '下降调整', '上升调整', '下降驱动']},
            'completion_pct': {'type': 'number', 'desc': '当前浪完成度%'}
        },
        'wiki': ['艾略特波浪理论', '斐波那契与波浪'],
        'code_template': '''# S6 波浪理论阶段识别策略 — 真实实现
# 识别摆动高低点，判断波浪阶段
import numpy as np

if len(close) < 30:
    signal = 0
else:
    window = 5
    closes = close.values
    highs_v = high.values
    lows_v = low.values

    peaks = []
    troughs = []

    for i in range(window, len(closes) - window):
        if highs_v[i] == max(highs_v[i - window:i + window + 1]):
            peaks.append(highs_v[i])
        if lows_v[i] == min(lows_v[i - window:i + window + 1]):
            troughs.append(lows_v[i])

    if len(peaks) < 2 or len(troughs) < 2:
        signal = 0
    else:
        last_peak = peaks[-1]
        last_trough = troughs[-1]
        prev_peak = peaks[-2] if len(peaks) >= 2 else last_peak
        prev_trough = troughs[-2] if len(troughs) >= 2 else last_trough

        higher_high = last_peak > prev_peak * 1.02
        higher_low = last_trough > prev_trough * 1.02
        lower_high = last_peak < prev_peak * 0.98
        lower_low = last_trough < prev_trough * 0.98

        current = closes[-1]
        recent_range = max(highs_v[-20:]) - min(lows_v[-20:]) if len(closes) >= 20 else 0
        pos_in_wave = (current - min(lows_v[-20:])) / max(recent_range, 1e-10) if recent_range > 0 else 0.5

        if higher_high and higher_low:
            signal = 1 if pos_in_wave < 0.7 else 0
        elif lower_high and lower_low:
            signal = -1 if pos_in_wave > 0.3 else 0
        else:
            signal = 0
signal = int(np.clip(signal, -1, 1))''',
        'is_system': True,
        'author': 'System',
        'updated': '2026-06-24',
    },

    # ── s7: 斐波那契时间周期策略 ──
    {
        'cat': 's7',
        'catLabel': '斐波那契策略',
        'catCN': '斐波那契时间周期策略',
        'name': 'FibonacciTimeCycleStrategy',
        'nameCN': '斐波那契时间周期策略',
        'icon': '🔢',
        'iconLarge': '🔢',
        'description': '基于斐波那契数列的时间周期和回调比例，预测关键支撑/阻力位和时间转折点。',
        'template_type': 'indicator',
        'tags': ['斐波那契', '时间周期', '回调', '预测'],
        'ready': False,
        'vibe': False,
        'devLabel': 'P3 待开发',
        'devPriority': 'P3',
        'parameters': [
            {'key': 'fib_levels', 'label': '回调线层级', 'val': 4, 'min': 1, 'max': 5, 'step': 1, 'opts': ['0.236/0.382', '+0.5', '+0.618', '+0.786', '+0.886']},
            {'key': 'time_period', 'label': '时间周期基数', 'val': 21, 'min': 8, 'max': 89, 'step': 1},
            {'key': 'extend_ratio', 'label': '扩展比例', 'val': 1.618, 'min': 1.0, 'max': 2.618, 'step': 0.001}
        ],
        'inputs': ['日线/周线K线数据', '波段起止点数据'],
        'output_schema': {
            'support_levels': {'type': 'array', 'desc': '关键支撑位列表'},
            'resistance_levels': {'type': 'array', 'desc': '关键阻力位列表'},
            'turn_points': {'type': 'array', 'desc': '时间转折点列表'},
            'signal': {'type': 'enum', 'values': ['回调到位', '反弹遇阻', '趋势延续', '无信号']}
        },
        'wiki': ['斐波那契分析', '时间周期理论'],
        'code_template': '''# S7 斐波那契时间周期策略 — 真实实现
# 基于波段极值计算斐波那契回调位
import numpy as np

if len(close) < 30:
    signal = 0
else:
    lookback = min(60, len(close))
    recent_high = high.iloc[-lookback:].max()
    recent_low = low.iloc[-lookback:].min()
    high_idx = high.iloc[-lookback:].idxmax()
    low_idx = low.iloc[-lookback:].idxmin()

    if isinstance(high_idx, (int, np.integer)):
        high_pos = high_idx
        low_pos = low_idx
    else:
        idx_list = list(close.index)
        high_pos = idx_list.index(high_idx) if high_idx in idx_list else 0
        low_pos = idx_list.index(low_idx) if low_idx in idx_list else 0

    up_swing = high_pos > low_pos
    swing_range = abs(recent_high - recent_low)

    if swing_range < recent_low * 0.05:
        signal = 0
    else:
        current = close.iloc[-1]
        fib_levels = [0.236, 0.382, 0.5, 0.618, 0.786]

        if up_swing:
            fib_prices = [recent_high - lvl * swing_range for lvl in fib_levels]
            near_support = False
            for fp in fib_prices[2:]:
                if abs(current - fp) / max(swing_range, 1e-10) < 0.05:
                    near_support = True
                    break
            signal = 1 if near_support else 0
        else:
            fib_prices = [recent_low + lvl * swing_range for lvl in fib_levels]
            near_resistance = False
            for fp in fib_prices[2:]:
                if abs(current - fp) / max(swing_range, 1e-10) < 0.05:
                    near_resistance = True
                    break
            signal = -1 if near_resistance else 0
signal = int(np.clip(signal, -1, 1))''',
        'is_system': True,
        'author': 'System',
        'updated': '2026-06-24',
    },
]


def _ensure_schema():
    """
    ALTER TABLE 添加新列（幂等操作）
    适用于 SQLite：新列检测不存在时添加，catch 已存在异常
    """
    for col, col_type in NEW_COLUMNS.items():
        try:
            db.session.execute(text(f"ALTER TABLE strategy_templates_v2 ADD COLUMN {col} {col_type}"))
            db.session.commit()
            logger.info(f"新增列: strategy_templates_v2.{col}")
        except Exception:
            db.session.rollback()  # 列已存在


def init_system_templates():
    """
    初始化系统预设策略模板种子数据

    幂等设计：
    - 先执行 schema 迁移（新增列）
    - 对同名模板执行更新覆盖
    - 新模板直接插入
    """
    logger.info("开始初始化系统预设策略模板...")

    _ensure_schema()

    created_count = 0
    updated_count = 0

    for template_data in SYSTEM_TEMPLATES:
        existing = StrategyTemplateV2.query.filter_by(
            name=template_data['name'],
            is_system=True
        ).first()

        if existing:
            # 更新已有模板（覆盖全部字段）
            for k, v in template_data.items():
                if k == 'template_type':
                    existing.template_type = StrategyTemplateType(v)
                else:
                    setattr(existing, k, v)
            existing.updated_at = datetime.now()
            updated_count += 1
        else:
            # 创建新模板
            template_data['updated_at'] = datetime.now()
            template_data['created_at'] = datetime.now()
            template_type_val = template_data.pop('template_type', 'indicator')
            template = StrategyTemplateV2(
                **template_data,
                template_type=StrategyTemplateType(template_type_val)
            )
            db.session.add(template)
            created_count += 1

    db.session.commit()
    logger.info(f"初始化完成: 新增 {created_count} 个模板, 更新 {updated_count} 个已存在的模板")

    # ── 设置 Vibe 策略标记 ──
    # 将不在 L1/L2/L3 管道中的候选策略标记为 vibe=True
    _VIBE_CANDIDATES = [
        'MarketSentimentCycleStrategy',
        'TrendChannelStrategy',
        'LimitUpShortTermStrategy',
        'WaveTheoryStrategy',
        'FibonacciTimeCycleStrategy',
    ]
    try:
        updated = StrategyTemplateV2.query.filter(
            StrategyTemplateV2.name.in_(_VIBE_CANDIDATES)
        ).update({'vibe': True}, synchronize_session=False)
        db.session.commit()
        if updated:
            logger.info(f"Vibe 策略标记完成: {updated} 个")
    except Exception as e:
        db.session.rollback()
        logger.warning(f"Vibe 策略标记失败: {e}")

    return created_count, updated_count
