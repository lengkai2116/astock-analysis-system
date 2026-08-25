# Task 4 完整提示：黑马型 10 种形态检测器

## Intent (from spec)

**[S1] 形态覆盖度**: 基于 Wiki 50 种量价形态，实现黑马型 10 种形态检测器。

**Scope boundary:** This task covers ONLY implementing the 10 blackhorse pattern detectors. Do NOT implement bullish, bearish, or state detectors (Tasks 2-3, 5 cover those).

## Task Description

**Covers:** [S1] 形态覆盖度

**Files:**
- Create: `backend/app/engine/patterns/detectors/blackhorse_patterns.py`
- Create: `backend/tests/test_blackhorse_patterns.py`

**Interfaces:**
- Consumes: `PatternDetector` 基类 (已由 Task 1 创建)
- Produces: `BlackHorsePatternDetector.detect()` → `List[PatternResult]`

## Context

Task 1 已创建 `PatternDetector` 基类和注册了 50 种形态元数据。现在需要实现具体的检测逻辑。

参考 Wiki《量价狙击》第八章的 10 种黑马型形态定义。

## Implementation Steps

### Step 1: 创建黑马型检测器文件

创建 `backend/app/engine/patterns/detectors/blackhorse_patterns.py`:

```python
"""
黑马型量价形态检测器（10种）
基于《量价狙击》第八章
"""
from typing import List, Optional, Dict
import pandas as pd
import numpy as np

from app.engine.patterns import PatternResult, PatternCategory, PatternStage, PatternLevel
from app.engine.patterns.detectors.base import PatternDetector


class BlackHorsePatternDetector(PatternDetector):
    """黑马型形态检测器"""

    def detect(self, df: pd.DataFrame, context: Optional[Dict] = None) -> List[PatternResult]:
        """检测所有黑马型形态"""
        if df.empty or len(df) < 30:
            return []

        results = []
        detectors = [
            self._p_3_1, self._p_3_2, self._p_3_3, self._p_3_4, self._p_3_5,
            self._p_3_6, self._p_3_7, self._p_3_8, self._p_3_9, self._p_3_10,
        ]

        for detector in detectors:
            try:
                p = detector(df, context)
                if p:
                    results.append(p)
            except Exception:
                continue

        return results

    # TODO: 实现 P-3-1 到 P-3-10 的检测方法
    # 参考计划文件中的具体实现示例
```

### Step 2: 创建测试文件

创建 `backend/tests/test_blackhorse_patterns.py`:

```python
"""测试黑马型形态检测器"""
import pytest
import pandas as pd
import numpy as np

from app.engine.patterns.detectors.blackhorse_patterns import BlackHorsePatternDetector


@pytest.fixture
def sample_df():
    """创建样本K线数据"""
    dates = pd.date_range(start='2025-01-01', periods=150, freq='D')
    np.random.seed(42)

    close = 100 + np.cumsum(np.random.randn(150) * 2)
    open_price = close + np.random.randn(150) * 0.5
    high = np.maximum(close, open_price) + np.abs(np.random.randn(150) * 1)
    low = np.minimum(close, open_price) - np.abs(np.random.randn(150) * 1)
    volume = np.random.randint(1000000, 5000000, 150).astype(float)

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
    detector = BlackHorsePatternDetector()
    assert detector is not None


def test_detect_returns_list(sample_df):
    """测试 detect 返回列表"""
    detector = BlackHorsePatternDetector()
    results = detector.detect(sample_df)
    assert isinstance(results, list)


def test_empty_dataframe():
    """测试空 DataFrame"""
    detector = BlackHorsePatternDetector()
    df = pd.DataFrame()
    results = detector.detect(df)
    assert results == []
```

### Step 3: 运行测试

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统/backend
source .venv/bin/activate
python -m pytest tests/test_blackhorse_patterns.py -v
```

Expected: 全部 PASS

### Step 4: Commit

```bash
git add app/engine/patterns/detectors/blackhorse_patterns.py tests/test_blackhorse_patterns.py
git commit -m "feat(patterns): implement P-3-1 to P-3-4 blackhorse detectors"
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
