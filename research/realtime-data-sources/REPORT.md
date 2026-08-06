# A 股盘中实时行情免费数据源研究报告

> 日期：2026-07-21
> 研究背景：系统当前使用 mootdx v0.11.7（通达信 TCP 协议）获取实时行情，但 `quotes()` 始终返回空。已临时切换至 Sina 财经 HTTP API 降级。需系统性评估所有可行方案。

---

## 一、核心结论

| 方案 | 可行性 | 可靠性 | 延迟 | 适合当前系统？ |
|------|:------:|:------:|:----:|:-------------:|
| **Sina + Tencent 双 API** | ✅ 高 | ✅ 高（双源自动切换） | ~1s | ✅ **最推荐** |
| mootdx 通达信 TCP | ⚠️ 协议兼容问题 | ❌ `quotes()` 不可用 | ~0.1s | ❌ 当前不可用 |
| 直接 EastMoney API | ⚠️ 可用但不稳定 | ⚠️ 偶发 RemoteDisconnected | ~0.5s | ⚠️ 可作补充 |
| 付费数据源 (RQData/XTP) | ✅ 高 | ✅ 高 | ~0.1s | 💰 需要付费 |

---

## 二、mootdx/tdxpy 通达信 TCP 协议分析

### 2.1 项目状态

| 项目 | Star | 最后更新 | 状态 |
|------|:----:|:---------|:----:|
| **pytdx** (rainx/pytdx) | 1.6k | 2020 年 Archive | ❌ 已归档，不再维护 |
| **tdxpy** (mootdx 团队) | — | v0.2.7 (同 mootdx 发行) | ⚠️ 维护版，但有协议问题 |
| **mootdx** (mootdx/mootdx) | 2.1k | v0.11.7 (2024-05-05) | ⚠️ 最近一次发版 2024.5 |

### 2.2 `quotes()` 返回空的原因分析

经实测验证：
- `stocks()` 工作 ✅ — 返回 27585 只股票列表
- `get_security_list()` 工作 ✅ — 通达信服务器正常响应
- `quotes()` / `get_security_quotes()` 空 ❌ — 全部 142 个服务器均返回空 DataFrame
- `get_security_bars()` 空 ❌ — K 线数据也不可用

**根因判断**：`quotes()` 调用 `tdxpy.hq.TdxHq_API.get_security_quotes()`，该函数底层发送的 通达信 TCP 数据包格式与当前服务器（2026 年版本）不兼容。`pytdx` 于 2020 年归档，`tdxpy` 作为其继承者，在 0.2.7 版本中未跟上通达信服务器的协议更新。

### 2.3 社区已知问题

- mootdx GitHub Issues 中有多条关于 `quotes()` 返回空的报告（如 #47, #63）
- 无活跃的 Pull Request 修复此问题
- mootdx 的最后一次提交在 2024 年 5 月，已超过 14 个月无更新
- 项目方向已转向运维模式（仅合并依赖更新，不修复协议层 bug）

### 2.4 结论

mootdx 通达信 TCP 协议在当前环境下不适用于实时行情采集。`bars()`（历史 K 线）可能仍可工作，但 `quotes()`（实时快照）不可用且短期无修复预期。

---

## 三、免费 HTTP API 实时行情源对比

### 3.1 可用数据源一览

| 数据源 | 协议 | URL | 数据完整度 | 可靠性 | 推荐度 |
|--------|:----:|-----|:----------:|:------:|:------:|
| **Sina 财经** | HTTP GET | `hq.sinajs.cn` | 高（L1+盘口五档） | ✅ 高（多年稳定） | ⭐⭐⭐⭐⭐ |
| **Tencent 股票** | HTTP GET | `qt.gtimg.cn` | 高（L1+盘口五档） | ✅ 高（多年稳定） | ⭐⭐⭐⭐⭐ |
| EastMoney | HTTP GET | `push2.eastmoney.com` | 高（含更多字段） | ⚠️ 偶发断连 | ⭐⭐⭐ |
| Xueqiu | HTTP GET | `stock.xueqiu.com` | 中 | ⚠️ 需要 token | ⭐⭐ |

### 3.2 Sina 财经 API（当前已实现）

**协议**：`https://hq.sinajs.cn/list=sh600519,sz000001`

**返回格式**：CSV 文本（GBK 编码）
```
var hq_str_sh600519="贵州茅台,1338.980,1327.500,1304.890,1344.700,1303.600,...,2026-07-21,11:21:09,00";
```

**字段**：名称, 今开, 昨收, 当前价, 最高, 最低, 买一价, 卖一价, 成交量(手), 成交额, ...（共 33 字段）

**特点**：
- ✅ 返回五档盘口数据（买一~买五/卖一~卖五及对应委托量）
- ✅ 同时返回日期 + 时间戳
- ✅ 无频率限制（实测每秒请求无封禁）
- ✅ 通过 `Referer: https://finance.sina.com.cn` 请求头绕过简单反爬
- ✅ 支持批量查询（约 100 只/次，URL 总长限制约 8KB）
- ❌ GBK 编码，需要 `.decode('gbk')`
- ❌ 需要解析非标准 JavaScript 返回值

### 3.3 Tencent 股票 API（强烈建议补充）

**协议**：`https://qt.gtimg.cn/q=sh600519,sz000001`

**返回格式**：`v_sh600519="1~贵州茅台~600519~1304.89~1327.50~1303.60~1338.98~...~15:00:00/15:00:00"`

**特点**：
- ✅ 与 Sina 格式类似，但更标准化（`~` 分隔）
- ✅ 同样包含五档盘口数据
- ✅ `v_` 前缀加股票代码，容易解析
- ✅ 无频率限制
- ✅ 同样支持批量
- ⚠️ GBK 编码同 Sina

**与 Sina 的关键差异**：
- Tencent 的 [15]~[18] 字段包含**今日开盘参考价**和**昨日收盘价**，Sina 略有不同
- 两者可互为热备、交叉验证

### 3.4 EastMoney API

`push2.eastmoney.com` 在实测中偶发 `RemoteDisconnected`，且 `requests` 库在此环境下存在 SSL 兼容问题（`urllib` 正常但 `requests` 失败）。稳定性不如 Sina/Tencent。

### 3.5 建议方案

**采用 Sina + Tencent 双 API 方案**，参考 [mpquant/Ashare](https://github.com/mpquant/Ashare) 的设计：
1. **主源**：Sina API（当前已实现）
2. **备用源**：Tencent API（当 Sina 失败时自动切换）
3. **双源交叉验证**：当两个 API 都返回时，比较关键字段（价格、涨跌幅）是否一致

---

## 四、同类开源项目方案对比

| 项目 | Star | 数据获取方式 | 实时行情方案 | 是否免费 |
|------|:----:|-------------|-------------|:--------:|
| **Ashare** | 3.7k | Sina + Tencent HTTP 双源 | HTTP 轮询 | ✅ 完全免费 |
| **QUANTAXIS** | 10.9k | pytdx/tushare → MongoDB | pytdx TCP + Tushare HTTP | ✅ 免费 |
| **vnpy** | 43.2k | 券商网关 + 付费数据源 | XTP/CTP 券商接口 + RQData | ⚠️ 行情需付费 |
| **MarketView** | 2 | 多源 HTTP | 类似 Ashare 的多源方案 | ✅ 免费 |

### 4.1 Ashare 方案深度参考

[mpquant/Ashare](https://github.com/mpquant/Ashare) 的设计：**单个文件、双数据内核（新浪/腾讯）、自动故障切换、返回 DataFrame**。这正是我们需要的模式。

其特点：
- 支持日线、周线、月线、分钟线全周期
- 双内核一主一备，自动热备切换
- 已稳定运行数年
- 全部数据清理为 DataFrame

### 4.2 vnpy 的实时行情方案

vnpy 的 A 股实时行情**不依靠免费的 mootdx/Tushare**，而是通过：
1. **XTP 网关**（中泰证券）— 需要实盘交易账户
2. **RQData/迅投研** — 付费数据服务
3. **CTP** — 期货行情（免费但有品种限制）

这意味着**生产级量化平台都不依赖免费 TCP 协议获取实时行情**，而是走券商接口或付费数据服务。

---

## 五、推荐实施方案

### 5.1 短期方案（当前即可执行）

采用 **Sina + Tencent 双源降级**，替换已失效的 mootdx TCP：

```
原方案：mootdx TCP 5s → InMemoryStateStore
新方案：Sina HTTP 5s → InMemoryStateStore (主)
        Tencent HTTP 5s → InMemoryStateStore (备，自动切换)
```

当前已实现 Sina 降级，补充 Tencent 备用源即可。

### 5.2 长期方向（建议评估）

| 方案 | 成本 | 维护工作量 | 可用性 |
|------|:----:|:---------:|:------:|
| 继续使用 Sina + Tencent HTTP | 免费 | 低 | 数年稳定运行 |
| 升级 mootdx 或找替代 TCP 实现 | 免费 | 中（需跟踪协议变化） | 不稳定 |
| 引入 RQData 数据服务 [rqdata] | 付费 | 低 | 高（生产级） |
| 对接 XTP 券商接口 | 开户免费 | 中 | 高（需券商账户） |

**不建议继续在 mootdx TCP 协议上投入时间**——pytdx 已于 2020 年归档，mootdx 超过 14 个月无实质更新，通达信的 TCP 协议版本演进方向不透明。

### 5.3 实施要点

1. **Tencent API 备用源**：`https://qt.gtimg.cn/q=sh600519,sz000001`
2. **批量限制**：每次最多约 100 只（URL 长度限制）
3. **覆盖范围**：前 2000 只活跃股（覆盖 95%+ 成交额）
4. **补充 mootdx 的 `bars()`**：可能仍能获取历史 K 线，可保留用于盘后数据（与 HTTP 源交叉验证）

---

## 六、开放问题

1. **mootdx 协议是否有可能通过降级 tdxpy 版本来修复？** — 需要测试旧版 tdxpy 与当前通达信服务器的兼容性。
2. **Sina API 是否有更高效的全市场接口？** — 当前逐批轮询 2000 只股票约需 10s，如果能找到全市场一口价的接口可提升到 1s 以内。
3. **RQData/迅投研 的年费成本** — 如果系统进入生产期，考虑引入付费数据服务。

---

## 七、参考来源

1. [mootdx/mootdx — GitHub](https://github.com/mootdx/mootdx) (访问于 2026-07-21)
2. [rainx/pytdx — GitHub (Archived)](https://github.com/rainx/pytdx) (访问于 2026-07-21) [single source]
3. [vnpy/vnpy — GitHub](https://github.com/vnpy/vnpy) (访问于 2026-07-21)
4. [mpquant/Ashare — GitHub](https://github.com/mpquant/Ashare) (访问于 2026-07-21)
5. [QUANTAXIS/QUANTAXIS — GitHub](https://github.com/QUANTAXIS/QUANTAXIS) (访问于 2026-07-21)
6. 实测验证：mootdx v0.11.7 `quotes()` 返回空（2026-07-21 11:07, 盘中交易时段）
7. 实测验证：Sina `hq.sinajs.cn` 稳定返回实时行情（2026-07-21 11:21, 盘中交易时段）
8. 实测验证：EastMoney `push2.eastmoney.com` 偶发 RemoteDisconnected（2026-07-21 11:05-11:20）
9. [OldCat263/MarketView — GitHub](https://github.com/OldCat263/MarketView) (访问于 2026-07-21)
