# Dim 引擎架构合规整改实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复413号方案§七中5项未解决的架构合规问题，使dim2-dim7主路径统一走data_context，消除直调DM/ECM。

**Architecture:** 按依赖关系分4个批次串行执行：P0(无依赖快速修复) → P1(dim1管道补全) → P2(dim3/dim5/dim7接入) → P3(dim4大规模改造)。每批次完成后运行`make check`回归验证。

**Tech Stack:** Python 3.11, SQLite WAL, Flask-SocketIO, pytest

## Global Constraints

- 所有代码必须考虑 Windows 兼容性（pathlib, 无eventlet）
- DataManager 是存储层唯一数据网关
- 禁止非采集层实例化 Provider
- 禁止 use_cache=False / sync_* 调用
- 数据缺失走 sync_requests 异步队列
- dim1 是 SIG 层唯一数据入口，dim2-dim7 的 evaluate() 仅从 data_context 读取
- 降级路径保留 fallback（ecm.get_cached_* 仅出现在 except/fallback 分支）

---

## P0: 快速修复（无依赖）

### Task 1: dim1 market_stats 数据管道补全

**Covers:** §七#6 — dim1 从 daemon 内存读取 market_stats

**Files:**
- Modify: `backend/data_daemon.py:2781` (已写入 pre_feat_cache)
- Modify: `backend/app/opportunity_atlas/dimensions/dim1_signal_engine.py:191-198`

**Interfaces:**
- Consumes: pre_feat_cache 表中 market_stats 组（daemon 已写入 L2781）
- Produces: dim1 data_context 中 `market_stats` key 从 pre_feat_cache 读取

**问题分析：**
- daemon L2781 已将 `_market_stats_cache` 写入 pre_feat_cache 的 `market_stats` 组
- dim1 L191-198 仍通过 `from data_daemon import _market_stats_cache` 直接读 daemon 内存
- dim1 的 `_batch_extract()` 方法中，ext_groups 循环已能从 pre_feat_cache 读取任意组
- market_stats 未被包含在 ext_groups 列表中

- [ ] **Step 1: 确认 dim1 ext_groups 加载机制**

读取 dim1_signal_engine.py 中 `_batch_extract` 方法，确认 ext_groups 循环如何加载 pre_feat_cache 数据。

- [ ] **Step 2: 将 market_stats 加入 ext_groups**

在 dim1_signal_engine.py 的 ext_groups 列表中添加 `'market_stats'`，使 `_batch_extract` 自动从 pre_feat_cache 加载。

- [ ] **Step 3: 删除 daemon 内存直接读取**

删除 `from data_daemon import _market_stats_cache` 及相关引用，改用 `loaded_data['market_stats']`（由 ext_groups 循环填充）。

- [ ] **Step 4: 运行测试验证**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统 && make check
```
预期：619+ 测试全部通过，dim1 不再有 `from data_daemon import`。

---

### Task 2: dim7 valuation_ext 消费

**Covers:** §七#13 — dim1 加载 valuation_ext 但 dim7 不读取

**Files:**
- Modify: `backend/app/opportunity_atlas/dimensions/dim7_valuation_engine.py`

**Interfaces:**
- Consumes: `data_context['valuation_ext']`（dim1 已加载）
- Produces: dim7 `_compute_valuation()` 使用预计算估值指标

**问题分析：**
- dim1 已加载 valuation_ext 到 data_context
- dim7 `_compute_valuation()` L605-651 从 ecm 读取 daily_basic/income/balancesheet/cashflow
- dim7 `evaluate()` L717-731 接收 data_context 但未提取 valuation_ext
- valuation_ext 包含预计算的 pe_percentile/pb_percentile 等，可减少 dim7 重复计算

- [ ] **Step 1: 在 evaluate() 中提取 valuation_ext**

在 dim7 evaluate() 方法中添加 `valuation_ext = data_context.get('valuation_ext') if data_context else None`。

- [ ] **Step 2: 传递 valuation_ext 到 _compute_valuation()**

修改 _compute_valuation() 签名接收 valuation_ext 参数，优先使用预计算值，fallback 到原始计算。

- [ ] **Step 3: 运行测试验证**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统 && make check
```

---

## P1: dim3/dim5 接入改造

### Task 3: dim3 StageDetector MA 预计算接入

**Covers:** §七#5 — dim3 StageDetector 残留 ~23 处 raw MA

**Files:**
- Modify: `backend/app/opportunity_atlas/dimensions/dim3_vp_engine.py`

**Interfaces:**
- Consumes: `data_context['indicator_ma_df']`（dim1 已加载）
- Produces: StageDetector/recognize_market_condition 使用预计算 MA

**问题分析：**
- dim3 EnhancedPatternDetector.detect_all() 已支持 precomputed_ma 参数
- 但 StageDetector.detect() L2152-2155、recognize_three_bloom() L2296-2301、_calc_valuation_zones() L2269-2270、_classify_stage() L2358-2362、recognize_market_condition() 仍用 raw np.mean
- 共约 23 处 np.mean(closes[-N:]) 需替换

- [ ] **Step 1: 在 evaluate() 中提取 indicator_ma_df**

dim3 evaluate() 已接收 data_context，确认 indicator_ma_df 传递到 StageDetector。

- [ ] **Step 2: StageDetector 接入预计算 MA**

修改 StageDetector 相关方法，优先从 indicator_ma_df 读取 MA5/10/20/60/120/250，fallback 到 raw np.mean。

- [ ] **Step 3: recognize_market_condition 接入预计算 MA**

修改 recognize_market_condition() 中约 10 处 MA/BOLL/EMA 计算，优先使用预计算值。

- [ ] **Step 4: 运行测试验证**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统 && make check
```

---

### Task 4: dim5 daily_basic/margin data_context 接入

**Covers:** §七#12 — dim5 daily_basic/margin ecm 直调

**Files:**
- Modify: `backend/app/opportunity_atlas/dimensions/dim5_emotion_engine.py:681,749`

**Interfaces:**
- Consumes: `data_context['daily_basic_df']`, `data_context['margin_df']`
- Produces: dim5 主路径优先从 data_context 读取

**问题分析：**
- L681: `ecm.get_cached_daily_basic(ts_code)` — 已有 data_context-first（L679），但 fallback 仍直调
- L749: `ecm.get_cached_margin(ts_code)` — 无 data_context-first 路径
- dim1 已加载 daily_basic_df 和 margin_df

- [ ] **Step 1: L749 margin_df 接入 data_context**

在 dim5 evaluate() 中提取 margin_df，传递到 BociasiQuadrantAnalyzer，L749 改为 data_context-first + ecm fallback。

- [ ] **Step 2: 运行测试验证**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统 && make check
```

---

## P2: dim4 大规模改造（工作流C）

### Task 5: dim4 MainForceScorer data_context 接入

**Covers:** §七#3 — dim4 主路径 30+ 处直调 DM

**Files:**
- Modify: `backend/app/opportunity_atlas/dimensions/dim4_chip_fund_engine.py`

**Interfaces:**
- Consumes: `data_context['moneyflow_df']`, `data_context['daily_basic_df']`, `data_context['indicator_ma_df']`, `data_context['indicator_other_df']`, `data_context['chip_fund_ext']`
- Produces: MainForceScorer 内部方法主路径从 data_context 读取

**问题分析：**
- dim4 evaluate() L5859 已接收 data_context，已提取 chip_fund_ext/moneyflow_df/indicator_ma_df/indicator_other_df
- 但 MainForceScorer L2842-3186 的内部方法仍直接调用 dm.get_cached_moneyflow/stk_holder/margin/lhb
- MarginAnalyzer L3344-3579 仍直接调用 dm.get_cached_moneyflow/margin/daily_data
- 需要将 data_context 中的数据传递到这些内部方法

- [ ] **Step 1: MainForceScorer.__init__ 接收 data_context**

修改 MainForceScorer 构造函数，接收 data_context 参数并存储为实例属性。

- [ ] **Step 2: _calc_main_force() 从 data_context 读取 moneyflow**

L2842: `self._dm.get_cached_moneyflow(symbol)` → 优先从 `self._data_context.get('moneyflow_df')` 读取。

- [ ] **Step 3: _calc_fina_health() 从 data_context 读取**

L3042-3186: stk_holder/margin/lhb 优先从 data_context 读取。

- [ ] **Step 4: MarginAnalyzer 接入 data_context**

MarginAnalyzer L3344-3579: moneyflow/margin/daily_data 优先从 data_context 读取。

- [ ] **Step 5: 其余辅助方法接入**

L4091-4910: daily_basic/fina_indicator/income/balancesheet 优先从 data_context 读取。

- [ ] **Step 6: evaluate() 传递 data_context 到内部类**

在 dim4 evaluate() 中将 data_context 传递到 MainForceScorer 和 MarginAnalyzer。

- [ ] **Step 7: 运行测试验证**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统 && make check
```

---

## 验证方案

### L1: 每个 Task 完成后

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统 && make check
```

### L2: 全部完成后 — dim 引擎直调 DM/ECM 扫描

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统/backend && PYTHONPATH=. .venv/bin/python -c "
import pathlib
dim_dir = pathlib.Path('app/opportunity_atlas/dimensions')
violations = []
for f in sorted(dim_dir.glob('dim[2-7]*.py')):
    content = f.read_text()
    for i, line in enumerate(content.split('\n'), 1):
        stripped = line.strip()
        if stripped.startswith('#'):
            continue
        if 'ecm.get_cached_' in stripped or 'dm.get_cached_' in stripped or 'self.dm.get_cached_' in stripped or 'self._dm.get_cached_' in stripped:
            violations.append(f'{f.name}:{i}: {stripped[:100]}')
if violations:
    print(f'⚠️ 发现 {len(violations)} 处直调：')
    for v in violations:
        print(f'  {v}')
else:
    print('✅ dim2-dim7 无直调 DM/ECM')
"
```

**通过标准：** 直调数从 41 处降至 ≤10 处（剩余为明确的 fallback/except 分支）。

### L3: dim1 无 daemon 内存引用

```bash
grep -r "from data_daemon import" backend/app/opportunity_atlas/dimensions/
```
**通过标准：** 0 处匹配。
