"""493 批次5 端到端探针（只读/临时写）：账户月度风险 预计算 → JUD 只读 全链

① 临时向 app.db 插入一组「本月 3 笔连续亏损」的卖出记录（探针末尾清理）；
② 调 daemon 侧 write_account_risk_status() → 落 account_risk_status.json；
③ 调 JUD 侧 get_account_risk_status() 读回 → 应 monthly_halt=True；
④ StatusEngine._assemble 顶层字段应透传 monthly_halt=True；
⑤ 清理临时 Trade 记录 + 快照文件。

安全：仅操作本地开发库（data/app.db），新增行带探针标记 stock_name='__PROBE_493__'，
      结束时按标记删除；账户原为空（0 行）故无残留风险。
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app import create_app, db  # noqa: E402
from app.models.trade import Trade  # noqa: E402
from app.services.account_risk_status import (  # noqa: E402
    get_account_risk_status, write_account_risk_status,
)

DATA_DIR = os.environ.get('DATA_DIR') or os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'data'))
MARK = '__PROBE_493__'
TODAY = date.today()


def main():
    app = create_app()
    with app.app_context():
        # 0. 清理历史探针残留
        Trade.query.filter(Trade.stock_name == MARK).delete()
        db.session.commit()

        # 1. 插入本月 3 笔连续亏损卖出（每笔亏 2 万 ≈ 2%；账户本金 100 万）
        for i in range(3):
            db.session.add(Trade(
                ts_code=f'60000{i}.SH', stock_name=MARK, direction='卖出',
                trade_date=TODAY, price=10.0, quantity=1000, amount=10000.0,
                realized_pnl=-20000.0,
            ))
        # 一笔买入建立本金口径（100 万）
        db.session.add(Trade(
            ts_code='600009.SH', stock_name=MARK, direction='买入',
            trade_date=TODAY, price=100.0, quantity=10000, amount=1_000_000.0,
        ))
        db.session.commit()

        # 2. daemon 侧预计算 → 落快照
        st_written = write_account_risk_status(DATA_DIR, today=TODAY)
        print('① 预计算快照:', {k: st_written[k] for k in
                              ('monthly_halt', 'monthly_loss_pct', 'consecutive_losses', 'halt_reason')})

        # 3. JUD 侧只读
        st_read = get_account_risk_status(DATA_DIR)
        print('② JUD 只读:', {k: st_read[k] for k in
                            ('monthly_halt', 'monthly_loss_pct', 'consecutive_losses')})

        # 4. StatusEngine._assemble 顶层透传
        from app.opportunity_atlas.status_engine import StatusEngine
        se = StatusEngine()
        row = se._assemble(
            '600000.SH', dims={'risk': {'light': 'green'}}, lifecycle=None,
            l0={'hard_veto': False, 'hold_only': False, 'soft_risks': [], 'position_coeff': 1.0},
            l2={'opportunity_state': 'enter', 'state_evidence': [], 'conflict_evidence': [],
                'consensus_rate': 0.8, 'direction': 'bullish'})
        print('③ _assemble 顶层: monthly_halt=%s monthly_loss_pct=%s consecutive_losses=%s'
              % (row.get('monthly_halt'), row.get('monthly_loss_pct'), row.get('consecutive_losses')))
        print('   opportunity_state 未被改动 =', row['opportunity_state'])

        # 5. 清理
        Trade.query.filter(Trade.stock_name == MARK).delete()
        db.session.commit()
        _f = os.path.join(DATA_DIR, 'account_risk_status.json')
        if os.path.exists(_f):
            os.remove(_f)
        print('④ 已清理探针记录与快照文件')

        ok = (st_written['monthly_halt'] is True and st_read['monthly_halt'] is True
              and row.get('monthly_halt') is True and row['opportunity_state'] == 'enter')
        print('\nRESULT:', 'ALL_OK' if ok else 'GAP')


if __name__ == '__main__':
    main()
