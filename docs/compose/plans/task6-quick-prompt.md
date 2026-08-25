# Task 6 实现提示：PatternEngine 主入口和聚合算法

## Intent
**[S3] 聚合算法**: 实现 Wiki 10 分制聚合算法，统一调度所有检测器。

## Task Description
创建 `PatternEngine` 类，统一调度所有检测器并实现聚合算法。

## Files
- Create: `backend/app/engine/patterns/engine.py`
- Create: `backend/tests/test_pattern_engine.py`

## 实现要点

### 1. 创建 PatternEngine 类
```python
from app.engine.patterns.detectors import (
    BullishPatternDetector,
    BearishPatternDetector,
    BlackHorsePatternDetector,
    StateDetector,
)

class PatternEngine:
    def __init__(self):
        self.bullish_detector = BullishPatternDetector()
        self.bearish_detector = BearishPatternDetector()
        self.blackhorse_detector = BlackHorsePatternDetector()
        self.state_detector = StateDetector()

    def detect_all(self, df, context=None):
        results = []
        results.extend(self.bullish_detector.detect(df, context))
        results.extend(self.bearish_detector.detect(df, context))
        results.extend(self.blackhorse_detector.detect(df, context))
        results.extend(self.state_detector.detect(df, context))
        return results

    def aggregate(self, patterns):
        # Wiki 10 分制聚合算法
        score = 5.0
        # ... 实现聚合逻辑
        return final_score, details

    def evaluate(self, df, context=None):
        patterns = self.detect_all(df, context)
        return self.aggregate(patterns)
```

### 2. 权重映射
- 预涨型：3.0（⭐⭐⭐）
- 预跌型：3.0（⭐⭐⭐）
- 黑马型：5.0（⭐⭐⭐⭐⭐）
- 状态：2.0-3.0

### 3. 聚合算法
- 基础分 5 分
- 预涨形态：+权重×strength
- 预跌形态：-权重×strength
- 黑马形态：+权重×strength×1.5
- 多形态共振：≥3 个同向形态，额外 ±1 分

## Commit
```bash
git add app/engine/patterns/engine.py tests/test_pattern_engine.py
git commit -m "feat(patterns): create PatternEngine with Wiki 10-point aggregation"
```
