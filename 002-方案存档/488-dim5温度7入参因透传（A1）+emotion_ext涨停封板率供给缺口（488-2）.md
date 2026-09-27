---
title: dim5 情绪温度 7 入参"因"透传（A1）+ 复跑暴露的 emotion_ext 涨停/封板率供给缺口（488-2）
type: 实施号（A1 已实施；488-2 缺口已实证定位、待拍板）
date: 2026-09-27
version: v1.0
status: ✅ A1 已实施并验证；🔄 488-2（数据供给缺口）登记待拍板
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

### 修复方向（待拍板，未实施）
1. **采集端**：补 `sentiment_pool_cache`（涨停池/炸板池：`limit_type` / `first_seal_time` / `consecutive_days`）的采集与日终同步（akshare/Tushare 涨停池）——消费方 `MarketSentimentService.get_sentiment_phase()` 已就绪，仅缺数据；
2. **回补**：近 N 交易日回补 + `pre_feat` 重算（8 股定向 + 全市场随 daemon 日终）；
3. **验证**：温度因句出现真实「涨停N家/封板率X%」；`data_available=True`；dim8 大盘状态句恢复。

> **注**：488-2 涉及采集端（daemon 采集任务 + 数据源），工作量与风险高于 A1，建议**另开数据采集号**或经用户拍板后在本号追加子项。

## 三、产物清单
- 代码：`dim5_emotion_engine.py`、`dim8_summary_engine.py`
- 测试：`tests/test_488_dim5_temperature_basis.py`（新增 8）、`tests/test_447_dim5_emotion_fix.py`（断言放宽 1 处）
- 探针：`backend/scripts/_488_emotion_ext_probe.py`、`backend/scripts/_488_sentiment_pool_probe.py`
- 登记：本档；`464-dim8-dim5现状描述输出定稿` §七观察项③、`479` §七遗留③ 回填关闭
