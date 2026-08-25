# Task 5 完整提示：四类八种状态检测器

## Intent (from spec)

**[S2] 动态状态感知**: 基于 Wiki 四类八种量价状态，实现状态检测器。

**Scope boundary:** This task covers ONLY implementing the 8 state detectors. Do NOT implement bullish, bearish, or blackhorse detectors (Tasks 2-4 cover those).

## Task Description

**Covers:** [S2] 动态状态感知

**Files:**
- Create: `backend/app/engine/patterns/detectors/state_detectors.py`
- Create: `backend/tests/test_state_detectors.py`

**Interfaces:**
- Consumes: `PatternDetector` 基类 (已由 Task 1 创建)
- Produces: `StateDetector.detect()` → `List[PatternResult]`

## Context

Task 1 已创建 `PatternDetector` 基类和注册了 8 种状态元数据。现在需要实现具体的检测逻辑。

参考 Wiki 动态量价状态感知策略的四类八种状态定义。

## 四类八种状态

1. **健康动量**
   - S-1: 价涨量增（收盘价>前收盘价 且 成交量>20日均量×1.2）
   - S-2: 价跌量缩（收盘价<前收盘价 且 成交量<20日均量×0.8）

2. **背离预警**
   - S-3: 价涨量缩（收盘价创新高 但 成交量连续3日低于均量）
   - S-4: 价跌量增（收盘价新低 但 成交量连续放大）

3. **极端信号**
   - S-5: 天量天价（成交量创60日新高 且 价格创20日新高）
   - S-6: 地量地价（成交量创60日新低 且 价格创20日新低）

4. **筹码转换**
   - S-7: 放量突破（股价突破关键均线 且 放量）
   - S-8: 缩量回踩（股价回踩不破关键均线 且 大幅缩量）

## Implementation Steps

### Step 1: 创建状态检测器文件

创建 `backend/app/engine/patterns/detectors/state_detectors.py`:

```python
"""
四类八种量价状态检测器
基于 Wiki 动态量价状态感知策略
"""
from typing import List, Optional, Dict
import pandas as pd
import numpy as np

from app.engine.patterns import PatternResult, PatternCategory, PatternStage, PatternLevel
from app.engine.patterns.detectors.base import PatternDetector


class StateDetector(PatternDetector):
    """四类八种状态检测器"""

    def detect(self, df: pd.DataFrame, context: Optional[Dict] = None) -> List[PatternResult]:
        """检测所有状态"""
        if df.empty or len(df) < 20:
            return []

        results = []
        detectors = [
            self._s_1, self._s_2, self._s_3, self._s_4,
            self._s_5, self._s_6, self._s_7, self._s_8,
        ]

        for detector in detectors:
            try:
                p = detector(df, context)
                if p:
                    results.append(p)
            except Exception:
                continue

        return results

    # TODO: 实现 S-1 到 S-8 的检测方法
    # 参考计划文件中的具体实现示例
```

### Step 2: 创建测试文件

创建 `backend/tests/test_state_detectors.py`:

```python
"""测试四类八种状态检测器"""
import pytest
import pandas as pd
import numpy as np

from app.engine.patterns.detectors.state_detectors import StateDetector


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
    detector = StateDetector()
    assert detector is not None


def test_detect_returns_list(sample_df):
    """测试 detect 返回列表"""
    detector = StateDetector()
    results = detector.detect(sample_df)
    assert isinstance(results, list)


def test_empty_dataframe():
    """测试空 DataFrame"""
    detector = StateDetector()
    df = pd.DataFrame()
    results = detector.detect(df)
    assert results == []
```

### Step 3: 运行测试

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统/backend
source .venv/bin/activate
python -m pytest tests/test_state_detectors.py -v
```

Expected: 全部 PASS

### Step 4: Commit

```bash
git add app/engine/patterns/detectors/state_detectors.py tests/test_state_detectors.py
git commit -m "feat(patterns): implement S-1 to S-4 state detectors"
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
