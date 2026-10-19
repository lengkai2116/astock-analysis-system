# 524号｜仪表盘「大盘行情信息」板块 前端功能定位与监控增强能力规划（wiki 学习 + 数据源实证）

> **版本**：v1.5（2026-10-19 只读核查 + 能力规划 + **Q1~Q6 用户拍板 + 实施计划 + 批次1'（后端只读接口）+ 批次1（Q4 as_sector_ranking 建表归属修正）+ 批次2（前端 L1/L2/L5 骨架）+ 批次3（前端 L3/L4 + 板块热度接口）已实施**；**代码改动仅限后端只读接口、板块库表修复与前端展示层**）
> **性质**：只读核查档（前端展示层功能定位 + LLM wiki 知识库学习 + 数据源逐项实证）
> **范围**：`_ui-prototype/dashboard.html`（前端）＋ 后端只读取数能力边界；**本档不涉及代码改动**
> **前置**：513/514（数据与连接核查处置）、516（各模块数据二轮核查处置）、523（全市场日终散点新增）、481（dim8 第一层环境定位）
> **关联**：523（`eod-snapshot` 接口先例）、481（大盘趋势/行业/个股位置句）、447/458（dim5 情绪温度/BOCIASI）、166（仪表盘需求规范）、171（API 映射）
> **HEAD（核查时）**：`befdb0c`（= origin/main）
> **核对口径**：2026-10-19 只读实证——DuckDB/SQLite 以 `read_only` 打开 8 个库文件 + 运行中 API `:5001` 实取 `market/overview`；数据主体＝最新交易日 **2026-10-16**（10-19 为周一盘中前/盘后，实取 `data_is_live=False`）

---

## 一、缘起

用户 2026-10-19 要求：针对仪表盘 UI 进行**前端功能的定位**——为用户提供**大盘的行情信息**，结合现有仪表盘页面功能排布，**通过 LLM wiki 知识库搜索学习**，再次思考如何增强该板块「对大盘市场情况进行**监控跟进输出**」的能力规划，并在对话框说明，**不改方案和代码**。

→ 已在对话框完整报告（现状排布 8 区块 + wiki 学习 13 篇 + L1~L6 能力规划 + 数据源可行性）。用户拍板「**开号落核查档**」→ 本档（承接 516 先例：只读核查档，不动代码）。

## 二、现状功能排布（模块 × 取数接口对照）

| # | 模块（`dashboard.html`） | 取数接口 | 状态（截至 2026-10-19） |
|---|---|---|---|
| ① | 头部状态条＋成交额（+成交额环比） | `/market/overview` | ✅（516 Q4 已改「盘后·数据日」标注；实取 `data_is_live=False / data_date=2026-10-16 / market_status=closed`） |
| ② | 四大指数卡 + miniK | overview.indexes（price/change_pct/mini_kline/amount/source） | ✅（4 指数齐） |
| ③ | 四大指数合计成交额（近20日） | `/market/index-daily` | ✅（516 Q5 已改名含「成分重叠」） |
| ④ | 全市场资金流向趋势（近20日） | `/market/moneyflow-summary` | ✅（516 Q6 散户符号已统一） |
| ⑤ | 全市场日终散点×2（体量×涨跌 / 开高低收四象限） | `/market/eod-snapshot` | ✅（523 新增，5566 只） |
| ⑥ | 行业板块净流入排行 + Top5 板块·个股流入/流出 | `/market/sector-moneyflow` | ✅（516 P1/P6/rank 已处置） |
| ⑦ | 行业板块涨跌幅（涨幅/跌幅前十） | `/market/sector-sector` + `/market/daily-top` | ✅（516 P3 删 Mock 走空态） |
| ⑧ | 策略信号汇总面板 | — | **空位占位**（2026-08-04 伪信号移除；516 Q2 AI 雷达已下线） |

**定位判断**：8 区块全部为「行情数据呈现（展示型）」，**无市场状态判定、无市场宽度/情绪聚合、无监控预警/跟进输出**——与系统「建议输出型」定位（495 B1）存在落差：用户打开仪表盘看到大量图表，但没有「今天市场处于什么状态、强在哪、风险在哪」的结论输出。

## 三、LLM wiki 知识库学习要点（大盘监控直接相关，13 篇）

| 概念（wiki 文件） | 核心 | 对仪表盘增强的启示 |
|---|---|---|
| 状态机市场识别模型 | 波动率+趋势强度+成交量驱动有限状态（趋势/震荡/高波动/盘整） | L1 大盘状态标签＋判定依据 |
| 市场状态识别（10种）FMZ | 价格/均线/MACD/RSI/ATR/量 10 状态分类 | 状态粒度候选（Q1 拍板） |
| 情绪周期六段论（国盛2022） | 筑底→复苏→确认→冲顶→钟摆→探底（斜率一阶导） | L3 情绪阶段标签 |
| 财信证券三维情绪模型 | 期指升贴水/PCR（中高频）·主力资金热度（中频）·行业相关性 0.83 警戒（低频） | 多频情绪监控框架 |
| 情绪综合评分模型 | 涨停生态0.3+BOCIASI 0.2+量价0.2+资金0.15+波动0.15 → 仓位映射 | ⚠️ 权重纯经验**未回测验证**，仅可作参考提示 |
| 市场状态感知因子 / 状态依赖加权法 | 个股信号×市场状态耦合；权重随环境动态 | L1 状态→后续可做信号过滤 |
| 板块轮动（陈秋明） | 先判行情性质→判主线板块→锁个股；牛/熊/震荡不同板块选择 | L4 板块轮动状态输出 |
| 缠中说禅板块强弱指标 | 板块内个股均线状态占比（女上位/男上位/吻） | L4 板块强度口径 |
| 比价效应 | 龙头先行→二线跟涨→估值趋同 | L4 领涨股/轮动节奏 |
| 关键交易日识别与验证框架 / 共振冰点 | 90%收益来自2%交易日；冰点+慢线极值→关键上涨日概率↑；快线须慢线确认 | L5 预警信号（冰点→关键上涨窗口） |
| 快线+慢线双通道状态识别 | 单日8状态(快)+5日频率(慢)+市场背景过滤 | 与已有 BOCIASI/447 阶段双源对齐 |
| 蜡烛情绪指数（CEI） | 犹豫/恐惧/贪婪三振荡器 | L3 微观情绪候选 |
| 情绪拥挤度因子 | 融资余额增长率−股价涨幅背离 | L5 顶部风险提示 |

## 四、增强能力规划（分层：展示 → 状态 → 预警/建议）

- **L1 大盘状态概览（增强①）**：头部加「市场状态」标签（趋势/震荡/高波动/盘整）+ 一句依据。数据源＝`market_stats_cache`（ma20_ratio/limit_ratio 等已实证）+ BenchmarkService（481 `_index_trend_sentence` 同源）。
- **L2 市场宽度面板（新增，落 ⑧ 空位）**：上涨/下跌/平盘家数、涨停/跌停家数、MA20占比、涨停比例。数据源＝`daily_cache ⋈ daily_basic_cache`（已实证可算）+ `market_stats_cache`。
- **L3 市场情绪温度计（新增）**：六段论阶段+温度+BOCIASI 状态。数据源＝`market_stats_cache` 全字段（447 dim5 温度7入参同源）；综合分→仓位建议仅作参考（权重未验证）。
- **L4 板块轮动监控（增强⑥⑦）**：板块卡补 up/down 家数、领涨股、热度/排名。数据源＝`sector_heat_cache`（已实证）＋盘中 `mem_store.get_sectors()`（内存，库表缺失见 §五 E4）。
- **L5 监控跟进输出（新增）**：预警型提示（冰点+慢线极值→关键上涨窗口；拥挤背离→顶部；宽度极端→反转；状态切换→风控）＋建议型（今日关注主线=板块热度Top+领涨股；仓位参考标注未验证）。落头部状态条 + ⑧ 空位，不新增页面，符合建议输出型定位。
- **L6 远期（可选）**：关键交易日日历标记；期指升贴水/PCR（需数据源评估）。

## 五、数据源逐项实证（2026-10-19 只读）

> 方法：`sqlite3`/`duckdb` 以 `read_only` 打开 `data/duckdb/*.db`（8 个库文件实测为 **SQLite 3.x 格式**）+ 运行中 API `:5001` 实取。全部只读，未写任何表。

| # | 数据源（库/表） | 实证结果 | 结论 |
|---|---|---|---|
| E1 | `compute_cache.db / sector_heat_cache` | 最新 `stat_date=2026-10-16` 全行业：`heat_level/strength/rank/stock_count` 齐全（样本：出版业 top_10/0.862/rank1/29 只；路桥/影视音像/啤酒/铁路…） | ✅ **可用**（L4 板块热度） |
| E2 | `compute_cache.db / market_stats_cache` | 最新 `stat_date=2026-10-16`：`ma20_ratio=0.164 / turnover_percentile=0.972 / limit_ratio=5.25 / rsi_percentile=0.309 / erp_percentile=0.048 / margin_trend=0.278 / pe_percentile=1.0`；连续 3 日（10-14/15/16）有值 | ✅ **可用**（L1 状态/L2 宽度/L3 温度原料） |
| E3 | `market_cache.db / daily_cache ⋈ daily_basic_cache` | 10-16 `daily_cache` 共 5602 行（含 36 指数）；纯股票 join=**5566**：涨 **3300** / 跌 **2128** / 平 **138**；`max_pct=30.0 / min_pct=-29.97` | ✅ **涨跌家数可算**（L2 市场宽度） |
| E4 | `as_sector_ranking`（全库） | **8 个库 SHOW TABLES 均无此表**（market_snapshot.db 仅 `as_market_snapshot`）；代码有建表(:828)/写入(:2170)/读取(:3083)，`akshare_collector._collect_sector_and_limit` 调 `write_as_sector_ranking`，但库表当前**不存在** | ❌ **库表缺失**（「仍活跃写入」注释与实际不符）；盘中板块排名实走**内存** `mem_store.update_sectors/get_sectors`（不落库） |
| E5 | `market_snapshot.db / as_market_snapshot` | 表存在 5229 行，但 `cached_at=2026-09-09`（**陈旧**）；代码注释「已停止写入」 | ⚠️ 盘中实时数据源在 `in_memory_store`（mootdx TCP→store），**非此表** |
| E6 | 运行中 API `market/overview` | `data_is_live=False / data_date=2026-10-16 / market_status=closed / 4 指数` | ⚠️ 当前（盘后）无实时快照→回退日线缓存（与 516 P4 一致）；**盘中实时链路待交易时段复验** |
| E7 | 路由层（`routes/*.py`） | grep `market/state|breadth|emotion|temperature|status` **无匹配** | ⚠️ **无现成市场级监控接口**（L1/L2/L3 需新增只读接口，数据源已实证 E1/E2/E3） |

**实证小结**：L1/L2/L3 的原料数据（`market_stats_cache`/`sector_heat_cache`/涨跌家数）**已实证存在且最新**；**唯一缺口**＝无市场级只读接口（需按 523 先例逐项拍板新增）+ **as_sector_ranking 库表缺失**（L4 若走库表需先补建，或直接读内存 `mem_store`）。

## 六、分级归并

| 级别 | 项 | 说明 |
|---|---|---|
| 🟢 数据已实证、可直接规划 | **L1 大盘状态**（E2）、**L2 市场宽度**（E3）、**L3 情绪温度**（E2/E7 需接口） | 原料数据在库，缺市场级只读接口 |
| 🟠 数据源待修/待确认 | **L4 as_sector_ranking 表缺失**（E4）→ 补建表或改读内存；**盘中实时链路**（E6）待交易时段复验 | 影响 L4/L1 盘中体验 |
| 🟡 待业务拍板 | 状态粒度/情绪口径/预警形式/⑧ 空位用途/接口范围（§七 Q1~Q6） | 全部需拍板后分批实施 |

## 七、待拍板（Q 列表，首项为建议）

- **Q1** 大盘状态分类粒度：4 状态（状态机模型）vs 牛/熊/震荡（板块轮动口径）vs 10 种（FMZ）；
- **Q2** 情绪面板口径：六段论阶段 vs BOCIASI 快慢线 vs 综合评分（未验证权重如何标注）；
- **Q3** 预警输出形式：状态条徽标 vs 面板列表 vs 仅数据不做预警；
- **Q4** 板块模块是否改接真实字段：补 `as_sector_ranking` 库表（E4）or 改读内存 `mem_store.get_sectors()` or 维持现状；
- **Q5** ⑧ 空位面板是否改造为「大盘状态+预警」面板；
- **Q6** 新增哪些只读接口（L1 状态 / L2 宽度 / L3 情绪），逐项按 523 先例拍板。

## 八、批次建议（拍板后）

- **批次1（纯前端，零后端）**：⑧ 空位改「市场宽度」面板（数据源 E3 涨跌家数——但需后端接口，见下）；若纯前端则先做「空态/占位+定时轮询」骨架。
- **批次1'（后端只读接口，523 先例）**：新增 `market/state`（E2 状态+E3 宽度聚合）与 `market/breadth`（E3 涨跌家数）——各含测试 + 真实库冒烟。
- **批次2**：前端 L1 状态条 + L2 宽度面板接线（轮询 `dashboard/full` 聚合或独立请求）。
- **批次3**：L3 情绪温度计（依赖 dim5 市场级输出是否现成，需先实证）＋ L4 板块热度（E1）。
- **批次4**：L5 预警提示（冰点/拥挤/宽度极端/状态切换），标注「建议型、非强制」。

## 九、只读核对命令（复核用）

```bash
# 库格式与表清单
file data/duckdb/*.db
sqlite3 "file:data/duckdb/market_snapshot.db?mode=ro" "SELECT name FROM sqlite_master WHERE type='table';"
# E1 板块热度
sqlite3 "file:data/duckdb/compute_cache.db?mode=ro" "SELECT stat_date,industry,heat_level,strength,rank,stock_count FROM sector_heat_cache WHERE stat_date=(SELECT MAX(stat_date) FROM sector_heat_cache) ORDER BY rank LIMIT 8;"
# E2 全市场统计
sqlite3 "file:data/duckdb/compute_cache.db?mode=ro" "SELECT stat_date,ma20_ratio,turnover_percentile,limit_ratio,rsi_percentile,erp_percentile,margin_trend,pe_percentile FROM market_stats_cache ORDER BY stat_date DESC LIMIT 3;"
# E3 涨跌家数（纯股票，523 同款 join 排除指数）
sqlite3 "file:data/duckdb/market_cache.db?mode=ro" "SELECT d.trade_date,count(*) n,sum(d.pct_chg>0) up,sum(d.pct_chg<0) down,sum(d.pct_chg=0) flat,max(d.pct_chg) maxp,min(d.pct_chg) minp FROM daily_cache d JOIN daily_basic_cache b ON d.ts_code=b.ts_code AND d.trade_date=b.trade_date WHERE d.trade_date=(SELECT MAX(trade_date) FROM daily_cache) GROUP BY d.trade_date;"
# E6 盘中状态（运行中 API）
curl -s http://127.0.0.1:5001/api/v3/market/overview | python -m json.tool | head -30
```

## 十、拍板结论（2026-10-19，用户逐项拍板 Q1~Q6）

| # | 议题 | 拍板 |
|---|---|---|
| Q1 | 大盘状态粒度 | **4 状态·状态机**（趋势/震荡/高波动/盘整；wiki《状态机市场识别模型》依据，判定因子在库数据可得） |
| Q2 | 情绪面板口径 | **六段论 + BOCIASI**（复用 dim5 已有实现——447 已对齐六段论、阶段双源、BOCIASI 状态；零新增引擎） |
| Q3 | 预警输出形式 | **徽标 + 面板列表**（头部状态条轻量徽标 + ⑧ 面板明细；建议输出型，不弹窗不强推） |
| Q4 | 板块数据源 | **补建库表对齐写路径**（`as_sector_ranking` 建表错库→静默失败；于快照库建表路径对齐后落库，前端读 up/down/lead；需 daemon 重启） |
| Q5 | ⑧ 空位用途 | **改造为大盘状态+预警面板**（L1 状态 + L2 宽度 + L3 情绪 + L5 预警汇集一处） |
| Q6 | 接口范围 | **market/breadth + market/state + market/emotion + 并入 dashboard/full（全选）**；emotion 实现前先实证 dim5 市场级输出是否现成 |

## 十一、实施计划（批次划分，待用户指示开工）

- **批次1'（后端只读接口，523 先例）**：`market/breadth`（E3 涨跌家数 + E2 宽度指标）、`market/state`（E2 + BenchmarkService 趋势句 → 4 状态 + 判定依据）；`market/emotion` 先只读实证 dim5 市场级输出现成度再定实现；三接口均**并入 `dashboard/full` 聚合载荷**（Q6 全选）；各含测试 + 真实库冒烟。
- **批次1（Q4 板块数据源）**：`as_sector_ranking` 建表归属修正（快照库建表路径对齐）+ 验证 `akshare_collector` 30min 覆盖式写入落库；需 daemon 重启生效。
- **批次2（前端 L1/L2/L5 骨架）**：头部状态条接入 `market/state`（徽标）＋ ⑧ 空位改「大盘状态+预警」面板（`market/breadth` 宽度数据 + 预警列表占位）。
- **批次3（前端 L3/L4）**：情绪温度计（`market/emotion`）＋ 板块卡增强（`sector_heat_cache` 热度/排名 + `as_sector_ranking` up/down/lead）。
- **批次4（L5 预警逻辑）**：冰点+慢线极值→关键上涨窗口 / 拥挤背离→顶部 / 宽度极端→反转 / 状态切换→风控 四条规则 + 建议输出（标注「建议型、非强制」，495 B1）。

## 十二、护栏（实施全程）

1. **§13 数据真实性**：状态/宽度/情绪一律真实数据，不造代理值（516 Q6 先例）。
2. **前端阶段规则**：仅展示层；后端改动仅限**只读接口**（523 先例逐项明示）；不改现有 8 区块数据契约。
3. **建议输出型**：预警/建议仅提示不强制（495 B1）。
4. **不回归**：513/514/516/523 已处置项不重做；定向测试 + 全量回归（须先停 daemon）。
5. **验证**：后端定向 pytest + 真实库冒烟；前端渲染由用户起服目检。

## 十三、页面布局说明（2026-10-19 用户询问「页面布局是如何设计的」后补充）

### 13.1 布局框架（全局统一，166 号文档）
- `app-layout`＝左侧 `sidebar`（默认折叠 64px、可展开 200px：概览/分析/验证/管理/系统 五组导航）+ 右侧 `main-content`；全站 14 页共用，仪表盘为默认激活页。
- 技术栈：原生 HTML5 + CSS3 + 原生 JS + ECharts 5.4.3 + socket.io（实时预留）。

### 13.2 当前布局（自上而下 8 区块，2026-10-19 现状）

```
┌─ ① 页头 page-header ─────────────────────────────────────┐
│  📊 仪表盘    ● 状态点 · 更新时间 · 成交额 ¥xxxx亿 ↑x.x% │
├─ ② 四大指数卡片 index-grid（4 列，各带 20 日 miniK）──────┤
│  [上证指数 000001.SH] [深证成指 399001.SZ]               │
│  [北证50 899050.BJ]   [创业板指 399006.SZ]               │
├─ ③ 四大指数合计成交额（近20日）— 全宽柱状图 ──────────────┤
│  #volume-chart（260px，红涨绿跌）                         │
├─ ④ 全市场资金流向趋势（近20日）— 全宽 ───────────────────┤
│  #chart-fund-flow（主力净流入柱 + 散户净流入折线）         │
├─ ⑤ 全市场日终散点 ×2（523 新增，grid-2 双列）────────────┤
│  [流通市值×涨跌幅 对数散点] [开高低收四象限 4 色]         │
├─ ⑥ 行业板块净流入排行 │ Top5 板块·个股净流入/流出 ────────┤
│  [sector-inflow-chart]  [流入卡片][流出卡片]              │
├─ ⑦ 行业板块涨跌幅 │ 涨幅前十/跌幅前十 │ ⑧空位 ───────────┤
│  [chart-sector]      [gainers-table Tab切换]  [空位占位]  │
└───────────────────────────────────────────────────────────┘
```

| 区块 | 取数接口 | 说明 |
|---|---|---|
| ① 页头 | `market/overview` | 状态点（绿=实时/灰=盘后·数据日，516 Q4）、成交额+环比 |
| ② 指数卡 | overview.indexes | 4 指数 price/change_pct + miniK（20 日 candlestick） |
| ③ 成交额 | `market/index-daily` | 4 指数 amount 求和（含成分重叠口径已标注） |
| ④ 资金流向 | `market/moneyflow-summary` | 主力/散户净流入（散户符号已统一） |
| ⑤ 日终散点 | `market/eod-snapshot` | 5566 只；Part1 对数轴 + Part2 四象限（自定义平移/缩放） |
| ⑥ 板块资金 | `market/sector-moneyflow` | 净流入排行 + Top5 个股（P1 符号已修） |
| ⑦ 板块涨跌 | `market/sector-sector` + `daily-top` | 涨跌幅条形 + 涨幅/跌幅前十（Mock 已删走空态） |
| ⑧ 空位 | — | 原「策略信号汇总」伪信号移除 + AI 雷达下线（516 Q2）后的占位 |

**响应式**：≤1100px 指数卡 2 列、grid-2 单列；≤700px 全单列、指数数值缩小。

### 13.3 166 号规范布局演进（对照）
166 §3.1~3.6：第三张卡 沪深300→**北证50**、第四张 成交额→**创业板指**、成交额移至页头、各卡内嵌 20 日 miniK、新增成交额柱状图、AI 雷达轮播条、策略信号汇总改接 Screener L3。当前差异仅两处（均有据）：AI 雷达已取消（516 Q2）、策略信号汇总已移空（166 §3.4 确认路由不存在→伪信号，2026-08-04 移除）。

### 13.4 524 规划后目标布局（L1~L6 增强版）
- **L1 大盘状态概览**（增强①）：页头加「市场状态」徽标（趋势/震荡/高波动/盘整）+ 判定依据；数据源 `market/state`（E2 + BenchmarkService 趋势句）。
- **L2 市场宽度面板**（落⑧空位）：上涨/下跌/平盘家数、涨停/跌停家数、MA20占比、涨停比例；数据源 `market/breadth`（E3 + E2）。
- **L3 市场情绪温度计**（落⑧空位）：六段论阶段 + BOCIASI 状态 + 市场温度；数据源 `market/emotion`（`MarketSentimentService` 六段论 + `market_level_temperature`）。
- **L4 板块轮动监控**（增强⑥⑦）：板块卡补 涨跌家数/领涨股/热度排名；数据源 `sector_heat_cache`（E1）+ `as_sector_ranking`（E4 需补建库表，批次1）。
- **L5 预警输出**（①徽标 + ⑧列表）：冰点→关键上涨窗口 / 拥挤背离→顶部 / 宽度极端→反转 / 状态切换→风控；建议型非强制（495 B1）。
- **L6 远期**：关键交易日日历标记、期指升贴水/PCR（需数据源评估）。

**设计要点**：新功能全部复用现有 8 区块位置（①增强 + ⑧空位启用），**不新增页面、不改既有区块数据契约**；后端仅新增 3 个只读接口并入 `dashboard/full` 聚合；符合前端阶段「仅展示层 + 523 只读接口先例」与「建议输出型」定位。

## 十四、批次1' 已实施（2026-10-19，后端只读接口）

**范围**：`backend/app/services/dashboard_service.py` + `backend/app/routes/dashboard.py` + `backend/tests/test_524_market_breadth_state_emotion.py`；**仅只读接口，未触前端/写路径/配置**。

### 14.1 `DashboardService.get_market_breadth`（L2 市场宽度原料）
- `daily_cache⋈daily_basic_cache`（最新交易日，inner join 天然排除指数）→ `{trade_date, count, up_count, down_count, flat_count, up_ratio, down_ratio}`；叠加 `market_stats_cache`（E2）→ `ma20_ratio`（×100 百分比）/`limit_ratio`/`turnover_percentile`（×100）。
- 真实库实测（2026-10-16）：`count=5566 / up=3300 / down=2128 / flat=138 / ma20_ratio=16.4 / limit_ratio=5.25`。

### 14.2 `DashboardService.get_market_state`（L1 大盘状态，4 状态·状态机）
- 数据源：`market_stats_cache`（turnover_percentile/limit_ratio）+ `BenchmarkService.get_index_daily(HS300)` 近 60 日（481 趋势句同源）。
- 判定（阈值可拍板调整）：高波动 `turnover≥0.85 且 |ret20|≥5%`；上升趋势 `ret20≥3% 且 close≥ma60`；下降趋势 `ret20≤-3% 且 close≤ma60`；盘整 `|ret20|<2% 且 turnover<0.4`；其余震荡。
- 输出：`{state, state_label, data_date, basis:{hs300_ret_20d/60d/close/ma60/turnover_percentile/limit_ratio}, source}`；⚠️ 冒烟发现 `round(np.float64)` 不可 JSON 序列化 → 已修 `float(round(...))`。
- 真实库实测（2026-10-16）：`high_volatility 高波动`（hs300 ret20=-8.79 / ret60=-12.87 / close=4170.6 < ma60=4547.1 / turnover=97.2）。

### 14.3 `DashboardService.get_market_emotion`（L3 情绪温度计原料）
- 复用 `MarketSentimentService.get_sentiment_phase`（273a 方案，`sentiment_pool_cache` → 六段论映射，**零新增引擎**）。
- 输出：`{phase, phase_label, metrics:{limit_up_count, limit_down_count, max_board_height, sealing_rate, up_down_ratio}, data_available, source}`。
- 真实库实测（2026-10-19 盘中）：`ferment 情绪发酵`（limit_up=61 / limit_down=10 / max_board=11 / sealing=55.5 / ratio=6.1）。
- ⚠️ **登记**：BOCIASI **市场级**聚合输出无现成实现（dim5 BOCIASI 为个股级）→ `market/emotion` 本期先出六段论；批次3 前端如需 BOCIASI 徽标需先建市场级聚合（另立小号或并入批次3）。

### 14.4 路由 + 聚合并入
- 新增 `GET /api/v3/market/breadth`、`/api/v3/market/state`、`/api/v3/market/emotion`（均 `@api_cache(ttl=120)` + `@handle_exceptions` + `_data_response` 503 兜底，523 模式）。
- `get_dashboard_full` 并入 `market_breadth` / `market_state` / `market_emotion` 三键（Q6 全选）。

### 14.5 测试与验证
- `tests/test_524_market_breadth_state_emotion.py`（9 用例：breadth 计数/比率/空态、state 上升趋势/默认/无指数兜底、emotion 六段论/空数据兜底、路由注册、dashboard/full 并入）——**9 passed**。
- 相邻回归（523 eod-snapshot 4 + 516 batch2/3 6 + 513 选日 5 + 524 9）**24 passed**；py_compile OK、ruff 三文件全过（测试 I001 import 排序已 fix）。
- **真实库只读冒烟（app_context）**：三接口全取数成功且 **JSON 可序列化**（np.float64 修复后 basis 全原生 float）；`breadth=2026-10-16/5566`、`state=high_volatility`、`emotion=ferment`。
- **前端渲染**：待用户起服（start.command）后浏览器目检（批次2 前端接线时一并复核）。

## 十五、批次1 已实施（2026-10-19，Q4 板块数据源：`as_sector_ranking` 建表归属修正）

**范围**：`backend/app/data/enhanced_cache_manager.py` + `backend/tests/test_524_batch1_sector_ranking.py`；**仅库表归属/读写路径修复，未触业务引擎/前端**。

### 15.1 根因链（实证）
`as_sector_ranking` 表在全部 8 个库**均不存在**（E4）。根因链：
1. **建表位置错**：建表语句在主库段 `_init_tables`（`enhanced_cache_manager.py:828` 附近，`self._execute`→总库）；而本表经 sharding 路由到 **market_snapshot.db**（快照库，`sharding_manager` 已登记）。
2. **426 空壳自清理 DROP**：`_init_tables` 末尾「总库空壳表自清理」（`:1337`）对「路由到分库且总库 0 行」的表一律 DROP → 每次启动主库建的空壳 `as_sector_ranking` 立即被删（日志实证：`DROP 34 张 [..., 'as_sector_ranking', ...]`）。
3. **快照库从未建表**：`_init_snapshot_tables`（`:1362`）只建 `as_market_snapshot`，**未建 as_sector_ranking** → market_snapshot.db 无此表。
4. **写静默丢**：`write_as_sector_ranking` → `_insert_from_df` → 分库路由 market_snapshot.db → 表不存在 → 自动建表依赖「从总库复制结构」（`main_sql`）→ 总库表也被 DROP → 建表失败 → `shard_cols` 空 → `logger.warning("分库表不存在且自动建表失败...跳过写入")` → 返回 0。且 `akshare_collector` 调它被 `except: pass` 吞 → **写全静默丢**。
5. **读恒空（499 同型）**：`read_as_sector_ranking`（`:3083`）用 `self.read_conn`（**总库连接**）读快照库表 → 即使表在快照库也读空；消费方 `akshare_reader.get_sector_rankings` 降级路径恒 `[]`。

### 15.2 修复（3 处，对齐 as_market_snapshot 家族「snapshot_conn 单路径」，426 S7/D5）
1. **建表归属**：`_init_snapshot_tables` 补建 `as_sector_ranking`（快照库，与 `as_market_snapshot` 并列；`sector_name PK / ts_code / change_pct / up_count / down_count / lead_ts_code / lead_name / lead_change_pct / updated_at`）。
2. **读路径**：`read_as_sector_ranking` 改走 `self.snapshot_conn`（修复 499 同型「分库表走总库连接读取」）。
3. **写路径**：`write_as_sector_ranking` 加 `sector_code → ts_code` 列映射（akshare `板块代码` 对齐表结构 `ts_code` 列；price/volume/amount/rank 由 `_insert_from_df` 按表列过滤）。

### 15.3 测试与验证
- `tests/test_524_batch1_sector_ranking.py`（5 用例：快照库建表存在 / 表结构含 L4 字段 / 写读闭环（sector_code→ts_code + up/down）/ read 走 snapshot_conn 源码断言 / concept 恒空未复活）——**5 passed**；+ `test_426_phase5_fix.py` 4 回归 = **9 passed**。
- py_compile OK；ruff：测试文件全过，`enhanced_cache_manager.py` 3 处 E702（`:1829/1831/1833` 分号）为 **既有基线**（git show HEAD 同款写法，非本次引入）。
- **真实库只读冒烟（app_context）**：修复后 ECM 初始化即在快照库建出 `as_sector_ranking`（表存在=True，列 9 项齐）；`read_as_sector_ranking(top_n=5)` 正常返回 `[]`（空表不报错）；**写入落库待 daemon 重启后由 akshare_collector 30min 覆盖式任务实证**（行数>0 断言留批次1 实机）。
- **需 daemon 重启生效**（加载新建表/读路径/写映射代码；按 daemon-stop-policy：EOD 运行期不为加载修复重启，今日 EOD 后或用户确认时重启）。

### 15.4 遗留
- `as_sector_ranking` 写入数据质量（lead_* 字段 akshare 采集未填充 → 恒空；513 #D5 同因）留 L4 前端接线时评估是否补采集。
- 主库段 `_init_tables` 原 as_sector_ranking 建表（:828）保留（空壳被自清理 DROP 无害，避免动主库段影响面）；如需彻底移除可另立小号。

## 十六、批次2 已实施（2026-10-19，前端 L1/L2/L5 骨架）

**范围**：`_ui-prototype/dashboard.html`（前端展示层，前端阶段规则）；**未触后端/依赖/配置**。

### 16.1 L1 大盘状态概览（增强① 页头）
- 页头 `page-header-actions` 新增 `#market-state-badge`（`market/state` 4 状态·状态机徽标）——色点 + 「大盘状态 {label}」：`trend_up` 红 / `trend_down` 绿 / `high_volatility` 橙 / 其余中性灰；`title` 附数据日 + source。
- `#market-state-line` 状态行：label + 判定依据（`basis`：沪深300 近20日/近60日涨跌、收盘 vs 60日线站上/跌破、换手分位、涨停比例）。
- `#market-state-date` 显示数据日。

### 16.2 L2 市场宽度面板（落 ⑧ 空位）
- ⑧ 空位（原「策略信号汇总」占位）改为「🛰️ 大盘状态」面板：状态行 + **市场宽度**（`market/breadth`）——上涨/下跌/平盘家数三栏 + 上涨/下跌占比 + MA20占比/涨停比例/换手分位 + 数据日/总数；**预警**区块（L5 骨架：暂无预警占位，规则批次4 落地：冰点/拥挤/宽度极端/状态切换）。

### 16.3 接线
- `loadDashboardFull` 成功路径消费 `dd.market_state` → `applyMarketState`、`dd.market_breadth` → `applyMarketBreadth`（Q6 聚合并入生效）。
- 降级 catch 补 `loadMarketState()` / `loadMarketBreadth()`（独立请求，`_cachedFetch` TTL 120s）。
- 空态兜底：接口失败静默（console.warn），面板保持「加载中/暂无预警」占位（§13 不造假数据）。

### 16.4 验证
- 内联 JS `node --check` 通过（提取 2 个 script 块 34KB）。
- **浏览器渲染待用户起服目检**（start.command + 强刷 Cmd+Shift+R；预期检查点：页头状态徽标显示「大盘状态 高波动」、⑧ 面板显示涨跌家数与宽度指标、预警区占位）。

### 16.5 遗留
- L5 预警规则（四条）批次4 落地；L3 情绪温度计 + L4 板块卡增强批次3 落地。
- `market/emotion` 已并入 `dashboard/full` 但前端尚未消费（批次3 接线）。

## 十七、批次3 已实施（2026-10-19，前端 L3 情绪温度计 + L4 板块热度；拍板：新增 `market/sector-heat` 接口）

**范围**：`backend/app/services/dashboard_service.py` + `backend/app/routes/dashboard.py` + `_ui-prototype/dashboard.html` + `backend/tests/test_524_batch3_sector_heat.py`；**后端仅新增 1 只读接口（523 先例拍板），前端限展示层**。

### 17.1 后端：`get_sector_heat` + 路由 + 聚合并入
- `DashboardService.get_sector_heat(top_n=8)`（读 `sector_heat_cache` 最新日全行业，E1 实证 10-16 109 行业）→ `{date, count, source, sectors:[{industry, heat_level, strength, rank, stock_count}]}`（rank 升序、跳过无效行业名、rank=999 兜底）。
- 路由 `GET /api/v3/market/sector-heat`（523 模式：`@api_cache(ttl=120)` + `@handle_exceptions` + `_data_response` 503 兜底）。
- `get_dashboard_full` 并入 `sector_heat` 键（Q6 全选扩展——本批拍板新增）。

### 17.2 前端 L3：市场情绪温度计（并入⑧面板）
- ⑧「🛰️ 大盘状态」面板加「😊 市场情绪」区块（`#market-emotion-panel`）——`dd.market_emotion`：六段论 `phase_label` + 涨停生态（涨停/跌停/最高连板/封板率/涨跌比）；色点：ice 绿（逆向机会）/ climax 红（风险）/ ebb 橙 / 其余灰。

### 17.3 前端 L4：板块热度 Top（⑥板块卡）
- ⑥「🏭 行业板块净流入排行」卡加「🔥 板块热度 Top」（`#sector-heat-panel` + `#sector-heat-date`）——`dd.sector_heat`：top8 行业 `rank + industry + stock_count + heat_level + strength`；色标：top_10 红 / top_20 橙 / 其余灰。

### 17.4 接线
- `loadDashboardFull` 成功路径消费 `dd.market_emotion` → `applyMarketEmotion`、`dd.sector_heat` → `applySectorHeat`；降级 catch 补 `loadMarketEmotion()` / `loadSectorHeat()`（`_cachedFetch` TTL 120s）；空态兜底静默（§13 不造假）。

### 17.5 验证
- `tests/test_524_batch3_sector_heat.py`（6 用例：rank 升序 / top_n 截断 / 无效行业跳过 / 无数据 None / 路由注册 / dashboard/full 并入）——**6 passed**；py_compile OK、ruff 三文件全过。
- **真实库只读冒烟（app_context）**：`sector_heat` 取数成功（date=2026-10-16、count=109、top3=出版业/路桥/影视音像 heat_level=top_10）；`dashboard/full` 含 `sector_heat` + `market_emotion`；JSON 可序列化。
- 内联 JS `node --check` 通过（2 个 script 块 36KB）。
- **浏览器渲染待用户起服目检**（start.command + 强刷；预期检查点：⑧ 面板「😊 市场情绪 情绪发酵」、⑥ 卡「🔥 板块热度 Top」出版业 top_10）。

### 17.6 遗留
- L5 预警规则（四条）批次4 落地（⑧ 面板预警区占位待填）。
- BOCIASI 市场级聚合无现成（dim5 个股级，批次3 未做 BOCIASI 徽标，已登记）——若前端需 BOCIASI 徽标另立小号建市场级聚合。
