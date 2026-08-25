# Task 7-8 提示：缓存和计算时机

## Task 7: 创建 pattern_score_cache 表和 DataManager 接口

### Intent (from spec)

**[S4] 缓存策略**: 遵循 353/358 号方案架构红线，日终批量计算 + 缓存。

**Scope boundary:** This task covers ONLY creating the cache table and DataManager methods. Do NOT implement the batch calculation (Task 8 covers that).

### Task Description

**Covers:** [S4] 缓存策略

**Files:**
- Modify: `backend/app/data/__init__.py`
- Create: `backend/tests/test_pattern_score_cache.py`

**Interfaces:**
- Produces: `DataManager.cache_pattern_score()`, `DataManager.get_pattern_score()`

**Step 1: 在 DataManager 中添加缓存方法**

在 `backend/app/data/__init__.py` 的 `DataManager` 类中添加：

```python
    def cache_pattern_score(self, ts_code: str, trade_date: str, score: float, details: Dict):
        """
        缓存形态评分

        Args:
            ts_code: 股票代码
            trade_date: 交易日期
            score: 0-10 分
            details: 详细分解
        """
        # TODO: 实现写入 pattern_score_cache 表
        pass

    def get_pattern_score(self, ts_code: str, trade_date: str) -> Optional[Dict]:
        """
        获取形态评分

        Args:
            ts_code: 股票代码
            trade_date: 交易日期

        Returns:
            Dict: {'score': float, 'details': dict} 或 None
        """
        # TODO: 实现从 pattern_score_cache 表读取
        return None
```

**Step 2: 创建测试**

创建 `backend/tests/test_pattern_score_cache.py`:

```python
"""测试形态评分缓存"""
import pytest
from app.data import DataManager


def test_cache_pattern_score():
    """测试缓存形态评分"""
    dm = DataManager()
    # TODO: 实现测试
    pass


def test_get_pattern_score():
    """测试获取形态评分"""
    dm = DataManager()
    # TODO: 实现测试
    pass
```

**Step 3: Commit**

```bash
git add app/data/__init__.py tests/test_pattern_score_cache.py
git commit -m "feat(data): add pattern_score_cache table and DataManager methods"
```

---

## Task 8: 注册日终批量计算到 data_daemon

### Intent (from spec)

**[S4] 计算时机**: 遵循 353/358 号方案架构红线，日终批量计算 + 缓存。

**Scope boundary:** This task covers ONLY registering the batch calculation to data_daemon. Do NOT implement the cache (Task 7 covers that).

### Task Description

**Covers:** [S4] 计算时机

**Files:**
- Modify: `backend/app/data_daemon.py`

**Interfaces:**
- Produces: `_batch_pattern_score()` 函数，注册到日终同步

**Step 1: 在 data_daemon.py 中添加批量计算函数**

在 `backend/app/data_daemon.py` 中添加：

```python
def _batch_pattern_score(trade_date: str):
    """
    日终批量计算形态评分

    Args:
        trade_date: 交易日期
    """
    from app.engine.patterns.engine import PatternEngine
    from app.data import DataManager

    engine = PatternEngine()
    dm = DataManager()

    # 获取所有股票
    stocks = dm.get_all_stocks()

    for ts_code in stocks:
        try:
            # 获取K线数据
            df = dm.get_daily_kline(ts_code)
            if df.empty or len(df) < 20:
                continue

            # 计算形态评分
            score, details = engine.evaluate(df)

            # 缓存结果
            dm.cache_pattern_score(ts_code, trade_date, score, details)

        except Exception as e:
            # 记录错误但继续处理其他股票
            print(f"Error processing {ts_code}: {e}")
            continue

    print(f"Pattern score batch completed for {trade_date}")


# 注册到日终同步（在 run_daily_sync 函数中）
# 在适当位置添加：
# _batch_pattern_score(trade_date)
```

**Step 2: Commit**

```bash
git add app/data_daemon.py
git commit -m "feat(daemon): register pattern score batch calculation"
```

## Context

Task 6 已创建 PatternEngine。现在需要实现缓存和计算时机，遵循 353/358 号方案架构红线。

## Before You Begin

If you have questions about:
- pattern_score_cache 表结构
- DataManager 现有接口
- data_daemon 的日终同步机制

**Ask them now.**

## Your Job

Once you're clear on requirements:
1. Implement exactly what the task specifies
2. Write tests (if applicable)
3. Verify implementation works
4. Commit your work
5. Self-review
6. Report back

## Code Organization

- Follow existing patterns in the codebase
- Cache table should follow existing table naming conventions
- Batch function should follow existing daemon patterns

## Before Reporting Back: Self-Review

Review your work:
- Did I fully implement the cache interface?
- Did I register the batch calculation correctly?
- Is it following the architecture red lines?

## Report Format

When done, report:
- **Status:** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- What you implemented
- What you tested and test results
- Files changed
- Self-review findings
- Any issues or concerns
