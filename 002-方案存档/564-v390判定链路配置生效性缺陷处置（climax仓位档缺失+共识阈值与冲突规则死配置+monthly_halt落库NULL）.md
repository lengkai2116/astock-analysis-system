---
title: v390 判定链路配置生效性缺陷处置（climax 仓位档缺失 + 共识阈值/冲突规则死配置 + monthly_halt 落库 NULL）
type: 核查与修复方案
date: 2026-11-12
status: A1/B2/C1 已实施并推送（2026-11-12，c910b03；测试 22 passed，11-11 回填完成，daemon 已重启；待下次日终 live 验收）
---

# 564 - v390 判定链路配置生效性缺陷处置

## 一、问题来源

2026-11-12 对 **2026-11-11 日终**的只读核查（沟通记录 `2026-11-12.md` §001）确认 SIG/JUD 全链路 19 步 done、无重试，但配置生效性存在 3 处缺陷。用户拍板「A、B、C 都开号」，本档为 A+B+C 的合并处置号。

三处缺陷：

| 编号 | 缺陷 | 严重度 | 是否行为变更 |
|---|---|---|---|
| A | `emotion_position_cap` 缺 `climax` 键，高潮期静默回落 `normal` 档 | 中（配置失真） | 取决于档位取值 |
| B | `consensus.enter_threshold/bearish_strong` 与 `conflict_rules` 在 v390 下为零消费死配置 | 中（调参误导） | B1 路线会变更 |
| C | `monthly_halt` 的 `false` 落库为 `NULL`，无法区分「不熔断」与「未评估」 | 低（可观测性） | 不改变判定 |

---

## 二、现状实证（逐项：代码位置 + 实测证据）

### A. `emotion_position_cap` 缺 `climax` 键

**代码位置**

- `backend/config/status_engine.yaml` → `l0.emotion_position_cap` 现有键：`ice 0.10 / ebb 0.30 / normal 0.60 / recovery 0.60 / positive 0.80`，**无 `climax`**。
- `backend/app/opportunity_atlas/status_engine.py:82-93` → `_SENTIMENT_TO_STATE_PHASE` 显式把 `'高潮': 'climax'`。
- `backend/app/opportunity_atlas/status_engine.py:936` → `_caps.get(_phase, _caps.get('normal', 0.6))`：键缺失即 **静默回落 0.60**。
- `backend/app/opportunity_atlas/consensus_engine.py:92-99` → `STATE_WEIGHTS` **有** `climax` 档（权重 0.15/0.15/0.20/0.10/0.20/0.20），说明 `climax` 是引擎一等阶段，唯独仓位上限表未登记。

**实测证据（跨日，`status_snapshot_history.l0`）**

| 数据日 | dim 情绪态 | 归一阶段 | `emotion_position_cap` |
|---|---|---|---|
| 2026-11-03 ~ 11-09 | 发酵 | positive | **0.8（5568~5572 只全部）** |
| 2026-11-10 | 高潮 | climax | **0.6（5571 只全部，回落 normal）** |
| 2026-11-11 | 高潮 | climax | **0.6（5572 只全部，回落 normal）** |

**结论**：配置读取链路真实生效（`positive` 档可被 0.8 验证），但 `climax` 走的是兜底而非配置。是否「应压到 0.6」目前无显式登记。

**影响面**：`l0.emotion_position_cap` 由 `advice_engine.py:93` 消费为总仓位上限。11-11 实际 `max_position_ratio` 最大 0.2（2% 风险预算先约束），故当前 0.6 上限**并未实际绑定**；A 的修复主要是「配置语义正确」而非当日数值变化。

---

### B. v390 下共识阈值与冲突规则为零消费死配置

**代码位置**

- `backend/app/opportunity_atlas/arbiter.py:67-79` → `_load_thresholds()` 读 `consensus.bearish_strong / enter_threshold`。
- 唯一调用点 `arbiter.py:213`，仅在 `arbitrate()`（legacy 规则优先级表）内使用（`arbiter.py:275/294`）。
- `backend/app/opportunity_atlas/status_engine.py:312-316` → `jud_engine_version == 'v390'` 时走 `_aggregate_v390()`，**不调用** `arbiter.arbitrate()`。
- `backend/app/opportunity_atlas/factor_arbiter.py:44-49` → v390 的状态映射阈值 `80/65/45/30` 为**模块常量**，不读 yaml。
- `arbiter.py:90-116` + `:224` → `conflict_rules.rules` 仅 legacy 规则名集合；v390 由 `conflict_matrix.detect` 产出 `C1~C14` 码。

**实测证据（11-11，5572 行）**

- `conflict_evidence` 规则前缀分布：`C12 2380 / C2b 1420 / C7 738 / C10 209 / C13 131 / C4 98 / C6 92 / C1 70 / C14 37 / C8 21 / C5 16 / C11 12 / C9 1`。
- yaml 六条规则名 `trend_vs_multi / high_profit_no_flow / distributing_vs_confirm / risk_high_vs_confirm / high_profit_no_presence / deep_valuation_confirm` **命中 0**。
- 日志中 `共识阈值读取失败` / `冲突规则配置读取失败` **0 次**（说明不是加载失败，而是根本没走 legacy 路径）。

**结论**：`status_engine.yaml` 中这两段在 v390 下是**死配置**。若按 yaml 调参，不会改变任何判定，属高误导风险。

---

### C. `monthly_halt` 的 false 落库为 NULL

**代码位置**

- `backend/app/opportunity_atlas/status_engine.py:1322` → `advice_params['monthly_halt'] = _mrs.get('monthly_halt', False)`。
- `status_engine.py:1338` → 顶层 `'monthly_halt': _mrs.get('monthly_halt', False)`。
- `backend/data_daemon.py:7640` → `1 if row.get('monthly_halt') else None`：**False 与缺失统一写 NULL**。
- 列定义存在：`data_daemon.py:7282-7283`（`INTEGER DEFAULT NULL`）。

**实测证据（11-11，5572 行）**

- `status_snapshot_history.monthly_halt`：`NULL = 5572`。
- 同源 `advice_params.monthly_halt`：`false = 5572`。

**结论**：标记值本身存在且正确（账户无交易 → 不熔断），但顶层便捷列无法区分「false」与「未评估」。属可观测性缺陷，不影响判定。

---

## 三、处置方案与选项

### Q1｜A：climax 仓位档取值

| 选项 | 取值 | 行为变化 | 说明 |
|---|---|---|---|
| **A1（推荐）** | `climax: 0.60` | 零（与现兜底一致） | 显式登记，消除隐式回落；11-11 数值不变 |
| A2 | `climax: 0.80` | 仅当仓位上限被绑定才变 | 对齐 `positive`；11-11 未绑定（max 0.2），仍零变化 |
| A3 | `climax: 0.50` 或 `0.30` | 会压缩高潮期新开仓 | 需知识库《情绪周期-仓位联动》依据；属「果」层判定，须独立论证 |

> 建议 A1 先行（配置化、零行为变更），A3 若要做须另开号并附知识库依据。

### Q2｜B：死配置处置路线

| 选项 | 做法 | 行为变化 | 风险 |
|---|---|---|---|
| **B2（推荐先行）** | yaml 注释显式标注「仅 legacy 生效」，并在 `arbiter.py`/`factor_arbiter.py` 交叉注明 v390 权威阈值位置 | 零 | 无 |
| B1 | 把 v390 的 `80/65/45/30` 与 C 码规则集接入 yaml | 有（可调参即改判定） | 阈值属「果」层（445/439），须单独拍板；改后需全市场回放 |
| B3 | 删除这两段死配置 | 零 | 丢失 legacy 回滚能力，不推荐 |

> 建议 B2 本号落地；B1 若需要，另开号做「v390 阈值配置化」并附回放对比。

### Q3｜C：monthly_halt 落库

| 选项 | 做法 | 行为变化 |
|---|---|---|
| **C1（推荐）** | 写库改 `int(bool(...))`（false→0），同时读取层 `NULL→False` 兜底 | 零判定变化；列值可区分 |
| C2 | 不改写库，仅读取层 `NULL→False` | 零判定变化；仍无法区分历史缺失 |

> 建议 C1；11-11 历史行是否回填由你决定（回填只改该列，不动判定）。

---

## 四、批次划分与依赖

| 批次 | 内容 | 依赖 | 预估改动面 |
|---|---|---|---|
| 批次 1 | C1：`data_daemon.py:7640` 写 0/1 + 读取层兜底 + 定向测试 | 无 | 1 文件 + 1 测试 |
| 批次 2 | A1：`status_engine.yaml` 增 `climax: 0.60` + 配置注释 | Q1 拍板 | 1 配置文件 |
| 批次 3 | B2：yaml/代码注释标注 v390 死配置边界 | Q2 拍板 | 2 文件（注释） |

> A 若选 A2/A3、B 若选 B1，均升级为行为变更批次，需先做全市场回放对比。

---

## 五、验证口径（按项目红线）

1. **静态**：`ruff check` + `py_compile`（若改 py）。
2. **定向测试**：`backend/tests/test_431_g2_config_loading.py`（阈值/规则加载）、`test_api_health` 等；新增 `climax` 档断言（0.6）与 `monthly_halt` 0/1 断言。
3. **沙箱重放（禁污染基准库）**：`cp -c` 克隆 `data/duckdb` → `init_sharding(tmp)` + `DATA_DIR` 双切 → 对 11-11 只跑 JUD（`--skip-sig`）→ 对比 `status_snapshot_history` 的 `opportunity_state / final_score / max_position_ratio` 分布**逐档不变**（A1/B2/C1 均应零变化）。
4. **live 验收**：改数据/引擎类须重启 daemon 后重跑对应管道步骤；C1 的 live 验证可在下一次日终或沙箱回放完成（不要求当日重跑全链路）。
5. **合规自检**：`git diff` 不新增 `TushareProvider()` / `sync_*` / `use_cache=False`；不触碰 routes/services 取数路径。

---

## 六、影响面与回滚

- **A1**：仅配置显式化，`emotion_position_cap` 输出不变；回滚 = 删 `climax` 键。
- **B2**：纯注释，无运行影响；回滚 = 还原注释。
- **C1**：`monthly_halt` 列由 NULL 变 0；所有读取方需确认 `0` 与 `False` 等价（`if monthly_halt:` 语义不变）。回滚 = 还原写库表达式；已写 0 的历史行可保留（0 与 NULL 在布尔语义上等价）。
- **不触碰**：`opportunity_state` 判定路径、`final_score` 评分、`consensus_rate`、`treemap` 构建。

---

## 七、待拍板清单

- **Q1**：A 档位取 A1（0.60，推荐）/ A2（0.80）/ A3（其他，需依据）？
- **Q2**：B 取 B2（标注，推荐）/ B1（v390 接线，另开号）/ B3（删除）？
- **Q3**：C 取 C1（写 0/1，推荐）/ C2（仅读取兜底）？是否回填 11-11 历史行？

---

## 八、实施记录（2026-11-12，拍板 A1 / B2 / C1+回填）

### 8.1 改动清单

| 项 | 文件 | 改动 |
|---|---|---|
| C1 | `backend/app/services/account_risk_status.py` | 新增纯函数 `monthly_halt_db_flag(value)`：True→1，False/None→0 |
| C1 | `backend/data_daemon.py` | `_build_status_snapshot` 内改为 `monthly_halt_db_flag(row.get('monthly_halt'))`（原 `1 if ... else None`） |
| A1 | `backend/config/status_engine.yaml` | `l0.emotion_position_cap` 增 `climax: 0.60` |
| B2 | `backend/config/status_engine.yaml` | `consensus` / `conflict_rules` 段加「仅 legacy 生效」注释 |
| B2 | `backend/app/opportunity_atlas/arbiter.py` | `_load_thresholds` / `_load_conflict_rules` docstring 标注 v390 不消费 |
| B2 | `backend/app/opportunity_atlas/factor_arbiter.py` | `_THRESHOLDS` 处标注「v390 权威档位，与 yaml consensus 不同源」 |
| 测试 | `backend/tests/test_564_config_dead_paths.py`（新增） | climax 显式档、v390 档位、`monthly_halt_db_flag` 三组断言 |
| 测试 | `backend/tests/test_431_g2_config_loading.py` | `emotion_position_cap` 期望补 `climax: 0.60` |

### 8.2 验证

- `backend/.venv/bin/python -m pytest backend/tests/test_564_config_dead_paths.py backend/tests/test_431_g2_config_loading.py -q` → **22 passed**。
- `py_compile`：`data_daemon.py` / `account_risk_status.py` / `arbiter.py` / `factor_arbiter.py` / 新测试 → **OK**。
- 回填 11-11：`status_snapshot` 5572 行、`status_snapshot_history` 5572 行，`monthly_halt` NULL→0（各 `changes()=5572`）；11-10 未动（仍 5571 NULL）。
- 配置自检：`get_status_engine_config()['l0']['emotion_position_cap']` 已含 `climax: 0.6`。
- daemon 重载：旧 pid 1353 于 08:15:14 收到停止信号、08:15:46 退出；看守 `start_daemon.sh` 于 08:16 拉起新 pid 8504，已进入启动补采。

### 8.3 待办

- **live 验收**：下一次日终（或定向回放）确认新写入的 `status_snapshot(_history).monthly_halt` 为 0/1 而非 NULL；A1/B2 为值不变/注释类，无需行为对比。
- 若后续要做 **B1（v390 阈值配置化）**，需另开号并按「果」层流程做全市场回放。
