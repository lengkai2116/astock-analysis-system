"""
拥挤度因子模型 - Crowding Factor
评估股票的筹码拥挤程度，从融资余额、换手率和波动率三个维度综合判断
"""

from typing import Dict, List, Optional
import pandas as pd
import numpy as np


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

    def calc_margin_ratio(self, ts_code: str) -> Optional[float]:
        """
        计算融资余额占比。
        融资余额占比 = 融资余额 / 流通市值。

        Args:
            ts_code: 股票代码

        Returns:
            Optional[float]: 融资余额占比，数据不可用时返回 None
        """
        try:
            from app.data import DataManager
            dm = DataManager()
            margin_df = dm.get_margin(ts_code)

            if margin_df is None or margin_df.empty:
                return None

            # 取最新一条融资数据
            latest = margin_df.iloc[-1]

            # 尝试获取融资余额和流通市值
            margin_balance = None
            circ_mv = None

            if isinstance(latest, (dict, pd.Series)):
                for col in ('marge_balance', '融资余额', 'marge', 'balance'):
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

            if margin_balance is not None and circ_mv is not None and circ_mv > 0:
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
            margin_ratio = self.calc_margin_ratio(ts_code)
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

        # 有效信号计数（排除数据不可用的维度）
        valid_signals = sum([
            1 if margin_ratio is not None else 0,
            1,  # 换手率总有结果
            1,  # 波动率总有结果
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
