# 478号｜daily_basic 5 年历史回补（「近5年分位」名实修复）

**定位**：dim7 定稿前置核查（2026-09-23）发现②——`daily_basic_cache` 仅 2026-01-05 起（9 个月/175 天），而 `daily_cache` 有 5 年+（2021-07-07 起）→ dim7 的 `pe_percentile_5y`/`pb_percentile_5y`（以及 a1/a2 锚）实为「近 9 个月分位」→ 分位结论系统性失真（万科"极度高估"方向存疑）。

**状态**：✅ **已实施**（2026-09-23）。`backend/scripts/_478_backfill_daily_basic.py` 回补 **1089/1089 交易日成功**（2021-07-07 → 2026-01-04，740s，备份 market_cache.db.bak_478_daily_basic_*）；600519 daily_basic 175→**1266 行**（对齐 daily_cache）。**回补后 5 年分位实证**：600519 PB 37.1%→**5.1%**/PE 21.7%→**3.1%**（历史极低位）；000002 PB 99.4%→**46.1%**（原"年内最高→极高估"修正为 5 年视角中位，**方向翻转**）。待 476 全量回算后 tags 更新 + dim7 结论重验。

## 根因（实证）
- `daily_basic_cache`（market_cache.db）：**963,677 行 / 5665 只 / 2026-01-05 → 09-22**（每只 175 天）；442 备份（09-15）同样仅 2026 年（169 天）——**从未有更早历史**（非最近丢失）。
- `daily_cache`（同库）：**6,472,239 行 / 2021-07-07 → 09-22**（600519=1266 天）——日线 5 年完整，**daily_basic 采集/补采滞后**（08-06 commit 1b2cc7f 提到"daily_basic 5年数据补采"但无对应代码落地；442 补的是 daily_cache 三天空洞非 daily_basic）。
- 采集链路：`_batch_daily_basic(trade_date)` = `pro.daily_basic(trade_date=...)` 按日增量，**无历史回补**（与 daily_cache 的 `_batch_daily` 同构，后者有完整历史）。

## 影响（dim7 + 全市场）
1. **`pe_percentile_5y`/`pb_percentile_5y` 名不副实**：175 天窗口 → a1（资产锚 PB 分位）/a2（收益锚 PE 分位）失真。
2. **000002 万科案例（方向可能反）**：pb=0.445 是 9 个月窗口**最高值** → 分位 99.4% → a1=-2 → 判「极度高估」；但 5 年视角万科 pb 处于**历史低位**（2019-21 达 2+）→ 真实 5 年分位应≈0（低估）→ **结论方向很可能错误**。
3. 全市场 5665 只分位均失真；消费 pe/pb 分位的其他引擎（dim4 等）同受影响。

## 方案（待拍板）
- **回补范围**：2021-07-07（对齐 daily_cache 起点，或 5 年 2021-09-23）→ 2026-01-04，逐交易日全市场。
- **实现**：新脚本 `backend/scripts/_478_backfill_daily_basic.py`（复用 daemon `_batch_daily_basic`，`_ts` 已做日期归一；交易日历取 `daily_cache` 的 DISTINCT trade_date 交集，避免节假日误调）；daemon 停止态执行；执行前备份 market_cache.db。
- **量级**：~1100 交易日 × ~5500 行 ≈ 600 万行（SQLite 分批写入）；API ~1100 次（Tushare 5000 积分可拉 daily_basic 全历史）。
- **回补后**：复用 `_476_recompute_raw2.py` 全量重算 RAW-2 → tags 更新（pe/pb 分位、composite/level 全变）。
- **验证**：600519/000002 daily_basic 行数（175 → 1200+）；000002 pb 5 年分位（99.4% → 应<10%，a1 -2 → +2）；dim7 level 重算（万科 extreme_high → 大概率翻转）；回归测试。

## 待办追踪
- 478 与 477（行业映射）并行；完成后 476 全量回算 + dim7 定稿数值拍板。
- 回补对 daily_basic 消费方（dim1 data_context daily_basic_df 等）为纯增量，无破坏风险。
