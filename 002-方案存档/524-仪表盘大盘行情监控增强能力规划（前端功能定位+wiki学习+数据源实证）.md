# 524号｜仪表盘「大盘行情信息」板块 前端功能定位与监控增强能力规划（wiki 学习 + 数据源实证）

> **版本**：v1.0（2026-10-19 只读核查 + 能力规划；**未改任何代码/方案**）
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
