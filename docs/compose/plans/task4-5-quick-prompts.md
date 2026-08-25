# Task 4-5 实现提示

## Task 4: 黑马型 10 种形态检测器

### Intent
**[S1] 形态覆盖度**: 基于 Wiki 50 种量价形态，实现黑马型 10 种形态检测器。

### Files
- Create: `backend/app/engine/patterns/detectors/blackhorse_patterns.py`
- Create: `backend/tests/test_blackhorse_patterns.py`

### 实现要点
1. 继承 `PatternDetector`
2. 实现 10 种检测方法：`_p_3_1` 到 `_p_3_10`
3. 参考《量价狙击》第八章

---

## Task 5: 四类八种状态检测器

### Intent
**[S2] 动态状态感知**: 基于 Wiki 四类八种量价状态，实现状态检测器。

### Files
- Create: `backend/app/engine/patterns/detectors/state_detectors.py`
- Create: `backend/tests/test_state_detectors.py`

### 实现要点
1. 继承 `PatternDetector`
2. 实现 8 种状态检测方法：`_s_1` 到 `_s_8`
3. 四类八种状态：
   - 健康动量：价涨量增、价跌量缩
   - 背离预警：价涨量缩、价跌量增
   - 极端信号：天量天价、地量地价
   - 筹码转换：放量突破、缩量回踩

### Commit
```bash
git add app/engine/patterns/detectors/blackhorse_patterns.py tests/test_blackhorse_patterns.py
git commit -m "feat(patterns): implement blackhorse pattern detectors"

git add app/engine/patterns/detectors/state_detectors.py tests/test_state_detectors.py
git commit -m "feat(patterns): implement state detectors"
```
