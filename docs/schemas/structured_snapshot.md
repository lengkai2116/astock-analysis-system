# 结构化快照 Schema

> 来源: 272号方案 §9.2
> 用途: 传递给 DeepSeek 的股票现状描述数据格式
> 更新: 2026-07-16

## 顶层结构

```json
{
  "market_context": { },
  "chanlun": { },
  "chip": { },
  "price_position": { },
  "volume_price": { },
  "capital_games": { },
  "return_driver": { },
  "time_rhythm": { },
  "verification": { }
}
```

各字段**有数据则填充，无数据则为 null**，DeepSeek 据此决定是否在描述中提及该维度。

---

## 字段定义

### market_context（环境定位）

| 字段 | 类型 | 数据来源 | 描述 |
|------|------|---------|------|
| `index_trend` | str | `market_context.idx_5d_ret` / `idx_20d_ret` | "bullish"/"bearish"/"sideways" |
| `sector` | str | `Stock.industry` | 所属行业 |
| `sector_strength` | str | sector_pct / 板块数据 | "strong"/"neutral"/"weak" |
| `relative_strength` | float | 个股涨幅 - 大盘涨幅 | 近20日相对强弱（百分比） |
| `new_high_250d_pct` | float | 250日新高比例 | 全市场新高占比 |

### chanlun（走势结构）

| 字段 | 类型 | 数据来源 | 描述 |
|------|------|---------|------|
| `level` | str | `trend.stage` | "daily"/"weekly"/"30min" |
| `trend_direction` | str | `trend.direction` | "up"/"down"/"neutral" |
| `trend_strength` | str | `trend.strength` | "strong"/"weakening" |
| `zhongshu_low` | float | 中枢下沿 | 最近中枢区间下限 |
| `zhongshu_high` | float | 中枢上沿 | 最近中枢区间上限 |
| `position_vs_zhongshu` | str | `multi_level.position_vs_zs` | "above"/"inside"/"below" |
| `zhongshu_duration` | str | `zhongshu_list[].duration` | 中枢持续时长 |
| `beichi_direction` | str/null | `买卖点信号.背驰信号.方向` | "up"/"down"/null |
| `beichi_confidence` | float | `买卖点信号.背驰信号.置信度` | 0-1 |
| `active_signal_type` | str/null | `buy_sell_point` 中最新一个 | "三类买点"/"三卖"/null |
| `active_signal_date` | str | 对应信号的形成日期 | "2026-07-10" |
| `active_signal_level` | str | 信号级别 | "30min"/"daily" |
| `zhongshu_strength` | str/null | Phase 2 V1 计算 | "strong"/"weak"/null |

### chip（筹码成本）

| 字段 | 类型 | 数据来源 | 描述 |
|------|------|---------|------|
| `chip_peak` | float | `ChipDistributionService` | 筹码主峰价格 |
| `main_force_cost` | float | `_calc_main_force_cost()` | 主力集中价 |
| `distance_pct` | float | (close - cost) / cost | 当前价偏离主力成本百分比 |
| `margin_cost_price` | float/null | margin_cache 估算 | 融资成本价 |
| `sandwich_zone` | str/null | 三种价格关系 | "main_force_profitable"/"both_profitable"/"both_loss" |
| `asr` | float | ASR指标 | 浮筹比例 0-100 |
| `chip_concentration` | str | `concentration` 变化 | "increasing"/"decreasing"/"stable" |
| `phase` | str | `phase_info.phase_name` | "accumulation"/"wash"/"raising"/"distribution" |

### price_position（价格位置）

| 字段 | 类型 | 数据来源 | 描述 |
|------|------|---------|------|
| `ma5`, `ma10`, `ma20`, `ma60` | float | K线均线计算 | 各周期均线值 |
| `ma_alignment` | str | `ma_alignment` | "bullish"/"bearish"/"converging" |
| `bias_ma5`, `bias_ma20`, `bias_ma60` | float | (close - MA) / MA * 100 | 各周期乖离率 |
| `percentile_250d` | float | 250日历史分位 | 0-100 |
| `support` | float | `near_levels` + VAP | 关键支撑位 |
| `resistance` | float | `near_levels` + VAP | 关键阻力位 |
| `vap_support`, `vap_resistance` | float/null | VAP计算 | 成交量密集区支撑/阻力 |

### volume_price（量价关系）

| 字段 | 类型 | 数据来源 | 描述 |
|------|------|---------|------|
| `basic_form` | str | 八种基本形态计算 | "量增价涨"/"价跌量缩"/... |
| `confirmation` | str | 确认/异常判断 | "confirmed"/"abnormal"/"连续异常" |
| `vol_ratio` | float | `volume_ratio` | 量比 |
| `vol_ma5_vs_ma120_pct` | float | 5日均量 vs 120日均量 | 成交量历史分位 |
| `vol_trend_5d` | str | 近5日量变化方向 | "increasing"/"decreasing"/"stable" |
| `pattern_name` | str/null | `enhance_patterns` 最优匹配 | "双针探底(预涨)" |
| `divergence_type` | str/null | `divergence_type` | "top"/"bottom"/null |
| `resonance_score` | float | `resonance_score` | 0-1 |
| `insider_behavior` | str/null | Phase 2 V2 检测 | "accumulation"/"distribution"/null |
| `three_laws_confirmed` | bool | 威科夫三定律验证 | true/false |

### capital_games（资金博弈）

| 字段 | 类型 | 数据来源 | 描述 |
|------|------|---------|------|
| `net_lg_amount_5d` | float | `market_context.net_lg_amount` | 5日大单净额 |
| `net_elg_amount_5d` | float | `moneyflow_cache` | 5日超大单净额 |
| `net_sm_amount_5d` | float | `moneyflow_cache` | 5日小单净额 |
| `retail_vs_institutional` | str | C2 计算 | "healthy"/"danger"/"overheat"/"panic" |
| `sentiment_crowding` | float/null | C3 计算 | 情绪拥挤度 |
| `sentiment_crowding_label` | str | C3 阈值判断 | "overheat"/"normal"/"cooling" |
| `turnover_rate` | float | `daily_basic.turnover_rate` | 换手率 |
| `circ_mv` | float | `daily_basic.circ_mv` | 流通市值（亿） |
| `lhb_net_buy` | float | `lhb_cache` | 龙虎榜净买额 |
| `lhb_institutional_ratio` | float | 龙虎榜席位分析 | 机构买入占比 0-1 |

### return_driver（收益驱动）

| 字段 | 类型 | 数据来源 | 描述 |
|------|------|---------|------|
| `available` | bool | 固定 false | 当前为 false，暂不可用 |
| `volatility_percentile` | float/null | 日涨跌幅标准差 | 波动率历史分位 |
| `margin_growth_rate` | float/null | margin_cache | 融资余额增长率 |

### time_rhythm（时间节奏）

| 字段 | 类型 | 数据来源 | 描述 |
|------|------|---------|------|
| `zhongshu_duration_months` | float | `zhongshu.duration` 转换 | 中枢持续月数 |
| `near_level_upper_limit` | bool | 日线≥6月/周线≥6月 | 是否接近经验性上限 |
| `boll_bandwidth` | str | BOLL 带宽计算 | "contracted"/"expanding"/"normal" |
| `ma_convergence` | bool | 多周期均线间距 | 均线是否粘合 |

### verification（辅助验证）

| 字段 | 类型 | 数据来源 | 描述 |
|------|------|---------|------|
| `sentiment_phase` | str/null | BOCIASI快慢线 | "ice"/"revival"/"climax"/"ebb"/null |
| `factor_score` | float | 因子评分系统 | 0-1 |
| `factor_rank_pct` | float | 因子评分排名 | 0-100 |
| `finance_check` | str/null | 财务排雷结果 | "passed"/"failed"/null |
| `finance_detail` | list[str] | 各项检查详情 | ["ROCE>15%✓", "速动比率>0.8✓"] |

---

## 状态管理

| 规则 | 说明 |
|------|------|
| **值可用** | 正常填充对应类型 |
| **值不可用** | 填充 `null`，DeepSeek 跳过该维度 |
| **数值边界** | 百分比字段统一为 0-100 或 -100-100 |
| **枚举字段** | 统一使用英文小写字符串，不带空格 |
