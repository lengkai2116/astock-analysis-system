# 473号 dim6 PIERS-E 高杠杆判据数据供给修复（debt_to_assets 补产）

## 起因
dim2-dim7 引擎代码核查（承 470/471 后），dim6 `_assess_piers_leverage` 高杠杆判据的 `debt_to_assets` 键**从未进 pre_feat**（数据`因`层缺口）：

- **证据**：`_raw2_one` 的 `valuation_ext` 段只产 `roe/roce/pe_ttm/pb/ps_ttm/total_mv`，**不含 `debt_to_assets`**。对 `data_daemon.py` 全文 grep `debt_to_assets|负债率|debt` = **0 匹配** → RAW 从不产该键。
- `_flatten_pre_feat` 只透传 pre_feat 已有键 → flat tags **恒无 `debt_to_assets`**（仅 `roce` 因 472 修复可用）。
- 于是 `_assess_piers_leverage` 的 `tags.get('debt_to_assets')` 恒 None → **必然走独立 `dm.get_cached_fina_indicator(ts_code)` 兜底查询**，异常被 `except: pass` 静默吞 → 高杠杆判据可静默失效。
- **与 411 号模式相悖**：dim6 `evaluate` 已注入 `data_context`，dim1 已预加载 `data_context['fina_df']`（= get_cached_fina_indicator，dim1 L114-118 明确「fina_indicator_cache（dim7需要）」。dim7 已 461-2 统一优先读 tags、dim4 走 market_context，唯 dim6 PIERS-E 仍是独立查询老模式。

## 修复（A 方案，用户拍板）
`_raw2_one` 的 `valuation_ext` 段，在 `roe` 回填处同步补产：
```python
_dta = latest_fina.get('debt_to_assets')
try:
    _dta = None if _dta is None or _dta != _dta else float(_dta)
except (TypeError, ValueError):
    _dta = None
if _dta is not None:
    _val_feat['debt_to_assets'] = _dta   # 真实列，缺数据不产键（对齐 472 禁假值）
```
让 flat tags 恒含真实 `debt_to_assets` → dim6 PIERS-E 走 tags 预计算短路，免 DB 兜底。

## 落地
- py_compile OK。
- 手动触发全量 RAW-2 重算（5553 只，`scripts/probe_473_recompute.py`，沿用 472 触发方式）。
- **注意**：无参 `_get_active_codes()` 的 fallback（`SELECT DISTINCT trade_date FROM daily_cache`）会命中总库空壳抛 `no such table`；必须显式传 `'2026-09-21'`。

## 验证
全量重算完成（5551/5553 只成功，耗时 892.7s），探针实证 `debt_to_assets` 已入 pre_feat `valuation_ext`：

| 股票 | debt_to_assets | roce | 判定 |
|---|---|---|---|
| 600519.SH 茅台 | 12.81% | 33.46% | 负债低+回报高，不触发 ✅ |
| 000008.SZ | 66.86% | -3.52% | 负债未越线，不触发 |
| 000002.SZ 万科 | 73.51%>70% | -17.77% | **真实高杠杆触发** ✅ |

三只 `flat.debt_to_assets=有` → dim6 `_assess_piers_leverage` 走 `tags.get()` 预计算短路，**不再依赖 DB 兜底查询**（异常被静默吞的隐患消除）。

全市场（trade_date=2026-09-21）`valuation_ext.debt_to_assets` 有值 5636 行、`roce` 有值 87252 行（含历史多期）。

## 待办
- 标准 ROCE 补采 current_liab（472 已记录，本号不涉）。
- dim6 `_assess_piers_leverage` docstring 描述「debt_to_assets 已落库…读取优先级 tags 预计算」现与真实一致（修复后 tags 确含）。
