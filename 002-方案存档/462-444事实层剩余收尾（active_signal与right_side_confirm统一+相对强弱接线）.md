---
title: 444 事实层剩余收尾（active_signal/right_side_confirm 值域类型统一 + 相对强弱接线 + 估值组落库）
type: 实施号（444 第②③步收尾；四子项独立实施验证记录于同文档）
date: 2026-09-18
version: v1.0
status: ✅ 已实施+验证（462-1~4 全部落地；sig_full_test OK 40/0/0；全市场估值组落库实证）
related:
  - 444-SIG股票现状描述的事实层仲裁与叙事框架方案——本号是其第②步收尾（§4.4 剩余 3 项挂账）
  - 460-dim1取数与各dim原料供应核查报告（三步盘点）——461 交付后剩余项归本号
  - 461-dim1取数一致性合并实施号（多子项统一）——同模式：一号多子项、独立实施验证记录
  - 445-dim2-dim7引擎正确性知识库核查——判定逻辑冻结，本号只修"事实/取数/口径"不碰判定
  - 438-第一层环境定位数据缺口修复方案——relative_strength_cache 持久表（数据已闭环）
---

# 462 — 444 事实层剩余收尾

> **定位**：444 第②步 SSOT 逐项拍板剩余 3 项挂账的落地（461 交付后遗留）：①derived.right_side_confirm 值域错位（英文两值代理 vs 消费方中文四档）；②derived.active_signal 类型错位（字符串枚举 vs 消费方期望 dict{date,price}）+ pattern_signal SSOT 确认；③面7 相对强弱接线（relative_strength_cache 数据就绪，消费块缺失）。
>
> **边界（445 冻结）**：只修"事实/口径/值域"统一（统一三原则：数据同源/依据标准统一/事实输出统一），**不改变任何判定条件**。right_side_confirm 判定条件集保持 `_check_right_side_confirm`（treemap 管道已用）不变，本号仅让 SIG/RAW-2 路径与 treemap 同源同判定。

---

## 〇、拍板（2026-09-18 用户确认）

1. **right_side_confirm 统一到四档**：RAW-2 derived 改接 `_check_right_side_confirm`（否决/强确认/基础确认/未确认，中文，与 treemap 管道同源）→ SIG→JUD 全链路值域对齐（arbiter P0 硬否决/门控/conflict_matrix/signal_analyzer/dim6 死代码转活）。接受行为变化：部分股票（如 vpf=diverging 量价背离）从 wait 变 avoid。
2. **active_signal 补产 dict 真实化**：RAW-2 补产 `{type,date,price}` JSON（从缠论买卖点详情 + 日线日期组装），`_signal_lifecycle` 生命周期（初期/中期/已延伸/回撤，334 §5.3）真实化。
3. **相对强弱并入 emotion/summary 段文本**：dim8 在 emotion 或 summary 段现状句补一句环境定位（消费 `get_relative_strength` 双基准 ex_ret），不改前端契约键。
4. **开 462 号统一记录**（本文档）。

---

## 一、子项清单与推进总览

| 子项 | 内容 | 状态 |
|---|---|---|
| 462-1 | **right_side_confirm 值域统一**（derived 接 _check_right_side_confirm 四档中文；confirm_evidence 补产） | ✅ 已实施+验证 |
| 462-2 | **active_signal 补产 dict**（{type,date,price} 生命周期真实化）+ pattern_signal SSOT 确认 | ✅ 已实施+验证 |
| 462-3 | **相对强弱接线**（dim8 emotion/summary 段文本补环境定位句） | ✅ 已实施+验证 |
| 462-4 | **RAW-2 估值组 app_context 修复**（子线程无 context 恒空，估值块包 _raw_app.app_context()） | ✅ 已实施+验证 |

---

## 工作进度记录（2026-09-18）

- [x] 探明三项挂账全链 + 真实数据实证（5 只：right_side_confirm 恒 unconfirmed、active_signal 纯枚举、relative_strength 数据就绪 asof 09-16）
- [x] 用户拍板四项（rsc 四档 / active_signal dict / 相对强弱入 emotion·summary / 开 462 号）
- [x] **462-1 right_side_confirm 值域统一**（derived 接 _check_right_side_confirm 中文四档，消费方全对齐；dim6:403 死代码转活）——改动 data_daemon 1 处 + 新测试 8 例；实测 600519 rsc=否决、sig_full_test 600519 signal 黄→红
- [x] **462-2 active_signal 补产 dict**（新纯函数 _build_active_signal 产 {type,date,price}，生命周期真实化；pattern_signal SSOT=kline_pattern 确认）——改动 data_daemon 2 处 + 新测试 8 例
- [x] **462-3 相对强弱接线**（dim8 _relative_strength_sentence 并入 summary 前置；build_seven_dim_report/入口增 ts_code）——改动 dim8/status_engine/data_daemon/回填脚本 4 文件 + 新测试 10 例
- [x] **462-4 RAW-2 估值组恒空修复**（根因=子线程无 app_context；估值块包 _raw_app.app_context()）——改动 data_daemon 1 处 + 新测试 2 例；5 只样本估值组真实落库
- [x] 汇总验证：新测试 27 例全过 + 相关回归 149 passed + sig_full_test **OK 40 / WARN 0 / FAIL 0**（停 daemon）+ 321 系 37 passed
- [x] **全市场 RAW-2 重算（09-15 基准日 5548 只）**：估值组非空率 **100%**（fina_health/roce_pass 全量落库），461-2 SSOT 真正生效实证
- [x] **附加收尾（数据采集缺口）**：09-16/17 曾仅 92 只/日——根因=节假日表误标（`trading_hours.py` `_DEFAULT_HOLIDAYS` 含错误 2026-09-15/16/17）→ ①直接补采闭环（daily/moneyflow/stk_limit/lhb 全量）②按官方通知审计修正 2026 节假日表 + 新增 `_WORKDAY_WEEKENDS` 调休上班周末；新测试 test_trading_calendar_2026.py 11 例全过；daemon 重启应用

---

## 462-1 — right_side_confirm 值域统一（derived 接四档）

### 实证
- 5 只样本 pre_feat 原值**全为 `unconfirmed`**（英文两值代理），即便 600519/300750 vpf=diverging（`_check_right_side_confirm` 会判**否决**）、000002 second_buy（会判**强确认**）——代理值域吞掉真实判定。
- SIG 消费方（arbiter P0-P6 / factor_arbiter 硬否决+门控 / conflict_matrix C4/C7/C8 / signal_analyzer 右侧否决 / cross_validate / dim6:403）全部判**中文四档**（否决/强确认/基础确认/未确认）→ 与 derived 英文两值错位 → **全部恒不触发**；dim6:403 为死代码（404号 DATA-03 已知限制）。

### 处置（用户拍板：统一到四档）
- data_daemon `_raw2_one` derived 组：`right_side_confirm` 改调 **`_check_right_side_confirm('', tags, df)`**（treemap 管道同源判定器，条件集不变），产出中文四档。
- 构造判定入参 tags（buy_sell_point / volume_price_fit / pattern_signal 三键，均从本组已算值取）；异常兜底 'unconfirmed' 并 debug 日志。
- **不产 confirm_evidence 死键**（app 层无消费者，461-13 纪律）。
- 值域与全部消费方对齐：dim6:403 死代码转活；arbiter/factor_arbiter/conflict_matrix/signal_analyzer/cross_validate 的右侧否决/门控/冲突开始真实触发。

### 验证
- 新测试 `tests/test_462_dim_derived_unify.py` TestRightSideConfirmDomain 8 例（vpf=diverging→否决、first_sell→否决、预跌形态→否决、second_sell→未确认降级、无基础→未确认、second_buy 放量站上MA20→强确认、无买点→基础确认、derived 生产接线源码断言）
- 真实数据重算 5 只：600519 rsc=**否决**（first_sell）、其余=未确认
- sig_full_test 全链路 **OK 40 / WARN 0 / FAIL 0**；600519 signal 由黄变红（否决真实触发，行为变化符合拍板预期）

---

## 462-2 — active_signal 补产 dict + pattern_signal SSOT

### 实证
- 5 只样本 active_signal 原值 = 纯枚举字符串（second_buy/first_buy_p/None），**无日期/价格**。
- `status_engine._signal_lifecycle`（334号 §5.3）期望 `{type,date,price}` → json/ast 解析失败 → 信号生命周期**恒 None**（静默降级）。
- pattern_signal = kline_pattern 拷贝（EnhancedPatternDetector → volume_price.kline_pattern → derived.pattern_signal），值一致、SSOT 明确，status_engine:863/strategy_analyze:681 消费，**无行为问题**。

### 处置（用户拍板：补产 dict 真实化）
- data_daemon 新增纯函数 **`_build_active_signal(cl_result, buy_sell_point)`**（461-10 抽纯函数先例）：从缠论买卖点详情匹配 `BuySellPoint.position`（已含 `{idx,price,date}`）组装 JSON `{'type','date','price'}`；无匹配/无价格回退枚举字符串（降级兼容）；无买点 → None。
- derived 组 `active_signal` 改调该函数；`_signal_lifecycle` 已有 dict 解析逻辑，直接生效。
- pattern_signal：确认 SSOT=EnhancedPatternDetector（data_daemon:3861）→ volume_price.kline_pattern → derived 扁平拷贝，无代码改动（仅文档确认）。

### 验证
- 新测试 TestActiveSignalDict 8 例（纯函数 6 例：none→None/匹配→JSON/买优先/卖点/无匹配回退/无价格回退；`_signal_lifecycle` 集成 1 例：初期/已延伸/回撤三阶段；derived 接线源码断言）
- 真实数据重算 5 只：active_signal 全部变为 dict JSON（如 000001 `{"type": "second_buy", "date": "2021-09-01", "price": 17.01}`、600519 first_sell 无 date 降级保留 price）
- 生命周期在 SIG 输出侧真实化（有 date+price 时算 初期/已延伸/回撤；date 缺失降级）

---

## 462-3 — 相对强弱并入 summary 段（面7 接线）

### 实证
- `relative_strength_cache` 数据完整（asof 2026-09-16，双基准 ex_ret_20d/60d 非空，5544 股 × 2 基准），`get_relative_strength()` **零业务调用**。
- seven_dim（dim8）**无环境定位区块**——消费块原不存在（438 明示依赖 437 第一层框架）；437-A D3「第一层环境定位并入 summary 前置」待落地。

### 处置（用户拍板：并入 emotion/summary 段文本）
- dim8 新增模块级纯函数 **`_relative_strength_sentence(ts_code)`**：取最新 asof 双基准 `ex_ret_20d/60d` 组"相对强弱：近20日跑赢沪深300 +12.5%、跑赢上证 +9.4%；近60日…"；无数据/异常返回 ''（437 缺则降级）。
- `build_seven_dim_report` 增 `ts_code` 参数（向后兼容默认 None），summary 段**前置**相对强弱句（对齐 437-A D3「并入 summary 前置」）；不传 ts_code → 跳过，前端契约键不变。
- 链路：`build_seven_dim_from_dim_results(..., ts_code=)` → dim8；data_daemon SIG 预计算调用点补传 ts_code；`_436_recompute_backfill` 同步补传（历史回填有数据则显、无则跳过）。

### 验证
- 新测试 TestRelativeStrengthSentence 6 例 + TestSummaryInjection 4 例（句子格式/最新 asof/空降级/异常降级/无 ts_code 跳过/入口透传/7 键契约不变）
- 437-A D3「并入 summary 前置」的落地形态（不改前端契约）

---

## 汇总验证（2026-09-18）

```
py_compile：data_daemon / status_engine / dim8_summary_engine / _436_recompute_backfill → OK
tests/test_462_dim_derived_unify.py（新，27 例）→ 27 passed
相关回归：436 契约 + 436_b3 + 461 系（7/6/8）+ 321_s2/arbiter/conflict + 452/453/459 → 149 passed
真实数据：5 只样本 RAW-2 重算（复用生产路径 _precompute_raw_features）→ derived 新值 + 估值组真实值落库
  （600519 rsc=否决、000001 act=dict JSON、600519 fina_health=pass/roce_pass=True、000001 pe5y=87.2）
sig_full_test 全链路（停 daemon）→ OK 40 / WARN 0 / FAIL 0
停 daemon 下 test_321 系（此前批跑 1 失败）→ 37 passed（确认为 daemon 持锁环境问题，非本号回归）
```

---

## 462-4 — RAW-2 估值组恒空修复（子线程 app_context）

### 根因（用户要求核实，实证链）
1. **症状**：pre_feat_cache valuation 组自 09-14 起恒空（600036.SH 历史：09-08~09-11 有值 `fina_health='pass'` 等 → 09-14 起空），抽查 600036/000858/601318 均空；461-12 补日志暴露 `RAW估值特征失败 [code]: Working outside of application context`。
2. **直接根因**：`_raw2_one` 经 `_run_with_timeout(lambda: _raw2_one(code))` 在**独立子线程**执行（data_daemon:3827）；Flask app_context 是**线程局部**的——`_precompute_raw_features` 池线程的 `with _flask_app.app_context():`（:3123）**不覆盖** `_raw2_one` 子线程。估值块（step 1）直接调 `ve.compute_tags(code)` → `DataManager.get_stock_industry`（valuation_estimator:728）→ SQLAlchemy `db.session` 依赖 app_context → 抛错 → except 吞（461-12 补日志）→ 估值组空。**对照 sector 块（step 3，:3336）显式包 `_raw_app.app_context():`（442 缺陷④修复），估值块漏包**。
3. **回归起点**：893bbe6（09-17「442-451 累积」）改 per-stock 调用为 `lambda: _raw2_one(code)`（修 428 带参 bug）后 `_raw2_one` 真正在子线程跑起来，估值块暴露无 context；09-11 前 pre_feat 由旧执行路径（`_raw2_one` 在池线程内直接跑、继承 app_context）写入。

### 影响（修复前）
- dim7 走运行时兜底 `_fina_health`/data_context，**不受影响**（sig_full_test valuation 维正常）；
- 但 461-2 白名单补产的 `roce_pass`/`value_trap` **落库意义悬空**——dim7 读 tags 的 SSOT 路径实际走不到（恒走兜底）。

### 处置（用户拍板：现在修复，并入 462-4）
- data_daemon `_raw2_one` 估值块：`ve.compute_tags(code)` 包 **`with _raw_app.app_context():`**（同 sector 块 :3336 先例；`_raw_app` 在 :3208 创建、闭包可见）。

### 验证
- 源码断言测试 2 例（TestValuationBlockAppContext：估值块包裹 + sector 块对照仍在）→ 27 passed
- 5 只样本 RAW-2 重算：**估值组全部真实落库**——600519 fina_health=pass/roce_pass=True、000001 fina_health=suspicious/pe5y=87.2、000002 fina_health=fail、300750 pe5y=0.0；"RAW估值特征失败"日志消失
- **全市场 RAW-2 重算（target_date=2026-09-15 最后全量日，5548 只，约 15 分钟，失败 0）**：pre_feat 09-15 **5544 行**，valuation 组非空率 **100%**（5544/5544）、fina_health 分布 suspicious=3925/fail=551/pass=1068、roce_pass 非空 **100%**、pe_percentile_5y 非空 78.7%（其余为亏损/新股合理缺失，437-A 合理缺失 PE 21% 一致）
- sig_full_test 全链路 **OK 40 / WARN 0 / FAIL 0**

### 说明
- 本次只修**数据生产链路**（估值组落库），未触碰任何判定/口径；461-2 SSOT（dim7 读 tags.fina_health）从此真正有值可读。
- 全量重算以 09-15 为目标日（09-16/17 daily_cache 采集仅 92 只非全量，见下）；daemon 下次全量采集后新交易日自动带估值组。
- **附发现（数据采集缺口，已补采 + 根因修复，2026-09-18）**：daily_cache 09-16/09-17 曾各仅 92 只（09-15 及以前 5548+ 全量）。**根因 = `app/utils/trading_hours.py` `_DEFAULT_HOLIDAYS` 硬编码 `2026-09-15/16/17` 为节假日（错误——2026 中秋节实为 09-25；该列表自 213 号混入错年份日期）→ `_is_trading_day` 返回 False → daemon 完整性检查回退补采循环跳过这两天**。①已直接补采闭环（绕过节假日门禁）：09-16 daily 5549/daily_basic 5550/moneyflow 5550/stk_limit 5643/lhb 73；09-17 daily 5552/5553/5553/5644/lhb 58，全部全量。②**节假日表已按《国务院办公厅关于2026年部分节假日安排的通知》（gov.cn content_7047090）审计修正**：移除错误条目（2025 春节 01-28~02-03、错位端午 06-12~14、错位中秋 09-15~17、国庆多余 10-08），补正确条目（元旦 1/2、春节 2/15-2/23 共 9 天、端午 6/19-21、中秋 9/25-27、国庆 10/1-10/7），并新增 `_WORKDAY_WEEKENDS`（调休上班周末 1/4、2/14、2/28、5/9、9/20、10/10 判为交易日）。验证：新测试 `tests/test_trading_calendar_2026.py` 11 例 + t25 5 例全过；daemon 重启应用后完整性检查正常。**影响**：后续国庆 10/1-10/7 休市、10/8 及调休周末开市的采集门禁将正确执行。

