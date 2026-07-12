# D3 分钟K线补齐 — AKShare East Money 方案

> **For agentic workers:** Inline execution.

**Goal:** 使用 AKShare `stock_zh_a_hist_min_em()` 一次性补齐全市场冷门股 ~3100 只的 30 天 1min K线数据到 ECM `minute_kline_cache`，补齐后清理临时脚本和相关流程。

**Architecture:** 
- 新建独立脚本 `scripts/backfill_minute_kline_ak.py`，复用 `AkshareProvider.get_minute_data()` 现有封装
- 逐只调用，150ms间隔防限流，每50只批量写入ECM
- 补齐验证后删除临时脚本 + 废弃的Tushare脚本，确保不影响日常

**Tech Stack:** Python 3.11, AKShare 1.18.64, ECM SQLite WAL

## 全局约束

- 遵循260号方案五层数据架构：只通过 DataManager/ECM 读写，不直调外部API
- 补齐后清理临时脚本，不留下可能被定时调度误触发的文件
- 不修改任何生产代码文件（不碰 data_daemon.py / mootdx_collector.py / 路由等）

---

### Task 1: 创建 AKShare 回填脚本

**Files:**
- Create: `backend/scripts/backfill_minute_kline_ak.py`

- [ ] **Step 1: 创建脚本**

脚本结构：
1. 查询ECM `daily_cache` 获取全市场股票列表
2. 查询ECM `minute_kline_cache` 获取已有1min数据的股票
3. 计算需补齐的股票集合
4. 逐只调用 `AkshareProvider.get_minute_data(ts_code, freq='1min', start_date=30日前, end_date=今日)`
5. 每50只批量写入ECM `cache_minute_kline()`
6. 输出日志：进度/行数/耗时

```python
#!/usr/bin/env python3
"""
backfill_minute_kline_ak.py — 分钟K线全量补齐脚本（AKShare East Money 版）

用途：一次性地利用 AKShare stock_zh_a_hist_min_em() 补齐全市场冷门股
      30 天 1min K线数据。适用于周末非交易时段运行。

使用方式： python scripts/backfill_minute_kline_ak.py

完成后操作：确认补齐成功后，删除本文件 + scripts/backfill_minute_kline.py（Tushare旧版）

⚠️ 一次性脚本 — 补齐后删除，不属于日常运维流程。
"""

import os, sys, time, logging
from datetime import datetime, timedelta

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('backfill_ak')

from app.data.enhanced_cache_manager import get_ecm_instance
from app.data.akshare_provider import AkshareProvider


def get_stock_list(ecm):
    """获取全市场股票列表和已有分钟数据的股票"""
    all_stocks = [r[0] for r in ecm.conn.execute(
        "SELECT DISTINCT ts_code FROM daily_cache ORDER BY ts_code"
    ).fetchall()]

    cutoff = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    have_1min = set(r[0] for r in ecm.conn.execute(
        "SELECT DISTINCT ts_code FROM minute_kline_cache WHERE freq='1min' AND trade_date >= ?", [cutoff]
    ).fetchall())

    return all_stocks, have_1min


def main():
    logger.info("=" * 60)
    logger.info("分钟K线全量补齐脚本 (AKShare East Money)")
    logger.info(f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    ecm = get_ecm_instance()
    provider = AkshareProvider()

    all_stocks, have_1min = get_stock_list(ecm)
    need = [s for s in all_stocks if s not in have_1min]
    logger.info(f"全部股票: {len(all_stocks)} | 已有1min: {len(have_1min)} | 需补齐: {len(need)}")

    if not need:
        logger.info("无需补齐，退出")
        return

    total_ok = 0
    total_rows = 0
    t_start = time.time()
    write_buf = []

    for i, code in enumerate(need):
        try:
            start_d = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            end_d = datetime.now().strftime('%Y-%m-%d')
            data = provider.get_minute_data(code, freq='1min', start_date=start_d, end_date=end_d)
            if data and len(data) > 0:
                import pandas as pd
                df = pd.DataFrame(data)
                df['ts_code'] = code
                df['freq'] = '1min'
                if 'vol' in df.columns and 'volume' not in df.columns:
                    df['volume'] = df['vol']
                    df = df.drop(columns=['vol'])
                write_buf.append(df)
                total_ok += 1
                total_rows += len(df)
        except Exception as e:
            logger.debug(f"  {code} 失败: {e}")

        # 每50只批量写入
        if len(write_buf) >= 50:
            for buf_df in write_buf:
                try:
                    ecm.cache_minute_kline(buf_df)
                except Exception:
                    pass
            write_buf = []

        # 进度输出
        if (i + 1) % 100 == 0:
            elapsed = time.time() - t_start
            rate = total_ok / (elapsed / 60) if elapsed > 0 else 0
            logger.info(f"  [{i+1}/{len(need)}] 成功{total_ok}只, {total_rows}行, {rate:.0f}只/分")

        # 150ms间隔
        time.sleep(0.15)

    # 最终写入
    for buf_df in write_buf:
        try:
            ecm.cache_minute_kline(buf_df)
        except Exception:
            pass

    t_total = time.time() - t_start
    logger.info("=" * 60)
    logger.info(f"补齐完成!")
    logger.info(f"成功: {total_ok}/{len(need)} 只, 共 {total_rows} 行")
    logger.info(f"耗时: {t_total:.0f}秒 ({t_total/60:.1f}分钟)")
    logger.info(f"速率: {total_ok/(t_total/60):.0f} 只/分钟")
    logger.info("=" * 60)
    logger.info("")
    logger.info("后续操作:")
    logger.info("  1. 确认行数合理后，删除本脚本:")
    logger.info("     rm scripts/backfill_minute_kline_ak.py")
    logger.info("  2. 删除废弃的Tushare旧版脚本:")
    logger.info("     rm scripts/backfill_minute_kline.py")
    logger.info("  3. 如有cron定时任务，移除对应条目")
    logger.info("")

if __name__ == '__main__':
    main()
```

- [ ] **Step 2: 语法验证**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统/backend && .venv/bin/python -c "import ast; ast.parse(open('scripts/backfill_minute_kline_ak.py').read()); print('AST OK')"
```

### Task 2: 运行回填（周末非交易时段）

- [ ] **Step 1: 执行脚本**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统/backend && .venv/bin/python scripts/backfill_minute_kline_ak.py 2>&1 | tee logs/backfill_minute_kline_ak.log
```

- [ ] **Step 2: 验证结果**

```bash
# 检查行数增长
cd /Users/kalence/Desktop/01-A股股票分析系统/backend && .venv/bin/python -c "
from app.data.enhanced_cache_manager import get_ecm_instance
ecm = get_ecm_instance()
rows = ecm.conn.execute('SELECT COUNT(*) FROM minute_kline_cache').fetchone()[0]
codes = ecm.conn.execute('SELECT COUNT(DISTINCT ts_code) FROM minute_kline_cache').fetchone()[0]
print(f'minute_kline_cache: {rows} 行, {codes} 只股票')
"
```

### Task 3: 验证成功后清理

- [ ] **Step 1: 删除一次性回填脚本**

```bash
rm /Users/kalence/Desktop/01-A股股票分析系统/backend/scripts/backfill_minute_kline_ak.py
```

- [ ] **Step 2: 删除废弃的 Tushare 旧版脚本**

```bash
rm /Users/kalence/Desktop/01-A股股票分析系统/backend/scripts/backfill_minute_kline.py
```

- [ ] **Step 3: 确认无残留定时引用**

```bash
# 确认 data_daemon.py 中没有引用这两个脚本
cd /Users/kalence/Desktop/01-A股股票分析系统/backend && grep -n 'backfill_minute_kline' data_daemon.py || echo "无残留引用 ✓"
```

- [ ] **Step 4: 更新待解决事项**

在 `待解决事项.md §十二 #10` 标记 D3 已完成。
