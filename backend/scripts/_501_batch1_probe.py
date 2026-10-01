"""501号 批次1 探针——RAW 当前生效修复（#R1/#R4/#R21/#R23/#R26）

隔离/桩验证（不发真实查询、不写库）：
  #R1   data_daemon._raw2_one 三处 _sr_once 消费点＝失败置 None 时兜底空字典（源码断言）
  #R4   compute_win_rates 10d/20d 独立样本门槛（少样本 → NaN）
  #R21  GTJA_HL20 分母仅正值（负/NaN 低值 → NaN 而非 inf）
  #R23  VOL_RATIO_20.name_cn == "20日量比"
  #R26  get_win_rates 查询失败记日志、不静默吞（桩抛错 → 回退实时计算）
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd  # noqa: E402

FAIL = []


def check(cond, msg):
    print(('  OK  ' if cond else '  FAIL') + ' ' + msg)
    if not cond:
        FAIL.append(msg)


# ══════════════ #R1：_raw2_one 三处 _sr_once 消费点 None 兜底 ══════════════
_SRC = open(
    os.path.join(os.path.dirname(__file__), '..', 'data_daemon.py'),
    encoding='utf-8').read()
for anchor, label in [
    ("_sr = _sr_once or {}", "衍生 support_resistance"),
    ("geo = _sr_once or {}", "risk_ext 几何"),
    ("_sr_result = _sr_once or {}", "structure_ext 结构位置"),
]:
    check(anchor in _SRC, f"#R1 {label}：_sr_once or {{}} 兜底已接线")

# ══════════════ #R23：VOL_RATIO_20 中文名 ══════════════
from app.factors.builtin.a_stock import VOL_RATIO_20  # noqa: E402

check(VOL_RATIO_20.name_cn == "20日量比",
      f"#R23 VOL_RATIO_20.name_cn == '20日量比'（实际 {VOL_RATIO_20.name_cn!r}）")

# ══════════════ #R21：GTJA_HL20 分母守卫 ══════════════
from app.factors.builtin.gtja import GTJA_HL20  # noqa: E402

_f = GTJA_HL20()
_df_hl20 = pd.DataFrame({
    'high': [10.0 + i for i in range(22)],
    'low':  [9.0 + i for i in range(22)],
})
# 构造含 0/负低值：low 全为 0 → where(low>0) → NaN（原 replace(0,np.nan) 只拦 0，负值会 inf）
_df_zero = pd.DataFrame({'high': [10.0] * 22, 'low': [0.0] * 22})
_out_zero = _f.calculate(_df_zero)
check(_out_zero.isna().all(),
      f"#R21 GTJA_HL20 零低值 → 全 NaN（实际 {_out_zero.tolist()[:3]}）")
_df_neg = pd.DataFrame({'high': [10.0] * 22, 'low': [-1.0] * 22})
_out_neg = _f.calculate(_df_neg)
check(_out_neg.isna().all(),
      f"#R21 GTJA_HL20 负低值 → 全 NaN（原实现会 inf，实际 {_out_neg.tolist()[:3]}）")
_out_pos = _f.calculate(_df_hl20)
check(not _out_pos.isna().all() and (_out_pos.dropna() > 1).all(),
      f"#R21 GTJA_HL20 正常正值仍产出 >1（实际 {_out_pos.dropna().tolist()}）")

# ══════════════ #R4 + #R26：compute_win_rates / get_win_rates ══════════════
from app.data.precompute_indicator_manager import PrecomputeIndicatorManager  # noqa: E402

# —— 桩 1：#R4 少样本 10d/20d → NaN ——
# 窗口：10 个交易日（01-01..01-10）。entry 日 idx 0..4；5d 前瞻 idx+5 ∈ [5,9] 全在窗口
#   （5d 样本=5 ≥ _MIN_SAMPLES）；10d/20d 前瞻 idx+10/20 全超出窗口 → 样本=0
#   → 期望：win_rate_5d 正常、win_rate_10d/20d = NaN、samples=5
_DATES = [f"2026-01-{d:02d}" for d in range(1, 11)]   # 10 交易日：01-01..01-10
_ENTRY_DAYS = [0, 1, 2, 3, 4]                         # 5 只股票 entry 日索引
_CODES = [f"T{i:02d}.SZ" for i in range(1, 6)]


class _StubECM_Short10:
    """5d 样本=5（≥ _MIN_SAMPLES=5）；10d/20d 前瞻日超出 10 日窗口 → 0 样本

    → 期望：win_rate_5d 正常、win_rate_10d/20d = NaN、samples=5
    """
    def _query_shard(self, table, sql, params=None):
        if "strategy_signal_detail" in sql:
            import json
            rows = [{'ts_code': _CODES[i], 'trade_date': _DATES[_ENTRY_DAYS[i]],
                     'signal_json': json.dumps({'signals': {'S1': {'signal': 'BUY'}}})}
                    for i in range(5)]
            return pd.DataFrame(rows)
        if "DISTINCT trade_date" in sql:
            return pd.DataFrame({'trade_date': _DATES})
        if "SELECT ts_code, trade_date, close" in sql:
            # 全部 10 日 × 5 只：entry 与 5d 前瞻日均有 close（10d/20d 前瞻日不需要）
            rows = [{'ts_code': _CODES[i], 'trade_date': _DATES[d], 'close': 100.0}
                    for i in range(5) for d in range(10)]
            return pd.DataFrame(rows)
        return pd.DataFrame()


_mgr = PrecomputeIndicatorManager(_StubECM_Short10())
_df_r4 = _mgr.compute_win_rates()
check(not _df_r4.empty, "#R4 compute_win_rates 有结果行")
if not _df_r4.empty:
    r = _df_r4.iloc[0]
    check(r['samples'] == 5, f"#R4 samples==5（实际 {r['samples']}）")
    check(pd.isna(r['win_rate_10d']), f"#R4 10d 0 样本 → win_rate_10d NaN（实际 {r['win_rate_10d']}）")
    check(pd.isna(r['win_rate_20d']), f"#R4 20d 0 样本 → win_rate_20d NaN（实际 {r['win_rate_20d']}）")
    check(pd.isna(r['sharpe_20d']), f"#R4 20d 0 样本 → sharpe_20d NaN（实际 {r['sharpe_20d']}）")

# —— 桩 2：#R26 get_win_rates 查询失败记日志并回退实时计算 ——
class _StubECM_Throw:
    """_query_shard 对 win_rate_cache 抛错；strategy_signal_detail 无数据

    → 期望：不抛错、回退 compute_win_rates 返回空 DataFrame
    """
    def _query_shard(self, table, sql, params=None):
        if "win_rate_cache" in sql:
            raise RuntimeError("模拟 DB 故障")
        return pd.DataFrame()


import logging  # noqa: E402


class _Cap(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []
    def emit(self, record):
        self.records.append(record)


_logger = logging.getLogger('app.data.precompute_indicator_manager')
_cap = _Cap()
_logger.addHandler(_cap)
_logger.setLevel(logging.WARNING)
_mgr2 = PrecomputeIndicatorManager(_StubECM_Throw())
_out26 = _mgr2.get_win_rates()
check(isinstance(_out26, pd.DataFrame) and _out26.empty,
      "#R26 get_win_rates DB 故障 → 回退实时计算返回空（不抛错）")
check(any('win_rate_cache 查询失败' in r.getMessage() for r in _cap.records),
      "#R26 查询失败已记 warning 日志（不再静默吞）")
_logger.removeHandler(_cap)

# ══════════════ 汇总 ══════════════
print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print("ALL PASSED")
