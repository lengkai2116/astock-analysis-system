---
title: 通达信数据源能力与替代性评估（TdxAiData + TCP 协议实测）
type: 评估报告
date: 2026-11-11
status: 只读评估完成，未改代码/未安装依赖/未购买 Key
---

# 通达信数据源能力与替代性评估（TdxAiData + TCP 协议实测）

> 评估时间：2026-11-11 07:20–07:55（盘前）
> 评估对象：通达信三条接入路径——`tqcenter`（客户端 RPC）、`tdxaidata`（tqserver，付费 Key）、`mootdx/tdxpy`（免费 TCP 协议）
> 对照基线：项目 2026-11-10 日终实测（沟通 092）与现行 Tushare / AKShare / 新浪腾讯东财 / mootdx 数据链路

---

## 一、结论（TL;DR）

1. **短期不能整体替代，但具备"分项替代 + 显著减痛"的价值。**
   - 免费 TCP（mootdx）当前**只能取股票列表、历史分时、财务快照、除权除息、板块清单/F10**；**日线/指数 K 线（bars/index）在所有实测主站均解析失败**，实时快照盘前为空，**不能承担日终主源**。
   - 付费 `tdxaidata`（tqserver）**能力面最完整**：K 线、财务 FN1~FN584、龙虎榜 GP02/08/09/17/18、两融 GP03/11/12/13、陆股通 GP06/07/SC02/20/40/42、ETF 份额 SC08/38、涨跌停 GP14/15/22/24/33/34 + `get_zdt_data`、涨跌家数 SC31、股本/复权/日历/分笔/竞价/实时订阅——**几乎覆盖当前 Tushare + AKShare 的全部日终数据类**。
   - **macOS 可行**：`tdxaidata 1.3.1` wheel 内自带 `libTdxAiData.dylib`（另含 .dll/.so），不依赖通达信客户端；`tqcenter` 文档仍只给 Windows 安装路径，**macOS 不可用**。
2. **最大未知是"数据更新时点"与"费用/配额"**：官方文档未给各数据集的当日可采时点（这正是本项目日终起跑的核心判据），也未公开积分价格；**必须先试用 Key 做 3~5 个交易日的首达探针**，才能判断能否把日终起跑从 16:00 提前。
3. **免费 TCP 侧有一个确定可修的稳定性缺陷**：`~/.mootdx/config.json` 的 `BESTIP.HQ` 仍是旧节点 `123.125.108.14`，该节点 `stocks()` 返回 `None` → 采集器每 5 分钟创建失败一次（11-09/11-10 各 49 次），全天降级新浪。改为主站健康检查 + 显式 server 列表即可消除，**不需要新增依赖**。
4. **建议路线**：P0 先修 mootdx 选点（零成本，恢复实时链路质量）→ P1 申请 TdxAiData 试用 Key，建只读并行探针（字段/覆盖/单位/首达时点）→ P2 仅迁移通过等价性验收的分项（优先涨停明细、两融、ETF、北向、龙虎榜、新股元数据），Tushare 保留为校验源。

---

## 二、本机可用性实测

### 2.1 三条路径现状

| 路径 | 依赖 | 本机状态 | 结论 |
|---|---|---|---|
| `tqcenter`（客户端 RPC） | 通达信终端 + `127.0.0.1:17709` | 未安装客户端、端口未监听、无 `PYPlugins` 目录 | ❌ 不可用（且文档仅 Windows） |
| `tdxaidata`（tqserver） | `pip install tdxaidata` + `TdxAiData.ini` 数据服务 Key | 包未安装、无 Key；PyPI 清华源有 **1.3.1**，wheel `py3-none-any` 4.3MB，内含 `libTdxAiData.dylib` | ⏳ 可落地，缺 Key |
| `mootdx` + `tdxpy`（免费 TCP） | 通达信行情主站 7709 | 已装 mootdx 0.11.7 / tdxpy 0.2.7（均为最新版） | ⚠️ 部分可用（见下） |

### 2.2 免费 TCP 实测矩阵（2026-11-11 07:35–07:50）

**主站连通性**（内置 38 台，逐台 2s 超时）：
- 仅 `110.41.147.114`（0.31s）、`124.70.199.56`（0.17s）可连；
- 其余深圳/上海/北京主站多为 2s 超时（本机网络环境相关，非永久结论）；
- `Quotes.factory()` 默认读 `~/.mootdx/config.json → BESTIP.HQ = 123.125.108.14`，该节点可连但 `stocks()` 返回 `None` → `TypeError: '>' not supported between 'NoneType' and 'int'`（mootdx `quotes.py:233`）。

**接口可用性**（显式指定 `110.41.147.114`）：

| 接口 | 结果 | 说明 |
|---|---|---|
| `stocks()` | ✅ 27,859 行 / 1.74s | 股票列表可用 |
| `minutes(symbol, date)` | ✅ 240 根 | 历史分时可用（分钟回填主路径） |
| `finance()` / `xdxr()` | ✅ | 财务快照、除权除息可用 |
| `block()` | ✅ 397,573 行 / 68 个板块 | 仅指数/风格/融资融券类板块，**非完整概念库** |
| `F10()` | ✅ dict | 公司概况可用 |
| `bars()`（日/周/5m/1m 各 category） | ❌ 全 category 返回 `None` | 底层 `struct.error: unpack requires a buffer of 4 bytes` → 响应体与 tdxpy 解析器不匹配（协议升级） |
| `index()`（指数 K 线） | ❌ `None` | 同上 |
| `get_security_quotes()` | ⚠️ 盘前返回空列表 | 盘前无快照属正常，**需 09:30 后复测** |
| `get_transaction_data()` | ❌ `None` | 逐笔同样解析失败 |
| `minute_time` / `hist_minute` | ✅ 240 点 | 当日分时/历史分时可用（但 `minute_time` 返回的 price 出现 10439.62，疑为指数/系数口径错位，需复核） |

> 结论：免费 TCP 的 **K 线链路已实质失效**；项目 `DataManager.get_kline_data()` 的 mootdx 兜底、`minute_backfill` 的 5min bars 路径均会静默拿到空表。当前日线/分钟能完整，靠的是 Tushare 日线 + `minutes()` 历史分时，而不是 bars。

### 2.3 付费 tdxaidata 实测（未安装/无 Key，仅静态核验）

- 从清华源下载 `tdxaidata-1.3.1-py3-none-any.whl`（未安装），包内：
  - `lib/TdxAiData.dll` / `libTdxAiData.dylib` / `libTdxAiData.so`（三平台齐备）；
  - `tdxaidata/docs/tdxaidata使用文档.md`（174KB，含完整字段百科 FN/GP/BK/SC/GO）；
  - `lib/TdxAiData.ini`（Token 节，空 Key 会认证失败）。
- 文档站（help.tdx.com.cn/quant）2026-11-11 已比 10-29 补全大量正文：概述、安装、行情类信息、通用函数、常量枚举、版本更新、HTTP 调用、TdxAiData 接口、FAQ、数据示例均有内容；**财务类数据、分类/板块、ETF/可转债/期货、调用公式 四页仍只有标题**（字段细节改由 wheel 内文档提供）。

---

## 三、TdxAiData（tqserver）能力盘点

### 3.1 覆盖范围（官方文档）

- **股票**：A 股、港股、美股、新三板；行情、基本信息、财务、交易/市场数据
- **基金**：ETF / LOF / REITs（行情、净值）
- **指数**：沪深京、板块指数、港股、中证/国证/华证；含成分股
- **板块**：通达信行业 / 概念 / 风格；`get_sector_list` + `get_stock_list_in_sector`
- **期货**：中金所/郑商所/大商所/上期所/上期能源/广期所（含历史）
- **宏观**：`.HG` 宏观指标
- **可转债 / 个股期权**
- **数据文件包**：`download_file`（龙虎榜 2026-07-10 起、限售解禁 2026-09-04 起、经营分析 2026-06-19 起）

### 3.2 接口清单（tqs 可用，节选）

| 类别 | 接口 |
|---|---|
| 行情 | `get_market_data`（1m/5m/15m/30m/1h/1d/1w/1mon/1q/1y，none/front/back）、`get_market_snapshot(_batch)`、`get_tick_data`、`get_minute_data`、`get_exmin_data`、`get_call_auction(_batch)` |
| 基础 | `get_stock_info(_batch)`、`get_more_info(_batch)`、`get_misc_data`、`get_stock_list`、`get_sector_list(_ds)`、`get_stock_list_in_sector`、`get_relation`、`get_trading_dates` |
| 专业数据 | `get_financial_data(_by_date)`（FN1~FN584）、`get_gpjy_value(_by_date)`（GP1~GP46）、`get_bkjy_value(_by_date)`、`get_scjy_value(_by_date)`（SC01~SC42）、`get_gp_one_data`（GO1~GO47） |
| 除权/股本 | `get_divid_factors`、`get_gb_info(_by_date)` |
| 涨跌停 | `get_zdt_data` |
| 可转债/ETF | `get_kzz_info(_batch)`、`get_trackzs_etf_info` |
| 市场/排名 | `get_global_data`（type=0 沪深京，87 字段）、`get_domain_sorthq` |
| 订阅 | `subscribe` / `unsubscribe` / `get_subscribe_hq_stock_list` |
| 公式 | `formula_process_mul_xg/zb/exp`、`formula_by_src/file`（批量/临时源码，**无本地公式执行**） |

### 3.3 与当前痛点直接对应的字段（关键）

| 当前痛点 | 通达信字段/接口 | 备注 |
|---|---|---|
| 涨停/跌停明细晚到（11-10 18:38 才补到） | `GP14` 涨停金额/开板次数、`GP15` 涨跌停状态/封单、`GP22` 封成比/封流比、`GP24` 首封时间/最大封单、`GP33/34` 跌停、`GP38~40` 涨停统计、`get_zdt_data`、`SC03/04/23/30/33/35/36` | 数据可用性/时点待实测 |
| 两融 T+1（11-09 15:00 才落） | `GP03/11/12/13`（个股融资余额、买入偿还、融券）、`SC01/25`（市场） | 可替代 `margin_detail` |
| ETF 份额 T+1 08:14 | `SC08/38`（ETF 规模份额、净申赎）、`get_gpjy_value`（2026-09-04 起支持 ETF 份额）、`get_trackzs_etf_info` | 可替代 `fund_share` |
| 北向停更（Tushare 10-20 后无） | `GP06/07`、`SC02/20/40/42` | **可能直接补上缺口** |
| 龙虎榜晚到 18:01–20:08 | `GP02/08/09/17/18/37/42`、`SC16~19`、`download_file` | 可替代 `top_list/top_inst` |
| 新股元数据缺失（688827.SH 被误剔） | `get_stock_info`、`get_misc_data`、`get_stock_list` | 可补 `stocks` 元数据 |
| 涨跌家数/市场宽度 | `SC31`（涨跌家数，剔停牌）、`SC39`（涨跌 5% 家数）、`get_global_data` 87 字段 | 可替代自算 |
| 市值/估值/换手 | `GP16` 总市值、`get_stock_info` 财务/每股指标、`get_more_info` 估值 | 单位万元，需换算 |
| 财务三表/指标 | `get_financial_data` FN1~FN584、`get_gp_one_data` GO1~GO47 | 可替代 `fina_indicator/income/balance/cashflow` |
| 复权因子/除权 | `get_divid_factors` + `ForwardFactor`（原始值） | 可替代 `adj_factor` |
| 交易日历 | `get_trading_dates` | 文档注明"需先下载上证指数盘后数据"（caveat） |
| 实时快照/订阅 | `get_market_snapshot(_batch)`、`subscribe` | 可替代 mootdx/新浪/腾讯/东财 |
| 集合竞价/分笔 | `get_call_auction(_batch)`、`get_tick_data` | 当前项目无稳定源 |

### 3.4 平台、商务与合规

- **平台**：tqserver 跨 Windows/macOS/Linux（dylib 已随包）；Python 3.7–3.14。
- **商务**：个人版商城会员中心创建"数据服务 Key"，积分制、账号级共享、Key 仅权限校验；**价格/配额未公开**，需向官方咨询。
- **合规**：用户协议（2026-11-01 生效）明确——数据仅限本人使用、**不得转售或用于商业用途**、仅限中国大陆；积分不足即拒绝调用；虚拟产品不退换。
- **限制**：tqs 无交易、无本地公式执行、无客户端交互、无自选板块管理；`get_misc_data` 返回格式化文本（不可直接计算）。

---

## 四、替代性对照矩阵

### 4.1 可替代（高置信，待实测时点后定优先级）

| 数据类 | 现源 | 通达信 | 迁移收益 |
|---|---|---|---|
| 日线/分钟/指数 K 线 | Tushare（16:00/18:34 就绪） | `get_market_data` | 若更早就绪 → 日终提前；否则作校验/兜底 |
| 除权除息/复权因子 | Tushare `adj_factor` | `get_divid_factors` / `ForwardFactor` | 减少一次 Tushare 调用 |
| 财务三表/指标 | Tushare（偶发空返回） | FN1~FN584 / GO1~GO47 | 降低空返回与限流 |
| 股票列表/基础信息 | Tushare `stock_basic`（月更，新股缺） | `get_stock_info`/`get_stock_list` | **直接修 688827 类缺口** |
| 交易日历 | Tushare `trade_cal` | `get_trading_dates` | 去 Tushare 依赖（注意 caveat） |
| 两融 | Tushare `margin_detail`（T+1 15:00） | GP03/11/12/13、SC01/25 | 可能提前到当日 |
| ETF 份额 | Tushare `fund_share`（T+1 08:14） | SC08/38、GP 系列 | 可能提前到当日 |
| 北向 | Tushare（停 10-20） | SC02/20/40/42、GP06/07 | **补上停更缺口** |
| 龙虎榜 | Tushare/AKShare（18:01–20:08） | GP02/08/09/17/18、SC16~19、download_file | 可能提前 |
| 涨停明细 | Tushare `limit_list_d`（18:30+） | GP14/15/22/24/33/34、get_zdt_data | **直接消除 559/560 晚到重建链** |
| 涨跌家数/情绪 | 自算 daily_cache | SC31/39、get_global_data | 减少计算、口径统一 |
| 实时快照 | mootdx（失败）/新浪腾讯东财 | get_market_snapshot(_batch)/subscribe | 稳定性与字段更完整 |

### 4.2 需验证/部分替代

- **板块成分**：TDX 是自有行业/概念/风格分类，**与申万/同花顺口径不同**；仪表盘板块热度（532 号，基于申万）不能直接替换，需重做映射。
- **市值/估值**：字段可得，但单位（万元）与项目（千元/万元混用）需逐表换算。
- **财务明细**：FN1~FN584 覆盖广，但需核对报告期口径（单季/累计）与 Tushare 是否一致。
- **历史深度**：文档给出各字段起始日（如 GP02 自 20230717、GP14 自 20180319），需确认项目回测窗口是否够用。

### 4.3 不建议替代

- **新闻/舆情/公告文本**：文档未见对应接口；仍依赖 Tushare `news` 与 AKShare。
- **申万行业指数/板块热度**：口径不一致，替换成本高于收益。
- **交易/下单**：tqs 明确不支持；项目当前也不需要。

---

## 五、对 11-10 日终痛点的具体改善判断

| 11-10 实测痛点 | 通达信能否改善 | 判断 |
|---|---|---|
| mootdx 49 次/日创建失败，全天 sina 降级 | 免费侧可修（BESTIP 旧节点）；付费侧可换 `get_market_snapshot_batch` | **P0 先修免费侧** |
| `bars()` 全挂，K 线兜底静默为空 | 付费 `get_market_data` 可替代 | 付费后消除 |
| 涨停明细 18:38 才到，CHECK 两次失败 | GP14/24 + get_zdt_data 若当日更早 → 消除 | **待测首达时点** |
| 两融/ETF T+1 | GP03 / SC08 若当日可得 → 消除 | **待测首达时点** |
| 北向停 10-20 | SC02/20 可补 | 待确认数据仍更新 |
| 龙虎榜 18:33 才 51 行 | GP02 等可替代 | 待测 |
| 688827.SH 元数据缺失被误剔 | get_stock_info 可补 | 高置信 |
| 指数日线 18:34 才齐 | get_market_data 指数 | 待测 |

> 说明：以上"待测"均指**当日数据可采时点**。官方文档没有发布时间表，必须用试用 Key 在 15:00–19:00 每 5 分钟探测各表行数，才能下结论。

---

## 六、风险与未知

1. **更新时点未知**（最大风险）：若 TDX 日线也要 18:00 后才全，则无法提前日终，只能作校验/兜底。
2. **费用/配额未知**：积分价格、每接口消耗、并发限制均未公开；需向官方询价并做月度成本测算。
3. **单厂商依赖**：tqserver 为闭源动态库，协议/字段随版本变化（1.3.0→1.3.2 已多次改字段），需锁定版本并保留 Tushare 兜底。
4. **口径差异**：板块分类、财务报告期、金额单位（万元 vs 千元）、复权因子语义均需逐项对齐。
5. **合规**：仅限本人使用、不得转售；若未来做多用户/云服务需重新评估授权。
6. **文档缺口**：网站财务/板块/ETF/公式四页仍空；`get_trading_dates` 的"需客户端下载 999999 盘后数据"与"tqserver 不依赖客户端"存在表述冲突，需实测澄清。
7. **免费 TCP 协议漂移**：bars/index 已因协议升级失效，说明免费链路不可作为长期基座。

---

## 七、建议路线与验收标准

### P0（本周，零成本，建议立即做）

1. **修 mootdx 选点**：`_get_client()` 改为显式健康检查服务器列表（`110.41.147.114`、`124.70.199.56` 优先），失败自动切换；**不要用 `stocks()` 作为唯一健康判据**（改为 `get_security_count` + 超时重试）；清理/忽略 `~/.mootdx/config.json` 的旧 `BESTIP`。
2. **兜底显式化**：`bars()` 返回空时记录 WARNING（当前静默），避免"以为有 K 线兜底"。
3. **验收**：连续 2 个交易日 `mootdx 客户端创建失败` = 0；实时源不再全天降级；分钟/日线覆盖不下降。

### P1（1–2 周，需申请试用 Key）

4. **申请 TdxAiData 试用 Key**（个人版商城，数据服务类型），在**独立临时 venv** 安装 `tdxaidata`（不改项目依赖），写只读探针 `_561_tdx_probe.py`：
   - 每日 15:00–19:30 每 5 分钟，对 20 张核心表对应的 tqs 接口取行数/首行；
   - 记录**首达时点**、字段完整性、单位、与 Tushare 同日值差异；
   - 连续 3–5 个交易日。
5. **重点验证项**：`get_market_data`（1d/1m/指数）、`get_zdt_data`、`get_gpjy_value`（GP03 两融/GP14 涨停）、`get_scjy_value`（SC08 ETF/SC02 北向/SC31 涨跌家数）、`get_financial_data`、`get_stock_info`、`get_trading_dates`、`get_market_snapshot_batch`。
6. **验收门槛**（全部满足才进入 P2）：
   - 关键表首达 **早于 Tushare ≥30 分钟**（或至少不晚于）；
   - 覆盖率 ≥99.5%（与 current 表逐日比对）；
   - 字段/单位换算后可复现 current 值（误差在业务容忍内）；
   - 连续 5 日无认证/限流/解析异常；
   - 月度成本可接受。

### P2（验收通过后，分项迁移）

7. **优先迁移**（收益最高）：涨停明细 → 两融 → ETF 份额 → 北向 → 龙虎榜 → 新股元数据。
8. **次优迁移**：日线/指数/分钟（若首达更早）、财务三表、交易日历、复权因子。
9. **保留双源**：Tushare 作为校验/兜底；关键表写入前做双源差异告警。
10. **不动**：申万板块热度、新闻舆情、交易执行。

---

## 八、附录：本次实测证据

### 8.1 环境

```
mootdx 0.11.7 / tdxpy 0.2.7 / akshare 1.18.64 / tushare 1.4.29 / pandas 3.0.1
Python 3.11（backend/.venv）
无通达信客户端；127.0.0.1:17709 未监听；无 TdxAiData.ini；无 TDX 本地数据目录（TDXDIR=C:/new_tdx）
```

### 8.2 关键复现命令（只读）

```bash
# 1) 主站连通性/接口矩阵（显式 server）
cd backend && .venv/bin/python - <<'PY'
from mootdx.quotes import Quotes
c = Quotes.factory(server=['110.41.147.114', 7709], timeout=6)
print(len(c.stocks()))      # 27859
print(len(c.minutes(symbol='000001')))  # 240
print(c.bars(symbol='000001', frequency=9, offset=5))  # 空
PY

# 2) bars 失败根因（raise_exception=True）
# struct.error: unpack requires a buffer of 4 bytes → tdxpy 解析器与主站响应不匹配

# 3) BESTIP 旧节点
python -c "import json;print(json.load(open('/Users/kalence/.mootdx/config.json'))['BESTIP'])"
# {'HQ': ['123.125.108.14', 7709], ...}

# 4) tdxaidata 包内平台库（未安装）
pip download --no-deps -d /tmp/tdxw tdxaidata==1.3.1 -i https://pypi.tuna.tsinghua.edu.cn/simple
unzip -l /tmp/tdxw/tdxaidata-1.3.1-py3-none-any.whl | grep -E "dylib|\.so|\.dll"
```

### 8.3 文档来源

- `https://help.tdx.com.cn/quant/`（TdxQuant 概述、安装、行情类信息、通用函数、常量枚举、版本更新、HTTP 调用、TdxAiData 接口、FAQ、数据示例）
- wheel 内置 `tdxaidata/docs/tdxaidata使用文档.md`（接口目录 + 字段百科 F.1~F.19）
- `https://help.tdx.com.cn/quant/docs/markdown/mindoc-1hp49ff1nkrus.html`（用户协议，2026-11-01 生效）

### 8.4 本次评估边界

- 只读：未安装 tdxaidata、未购买 Key、未改项目代码/配置、未写业务库。
- 未验证：盘中实时快照、当日数据首达时点、Key 配额/价格、`get_trading_dates` 的客户端数据依赖、财务/板块/ETF 字段细节（网站页仍空，wheel 文档已有但未逐字段比对）。
