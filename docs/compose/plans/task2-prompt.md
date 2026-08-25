# Task 2 提示：实现预涨型 20 种形态检测器

## Intent (from spec)

**[S1] 形态覆盖度**: 基于 Wiki 50 种量价形态，实现预涨型 20 种形态检测器。

**Scope boundary:** This task covers ONLY implementing the 20 bullish pattern detectors. Do NOT implement bearish, blackhorse, or state detectors (Tasks 3-5 cover those).

## Task Description

**Covers:** [S1] 形态覆盖度

**Files:**
- Create: `backend/app/engine/patterns/detectors/bullish_patterns.py`
- Create: `backend/tests/test_bullish_patterns.py`

**Interfaces:**
- Consumes: `PatternDetector` 基类
- Produces: `BullishPatternDetector.detect()` → `List[PatternResult]`

**Step 1: 创建预涨型检测器文件**

创建 `backend/app/engine/patterns/detectors/bullish_patterns.py`:

```python
"""
预涨型量价形态检测器（20种）
基于《量价狙击》第六章
"""
from typing import List, Optional, Dict
import pandas as pd
import numpy as np

from app.engine.patterns import PatternResult, PatternCategory, PatternStage, PatternLevel
from app.engine.patterns.detectors.base import PatternDetector


class BullishPatternDetector(PatternDetector):
    """预涨型形态检测器"""

    def detect(self, df: pd.DataFrame, context: Optional[Dict] = None) -> List[PatternResult]:
        """检测所有预涨型形态"""
        if df.empty or len(df) < 20:
            return []

        results = []
        detectors = [
            self._p_1_1, self._p_1_2, self._p_1_3, self._p_1_4, self._p_1_5,
            self._p_1_6, self._p_1_7, self._p_1_8, self._p_1_9, self._p_1_10,
            self._p_1_11, self._p_1_12, self._p_1_13, self._p_1_14, self._p_1_15,
            self._p_1_16, self._p_1_17, self._p_1_18, self._p_1_19, self._p_1_20,
        ]

        for detector in detectors:
            try:
                p = detector(df, context)
                if p:
                    results.append(p)
            except Exception:
                continue

        return results

    # TODO: 实现 P-1-1 到 P-1-20 的检测方法
    # 参考计划文件中的具体实现示例
```

**Step 2: 创建测试文件**

创建 `backend/tests/test_bullish_patterns.py`:

```python
"""测试预涨型形态检测器"""
import pytest
import pandas as pd
import numpy as np

from app.engine.patterns.detectors.bullish_patterns import BullishPatternDetector


@pytest.fixture
def sample_df():
    """创建样本K线数据"""
    dates = pd.date_range(start='2025-01-01', periods=100, freq='D')
    np.random.seed(42)

    close = 100 + np.cumsum(np.random.randn(100) * 2)
    open_price = close + np.random.randn(100) * 0.5
    high = np.maximum(close, open_price) + np.abs(np.random.randn(100) * 1)
    low = np.minimum(close, open_price) - np.abs(np.random.randn(100) * 1)
    volume = np.random.randint(1000000, 5000000, 100).astype(float)

    df = pd.DataFrame({
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume
    }, index=dates)

    return df


def test_detector_initialization():
    """测试检测器初始化"""
    detector = BullishPatternDetector()
    assert detector is not None


def test_detect_returns_list(sample_df):
    """测试 detect 返回列表"""
    detector = BullishPatternDetector()
    results = detector.detect(sample_df)
    assert isinstance(results, list)


def test_empty_dataframe():
    """测试空 DataFrame"""
    detector = BullishPatternDetector()
    df = pd.DataFrame()
    results = detector.detect(df)
    assert results == []


def test_short_dataframe():
    """测试数据不足"""
    detector = BullishPatternDetector()
    df = pd.DataFrame({
        'open': [100, 101],
        'high': [102, 103],
        'low': [99, 100],
        'close': [101, 102],
        'volume': [1000000, 1100000]
    })
    results = detector.detect(df)
    assert results == []
```

**Step 3: 运行测试**

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统/backend
pytest tests/test_bullish_patterns.py -v
```

Expected: 全部 PASS

**Step 4: Commit**

```bash
git add app/engine/patterns/detectors/bullish_patterns.py tests/test_bullish_patterns.py
git commit -m "feat(patterns): implement P-1-1 to P-1-6 bullish detectors"
```

## Context

Task 1 已创建 `PatternDetector` 基类和注册了 50 种形态元数据。现在需要实现具体的检测逻辑。

参考 Wiki《量价狙击》第六章的 20 种预涨型形态定义。

## Before You Begin

If you have questions about:
- 20 种预涨型形态的具体定义
- 检测逻辑的实现细节
- 与 PatternDetector 基类的集成方式

**Ask them now.**

## Your Job

Once you're clear on requirements:
1. Implement exactly what the task specifies
2. Write tests (following TDD)
3. Verify implementation works
4. Commit your work
5. Self-review
6. Report back

## Code Organization

- Follow the file structure defined in the plan
- Each detection method should be separate and focused
- Follow existing patterns in the codebase

## Before Reporting Back: Self-Review

Review your work:
- Did I fully implement all 20 bullish patterns?
- Did I miss any requirements?
- Are tests comprehensive?

## Report Format

When done, report:
- **Status:** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- What you implemented
- What you tested and test results
- Files changed
- Self-review findings
- Any issues or concerns
