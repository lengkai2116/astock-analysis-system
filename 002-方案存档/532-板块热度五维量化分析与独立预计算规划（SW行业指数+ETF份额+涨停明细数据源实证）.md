# 532号｜板块热度五维量化分析与独立预计算规划（SW行业指数 + ETF份额 + 涨停明细数据源实证）

**状态**：🟢 批次1~批次4 已完成（COL 4 表 + 250 日回填 + RAW-2E 31 行业 + DataManager/API/前端五维榜 + 250 日历史回算/阈值校准）；待前端目检与提交
**HEAD（开工前）**：`49a3b3c`（531 目检迭代，未推送）
**缘起**：2026-10-21 用户贴出 wiki《行业板块热度的多维量化分析框架》，要求评估现有「板块热度 Top」能否按该框架调整；只读评估后用户拍板「开新号，先按完成实现来进行规划」。
**三条硬约束（用户 2026-10-21 明确）**：
1. **第一步先确认缺失数据源是否能够获取**（本档 §二 已实测）；
2. 新增数据**单独规划在 RAW 或 SIG 环节**（预计算或独立引擎），**不得直接修改原有数据体系的核算与消费逻辑**；
3. 现阶段为系统修正阶段，**可停 daemon 做回填/回算**。

---

## 一、目标与非目标

### 1.1 目标
在既有数据底座上，新增一套**与现有板块热度并行的**五维热度 sidecar：

| 维度 | 内容 | 输出 |
|---|---|---|
| D1 相对强弱 | 20/60/120 日 RPS、多周期共振、相对沪深300超额 | 分位/分值 |
| D2 资金流向 | 主力净流入（已有）、融资余额增速、ETF 份额变化、北向（可选） | 强度/分值 |
| D3 量价形态 | 板块指数放量突破/缩量回踩/天量滞涨/地量横盘/放量下跌 | 状态+分值 |
| D4 情绪拥挤 | 涨停占比、炸板率、连板高度、成交额占比、封板资金 | 拥挤度（反向） |
| D5 内部广度 | 上涨家数占比、中位 vs 平均涨幅、板块内高 RPS 占比 | 扩散度 |
| 综合 | 质量分 0~100 + 阶段（主线/脉冲/过热/冷门/中性）+ 过热预警 | 排序+文案 |

### 1.2 非目标（红线）
- **不改** `sector_heat_cache`、`sector_fund_heat_cache`、`SectorRotationModel`、`DashboardService.get_sector_heat`；
- **不改** 现有 `heat_level` 语义（top_10/top_20/normal/none）及 **11 处引擎消费方**（dim5、dim8 adapter、arbiter、cross_validate、phase_detector、potential、radar 等）；
- 不做盘中实时（日频，T+1 可用）；
- 不引入新数据库/Redis，不绕过 DataManager；
- 不用 Mock/随机数据补齐缺口（缺失→null + 覆盖标记）。

---

## 二、数据源可得性实证（2026-10-21 只读探测）

> 环境：`backend/.venv`（tushare 1.4.29 + akshare 1.18.64）；token 来自项目 `.env`；探测不写库。
> 当前数据日：**2026-10-20**。

| # | 数据源 / 接口 | 探测结果 | 关键字段 | 结论 |
|---|---|---|---|---|
| E1 | `pro.sw_daily(ts_code='801080.SI', 20260101~20261021)` | **190 行**（2026-01-01~10-20） | ts_code, trade_date, open/high/low/close, pct_change, vol, amount, pe, pb, float_mv | ✅ **申万一级行业指数日线可得**（D1/D3 官方口径） |
| E2 | `pro.index_classify(level='L1', src='SW2021')` | **31 行** | index_code, industry_name, level | ✅ 31 个申万一级指数清单 |
| E3 | `pro.index_daily(ts_code='801080.SI')` | **0 行** | — | ❌ 不能用 `index_daily` 取 SW 指数，必须用 `sw_daily` |
| E4 | `pro.moneyflow_hsgt(2026-04-01~10-21)` | **129 行** | trade_date, hgt, sgt, north_money, south_money | ✅ **市场级北向**可得；❌ 无行业拆分 |
| E5 | `pro.hk_hold(trade_date='20261020')` | **1,018 行，全部 exchange=HK，A 股 0 行** | code, ts_code, vol, ratio, exchange | ❌ **A 股北向持股当前期不可得** |
| E5' | `pro.hk_hold(trade_date='20240105')` | 4,042 行（SH 1,513 / SZ 1,758 / HK 771） | 同上 | ⚠️ 仅历史可得（当前期已停更/口径变化） |
| E6 | `pro.fund_basic(market='E')` | **2,997 只 ETF**，benchmark 100% 有值 | ts_code, name, benchmark, fund_type | ✅ ETF 清单与跟踪指数可得 |
| E7 | `pro.fund_share(trade_date='20261020')` | **1,798 行**（fund_type=ETF） | ts_code, trade_date, fd_share | ✅ **ETF 份额日频可得** |
| E7' | `pro.fund_share(ts_code='510300.SH', 2026-04-01~10-21)` | **134 行** | 同上 | ✅ 单只历史完整，可回填 |
| E8 | `pro.index_daily('000300.SH', 2026-01-01~10-21)` | **190 行**；2024 年一年 246 行 | close, pct_chg | ✅ HS300 历史可回填（≥120 日） |
| E9 | `pro.limit_list_d(trade_date='20261020', limit_type='U')` | **54 行** | fd_amount, first_time, last_time, open_times, up_stat, limit_times, limit | ✅ **封板资金/开板次数/首末封板/连板数可得** |
| E10 | 现有 `sentiment_pool_cache` | 2,376 行 / 17 日；up 1,344 / down 432 / **zha 600** | limit_type, consecutive_days, first_seal_time | ✅ 炸板池已在采集（`stock_zt_pool_zbgc_em`） |

**缺口结论**：
1. **北向行业净流入**：❌ 当前期 A 股持股不可得（E5=0 行），只有市场级 `north_money`（E4）→ **不纳入行业分维**，仅作市场背景（默认关闭）；
2. **ETF 份额**：✅ 可得（E7/E7'），但行业归属需**新建 ETF→SW 行业映射表**（E6 的 name/benchmark 关键词可覆盖大部分行业 ETF，需人工兜底）；
3. **龙头开板/溢价**：✅ 开板次数、封板资金、首末封板时间、连板数可得（E9）；**溢价率无字段**，以封板资金+开板次数+首末封板时间近似，须标注口径；
4. **板块指数**：✅ 官方 `sw_daily` 可得（E1），**无需用成分股合成**。

---

## 三、五维指标 → 数据源 → 预计算映射

> 行业口径统一：**申万一级 31 类**（`stock_sw_industry` 5,220 只 / 全市场约 5,500，覆盖 ~95%）。

### D1 相对强弱
| 指标 | 公式 | 数据源 |
|---|---|---|
| `ret_20/60/120` | `close_t / close_{t-N} - 1`（N=20/60/120 交易日） | `sw_index_daily_cache`（E1） |
| `rps_20/60/120` | 31 个行业 `ret_N` 的横截面百分位（0~100） | 同上（预计算） |
| `rps_resonance` | `count(rps_20>=80)+count(rps_60>=80)+count(rps_120>=80)` → 0~3 | 同上 |
| `excess_20/60` | 行业收益 − 沪深300 同期收益（120 日超额待回填后启用） | `index_daily_cache`（E8） |
| `rps_trend` | `rps_20` 近 5 日变化（升/降/平） | `sector_heat_dim_cache` 历史 |

### D2 资金流向
| 指标 | 公式 | 数据源 |
|---|---|---|
| `main_net_5d` / `fund_ratio` | 近 5 日 `buy_lg+buy_elg−sell_lg−sell_elg` 按行业汇总；÷ 行业流通市值×100 | `moneyflow_cache` + `daily_basic_cache`（已有，口径同 530 RAW-2D） |
| `margin_growth_5d` | 行业 `rzye` 近 5 日变化率（成分股求和） | `margin_cache`（逐股，95 日） |
| `north_net_5d` | 市场级 `north_money` 5 日累计（仅背景，不参与行业排序） | `northbound_flow_cache`（E4，**默认关闭**） |
| `etf_share_chg_5d` | 行业映射 ETF 的 `fd_share` 5 日变化率（按份额加权） | `fund_share_cache` + `etf_industry_map`（E7） |

### D3 量价形态
| 指标 | 公式 | 数据源 |
|---|---|---|
| `vol_ratio_5d` | `amount_t / mean(amount_{t-5..t-1})` | `sw_index_daily_cache` |
| `breakout_20d` | `close_t >= max(close_{t-20..t-1})` | 同上 |
| `vp_state` | 放量突破 / 缩量回踩 / 天量滞涨 / 地量横盘 / 放量下跌（阈值 yaml） | 同上 |
| `vp_score` | 状态映射 0~100（健康=高、派发=低） | 引擎 |

### D4 情绪拥挤（反向维度）
| 指标 | 公式 | 数据源 |
|---|---|---|
| `limit_up_ratio` | 行业涨停家数 ÷ 行业成分股数 | `limit_detail_cache`（E9）/`sentiment_pool_cache` |
| `zhaban_ratio` | 行业炸板数 ÷（涨停+炸板） | `sentiment_pool_cache`（zha） |
| `max_board_height` | 行业 `limit_times`/`consecutive_days` 最大值 | E9 / 现有池 |
| `amount_share` | 行业成交额 ÷ 全市场成交额 | `daily_cache` / `sw_index_daily_cache` |
| `fd_amount_ratio` | 行业龙头封板资金 ÷ 行业流通市值 | `limit_detail_cache`（E9） |
| `open_times_avg` | 行业涨停股平均开板次数 | `limit_detail_cache`（E9） |

### D5 内部广度
| 指标 | 公式 | 数据源 |
|---|---|---|
| `up_ratio` | 行业上涨家数 ÷ 行业成分股数 | `daily_cache` + `stock_sw_industry` |
| `med_vs_mean` | 行业中位涨幅 − 平均涨幅（>0 说明少数大票拉动） | 同上 |
| `rps_high_ratio` | 行业内 `rps_20>=80` 的个股占比 | `relative_strength_cache`（个股已有，12 日）+ 新算 |
| `breadth_divergence` | 指数涨但 `up_ratio<50%`（或反之） | 上述组合 |

---

## 四、架构设计（全部新增，旧链路零改动）

### 4.1 新增采集表（COL 层）

| 表 | 主键 | 字段 | 来源 | 路由 |
|---|---|---|---|---|
| `daily_cache`（**复用，不新建**） | (ts_code, trade_date) | open/high/low/close/vol/amount/pct_chg | 申万 31 个 801xxx 已由 `_batch_index_daily` 写入（2026-10-21 实证：31 代码 / 2,790 行）；HS300 亦在内（89 行）→ 批次1 仅补历史 | market_cache.db |
| `fund_share_cache` | (ts_code, trade_date) | fd_share, fund_type, market | `fund_share` | market_cache.db |
| `etf_industry_map` | ts_code | sw_industry, fund_name, benchmark, mapping_source, updated_at | `fund_basic` + 人工/规则映射 | compute_cache.db（配置表） |
| `limit_detail_cache` | (trade_date, ts_code) | fd_amount, first_time, last_time, open_times, limit_times, up_stat, limit | `limit_list_d` | market_cache.db |
| `northbound_flow_cache` | trade_date | north_money, hgt, sgt | `moneyflow_hsgt`（可选） | market_cache.db |

> 新表必须在 `sharding_manager` 注册路由；**不得修改**既有表结构（含 `sentiment_pool_cache`）。
> 现有 `index_daily_cache` 已有代码路径（`_batch_index_daily`），HS300 回填优先复用；若为空则新建/补采。

### 4.2 新增 RAW 步骤 `RAW-2E`

- 位置：`data_daemon._drive_pipeline` 中 **RAW-2D 之后**（当前 RAW-2D 在 `data_daemon.py:7105-7107`）；
- 函数：`_precompute_sector_heat_dim(codes)`（新函数，独立短连接 + 写锁，模式对齐 `_precompute_sector_fund_heat`）；
- 输入：§4.1 新表 + 既有 `moneyflow_cache`/`margin_cache`/`daily_cache`/`daily_basic_cache`/`sentiment_pool_cache`/`relative_strength_cache`/`stock_sw_industry`；
- 输出：`sector_heat_dim_cache`（compute_cache.db），按 `stat_date` 幂等替换；
- 失败策略：任一输入缺失 → 对应维度 `null` + `coverage` 标记，**不阻断**旧 RAW；不回退 Mock。

**新表 `sector_heat_dim_cache`（草案）**：
```sql
CREATE TABLE IF NOT EXISTS sector_heat_dim_cache (
    stat_date TEXT NOT NULL,
    industry TEXT NOT NULL,
    -- D1
    ret_20 REAL, ret_60 REAL, ret_120 REAL,
    rps_20 REAL, rps_60 REAL, rps_120 REAL,
    rps_resonance INTEGER, excess_20 REAL, excess_60 REAL,
    -- D2
    main_net_5d REAL, fund_ratio REAL, margin_growth_5d REAL,
    north_net_5d REAL, etf_share_chg_5d REAL,
    -- D3
    vol_ratio_5d REAL, breakout_20d INTEGER, vp_state TEXT, vp_score REAL,
    -- D4
    limit_up_ratio REAL, zhaban_ratio REAL, max_board_height INTEGER,
    amount_share REAL, fd_amount_ratio REAL, open_times_avg REAL,
    -- D5
    up_ratio REAL, med_vs_mean REAL, rps_high_ratio REAL,
    -- 综合
    dim_rs REAL, dim_fund REAL, dim_vp REAL, dim_sentiment REAL, dim_breadth REAL,
    quality_score REAL, stage TEXT, heat_rank INTEGER,
    flags_json TEXT, coverage_json TEXT, calc_version TEXT,
    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (stat_date, industry)
);
```

### 4.3 新增独立引擎

- 文件：`backend/app/engine/framework/sector_heat_composite.py`（**新文件**）；
- 类：`SectorHeatCompositeEngine`；
- 纯函数：输入各维原始指标 + YAML 配置 → 输出分维分值、`quality_score`、`stage`、`flags`；
- **不读写 DB**（由 RAW-2E 调用），便于单测；
- **不修改** `SectorRotationModel`（旧热度继续由它产出）。

**阶段判定（草案）**：

| 阶段 | 条件（示意） |
|---|---|
| 主线确立 | `rps_resonance>=2` 且 `up_ratio>=0.6` 且 `fund_ratio>0` 且 `vp_state` 健康 |
| 脉冲热点 | `rps_20>=90` 但 `rps_60<60` 或 `up_ratio<0.5` |
| 过热预警 | `limit_up_ratio>5%` 且 `zhaban_ratio>40%`，或 `amount_share` 创 20 日新高且 `rps_120>95` |
| 冷门潜伏 | `rps_20<30` 且 `vol_ratio_5d<0.8` 且 `fund_ratio>0` |
| 中性/退潮 | 其余（按分值排序） |

### 4.4 新增配置

- `backend/config/sector_heat.yaml`（**新文件**，不修改 `dim_engine.yaml` 等）：
  - 维度权重（初值建议：资金 30 / 强弱 25 / 广度 25 / 情绪 20；量价作为修正项 ±10）；
  - 绝对阈值（RPS 90/95、涨停占比 5%、炸板率 40%、成交额占比 15%）+ 分位阈值；
  - 阶段规则、`northbound.enabled=false`、`etf.enabled=true`、`calc_version`。

### 4.5 读路径与展示（Q1=**替换旧榜**）

- `DataManager.get_cached_sector_heat_dim(stat_date=None)`（**新增只读方法**）；
- 新 API：`GET /api/v3/market/sector-heat-dim`（**新增路由**）；
- 旧 `/api/v3/market/sector-heat` **保留不改**（引擎消费链不受影响）；
- 前端：把「🔥 板块热度 Top」卡片的**内容替换**为五维榜（标题改「🔥 板块热度 · 五维」），新渲染函数 `renderSectorHeatDim()` 替代 `applySectorHeat()` 的展示；旧 `applySectorHeat()` 仅作**降级回退**（新接口空/失败时显示旧资金热度并标注「五维未就绪，暂显示原资金热度」）；
- **旧表、旧引擎、旧 API、11 处引擎消费方全部不动**；“替换”仅指展示层。

### 4.6 展示形态设计（前置规划，2026-10-21 Q1 拍板）

#### 4.6.1 信息架构（自上而下）

1. **卡头**：`🔥 板块热度 · 五维` + 数据日（如 `2026-10-20`）+ `口径说明 ⓘ`（展开/收起）+ `展开全部 31 类 / 收起`；
2. **KPI 条**（4 格）：主线板块 N 个｜过热预警 M 个｜中位质量分 X（较上一交易日 ±Y）｜数据覆盖（ETF xx% · 北向 关闭）；
3. **过热预警条**（仅有预警时显示）：`⚠️ 过热：电子（涨停 6.2% / 炸板 45%）、有色（成交额占比 15.8%）…`，点击即筛选；
4. **工具条**：排序（质量分/资金/强弱/情绪拥挤）+ 阶段筛选（全部/主线/脉冲/过热/冷门）；
5. **主表**（默认质量分 Top10，可展开 31 类）；
6. **行展开详情**（手风琴，单行展开）：雷达图 + 五维明细 + 阶段判定依据。

#### 4.6.2 主表列定义

| 列 | 宽度 | 内容 |
|---|---|---|
| `#` | 40px | 质量分排名 |
| 行业 | 180px | 行业名 + 阶段徽标（主线/脉冲/过热/冷门/中性） |
| 质量分 | 130px | 0~100 数字 + 横向渐变条 |
| 五维 | 260px | 5 条迷你横条：强/资/价/情/广（各 0~100，带 tooltip） |
| 关键证据 | flex | 一行摘要：`RPS20 92 · 主力5日 +12.3亿 · 涨停 2/45 · 上涨 78%` |
| 标签 | 110px | 过热 / 广度背离 / ETF覆盖低 / 北向关闭 |
| ▾ | 32px | 展开详情 |

#### 4.6.3 行展开详情

- **左（约 320px）**：5 轴雷达（强弱/资金/量价/情绪/广度）+ 质量分/阶段/排名；
- **右（五维卡片，2 列）**：
  - 强弱：RPS20/60/120、共振 0~3、超额 20/60；
  - 资金：主力 5 日净流入、资金占比、融资增速 5 日、ETF 份额变化 5 日；
  - 量价：量比 5 日、20 日突破、量价状态（放量突破/缩量回踩/天量滞涨/地量横盘/放量下跌）；
  - 情绪：涨停占比、炸板率、连板高度、成交额占比、封板资金占比（**反向色**：越高越红）；
  - 广度：上涨占比、中位−平均涨幅、高 RPS 占比；
- **底部**：阶段判定依据（规则命中列表，如 `RPS 共振 2/3 ✓｜上涨占比 78% ✓｜主力净流入 ✓｜量价=放量突破 ✓`）；
- 缺失维度显示 `—` + `覆盖不足` 徽标，不显示 0 冒充。

#### 4.6.4 交互

- 默认按**质量分降序 Top10**；「展开全部」显示 31 类；
- 排序切换：质量分 / 资金 / 强弱 / 情绪拥挤（高→低）；
- 阶段筛选与过热条联动；
- 行点击展开，再次点击收起（同时只展开一行）；
- 迷你条 hover 显示原始值；阶段徽标 hover 显示规则；
- 表格横向溢出时容器内滚动（`overflow-x:auto`），不破卡片。

#### 4.6.5 状态与降级

| 状态 | 展示 |
|---|---|
| 正常 | 上述完整五维 |
| 部分缺失 | 对应维度 `—` + `覆盖不足`；KPI 覆盖格标注（如 `ETF 62%`） |
| 新接口空/失败 | 显示「五维数据未就绪（RAW-2E 未运行）」+ 旧资金热度榜（明确标注「暂显示原资金热度」） |
| 北向关闭 | 详情中显示「行业级北向当前不可得，已关闭」灰字 |

#### 4.6.6 视觉规范

- 沿用仪表盘现有暗色卡片/14px 说明文字口径（531 §八）；
- 阶段色：主线 `#EF4444`、脉冲 `#F59E0B`、过热 `#DC2626`（斜纹底）、冷门 `#3B82F6`、中性 `#94A3B8`；
- 质量分条：低→高 灰→橙→红渐变；情绪条反向（低=绿，高=红）；
- 数字与单位分离（如 `+12.3` `亿`），保留 1 位小数；
- 数据日标注用具体交易日，不用「今日/当日」。

#### 4.6.7 线框示意

```text
┌ 🔥 板块热度 · 五维 ─────────────────────────── 2026-10-20  ⓘ口径  [展开全部31类] ┐
│ 主线 6 │ 过热预警 3 │ 中位质量分 58（↑4） │ ETF覆盖 82% · 北向关闭            │
│ ⚠ 过热：电子（涨停 6.2%/炸板 45%）· 有色（成交额占比 15.8%）…               │
│ 排序[质量分▾]  筛选[全部|主线|脉冲|过热|冷门]                              │
├────┬──────────┬─────────┬──────────────────────┬──────────────────────────┬────────┤
│ #  │ 行业      │ 质量分   │ 五维(强 资 价 情 广)  │ 关键证据                  │ 标签   │
│ 1  │ 电子 [主线]│ 86 ████ │ ▓▓▓ ▓▓▓▓ ▓▓  ▓  ▓▓▓  │ RPS20 92 · 主力+12.3亿 · 涨停2/45 · 上涨78% │ 过热  │
│ 2  │ 有色 [脉冲]│ 79 ███  │ ▓▓▓ ▓▓   ▓▓▓ ▓▓  ▓    │ RPS20 88 · 主力+6.1亿 · 涨停1/38 · 上涨64%  │       │
│ …  │ …        │ …       │ …                    │ …                        │       │
├────┴──────────┴─────────┴──────────────────────┴──────────────────────────┴────────┤
│ ▼ 详情：电子（2026-10-20）                                                       │
│ ┌─ 雷达(强弱/资金/量价/情绪/广度) ─┐ ┌ 强弱 RPS20 92 · RPS60 81 · 共振2/3 ─────┐ │
│ │        强弱 96                │ │ 资金 主力+12.3亿 · 占比+0.42% · 融资+1.8% │ │
│ │  广度 78      资金 88         │ │ 量价 量比1.9 · 突破20日高 · 放量突破     │ │
│ │      量价 72   情绪 35(拥挤)   │ │ 情绪 涨停6.2% · 炸板45% · 连板3 · 成交额12%│ │
│ └──────────────────────────────┘ │ 广度 上涨78% · 中位−平均 −0.3% · 高RPS 41%│ │
│ 阶段依据：RPS共振2/3 ✓｜上涨78% ✓｜主力净流入 ✓｜量价放量突破 ✓              │
└──────────────────────────────────────────────────────────────────────────────────┘
```

> 说明：以上为**展示层设计**，不改旧数据核算与旧接口；旧榜仅作新接口不可用时的回退。

---

---

## 五、回填与回算（可停 daemon）

| 步骤 | 内容 | 预估 |
|---|---|---|
| 1 | 停 daemon + 看守（按既有约定，避免 10s 复活） | 1 min |
| 2 | 回填 `sw_index_daily_cache`：31 指数 × 250 交易日 | 31 次调用，~5-10 min |
| 3 | 回填 `fund_share_cache`：250 个交易日（按日拉取） | ~250 次调用，~10-20 min |
| 4 | 回填 `limit_detail_cache`：120 个交易日 | 120 次调用，~5-10 min |
| 5 | 回填 HS300：250 交易日（`index_daily`） | 1 次调用 |
| 6 | （可选）`northbound_flow_cache`：250 日 | 1 次调用 |
| 7 | 一次性重算 `RAW-2E` 近 120/250 日 | 新脚本，~5-15 min |
| 8 | 阈值校准（250 日分布）→ 写 `sector_heat.yaml` → 重算最近 5 日 | ~5 min |
| 9 | 重启 daemon + API，核验新接口与旧接口 | 5 min |

> 回填脚本放 `backend/scripts/`（**新文件**），不改既有脚本；回填期间不跑 EOD（避开 18:00 门槛窗口）。

---

## 六、分批实施计划

| 批次 | 内容 | 交付物 | 验收 |
|---|---|---|---|
| **批次0** | 数据源/表设计/映射规则（本档 §二~§四） | 532 方案 + 探针记录 | 数据源结论确认 |
| **批次1** | COL 新表 DDL + 采集函数 + 路由注册 + 回填脚本 | 5 张表 + 采集代码 | 表有数据、日期连续、幂等 |
| **批次2** | `SectorHeatCompositeEngine` + `sector_heat.yaml` + RAW-2E + 单测 | 引擎/配置/预计算 | 单测全过；31 行业全量输出 |
| **批次3** | DataManager 方法 + 新 API + 前端五维榜（**替换旧榜**，旧榜降级回退） | 读路径/展示 | 接口 200；旧 API/表/引擎不变；新接口空/失败回退正常 |
| **批次4** | 全量回填 + 阈值校准 + 回归 + 文档 | 校准配置/验证报告 | 旧 11 消费方零变更；全量测试通过 |

---

## 七、验证与验收标准

1. **单元测试**：引擎公式、阶段边界、缺失维度降级（不抛异常、不产生 NaN 排序）；
2. **数据校验**：31 行业 × 目标日期无缺失；`coverage_json` 标出 ETF/北向缺失；日期连续；
3. **回归**：daemon 停止后跑定向 + 全量；旧 `sector_heat_cache`/`sector_fund_heat_cache`/`get_sector_heat` 输出前后快照一致；
4. **接口**：新接口 schema 稳定，旧接口向后兼容；
5. **前端**：用户手动起服目检（旧榜单不变，新增五维块可折叠）。

---

## 八、风险与红线

| 风险 | 影响 | 处置 |
|---|---|---|
| 北向 A 股持股当前不可得（E5） | 行业北向维度缺失 | 默认关闭；只保留市场级背景；不造假数据 |
| ETF 行业映射歧义 | ETF 份额维度偏差 | 新表 + 人工兜底；仅纳入行业/主题 ETF；输出覆盖率 |
| SW 指数为 T+1/权限/限频 | D1/D3 滞后 | 本地缓存 + 失败重试；RAW 幂等 |
| 回填期间停 daemon | 盘中数据中断 | 选择非交易时段/避开 EOD；回填后重启 |
| SQLite 写锁 | RAW-2E 写失败 | 独立短连接 + 写锁（对齐 RAW-2D） |
| 误改旧链路 | 11 消费方回归 | 只新增表/引擎/接口；旧表/旧字段/旧方法零改动 |

**红线**：新增指标一律走 COL→RAW→DataManager→调用层；路由不得实时计算/直连数据源；缺失不 Mock。

---

## 九、拍板结果（2026-10-21，Q1~Q7 全部确认）

| # | 拍板 | 落地口径 |
|---|---|---|
| Q1 | ✅ **替换旧榜** | 「🔥 板块热度 Top」卡片内容替换为五维榜；**旧 API/旧表/旧引擎保留**，仅展示层替换；新接口空/失败时回退旧资金热度并标注「五维未就绪，暂显示原资金热度」 |
| Q2 | ✅ 接受建议权重 | 资金 30 / 强弱 25 / 广度 25 / 情绪 20；量价 ±10 修正项 |
| Q3 | ✅ 接受 | 北向维度**默认关闭**（行业级当前不可得），仅保留市场级背景 |
| Q4 | ✅ **行业 + 主题 ETF 一并纳入** | `etf_industry_map` 增 `etf_type`（industry/theme）区分；输出映射覆盖率到 KPI，避免后续二次操作 |
| Q5 | ✅ 接受 | 校准窗口 250 日，不足自动退 120 日并标注 |
| Q6 | ✅ 接受 | 回填 250 日（D1/D2）；情绪/涨停 120 日 |
| Q7 | ✅ **量价纳入首批** | D3 与 D1/D2/D4/D5 同批实施 |

> 展示形态见 §4.6；若实施中 ETF 主题映射覆盖率过低，按 Q4 保留行业 ETF 优先并在 KPI 标注覆盖率，不阻塞首批。

---

## 十、附录：探测命令与原始结果（2026-10-21）

```text
# 环境
backend/.venv: tushare 1.4.29 / akshare 1.18.64

# 数据源探测（只读，未落库）
sw_daily(801080.SI, 20260101~20261021)      -> 190 rows, OHLCV+pe/pb/float_mv
index_classify(level=L1, src=SW2021)        -> 31 rows
index_daily(801080.SI)                      -> 0 rows
moneyflow_hsgt(2026-04-01~10-21)            -> 129 rows（市场级）
hk_hold(2026-10-20)                         -> 1018 rows, exchange=HK 100%，A 股 0
hk_hold(2024-01-05)                         -> 4042 rows（SH 1513 / SZ 1758 / HK 771）
fund_basic(market=E)                        -> 2997 rows, benchmark 全有
fund_share(2026-10-20)                      -> 1798 rows
fund_share(510300.SH, 2026-04-01~10-21)     -> 134 rows
index_daily(000300.SH, 2026)                -> 190 rows
limit_list_d(2026-10-20, U)                 -> 54 rows（fd_amount/open_times/limit_times/first_time/last_time）
```

**现有底座（只读实测）**：`daily_cache` 8,448,792 行 / 7,550 日；`daily_basic_cache` 6,630,620 行 / 1,280 日；`moneyflow_cache` 329,552 行 / 60 日；`margin_cache` 419,512 行 / 95 日；`sentiment_pool_cache` 2,376 行 / 17 日（up 1,344 / down 432 / zha 600）；`relative_strength_cache` 133,290 行 / 12 日（仅 rps_20/60）；`stock_sw_industry` 5,220 只；`sector_fund_heat_cache` 31 行 / 仅 2026-10-19；`sector_heat_cache` 1,594 行 / 16 日 / 109 行业。

---

## 十一、批次1 实施记录（2026-10-21，代码已落地；回填待执行）

**范围调整（实证）**：原计划 `sw_index_daily_cache` **取消**——`_batch_index_daily` 已将申万 31 个 801xxx 写入 `daily_cache`（2026-10-21 实证：2,790 行 / 2026-06-08~10-20），HS300 亦在内（89 行）。批次1 实际新增 **4 张表**：`fund_share_cache`、`limit_detail_cache`、`northbound_flow_cache`（market_cache.db）、`etf_industry_map`（compute_cache.db）。

**已实施**
- **分库路由**：`sharding_manager` 登记 4 表（3 market + 1 compute）。
- **建表**：ECM `fund_share_cache` / `limit_detail_cache` / `northbound_flow_cache` / `etf_industry_map`。
- **写入/读取**：`cache_fund_share_data` / `cache_limit_detail_data` / `cache_northbound_flow_data` / `cache_etf_industry_map` + 4 个 `get_cached_*`。
- **Provider**：`get_sw_index_daily`（回填）、`get_index_daily_range`（HS300）、`get_fund_basic`、`get_fund_share`、`get_limit_list_d`、`get_moneyflow_hsgt`；旧 `get_index_daily` 行为不变。
- **ETF 映射模块**：`backend/app/data/etf_industry_map.py`（31 行业关键词 + 跨行业主题 + 宽基排除；`etf_type=industry/theme`；月度刷新、失败保留旧表）。
- **daemon**：`run_daily_sync` 追加 ETF 份额 / 涨停炸板明细 / 北向市场级 / ETF 映射任务（失败不阻断）；申万指数与 HS300 继续走既有 `_batch_index_daily`。
- **回填脚本**：`backend/scripts/_532_backfill_sector_heat_sources.py`（`--days/--only/--dry-run`，主键覆盖幂等）。
- **测试**：`backend/tests/test_532_col_sources.py` **5 passed**（DDL/路由/ETF 分类/Provider 假接口）；新增文件 ruff 通过、本次新增行 lint **0**。

**未执行**：实际回填（需停 daemon）；批次1 验收“表有数据/日期连续”待回填后确认。**未改**旧表/旧引擎/11 消费方。

**文件**：`backend/app/data/sharding_manager.py`、`enhanced_cache_manager.py`、`tushare_provider.py`、`etf_industry_map.py`（新）、`backend/data_daemon.py`、`backend/scripts/_532_backfill_sector_heat_sources.py`（新）、`backend/tests/test_532_col_sources.py`（新）。

---

## 十二、5 日 smoke 回填验证（2026-10-21）

**执行**：停 daemon/看守 → `_532_backfill_sector_heat_sources.py --days 5` → 重启。

| 表 | 结果 | 备注 |
|---|---|---|
| `fund_share_cache` | **8,984 行** / 5 日（10-14~10-20）/ 1,816 只 | ✅ |
| `limit_detail_cache` | **363 行** / 5 日（U 233 / Z 130） | ✅ 炸板池可用 |
| `northbound_flow_cache` | **4 行**（10-14~10-20，缺 1 日） | 市场级；缺日不补 |
| `daily_cache` 801xxx | 31 个 / **2,790 行**（回填 155 行） | 已有日期覆盖，幂等 |
| `daily_cache` 000300.SH | **5,291 行**（2005~2026） | 首跑顺带补全历史（原仅 89 行） |
| `etf_industry_map` | **588 条**（industry 472 / theme 116 / 27 行业） | 行业+主题；宽基已排除 |

**smoke 中发现并修复的两个问题**：
1. **总库空壳表自清理**会把新分库表的空壳 DROP → `_insert_from_df` 无法从总库复制结构 → 写入 0。修复：新增 `_ensure_sector_heat_shard_tables()`，在 `market_cache.db` 直接建 3 张新表（写入前调用，按库去重）。
2. **回填脚本 `create_app()` 误启采集/调度**（APScheduler 报错、采集线程启动）。修复：改 `init_sharding + EnhancedCacheManager` 轻量入口，并设 `DATA_DAEMON_RUNNING=1`，不启动 Flask/采集。

**状态**：daemon/看守已重启（2026-10-21 12:25；daemon PID 20834 / 看守 20782），`/api/v3/health/live` = alive；未改旧表/旧引擎/11 消费方。

### 250 日全量回填（2026-10-21，窗口 2025-10-09 ~ 2026-10-20）

| 表 | 结果 | 备注 |
|---|---|---|
| `fund_share_cache` | **397,753 行** / 250 日 / 4,954 只 | ✅ 全窗口 |
| `limit_detail_cache` | **12,043 行** / 120 日（U 8,836 / Z 3,207） | 首轮触发 200次/分钟限频缺 15 日 → 加“跳过已有 + 0.35s 节流 + 重试”后补齐 1,162 行，缺失 0 |
| `northbound_flow_cache` | **242 行**（2025-10-09~2026-10-20） | 市场级；源侧少数日期缺行 |
| `daily_cache` 801xxx | **7,750 行 / 31 个 / 250 日** | ✅ |
| `daily_cache` 000300.SH | **5,291 行**（2005~2026） | 首跑顺带补全历史 |
| `etf_industry_map` | **588 条**（industry 472 / theme 116 / 27 行业） | 宽基/债券/商品已排除 |

**结论**：五维原料已齐（D1/D3 用 250 日 801 指数；D2 ETF 份额 250 日 + 主力/融资；D4 涨停/炸板 120 日；D5 广度可由 daily_cache 直接算），具备进入批次2（RAW-2E + 引擎）的数据条件。

---

## 十三、批次2 实施记录（2026-10-21，RAW-2E + 五维引擎）

**已实施**
- `app/engine/framework/sector_heat_composite.py`：纯函数引擎（D1~D5、综合质量分、阶段、flags、evidence；31 指数→行业名映射）。
- `backend/config/sector_heat.yaml`：资金 30 / 强弱 25 / 广度 25 / 情绪 20、量价 ±10、阈值、北向关闭。
- `app/data/sector_heat_dim.py`：只读装配（801 收益/HS300 超额、主力/融资/ETF、量价、涨停/炸板、广度）。
- `sector_heat_dim_cache` 建表 + compute_cache.db 路由。
- `data_daemon._precompute_sector_heat_dim` + RAW-2E（RAW-2D 后）注册。
- 测试：`test_532_batch2_sector_heat_engine.py` 4 + 批次1 5 = **9 passed**；新增文件 ruff 通过。

**实数据验证（2026-10-20）**
- 31 个行业全部落表；分维无 null。
- stage：**neutral 29 / pulse 2**。
- TOP5：煤炭 72.23 · 石油石化 71.45 · 银行 71.38（pulse）· 美容护理 70.78 · 房地产 67.75。
- 初版阈值下多数 neutral 属预期；绝对阈值/阶段规则待 250 日分布校准（批次4）。

**关键修复**
- `000001.SH`（上证指数）与 `000001`（平安银行）6 位代码碰撞，被误归银行 → 银行 `amount_share` 34.07%、误判 overheat；已在资金/市值/融资/日线/涨停/相对强弱聚合前统一 `is_index_code()` 过滤。修复后银行 amount_share **2.27%**、stage=**pulse**。

**状态**：批次2 代码 + 实数据验证完成；批次3（DataManager/API/前端替换旧榜）与批次4（校准）待实施。

---

## 十四、批次3 实施记录（2026-10-21，读路径 + API + 前端五维榜）

**已实施**
- `EnhancedCacheManager.get_cached_sector_heat_dim(stat_date=None)`：读 `sector_heat_dim_cache` 最新日全行业，解析 `flags_json`/`coverage_json`，附 `prev_date` / `prev_rank`（存在两日数据时）。
- `DataManager.get_cached_sector_heat_dim()`：存储层唯一网关只读封装。
- `DashboardService.get_sector_heat_dim(top_n=31)`：31 行业 + KPI（`stage_counts` / `median_quality` / `median_quality_delta` / `coverage`）+ `rules`（阶段判定依据）+ `prev_rank`；无数据返回 None → 路由 503。
- 新路由 `GET /api/v3/market/sector-heat-dim`（`top_n` clamp 1~31，`api_cache` 120s）。
- 前端 `_ui-prototype/dashboard.html`：`renderSectorHeatDim()` 完整 §4.6（KPI 四格 + 过热条 + 排序/阶段筛选 + Top10/展开 31 + 行展开雷达与五维明细）；`loadSectorHeatDim()` 独立加载；旧 `applySectorHeat()` 仅降级回退并标注「五维未就绪，暂显示原资金热度」；`dashboard/full` 不再直接套旧 `sector_heat`。
- 缺陷修复：`sector_heat_composite.compute()` 的 `etf_coverage_low` 把布尔 `True` 当 `1`（`True < 50` 恒真）→ 31/31 误标；已排除 bool；服务层再按 `coverage.etf` 纠正存量 flags（无需重跑 RAW-2E）。
- 测试：新增 `test_532_batch3_sector_heat_dim.py` 4 用例；定向 16 passed；仪表盘/板块相关 **130 passed**；前端两段内联 JS `node --check` 通过。

**实数据验证（2026-10-20）**
- 31 类全量；stage neutral 29 / pulse 2；中位质量分 **51.07**；ETF 覆盖 **87.1%**（27/31）；北向关闭。
- TOP3：煤炭 72.23 / 石油石化 71.45 / 银行 71.38（pulse）。
- 仅 1 个交易日：`median_quality_delta=None`、`prev_rank=None`；前端显示「首日」，且不标「新进榜」。

**未改**：旧 `sector_heat_cache` / `sector_fund_heat_cache` / `/market/sector-heat` / 11 处引擎消费方。

**状态**：批次3 完成；批次4（250 日 RAW-2E 回算 + 阈值校准）待实施。

---

## 十五、批次4 实施记录（2026-10-21，250 日历史回算 + 阈值校准）

**拍板**：分维回算（D1/D3/D5 250 日，D2 受 moneyflow 60 日、D4 受 limit_detail 120 日限制，缺失维度重归一）；分位校准 + 写回；先 dry-run 后写库。

**代码改造**
- `build_sector_heat_rows(ecm, target_date=None)`：历史回算入口；所有查询按 `<= target_date` 截断，避免前视偏差。
- `_last5_dates(..., end_date)`：资金/融资/ETF/北向近 5 日窗口按目标日截断。
- `limit_detail` 覆盖判断：以表内最早日期判断目标日是否在采集覆盖内；覆盖内 0 行＝真实 0 事件，覆盖外为缺失（不写 0 冒充）。
- `relative_strength_cache` 取 `MAX(asof_date) <= target`，避免用未来 RPS。
- **`_ret()` 修正**：原实现 `-n-2` 多退一天（实为 n+1 日收益），且 `len<=n` 在 `len=n+1` 时越界；改为 `-1-n` + `len < n+1`。
- 新增 `backend/scripts/_532_backfill_sector_heat_dim.py`：`--days/--end/--write/--calibrate/--keep/--min-sample/--report`；默认 dry-run；校准后按新阈值重算再写库；yaml 仅替换阈值数值并追加 calibration 元信息。

**回算结果**
- 250 个交易日（2025-10-09~2026-10-20）× 31 行业 = **7750 行**写入 `sector_heat_dim_cache`。
- 覆盖（行业-日）：D1 7130 / D2 1891 / D3 7719 / D4 3720 / D5 7750 / RPS 589 / ETF 6714。

**校准写回（5 项；zhaban 保持 40）**
- `rps120_overheat` 95 → **96.67**
- `limit_up_ratio` 5 → **5.43**
- `amount_share` 15 → **9.97**
- `crowding_overheat` 90 → **93.33**
- `rps_very_strong` 90 → **90**（不变）
- `zhaban_ratio` 保持 **40**：P90/P95 均为 100%（行业只有炸板时该比值结构性为 100），80 仅为 clamp 上限，不采纳。

**阶段影响（旧→新）**：mainline 2→2 / pulse 436→456 / overheat 631→499 / cold 5→5 / neutral 6676→6788；142 个行业-日变化（约 1.8%）。

**验证**
- `test_532_batch4_backfill.py` 8 用例；批次2/3/4 定向 **16 passed**；仪表盘/板块相关 **138 passed**。
- 实机 API `GET /api/v3/market/sector-heat-dim`：200；date=2026-10-20、prev_date=2026-10-19、count=31、median=51.07、delta=**+0.05**、stages neutral 28/pulse 3、ETF 87.1%、prev_rank 已返回；旧 `/market/sector-heat` 仍 200。
- 回算期间停 daemon/看守，完成后已重启 daemon 与 API（见 §状态）。

**未改**：旧 `sector_heat_cache` / `sector_fund_heat_cache` / `/market/sector-heat` / 11 处引擎消费方。

**状态**：批次4 完成；代码未提交、未 push。daemon 当前为直跑（看守单实例检查未接管），下次 `start.command` 可恢复正常看守。

---

## 十六、2026-10-21 目检后续修正（阶段说明 + 板块涨跌幅固定上一交易日）

**#1 阶段说明**：保留原词（主线/脉冲/过热/冷门/中性）；五维卡新增 14px 阶段说明行 + 阶段徽标 hover tooltip；注明「主力5日」＝大单+特大单净流入。

**#2 板块涨跌幅**：`get_sector_changes` 默认 `use_intraday=False`，不再优先读 `in_memory_store` 盘中板块快照（东方财富细分行业，5min 刷新）；改为 DB `_get_best_trade_date(before=today)` 固定 **today 之前最近完整交易日**（当前 2026-10-20），`as_of` 贯穿连续涨跌/近5日走势，避免收盘入库后切日。行业口径统一**申万一级 31 类**（发现柱状图/连续涨跌用 110 个东财二级行业，而近5日走势已用 31 类；110 类中小样本行业产生 -6% 级极端值）。前端 `renderSectorChart` 增加 `_sectorChartSig` 数据签名，30s 刷新相同数据不重绘。盘中快照仅显式 `use_intraday=True` 时启用。

**根因实证**：接口原返回 `date=2026-10-21/source=东方财富行业板块（盘中）`、细分行业榜单；`daily_cache` 最近完整日=2026-10-20（5604 行）；`as_sector_ranking.updated_at=2026-10-21 06:38:53`。非批次3/4 直接改动，触发因素为 daemon/API 重启后内存快照非空。

**验证**：定向 22 passed；仪表盘/板块 **143 passed**；API 连续两次 `date=2026-10-20/source=DuckDB daily_cache 聚合`、5日序列 `2026-10-14~2026-10-20` 一致，涨幅 计算机 2.66 / 电子 2.51 / 通信 2.37 / 机械设备 2.25 / 家用电器 1.78，跌幅 煤炭 -2.24 / 银行 -1.09 / 非银金融 -0.97 / 公用事业 -0.84 / 钢铁 -0.71；前端内联 JS `node --check` 通过。

**状态**：改动未提交/未 push；API 已重启、daemon 未动。

---

**本档：规划 + 批次1（COL/回填）+ 批次2（RAW-2E/引擎）+ 批次3（读路径/API/前端）+ 批次4（250 日回算/校准）+ 目检后续修正；待前端目检与提交。**
