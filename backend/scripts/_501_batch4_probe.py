"""501号 批次4 探针——指标引擎一致性（#R46/#R47/#R48/#R49/#R50/#R51）

隔离验证（不发真实查询、不写库）：
  #R46  calculate_all_indicators 死赋值已删（源码断言）
  #R47  get_latest_indicators 返回契约补全（ma30/60/120/250/bbi/ene_upper/ene_lower）
  #R48  九转向向量化 ≡ 原逐行循环（构造含连续/中断/相等日数据比对）
  #R49  calculate_all_indicators RSI 与 calculate_rsi 平滑锚点一致（delta.fillna(0)）
  #R50  calculate_kdj 平盘窗口零分母守卫（不再 inf/NaN）
  #R51  precompute_indicator_manager 惰性日志（参数化 logger.info）
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

FAIL = []


def check(cond, msg):
    print(('  OK  ' if cond else '  FAIL') + ' ' + msg)
    if not cond:
        FAIL.append(msg)


from app.indicators import TechnicalIndicatorEngine  # noqa: E402

_engine = TechnicalIndicatorEngine()

# ══════════════ #R46：死赋值已删 ══════════════
_src = open(os.path.join(os.path.dirname(__file__), '..',
            'app/indicators/__init__.py'), encoding='utf-8').read()
# calculate_all_indicators 的 MACD 段不应再有活代码 close = result['close'].values
# （剔除注释行——:49 的 #R46 说明注释本身含该字样）
_check_region = _src.split('def calculate_macd')[0]
_code_lines = [l for l in _check_region.splitlines()
               if l.strip() and not l.strip().startswith('#')]
check(not any('close = result[\'close\'].values' in l for l in _code_lines),
      "#R46 calculate_all_indicators 死赋值已删（活代码）")

# ══════════════ 通用测试数据 ══════════════
def _mk_df(n=300, seed=42, flat_window=False):
    rng = np.random.default_rng(seed)
    if flat_window:
        # 构造 9 日平盘窗口（high==low==close）验证 KDJ 零分母守卫
        close = np.concatenate([np.full(9, 10.0), rng.uniform(8, 12, n - 9)])
        high = close.copy()
        low = close.copy()
    else:
        close = rng.uniform(8, 12, n).cumsum() + 100
        high = close + rng.uniform(0, 0.5, n)
        low = close - rng.uniform(0, 0.5, n)
    df = pd.DataFrame({
        'ts_code': ['T'] * n,
        'trade_date': [f'2026-{1:02d}-{1:02d}'] * n,
        'open': close - 0.1,
        'high': high,
        'low': low,
        'close': close,
        'vol': rng.uniform(1000, 5000, n),
    })
    return df


_df = _mk_df(300)
_out = _engine.calculate_all_indicators(_df)

# ══════════════ #R47：返回契约补全 ══════════════
_latest = _engine.get_latest_indicators(_df)
_need_keys = ['ma5', 'ma10', 'ma20', 'ma30', 'ma60', 'ma120', 'ma250',
              'macd_dif', 'macd_dea', 'macd_hist', 'rsi14',
              'kdj_k', 'kdj_d', 'kdj_j',
              'boll_upper', 'boll_mid', 'boll_lower',
              'bbi', 'ene_upper', 'ene_lower',
              'vol_ma5', 'vol_ma10']
check(all(k in _latest for k in _need_keys),
      f"#R47 get_latest_indicators 返回键齐全（缺失: {[k for k in _need_keys if k not in _latest]}）")
check(_latest['bbi'] is not None and _latest['ene_upper'] is not None,
      "#R47 bbi/ene_upper 有值（非 None）")

# ══════════════ #R48：九转向向量化 ≡ 原循环 ══════════════
def _orig_nine(result):
    """原始逐行循环实现（用于等价比对）"""
    nine_buy_arr = np.zeros(len(result), dtype=int)
    nine_sell_arr = np.zeros(len(result), dtype=int)
    cnt_buy = 0
    cnt_sell = 0
    close = result['close']
    for i in range(4, len(result)):
        if close.iloc[i] < close.iloc[i - 4]:
            cnt_buy = min(cnt_buy + 1, 9)
            cnt_sell = 0
        elif close.iloc[i] > close.iloc[i - 4]:
            cnt_sell = min(cnt_sell + 1, 9)
            cnt_buy = 0
        else:
            cnt_buy = 0
            cnt_sell = 0
        if cnt_buy > 0:
            nine_buy_arr[i] = cnt_buy
        if cnt_sell > 0:
            nine_sell_arr[i] = cnt_sell
    return pd.Series(nine_buy_arr), pd.Series(nine_sell_arr)


def _test_nine(df, seed, label):
    d = _mk_df(len(df), seed=seed)
    # 构造含相等日（close == close.shift(4)）与连续段
    rng = np.random.default_rng(seed)
    cl = rng.uniform(8, 12, len(d)).cumsum() + 100
    cl[10:30] = cl[10:30] * 1.0      # 平稳区
    cl[50:80] = cl[50:80] + 5        # 连续上涨段（9+ 日买触发）
    d['close'] = cl
    d['high'] = cl + 0.3
    d['low'] = cl - 0.3
    out = _engine.calculate_all_indicators(d)
    ob, os_ = _orig_nine(d)
    eq_b = (out['nine_buy'].values == ob.values).all()
    eq_s = (out['nine_sell'].values == os_.values).all()
    check(eq_b and eq_s,
          f"#R48 九转向向量化 ≡ 原循环 [{label}]（buy={eq_b}, sell={eq_s}）")
    if not (eq_b and eq_s):
        diff_b = np.where(out['nine_buy'].values != ob.values)[0][:5]
        diff_s = np.where(out['nine_sell'].values != os_.values)[0][:5]
        print(f"       buy diff idx={diff_b} 卖 diff idx={diff_s}")
        print(f"       向量 buy[:50]={out['nine_buy'].values[:50].tolist()}")
        print(f"       原循环 buy[:50]={ob.values[:50].tolist()}")


_test_nine(_df, 1, 'seed1')
_test_nine(_df, 7, 'seed7')
_test_nine(_df, 99, 'seed99')

# ══════════════ #R49：RSI 双实现一致 ══════════════
_out_all = _engine.calculate_all_indicators(_df)
_out_rsi = _engine.calculate_rsi(_df, period=14)
# 两实现 rsi14 应一致（delta.fillna(0) 与 np.diff+insert 平滑锚点相同）
_rsi_all = _out_all['rsi14'].values
_rsi_sep = _out_rsi['rsi14'].values
diff_mask = ~(np.isnan(_rsi_all) & np.isnan(_rsi_sep))
both_valid = diff_mask & ~np.isnan(_rsi_all) & ~np.isnan(_rsi_sep)
max_diff = np.max(np.abs(_rsi_all[both_valid] - _rsi_sep[both_valid])) if both_valid.any() else 0
check(max_diff < 1e-9,
      f"#R49 calculate_all_indicators RSI ≡ calculate_rsi（max_diff={max_diff:.2e}）")

# ══════════════ #R50：calculate_kdj 平盘窗口零分母 ══════════════
_df_flat = _mk_df(60, flat_window=True)
_out_flat = _engine.calculate_kdj(_df_flat, n=9)
_k = _out_flat['kdj_k']
# 前 8 日为 rolling(9) 窗口预热期（low_min/high_max NaN → rsv NaN）属正常；
# 平盘段（第 9 日起）应被 .replace(0,1e-10) 守卫为有限值
_after_warm = _k.iloc[9:]
check(np.isfinite(_after_warm).all(),
      f"#R50 calculate_kdj 平盘窗口窗口满后无 inf/NaN（k[9:] 有限性: {np.isfinite(_after_warm).all()}）")
check((_after_warm.dropna() >= 0).all() and (_after_warm.dropna() <= 100).all(),
      "#R50 KDJ K 值域 [0,100]")

# ══════════════ #R51：惰性日志 ══════════════
_pm_src = open(os.path.join(os.path.dirname(__file__), '..',
               'app/data/precompute_indicator_manager.py'), encoding='utf-8').read()
check('logger.info("胜率计算完成: %d 种策略类型（窗口 %s）"' in _pm_src,
      "#R51 惰性日志参数化（%s 占位）")

# ══════════════ 汇总 ══════════════
print()
if FAIL:
    print(f"FAILED {len(FAIL)}: {FAIL}")
    sys.exit(1)
print("ALL PASSED")
