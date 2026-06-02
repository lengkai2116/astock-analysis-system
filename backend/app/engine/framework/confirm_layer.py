"""
辅助验证层 - Phase 2 模块6
对应书本第9章§9.3

功能：
  1. 换手率验证 — 低换手折扣/高换手加强卖出
  2. 转移速度验证 — 加速期追高风险
  3. 五档盘口不平衡验证（QMT增强，标注可选）
  4. 假突破过滤器 — 量+时间+深度三维确认
"""
from typing import Dict, Optional
import pandas as pd
import numpy as np


class ConfirmLayer:
    """
    多层辅助验证层
    对候选信号进行多层验证，返回调整后的置信度和仓位建议
    """

    def verify(self, signal: Dict, context: Dict) -> Dict:
        """
        对候选信号进行多层验证

        Args:
            signal: 待验证的信号
                {'signal_type': 'BUY'|'SELL', 'confidence': float, 'position': float, ...}
            context: 上下文数据
                {'turnover_rate': float, 'transfer_speed': float,
                 'vol_ratio': float, 'cyqkl': float, 'breakout_days': int,
                 'has_qmt': bool, 'order_imbalance': float,
                 'close_prices': List[float], 'breakout_price': float}

        Returns:
            {'action': 'HOLD'|'PASS', 'reason': str,
             'confidence': float, 'position': float}
        """
        confidence = signal.get('confidence', 0.5)
        position = signal.get('position', 0.5)
        signal_type = signal.get('signal_type', 'BUY')

        reasons = []

        # 1. 换手率验证
        turnover = context.get('turnover_rate', None)
        if turnover is not None:
            adj = self._verify_turnover(turnover, signal_type)
            confidence *= adj.get('confidence_mult', 1.0)
            if adj.get('reason'):
                reasons.append(adj['reason'])

        # 2. 转移速度验证
        transfer_speed = context.get('transfer_speed', None)
        if transfer_speed is not None:
            adj = self._verify_transfer_speed(transfer_speed, signal_type)
            confidence *= adj.get('confidence_mult', 1.0)
            position *= adj.get('position_mult', 1.0)
            if adj.get('reason'):
                reasons.append(adj['reason'])

        # 3. 五档盘口不平衡验证（QMT增强项）
        if context.get('has_qmt', False):
            imbalance = context.get('order_imbalance', 0)
            adj = self._verify_order_imbalance(imbalance, signal_type)
            confidence *= adj.get('confidence_mult', 1.0)
            if adj.get('reason'):
                reasons.append(adj['reason'])

        # 4. 假突破过滤器
        breakout_check = self._false_breakout_check(context)
        if not breakout_check['passed']:
            return {
                'action': 'HOLD',
                'reason': "假突破过滤: " + breakout_check['reason'],
                'confidence': 0.0,
                'position': 0.0
            }

        return {
            'action': 'PASS',
            'reason': '; '.join(reasons) if reasons else '全部验证通过',
            'confidence': round(confidence, 4),
            'position': round(position, 4)
        }

    # ---------- 子验证方法 ----------

    def _verify_turnover(self, turnover_rate: float, signal_type: str) -> Dict:
        """
        换手率验证（书本第3章§3.6）

        规则：
          turnover < 2%   -> 低活跃度，置信度*0.5
          turnover > 10%  -> SELL加强(1.2), BUY警惕(0.8)
          其他 -> 正常
        """
        if turnover_rate < 0.02:
            return {
                'confidence_mult': 0.5,
                'reason': "换手率{:.2f}%<2%(低活跃)".format(turnover_rate * 100)
            }
        elif turnover_rate > 0.10:
            if signal_type == 'SELL':
                return {
                    'confidence_mult': 1.2,
                    'reason': "换手率{:.2f}%>10%(卖出验证)".format(turnover_rate * 100)
                }
            else:
                return {
                    'confidence_mult': 0.8,
                    'reason': "换手率{:.2f}%>10%(买入警惕)".format(turnover_rate * 100)
                }
        return {'confidence_mult': 1.0, 'reason': ''}

    def _verify_transfer_speed(self, transfer_speed: float, signal_type: str) -> Dict:
        """
        转移速度验证（筹码加速转移时追高风险）

        规则：
          transfer_speed > 1%/日 -> 加速期
            BUY信号: confidence*0.8, position*0.7
            其他信号: 无调整
        """
        if transfer_speed > 0.01 and signal_type == 'BUY':
            return {
                'confidence_mult': 0.8,
                'position_mult': 0.7,
                'reason': "筹码加速转移({:.2f}%/日)追高风险".format(transfer_speed * 100)
            }
        return {'confidence_mult': 1.0, 'position_mult': 1.0, 'reason': ''}

    def _verify_order_imbalance(self, imbalance: float, signal_type: str) -> Dict:
        """
        五档盘口不平衡验证（QMT增强项）
        """
        if signal_type == 'BUY' and imbalance > 0.2:
            return {'confidence_mult': 1.15, 'reason': '盘口买盘旺盛'}
        elif signal_type == 'SELL' and imbalance < -0.2:
            return {'confidence_mult': 1.15, 'reason': '盘口卖盘旺盛'}
        elif signal_type == 'BUY' and imbalance < -0.1:
            return {'confidence_mult': 0.8, 'reason': '信号与盘口方向相反'}
        return {'confidence_mult': 1.0, 'reason': ''}

    def _false_breakout_check(self, context: Dict) -> Dict:
        """
        假突破过滤器 - 三维确认（书本第9章§9.3）

        维度1: 量能确认 - 突破日 vol_ratio >= 1.5
        维度2: 时间确认 - 突破后连续N日未回落
        维度3: 深度确认 - CYQKL >= 20%

        Returns:
            {'passed': bool, 'reason': str}
        """
        # 维度1：量能确认
        vol_ratio = context.get('vol_ratio', 0)
        if vol_ratio < 1.5:
            return {
                'passed': False,
                'reason': "量能不足(vol_ratio={:.2f}<1.5)".format(vol_ratio)
            }

        # 维度2：时间确认（突破后3日未回落）
        breakout_days = context.get('breakout_days', 0)
        if breakout_days < 3:
            return {
                'passed': False,
                'reason': "突破时间不足(breakout_days={}<3)".format(breakout_days)
            }

        # 维度3：深度确认（CYQKL >= 20%）
        cyqkl = context.get('cyqkl', 0)
        if cyqkl < 0.2:
            return {
                'passed': False,
                'reason': "穿透深度不足(cyqkl={:.2f}<0.2)".format(cyqkl)
            }

        return {'passed': True, 'reason': ''}

    def check_false_breakout(self, df: pd.DataFrame, indicators: Dict) -> Dict:
        """
        便捷的假突破检查接口，从K线和指标上下文中提取参数

        Args:
            df: K线数据
            indicators: 筹码指标字典

        Returns:
            {'is_real': bool, 'reason': str, 'details': Dict}
        """
        if df.empty or len(df) < 5:
            return {'is_real': False, 'reason': '数据不足', 'details': {}}

        latest = df.iloc[-1]
        closes = df['close'].values

        # 判断是否处于突破状态（价格在近期高位）
        if len(closes) >= 20:
            max_20 = np.max(closes[-20:])
            is_at_high = latest['close'] >= max_20 * 0.98
        else:
            is_at_high = False

        if not is_at_high:
            return {'is_real': False, 'reason': '非突破状态', 'details': {}}

        # 计算突破持续天数
        breakout_days = 0
        if len(closes) >= 3 and is_at_high:
            breakout_level = max_20 * 0.98
            for i in range(len(closes) - 1, -1, -1):
                if closes[i] >= breakout_level:
                    breakout_days += 1
                else:
                    break

        context = {
            'vol_ratio': indicators.get('vol_ratio', 0),
            'breakout_days': breakout_days,
            'cyqkl': indicators.get('cyqkl', 0),
        }

        result = self._false_breakout_check(context)
        return {
            'is_real': result['passed'],
            'reason': result['reason'],
            'details': context
        }
