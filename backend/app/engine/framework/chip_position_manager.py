"""
仓位管理执行层 - Phase 3 模块7
对应书本第9章§9.4-9.5

功能：基于操盘阶段 + 信号调整 + 大盘环境 + 熔断检查，计算目标仓位

工作流程：
  1. 基础仓位（按操盘阶段）
  2. 信号调整（按触发信号类型）
  3. 大盘环境乘数（MarketEnvironmentFilter 输出）
  4. 熔断检查（CircuitBreaker 输出）
  5. 限仓（按阶段上限 + 大盘差时40%封顶）
"""
from typing import Dict, Optional


class ChipPositionManager:
    """基于操盘阶段+多层风控的仓位管理器（含金字塔建仓）"""

    # 每个操盘阶段的基础仓位上限
    PHASE_BASE_POSITION = {
        'BUILDING': 0.30,   # 建仓期：最大30%
        'WASHING': 0.50,    # 洗盘期：最大50%
        'RAISING': 0.70,    # 拉升期：最大70%
        'SHIPPING': 0.00,   # 出货期：清仓
        'SUPPORT': 0.30,    # 支撑/下跌期：最大30%
    }

    # 信号类型与仓位调整乘数
    SIGNAL_ADJUSTMENT = {
        'S_BUY': 1.0,
        'S_WASH_END': 0.8,
        'S_BOUNCE': 0.5,
        'S_SELL': 0.0,
        'S_WASH_STOP': 0.0,
        'S_DIVERG_SELL': 0.0,  # 由信号自身的 position_adjustment 决定
        'HOLD': 0.0,
    }

    # 大盘环境乘数
    MARKET_MULTIPLIER = {
        'GOOD': 1.0,
        'POOR': 0.5,
        'UNKNOWN': 0.7,
    }

    # 金字塔建仓参数
    PYRAMID_CONFIG = {
        'tier1_ratio': 0.5,      # 首次入场：目标仓位的50%
        'tier2_ratio': 0.8,      # 二次加仓：目标仓位的80%
        'tier3_ratio': 1.0,      # 三次加仓：目标仓位的100%
        'tier1_confirm_days': 0,  # Tier1 立即执行
        'tier2_confirm_days': 3,  # Tier2 需3日后确认
        'tier3_confirm_days': 6,  # Tier3 需6日后确认
        'price_up_threshold': 0.01,  # 确认条件：价格不低于入场价99%
        'price_up_strong': 0.02,     # 强确认条件：涨幅超过2%
    }

    def __init__(self):
        self._current_position = 0.0
        # 金字塔建仓状态跟踪 {symbol: {'entry_price': float, 'tier': int,
        #                           'entry_date': int, 'phase': str}}
        self._pyramid_state: Dict[str, Dict] = {}

    def set_current_position(self, position: float):
        """设置当前仓位（由外部调用更新）"""
        self._current_position = max(0.0, min(1.0, position))

    def reset_pyramid(self, symbol: str):
        """清空指定股票的金字塔建仓状态"""
        self._pyramid_state.pop(symbol, None)

    def _get_pyramid_tier_info(self, symbol: str, signal_action: str,
                                entry_price: float, date_idx: int,
                                current_price: float) -> Dict:
        """
        获取金字塔建仓层级信息

        金字塔规则（短线风险控制 仓位控制）：
          Tier1: 首批入场 50%，立即执行
          Tier2: +30%(累计80%)，需3日后价格不破入场价
          Tier3: +20%(累计100%)，需6日后价格不破入场价

        如果价格下跌：停留在当前层级不再加仓
        如果卖出信号：重置状态
        """
        state = self._pyramid_state.get(symbol)
        config = self.PYRAMID_CONFIG

        # 首次买入：初始状态
        if state is None:
            self._pyramid_state[symbol] = {
                'entry_price': entry_price,
                'tier': 1,
                'entry_date': date_idx,
                'phase': 'init'
            }
            return {
                'current_tier': 1,
                'tier_ratio': config['tier1_ratio'],
                'confirm_needed': False,
                'status': '金字塔Tier1:首仓50%'
            }

        # 已有持仓 - 检查是否可以加仓
        current_tier = state.get('tier', 1)
        holding_days = date_idx - state.get('entry_date', date_idx)
        entry = state.get('entry_price', entry_price)
        price_change = (current_price - entry) / entry if entry > 0 else 0

        # 如果价格已跌破入场价95%，不再加仓
        if price_change < -0.05:
            return {
                'current_tier': current_tier,
                'tier_ratio': [0.5, 0.8, 1.0][min(current_tier - 1, 2)],
                'confirm_needed': False,
                'status': f'价格已跌{price_change*100:.1f}%,暂停加仓,Tier{current_tier}'
            }

        # Tier1→Tier2：3日后确认
        if current_tier == 1 and holding_days >= config['tier2_confirm_days']:
            if price_change >= 0:
                # 价格未跌破入场价，加仓至80%
                state['tier'] = 2
                state['entry_date'] = date_idx  # 重置计数
                return {
                    'current_tier': 2,
                    'tier_ratio': config['tier2_ratio'],
                    'confirm_needed': True,
                    'confirm_passed': True,
                    'status': f'金字塔Tier2:加仓至80%(确认Tier1涨幅{price_change*100:.1f}%)'
                }

        # Tier2→Tier3：又3日后确认
        if current_tier == 2 and holding_days >= config['tier3_confirm_days'] - config['tier2_confirm_days']:
            if price_change >= config['price_up_threshold']:
                state['tier'] = 3
                return {
                    'current_tier': 3,
                    'tier_ratio': config['tier3_ratio'],
                    'confirm_needed': True,
                    'confirm_passed': True,
                    'status': f'金字塔Tier3:加仓至满仓(确认涨幅{price_change*100:.1f}%)'
                }

        return {
            'current_tier': current_tier,
            'tier_ratio': [0.5, 0.8, 1.0][min(current_tier - 1, 2)],
            'confirm_needed': current_tier < 3,
            'confirm_passed': False,
            'status': f'金字塔Tier{current_tier}:等待确认(持仓{holding_days}日,涨幅{price_change*100:.1f}%)'
        }

    def calculate_target_position(
        self,
        phase: str,                     # 操盘阶段
        signal_result: Dict,            # _combine_signals 的输出
        market_condition: str = 'GOOD', # 'GOOD' / 'POOR' / 'UNKNOWN'
        circuit_breaker: Optional[Dict] = None,  # CircuitBreaker.check() 输出
        symbol: Optional[str] = None,   # 股票代码（金字塔建仓用）
        entry_price: Optional[float] = None,  # 入场价格
        current_price: Optional[float] = None, # 当前价格
        date_idx: int = 0,              # 交易日索引
    ) -> Dict:
        """
        计算目标仓位

        Args:
            phase: 操盘阶段 'BUILDING'/'WASHING'/'RAISING'/'SHIPPING'/'SUPPORT'
            signal_result: _combine_signals 的输出
                {'action': str, 'reason': str, 'target_position': float, 'priority': int}
            market_condition: 大盘环境 'GOOD'/'POOR'/'UNKNOWN'
            circuit_breaker: CircuitBreaker 输出的熔断信息

        Returns:
            {'target_position': float, 'action': str, 'reason': str,
             'breakdown': Dict}  # 分步计算明细
        """
        breakdown = {}

        # ---- 步骤1: 基础仓位 ----
        base = self.PHASE_BASE_POSITION.get(phase, 0.30)
        breakdown['base_position'] = base
        breakdown['phase'] = phase

        # ---- 步骤2: 信号调整 ----
        signal_action = signal_result.get('action', 'HOLD')
        signal_adjust = self.SIGNAL_ADJUSTMENT.get(signal_action, 0.0)

        # S_DIVERG_SELL 特殊处理：使用信号自身的 position_adjustment
        if signal_action == 'REDUCE' and 'position_adjustment' in signal_result:
            signal_adjust = signal_result['position_adjustment']

        # 卖出/止损信号直接覆盖为0
        if signal_action in ('SELL',):
            signal_adjust = 0.0

        breakdown['signal_action'] = signal_action
        breakdown['signal_adjustment'] = signal_adjust

        # 信号调整后的目标仓位
        if signal_action == 'BUY':
            # 买入：基础仓位 * 信号乘数
            position = base * signal_adjust
            # 如果是 BUY 信号且有明确 target_position，使用它
            if 'target_position' in signal_result and signal_result['target_position'] is not None:
                position = signal_result['target_position']
            # 金字塔建仓：用多级入场替代一次性满仓
            if symbol is not None:
                tier_info = self._get_pyramid_tier_info(
                    symbol, signal_action,
                    entry_price or current_price or 0,
                    date_idx,
                    current_price or 0
                )
                position *= tier_info['tier_ratio']
                breakdown['pyramid'] = tier_info
        elif signal_action == 'SELL' or signal_action == 'REDUCE':
            # 卖出/减仓：使用信号的 target_position
            position = signal_result.get('target_position', 0.0)
            # target_position=None 时默认为0
            if position is None:
                position = 0.0
            # 清仓时重置金字塔状态
            if symbol is not None:
                self.reset_pyramid(symbol)
        else:
            # HOLD / 无信号
            position = self._current_position

        breakdown['after_signal'] = position

        # ---- 步骤3: 大盘环境调整 ----
        market_mult = self.MARKET_MULTIPLIER.get(market_condition, 0.7)
        position *= market_mult
        breakdown['market_condition'] = market_condition
        breakdown['market_multiplier'] = market_mult
        breakdown['after_market'] = position

        # ---- 步骤4: 熔断检查 ----
        if circuit_breaker and circuit_breaker.get('triggered', False):
            breaker_action = circuit_breaker.get('action', 'NONE')
            if breaker_action == 'LIQUIDATE_ALL':
                position = 0.0
                breakdown['circuit_breaker'] = 'LIQUIDATE_ALL'
            elif breaker_action == 'LIQUIDATE_50':
                position *= 0.5
                breakdown['circuit_breaker'] = 'LIQUIDATE_50'
            else:
                breakdown['circuit_breaker'] = 'NONE'
        else:
            breakdown['circuit_breaker'] = 'NONE'

        breakdown['after_circuit_breaker'] = position

        # ---- 步骤5: 限仓 ----
        max_allowed = self.PHASE_BASE_POSITION.get(phase, 0.30)

        # 大盘差时额外限仓40%
        if market_condition == 'POOR':
            max_allowed = min(max_allowed, 0.40)

        # 卖出/止损信号不限制（可以直接清仓）
        if signal_action not in ('SELL', 'REDUCE'):
            position = min(position, max_allowed)

        position = max(0.0, min(1.0, position))
        breakdown['max_allowed'] = max_allowed
        breakdown['final_position'] = position

        # 确定操作方向
        if position > self._current_position + 0.01:
            action = 'BUY'
        elif position < self._current_position - 0.01:
            action = 'SELL'
        else:
            action = 'HOLD'

        reasons = []
        if signal_result.get('reason'):
            reasons.append(signal_result['reason'])
        if breakdown.get('circuit_breaker', 'NONE') != 'NONE':
            reasons.append(f"熔断: {breakdown['circuit_breaker']}")
        if not reasons:
            reasons.append('仓位维持')

        return {
            'target_position': round(position, 4),
            'action': action,
            'reason': '; '.join(reasons),
            'breakdown': breakdown,
        }

    def get_phase_base(self, phase: str) -> float:
        """获取指定阶段的基准仓位"""
        return self.PHASE_BASE_POSITION.get(phase, 0.30)
