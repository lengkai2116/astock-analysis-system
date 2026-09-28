"""493号 批次5 回归（P2-d 月度风险预算 6% + 连亏 3 笔停机）

知识库《月度风险预算》：
  - 月度最大允许亏损 = 账户总资金 × 6%
  - 最大允许亏损笔数 = 6% ÷ 2% = 3 笔
  - 连亏 3 笔后：本月停止交易等下月（或降单笔风险至 1%）

用户拍板（2026-09-28）：
  ① 接入方式 = 预计算快照 + JUD 只读；
  ② 停机动作 = **仅产出标记字段**（monthly_halt / monthly_loss_pct / consecutive_losses），
     本批不改 opportunity_state / 仓位；
  ③ 阈值 = 6% + 3 笔（入 yaml `monthly_risk_budget` 可配）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.account_risk_status import (  # noqa: E402
    DEFAULT_ACCOUNT_CAPITAL, evaluate_monthly_risk_status, get_account_risk_status,
    write_account_risk_status,
)


# ══ 纯函数：evaluate_monthly_risk_status ══════════════════════════════

def test_empty_account_is_neutral():
    """空账户：亏损 0、连亏 0、不停机"""
    s = evaluate_monthly_risk_status(month_pnl=0.0, month_start_asset=1_000_000,
                                     consecutive_losses=0)
    assert s['monthly_halt'] is False
    assert s['monthly_loss_pct'] == 0.0
    assert s['consecutive_losses'] == 0


def test_monthly_loss_6pct_halts():
    """月度亏损 = 6% → 停机（边界命中）"""
    s = evaluate_monthly_risk_status(month_pnl=-60_000, month_start_asset=1_000_000,
                                     consecutive_losses=0)
    assert s['monthly_loss_pct'] == 6.0
    assert s['monthly_halt'] is True
    assert '月度亏损' in s['halt_reason']


def test_monthly_loss_below_6pct_no_halt():
    """月度亏损 5.9% → 不停机"""
    s = evaluate_monthly_risk_status(month_pnl=-59_000, month_start_asset=1_000_000,
                                     consecutive_losses=0)
    assert s['monthly_halt'] is False


def test_consecutive_3_losses_halts():
    """连亏 3 笔（月度未超限）→ 停机"""
    s = evaluate_monthly_risk_status(month_pnl=-10_000, month_start_asset=1_000_000,
                                     consecutive_losses=3)
    assert s['monthly_halt'] is True
    assert '连续亏损' in s['halt_reason']


def test_consecutive_2_losses_no_halt():
    """连亏 2 笔 → 不停机"""
    s = evaluate_monthly_risk_status(month_pnl=-10_000, month_start_asset=1_000_000,
                                     consecutive_losses=2)
    assert s['monthly_halt'] is False


def test_profit_no_halt():
    """月度盈利 → 不停机、亏损率为负"""
    s = evaluate_monthly_risk_status(month_pnl=+30_000, month_start_asset=1_000_000,
                                     consecutive_losses=0)
    assert s['monthly_halt'] is False
    assert s['monthly_loss_pct'] == -3.0


def test_zero_asset_no_div_by_zero():
    s = evaluate_monthly_risk_status(month_pnl=-1000, month_start_asset=0,
                                     consecutive_losses=1)
    assert s['monthly_loss_pct'] == 0.0
    assert s['monthly_halt'] is False


def test_yaml_thresholds_override():
    """yaml monthly_risk_budget 可覆盖阈值（8% / 5 笔）"""
    cfg = {'monthly_risk_budget': {'monthly_loss_limit_pct': 0.08,
                                   'consecutive_loss_limit': 5}}
    # 6% 亏损在 8% 上限下不停机
    assert evaluate_monthly_risk_status(-60_000, 1_000_000, 0, cfg=cfg)['monthly_halt'] is False
    # 连亏 3 笔在 5 笔上限下不停机
    assert evaluate_monthly_risk_status(-10_000, 1_000_000, 3, cfg=cfg)['monthly_halt'] is False


def test_yaml_actual_config_is_6pct_3():
    """默认 status_engine.yaml 须为 6% + 3 笔（知识库口径）"""
    from app.services.status_config import get_status_engine_config
    mrb = get_status_engine_config().get('monthly_risk_budget') or {}
    assert mrb.get('monthly_loss_limit_pct') == 0.06
    assert mrb.get('consecutive_loss_limit') == 3


# ══ 快照读写（JUD 只读路径） ══════════════════════════════════════════

def test_get_status_snapshot_read(tmp_path):
    """写入快照后 JUD 侧只读命中（空账户 → 中性）"""
    write_account_risk_status(str(tmp_path), cfg={'monthly_risk_budget': {}})
    s = get_account_risk_status(str(tmp_path))
    assert s['monthly_halt'] is False
    assert s['monthly_loss_pct'] == 0.0
    assert os.path.exists(str(tmp_path / 'account_risk_status.json'))


def test_get_status_missing_file_neutral():
    """快照缺失 → 中性降级（不抛错）"""
    s = get_account_risk_status('/nonexistent/dir/xyz')
    assert s['monthly_halt'] is False


def test_default_capital_constant():
    assert DEFAULT_ACCOUNT_CAPITAL == 1_000_000.0


# ══ JUD 只读接线（status_engine._assemble 顶层字段） ═════════════════

def test_status_engine_assembles_monthly_fields():
    """_assemble 须产出 monthly_halt / monthly_loss_pct / consecutive_losses"""
    from app.opportunity_atlas.status_engine import StatusEngine
    se = StatusEngine(dm=object())
    row = se._assemble(
        'T.SZ',
        dims={'structure': {'light': 'green'}, 'risk': {'light': 'green'}},
        lifecycle=None,
        l0={'hard_veto': False, 'hold_only': False, 'soft_risks': [], 'position_coeff': 1.0},
        l2={'opportunity_state': 'wait', 'state_evidence': [], 'conflict_evidence': [],
            'consensus_rate': 0.5, 'direction': 'neutral'},
    )
    assert 'monthly_halt' in row
    assert row['monthly_halt'] is False
    assert row['monthly_loss_pct'] == 0.0
    assert row['consecutive_losses'] == 0
    ap = json.loads(row['advice_params'])
    assert 'monthly_halt' in ap and 'monthly_loss_pct' in ap
