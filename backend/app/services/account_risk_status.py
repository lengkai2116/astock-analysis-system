"""account_risk_status.py — 493号 P2-d：账户级月度风险预算状态（月度 6% + 连亏 3 笔停机）

知识库《月度风险预算》：
  - 月度最大允许亏损 = 账户总资金 × 6%
  - 月度最大允许亏损笔数 = 6% ÷ 2% = 3 笔
  - 连续亏损 3 笔后：本月停止交易等下月（或降单笔风险至 1%）
  - 在决策流程中为「第一步检查」（先于情绪阶段/信号/止损/R:R/仓位）

架构（用户 2026-09-28 拍板）：
  - **预计算快照 + JUD 只读**：daemon 日终（管道完成后）按账户交易记录算一次
    「月度 P&L% + 连亏笔数」→ 原子写 `<DATA_DIR>/account_risk_status.json`；
    JUD `_assemble` 只读该快照（不引入 JUD→app.db 实时耦合，规避 daemon 子线程
    无 app_context / 分库锁风险）。
  - **仅产出标记字段**：`monthly_halt` / `monthly_loss_pct` / `consecutive_losses`
    落 `advice_params` + 顶层，供前端/消费方展示；**本批不改 opportunity_state/仓位**。
  - 账户为空（无 Trade 记录）→ 中性（`monthly_halt=False`、亏损 0）。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

# 知识库《月度风险预算》默认阈值（可经 status_engine.yaml `monthly_risk_budget` 覆盖）
DEFAULT_MONTHLY_LOSS_LIMIT_PCT = 0.06     # 月度最大允许亏损 = 账户总资金 × 6%
DEFAULT_CONSECUTIVE_LOSS_LIMIT = 3        # 连亏 3 笔 → 本月停止交易
DEFAULT_ACCOUNT_CAPITAL = 1_000_000.0     # 无账户数据时的账户资金口径（与 492 K1 一致）

STATE_FILE_NAME = 'account_risk_status.json'


def _cfg_limits(cfg: Optional[dict] = None) -> tuple[float, int]:
    """取阈值（status_engine.yaml monthly_risk_budget 段；缺失回退知识库默认）"""
    mrb = ((cfg or {}).get('monthly_risk_budget') or {}) if isinstance(cfg, dict) else {}
    limit_pct = mrb.get('monthly_loss_limit_pct', DEFAULT_MONTHLY_LOSS_LIMIT_PCT)
    consec = mrb.get('consecutive_loss_limit', DEFAULT_CONSECUTIVE_LOSS_LIMIT)
    try:
        limit_pct = float(limit_pct)
    except (TypeError, ValueError):
        limit_pct = DEFAULT_MONTHLY_LOSS_LIMIT_PCT
    try:
        consec = int(consec)
    except (TypeError, ValueError):
        consec = DEFAULT_CONSECUTIVE_LOSS_LIMIT
    return limit_pct, consec


def evaluate_monthly_risk_status(month_pnl: float = 0.0,
                                 month_start_asset: float = DEFAULT_ACCOUNT_CAPITAL,
                                 consecutive_losses: int = 0,
                                 cfg: Optional[dict] = None) -> dict:
    """纯函数：由账户月度 P&L / 连亏笔数 → 月度风险状态。

    月度亏损率 = -month_pnl / month_start_asset（正数=亏损比例）。
    命中「月度亏损 ≥ 6%」或「连亏 ≥ 3 笔」→ monthly_halt=True（本月停止交易）。
    """
    limit_pct, consec_limit = _cfg_limits(cfg)
    try:
        asset = float(month_start_asset or 0.0)
    except (TypeError, ValueError):
        asset = 0.0
    try:
        month_pnl = float(month_pnl or 0.0)
    except (TypeError, ValueError):
        month_pnl = 0.0
    try:
        consecutive_losses = int(consecutive_losses or 0)
    except (TypeError, ValueError):
        consecutive_losses = 0

    if asset <= 0:
        loss_pct = 0.0
    else:
        loss_pct = round(-month_pnl / asset, 6)      # 正数=亏损比例（0.063=亏6.3%）

    reasons = []
    if loss_pct >= limit_pct:
        reasons.append(f'月度亏损 {loss_pct * 100:.1f}% ≥ {limit_pct * 100:.0f}% 上限')
    if consecutive_losses >= consec_limit:
        reasons.append(f'连续亏损 {consecutive_losses} 笔 ≥ {consec_limit} 笔')

    return {
        'monthly_pnl': round(month_pnl, 2),
        'month_start_asset': round(asset, 2),
        'monthly_loss_pct': round(loss_pct * 100, 2),   # 百分数（前端直读）
        'monthly_loss_limit_pct': round(limit_pct * 100, 2),
        'consecutive_losses': consecutive_losses,
        'consecutive_loss_limit': consec_limit,
        'monthly_halt': bool(reasons),                   # 本月停止交易（标记）
        'halt_reason': '；'.join(reasons),
    }


def compute_from_account(today: Optional[date] = None,
                         cfg: Optional[dict] = None) -> dict:
    """从账户交易记录（Trade/AccountSnapshot）计算月度风险状态。

    须在 Flask app_context 内调用（内部走 ORM db.session）；无账户数据 / 无上下文
    / 查询异常 → 中性降级（不抛错，保证 daemon 钩子与 JUD 读侧永不阻塞）。
    """
    today = today or date.today()
    month_start = today.replace(day=1)
    month_pnl = 0.0
    consecutive_losses = 0
    month_start_asset = None
    try:
        from app.models.trade import AccountSnapshot, Trade
        # ① 本月已实现盈亏（Trade.realized_pnl 累计）
        _rows = Trade.query.filter(Trade.trade_date >= month_start).all()
        month_pnl = sum(float(t.realized_pnl or 0) for t in _rows)
        # ② 月初账户资产：优先本月之前最近一条快照，否则累计买入额近似（初始本金）
        _snap = (AccountSnapshot.query
                 .filter(AccountSnapshot.snapshot_date < month_start)
                 .order_by(AccountSnapshot.snapshot_date.desc()).first())
        if _snap and _snap.total_asset:
            month_start_asset = float(_snap.total_asset)
        else:
            _all = Trade.query.order_by(Trade.trade_date.asc()).all()
            _buys = sum(float(t.amount) for t in _all if t.direction == '买入')
            if _buys > 0:
                month_start_asset = _buys
        # ③ 连续亏损笔数（按日期倒序，从最近卖出往前数 realized_pnl<0）
        _sells = (Trade.query.filter(Trade.direction == '卖出')
                  .order_by(Trade.trade_date.desc(), Trade.id.desc()).all())
        for t in _sells:
            _pnl = float(t.realized_pnl or 0)
            if _pnl < 0:
                consecutive_losses += 1
            else:
                break
    except Exception as e:
        logger.debug("账户月度风险读取失败（降级中性）: %s", e)

    return evaluate_monthly_risk_status(
        month_pnl=month_pnl,
        month_start_asset=month_start_asset or DEFAULT_ACCOUNT_CAPITAL,
        consecutive_losses=consecutive_losses,
        cfg=cfg)


def write_account_risk_status(data_dir: str, today: Optional[date] = None,
                              cfg: Optional[dict] = None) -> dict:
    """daemon 侧：计算并原子写 `<data_dir>/account_risk_status.json`（失败不抛错）。"""
    try:
        status = compute_from_account(today=today, cfg=cfg)
        status['as_of'] = (today or date.today()).isoformat()
        _path = os.path.join(data_dir, STATE_FILE_NAME)
        _tmp = _path + '.tmp'
        os.makedirs(os.path.dirname(_path), exist_ok=True)
        with open(_tmp, 'w', encoding='utf-8') as f:
            json.dump(status, f, ensure_ascii=False, indent=2)
        os.replace(_tmp, _path)
        logger.info("账户月度风险状态已落盘: halt=%s 亏损=%.2f%% 连亏=%d",
                    status['monthly_halt'], status['monthly_loss_pct'],
                    status['consecutive_losses'])
        return status
    except Exception as e:
        logger.warning("账户月度风险状态落盘失败: %s", e)
        return evaluate_monthly_risk_status()


def _default_data_dir() -> str:
    return os.environ.get('DATA_DIR') or os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'data'))


def get_account_risk_status(data_dir: Optional[str] = None,
                            cfg: Optional[dict] = None) -> dict:
    """JUD 侧只读：读快照（缺失/异常 → 中性，不阻塞）。"""
    try:
        _path = os.path.join(data_dir or _default_data_dir(), STATE_FILE_NAME)
        if os.path.exists(_path):
            with open(_path, encoding='utf-8') as f:
                _d = json.load(f)
            if isinstance(_d, dict) and 'monthly_halt' in _d:
                return _d
    except Exception as e:
        logger.debug("账户月度风险快照读取失败（中性降级）: %s", e)
    return evaluate_monthly_risk_status(cfg=cfg)
