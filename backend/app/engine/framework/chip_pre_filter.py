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
                'sentiment': self.check_sentiment(),
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
                'sentiment': self.check_sentiment(),
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
                'sentiment': self.check_sentiment(),
                'reason': f'沪深300({current_close:.0f}) ≤ 60日均线({current_ma60:.0f})，持续{days_since}日'
            }



    def check_sentiment(self) -> Dict:
        """
        情绪周期辅助大盘过滤 (V2方向6)
        知识库依据: 六段论(筑底/复苏/确认/冲顶/钟摆/探底)
                    华泰非对称买卖策略

        使用全市场 daily_basic 数据的平均换手率作为代理情绪指标：
          恐慌(x0.5) / 正常(x1.0) / 活跃(x1.0) / 过热(x0.7)

        Returns:
            {'sentiment': 'PANIC'|'NORMAL'|'ACTIVE'|'OVERHEAT',
             'position_multiplier': float,
             'reason': str}
        """
        try:
            from app.data import DataManager
            dm = DataManager()
            # 获取最近2个交易日的全市场换手率
            df = dm.get_cached_daily_basic(
                ts_code='000300.SH',
                start_date=(datetime.now() - pd.Timedelta(days=60)).strftime('%Y-%m-%d')
            )
            if df.empty or 'turnover_rate' not in df.columns:
                return {'sentiment': 'NORMAL', 'position_multiplier': 1.0, 'reason': '无数据，默认正常'}

            recent = df['turnover_rate'].dropna().tail(5)
            if len(recent) == 0:
                return {'sentiment': 'NORMAL', 'position_multiplier': 1.0, 'reason': '无换手率数据'}

            avg_turnover = float(recent.mean())

            # 以历史经验阈值划分情绪周期
            if avg_turnover < 0.5:
                sentiment = 'PANIC'
                multiplier = 0.5
                reason = f'全市场换手率{avg_turnover:.2f}% < 0.5%，恐慌，仓位x0.5'
            elif avg_turnover < 1.5:
                sentiment = 'NORMAL'
                multiplier = 1.0
                reason = f'全市场换手率{avg_turnover:.2f}%，正常，仓位x1.0'
            elif avg_turnover < 3.0:
                sentiment = 'ACTIVE'
                multiplier = 1.0
                reason = f'全市场换手率{avg_turnover:.2f}%，活跃，仓位x1.0'
            else:
                sentiment = 'OVERHEAT'
                multiplier = 0.7
                reason = f'全市场换手率{avg_turnover:.2f}% > 3%，过热，仓位x0.7'

            return {
                'sentiment': sentiment,
                'position_multiplier': multiplier,
                'avg_turnover': round(avg_turnover, 2),
                'reason': reason
            }
        except Exception as e:
            return {'sentiment': 'NORMAL', 'position_multiplier': 1.0, 'reason': f'检测异常: {e}'}


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

    def __init__(self, data_manager: Optional[DataManager] = None):
        self.data_manager = data_manager or DataManager()
        self._stock_info_cache = {}

    def check(self, ts_code: str) -> Dict:
        """
        检查股票是否满足上市时间要求

        规则（书本§9.6）：
          上市不满250个交易日的股票排除

        Returns:
            {'passed': True|False, 'reason': str, 'days_listed': int}
        """
        # 优先从缓存获取
        if ts_code in self._stock_info_cache:
            list_date = self._stock_info_cache[ts_code]
        else:
            list_date = self._fetch_list_date(ts_code)
            if list_date:
                self._stock_info_cache[ts_code] = list_date

        if list_date is None:
            return {'passed': True, 'reason': '无法获取上市日期，默认通过', 'days_listed': 0}

        days_listed = (date.today() - list_date).days

        if days_listed < 250:
            return {
                'passed': False,
                'reason': f'上市仅{days_listed}天，不足250个交易日标准',
                'days_listed': days_listed
            }

        return {'passed': True, 'reason': '', 'days_listed': days_listed}

    def _fetch_list_date(self, ts_code: str) -> Optional[date]:
        """从多种来源获取上市日期"""
        # 1. 从 Stock ORM 模型获取（如果表存在且有数据）
        try:
            from app.models import Stock
            stock = Stock.query.get(ts_code)
            if stock is not None and stock.list_date is not None:
                if isinstance(stock.list_date, str):
                    return datetime.strptime(stock.list_date, '%Y-%m-%d').date()
                return stock.list_date
        except Exception:
            pass

        # 2. 从 DataManager stock_list 获取（akshare/tushare）
        try:
            stock_list = self.data_manager.get_stock_list()
            for s in stock_list:
                if s.get('ts_code') == ts_code:
                    ipo_date = s.get('list_date') or s.get('ipo_date')
                    if ipo_date:
                        if isinstance(ipo_date, str):
                            return datetime.strptime(ipo_date[:10], '%Y-%m-%d').date()
                        return ipo_date
        except Exception:
            pass

        return None


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

        # Phase 2: 财务风险过滤 + ROCE 指标
        self.financial_risk_filter = FinancialRiskFilter()
        self.roce_indicator = ROCEIndicator()

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

        # 情绪周期覆盖
        sentiment_info = env.get('sentiment', {})
        if isinstance(sentiment_info, dict) and sentiment_info.get('position_multiplier', 1.0) < 1.0:
            result['overall_position_multiplier'] *= sentiment_info['position_multiplier']
            result['overall_max_position'] *= sentiment_info['position_multiplier']

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


        # Phase 2: 财务风险检查
        fin_risk = self.financial_risk_filter.check(ts_code)
        if not fin_risk['passed']:
            passed = False
            reasons.extend(fin_risk['reasons'])

        # ROCE 指标（不排除股票，仅作为辅助参考）
        roce_result = self.roce_indicator.get_roce(ts_code)

        return {
            'passed': passed,
            'reasons': reasons,
            'turnover_rate': turnover_rate,
            'cap_level': cap.get('cap_level', 'UNKNOWN'),
            'circ_mv': cap.get('circ_mv', 0),
            'days_listed': elig.get('days_listed', 0),
            'param_adjustments': cap.get('param_adjustments', {}),
            'financial_risk': fin_risk,
            'roce': roce_result,
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


        # Phase 2: 财务风险检查
        fin_risk = self.financial_risk_filter.check(ts_code)
        if not fin_risk['passed']:
            passed = False
            reasons.extend(fin_risk['reasons'])

        # ROCE 指标（不排除股票，仅作为辅助参考）
        roce_result = self.roce_indicator.get_roce(ts_code)

        return {
            'passed': passed,
            'failed': failed,
            'market': market
        }


# ═══════════════════════════════════════════════
# Phase 2: 六大禁区过滤器 + ROCE 指标接入
# ═══════════════════════════════════════════════

class FinancialRiskFilter:
    """
    财务风险过滤器 — 覆盖六大禁区
    
    六大禁区：
      1. 业绩雷：净利润连续2年下滑或亏损
      2. 退市雷：ST/*ST/退市预警
      3. 财务雷：资产负债率异常/现金流为负
      4. 监管雷：被证监会立案调查/行政处罚
      5. 行业雷：行业政策风险（如双减/房地产三条红线）
      6. 流动性雷：日均成交额<500万（补充 LiquidityFilter）
    
    注：完整财务数据依赖 Tushare fina_vip 接口（需>=5000积分），
    当前在有限数据下优先使用 daily_basic 已有字段做初步过滤。
    """

    def __init__(self, data_manager=None):
        from app.data import DataManager
        self.data_manager = data_manager or DataManager()

    def check(self, ts_code: str) -> Dict:
        """
        执行六大禁区检查

        Returns:
            {'passed': bool, 'reasons': [str], 'details': Dict}
        """
        reasons = []
        details = {}

        # 1. 退市雷：检查股票代码和名称的ST标记
        st_check = self._check_st_status(ts_code)
        if not st_check['passed']:
            reasons.append(st_check['reason'])
        details['st_status'] = st_check

        # 2. 业绩雷：基于PE和daily_basic数据做初步判断
        profit_check = self._check_profit_risk(ts_code)
        if not profit_check['passed']:
            reasons.append(profit_check['reason'])
        details['profit_risk'] = profit_check

        # 3. 财务雷：基于资产负债率初步判断
        debt_check = self._check_debt_risk(ts_code)
        if not debt_check['passed']:
            reasons.append(debt_check['reason'])
        details['debt_risk'] = debt_check

        # 4. 流动性雷（补充）：成交额过滤
        liquid_check = self._check_liquidity_risk(ts_code)
        if not liquid_check['passed']:
            reasons.append(liquid_check['reason'])
        details['liquidity_risk'] = liquid_check

        # 5. 监管雷：从数据库/缓存中查找监管标记
        reg_check = self._check_regulatory_risk(ts_code)
        if not reg_check['passed']:
            reasons.append(reg_check['reason'])
        details['regulatory_risk'] = reg_check

        # 6. 行业雷：基于行业分类做初步判断
        industry_check = self._check_industry_risk(ts_code)
        if not industry_check['passed']:
            reasons.append(industry_check['reason'])
        details['industry_risk'] = industry_check


        # Phase 2: 财务风险检查
        fin_risk = self.financial_risk_filter.check(ts_code)
        if not fin_risk['passed']:
            passed = False
            reasons.extend(fin_risk['reasons'])

        # ROCE 指标（不排除股票，仅作为辅助参考）
        roce_result = self.roce_indicator.get_roce(ts_code)

        return {
            'passed': len(reasons) == 0,
            'reasons': reasons,
            'details': details,
        }

    def _check_st_status(self, ts_code: str) -> Dict:
        """检查退市雷：ST/*ST标记"""
        # 从股票简称判断：ST开头即为ST股
        try:
            from app.models import Stock
            stock = Stock.query.get(ts_code)
            if stock is not None:
                name = getattr(stock, 'name', '') or ''
                if name.startswith('*ST') or name.startswith('ST'):
                    return {'passed': False, 'reason': f'退市雷: {name} 为ST/*ST股，排除', 'name': name}
                if '退' in name:
                    return {'passed': False, 'reason': f'退市雷: {name} 已进入退市程序', 'name': name}
                return {'passed': True, 'reason': '', 'name': name}
        except Exception:
            pass

        # 从ts_code判断：以ST或退开头
        if ts_code.startswith('ST') or 'ST' in ts_code:
            return {'passed': False, 'reason': f'退市雷: {ts_code} 为风险警示股', 'name': ''}

        return {'passed': True, 'reason': '', 'name': ''}

    def _check_profit_risk(self, ts_code: str) -> Dict:
        """检查业绩雷：基于PE和daily_basic"""
        try:
            dm = self.data_manager
            df = dm.get_cached_daily_basic(
                ts_code,
                start_date=None
            )
            if df.empty or 'pe' not in df.columns and 'pe_ttm' not in df.columns:
                return {'passed': True, 'reason': '', 'detail': 'PE数据不足，默认通过'}

            pe_col = 'pe_ttm' if 'pe_ttm' in df.columns else 'pe'
            recent_pe = df[pe_col].dropna()

            if len(recent_pe) == 0:
                return {'passed': True, 'reason': '', 'detail': 'PE数据为空，默认通过'}

            latest_pe = float(recent_pe.iloc[-1])

            # PE为0：可能亏损（0 < PE < 合理值通常表示盈利）
            # PE为负：净利润为负 → 业绩雷
            if latest_pe < 0:
                return {
                    'passed': False,
                    'reason': f'业绩雷: PE={latest_pe:.2f}<0，净利润为负',
                    'detail': {'pe': latest_pe}
                }

            # PE极高（>300）：可能业绩剧烈波动
            if latest_pe > 300:
                return {
                    'passed': False,
                    'reason': f'业绩雷: PE={latest_pe:.2f}>300，业绩异常',
                    'detail': {'pe': latest_pe}
                }

            return {'passed': True, 'reason': '', 'detail': {'pe': latest_pe}}

        except Exception as e:
            return {'passed': True, 'reason': '', 'detail': f'检测异常: {e}'}

    def _check_debt_risk(self, ts_code: str) -> Dict:
        """检查财务雷：基于PE/市值辅助判断"""
        try:
            dm = self.data_manager
            df = dm.get_cached_daily_basic(
                ts_code,
                start_date=None
            )
            if df.empty:
                return {'passed': True, 'reason': '', 'detail': '数据不足，默认通过'}

            # 使用市值判断是否有财务雷嫌疑
            # 小市值+PE异常的组合
            if 'circ_mv' in df.columns:
                mv = float(df['circ_mv'].dropna().iloc[-1]) if not df['circ_mv'].dropna().empty else 0
                if mv < 5:  # 流通市值<5亿
                    return {
                        'passed': True,
                        'warning': True,
                        'reason': f'财务雷预警: 流通市值仅{mv:.1f}亿，需关注',
                        'detail': {'circ_mv': mv}
                    }

            return {'passed': True, 'reason': '', 'detail': {}}

        except Exception as e:
            return {'passed': True, 'reason': '', 'detail': f'检测异常: {e}'}

    def _check_liquidity_risk(self, ts_code: str) -> Dict:
        """检查流动性雷：日均成交额<500万"""
        try:
            dm = self.data_manager
            df = dm.get_cached_daily_data(ts_code)
            if df.empty:
                return {'passed': True, 'reason': '', 'detail': '数据不足，默认通过'}

            # 使用amount字段判断成交额
            amount_col = 'amount' if 'amount' in df.columns else 'vol'
            recent_amount = df[amount_col].dropna().tail(20)
            if len(recent_amount) == 0:
                return {'passed': True, 'reason': '', 'detail': '无成交额数据'}

            avg_amount = float(recent_amount.mean())
            if avg_amount < 5000000:  # 500万
                return {
                    'passed': False,
                    'reason': f'流动性雷: 20日日均成交额{avg_amount/10000:.0f}万 < 500万',
                    'detail': {'avg_amount': avg_amount}
                }

            return {'passed': True, 'reason': '', 'detail': {'avg_amount': avg_amount}}

        except Exception as e:
            return {'passed': True, 'reason': '', 'detail': f'检测异常: {e}'}

    def _check_regulatory_risk(self, ts_code: str) -> Dict:
        """检查监管雷：从数据库/缓存中查找监管标记"""
        # 当前无监管数据API接入，返回默认通过
        # TODO: 接入监管数据后，检查是否存在:
        #   - 证监会立案调查
        #   - 行政处罚
        #   - 交易所公开谴责
        #   - 业绩预告变脸
        return {'passed': True, 'reason': '', 'detail': '监管数据未接入，默认通过'}

    def _check_industry_risk(self, ts_code: str) -> Dict:
        """检查行业雷：基于行业分类"""
        # 当前无行业分类数据API
        # TODO: 接入行业分类数据后，检查:
        #   - 政策限制行业（如房地产三条红线）
        #   - 产能过剩行业
        #   - 衰退期行业
        return {'passed': True, 'reason': '', 'detail': '行业分类数据未接入，默认通过'}


class ROCEIndicator:
    """
    ROCE（资本回报率）指标接入
    
    ROCE = EBIT / (总资产 - 流动负债)
    用于评估公司资本使用效率。
    
    数据来源：Tushare fina_vip（需>=5000积分），当前为占位实现。
    可用的替代数据源：akshare 财务指标接口。
    """

    def __init__(self, data_manager=None):
        from app.data import DataManager
        self.data_manager = data_manager or DataManager()

    def get_roce(self, ts_code: str) -> Dict:
        """
        计算ROCE指标

        Returns:
            {
                'roce': float or None,
                'available': bool,     # 数据是否可用
                'level': str,          # 'EXCELLENT'/'GOOD'/'FAIR'/'POOR'/'UNKNOWN'
                'reason': str,
                'detail': Dict
            }
        """
        # 尝试从daily_basic的pe/roe字段估算
        roce_est = self._estimate_roce(ts_code)
        if roce_est['available']:
            return roce_est

        # 尝试通过akshare获取（如果已安装）
        return self._fetch_from_akshare(ts_code)

    def _estimate_roce(self, ts_code: str) -> Dict:
        """从daily_basic的PE字段估算ROCE"""
        try:
            dm = self.data_manager
            df = dm.get_cached_daily_basic(ts_code)
            if df.empty:
                return {'roce': None, 'available': False,
                        'level': 'UNKNOWN', 'reason': '数据不足', 'detail': {}}

            # PE的倒数可作为ROE的粗略估算
            # ROCE ≈ EBIT/(总资产-流动负债)，比ROE更宽泛
            if 'pe_ttm' in df.columns:
                pe = float(df['pe_ttm'].dropna().iloc[-1]) if not df['pe_ttm'].dropna().empty else 0
            elif 'pe' in df.columns:
                pe = float(df['pe'].dropna().iloc[-1]) if not df['pe'].dropna().empty else 0
            else:
                return {'roce': None, 'available': False,
                        'level': 'UNKNOWN', 'reason': '无PE数据', 'detail': {}}

            if pe > 0:
                # ROCE ≈ 1/PE × 1.5（经验系数，ROCE通常略高于PE倒数）
                roce_est = (1.0 / pe) * 100 * 1.5
                level = self._classify_roce(roce_est)
                return {
                    'roce': round(roce_est, 2),
                    'available': True,
                    'level': level,
                    'reason': f'基于PE估算ROCE={roce_est:.1f}%',
                    'detail': {'method': 'pe_estimate', 'pe': pe}
                }
            else:
                return {'roce': None, 'available': False,
                        'level': 'UNKNOWN', 'reason': f'PE={pe}，无法估算', 'detail': {'pe': pe}}

        except Exception as e:
            return {'roce': None, 'available': False,
                    'level': 'UNKNOWN', 'reason': f'估算异常: {e}', 'detail': {}}

    def _fetch_from_akshare(self, ts_code: str) -> Dict:
        """尝试通过akshare获取财务指标"""
        try:
            import akshare as ak
            # akshare 的财务指标接口
            symbol = ts_code.split('.')[0]
            # 尝试获取利润表/资产负债表
            df = ak.stock_profit_sheet_by_report_em(symbol)
            if df is not None and not df.empty:
                # 提取EBIT和资本数据
                return {
                    'roce': None,
                    'available': True,
                    'level': 'UNKNOWN',
                    'reason': 'akshare数据可用，需进一步对接',
                    'detail': {'method': 'akshare_available'}
                }
        except ImportError:
            pass
        except Exception:
            pass

        return {'roce': None, 'available': False,
                'level': 'UNKNOWN', 'reason': '财务数据接口未接入', 'detail': {}}

    @staticmethod
    def _classify_roce(roce: float) -> str:
        """ROCE等级分类"""
        if roce >= 20:
            return 'EXCELLENT'
        elif roce >= 12:
            return 'GOOD'
        elif roce >= 6:
            return 'FAIR'
        elif roce > 0:
            return 'POOR'
        return 'NEGATIVE'


