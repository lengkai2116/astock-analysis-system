---
title: 446号 dim3 RPS 缺产出（D12）
type: 方案（B类引擎输出契约补全，445 §6.1 dim3）
date: 2026-09-17
version: v1.0
status: ✅ 已完成
related:
  - 445-dim2-dim7引擎正确性知识库核查——本号是 445 §6.1 dim3「RPS 被 RSI 顶替 / 强势股 RPS 信号缺失」处置
  - 450-dim3量价背离处置——dim3 系列前一号（背离权威标签化+格兰威尔多日粒度+50形态对齐，已完成 ①④⑤）
  - 446-dim4资金价格背离补产出（D11）——445 输出契约补全先例（纯补产出思路）
---

# 446 号 D12 — dim3 RPS 缺产出

## 一、问题确认（445 §6.1 dim3 偏差，代码级已核）

**445 §6.1 dim3 输出项**：「……RPS>85 被 RSI 顶替」——强弱因子 `is_` 只读 `rsi14`，**RPS（相对强弱排名百分位）从不参与评分**，强势股筛选信号缺失。

**引擎现状**（`dim3_vp_engine.py:Dim3VPEngine.evaluate`）：
- 10 分制 health_score 公式：`raw = vp_score + ve + ms + cs + is_ + dp`，其中 `is_`（RSI 内驱强度）由 `rsi14` 映射（60<rsi≤70→1 / 30≤rsi<40→0.8 / 极值→0.2 / 否则 0.5）。
- 数据侧：`relative_strength_cache`（compute_cache.db，438号缺口③/432号产出）存每股 20d/60d 收益 + 双基准（000001.SH/000300.SH）超额收益，**但无跨截面 RPS 百分位列**；dim1 data_context 也未预加载。
- 结论：RPS 数据与评分链路**双缺失**——数据层没有 RPS 分位，dim3 强弱判据只有 RSI 一维，445 登记的正是这「强势股 RPS 信号缺失」。

**知识库权威**：
- 《量价形态打分系统》：**RPS>85 → +1 分**（加分项，纳入健康度）。
- 《RPS相对强弱指标》：RPS = 个股涨幅在全部股票涨幅排名中的位次值 `(1-rank/n)*100`；欧奈尔狂飙前平均 RPS=87，A 股 80 以上——强势股应显著高于 80。

## 二、修复方案（数据→引擎 4 文件接线；**用户拍板：补产出 + RPS>85 入 health_score（+1）**）

**判定基准不变**（445 冻结的 dim3 量价四阶/形态/背离/量价齐升权重），只在强弱判据上，除 RSI 外**新增 RPS 强势加分项**（+1），并补齐 RPS 产出。

### 2.1 `data_daemon.py:_compute_relative_strength`（跨截面 RPS 补算 + 写出）

- 在现有每股 20d/60d 收益 `ret_map` 后，新增跨截面 RPS 百分位：
  `ret20_series = pd.Series({c: r[0] for c,r in ret_map.items() if r[0] is not None})`
  `rps20_by_code = (ret20_series.rank(pct=True)*100).to_dict()`（`len>=2` 才产出，否则 None，由消费侧兜底不产结论）；60d 同构。
- 行 tuple 由 9 元组扩为 **11 元组**：追加 `rps20=round(rps20_by_code[code],2)`、`rps60`。RPS 为市场截面，双基准行同值。
- 双基准窗口内 20d/60d 收益、超额收益（ex_ret_*）口径完全不变。

### 2.2 `enhanced_cache_manager.py`（schema + 写入 + 存量补列）

- `_init_compute_tables` 建表增加 `rps_20d REAL, rps_60d REAL`。
- `cache_relative_strength` 文档串/占位符升至 11 列，INSERT 增 `rps_20d, rps_60d`，并在开头调用**新增** `_ensure_relative_strength_rps_columns()`（幂等：`PRAGMA table_info` 已存在即跳过，否则 `ALTER TABLE ADD COLUMN`，镜像 `_ensure_market_stats_cache_column` 手法）——对存量库（当前 compute_cache.db 仍是旧 9 列）首次写入时自动补列，无需手工迁移。
- 读方 `get_relative_strength` 用 `SELECT *`，随附新列，无需改动。

### 2.3 `dim1_signal_engine.py`（data_context 预加载 RPS）

- 类别5（板块热度之后）新增：`dm.cache.get_relative_strength(ts_code)` → 取任一行 `rps_20d/rps_60d/asof_date` 入 `loaded_data['relative_strength']`。
- **不加入 optional 校验列表**（读方空时返回 `[]` 而非抛异常，若加进 `_validate` 会把「无 RPS 数据」误标为 missing，改变 completeness_score/quality_level）——数据缺失时 dim3 走中性放行，不影响门禁评分。

### 2.4 `dim3_vp_engine.py:evaluate`（评分接线 + 契约键）

- 读取 RPS：优先 `data_context['relative_strength']`（dim1 预加载路径），取 `rps_20d`，缺则 `rps_60d`；未预加载时回退 `self._get_dm().cache.get_relative_strength(ts_code)`。
- 强弱加分：`rps_factor = 1 if (rps is not None and rps > 85) else 0`；无数据不给分不扣分（保守）。`raw` 公式追加 `rps_factor`。
- 契约键 / 文案 / 稽核（**只加输出，不调其它判定**）：
  - `status_description['rps']`：`f'{rps:.1f}/100'` 或 `'数据不足'`。
  - `status_description['plain']`：RPS>85 追加 `，RPS=.. 强势（全市场涨幅居前）`。
  - audit 新增条件「相对强弱RPS」：`satisfied = rps is None or rps > 85`（数据不足中性放行），`threshold='RPS>85（数据不足时中性放行）'`。

**SIG/JUD 边界合规**：本号只给 dim3 加**分析结论 + 现状描述（RPS 加分/强证据）**，不产灯色/判定；`judgment.light` 仍由 vp_state 决定，RPS 加分仅反映在 health_score 数值（供 JUD 后续消费），符合 444/439 边界标准。

## 三、影响评估（445 约束：不破坏 dim3 基准）

- **评分只加不减**：RPS>85 仅 +1，RPS≤85/数据不足一律 0 分——对既有无 RPS 数据存量产出**完全无变化**（rps None → factor 0）；仅 RPS>85 的强势股分数上移 1 档（10 分制取整，多数情形 hs 不变或 +1）。
- **数据链路只增列**：daemon 补算 RPS 列、manager 幂等补 schema，对 ret/ex_ret 既有列零改动，读方 `SELECT *` 兼容。
- **消费链受益**：dim3 现可输出「RPS=xx 强势」证据 + audit 强弱闸门，强势股筛选信号补齐；dim8/前端可读。
- **边界安全**：跨市场 <2 股（无对比）→ RPS None → 消费侧中性；evaluate 缺 RPS 数据不崩、不扣分。

## 四、验证（全部通过）

### 4.1 单元测试 `tests/test_446_dim3_rps_output.py`（11 测试）✅
- **TestRpsScoring（7）**：RPS>85 健康度 ≥ 无 RPS 时；缺 RPS 数据不扣分（rps=='数据不足' 且 score≥0）；RPS=60（≤85）不加分且 rps 键输出 `60.0/100`；audit「相对强弱RPS」RPS>85→satisfied、无数据→中性放行；plain 强 RPS 含 `RPS=` + `强势`、弱 RPS 不含。
- **TestRpsSourceWiring（4）**：dim3 evaluate 含 rps 评分接线（`rps>85`/`'rps'`/`relative_strength`）；dim1 预加载含 `relative_strength`；**daemon `_compute_relative_strength` 含 `rank(pct=True)` + `rps20/rps60_by_code` 跨截面计算**（列名 rps_20d/rps_60d 在 manager INSERT 另测）；cache manager 建表/写路径含 rps 列。
- 全程注入 `data_context`（含 daily_df + relative_strength），不触发真实 DB 回退，与 dim3 既有手法一致。

### 4.2 相关回归 ✅（58 passed）
- `test_dim3_patterns.py` 6 + `test_450_dim3_divergence_granville.py` 11 + `test_443_r2_cost_ext.py` 7 + `test_449_dim7_valuation_traps.py` 8 + `test_448_piers_hard_veto.py` 9 + `test_446_dim4_fund_price_divergence.py` 7 + `test_446_dim2_trend.py` 10 = **58 passed**

### 4.3 真实 DB 端到端 ✅
- 停 daemon（清 SQLite 锁）后用 `._compute_relative_strength()` 对真实 compute_cache.db 重算：`asof=2026-09-16 写入 11094 条（5547 股 × 2 基准）`。
- 校验：`rps_20d/rps_60d` 列已补（schema 迁移生效），最新 asof 全部有 RPS；极值合理（300010.SZ RPS20=100.0，20日领涨；无对比的 `000001.SZ` 等 RPS=… 见样本）。RPS 为市场截面分位（最高=100），双基准行同值。
- 验证后已重启 daemon + start_daemon.sh 看守（恢复原运行态）。

> ⚠ 与 D10/D11 相同的环境限制：DB/network 类沙箱 test（test_411_pipeline/test_418_jud_v390 等）运行时挂起，与本改动无关，已单独记录；本改动纯补 RPS 列 + 新增输出键 + 强弱加分，定向回归已覆盖全部相关调用面。

## 五、约束 / 后续

- 本号只补「RPS 缺产出 + RPS>85 入 health_score（+1）」，**不调 dim3 判定基准**（量价四阶/形态/背离/八准则）。RPS≤85 及无数据不加分，存量产出零变化。
- 445 dim3 剩余登记项：「八准则装饰性+单日粒度+放量滞涨逻辑缺陷」「cs 值域 bug」「背离用 MACD 柱代成交量+缺底背离」——其中 背离/八准则/cs/50形态 已于 450 号④⑤①② 处置；本号接续补 RPS。
- 数据缺口（dim6 PIERS I/S、dim7 FCF）与 dim6 流动性口径仍在队列。

## 工作进度记录（2026-09-17）

- [x] 445 §6.1 dim3「RPS 被 RSI 顶替 / 强势股 RPS 信号缺失」核查（wiki《量价形态打分系统》RPS>85→+1、《RPS相对强弱指标》定义权威）
- [x] 用户拍板范围：**补产出 + RPS>85 入 health_score（+1）**
- [x] data_daemon 跨截面 RPS 补算（rank(pct=True)*100，11 元组写出）
- [x] cache manager schema 加列 + 写路径加列 + 幂等存量补列（_ensure_relative_strength_rps_columns）
- [x] dim1 data_context 预加载 relative_strength（不入 optional，避免误标缺失）
- [x] dim3 evaluate 评分接线（data_context 优先 → DB 回退；rps_factor +1；rps 契约键/plain 强证据/audit 相对强弱RPS）
- [x] 校验：py_compile OK；新单测 11 passed + dim3 及相关回归 58 passed；真实 compute_cache.db 端到端重算（asof 09-16 11094 条含 RPS）
- [x] 落稿（本方案）+ 项目记忆
