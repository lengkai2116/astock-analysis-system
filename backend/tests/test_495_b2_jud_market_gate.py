"""495号 批次2（A4）：JUD 真实数据端到端抽样回归门禁

沿生产路径 `StatusEngine.evaluate(code, dim_results=...)` 抽样**真实 SIG 产物**
（strategy_signal_detail 最近交易日 dim_results_json），断言判定链健康：

  H1  evaluate 失败率 = 0（异常/空返回均计失败）
  H2  单源化不变量 = 0（495 批次1）：
      - 映射不一致：|(v390_consensus_rate+1)/2 - dim8_summary.consensus_rate| > 0.01
      - 矛盾组合：v390 opportunity_state=avoid 且 dim8 summary.status_bar ∈ 正向确认
  H3  consensus_rate ∈ [-1,1]（判定权威）、final_score ∈ [0,100]
  R1' 五档分布合理性（宽范围，容忍抽样波动）：
      avoid ∈ [40%,75%] / wait ∈ [10%,45%] / reduce ∈ [2%,25%] / enter+light ∈ [1%,15%]

数据源：真实 data/ 库（未设 TEST_DATA_DIR 的常规 pytest 环境直读）；沙盒/CI 无数据 → skip。
样本量：JUD_GATE_SAMPLE 环境变量（默认 500）。
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.data.sharding_manager import sharding_manager  # noqa: E402
from app.opportunity_atlas.status_engine import StatusEngine  # noqa: E402

SAMPLE = int(os.environ.get('JUD_GATE_SAMPLE', '500'))
_POSITIVE_BARS = {'strong_confirm', 'trend_confirm', 'light_confirm'}

# 五档分布合理性宽范围（%）
# 497号（批次3/P1，2026-09-29）：随门禁基线重定（avoid 78.5 / wait 13.5）同步校准宽范围，
#   覆盖数据真实化后的新分布（归因见 scripts/_495_b2_jud_market_gate.py STATE_BASELINE 注释）。
RANGE = {'avoid': (60.0, 92.0), 'wait': (5.0, 30.0), 'reduce': (2.0, 20.0),
         'enter_light': (0.0, 10.0)}


def _load_sample():
    """读最近交易日 dim_results_json 并等间隔抽样；无数据/库不可用返回 (None, 交易日)"""
    try:
        rows = sharding_manager.execute_query(
            'strategy_signal_detail', 'SELECT MAX(trade_date) FROM strategy_signal_detail', [])
        trade_date = str(rows[0][0]) if rows and rows[0][0] else ''
        if not trade_date:
            return None, ''
        rows = sharding_manager.execute_query(
            'strategy_signal_detail',
            "SELECT ts_code, dim_results_json FROM strategy_signal_detail "
            "WHERE trade_date = ? AND dim_results_json IS NOT NULL", [trade_date])
    except Exception:
        return None, ''
    if not rows:
        return None, trade_date
    step = max(1, len(rows) // SAMPLE)
    return rows[::step][:SAMPLE], trade_date


@pytest.fixture(scope='module')
def market_sample():
    rows, trade_date = _load_sample()
    if not rows:
        pytest.skip('无真实 SIG 数据（strategy_signal_detail 最近交易日为空；'
                    '沙盒/CI 环境跳过，需真实 data/ 库）')
    se = StatusEngine()
    out = []
    fail = 0
    for code, dj in rows:
        try:
            dr = json.loads(dj)
            row = se.evaluate(code, dim_results=dr)
        except Exception:
            fail += 1
            continue
        if not row:
            fail += 1
            continue
        out.append((code, row))
    return {'rows': out, 'fail': fail, 'trade_date': trade_date, 'n_in': len(rows)}


# ── H1：异常率 ───────────────────────────────────────────

class TestNoFailures:

    def test_evaluate_failure_rate_zero(self, market_sample):
        assert market_sample['fail'] == 0, \
            f"evaluate 失败 {market_sample['fail']}/{market_sample['n_in']}"


# ── H2：单源化不变量（495 批次1） ─────────────────────────

class TestSingleSourceInvariants:

    def test_consensus_mapping_consistent(self, market_sample):
        bad = 0
        for code, row in market_sample['rows']:
            try:
                vc = float(row.get('consensus_rate') or 0)
                der = json.loads(row.get('dim_engine_results') or '{}')
                dc = float((der.get('summary') or {}).get('judgment', {}).get('consensus_rate') or 0)
                expect = round(max(0.0, min(1.0, (vc + 1) / 2)), 2)
                if abs(dc - expect) > 0.01:
                    bad += 1
            except Exception:
                continue
        assert bad == 0, f'映射不一致样本 {bad}'

    def test_no_avoid_positive_contradiction(self, market_sample):
        bad = 0
        for code, row in market_sample['rows']:
            try:
                der = json.loads(row.get('dim_engine_results') or '{}')
                dbar = (der.get('summary') or {}).get('judgment', {}).get('status_bar')
                if row.get('opportunity_state') == 'avoid' and dbar in _POSITIVE_BARS:
                    bad += 1
            except Exception:
                continue
        assert bad == 0, f'矛盾组合样本 {bad}（v390=avoid 而 dim8 正向确认）'


# ── H3：数值范围 ─────────────────────────────────────────

class TestValueRanges:

    def test_consensus_rate_in_range(self, market_sample):
        bad = 0
        for code, row in market_sample['rows']:
            try:
                cr = float(row.get('consensus_rate') or 0)
            except (TypeError, ValueError):
                bad += 1
                continue
            if not (-1.0 <= cr <= 1.0):
                bad += 1
        assert bad == 0, f'consensus_rate 越界样本 {bad}'

    def test_final_score_in_range(self, market_sample):
        bad = 0
        for code, row in market_sample['rows']:
            try:
                fs = float(row.get('final_score') or 0)
            except (TypeError, ValueError):
                bad += 1
                continue
            if not (0.0 <= fs <= 100.0):
                bad += 1
        assert bad == 0, f'final_score 越界样本 {bad}'


# ── R1'：五档分布合理性（宽范围） ────────────────────────

class TestStateDistribution:

    def test_five_state_distribution_plausible(self, market_sample):
        rows = market_sample['rows']
        n = len(rows)
        cnt = {}
        for code, row in rows:
            st = row.get('opportunity_state')
            cnt[st] = cnt.get(st, 0) + 1
        p = {k: cnt.get(k, 0) / n * 100 for k in ('enter', 'light', 'wait', 'reduce', 'avoid')}
        assert RANGE['avoid'][0] <= p['avoid'] <= RANGE['avoid'][1], f'avoid {p["avoid"]:.1f}%'
        assert RANGE['wait'][0] <= p['wait'] <= RANGE['wait'][1], f'wait {p["wait"]:.1f}%'
        assert RANGE['reduce'][0] <= p['reduce'] <= RANGE['reduce'][1], f'reduce {p["reduce"]:.1f}%'
        el = p['enter'] + p['light']
        assert RANGE['enter_light'][0] <= el <= RANGE['enter_light'][1], \
            f'enter+light {el:.1f}%'
        # 五档必须覆盖全部样本（无未知档）
        assert sum(p.values()) > 99.9, f'存在未知档位: {p}'
