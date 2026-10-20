"""516号 登记项处置定向测试。

- **P6**：`_aggregate_sector_moneyflow` 的 `out_sectors` 由硬编码 `[:5]` 改为与 `sectors` 同为 `[:top_n]`。
- **`sector_analysis_service._get_sector_moneyflow_rank`**：原把 `get_sector_moneyflow` 返回当 list
  迭代并读 `sector_name`/`net_amount`（实际为 dict + `name`/`net_inflow`）⇒ 恒吞 except、rank/net 恒 0；
  改为按真实契约合并流入/流出按净额降序排名。
"""
from app.services.dashboard_service import DashboardService


def _rec(code, net):
    buy = net if net > 0 else 0.0
    sell = -net if net < 0 else 0.0
    return {
        'ts_code': code, 'buy_lg_amount': buy, 'buy_elg_amount': 0.0,
        'sell_lg_amount': sell, 'sell_elg_amount': 0.0,
    }


def test_p6_out_sectors_uses_top_n_not_hardcoded_5():
    industry_map = {f'C{i}.SH': f'OUT{i}' for i in range(6)}
    raw = [_rec(f'C{i}.SH', -(1e8 + i)) for i in range(6)]
    res = DashboardService()._aggregate_sector_moneyflow(
        raw, industry_map, top_n=8, stocks_per_sector=3, trade_date='20261012')
    # 修复前硬编码 [:5] → 恒 5；修复后 = min(6, top_n=8) = 6
    assert len(res['out_sectors']) == 6


def test_sector_moneyflow_rank_reads_real_contract(monkeypatch):
    import app.services.dashboard_service as ds

    class _FakeDash:
        def get_sector_moneyflow(self, top_n=8, stocks_per_sector=3,
                                 industry_scope='sw'):
            return {
                'sectors': [{'name': 'X', 'net_inflow': 9.0},
                            {'name': 'Y', 'net_inflow': 4.0}],
                'out_sectors': [{'name': 'Z', 'net_inflow': -2.0}],
            }

    monkeypatch.setattr(ds, 'DashboardService', _FakeDash)
    from app.services.sector_analysis_service import SectorAnalysisService
    svc = SectorAnalysisService()
    # 排名按净额降序：X(1) > Y(2) > Z(3)
    assert svc._get_sector_moneyflow_rank(None, 'Y') == {'rank': 2, 'net_amount': 4.0}
    assert svc._get_sector_moneyflow_rank(None, 'Z') == {'rank': 3, 'net_amount': -2.0}
    assert svc._get_sector_moneyflow_rank(None, 'W') == {'rank': 0, 'net_amount': 0}
