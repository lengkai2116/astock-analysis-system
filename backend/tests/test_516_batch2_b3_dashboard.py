"""516号 核查档 批次2/3 定向测试。

- **批次2（Q2）**：AI 交易机会雷达模块**前后端一并下线**——前端删
  `radar-section`/`radar-track`/`loadRadar`/`applyRadar`/`colorMap`/`dirLabelMap`/`dashboard_summary`；
  后端删 `DashboardService.get_dashboard_summary` + `/api/v3/dashboard/summary` 路由 + 聚合键 `dashboard_summary`。
- **批次3**：**Q4** `get_index_summary` 附 `data_is_live`/`data_date`；**Q5** 成交额标题改
  「四大指数合计成交额（含指数成分重叠）」；**Q6** `retail_net_outflow` → `retail_net_inflow`
  （统一为「散户净流入」）。
"""
import inspect
import os

from app.services.dashboard_service import DashboardService

_HTML = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "_ui-prototype",
    "dashboard.html",
)


def _rec(code, net):
    buy = net if net > 0 else 0.0
    sell = -net if net < 0 else 0.0
    return {
        'ts_code': code, 'buy_lg_amount': buy, 'buy_elg_amount': 0.0,
        'sell_lg_amount': sell, 'sell_elg_amount': 0.0, 'net_sm_amount': net,
    }


# ── 批次2：雷达模块前后端下线 ──────────────────────────────
def test_backend_summary_method_removed():
    assert not hasattr(DashboardService, 'get_dashboard_summary')


def test_backend_summary_route_removed():
    from app.routes import dashboard as _dash
    assert not hasattr(_dash, 'get_dashboard_summary')


def test_frontend_radar_module_removed():
    with open(_HTML, encoding='utf-8') as f:
        html = f.read()
    for tok in ('radar-section', 'radar-track', 'loadRadar', 'applyRadar',
                'colorMap', 'dirLabelMap', 'dashboard/summary', 'dashboard_summary'):
        assert tok not in html, f"残留：{tok}"


# ── 批次3：Q4/Q5/Q6 ────────────────────────────────────────
def test_q4_overview_exposes_data_freshness_fields():
    src = inspect.getsource(DashboardService.get_index_summary)
    assert "'data_is_live'" in src
    assert "'data_date'" in src


def test_q6_moneyflow_key_renamed_to_net_inflow():
    svc = DashboardService()
    res = svc._aggregate_moneyflow_by_date(
        [_rec('X.SH', +5e4)], max_days=20, source_label='t')
    day = res['days'][0]
    assert 'retail_net_inflow' in day
    assert 'retail_net_outflow' not in day


def test_q5_q6_frontend_labels_updated():
    with open(_HTML, encoding='utf-8') as f:
        html = f.read()
    assert '四大交易所合计' not in html                                   # Q5 旧名已改
    assert '四大指数合计成交额（含指数成分重叠）' in html                 # Q5 新名
    assert 'retail_net_outflow' not in html                              # Q6 键名统一
    assert "'散户净流入'" in html                                        # Q6 标注统一
