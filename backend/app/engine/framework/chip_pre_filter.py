"""
筹码分布策略 - 前置过滤层（Phase 1）
对应书本：第0层市场环境与股票过滤 + 第7章大盘环境 + 第9章市值适配/新股排除/流动性过滤

功能：
  1. MarketEnvironmentFilter — 大盘环境判断（沪深300±60日均线）
  2. EligibilityFilter — 新股排除（上市<250交易日）
  3. LiquidityFilter — 流动性过滤（换手率<2%排除）
  4. MarketCapAdapter — 市值适配（不同市值不同参数集）
  5. CircuitBreaker — 熔断规则（大盘单日跌幅>5%触发）
"""
from typing import Dict, Optional, Tuple
from datetime import datetime, date
import pandas as pd
import numpy as np

from app.services.benchmark_service import BenchmarkService, BenchmarkIndex
from app.data import DataManager


class MarketEnvironmentFilter:
    """大盘环境判断器 - 书本第7章§7.4"""

    def __init__(self, benchmark_service: Optional[BenchmarkService] = None):
        self.benchmark = benchmark_service or BenchmarkService()

    def check(self, index_code: str = BenchmarkIndex.HS300) -> Dict:
        """
        检查大盘环境

        规则（书本§7.4）：
          沪深300在60日均线上方 → GOOD, 仓位上限70%
          沪深300在60日均线下方 → POOR, 仓位上限40%

        Returns:
            {'condition': 'GOOD'|'POOR',
             'max_position': 0.7|0.4,
             'position_multiplier': 1.0|0.5,
             'ma60': float,
             'current_close': float,
             'days_since_cross': int}  # 突破/跌破60日线持续天数
        """
        df = self.benchmark.get_index_daily(
            ts_code=index_code,
            start_date=(datetime.now() - pd.Timedelta(days=365)).strftime('%Y%m%d')
        )

        if df.empty or len(df) < 60:
            return {
                'condition': 'UNKNOWN',
                'max_position': 0.5,
                'position_multiplier': 0.7,
                'ma60': 0,
                'current_close': 0,
                'days_since_cross': 0,
                'reason': '数据不足'
            }

        closes = df['close'].values
        ma60 = pd.Series(closes).rolling(60).mean().values
        current_close = float(closes[-1])
        current_ma60 = float(ma60[-1])

        # 计算突破/跌破60日线的持续天数
        days_since = 0
        for i in range(len(closes) - 1, -1, -1):
            if (current_close > current_ma60 and closes[i] > ma60[i]) or \
               (current_close <= current_ma60 and closes[i] <= ma60[i]):
                days_since += 1
            else:
                break

        if current_close > current_ma60:
            return {
                'condition': 'GOOD',
                'max_position': 0.7,
                'position_multiplier': 1.0,
                'ma60': round(current_ma60, 2),
                'current_close': current_close,
                'days_since_cross': days_since,
                'reason': f'沪深300({current_close:.0f}) > 60日均线({current_ma60:.0f})，持续{days_since}日'
            }
        else:
            return {
                'condition': 'POOR',
                'max_position': 0.4,
                'position_multiplier': 0.5,
                'ma60': round(current_ma60, 2),
                'current_close': current_close,
                'days_since_cross': days_since,
                'reason': f'沪深300({current_close:.0f}) ≤ 60日均线({current_ma60:.0f})，持续{days_since}日'
            }


class CircuitBreaker:
    """熔断检查器 - 书本第9章§9.5"""

    def __init__(self, benchmark_service: Optional[BenchmarkService] = None):
        self.benchmark = benchmark_service or BenchmarkService()

    def check(self, index_code: str = BenchmarkIndex.HS300) -> Dict:
        """
        熔断检查

        规则（书本§9.5）：
          大盘单日跌幅>5% → 平仓50%
          大盘连续3日下跌且累计>8% → 清空所有仓位

        Returns:
            {'triggered': True|False,
             'action': 'LIQUIDATE_50'|'LIQUIDATE_ALL'|'NONE',
             'reason': str}
        """
        df = self.benchmark.get_index_daily(
            ts_code=index_code,
            start_date=(datetime.now() - pd.Timedelta(days=30)).strftime('%Y%m%d')
        )

        if df.empty or len(df) < 5:
            return {'triggered': False, 'action': 'NONE', 'reason': '数据不足'}

        closes = df['close'].values
        pct_chg = df.get('pct_chg', df['close'].pct_change() * 100).values

        # 最近5日数据
        recent_pct = pct_chg[-5:]
        recent_closes = closes[-5:]

        # 规则1：单日跌幅>5%
        latest_pct = recent_pct[-1] if not np.isnan(recent_pct[-1]) else 0
        if latest_pct < -5:
            return {
                'triggered': True,
                'action': 'LIQUIDATE_50',
                'reason': f'大盘单日跌幅{abs(latest_pct):.1f}% > 5%，触发熔断，减仓50%'
            }

        # 规则2：连续3日下跌且累计>8%
        consecutive_days = 0
        cumulative = 0
        for p in reversed(recent_pct):
            if np.isnan(p):
                break
            if p < 0:
                consecutive_days += 1
                cumulative += abs(p)
            else:
                break

        if consecutive_days >= 3 and cumulative > 8:
            return {
                'triggered': True,
                'action': 'LIQUIDATE_ALL',
                'reason': f'大盘连续{consecutive_days}日下跌，累计跌幅{cumulative:.1f}% > 8%，清空仓位'
            }

        return {'triggered': False, 'action': 'NONE', 'reason': '正常'}


class EligibilityFilter:
    """新股过滤器 - 书本第9章§9.6"""

    def __init__(self):
        self._stock_info_cache = {}

    def check(self, ts_code: str) -> Dict:
        """
        检查股票是否满足上市时间要求

        规则（书本§9.6）：
          上市不满250个交易日的股票排除

        Returns:
            {'passed': True|False, 'reason': str, 'days_listed': int}
        """
        from app.models import Stock
        stock = Stock.query.get(ts_code)
        if stock is None or stock.list_date is None:
            return {'passed': False, 'reason': '无法获取上市日期', 'days_listed': 0}

        if isinstance(stock.list_date, str):
            list_date = datetime.strptime(stock.list_date, '%Y-%m-%d').date()
        else:
            list_date = stock.list_date

        days_listed = (date.today() - list_date).days

        if days_listed < 250:
            return {
                'passed': False,
                'reason': f'上市仅{days_listed}天，不足250个交易日标准',
                'days_listed': days_listed
            }

        return {'passed': True, 'reason': '', 'days_listed': days_listed}


class LiquidityFilter:
    """流动性过滤器 - 书本第3章§3.6"""

    def __init__(self, data_manager: Optional[DataManager] = None):
        self.data_manager = data_manager or DataManager()

    def check(self, ts_code: str) -> Dict:
        """
        检查股票流动性

        规则（书本§3.6）：
          换手率<2% → 低活跃度，排除
          换手率2%~5% → 正常
          换手率5%~10% → 活跃
          换手率≥10% → 极高活跃，出货期警惕

        使用最近20个交易日的平均换手率作为判断依据

        Returns:
            {'passed': bool, 'turnover_rate': float, 'status': str}
        """
        df = self.data_manager.get_cached_daily_basic(
            ts_code,
            start_date=(datetime.now() - pd.Timedelta(days=60)).strftime('%Y-%m-%d')
        )

        if df.empty or 'turnover_rate' not in df.columns:
            return {
                'passed': True,
                'turnover_rate': 0,
                'status': '未知',
                'reason': '无换手率数据，默认通过'
            }

        recent = df['turnover_rate'].dropna().tail(20)
        if len(recent) == 0:
            return {
                'passed': True,
                'turnover_rate': 0,
                'status': '未知',
                'reason': '换手率数据为空，默认通过'
            }

        avg_turnover = float(recent.mean())

        if avg_turnover < 2.0:
            return {
                'passed': False,
                'turnover_rate': round(avg_turnover, 2),
                'status': '低活跃度',
                'reason': f'20日平均换手率{avg_turnover:.2f}% < 2%，流动性不足'
            }
        elif avg_turnover < 5.0:
            return {
                'passed': True,
                'turnover_rate': round(avg_turnover, 2),
                'status': '正常',
                'reason': ''
            }
        elif avg_turnover < 10.0:
            return {
                'passed': True,
                'turnover_rate': round(avg_turnover, 2),
                'status': '活跃',
                'reason': ''
            }
        else:
            return {
                'passed': True,
                'turnover_rate': round(avg_turnover, 2),
                'status': '极高',
                'reason': '换手率极高，注意出货风险'
            }


class MarketCapAdapter:
    """市值适配器 - 书本第9章§9.4"""

    def __init__(self, data_manager: Optional[DataManager] = None):
        self.data_manager = data_manager or DataManager()

    def get_parameters(self, ts_code: str) -> Dict:
        """
        根据市值获取适配参数集

        规则（书本§9.4）：
          <50亿(小盘)     → 标准参数
          50~200亿(中盘)  → 放宽成交量倍数0.2
          200~1000亿(大盘) → CYQKL阈值降低5
          >1000亿(超大盘) → 不作为主策略

        Returns:
            {'cap_level': str, 'param_adjustments': Dict, 'circ_mv': float}
        """
        df = self.data_manager.get_cached_daily_basic(
            ts_code,
            start_date=(datetime.now() - pd.Timedelta(days=30)).strftime('%Y-%m-%d')
        )

        if df.empty or 'circ_mv' not in df.columns:
            return {'cap_level': 'UNKNOWN', 'circ_mv': 0, 'param_adjustments': {}}

        circ_mv = float(df['circ_mv'].dropna().iloc[-1])

        if circ_mv < 50:  # 亿
            return {
                'cap_level': 'SMALL',
                'circ_mv': circ_mv,
                'param_adjustments': {}
            }
        elif circ_mv < 200:
            return {
                'cap_level': 'MID',
                'circ_mv': circ_mv,
                'param_adjustments': {'vol_multiplier_boost': 0.2}
            }
        elif circ_mv < 1000:
            return {
                'cap_level': 'LARGE',
                'circ_mv': circ_mv,
                'param_adjustments': {'cyqkl_threshold_reduction': -5}
            }
        else:
            return {
                'cap_level': 'MEGA',
                'circ_mv': circ_mv,
                'param_adjustments': {'is_secondary': True}
            }


class ChipPreFilter:
    """
    筹码策略前置过滤器（主入口）
    
    按书本第0层-第9章的过滤逻辑，串联所有前置检查。
    输出一个统一的过滤结果，供后续策略模块使用。
    """

    def __init__(self):
        self.market_filter = MarketEnvironmentFilter()
        self.circuit_breaker = CircuitBreaker()
        self.eligibility_filter = EligibilityFilter()
        self.liquidity_filter = LiquidityFilter()
        self.cap_adapter = MarketCapAdapter()

    def filter_market(self) -> Dict:
        """大盘环境过滤"""
        env = self.market_filter.check()
        breaker = self.circuit_breaker.check()

        result = {
            'environment': env,
            'circuit_breaker': breaker,
            'overall_position_multiplier': env['position_multiplier'],
            'overall_max_position': env['max_position']
        }

        # 熔断覆盖大盘环境
        if breaker['triggered']:
            if breaker['action'] == 'LIQUIDATE_ALL':
                result['overall_position_multiplier'] = 0.0
                result['overall_max_position'] = 0.0
            elif breaker['action'] == 'LIQUIDATE_50':
                result['overall_position_multiplier'] *= 0.5
                result['overall_max_position'] *= 0.5

        return result

    def filter_stock(self, ts_code: str) -> Dict:
        """
        对单只股票执行完整的过滤检查

        Returns:
            {
                'passed': True|False,   # 是否通过所有检查
                'reasons': [str],       # 未通过原因列表
                'turnover_rate': float,  # 换手率
                'cap_level': str,        # 市值等级
                'circ_mv': float,        # 流通市值
                'days_listed': int,      # 上市天数
                'param_adjustments': {}  # 参数调整
            }
        """
        reasons = []
        passed = True

        # 1. 新股排除
        elig = self.eligibility_filter.check(ts_code)
        if not elig['passed']:
            passed = False
            reasons.append(elig['reason'])

        # 2. 流动性过滤
        liq = self.liquidity_filter.check(ts_code)
        if not liq['passed']:
            passed = False
            reasons.append(liq['reason'])

        # 3. 市值适配（不排除股票，只调整参数）
        cap = self.cap_adapter.get_parameters(ts_code)
        if cap.get('cap_level') == 'MEGA':
            reasons.append('超大盘股，仅作为次要策略')

        # 整理换手率
        turnover_rate = 0.0
        if 'turnover_rate' in liq:
            turnover_rate = liq['turnover_rate']

        return {
            'passed': passed,
            'reasons': reasons,
            'turnover_rate': turnover_rate,
            'cap_level': cap.get('cap_level', 'UNKNOWN'),
            'circ_mv': cap.get('circ_mv', 0),
            'days_listed': elig.get('days_listed', 0),
            'param_adjustments': cap.get('param_adjustments', {})
        }

    def filter_batch(self, ts_codes: list) -> Dict:
        """
        批量过滤股票，返回通过/未通过列表

        Returns:
            {
                'passed': [ts_code, ...],
                'failed': {ts_code: [reason, ...], ...},
                'market': {...}
            }
        """
        market = self.filter_market()

        passed = []
        failed = {}

        for code in ts_codes:
            result = self.filter_stock(code)
            if result['passed']:
                passed.append(code)
            else:
                failed[code] = result['reasons']

        return {
            'passed': passed,
            'failed': failed,
            'market': market
        }
