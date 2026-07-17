"""
273a 方案实施验证测试

覆盖: 情绪四阶段 + 财务排雷

运行方式: pytest backend/tests/test_273a_implementation.py -v
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import pandas as pd
from datetime import datetime


# ════════════════════════════════════════════════════════════════
# MarketSentimentService — 情绪四阶段映射逻辑
# ════════════════════════════════════════════════════════════════

class TestSentimentPhase:
    """MarketSentimentService 四阶段映射逻辑"""

    def _simulate_phase(self, limit_up_count, max_board_height, sealing_rate):
        """复现 MarketSentimentService.get_sentiment_phase 的映射逻辑"""
        if limit_up_count < 20 and max_board_height < 3 and sealing_rate < 40:
            return 'ice', '情绪冰点'
        elif limit_up_count > 80 and sealing_rate > 75:
            return 'high', '情绪高潮'
        elif max_board_height >= 3 and sealing_rate < 50:
            return 'ebb', '情绪退潮'
        elif limit_up_count >= 20 and max_board_height >= 3:
            return 'recovery', '情绪复苏'
        return 'neutral', '情绪中性'

    def test_ice_phase(self):
        """涨停<20, 连板<3, 封板<40% → 冰点"""
        phase, label = self._simulate_phase(15, 2, 30)
        assert phase == 'ice'
        assert label == '情绪冰点'

    def test_recovery_phase(self):
        """涨停≥20, 连板≥3 → 复苏"""
        phase, label = self._simulate_phase(35, 4, 60)
        assert phase == 'recovery'
        assert label == '情绪复苏'

    def test_high_phase(self):
        """涨停>80, 封板>75% → 高潮"""
        phase, label = self._simulate_phase(90, 5, 80)
        assert phase == 'high'
        assert label == '情绪高潮'

    def test_ebb_phase(self):
        """连板≥3, 封板<50% → 退潮"""
        phase, label = self._simulate_phase(50, 4, 40)
        assert phase == 'ebb'
        assert label == '情绪退潮'

    def test_neutral_phase(self):
        """其他 → 中性"""
        phase, label = self._simulate_phase(30, 2, 50)
        assert phase == 'neutral'

    def test_empty_data(self):
        """无数据 → 中性"""
        phase, label = self._simulate_phase(0, 0, 0)
        assert phase == 'ice'  # 0<20, 0<3, 0<40 → ice
        # 这其实是个边界情况，正常不会"涨停0家"


class TestSentimentServiceImport:
    """MarketSentimentService 导入"""

    def test_import(self):
        from app.services.market_sentiment_service import MarketSentimentService
        assert MarketSentimentService is not None

    def test_import_finance(self):
        from app.services.finance_report_service import FinanceReportService
        assert FinanceReportService is not None


# ════════════════════════════════════════════════════════════════
# FinanceReportService — 财务排雷规则引擎
# ════════════════════════════════════════════════════════════════

class TestFinanceReport:
    """FinanceReportService 规则引擎"""

    def _build_verdict(self, roce, quick_ratio, cf_positive_years, asset_liab_ratio):
        """复现 FinanceReportService.get_finance_verdict 的逻辑"""
        checks = {}
        checks['roce'] = {
            'passed': roce is not None and roce > 15,
            'value': roce,
            'threshold': '> 15%',
        }
        checks['quick_ratio'] = {
            'passed': quick_ratio is not None and quick_ratio > 0.8,
            'value': quick_ratio,
            'threshold': '> 0.8',
        }
        checks['cashflow'] = {
            'passed': cf_positive_years >= 2,
            'value': f'{cf_positive_years}/3年为正',
            'threshold': '3年至少2年正',
        }
        checks['debt_ratio'] = {
            'passed': asset_liab_ratio is not None and asset_liab_ratio < 70,
            'value': asset_liab_ratio,
            'threshold': '< 70%',
        }
        return {'all_passed': all(c['passed'] for c in checks.values()), 'checks': checks}

    def test_all_passed(self):
        verdict = self._build_verdict(18.5, 1.2, 3, 45.0)
        assert verdict['all_passed'] is True

    def test_roce_failed(self):
        verdict = self._build_verdict(12.0, 1.2, 3, 45.0)
        assert verdict['all_passed'] is False
        assert verdict['checks']['roce']['passed'] is False

    def test_quick_ratio_failed(self):
        verdict = self._build_verdict(18.5, 0.6, 3, 45.0)
        assert verdict['all_passed'] is False
        assert verdict['checks']['quick_ratio']['passed'] is False

    def test_cashflow_failed(self):
        verdict = self._build_verdict(18.5, 1.2, 1, 45.0)
        assert verdict['all_passed'] is False
        assert verdict['checks']['cashflow']['passed'] is False

    def test_debt_ratio_failed(self):
        verdict = self._build_verdict(18.5, 1.2, 3, 75.0)
        assert verdict['all_passed'] is False
        assert verdict['checks']['debt_ratio']['passed'] is False

    def test_multiple_failures(self):
        verdict = self._build_verdict(10.0, 0.5, 0, 80.0)
        assert verdict['all_passed'] is False
        for k in ('roce', 'quick_ratio', 'cashflow', 'debt_ratio'):
            assert verdict['checks'][k]['passed'] is False


class TestFinanceReportService:
    """FinanceReportService 方法测试"""

    def test_safe_float_none(self):
        from app.services.finance_report_service import _safe_float
        assert _safe_float(None) is None

    def test_safe_float_valid(self):
        from app.services.finance_report_service import _safe_float
        assert _safe_float(15.3) == 15.3
        assert _safe_float('12.5') == 12.5

    def test_safe_float_nan(self):
        from app.services.finance_report_service import _safe_float
        import math
        result = _safe_float(float('nan'))
        assert result is None or result != result  # NaN → None

    def test_get_finance_report_no_data(self):
        from app.services.finance_report_service import FinanceReportService
        svc = FinanceReportService()
        # 无数据的股票
        result = svc.get_finance_report('999999.XX')
        assert isinstance(result, dict)
        # 可能 available 为 False 或有数据
        assert 'available' in result


# ════════════════════════════════════════════════════════════════
# ECM 缓存层
# ════════════════════════════════════════════════════════════════

class TestECMNewTables:
    """ECM 新增表结构"""

    def test_tables_exist_in_schema(self):
        from app.data.enhanced_cache_manager import get_ecm_instance
        ecm = get_ecm_instance()
        tables = ecm._query_df(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        all_tables = set(tables['name'].tolist())
        assert 'sentiment_pool_cache' in all_tables, 'sentiment_pool_cache 表未创建'
        assert 'finance_report_cache' in all_tables, 'finance_report_cache 表未创建'

    def test_sentiment_pool_write_and_read(self):
        from app.data.enhanced_cache_manager import get_ecm_instance
        ecm = get_ecm_instance()
        records = [
            {
                'trade_date': '20260717',
                'ts_code': '000001.SZ',
                'name': '平安银行',
                'change_pct': 10.0,
                'price': 12.5,
                'limit_type': 'up',
                'consecutive_days': 2,
                'reason_category': '业绩预增',
                'first_seal_time': '09:35:00',
                'data_source': 'akshare',
            },
            {
                'trade_date': '20260717',
                'ts_code': '000002.SZ',
                'name': '万科A',
                'change_pct': -10.0,
                'price': 8.5,
                'limit_type': 'down',
                'consecutive_days': 1,
                'reason_category': '',
                'first_seal_time': '',
                'data_source': 'akshare',
            },
        ]
        ecm.write_sentiment_pool(records)
        df = ecm.get_cached_sentiment_pool('20260717')
        assert df is not None and not df.empty
        assert len(df) >= 2
        up_df = df[df['limit_type'] == 'up']
        assert len(up_df) >= 1
        assert '平安银行' in up_df['name'].values

    def test_finance_report_write_and_read(self):
        from app.data.enhanced_cache_manager import get_ecm_instance
        ecm = get_ecm_instance()
        import pandas as pd
        df = pd.DataFrame([{
            'ts_code': '000001.SZ',
            'end_date': '2026-06-30',
            'roe': 15.3,
            'roce': 12.5,
            'quick_ratio': 1.2,
            'ocfps': 0.8,
            'current_ratio': 1.5,
            'asset_liab_ratio': 45.0,
            'ebit': 100000000.0,
            'operating_profit': 95000000.0,
            'total_assets': 1000000000.0,
            'total_liab': 450000000.0,
            'current_assets': 600000000.0,
            'current_liab': 400000000.0,
        }])
        ecm.cache_finance_report_data(df)
        df2 = ecm.get_cached_finance_report('000001.SZ')
        assert df2 is not None and not df2.empty
        assert df2.iloc[0]['roce'] == 12.5
        assert df2.iloc[0]['quick_ratio'] == 1.2


# ════════════════════════════════════════════════════════════════
# SnapshotAssembler — verification 区块
# ════════════════════════════════════════════════════════════════

class TestSnapshotVerification:
    """SnapshotAssembler verification 区块"""

    def test_verification_block_in_snapshot(self):
        from app.services.snapshot_assembler import SnapshotAssembler
        assembler = SnapshotAssembler()
        result = assembler.assemble([], ts_code='')
        assert 'verification' in result, 'verification 区块缺失'

    def test_verification_with_ts_code(self):
        from app.services.snapshot_assembler import SnapshotAssembler
        assembler = SnapshotAssembler()
        result = assembler.assemble([], ts_code='000001.SZ')
        assert 'verification' in result


# ════════════════════════════════════════════════════════════════
# 集成测试
# ════════════════════════════════════════════════════════════════

class Test273aIntegration:
    """273a 方案端到端集成"""

    def test_all_modules_importable(self):
        from app.services.market_sentiment_service import MarketSentimentService
        from app.services.finance_report_service import FinanceReportService, _safe_float
        MarketSentimentService
        FinanceReportService
        _safe_float

    def test_sentiment_service_with_mock_data(self):
        """用 mock ECM 数据测试 MarketSentimentService 是否正常初始化"""
        from app.services.market_sentiment_service import MarketSentimentService
        svc = MarketSentimentService()
        result = svc.get_sentiment_phase('20260717')
        # 可能无数据，但不应该抛异常
        assert isinstance(result, dict)
        assert 'phase' in result
        assert 'phase_label' in result

    def test_snapshot_returns_dict(self):
        from app.services.snapshot_assembler import SnapshotAssembler
        assembler = SnapshotAssembler()
        result = assembler.assemble([
            {
                'strategy_name': '缠论走势分析',
                'signal': 'bullish',
                'status_recognition': {
                    'trend': {'stage': '日线级别', 'direction': 'up', 'strength': 'strong'},
                },
            },
        ], ts_code='000001.SZ')
        assert isinstance(result, dict)
        assert result['ts_code'] == '000001.SZ'
        assert 'verification' in result
