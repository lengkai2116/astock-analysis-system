---
title: dim5 情绪温度 7 入参"因"透传（A1）+ emotion_ext 涨停/封板率供给缺口修复（488-2）
type: 实施号（A1 + 488-2 均已实施并验证）
date: 2026-09-27
version: v1.1（A1 实施 + 488-2 由缺口登记转为本号内实施）
status: ✅ 全部实施并验证（A1 透传；488-2 采集修复+回补+重算+dim8 接线）
related:
  - 464-dim8-dim5现状描述输出定稿（情绪环境）（§七观察项③ 拍板「以 7 入参明细作因透传」，§三-7 话术形态）
  - 479-dim8现状描述改造与全链路收口总方案（§七遗留③ 登记「7 入参明细未透传」）
  - 447-dim5情绪引擎知识库修正（T1a 温度 7 入参全传 + T5 温度 SSOT）
  - 485-SIG全环节运行核查（P1-P2 清单；本次复跑暴露法承接其探针）
  - 445-Freeze-vs-Fact-Layer（冻结边界：只改「因」侧透传/表述，不碰「果」判定）
---

# 488号｜dim5 温度 7 入参"因"透传（A1）+ emotion_ext 供给缺口（488-2）

> **定位**：落地 dim5 定稿 §七观察项③ 拍板项「以 7 入参明细作因透传」，闭合 479 §七遗留③。实施后 8 股复跑**暴露一处真实数据供给缺口**（488-2），本号一并实证定位。

## 一、A1 实施（✅ 2026-09-27）

### 改动（2 文件 + 1 测试）
| 文件 | 改动 |
|---|---|
| `app/opportunity_atlas/dimensions/dim5_emotion_engine.py` | ① 导入 `PHASE_BASE_TEMP`（温度 SSOT，之前只导入 `calc_emotion_temperature`）；② 新增 `_fmt_temperature_basis()`（7 入参因句，缺项标「无数据」）；③ `evaluate` 新增 `_has_limit_up` 标志（区分「涨停 0 家」与「无数据」）；④ `status_description` 新增键 **`temperature_basis`** |
| `app/opportunity_atlas/dimensions/dim8_summary_engine.py` | ① `_DIM8_FIELD_CN` 补 `temperature_basis`: 温度入参；② `_compose_dim_text` 对 `emotion/temperature` 做**「果（因）」合并**——`情绪温度：中性53.8/100（阶段退潮(基温25)+…）`（对齐定稿 §三-7 话术形态）；basis 缺则不产括号 |
| `tests/test_488_dim5_temperature_basis.py` | 新增 8 用例（纯函数 / evaluate 集成 / 缺数据标注 / 零涨停 vs 无数据 / judgment 键集不变 / dim8 合并 / 无 basis 不产括号） |
| `tests/test_447_dim5_emotion_fix.py` | `test_dim5_imports_not_embeds` 断言由「字面整行」改「模块 + 符号」级（SSOT 导入改为多行括号形式；原意「import SSOT、不内嵌副本」不变） |

### 话术形态（8 股真实链路实测，600519.SH）
```
情绪温度：中性53.8/100（阶段退潮(基温25)+涨停无数据+封板率无数据+板块排名无数据
        +量价中性+融资5日-12.5%+广度39%(20日均线占比近似)，情绪周期修正(快0.68×0.6+慢0.72×0.4)）
```
（`MA20` 经 dim8 中文网关转「20日均线」，符合 480 网关口径。）

### 验证
- 单测：`test_488_dim5_temperature_basis.py` **8 passed**；回归 dim5/dim8 系（447/470/471/472/419/479_1/479_4/479_5/480/437a/420/461/323）合计 **133 passed**。
- 注意：`test_447` 的 I001（import 排序）与 dim5 `I001` 为**改动前既有**（对 HEAD 版本 ruff 复核确认），非本次引入；新增/改动文件除既有项外 ruff 干净；py_compile OK。
- 端到端：探针 `backend/scripts/_485_sig_full_run_probe.py` 8 股复跑，**8 股 × 6 段 text 全 OK**，dim5 段温度句均带因（见上）。

### 445 边界合规
`temperature_basis` 为**纯「因」透传**（引擎已算的入参值），不参与 `calc_emotion_temperature`；`judgment`（灯色/方向/`continuous_value`）键集与值域**零变化**（单测 `test_judgment_keys_unchanged` 固化）。

## 二、488-2｜复跑暴露的缺口：情绪温度 7 入参中「涨停家数 / 封板率」从未生效（🔄 待拍板）

### 现象
8 股因句**全部**为「涨停无数据+封板率无数据」（探针实测 16 处 = 8 股 × 2 段引用）。即温度 **7 入参只有 5 项生效**，合计 **25% 权重**（涨停 15% + 封板率 10%）长期取默认值（0 家 / 50%）。

### 证据链（逐层实证，勿重做）
| # | 环节 | 实证 |
|---|---|---|
| 1 | pre_feat `emotion_ext` 内容 | 探针 `_488_emotion_ext_probe.py`：`{'emotion_temperature': 43.8, 'market_emotion': 'ebb', 'sector_emotion': 'hot', 'stock_emotion': 'neutral'}` —— **无 `limit_up_count`/`sealing_rate`** |
| 2 | 生产侧写入条件 | `data_daemon.py:3697-3716`：`_sent` 仅在 `sentiment.get('data_available')` 为真时补写 `limit_up_count`/`sealing_rate`；`data_daemon.py:4271-4276` 再由 `_sent` 透传进 `emotion_ext`——**条件永不成立 ⇒ 该透传为死代码** |
| 3 | 上游数据可用性 | `_488_sentiment_pool_probe.py`：`sentiment_pool_cache` **20260922/23/24/27 全部 0 行** → `ms.get_sentiment_phase()` 恒 `data_available=False`、`metrics={}` |
| 4 | 连带影响 | ① dim5 温度 2 项入参恒默认；② 市场阶段（六段论）实际走 daemon 兜底 `_sentiment_phase_global`（`:3636-3642`），非 `sentiment_pool` 源；③ dim8「大盘状态：…涨停N家/封板率X%」句（`dim8:1163-1168`）**从不产出** |

### 性质与边界
属**数据采集缺口**（「因」侧，445 允许修复）；与 488 A1 的透传改动相互独立——A1 让缺口**可见**（此前静默取默认）。

### 修复（✅ 2026-09-27 本号内实施，5 处）
| # | 位置 | 改动 |
|---|---|---|
| 1 | `akshare_collector._collect_sentiment_pool` | 改官方**三接口** `date=`：`stock_zt_pool_em`（涨停）/ `stock_zt_pool_dtgc_em`（跌停）/ `stock_zt_pool_zbgc_em`（炸板）；新增 `_pool_ts_code`（6→SH / 0,3→SZ / 4,8→BJ / 9→SH）、`_pool_int`；连续板数字段分流（连板数 / 连续跌停 / 炸板池缺列默认 1）；失败改 **warning** 级（不再静默）；新增 `backfill_sentiment_pool(dates)` 覆盖式回补（`INSERT OR REPLACE` 幂等） |
| 2 | `market_sentiment_service` 封板率**口径** | 改「涨停 /(涨停+炸板)」——AKShare 涨停池本身即已封板股，原按池内 `first_seal_time` 比 **恒 100%、无区分度**；炸板池缺数据回退原口径 |
| 3 | `data_daemon` RAW-2 情绪块 | 按本行特征 `trade_date` 取市情绪池（原 `ms.get_sentiment_phase()` 缺省 today → 非交易日/回补重算取今日池必空） |
| 4 | `data_daemon.run_integrity_check` | 增「覆盖式补采近 N 交易日」（交易日历 ∩ 数据面；日历不可用回退今日单日） |
| 5 | `dim8._market_state_sentence` | 涨停家数/封板率**双源**：`market_stats`（封板率分数 0-1，437-A 契约）优先 → `emotion_ext`（百分数 0-100）兜底 |

### 回补与重算（2026-09-27，daemon 停态）
- **回补 3 交易日**：`2026-09-22/23/24` → 写入 **249 条**；涨停 **63/51/52** 家、封板率 **77.8/67.1/83.9%**、`data_available=True`（phase=ferment）。
- **pre_feat 定向重算 8 股**（`target_date=2026-09-24`，脚本 `_488_backfill_and_recompute.py`）：`emotion_ext` 落 `limit_up_count=52` / `sealing_rate=83.9`；**温度 43.8 → 63.7**（25% 权重首次真实生效）。

### 验证
- **探针复跑 8 股**：段 text 全 OK（无 EMPTY/FATAL）；温度句 `偏热61.7/100（阶段发酵(基温60)+涨停52家+封板率84%+板块排名无数据+量价中性+融资5日-12.5%+广度39%(20日均线占比近似)，情绪周期修正(快0.68×0.6+慢0.72×0.4)）`；大盘状态句 `全市场20日均线强势占比39%（偏弱）；涨停52家；封板率84%`。
- **单测**：`tests/test_488_sentiment_pool_collector.py` **9 passed**（ts_code 归一 / 整数化 / 三接口映射与调用 / 缺接口降级 / 多日回补 / 封板率口径与回退 / dim8 句含涨停封板率 / 缺数据降级）。
- **回归**：dim5/dim8 系 **167 passed**。
- **ruff/py_compile**：改动文件无**新增**问题（`dim5`/`test_447` 既有 I001、`akshare_collector:270` 既有 F841 均经对 HEAD 版本复核确认为改动前存在）。

### 遗留（登记，非本号缺口）
- `market_stats` 未落 `limit_up_count`/`sealing_rate`（需 `market_stats_cache` DDL + 持久化 + 列迁移）→ dim8 走 `emotion_ext` 兜底；若未来要求 market_stats 直读，另立小号。
- **全市场** `emotion_ext` 的该两键将随 daemon 下次日终 RAW-2 自然刷新（本次仅 8 股定向重算）；建议交易日重启 daemon 后回收验。

## 三、产物清单
- 代码：`dim5_emotion_engine.py`、`dim8_summary_engine.py`、`app/data/akshare_collector.py`、`app/services/market_sentiment_service.py`、`data_daemon.py`
- 测试：`tests/test_488_dim5_temperature_basis.py`（新增 8）、`tests/test_488_sentiment_pool_collector.py`（新增 9）、`tests/test_447_dim5_emotion_fix.py`（断言放宽 1 处）
- 脚本/探针：`backend/scripts/_488_emotion_ext_probe.py`、`_488_sentiment_pool_probe.py`、`_488_backfill_and_recompute.py`
- 登记：本档；`464-dim8-dim5现状描述输出定稿` §七观察项③、`479` §七遗留③ 回填关闭
