"""532号 批次2：板块热度五维引擎 / 表 / 配置 / RAW-2E 回归。

引擎为纯函数；其余为静态结构校验，不连外部接口、不写业务库。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _src(p: Path) -> str:
    return p.read_text(encoding='utf-8')


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


def test_percentile_rank_basic_and_missing():
    from app.engine.framework.sector_heat_composite import percentile_rank

    assert percentile_rank([10, 20, 30]) == [0.0, 50.0, 100.0]
    assert percentile_rank([None, 5, None]) == [None, 50.0, None]
    assert percentile_rank([]) == []


def test_engine_stage_mainline_overheat_cold():
    from app.engine.framework.sector_heat_composite import compute

    rows = [
        _row('主线', rps_20=95, rps_60=85, rps_120=80, rps_resonance=2,
             fund_ratio=0.5, up_ratio=0.72, vp_state='放量突破', vp_score=90,
             limit_up_ratio=1.0, zhaban_ratio=10.0, amount_share=8.0),
        _row('过热', rps_20=90, rps_60=70, rps_120=96, rps_resonance=1,
             fund_ratio=0.1, up_ratio=0.4, vp_state='天量滞涨', vp_score=25,
             limit_up_ratio=6.0, zhaban_ratio=45.0, amount_share=16.0,
             max_board_height=4, fd_amount_ratio=0.4),
        _row('冷门', rps_20=20, rps_60=30, rps_120=40, rps_resonance=0,
             fund_ratio=0.2, up_ratio=0.3, vp_state='地量横盘', vp_score=45,
             vol_ratio_5d=0.5, limit_up_ratio=0.0, zhaban_ratio=0.0,
             amount_share=2.0),
        _row('中性'),
    ]
    out = compute(rows)
    by = {r['industry']: r for r in out}
    assert by['主线']['stage'] == 'mainline'
    assert by['过热']['stage'] == 'overheat'
    assert by['冷门']['stage'] == 'cold'
    assert by['中性']['stage'] == 'neutral'

    # 分维/综合分范围 + 排名唯一
    for r in out:
        for k in ('dim_rs', 'dim_fund', 'dim_vp', 'dim_sentiment', 'dim_breadth', 'quality_score'):
            assert r[k] is None or 0 <= r[k] <= 100, (r['industry'], k, r[k])
    assert sorted(r['heat_rank'] for r in out) == [1, 2, 3, 4]


def test_engine_missing_dims_do_not_raise():
    from app.engine.framework.sector_heat_composite import compute

    row = _row('缺数据')
    for k in ('rps_20', 'rps_60', 'rps_120', 'fund_ratio', 'margin_growth_5d',
              'etf_share_chg_5d', 'vp_score', 'limit_up_ratio', 'zhaban_ratio',
              'amount_share', 'fd_amount_ratio', 'up_ratio', 'med_vs_mean',
              'rps_high_ratio'):
        row[k] = None
    out = compute([row])
    assert len(out) == 1
    assert 'missing_dim' in out[0]['flags']
    assert out[0]['stage'] == 'neutral'


def test_static_ddl_route_config_and_mapping():
    from app.engine.framework.sector_heat_composite import SW_INDEX_TO_INDUSTRY

    ecm = _src(ROOT / 'backend' / 'app' / 'data' / 'enhanced_cache_manager.py')
    shard = _src(ROOT / 'backend' / 'app' / 'data' / 'sharding_manager.py')
    daemon = _src(ROOT / 'backend' / 'data_daemon.py')

    assert 'CREATE TABLE IF NOT EXISTS sector_heat_dim_cache' in ecm
    assert 'quality_score REAL, stage TEXT, heat_rank INTEGER' in ecm
    assert "'sector_heat_dim_cache': 'compute_cache.db'" in shard
    assert 'def _precompute_sector_heat_dim' in daemon
    assert "'RAW-2E'" in daemon
    assert len(SW_INDEX_TO_INDUSTRY) == 31

    cfg = ROOT / 'backend' / 'config' / 'sector_heat.yaml'
    assert cfg.exists()
    text = cfg.read_text(encoding='utf-8')
    for key in ('weights:', 'vp_adjust:', 'thresholds:', 'northbound: false'):
        assert key in text
