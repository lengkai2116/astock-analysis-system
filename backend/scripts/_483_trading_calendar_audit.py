"""483号 附：交易日历交叉审计（用权威行情源校验 trading_hours 的假期/调休配置）

用法（backend 下）：.venv/bin/python scripts/_483_trading_calendar_audit.py

两个方向：
  正向：对 trading_hours 中每个特殊日期（法定节假日 + 调休上班周末），用 Tushare `daily`
        当日行数验证 —— 节假日应 0 行，调休上班日应 >0 行。
  反向：扫描 daily_cache 中「周六/周日却有行情」的日期 —— 它们才是真实的调休交易日，
        若未登记进 `_WORKDAY_WEEKENDS` 即为漏登记（会导致该日被当节假日跳过）。

背景：2026-09-26 审计发现 5 个「调休上班」条目（01-04/02-14/02-28/05-09/09-20）行情均为 0 行
（即实际休市），且 daily_cache 全历史 1268 个交易日内无任何周末有行情 → 用户拍板删除该 5 条
（保留未来 2026-10-10 待验证）。详见 483 号文档。修改日历后请重跑本脚本复核。
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.data.tushare_provider import TushareProvider, _ts
from app.utils import trading_hours as th


def audit_forward(p) -> list:
    """正向：逐条验证特殊日期配置与行情一致性"""
    today = datetime.now()
    allsp = sorted(set(th._DEFAULT_HOLIDAYS) | set(th._WORKDAY_WEEKENDS))
    past = [d for d in allsp if datetime.strptime(d, '%Y-%m-%d') <= today]
    future = [d for d in allsp if datetime.strptime(d, '%Y-%m-%d') > today]
    print(f"[正向] 审计 {len(past)} 个已过特殊日期（未来 {len(future)} 个无法验证: {future}）")
    mismatch = []
    for d in past:
        df = _ts(p.pro.daily, trade_date=d.replace('-', ''))
        n = 0 if df is None or df.empty else len(df)
        cfg_holiday = d in th._DEFAULT_HOLIDAYS
        ok = (cfg_holiday == (n == 0))
        if not ok:
            mismatch.append((d, '配置=假期' if cfg_holiday else '配置=调休上班', n))
        print(f"  {d} 配置={'假期' if cfg_holiday else '调休上班'} 行情={n} {'OK' if ok else '<== 不一致'}")
    return mismatch


def audit_reverse() -> list:
    """反向：库里「周末却有行情」= 真实调休交易日；未登记进 _WORKDAY_WEEKENDS 即漏登记"""
    from app.data.sharding_manager import sharding_manager as sm
    conn = sm.get_connection(sm.get_db_for_table('daily_cache'))
    rows = conn.execute("SELECT DISTINCT trade_date FROM daily_cache").fetchall()
    dates = [str(r[0]) for r in rows]
    weekend = [d for d in dates if datetime.strptime(d, '%Y-%m-%d').weekday() >= 5]
    undeclared = [d for d in weekend if d not in th._WORKDAY_WEEKENDS]
    print(f"[反向] daily_cache 共 {len(dates)} 个交易日，其中周末有行情 {len(weekend)} 个")
    print(f"  周末有行情但未登记调休: {undeclared if undeclared else '无 ✅'}")
    return undeclared


def main():
    p = TushareProvider()
    mismatch = audit_forward(p)
    print()
    undeclared = audit_reverse()
    print(f"\n结论：正向不一致 {len(mismatch)} 项；反向漏登记 {len(undeclared)} 项")
    return 1 if (mismatch or undeclared) else 0


if __name__ == '__main__':
    sys.exit(main())
