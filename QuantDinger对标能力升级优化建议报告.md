# QuantDinger 对标能力升级优化建议报告

- 编制日期：2026-05-24
- 适用项目：A股股票分析决策支持系统
- 参考项目：[brokermr810/QuantDinger](https://github.com/brokermr810/QuantDinger)
- 报告定位：基于 QuantDinger 当前开源项目能力，提出本项目的能力升级路线；本项目明确定位为“策略输出与投研决策支持系统”，不涉及自动交易实施。

## 一、结论摘要

QuantDinger 的核心价值不只是 K 线界面，而是把“市场数据、Python 指标、策略开发、回测验证、AI 分析、Agent/MCP 接口、部署运维”整合成一套本地化量化操作系统。对本项目而言，最值得借鉴的是研究与验证闭环，而不是实盘交易闭环。

本项目应升级为：

1. A股策略研究工作台：支持指标编写、因子筛选、策略模板、图表叠加、信号解释。
2. 策略验证与报告中心：支持批量回测、参数寻优、稳健性评估、风险归因、策略输出报告。
3. AI 辅助投研系统：支持自然语言生成指标/策略草案、多角色分析、策略复盘、异常风险提示。
4. Agent/MCP 只读与仿真接口：允许外部 AI 工具读取行情、运行回测、生成报告，但不提供自动下单能力。

必须明确剔除：

- 不接入券商自动下单接口。
- 不实现无人值守交易执行。
- 不提供“AI 自动交易”“实盘托管”“自动调仓下单”等功能。
- 模拟交易仅用于策略评估、仓位建议和报告展示，不作为真实交易通道。

## 二、QuantDinger 核心能力拆解

### 2.1 产品定位

QuantDinger 在 README 中定义为 self-hosted、local-first 的 AI 量化平台，覆盖 AI 研究、Python 原生策略、回测和 live execution。其部署结构包含 Vue 前端、Flask API、PostgreSQL、Redis、外部 LLM、市场数据、券商/交易所、通知和支付等模块。

对本项目的启发：

- 保留“本地化部署 + 数据自主管理 + AI 辅助研究”的思想。
- 借鉴“策略开发到回测验证”的闭环。
- 删除或屏蔽“交易所/券商执行、订单、资金、支付”等与本项目边界不符的能力。

### 2.2 策略开发双模式

QuantDinger 策略开发指南将策略分为两类：

| 模式 | QuantDinger 用途 | 本项目建议 |
|------|------------------|------------|
| IndicatorStrategy | dataframe 指标/信号脚本、图表展示、信号型回测 | 重点采用，作为本项目策略输出主协议 |
| ScriptStrategy | on_init/on_bar 事件驱动、显式 buy/sell/close_position、用于执行型策略 | 不直接采用执行语义，可改造成“策略状态机仿真模式” |

建议本项目统一采用“信号输出协议”，而不是“交易执行协议”。

建议协议字段：

```json
{
  "strategy_name": "双均线趋势策略",
  "signal": "BUY | SELL | HOLD | WATCH",
  "confidence": 0.72,
  "entry_zone": [12.30, 12.80],
  "risk_line": 11.60,
  "target_zone": [14.20, 15.00],
  "position_suggestion": "10%-20%",
  "holding_period": "5-20个交易日",
  "evidence": ["MA5上穿MA20", "成交量放大", "行业强度排名提升"],
  "risk_notes": ["接近前高压力位", "若跌破风险线则信号失效"]
}
```

### 2.3 指标 IDE 与代码质量检查

QuantDinger 具备指标代码协议、参数注解、策略默认配置、代码质量检查能力。其 `indicator_code_quality.py` 会检查：

- 是否生成 `df['buy']` / `df['sell']`
- 是否有 `output` 字典
- 是否声明指标名称和描述
- 是否 `df = df.copy()`
- 是否存在未来函数，如 `shift(-N)`
- 是否存在 ndarray 错用 pandas 方法等常见错误

本项目当前已有指标 IDE 页面、因子系统和技术指标计算，但还缺少完整的“指标代码协议 + 静态检查 + 沙盒执行 + 保存加载 + 回测联动”闭环。

建议新增：

- `backend/app/services/indicator_contract.py`：定义指标输出协议。
- `backend/app/services/indicator_quality.py`：迁移并 A 股化代码质量检查。
- `backend/app/services/indicator_sandbox.py`：只允许 pandas/numpy 计算，禁止文件、网络、子进程。
- `backend/app/routes/indicator_ide.py`：提供验证、运行、保存、加载接口。

### 2.4 AI 实验与多轮优化

QuantDinger 的 experiment runner 包含市场状态识别、LLM 候选参数生成、批量回测、评分排序、样本外验证等流程。

本项目可改造为“策略输出优化器”：

1. 输入基础策略代码或模板。
2. 识别市场状态：趋势、震荡、高波动、低流动性等。
3. 生成多组参数候选。
4. 对候选参数批量回测。
5. 按收益、回撤、夏普、胜率、稳定性、换手率评分。
6. 输出最佳参数、适用市场、失效条件、风险说明。

重要边界：

- 输出的是“候选策略方案”和“策略评估报告”。
- 不输出真实交易指令。
- 不自动执行买卖。

### 2.5 Agent Gateway 与 MCP

QuantDinger 提供 `/api/agent/v1` 和 MCP server，面向 Cursor、Claude Code、Codex 等外部 AI 工具。其设计包含能力分级、Token、scope、paper_only、audit log、rate limit 等安全机制。

本项目可采用更保守的能力分级：

| 风险等级 | 能力 | 是否开放给 Agent/MCP |
|----------|------|----------------------|
| R | 读取股票、K线、指标、因子、报告 | 允许 |
| B | 运行回测、参数优化、生成策略报告 | 允许 |
| W | 保存策略模板、保存研究笔记 | 受控允许 |
| C | 修改真实凭证、外部交易账户 | 不提供 |
| T | 下单、撤单、调仓、自动交易 | 不提供 |

建议本项目 MCP 工具只包含：

- `get_stock_kline`
- `list_factors`
- `run_strategy_backtest`
- `evaluate_factor`
- `generate_strategy_report`
- `compare_strategy_versions`

不包含：

- `place_order`
- `cancel_order`
- `start_live_strategy`
- `set_broker_credentials`

## 三、本项目当前能力对标

### 3.1 已具备能力

| 能力 | 当前状态 | 说明 |
|------|----------|------|
| 数据层 | 已具备 | PostgreSQL + Redis + DuckDB + Tushare |
| 技术指标 | 已具备 | MA、MACD、RSI、KDJ、BOLL、VOL |
| 信号生成 | 已具备 | 单指标与多指标共振 |
| 因子库 | 已具备雏形 | Alpha101、GTJA、Qlib158、A股因子等 |
| 回测引擎 | 已具备基础版 | 当前更接近买入持有/简化因子回测 |
| 指标 IDE 前端 | 已具备雏形 | Vue2 + Vite + klinecharts |
| AI 分析 | 已具备模拟接口 | 当前多为 mock 分析 |
| 策略模板 | 已具备雏形 | SQLite 模板表与预置模板 |

### 3.2 主要差距

| 差距 | 影响 | 优先级 |
|------|------|--------|
| 缺少统一策略输出协议 | 前端、回测、AI、报告难以复用 | P0 |
| 回测引擎偏简化 | 策略有效性评估不足 | P0 |
| 指标代码缺少沙盒和质量检查 | 自定义策略风险高 | P1 |
| AI 分析结果未接真实数据 | 投研价值有限 | P1 |
| 策略模板仍偏“交易执行代码” | 与本项目非自动交易定位不一致 | P1 |
| Agent/MCP 尚无边界设计 | 后续 AI 集成容易越界 | P2 |
| 缺少策略报告导出 | 难以形成决策支持闭环 | P2 |

## 四、能力升级建议

### 4.1 建立“策略输出协议”作为系统核心

当前项目中很多模块仍使用 `BUY/SELL`、`buy/sell`、`context.buy()` 等交易化语义。建议统一调整为“策略建议语义”。

建议标准：

| 旧语义 | 新语义 |
|--------|--------|
| BUY | 看多/关注/建议建仓区间 |
| SELL | 看空/减仓/退出观察 |
| HOLD | 持有观察 |
| position_size | 建议仓位区间 |
| stop_loss | 风险线 |
| take_profit | 目标区间 |
| trade/order | 策略事件/模拟成交/回测记录 |

落地文件建议：

- `backend/app/schemas/strategy_output.py`
- `backend/app/services/strategy_output_service.py`
- `frontend/vue-project/src/services/strategyOutputService.js`

### 4.2 升级回测引擎为“策略验证引擎”

当前 `BacktestEngine` 能计算收益、回撤、夏普、胜率等指标，但缺少 A 股实际规则和策略事件建模。

建议增加：

- A股 T+1 约束。
- 涨跌停不可成交模拟。
- 手续费、印花税、滑点、最小交易单位。
- 调仓频率：日、周、月、自定义事件。
- 单标的与多标的组合回测。
- 基准对比：沪深300、中证500、行业指数。
- 样本内/样本外切分。
- 滚动窗口验证。
- 参数敏感性热力图。

输出不应是“下单记录”，而应是：

- 策略信号序列。
- 模拟成交假设。
- 权益曲线。
- 风险指标。
- 适用市场状态。
- 策略失效条件。

### 4.3 完善指标 IDE：从图表工具升级为研究工作台

建议参考 QuantDinger 的 IndicatorStrategy，但保留 A 股本地化。

新增能力：

1. 指标协议：`my_indicator_name`、`my_indicator_description`、`# @param`、`output`。
2. 可调参数面板：自动从 `# @param` 生成输入控件。
3. 指标质量检查：未来函数、空值、类型错误、未复制 df、缺少 buy/sell。
4. 图表展示：主图叠加、副图、B/S 标记、风险线、目标区间。
5. 策略建议面板：展示信号、置信度、证据链、风险提示。
6. 一键回测：当前指标参数直接进入回测验证。
7. 一键生成报告：把图表、信号、回测和 AI 分析整合为 Markdown/HTML。

### 4.4 把策略模板从“执行模板”改为“研究模板”

当前 `strategy_templates.py` 中模板使用 `initialize(context)`、`handle_bar(context, bar)`、`context.buy()`、`context.sell()`。这会把系统导向交易执行平台。

建议改成三类模板：

1. 指标型模板：输出指标曲线与信号点。
2. 选股型模板：输出候选股票池、排序、入选原因。
3. 组合型模板：输出仓位建议、风格暴露、风险约束。

示例模板应改为：

```python
my_strategy_name = "双均线趋势观察策略"
my_strategy_description = "用于识别趋势增强与减弱，不产生自动交易指令。"

# @param fast_ma int 5 短期均线
# @param slow_ma int 20 长期均线
# @param risk_buffer float 0.03 风险线缓冲

df = df.copy()
df["fast_ma"] = df["close"].rolling(fast_ma).mean()
df["slow_ma"] = df["close"].rolling(slow_ma).mean()

df["signal"] = "WATCH"
df.loc[df["fast_ma"] > df["slow_ma"], "signal"] = "BULLISH"
df.loc[df["fast_ma"] < df["slow_ma"], "signal"] = "BEARISH"

output = {
    "strategy_name": my_strategy_name,
    "signals": df[["trade_date", "signal"]].to_dict("records"),
    "plots": ["fast_ma", "slow_ma"],
    "risk_notes": ["信号仅用于观察和决策支持，不构成自动交易指令"]
}
```

### 4.5 建设 AI 策略研究流水线

建议借鉴 QuantDinger experiment runner，但将目标改为“策略解释与优化建议”。

推荐流程：

1. 用户选择策略模板或输入自然语言。
2. AI 生成指标/策略草案。
3. 代码质量检查与沙盒执行。
4. 回测与参数扫描。
5. AI 解释回测结果。
6. 生成策略建议报告。
7. 人工确认是否采纳。

报告中应强制包含：

- 策略逻辑。
- 数据范围。
- 参数配置。
- 回测假设。
- 关键指标。
- 风险暴露。
- 失效条件。
- 不构成自动交易指令声明。

### 4.6 建设“策略报告中心”

本项目的目标是策略输出支持，因此报告中心应成为核心功能。

建议支持：

- 单股票策略报告。
- 多股票筛选报告。
- 因子组合评估报告。
- 回测对比报告。
- 策略版本对比报告。
- AI 多角色投研报告。

报告格式：

- Markdown：便于归档。
- HTML：便于前端查看。
- PDF：便于分享。
- JSON：便于后续系统消费。

### 4.7 Agent/MCP 作为研究接口，不作为执行接口

建议新增 `backend/app/routes/agent_research.py` 或独立 MCP server，但只暴露研究能力。

建议工具清单：

| 工具名 | 功能 | 风险 |
|--------|------|------|
| `get_market_snapshot` | 获取股票快照 | 低 |
| `get_kline_data` | 获取K线 | 低 |
| `run_indicator` | 执行指标脚本 | 中，需要沙盒 |
| `run_backtest` | 运行回测 | 中，需要限流 |
| `evaluate_strategy` | 策略评分 | 中 |
| `generate_report` | 生成报告 | 低 |

禁止工具清单：

| 工具名 | 原因 |
|--------|------|
| `place_order` | 涉及真实交易执行 |
| `cancel_order` | 涉及真实订单管理 |
| `connect_broker` | 涉及券商凭证 |
| `start_live_bot` | 导向自动交易 |
| `rebalance_portfolio` | 可能被理解为真实调仓 |

## 五、非自动交易边界说明

本项目应在产品、API、代码和报告层面统一声明：

> 本系统为 A 股股票分析与策略决策支持系统，输出内容包括市场分析、策略信号、回测结果、风险提示和仓位建议。系统不连接券商交易接口，不自动下单，不自动撤单，不执行真实资金调仓。所有策略结果仅作为研究与决策参考，最终投资行为由用户自行判断和执行。

### 5.1 API 命名建议

避免：

- `/quick_trade`
- `/place_order`
- `/live_trading`
- `/broker_accounts`
- `/auto_execute`

推荐：

- `/strategy-advice`
- `/strategy-reports`
- `/simulation`
- `/backtests`
- `/risk-assessment`
- `/decision-support`

### 5.2 前端文案建议

避免：

- “买入”
- “卖出”
- “下单”
- “自动交易”
- “实盘运行”

推荐：

- “看多信号”
- “风险退出信号”
- “建议关注”
- “策略建议”
- “模拟验证”
- “人工决策参考”

### 5.3 数据库命名建议

当前可保留模拟交易表，但长期建议区分：

| 原命名 | 建议命名 |
|--------|----------|
| `PaperTrade` | `SimulationEvent` |
| `PortfolioHolding` | `SimulatedHolding` |
| `trade` | `simulation_event` |
| `order` | 不使用 |

## 六、实施路线图

### 阶段一：协议与边界统一（1-2周）

目标：先把系统方向从“交易执行”统一调整为“策略输出支持”。

任务：

1. 定义 `StrategyOutput` 标准结构。
2. 修改前端和报告中的交易化文案。
3. 梳理现有 API，标记模拟/研究/报告用途。
4. 将策略模板中的 `context.buy/sell` 改为信号输出模板。
5. 新增统一免责声明。

交付物：

- 策略输出协议文档。
- 策略建议 API 草案。
- 策略模板 v2。

### 阶段二：回测与策略验证升级（2-4周）

目标：让策略输出有可验证依据。

任务：

1. 增强 A 股回测假设：T+1、涨跌停、费用、滑点。
2. 支持多标的组合回测。
3. 支持参数扫描和样本外验证。
4. 输出回测报告 JSON + Markdown。
5. 前端回测页展示权益曲线、回撤、指标对比、交易假设。

交付物：

- 策略验证引擎 v1。
- 回测报告中心 v1。

### 阶段三：指标 IDE 与 AI 研究流水线（4-6周）

目标：形成“写指标 -> 验证 -> 解释 -> 报告”的闭环。

任务：

1. 实现指标协议解析。
2. 实现代码质量检查。
3. 实现沙盒执行。
4. AI 生成策略草案。
5. AI 解释回测与风险。
6. 策略版本管理。

交付物：

- 指标 IDE v2。
- AI 策略研究流水线 v1。

### 阶段四：Agent/MCP 研究接口（2-3周）

目标：让外部 AI 工具可以安全调用研究能力。

任务：

1. 设计研究型 Agent API。
2. 添加 token、scope、rate limit、audit log。
3. 提供 MCP 工具：读取、回测、报告。
4. 明确禁止交易类工具。

交付物：

- Research Agent Gateway v1。
- MCP research tools v1。

## 七、优先级建议

| 优先级 | 建议项 | 原因 |
|--------|--------|------|
| P0 | 策略输出协议 | 决定系统边界和所有模块对齐方式 |
| P0 | A股回测增强 | 策略建议必须可验证 |
| P1 | 指标代码质量检查 | 自定义策略必须控制风险 |
| P1 | 策略模板研究化 | 避免系统误导为交易执行工具 |
| P1 | AI 回测解释 | 提升决策支持价值 |
| P2 | 策略报告中心 | 提升沉淀和交付能力 |
| P2 | Agent/MCP 研究接口 | 支持后续 AI 工具生态 |
| P3 | 多用户/权限/审计 | 在团队化使用时再强化 |

## 八、参考资料

1. QuantDinger GitHub 仓库：https://github.com/brokermr810/QuantDinger
2. QuantDinger README：https://github.com/brokermr810/QuantDinger/blob/main/README.md
3. QuantDinger 策略开发指南：https://github.com/brokermr810/QuantDinger/blob/main/docs/STRATEGY_DEV_GUIDE_CN.md
4. QuantDinger 截面策略指南：https://github.com/brokermr810/QuantDinger/blob/main/docs/CROSS_SECTIONAL_STRATEGY_GUIDE_CN.md
5. QuantDinger Agent/MCP 文档：https://github.com/brokermr810/QuantDinger/tree/main/docs/agent
6. 本项目既有文档：`002-方案存档/068-QuantDinger指标IDE深度分析与A股项目修改方案评估.md`
7. 本项目既有文档：`002-方案存档/069-QuantDinger指标IDE完整移植方案.md`
8. 本项目既有文档：`002-方案存档/070-方案A执行报告-QuantDinger适配A股指标IDE.md`

## 九、最终建议

本项目不应完整复制 QuantDinger 的“交易操作系统”定位，而应吸收其研究链路和工程能力，升级为 A 股策略决策支持系统：

- 用 QuantDinger 的 IndicatorStrategy 思想升级指标 IDE。
- 用 QuantDinger 的实验流水线思想升级回测与参数优化。
- 用 QuantDinger 的 Agent Gateway/MCP 思想开放研究接口。
- 明确去除 live execution、quick trade、broker account、order management 等自动交易能力。

最终产品目标应是：

> 让用户更快地产生、验证、解释和沉淀 A 股策略观点，而不是让系统替用户自动交易。
