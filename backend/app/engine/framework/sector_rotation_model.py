"""
板块轮动模型 - Sector Rotation Model
评估股票所属板块在当前市场环境中的轮动状态
"""

from typing import Dict, List, Optional
import pandas as pd
import numpy as np


class SectorRotationModel:
    """
    板块轮动模型

    通过股票自身收益率的多周期分析，近似评估其在板块中的相对位置
    和轮动状态（领先/走强/走弱/滞后/未知）。
    由于缺少实时全市场板块指数数据，采用简化模型：
    将股票自身多周期收益率作为板块轮动状态的代理指标。
    """

    # 轮动状态常量
    LEADING = 'LEADING'
    STRENGTHENING = 'STRENGTHENING'
    WEAKENING = 'WEAKENING'
    LAGGING = 'LAGGING'
    UNKNOWN = 'UNKNOWN'

    def __init__(self):
        self._name = 'SectorRotationModel'

    @property
    def name(self) -> str:
        return self._name

    def get_sector_data(self, ts_code: str, df: pd.DataFrame) -> Dict:
        """
        获取股票的行业/概念数据。
        由于无法实时获取全市场同板块股票进行比对，
        返回股票的行业信息（近似替代板块分析）。

        Args:
            ts_code: 股票代码
            df: 股票行情数据 DataFrame（需含 close 列）

        Returns:
            Dict: {
                'industry': str or '',
                'industry_source': str,
                'has_sector_data': bool
            }
        """
        result = {
            'industry': '',
            'industry_source': 'df_attr',
            'has_sector_data': False,
        }

        # 尝试从 DataFrame 的 attrs 或 columns 中获取行业信息
        if df is not None and not df.empty:
            # 检查 DataFrame 是否有 industry 列
            if 'industry' in df.columns:
                try:
                    val = df['industry'].iloc[-1]
                    if pd.notna(val) and str(val).strip():
                        result['industry'] = str(val).strip()
                        result['has_sector_data'] = True
                        return result
                except (IndexError, KeyError, TypeError):
                    pass

            # 检查 DataFrame attrs
            try:
                attrs = getattr(df, 'attrs', {}) or {}
                for key in ('industry', '行业', 'sector', '板块'):
                    val = attrs.get(key, '')
                    if val and str(val).strip():
                        result['industry'] = str(val).strip()
                        result['industry_source'] = 'df_attrs'
                        result['has_sector_data'] = True
                        return result
            except (AttributeError, TypeError):
                pass

        # 尝试通过 DataManager 获取行业分类
        try:
            from app.data import DataManager
            dm = DataManager()
            ind_data = dm.get_industry(ts_code)
            if ind_data is not None and not ind_data.empty:
                # 取第一条行业记录
                industry_val = ind_data.iloc[0].get('industry', '') if isinstance(
                    ind_data.iloc[0], (dict, pd.Series)
                ) else ''
                if industry_val and str(industry_val).strip():
                    result['industry'] = str(industry_val).strip()
                    result['industry_source'] = 'tushare'
                    result['has_sector_data'] = True
                    return result
        except Exception:
            pass

        return result

    def calc_sector_strength(
        self,
        ts_code: str,
        df: pd.DataFrame,
        market_context: Optional[Dict] = None,
    ) -> float:
        """
        计算板块轮动强度分数。
        通过股票自身收益率分析近似评估板块强度。

        Args:
            ts_code: 股票代码
            df: 股票行情数据（需含 close 列，至少 20 个交易日）
            market_context: 市场上下文（可选，可含 industry 等信息）

        Returns:
            float: -1.0 到 1.0 的分数，正值表示强势，负值表示弱势
        """
        if df is None or df.empty or 'close' not in df.columns:
            return 0.0

        try:
            close = df['close'].values
            if len(close) < 5:
                return 0.0

            # 1. 计算多周期收益率
            ret_5d = (close[-1] / close[-5] - 1) if len(close) >= 5 else 0.0
            ret_20d = (close[-1] / close[max(0, len(close) - 20)] - 1) if len(close) >= 20 else ret_5d

            # 2. 计算相对强度（股票收益率 vs 自身历史）
            # 以 20 日收益率序列的 80% 分位点作为基准
            if len(close) >= 40:
                # 滚动计算 20 日收益率序列
                rolling_returns = []
                for i in range(20, len(close)):
                    rr = close[i] / close[i - 20] - 1
                    rolling_returns.append(rr)
                if rolling_returns:
                    p80 = np.percentile(rolling_returns, 80)
                    p20 = np.percentile(rolling_returns, 20)
                    # 相对强度 = (当前收益 - p20) / (p80 - p20)，截断到 [-1, 1]
                    spread = p80 - p20
                    if spread > 1e-8:
                        raw_relative = (ret_20d - p20) / spread
                        relative_strength = max(-1.0, min(1.0, raw_relative))
                    else:
                        relative_strength = 0.0
                else:
                    relative_strength = 0.0
            else:
                relative_strength = 0.0

            # 3. 市场广度近似（如有市场上下文）
            breadth_factor = 0.0
            if market_context:
                market_breadth = market_context.get('market_breadth', None)
                if market_breadth is not None:
                    # market_breadth 假设在 [-1, 1] 范围
                    breadth_factor = float(market_breadth) * 0.3  # 广度权重 0.3

            # 4. 综合评分
            # 权重：近期动量 0.4，相对强度 0.4，市场广度 0.2
            momentum_score = max(-1.0, min(1.0, ret_20d * 5.0))  # 20% 收益映射到 1.0
            score = (
                0.4 * momentum_score
                + 0.4 * relative_strength
                + 0.2 * breadth_factor
            )

            return max(-1.0, min(1.0, score))

        except Exception:
            return 0.0

    def evaluate(
        self,
        ts_code: str,
        df: pd.DataFrame,
        market_context: Optional[Dict] = None,
    ) -> Dict:
        """
        综合评估股票的板块轮动状态。

        Args:
            ts_code: 股票代码
            df: 股票行情数据（需含 close 列）
            market_context: 市场上下文（可选）

        Returns:
            Dict: {
                'rotation_state': str,      # LEADING/STRENGTHENING/WEAKENING/LAGGING/UNKNOWN
                'sector_score': float,      # -1.0 ~ 1.0
                'confidence': float,         # 0.0 ~ 1.0
                'evidence': List[str],       # 判断依据列表
            }
        """
        evidence: List[str] = []
        rotation_state = self.UNKNOWN
        sector_score = 0.0
        confidence = 0.0

        if df is None or df.empty or 'close' not in df.columns:
            return {
                'rotation_state': rotation_state,
                'sector_score': sector_score,
                'confidence': confidence,
                'evidence': ['数据不足'],
            }

        try:
            close = df['close'].values
            has_5d = len(close) >= 5
            has_20d = len(close) >= 20

            ret_5d = (close[-1] / close[-5] - 1) if has_5d else None
            ret_20d = (close[-1] / close[max(0, len(close) - 20)] - 1) if has_20d else None

            sector_data = self.get_sector_data(ts_code, df)
            industry = sector_data.get('industry', '')

            if industry:
                evidence.append(f'所属行业/板块: {industry}')

            # 根据规则判定轮动状态
            if has_20d and ret_20d is not None:
                if ret_20d > 0.10:
                    rotation_state = self.LEADING
                    evidence.append(f'20日涨幅 {ret_20d:.2%} > 10%，板块领先')
                    confidence = min(1.0, abs(ret_20d) * 5.0)
                elif ret_20d > 0.05 and has_5d and ret_5d is not None and ret_5d > 0:
                    rotation_state = self.STRENGTHENING
                    evidence.append(f'20日涨幅 {ret_20d:.2%} > 5%，近5日为正 {ret_5d:.2%}，板块走强')
                    confidence = min(1.0, abs(ret_20d) * 5.0)
                elif ret_20d < -0.10:
                    rotation_state = self.LAGGING
                    evidence.append(f'20日涨幅 {ret_20d:.2%} < -10%，板块滞后')
                    confidence = min(1.0, abs(ret_20d) * 5.0)
                elif ret_20d < -0.05 and has_5d and ret_5d is not None and ret_5d < 0:
                    rotation_state = self.WEAKENING
                    evidence.append(f'20日涨幅 {ret_20d:.2%} < -5%，近5日为负 {ret_5d:.2%}，板块走弱')
                    confidence = min(1.0, abs(ret_20d) * 5.0)
                else:
                    evidence.append(f'20日涨幅 {ret_20d:.2%}，未触发明显轮动信号')
                    confidence = 0.2

            # 计算 sector_score
            sector_score = self.calc_sector_strength(ts_code, df, market_context)

            # 如果没有足够数据，默认 UNKNOWN
            if not has_20d:
                evidence.append('数据不足20个交易日，无法判断轮动状态')
                confidence = 0.0

        except Exception as e:
            evidence.append(f'评估过程异常: {str(e)}')
            rotation_state = self.UNKNOWN
            sector_score = 0.0
            confidence = 0.0

        return {
            'rotation_state': rotation_state,
            'sector_score': round(sector_score, 4),
            'confidence': round(confidence, 4),
            'evidence': evidence,
        }
