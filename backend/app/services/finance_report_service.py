"""
FinanceReportService — 财务排雷服务

273a 方案：基于 Tushare fina_indicator 数据计算 ROCE/速动比率等指标，
通过规则引擎输出排雷结论。

数据流:
  fina_indicator_cache + income_cache + balancesheet_cache (ECM)
    → FinanceReportService (计算 + 规则引擎)
      → snapshot.verification.finance_check
"""
import logging
from datetime import datetime, date
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class FinanceReportService:
    """财务排雷服务 — 财报指标 → 规则引擎 → 排雷结论"""

    def __init__(self, data_manager=None):
        if data_manager is None:
            from app.data import DataManager
            data_manager = DataManager()
        self.data_manager = data_manager

    def get_finance_report(self, ts_code: str) -> Dict:
        """获取单只股票的完整财务指标快照

        Args:
            ts_code: 股票代码

        Returns:
            { roce, quick_ratio, ocfps, asset_liab_ratio, roe, available }
        """
        df = self.data_manager.get_cached_fina_indicator(ts_code)
        if df is None or df.empty:
            return {'available': False}

        latest = df.iloc[0]
        result = {
            'roe': _safe_float(latest.get('roe')),
            'roce': _safe_float(latest.get('roce')),
            'quick_ratio': _safe_float(latest.get('quick_ratio')),
            'ocfps': _safe_float(latest.get('cf_ps')),
            'revenue_ps': _safe_float(latest.get('revenue_ps')),
            'available': True,
        }

        # 资产负债率从 balancesheet 补充
        try:
            bs_df = self.data_manager.get_cached_balancesheet(ts_code)
            if bs_df is not None and not bs_df.empty:
                bs = bs_df.iloc[0]
                ta = _safe_float(bs.get('total_assets'))
                tl = _safe_float(bs.get('total_liab'))
                if ta and ta > 0:
                    result['asset_liab_ratio'] = round(tl / ta * 100, 1)
                ca = _safe_float(bs.get('current_assets'))
                cl = _safe_float(bs.get('current_liab'))
                # 若 quick_ratio 直接从 fina_indicator 不可得，用(current_assets/current_liab)代替
                if not result.get('quick_ratio') and cl and cl > 0:
                    result['quick_ratio'] = round(ca / cl, 2)
        except Exception:
            pass

        # 若 roce 不可得，从 income+balancesheet 计算
        if not result.get('roce'):
            try:
                inc_df = self.data_manager.get_cached_income(ts_code)
                bs_df2 = self.data_manager.get_cached_balancesheet(ts_code)
                if inc_df is not None and not inc_df.empty and bs_df2 is not None and not bs_df2.empty:
                    inc = inc_df.iloc[0]
                    bs2 = bs_df2.iloc[0]
                    op_profit = _safe_float(inc.get('operating_profit'))
                    ta2 = _safe_float(bs2.get('total_assets'))
                    cl2 = _safe_float(bs2.get('current_liab'))
                    if op_profit and ta2 and cl2 is not None and (ta2 - cl2) > 0:
                        result['roce'] = round(op_profit / (ta2 - cl2) * 100, 1)
            except Exception:
                pass

        return result

    def get_finance_verdict(self, ts_code: str) -> Dict:
        """排雷规则引擎

        Returns:
            {
                'checked': True,
                'all_passed': True/False,
                'checks': { ... },
                'data_available': True/False,
            }
        """
        report = self.get_finance_report(ts_code)
        if not report.get('available'):
            return {'checked': False, 'all_passed': False, 'checks': {}, 'data_available': False}

        # 获取近3年数据用于现金流检查
        df = self.data_manager.get_cached_fina_indicator(ts_code)
        have_cf_data = False
        if df is not None and len(df) >= 2:
            cf_positive_count = sum(
                1 for _, r in df.head(3).iterrows()
                if _safe_float(r.get('cf_ps', 0)) > 0
            )
            have_cf_data = True
        else:
            cf_positive_count = 0

        checks = {}

        # ROCE > 15%
        roce = report.get('roce')
        checks['roce'] = {
            'passed': roce is not None and roce > 15,
            'value': roce,
            'threshold': '> 15%',
        }

        # 速动比率 > 0.8
        qr = report.get('quick_ratio')
        checks['quick_ratio'] = {
            'passed': qr is not None and qr > 0.8,
            'value': qr,
            'threshold': '> 0.8',
        }

        # 经营现金流（近3年至少2年为正）
        checks['cashflow'] = {
            'passed': have_cf_data and cf_positive_count >= 2,
            'value': f'{cf_positive_count}/3年为正',
            'threshold': '3年至少2年正',
        }

        # 资产负债率 < 70%
        alr = report.get('asset_liab_ratio')
        checks['debt_ratio'] = {
            'passed': alr is not None and alr < 70,
            'value': alr,
            'threshold': '< 70%',
        }

        all_passed = all(c['passed'] for c in checks.values())

        return {
            'checked': True,
            'all_passed': all_passed,
            'checks': checks,
            'data_available': True,
        }


def _safe_float(val, default=None):
    if val is None:
        return default
    try:
        v = float(val)
        return None if v != v else v  # NaN → None
    except (ValueError, TypeError):
        return default
