# Task 3 完整提示：预跌型 20 种形态检测器

## Intent (from spec)

**[S1] 形态覆盖度**: 基于 Wiki 50 种量价形态，实现预跌型 20 种形态检测器。

**Scope boundary:** This task covers ONLY implementing the 20 bearish pattern detectors. Do NOT implement bullish, blackhorse, or state detectors (Tasks 2, 4-5 cover those).

## Task Description

**Covers:** [S1] 形态覆盖度

**Files:**
- Create: `backend/app/engine/patterns/detectors/bearish_patterns.py`
- Create: `backend/tests/test_bearish_patterns.py`

**Interfaces:**
- Consumes: `PatternDetector` 基类 (已由 Task 1 创建)
- Produces: `BearishPatternDetector.detect()` → `List[PatternResult]`

## Context

Task 1 已创建 `PatternDetector` 基类和注册了 50 种形态元数据。现在需要实现具体的检测逻辑。

参考 Wiki《量价狙击》第七章的 20 种预跌型形态定义。

## Implementation Steps

### Step 1: 创建预跌型检测器文件

创建 `backend/app/engine/patterns/detectors/bearish_patterns.py`:

```python
"""
预跌型量价形态检测器（20种）
基于《量价狙击》第七章
"""
from typing import List, Optional, Dict
import pandas as pd
import numpy as np

from app.engine.patterns import PatternResult, PatternCategory, PatternStage, PatternLevel
from app.engine.patterns.detectors.base import PatternDetector


class BearishPatternDetector(PatternDetector):
    """预跌型形态检测器"""

    def detect(self, df: pd.DataFrame, context: Optional[Dict] = None) -> List[PatternResult]:
        """检测所有预跌型形态"""
        if df.empty or len(df) < 20:
            return []

        results = []
        detectors = [
            self._p_2_1, self._p_2_2, self._p_2_3, self._p_2_4, self._p_2_5,
            self._p_2_6, self._p_2_7, self._p_2_8, self._p_2_9, self._p_2_10,
            self._p_2_11, self._p_2_12, self._p_2_13, self._p_2_14, self._p_2_15,
            self._p_2_16, self._p_2_17, self._p_2_18, self._p_2_19, self._p_2_20,
        ]

        for detector in detectors:
            try:
                p = detector(df, context)
                if p:
                    results.append(p)
            except Exception:
                continue

        return results

    # TODO: 实现 P-2-1 到 P-2-20 的检测方法
    # 参考计划文件中的具体实现示例
```

### Step 2: 创建测试文件

创建 `backend/tests/test_bearish_patterns.py`:

```python
"""测试预跌型形态检测器"""
import pytest
import pandas as pd
import numpy as np

from app.engine.patterns.detectors.bearish_patterns import BearishPatternDetector


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
    detector = BearishPatternDetector()
    assert detector is not None


def test_detect_returns_list(sample_df):
    """测试 detect 返回列表"""
    detector = BearishPatternDetector()
    results = detector.detect(sample_df)
    assert isinstance(results, list)


def test_empty_dataframe():
    """测试空 DataFrame"""
    detector = BearishPatternDetector()
    df = pd.DataFrame()
    results = detector.detect(df)
    assert results == []
```

### Step 3: 运行测试

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统/backend
source .venv/bin/activate
python -m pytest tests/test_bearish_patterns.py -v
```

Expected: 全部 PASS

### Step 4: Commit

```bash
git add app/engine/patterns/detectors/bearish_patterns.py tests/test_bearish_patterns.py
git commit -m "feat(patterns): implement P-2-1 to P-2-6 bearish detectors"
```

## Your Job

1. Implement exactly what the task specifies
2. Write tests (following TDD)
3. Verify implementation works
4. Commit your work
5. Self-review
6. Report back

## Report Format

When done, report:
- **Status:** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- What you implemented
- What you tested and test results
- Files changed
- Self-review findings
- Any issues or concerns
