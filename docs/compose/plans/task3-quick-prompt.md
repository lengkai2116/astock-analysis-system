# Task 3 实现提示：预跌型 20 种形态检测器

## Intent
**[S1] 形态覆盖度**: 基于 Wiki 50 种量价形态，实现预跌型 20 种形态检测器。

## Task Description
实现 `BearishPatternDetector` 类，检测 20 种预跌型形态。

## Files
- Create: `backend/app/engine/patterns/detectors/bearish_patterns.py`
- Create: `backend/tests/test_bearish_patterns.py`

## 实现要点

### 1. 继承 PatternDetector
```python
from app.engine.patterns.detectors.base import PatternDetector

class BearishPatternDetector(PatternDetector):
    def detect(self, df, context=None):
        # 实现检测逻辑
        pass
```

### 2. 实现 20 种检测方法
- `_p_2_1` 到 `_p_2_20`
- 每个方法返回 `Optional[PatternResult]`

### 3. 测试要求
- 初始化测试
- 返回列表测试
- 空数据测试
- 数据不足测试

## Commit
```bash
git add app/engine/patterns/detectors/bearish_patterns.py tests/test_bearish_patterns.py
git commit -m "feat(patterns): implement bearish pattern detectors"
```
