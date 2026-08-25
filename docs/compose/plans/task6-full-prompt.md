# Task 6 完整提示：PatternEngine 主入口和聚合算法

## Intent (from spec)

**[S3] 聚合算法**: 实现 Wiki 10 分制聚合算法，统一调度所有检测器。

**Scope boundary:** This task covers ONLY creating PatternEngine and implementing the aggregation algorithm. Do NOT implement caching (Tasks 7-8) or integration (Task 9).

## Task Description

**Covers:** [S3] 聚合算法

**Files:**
- Create: `backend/app/engine/patterns/engine.py`
- Create: `backend/tests/test_pattern_engine.py`

**Interfaces:**
- Consumes: `BullishPatternDetector`, `BearishPatternDetector`, `BlackHorsePatternDetector`, `StateDetector`
- Produces: `PatternEngine.detect_all()`, `PatternEngine.aggregate()`

## Context

Task 2-5 已实现各种形态检测器。现在需要创建主入口统一调度并实现聚合逻辑。

## Implementation Steps

### Step 1: 创建 PatternEngine

创建 `backend/app/engine/patterns/engine.py`:

```python
"""
PatternEngine — 形态评分引擎主入口
==================================
统一调度 50 种形态 + 8 种状态检测器，实现 Wiki 10 分制聚合算法。
"""
from typing import List, Tuple, Dict, Optional
import pandas as pd

from app.engine.patterns import PatternResult
from app.engine.patterns.registry import PatternRegistry
from app.engine.patterns.detectors import (
    BullishPatternDetector,
    BearishPatternDetector,
    BlackHorsePatternDetector,
    StateDetector,
)


# 形态权重映射（基于 Wiki 星级）
WEIGHT_MAP = {
    # 预涨型 ⭐⭐⭐
    'P-1-1': 3.0, 'P-1-2': 3.0, 'P-1-3': 2.0, 'P-1-4': 3.0,
    'P-1-5': 3.0, 'P-1-6': 3.0, 'P-1-7': 3.0, 'P-1-8': 2.0,
    'P-1-9': 2.0, 'P-1-10': 3.0, 'P-1-11': 3.0, 'P-1-12': 2.0,
    'P-1-13': 2.0, 'P-1-14': 2.0, 'P-1-15': 3.0, 'P-1-16': 2.0,
    'P-1-17': 3.0, 'P-1-18': 3.0, 'P-1-19': 2.0, 'P-1-20': 3.0,

    # 预跌型 ⭐⭐⭐
    'P-2-1': 3.0, 'P-2-2': 3.0, 'P-2-3': 2.0, 'P-2-4': 3.0,
    'P-2-5': 3.0, 'P-2-6': 3.0, 'P-2-7': 2.0, 'P-2-8': 3.0,
    'P-2-9': 3.0, 'P-2-10': 2.0, 'P-2-11': 3.0, 'P-2-12': 3.0,
    'P-2-13': 2.0, 'P-2-14': 3.0, 'P-2-15': 2.0, 'P-2-16': 3.0,
    'P-2-17': 3.0, 'P-2-18': 2.0, 'P-2-19': 3.0, 'P-2-20': 3.0,

    # 黑马型 ⭐⭐⭐⭐⭐
    'P-3-1': 5.0, 'P-3-2': 4.0, 'P-3-3': 5.0, 'P-3-4': 4.0,
    'P-3-5': 5.0, 'P-3-6': 4.0, 'P-3-7': 4.0, 'P-3-8': 5.0,
    'P-3-9': 4.0, 'P-3-10': 4.0,

    # 四类八种状态
    'S-1': 2.0, 'S-2': 2.0, 'S-3': 2.5, 'S-4': 2.5,
    'S-5': 3.0, 'S-6': 3.0, 'S-7': 2.0, 'S-8': 2.0,
}


class PatternEngine:
    """
    形态评分引擎

    实现 Wiki 10 分制评分：
    - 基础分 5 分
    - 预涨形态：+权重×strength
    - 预跌形态：-权重×strength
    - 黑马形态：+权重×strength×1.5（高权重）
    - 多形态共振：≥3 个同向形态，额外 ±1 分
    """

    def __init__(self):
        self.registry = PatternRegistry()
        self.bullish_detector = BullishPatternDetector()
        self.bearish_detector = BearishPatternDetector()
        self.blackhorse_detector = BlackHorsePatternDetector()
        self.state_detector = StateDetector()

    def detect_all(self, df: pd.DataFrame, context: Optional[Dict] = None) -> List[PatternResult]:
        """检测所有形态和状态"""
        results = []
        results.extend(self.bullish_detector.detect(df, context))
        results.extend(self.bearish_detector.detect(df, context))
        results.extend(self.blackhorse_detector.detect(df, context))
        results.extend(self.state_detector.detect(df, context))
        return results

    def aggregate(self, patterns: List[PatternResult]) -> Tuple[float, Dict]:
        """聚合形态为 0-10 分"""
        score = 5.0
        bull_count = 0
        bear_count = 0

        for p in patterns:
            weight = WEIGHT_MAP.get(p.name, 1.0)
            if p.direction == 'bullish':
                if p.name.startswith('P-3-'):
                    score += p.strength * weight * 1.5
                else:
                    score += p.strength * weight
                bull_count += 1
            elif p.direction == 'bearish':
                score -= p.strength * weight
                bear_count += 1

        if bull_count >= 3:
            score += 1.0
        if bear_count >= 3:
            score -= 1.0

        final_score = max(0.0, min(10.0, score))
        details = {
            'bull_count': bull_count,
            'bear_count': bear_count,
            'pattern_count': len(patterns),
        }
        return final_score, details

    def evaluate(self, df: pd.DataFrame, context: Optional[Dict] = None) -> Tuple[float, Dict]:
        """一站式评估：检测 + 聚合"""
        patterns = self.detect_all(df, context)
        return self.aggregate(patterns)
```

### Step 2: 创建引擎测试

创建 `backend/tests/test_pattern_engine.py`:

```python
"""测试 PatternEngine"""
import pytest
import pandas as pd
import numpy as np

from app.engine.patterns.engine import PatternEngine


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


def test_engine_initialization():
    """测试引擎初始化"""
    engine = PatternEngine()
    assert engine is not None


def test_detect_all_returns_list(sample_df):
    """测试 detect_all 返回列表"""
    engine = PatternEngine()
    results = engine.detect_all(sample_df)
    assert isinstance(results, list)


def test_aggregate_returns_tuple(sample_df):
    """测试 aggregate 返回元组"""
    engine = PatternEngine()
    patterns = engine.detect_all(sample_df)
    score, details = engine.aggregate(patterns)
    assert isinstance(score, float)
    assert isinstance(details, dict)
    assert 0 <= score <= 10


def test_evaluate_returns_tuple(sample_df):
    """测试 evaluate 返回元组"""
    engine = PatternEngine()
    score, details = engine.evaluate(sample_df)
    assert isinstance(score, float)
    assert isinstance(details, dict)
    assert 0 <= score <= 10


def test_empty_dataframe():
    """测试空 DataFrame"""
    engine = PatternEngine()
    df = pd.DataFrame()
    score, details = engine.evaluate(df)
    assert score == 5.0  # 基础分
    assert details['pattern_count'] == 0
```

### Step 3: 运行测试

```bash
cd /Users/kalence/Desktop/01-A股股票分析系统/backend
source .venv/bin/activate
python -m pytest tests/test_pattern_engine.py -v
```

Expected: 全部 PASS

### Step 4: Commit

```bash
git add app/engine/patterns/engine.py tests/test_pattern_engine.py
git commit -m "feat(patterns): create PatternEngine with Wiki 10-point aggregation"
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
