"""483号 附：交易日历交叉审计（用权威行情源校验 trading_hours 的假期/调休配置）

用法（backend 下）：.venv/bin/python scripts/_483_trading_calendar_audit.py

口径：对 trading_hours 中每个特殊日期（法定节假日 + 调休上班周末），用 Tushare `daily`
当日行数验证——节假日应 0 行，调休上班日应 >0 行。
背景：2026-09-26 审计发现 5 个「调休上班」条目（01-04/02-14/02-28/05-09/09-20）行情均为 0 行
（即实际休市），与配置不符；详见 483 号文档。修改日历后请重跑本脚本复核。
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.data.tushare_provider import TushareProvider, _ts
from app.utils import trading_hours as th


def main():
    today = datetime.now()
    p = TushareProvider()
    allsp = sorted(set(th._DEFAULT_HOLIDAYS) | set(th._WORKDAY_WEEKENDS))
    past = [d for d in allsp if datetime.strptime(d, '%Y-%m-%d') <= today]
    future = [d for d in allsp if datetime.strptime(d, '%Y-%m-%d') > today]
    print(f"审计 {len(past)} 个已过特殊日期（未来 {len(future)} 个无法验证: {future}）")
    mismatch = []
    for d in past:
        df = _ts(p.pro.daily, trade_date=d.replace('-', ''))
        n = 0 if df is None or df.empty else len(df)
        cfg_holiday = d in th._DEFAULT_HOLIDAYS
        ok = (cfg_holiday == (n == 0))
        if not ok:
            mismatch.append((d, '配置=假期' if cfg_holiday else '配置=调休上班', n))
        print(f"  {d} 配置={'假期' if cfg_holiday else '调休上班'} 行情={n} {'OK' if ok else '<== 不一致'}")
    print(f"\n不一致 {len(mismatch)} 项: {mismatch}")
    return 1 if mismatch else 0


if __name__ == '__main__':
    sys.exit(main())
