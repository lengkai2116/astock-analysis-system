"""532号 批次3：板块热度五维读路径（ECM/DataManager）、API 与前端接线回归。

不连外部接口、不写业务库；ECM 用假 `_query_shard`，服务层用假 DataManager。
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HTML_PATH = ROOT / '_ui-prototype' / 'dashboard.html'


def _row(industry: str, **kw):
    base = dict(
        industry=industry,
        ret_20=0.0, ret_60=0.0, ret_120=0.0,
        rps_20=50.0, rps_60=50.0, rps_120=50.0, rps_resonance=0,
        excess_20=0.0, excess_60=0.0,
        main_net_5d=0.0, fund_ratio=0.0, margin_growth_5d=0.0,
        etf_share_chg_5d=0.0,
        vol_ratio_5d=1.0, breakout_20d=0, vp_state='常态', vp_score=55.0,
        limit_up_ratio=0.0, zhaban_ratio=0.0, max_board_height=0,
        amount_share=5.0, fd_amount_ratio=0.0, open_times_avg=0.0,
        up_ratio=0.5, med_vs_mean=0.0, rps_high_ratio=10.0,
        index_pct=0.0, coverage={'etf': True},
    )
    base.update(kw)
    return base


def test_etf_coverage_flag_ignores_bool_true():
    """bool 是 int 子类：coverage.etf=True 不得误触发 etf_coverage_low。"""
    from app.engine.framework.sector_heat_composite import compute

    out = compute([_row('电子', coverage={'etf': True}),
                   _row('银行', coverage={'etf': False})])
    by = {r['industry']: r for r in out}
    assert 'etf_coverage_low' not in by['电子']['flags']
    assert 'etf_coverage_low' in by['银行']['flags']


def test_ecm_get_cached_sector_heat_dim_parses_rows():
    """ECM 读取最新日 + 上一日 rank，并解析 flags/coverage JSON。"""
    from app.data.enhanced_cache_manager import EnhancedCacheManager

    dates = pd.DataFrame({'stat_date': ['2026-10-20', '2026-10-19']})
    rows = pd.DataFrame([{
        'stat_date': '2026-10-20', 'industry': '电子', 'heat_rank': 1,
        'quality_score': 80.0, 'stage': 'mainline',
        'dim_rs': 95.0, 'dim_fund': 80.0, 'dim_vp': 90.0,
        'dim_sentiment': 20.0, 'dim_breadth': 70.0,
        'rps_20': 95.0, 'rps_60': 85.0, 'rps_120': 80.0, 'rps_resonance': 2,
        'up_ratio': 0.72, 'fund_ratio': 0.5, 'vp_state': '放量突破',
        'flags_json': '["breadth_divergence", "northbound_off"]',
        'coverage_json': '{"etf": true, "northbound": false}',
        'calc_version': '532.1',
    }])
    prev = pd.DataFrame([{'industry': '电子', 'heat_rank': 3}])

    class _FakeECM:
        def _query_shard(self, table, sql, params=None):
            if 'DISTINCT stat_date' in sql:
                return dates
            if 'SELECT industry, heat_rank' in sql:
                return prev
            return rows

    res = EnhancedCacheManager.get_cached_sector_heat_dim(_FakeECM())
    assert res['date'] == '2026-10-20'
    assert res['prev_date'] == '2026-10-19'
    assert res['prev_rank'] == {'电子': 3}
    assert len(res['rows']) == 1
    r0 = res['rows'][0]
    assert r0['industry'] == '电子'
    assert r0['quality_score'] == 80.0
    assert r0['flags'] == ['breadth_divergence', 'northbound_off']
    assert r0['coverage'] == {'etf': True, 'northbound': False}


def test_service_kpi_rules_and_flag_sanitize():
    """服务层：KPI 聚合、rules、旧 flags 的 etf_coverage_low 按 coverage 纠正。"""
    from app.services.dashboard_service import DashboardService

    payload = {
        'date': '2026-10-20', 'prev_date': '', 'prev_rank': {},
        'rows': [
            {'industry': '电子', 'rank': 1, 'quality_score': 80.0, 'stage': 'mainline',
             'dim_rs': 95.0, 'dim_fund': 80.0, 'dim_vp': 90.0,
             'dim_sentiment': 20.0, 'dim_breadth': 70.0,
             'rps_20': 95.0, 'rps_60': 85.0, 'rps_120': 80.0, 'rps_resonance': 2,
             'up_ratio': 0.72, 'fund_ratio': 0.5, 'vp_state': '放量突破',
             'limit_up_ratio': 1.0, 'zhaban_ratio': 10.0, 'amount_share': 8.0,
             'vol_ratio_5d': 1.2,
             'flags': ['etf_coverage_low', 'northbound_off'],
             'coverage': {'etf': True, 'northbound': False}},
            {'industry': '银行', 'rank': 2, 'quality_score': 60.0, 'stage': 'pulse',
             'dim_rs': 90.0, 'dim_fund': 50.0, 'dim_vp': 55.0,
             'dim_sentiment': 30.0, 'dim_breadth': 40.0,
             'rps_20': 92.0, 'rps_60': 55.0, 'rps_120': 70.0, 'rps_resonance': 1,
             'up_ratio': 0.4, 'fund_ratio': 0.1, 'vp_state': '常态',
             'limit_up_ratio': 0.0, 'zhaban_ratio': 0.0, 'amount_share': 5.0,
             'vol_ratio_5d': 1.0,
             'flags': [], 'coverage': {'etf': False, 'northbound': False}},
        ],
    }

    class _FakeDM:
        def get_cached_sector_heat_dim(self, stat_date=None):
            return payload

    svc = DashboardService()
    svc._data_manager = _FakeDM()
    res = svc.get_sector_heat_dim()

    assert res is not None
    assert res['count'] == 2
    assert res['stage_counts'] == {'mainline': 1, 'pulse': 1,
                                   'overheat': 0, 'cold': 0, 'neutral': 0}
    assert res['median_quality'] == 70.0
    assert res['median_quality_delta'] is None
    assert res['coverage'] == {'etf_pct': 50.0, 'northbound': False}
    assert res['sectors'][0]['rules']['mainline'] is True
    assert res['sectors'][0]['rules']['pulse'] is False
    assert 'etf_coverage_low' not in res['sectors'][0]['flags']
    assert 'etf_coverage_low' in res['sectors'][1]['flags']


def test_route_registered_and_frontend_wired():
    """新路由存在；前端改为五维榜 + 旧榜仅降级回退。"""
    from app.routes import dashboard as dash

    assert hasattr(dash, 'get_sector_heat_dim')

    html = HTML_PATH.read_text(encoding='utf-8')
    assert '🔥 板块热度 · 五维' in html
    assert 'renderSectorHeatDim' in html
    assert '/market/sector-heat-dim' in html
    assert '五维未就绪，暂显示原资金热度' in html
    assert 'if(dd.sector_heat) applySectorHeat' not in html
    assert 'loadSectorHeatDim();' in html
    assert html.count('id="sector-heat-panel"') == 1
