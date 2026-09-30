"""500号 批次4 探针——内存与分钟/重采样（#13~#19 + #50~#54）

桩验证（不依赖真实库/网络）：
  #13 clear_all 清 _lhb_detail
  #14 读方法深拷贝（嵌套结构不被外部改写污染内部）
  #15 get_minute_kline 按 ts_code 索引 O(k) + 上限裁剪
  #16 分钟时间基准：位置索引（非 int(idx)）+ 240 根上限 + trade_date 归一
  #17 backfill_1min 窗口聚合（不读全历史）
  #18 重采样组内排序（乱序输入 Open/Close 正确）
  #19 同/粗频直返仍归一；周键 ISO
  #50 聚合 low 缺键不产 inf
  #51 watchlist 连接上下文
  #53 分钟频率共享常量
  #54 非 dict 元素过滤
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd  # noqa: E402
from app.data.in_memory_store import InMemoryStateStore  # noqa: E402
from app.data.kline_resampler import KlineResampler  # noqa: E402

FAIL = []


def check(cond, msg):
    print(('  OK  ' if cond else '  FAIL') + ' ' + msg)
    if not cond:
        FAIL.append(msg)


# ── #13 clear_all 清 _lhb_detail ────────────────────────────────────────
print("=== #13/#14/#15 in_memory_store ===")
st = InMemoryStateStore()
st.update_lhb_detail([{'ts_code': '000001.SZ', 'seat': 'A'}])
st.update_snapshot([{'ts_code': '000001.SZ'}])
st.clear_all()
check(st.get_lhb_detail() == [], "#13 clear_all 清除席位级龙虎榜")
check(st.get_snapshot() == [], "#13 clear_all 清快照")

# #14 深拷贝：读出的嵌套结构改写不影响内部
st2 = InMemoryStateStore()
st2.update_snapshot([{'ts_code': 'X', 'nested': {'k': [1, 2]}}])
r = st2.get_by_code('X')
r['nested']['k'].append(999)
check(st2.get_by_code('X')['nested']['k'] == [1, 2], "#14 深拷贝：外部改写不回污内部")

# #15 按 ts_code 索引 + 裁剪
st3 = InMemoryStateStore()
st3.append_minute_kline([{'ts_code': 'A', 't': 1}, {'ts_code': 'B', 't': 2}])
check(len(st3.get_minute_kline('A')) == 1, "#15 单只过滤正确")
check(len(st3.get_minute_kline()) == 2, "#15 全量读取正确")
st3._MINUTE_MAX_BARS = 3
st3.append_minute_kline([{'ts_code': 'C', 't': i} for i in range(5)])
check(len(st3.get_minute_kline()) == 3, "#15 超过上限按 FIFO 裁剪到 3")
check(len(st3.get_minute_kline('C')) == 3, "#15 裁剪后索引同步（C 剩 3）")

# ── #16 分钟时间基准 ────────────────────────────────────────────────────
print("=== #16 minute_backfill 时间基准 ===")
import inspect  # noqa: E402

import app.data.minute_backfill as mb  # noqa: E402

_src16 = inspect.getsource(mb._get_mootdx_minutes_safe)
check('for pos, r in enumerate(raw.to_dict' in _src16, "#16(a) enumerate 位置索引（不再 int(idx)）")
check('if pos >= 240' in _src16, "#16(b) 单日 240 根上限")
_src_ce = inspect.getsource(mb._cache_to_ecm)
check('pd.to_datetime' in _src_ce and "dt.strftime('%Y-%m-%d')" in _src_ce, "#16(c) trade_date 归一")

# ── #17 backfill_1min 窗口聚合 ──────────────────────────────────────────
print("=== #17 窗口聚合 ===")
_src17 = inspect.getsource(mb.backfill_1min)
check('window_records' in _src17, "#17 仅窗口内记录聚合（不再全历史读）")

# ── #18/#19/#50/#53/#54 kline_resampler ─────────────────────────────────
print("=== #18/#19/#53/#54 kline_resampler ===")
ks = KlineResampler()
check('60min' in KlineResampler.MINUTE_FREQS, "#53 分钟频率共享常量含 60min")

# #18 乱序输入 → Open=最早 Close=最晚
_d = [
    {'trade_time': '2026-09-29 14:00:00', 'open': 12.0, 'high': 12.5, 'low': 11.5, 'close': 12.2, 'vol': 10},
    {'trade_time': '2026-09-29 09:30:00', 'open': 10.0, 'high': 10.5, 'low': 9.5, 'close': 10.3, 'vol': 20},
    {'trade_time': '2026-09-29 11:00:00', 'open': 11.0, 'high': 11.5, 'low': 10.5, 'close': 11.2, 'vol': 30},
]
_daily = ks.resample(_d, '1min', 'daily')
check(len(_daily) == 1 and _daily[0]['open'] == 10.0 and _daily[0]['close'] == 12.2,
      f"#18 组内排序后 Open=10.0/Close=12.2（实={_daily[0]['open']}/{_daily[0]['close']}）")

# #19 同频直返仍归一（排序）
_same = ks.resample(list(reversed(_d)), 'daily', 'weekly') if False else \
    ks.resample([{'trade_date': '2026-09-29', 'open': 1, 'high': 1, 'low': 1, 'close': 1, 'vol': 1},
                 {'trade_date': '2026-09-25', 'open': 1, 'high': 1, 'low': 1, 'close': 1, 'vol': 1}], 'daily', 'daily')
# daily→daily：走 _normalize_bars 排序
check([b['trade_date'] for b in _same] == ['2026-09-25', '2026-09-29'], "#19 同频直返排序归一")
check(KlineResampler.FREQ_AGG_MAP['weekly']['format'] == '%G-W%V', "#19 周键统一 ISO")

# #54 非 dict 元素过滤
_mixed = [{'trade_time': '2026-09-29 09:30:00', 'open': 1, 'high': 1, 'low': 1, 'close': 1, 'vol': 1}, 'BAD', None]
try:
    out54 = ks.resample(_mixed, '1min', 'daily')
    check(len(out54) == 1, "#54 非 dict 元素被过滤（不抛 AttributeError）")
except Exception as e:
    check(False, f"#54 抛错: {e}")

# #50 low 缺键不产 inf
_recs = [{'trade_time': '2026-09-29 09:30:00', 'open': 1, 'high': 2, 'low': 1, 'close': 1, 'vol': 1},
         {'trade_time': '2026-09-29 09:31:00', 'open': 1, 'high': 2, 'vol': 1}]  # 缺 low
agg = mb._resample_minute(_recs, '1min', '5min')
check(agg and agg[0]['low'] != float('inf'), f"#50 缺 low 不产 inf（实={agg[0]['low'] if agg else 'N/A'}）")

# #51 watchlist 连接上下文
_src51 = inspect.getsource(mb.get_watchlist_stocks)
check('with sqlite3.connect' in _src51, "#51 连接上下文管理")

print()
if FAIL:
    print(f"❌ {len(FAIL)} 项失败")
    sys.exit(1)
print("✅ 批次4 探针全绿（#13~#19/#50~#54）")
