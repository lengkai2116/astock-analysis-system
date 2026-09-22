# 472号｜PIERS-E ROCE=0.0 误触发根因核查 + 全链路禁假值回填修复

**定位**：dim6 PIERS-E「资本回报率偏低（ROCE 0.0%<15%）」对高回报股本（如茅台）误触发的数据`因`层根因核查 + 修复（2026-09-22）。445 冻结边界内（`果`判定逻辑不动，修数据事实）。

## 起因
真实数据运行（pre_feat_cache 探针）显示四只股票「资本回报率偏低（ROCE 0.0%<15%）」全触发，包括茅台（真实 ROCE≈33%）、万科等明显高质/低质本。判定为数据`因`层假值。

## 根因（已确定性坐实，多探针实证）

### 病根链
```
fina_indicator_cache 表（分库 financial_cache.db）无 roce 列（54列，有 roe/debt_to_assets）
  → data_daemon.py:3761  `_val_feat['roce'] = float(latest_fina.get('roce', 0) or 0)`  → 占位 0.0
  → valuation_ext.roce=0.0 写入 pre_feat_cache
  → status_engine._flatten_pre_feat 平铺 → flat tags['roce']=0.0
  → dim6 _assess_piers_leverage  `rce=0.0 < 15` → 误触发
```

### 决定性证据
- **probe_472c**（真实扁平 tags + Dim6RiskEngine）：四股 `flat tags.roce=0.0`，`_assess_piers_leverage` 全触发「ROCE 0.0%<15%」。
- **probe_472l**：fina_indicator_cache 分库 54 列无 `roce`；finance_report_cache 15 列有 `roce`。
- **probe_472e/f**：finance_report_cache 65960 行 `roce` **全 NULL**；balancesheet `current_liab` 全 NULL（标准 ROCE = EBIT/(总资产-流动负债) **分母不可得**）。
- **probe_472m**（Tushare 实测）：`get_fina_indicator_extended` 返回 keys **无 `roce` 字段**（仅 eps/roe/quick_ratio/ocfps/current_ratio/ebit）；但 **`ebit` 真实返回**（茅台 61192879672.31）。

### 同源 bug 波击
- `chip_pre_filter.py:938` / `dim4_chip_fund_engine.py:4827`：`roce=latest.get('roce',0) or 0` → `roce_pass=roce>=15` 恒 false（茅台也被判不达标）。
- `grossprofit_margin` 同为假键（表内真实列为 `gross_margin`，data_daemon:3762 `get('grossprofit_margin',0) or 0`）。
- `debt_to_assets` 是**真实列**（茅台 12.81），但 `chip_pre_filter`/`dim4` 读的是 `debt_ratio`（假列，None）。

## 修复方案（全链路禁假值 + EBIT/净资产回填）

### 方向（user 拍板）：全链路禁假值 + EBIT/净资产回填 + ROE 兑底

**数据`因`层修复**（核心）——让 `valuation_ext.roce` 产**真实 ROCE**：
- **主口径**：ROCE = finance_report_cache.ebit / (balancesheet.total_assets − balancesheet.total_liab)，即 **EBIT/净资产**（标准 ROCE 需 current_liab 不可得，退净资产品质口径）。
- **兑底**：无 ebit 时退 `fina.roe × 1.2`（dim4 `_check_roce` 既有经验系数，ROCE 通常略高于 ROE 加杠杆）。
- **缺 data_fina 全缺**：不写 0 假值 → `valuation_ext` 不产 `roce` 键。

daemon `_val_feat['roce']` 段重写：`ebit/净资产 → roe×1.2 → None(不产)`。`grossprofit_margin` 假键删除或映射真实 `gross_margin`。

### 消费侧防空（None/0 视为「无数据不触发」）
- **dim6 `_assess_piers_leverage`**：`roce` 为 None/0（疑似占位）时不触发 ROCE 条件（debt_to_assets 仍走真实列）。
- **chip_pre_filter / dim4 `roce_pass`**：`roce None/0 → roce_pass=False` 但不再恒误杀；改为「无数据不硬判 fail」。

### 涉及文件
- `backend/data_daemon.py`（L3760-3763）：roce 回填 + grossprofit_margin 修正。
- `backend/app/opportunity_atlas/dimensions/dim6_risk_engine.py` `_assess_piers_leverage`：roce 防空。
- `backend/app/engine/framework/chip_pre_filter.py`：roce_pass 防空。
- `backend/app/opportunity_atlas/dimensions/dim4_chip_fund_engine.py`：roce_pass 防空 + debt_ratio→debt_to_assets。

## 验证
- **决定性探针**：修复后四股 ROCE 值（茅台 33.46% 不触发；万科/000078/000001 触发）。
- 单测回归（dim6 test_459/448/452，dim4 test_464，chip_pre）。

## 待办追踪
- 标准 ROCE（EBIT/(总资产-流动负债)）需补采 `current_liab` 列后才可用——本号用 EBIT/净资产 近似口径，记录在案。
- 其余空壳财务列（roic/roa/ebit/gross_margin）在 fina_indicator_cache 全空——需 Tushare FINA_FIELDS 扩采方可真实回填，属于数据采集后续号。
