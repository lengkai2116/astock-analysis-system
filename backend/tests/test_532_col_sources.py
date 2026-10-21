"""532号 批次1：COL 新表 / Provider 接口 / ETF 映射回归。

只做静态与纯函数校验，不连外部接口、不写业务库（新增表写入留待回填脚本与批次2验证）。
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
ECM_PATH = ROOT / 'backend' / 'app' / 'data' / 'enhanced_cache_manager.py'
SHARD_PATH = ROOT / 'backend' / 'app' / 'data' / 'sharding_manager.py'


def _src(p: Path) -> str:
    return p.read_text(encoding='utf-8')


def test_new_tables_ddl_present():
    src = _src(ECM_PATH)
    for table in ('fund_share_cache', 'limit_detail_cache',
                  'northbound_flow_cache', 'etf_industry_map'):
        assert f'CREATE TABLE IF NOT EXISTS {table}' in src, table
    for col in ('fd_share', 'fd_amount', 'open_times', 'limit_times',
                'first_time', 'last_time', 'north_money', 'etf_type', 'mapping_source'):
        assert col in src, col
    for method in ('cache_fund_share_data', 'cache_limit_detail_data',
                   'cache_northbound_flow_data', 'cache_etf_industry_map'):
        assert f'def {method}' in src, method


def test_new_tables_routing_registered():
    src = _src(SHARD_PATH)
    expected = {
        'fund_share_cache': 'market_cache.db',
        'limit_detail_cache': 'market_cache.db',
        'northbound_flow_cache': 'market_cache.db',
        'etf_industry_map': 'compute_cache.db',
    }
    for table, db in expected.items():
        assert f"'{table}': '{db}'" in src, f'{table} 未登记路由'


def test_etf_classifier_industry_and_theme():
    from app.data.etf_industry_map import classify_etf

    assert classify_etf('华夏中证半导体ETF', '中证半导体指数收益率') == ('电子', 'industry')
    assert classify_etf('华宝中证光伏产业ETF', '中证光伏产业指数') == ('电力设备', 'industry')
    assert classify_etf('华夏中证人工智能ETF', '中证人工智能指数') == ('计算机', 'theme')
    assert classify_etf('华夏中证新能源汽车ETF', '中证新能源汽车指数') == ('汽车', 'theme')
    # 宽基不归属行业
    assert classify_etf('华泰柏瑞沪深300ETF', '沪深300指数') == (None, None)


def test_build_etf_rows_stats():
    from app.data.etf_industry_map import build_etf_industry_rows

    df = pd.DataFrame([
        {'ts_code': 'A.SH', 'name': '半导体ETF', 'fund_type': 'ETF', 'benchmark': '中证半导体'},
        {'ts_code': 'B.SH', 'name': '沪深300ETF', 'fund_type': 'ETF', 'benchmark': '沪深300'},
        {'ts_code': 'C.SH', 'name': '人工智能ETF', 'fund_type': 'ETF', 'benchmark': '中证人工智能'},
        {'ts_code': 'D.SH', 'name': '主动混合基金', 'fund_type': '混合型', 'benchmark': 'x'},
    ])
    rows, stats = build_etf_industry_rows(df)
    assert stats['total'] == 3          # 仅 ETF
    assert stats['mapped'] == 2         # 半导体 + 人工智能
    assert stats['industry'] == 1
    assert stats['theme'] == 1
    assert set(rows['etf_type']) == {'industry', 'theme'}


def test_provider_532_methods_with_fake_pro():
    from app.data.tushare_provider import TushareProvider

    class _FakePro:
        def sw_daily(self, **kw):
            return pd.DataFrame([{'ts_code': kw['ts_code'], 'trade_date': '20261020', 'close': 1.0}])

        def fund_basic(self, **kw):
            return pd.DataFrame([{'ts_code': '510300.SH', 'name': '沪深300ETF'}])

        def fund_share(self, **kw):
            return pd.DataFrame([{'ts_code': '510300.SH', 'trade_date': '20261020', 'fd_share': 1.0}])

        def limit_list_d(self, **kw):
            return pd.DataFrame([{'ts_code': '000001.SZ', 'trade_date': kw['trade_date'],
                                  'limit_type': kw.get('limit_type')}])

        def moneyflow_hsgt(self, **kw):
            return pd.DataFrame([{'trade_date': '20261020', 'north_money': 1.0}])

        def index_daily(self, **kw):
            return pd.DataFrame([{'ts_code': kw['ts_code'], 'trade_date': '20261020', 'close': 1.0}])

    p = TushareProvider.__new__(TushareProvider)
    p.token = 'test'
    p.pro = _FakePro()

    assert len(p.get_sw_index_daily('801080.SI', '20261001', '20261020')) == 1
    assert len(p.get_fund_basic()) == 1
    assert len(p.get_fund_share(trade_date='20261020')) == 1
    assert len(p.get_limit_list_d('20261020', 'U')) == 1
    assert len(p.get_moneyflow_hsgt('20261001', '20261020')) == 1
    assert len(p.get_index_daily_range('000300.SH', '20261001', '20261020')) == 1
